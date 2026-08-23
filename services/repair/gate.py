"""Verification-gated completion and failure-aware repair feedback."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from core.runtime_state import RuntimeState
from services.attachments.types import AttachmentMessage
from services.observability import TraceRecorder
from services.repair.fingerprint import fingerprint_failure
from services.repair.parser import FailureParser
from services.repair.policy import RepairLoopPolicy
from services.repair.retriever import RepositoryRetriever
from services.repair.types import RepairContextBundle, VerificationReport
from services.verification import VerificationCommand
from services.verification.executor import VerificationExecutor, parse_verification_commands
from utils.toolResultStorage import ToolResultStorage


@dataclass(frozen=True)
class FinishDecision:
    outcome: Literal["pass", "continue", "blocked", "exhausted"]
    message: str = ""
    attachment: dict[str, Any] | None = None
    report: VerificationReport | None = None


class RepairLoopGate:
    """Runs local checks and turns failures into bounded repair context."""

    def __init__(self, workspace: Path, *, result_store: ToolResultStorage, trace_recorder: TraceRecorder | None = None, max_attempts: int = 3, timeout_seconds: float = 120.0, executor: VerificationExecutor | None = None, policy: RepairLoopPolicy | None = None) -> None:
        self.workspace = workspace.resolve()
        self.result_store = result_store
        self.trace_recorder = trace_recorder or TraceRecorder.noop()
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.executor = executor or VerificationExecutor(
            self.workspace,
            result_store=result_store,
            trace_recorder=self.trace_recorder,
            timeout_seconds=timeout_seconds,
        )
        self.policy = policy or RepairLoopPolicy()
        self.parser = FailureParser()
        self.retriever = RepositoryRetriever(self.workspace)

    def bind_result_store(self, result_store: ToolResultStorage) -> None:
        self.result_store = result_store
        self.executor.bind_result_store(result_store)

    async def evaluate(self, state: RuntimeState, *, final_text: str, assistant_message: dict[str, Any] | None) -> FinishDecision:
        del final_text, assistant_message
        changed_files = tuple(str(item) for item in state.metadata.get("files_changed", ()) if isinstance(item, str))
        if not changed_files:
            return FinishDecision("pass", "No repository files changed; verification gate skipped.")
        attempt = int(state.metadata.get("repair_attempts", 0)) + 1
        commands = self._commands()
        if not commands:
            return FinishDecision("blocked", "Verification is required after edits, but no verification command is configured.")
        report = await self.executor.execute(commands, attempt=attempt)
        state.metadata["last_verification"] = {"status": report.status, "outcome": report.outcome, "fingerprint": report.fingerprint, "artifact_path": report.artifact_path}
        if report.status == "passed":
            state.metadata["repair_attempts"] = attempt
            self.trace_recorder.event("verification_passed", {"attempt": attempt, "checks": len(report.checks)})
            return FinishDecision("pass", "Verification passed.", report=report)
        if report.outcome != "test_failed":
            self.trace_recorder.event("verification_blocked", {"attempt": attempt, "outcome": report.outcome})
            return FinishDecision("blocked", f"Verification could not run ({report.outcome}); inspect the stored output.", report=report)
        state.metadata["repair_attempts"] = attempt
        evidence = self.parser.parse("\n".join(check.output for check in report.checks)) if self.policy.enable_failure_parser else ()
        report = VerificationReport(report.status, report.checks, fingerprint_failure(evidence, outcome=report.outcome), report.artifact_path, report.outcome)
        state.metadata["last_verification"]["fingerprint"] = report.fingerprint
        previous = state.metadata.get("last_failure_fingerprint")
        repeats = int(state.metadata.get("same_failure_repeats", 0)) + 1 if previous == report.fingerprint else 1
        state.metadata["last_failure_fingerprint"] = report.fingerprint
        state.metadata["same_failure_repeats"] = repeats
        if attempt >= self.max_attempts or repeats >= 2:
            self.trace_recorder.event("repair_exhausted", {"attempt": attempt, "same_failure_repeats": repeats})
            return FinishDecision("exhausted", "Verification failed repeatedly; repair budget exhausted.", report=report)
        snippets = self.retriever.retrieve(evidence, changed_files) if self.policy.enable_repository_retrieval else ()
        bundle = RepairContextBundle(attempt, report, evidence, snippets, changed_files)
        attachment = AttachmentMessage(self._attachment_payload(bundle), source="repair_loop").to_message()
        self.trace_recorder.event("verification_failed", {"attempt": attempt, "evidence_count": len(evidence), "snippet_count": len(snippets)})
        return FinishDecision("continue", "Verification failed; repair context added.", attachment=attachment, report=report)

    def _commands(self) -> tuple[VerificationCommand, ...]:
        settings = self.workspace / ".onecode" / "settings.json"
        try:
            payload = json.loads(settings.read_text(encoding="utf-8"))
            commands = parse_verification_commands(payload.get("verification", {}).get("commands", []))
            if commands:
                return commands
        except (OSError, ValueError, AttributeError):
            pass
        return (VerificationCommand("uv run python -m pytest tests -q", ("uv", "run", "python", "-m", "pytest", "tests", "-q")),) if (self.workspace / "tests").is_dir() else ()

    @staticmethod
    def _attachment_payload(bundle: RepairContextBundle) -> dict[str, Any]:
        return {"type": "repair_feedback", "attempt": bundle.attempt, "status": bundle.report.status, "artifact_path": bundle.report.artifact_path, "changed_files": list(bundle.changed_files), "evidence": [item.__dict__ for item in bundle.evidence], "snippets": [item.__dict__ for item in bundle.snippets], "output_preview": "\n".join(check.output for check in bundle.report.checks)[:4000]}
