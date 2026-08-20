"""Verification-gated completion and failure-aware repair feedback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Literal

from core.runtime_state import RuntimeState
from services.attachments.types import AttachmentMessage
from services.observability import TraceRecorder
from services.repair.parser import FailureParser
from services.repair.retriever import RepositoryRetriever
from services.repair.types import CheckResult, RepairContextBundle, VerificationReport
from utils.toolResultStorage import ToolResultStorage


@dataclass(frozen=True)
class FinishDecision:
    outcome: Literal["pass", "continue", "blocked", "exhausted"]
    message: str = ""
    attachment: dict[str, Any] | None = None
    report: VerificationReport | None = None


class RepairLoopGate:
    """Runs local checks and turns failures into bounded repair context."""

    def __init__(self, workspace: Path, *, result_store: ToolResultStorage, trace_recorder: TraceRecorder | None = None, max_attempts: int = 3, timeout_seconds: float = 120.0) -> None:
        self.workspace = workspace.resolve()
        self.result_store = result_store
        self.trace_recorder = trace_recorder or TraceRecorder.noop()
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.parser = FailureParser()
        self.retriever = RepositoryRetriever(self.workspace)

    def bind_result_store(self, result_store: ToolResultStorage) -> None:
        self.result_store = result_store

    async def evaluate(self, state: RuntimeState, *, final_text: str, assistant_message: dict[str, Any] | None) -> FinishDecision:
        del final_text, assistant_message
        changed_files = tuple(str(item) for item in state.metadata.get("files_changed", ()) if isinstance(item, str))
        if not changed_files:
            return FinishDecision("pass", "No repository files changed; verification gate skipped.")
        attempt = int(state.metadata.get("repair_attempts", 0)) + 1
        commands = self._commands()
        if not commands:
            return FinishDecision("blocked", "Verification is required after edits, but no verification command is configured.")
        report = await self._verify(commands, attempt)
        state.metadata["last_verification"] = {"status": report.status, "fingerprint": report.fingerprint, "artifact_path": report.artifact_path}
        if report.status == "passed":
            state.metadata["repair_attempts"] = attempt
            self.trace_recorder.event("verification_passed", {"attempt": attempt, "checks": len(report.checks)})
            return FinishDecision("pass", "Verification passed.", report=report)
        if report.status == "blocked":
            self.trace_recorder.event("verification_blocked", {"attempt": attempt})
            return FinishDecision("blocked", "Verification could not run; inspect the stored output.", report=report)
        state.metadata["repair_attempts"] = attempt
        previous = state.metadata.get("last_failure_fingerprint")
        repeats = int(state.metadata.get("same_failure_repeats", 0)) + 1 if previous == report.fingerprint else 1
        state.metadata["last_failure_fingerprint"] = report.fingerprint
        state.metadata["same_failure_repeats"] = repeats
        if attempt >= self.max_attempts or repeats >= 2:
            self.trace_recorder.event("repair_exhausted", {"attempt": attempt, "same_failure_repeats": repeats})
            return FinishDecision("exhausted", "Verification failed repeatedly; repair budget exhausted.", report=report)
        evidence = self.parser.parse("\n".join(check.output for check in report.checks))
        snippets = self.retriever.retrieve(evidence, changed_files)
        bundle = RepairContextBundle(attempt, report, evidence, snippets, changed_files)
        attachment = AttachmentMessage(self._attachment_payload(bundle), source="repair_loop").to_message()
        self.trace_recorder.event("verification_failed", {"attempt": attempt, "evidence_count": len(evidence), "snippet_count": len(snippets)})
        return FinishDecision("continue", "Verification failed; repair context added.", attachment=attachment, report=report)

    def _commands(self) -> tuple[str, ...]:
        settings = self.workspace / ".onecode" / "settings.json"
        try:
            payload = json.loads(settings.read_text(encoding="utf-8"))
            commands = payload.get("verification", {}).get("commands", [])
            if isinstance(commands, list) and all(isinstance(item, str) and item.strip() for item in commands):
                return tuple(commands)
        except (OSError, ValueError, AttributeError):
            pass
        return ("uv run python -m pytest tests -q",) if (self.workspace / "tests").is_dir() else ()

    async def _verify(self, commands: tuple[str, ...], attempt: int) -> VerificationReport:
        checks: list[CheckResult] = []
        for command in commands:
            started = time.monotonic()
            try:
                process = await asyncio.create_subprocess_shell(command, cwd=self.workspace, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
                output = stdout.decode("utf-8", errors="replace")
                status: Literal["passed", "failed"] = "passed" if process.returncode == 0 else "failed"
                checks.append(CheckResult(command, process.returncode, output, int((time.monotonic() - started) * 1000), status))
            except (OSError, asyncio.TimeoutError) as exc:
                checks.append(CheckResult(command, None, str(exc), int((time.monotonic() - started) * 1000), "blocked"))
        full_output = "\n\n".join(f"$ {check.command}\n{check.output}" for check in checks)
        ref = self.result_store.persist_tool_result(tool_call_id=f"verification-{attempt}", tool_name="verification", content=full_output)
        status: Literal["passed", "failed", "blocked"] = "blocked" if any(check.status == "blocked" for check in checks) else ("failed" if any(check.status == "failed" for check in checks) else "passed")
        fingerprint = hashlib.sha256((status + "\n" + full_output).encode("utf-8")).hexdigest()[:16]
        return VerificationReport(status, tuple(checks), fingerprint, str(ref.absolute_path))

    @staticmethod
    def _attachment_payload(bundle: RepairContextBundle) -> dict[str, Any]:
        return {"type": "repair_feedback", "attempt": bundle.attempt, "status": bundle.report.status, "artifact_path": bundle.report.artifact_path, "changed_files": list(bundle.changed_files), "evidence": [item.__dict__ for item in bundle.evidence], "snippets": [item.__dict__ for item in bundle.snippets], "output_preview": "\n".join(check.output for check in bundle.report.checks)[:4000]}
