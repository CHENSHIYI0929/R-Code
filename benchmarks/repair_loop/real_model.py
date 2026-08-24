"""Real-provider adapter for the executable benchmark runtime.

This module deliberately owns no agent behaviour.  It swaps the deterministic
model used by :mod:`runtime_adapter` for a configured ``ModelClient`` while
retaining the production loop, tools, guard, repair gate, verifier, trace and
transcript implementations.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import time
from typing import Any, Callable

from benchmarks.repair_loop.contracts import CaseContract, EvaluationTier
from benchmarks.repair_loop.runtime_adapter import _collect, _record, _runtime
from benchmarks.repair_loop.types import BenchmarkRun
from core.runtime_state import RuntimeState
from core.transitions import TransitionReason
from infrastructure.config.env import ResolvedProviderConfig
from infrastructure.providers.factory import resolve_config
from infrastructure.providers.http import HttpxAsyncHttpTransport
from benchmarks.repair_loop.provider_smoke import BoundedSmokeClient
from services.model.types import ProviderError
from services.context.message_store import MessageStore
from services.context.transcript import JsonlTranscriptStore
from services.model.client import ModelClient
from ui.cli.resume import restore_session_state


class RealModelAdapter:
    """Run frozen benchmark contracts with one fixed real provider config."""

    def __init__(
        self,
        env_path: str | Path = ".env",
        *,
        artifact_root: Path | None = None,
        model_factory: Callable[[], ModelClient] | None = None,
        max_model_calls: int = 12,
        max_tool_steps: int = 12,
        max_wall_clock_seconds: float = 180,
    ) -> None:
        self.env_path = Path(env_path)
        self.config: ResolvedProviderConfig = resolve_config(self.env_path)
        self.artifact_root = artifact_root
        self.max_tool_steps = max_tool_steps
        self.max_wall_clock_seconds = max_wall_clock_seconds
        def default_model() -> ModelClient:
            client = BoundedSmokeClient(self.config, async_transport=HttpxAsyncHttpTransport(provider_id=self.config.provider_id), mode="stream", call_timeout_seconds=25)
            client.max_model_calls = max_model_calls
            return client
        self._model_factory = model_factory or default_model

    @property
    def model_label(self) -> str:
        return f"{self.config.provider_id}/{self.config.model}"

    @property
    def decoding_params(self) -> dict[str, Any]:
        return dict(self.config.default_params)

    async def __call__(self, case: CaseContract, profile: str, workspace: Path, tier: EvaluationTier) -> BenchmarkRun:
        if tier != "real_model":
            raise ValueError("RealModelAdapter only supports real_model tier")
        if case.experiment == "repair_loop":
            record = await self._repair(case, profile, workspace)
        elif case.experiment == "harness_regression":
            record = await self._harness(case, profile, workspace)
        elif case.experiment == "context_compaction":
            record = await self._context(case, profile, workspace)
        elif case.experiment == "session_memory":
            record = await self._memory(case, profile, workspace)
        elif case.experiment == "resume_recovery":
            record = await self._recovery(case, profile, workspace)
        else:
            raise ValueError(f"real-model evaluation is not defined for {case.experiment}")
        self._archive(workspace, record)
        return record

    async def _repair(self, case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
        state, store, trace, errors, loop, _memory = _runtime(
            workspace, self._model_factory(), repair_profile=None if profile == "baseline" else profile
        )
        prompt = (
            "Repair the failing test in the known fixture layout: inspect src/sample.py "
            "and tests/test_sample.py, then edit only src/sample.py. After the necessary "
            "edit, respond with the final answer immediately; do not self-check by re-reading "
            "because the runtime verifier decides correctness."
        )
        events, elapsed = await _timed_collect(loop, prompt, max_tool_steps=self.max_tool_steps, max_wall_clock_seconds=self.max_wall_clock_seconds)
        verified = state.last_transition == TransitionReason.COMPLETED_VERIFIED
        resolved = "return 200" in (workspace / "src" / "sample.py").read_text(encoding="utf-8")
        outcome = state.metadata.get("last_verification")
        failure = None if verified else _repair_failure(state, outcome, profile)
        return _record(case, profile, state, store, trace, errors, events, elapsed, success=verified, resolved=resolved, failure_kind=failure, tier="real_model")

    async def _harness(self, case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
        state, store, trace, errors, loop, _memory = _runtime(workspace, self._model_factory())
        prompt = (
            "Call read_file for src/a.py exactly once, then report its value."
            if case.id.endswith("tool")
            else "Attempt write_file once at ../outside.txt with content 'no', then report the tool result."
        )
        events, elapsed = await _timed_collect(loop, prompt)
        results = [message for message in store.current_messages() if message.get("role") == "tool_result"]
        denied = bool(results and results[-1].get("is_error"))
        expected_denial = not case.id.endswith("tool")
        benchmark_error = state.metadata.get("benchmark_error")
        ok = bool(results) and denied == expected_denial and benchmark_error is None
        failure = None if ok else (benchmark_error if isinstance(benchmark_error, str) else ("policy_denied" if expected_denial else "runtime_error"))
        return _record(case, profile, state, store, trace, errors, events, elapsed, success=ok, resolved=ok, failure_kind=failure, tier="real_model", extra={"runtime_correct": ok, "tool_correct": ok, "hook_correct": True, "budget_respected": True, "recovery_steps": 0, "security_boundary": denied == expected_denial})

    async def _context(self, case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
        from services.compaction import CompactionConfig, ContextCompactionService

        compaction = ContextCompactionService(config=CompactionConfig(snip_max_messages=3, microcompact_keep_recent=2))
        state, store, trace, errors, loop, _memory = _runtime(workspace, self._model_factory(), compaction=compaction)
        for index in range(5):
            store.append_user(f"old context {index}: " + ("x" * 500))
        store.append_user("critical fact: port 8123")
        events, elapsed = await _timed_collect(loop, "What is the critical port? Answer with the number only.")
        final = _final_text(events)
        info = state.metadata.get("last_compaction", {})
        before, after = int(info.get("token_before", 0)), int(info.get("token_after", 0))
        retained = "8123" in final
        return _record(case, profile, state, store, trace, errors, events, elapsed, success=retained, resolved=retained, failure_kind=None if retained else "key_fact_lost", tier="real_model", extra={"compression_ratio": round(after / before, 4) if before else 1.0, "prompt_tokens": after, "key_fact_retention": retained, "task_success": retained})

    async def _memory(self, case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
        state, store, trace, errors, loop, _memory = _runtime(workspace, self._model_factory())
        initial, first_elapsed = await _timed_collect(loop, "Read src/config.py with read_file and state the configured port.")
        if profile == "memory_stale":
            target = workspace / "src" / "config.py"
            target.write_text("PORT = 9000\n", encoding="utf-8")
        followup = (
            "For this audit, call read_file on src/config.py again, then give the current port."
            if profile == "memory_off" else "Give the current configured port. Use read_file if the previous observation is not sufficient."
        )
        later, second_elapsed = await _timed_collect(loop, followup)
        final = _final_text(later)
        reads = sum(1 for item in store.current_messages() if item.get("role") == "tool_result" and item.get("tool_name") == "read_file")
        stale = profile == "memory_stale" and "8123" in final
        expected = "9000" if profile == "memory_stale" else "8123"
        success = expected in final and not stale
        return _record(case, profile, state, store, trace, errors, [*initial, *later], first_elapsed + second_elapsed, success=success, resolved=success, failure_kind=None if success else ("stale_memory" if stale else "memory_missing"), tier="real_model", extra={"repeated_file_reads": reads, "task_success": success, "fact_recall": expected in final, "stale_injection": stale})

    async def _recovery(self, case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
        state, store, trace, errors, loop, _memory = _runtime(workspace, self._model_factory())
        initial, elapsed = await _timed_collect(loop, "Read src/state.py and report the version.")
        store.flush_transcript()
        target = workspace / "src" / "state.py"
        if profile == "file_deleted":
            target.unlink()
        elif profile != "normal":
            target.write_text("VERSION = 2\n", encoding="utf-8")
        restored_state = RuntimeState(session_id=state.session_id)
        restored_store = MessageStore.from_transcript(JsonlTranscriptStore(store.transcript_store.session_dir.parent, state.session_id, cwd=workspace), restored_state)
        restore_session_state(restored_state, restored_store.current_messages(), message_store=restored_store)
        _state, _store, resumed_trace, resumed_errors, resumed_loop, _memory = _runtime(workspace, self._model_factory(), state=restored_state, store=restored_store)
        resumed, resumed_elapsed = await _timed_collect(resumed_loop, "Report the current state. Re-read src/state.py before relying on any historical read if it is stale or missing.")
        final = _final_text(resumed)
        changed = profile != "normal"
        expected = "VERSION = 1" if profile == "normal" else ("missing" if profile == "file_deleted" else "VERSION = 2")
        stale_reuse = changed and "VERSION = 1" in final
        success = expected.lower() in final.lower() and not stale_reuse
        failure = None if success else ("missing_file" if profile == "file_deleted" else "workspace_changed")
        return _record(case, profile, restored_state, restored_store, resumed_trace, resumed_errors, [*initial, *resumed], elapsed + resumed_elapsed, success=success, resolved=success, failure_kind=failure, tier="real_model", extra={"resume_success": bool(restored_store.current_messages()), "stale_reuse": stale_reuse, "recovery_steps": sum(1 for event in resumed if event.type == "tool_result")})

    def _archive(self, workspace: Path, record: BenchmarkRun) -> None:
        if self.artifact_root is None:
            return
        destination = self.artifact_root / record.experiment / record.case_id / record.profile / str(time.time_ns())
        destination.mkdir(parents=True, exist_ok=False)
        session_dir = workspace / ".onecode"
        if session_dir.exists():
            shutil.copytree(session_dir, destination / ".onecode")
        (destination / "record.json").write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def _timed_collect(loop: Any, prompt: str, *, max_tool_steps: int = 12, max_wall_clock_seconds: float = 180) -> tuple[list[Any], int]:
    started = time.perf_counter()
    events: list[Any] = []
    try:
        async with asyncio.timeout(max_wall_clock_seconds):
            async for event in loop.stream(prompt):
                events.append(event)
                if sum(item.type == "tool_result" for item in events) > max_tool_steps:
                    raise ProviderError("Benchmark tool budget exceeded.", error_type="tool_budget_exceeded")
    except TimeoutError:
        loop.state.metadata["benchmark_error"] = "wall_clock_budget_exceeded"
    except ProviderError as exc:
        loop.state.metadata["benchmark_error"] = {"timeout_error": "provider_timeout"}.get(exc.error_type or "", exc.error_type or "provider_error")
    return events, round((time.perf_counter() - started) * 1000)


def _final_text(events: list[Any]) -> str:
    completed = next((event for event in reversed(events) if event.type == "completed"), None)
    return completed.text if completed is not None else ""


def _repair_failure(state: RuntimeState, outcome: object, profile: str) -> str:
    if isinstance(state.metadata.get("benchmark_error"), str):
        return state.metadata["benchmark_error"]
    if profile == "baseline":
        return "verification_skipped"
    if state.last_transition == TransitionReason.REPAIR_EXHAUSTED:
        return "repair_exhausted"
    if isinstance(outcome, dict) and isinstance(outcome.get("outcome"), str):
        candidate = str(outcome["outcome"])
        if candidate in {"test_failed", "command_missing", "environment_blocked", "timeout", "repair_exhausted"}:
            return candidate
    return "environment_blocked"
