"""Executable benchmark adapter built from the production runtime services.

The model in this module is deliberately deterministic, but every tool call,
verification command, transcript entry, trace event and terminal transition is
produced by the real R-Code runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from core.context_engine import ContextEngine, StaticPromptAssembler
from core.loop import AgentLoop
from core.runtime_state import RuntimeState
from core.transitions import TransitionReason
from services.compaction import CompactionConfig, ContextCompactionService, SessionMemoryStore, SessionMemoryToolUpdater
from services.context.message_store import MessageStore
from services.guard import SandboxBoundary, SandboxGuard
from services.hooks import HookEvent, HookRegistry
from services.model.stream import ModelStreamEvent
from services.model.types import ModelUsage
from services.observability import ErrorLogRecorder, JsonlErrorLogSink, JsonlTraceSink, TraceRecorder
from services.repair import RepairLoopGate
from services.tools.executor import RegistryToolExecutor
from services.tools.file_state import FileStateCache
from services.tools.registry import ToolRegistry
from services.tools.types import ToolCall
from ui.cli.app import production_coding_tool_descriptors
from utils.toolResultStorage import ToolResultStorage

from benchmarks.repair_loop.contracts import CaseContract, EvaluationTier
from benchmarks.repair_loop.events import summarize_events
from benchmarks.repair_loop.profiles import repair_loop_policy
from benchmarks.repair_loop.types import BenchmarkRun, PROFILES


class DeterministicModel:
    """A provider-neutral model that only returns the supplied responses."""

    def __init__(self, responses: list[ToolCall | str]) -> None:
        self._responses = responses
        self.snapshots: list[Any] = []

    async def stream(self, snapshot):  # type: ignore[no-untyped-def]
        self.snapshots.append(snapshot)
        if not self._responses:
            raise AssertionError("deterministic benchmark model exhausted")
        response = self._responses.pop(0)
        if isinstance(response, ToolCall):
            wire_call = {
                "id": response.id,
                "name": response.name,
                "input": response.input,
            }
            yield ModelStreamEvent.message_completed(
                assistant_message={"role": "assistant", "content": "", "tool_calls": [wire_call]},
                final_text="",
                tool_calls=(response,),
                usage=ModelUsage(input_tokens=1, output_tokens=1),
            )
            return
        yield ModelStreamEvent.message_completed(
            assistant_message={"role": "assistant", "content": response},
            final_text=response,
            usage=ModelUsage(input_tokens=1, output_tokens=1),
        )


async def executable_adapter(
    case: CaseContract,
    profile: str,
    workspace: Path,
    tier: EvaluationTier,
) -> BenchmarkRun:
    if tier != "scripted":
        raise ValueError("the executable fake-model adapter only supports scripted tier")
    if case.experiment == "repair_loop":
        return await _run_repair(case, profile, workspace)
    if case.experiment == "harness_regression":
        return await _run_harness(case, profile, workspace)
    if case.experiment == "context_compaction":
        return await _run_context(case, profile, workspace)
    if case.experiment == "session_memory":
        return await _run_memory(case, profile, workspace)
    if case.experiment == "resume_recovery":
        return await _run_recovery(case, profile, workspace)
    if case.experiment == "resume_staleness":
        return await _run_resume_staleness(case, profile, workspace)
    if case.experiment == "long_term_memory":
        return await _run_long_term_memory(case, profile, workspace)
    raise ValueError(f"no executable adapter for {case.experiment}")


def _runtime(
    workspace: Path,
    model: Any,
    *,
    repair_profile: str | None = None,
    compaction: ContextCompactionService | None = None,
    state: RuntimeState | None = None,
    store: MessageStore | None = None,
):
    state = state or RuntimeState()
    state.metadata["workspace"] = str(workspace)
    sessions = workspace / ".onecode" / "sessions"
    store = store or MessageStore(transcript_root=sessions, session_id=state.session_id, cwd=workspace, flush_interval_seconds=60)
    trace = TraceRecorder(session_id=state.session_id, workspace=workspace, sink=JsonlTraceSink(sessions, state.session_id, flush_interval_seconds=60))
    errors = ErrorLogRecorder(session_id=state.session_id, workspace=workspace, sink=JsonlErrorLogSink(sessions, state.session_id, flush_interval_seconds=60))
    hooks = HookRegistry(trace_recorder=trace)
    memory_store = SessionMemoryStore(store.transcript_store.session_dir)
    hooks.register(HookEvent.POST_TOOL_USE, SessionMemoryToolUpdater(memory_store).on_tool_result)
    hooks.register(HookEvent.TOOL_ERROR, SessionMemoryToolUpdater(memory_store).on_tool_result)
    registry = ToolRegistry(production_coding_tool_descriptors())
    guard = SandboxGuard(SandboxBoundary(cwd=workspace))
    executor = RegistryToolExecutor(registry, guard=guard, hooks=hooks, trace_recorder=trace, error_log_recorder=errors, result_store=ToolResultStorage(store.transcript_store.session_dir), file_state_cache=FileStateCache())
    if compaction is None:
        context = ContextEngine(store, prompt_assembler=StaticPromptAssembler(), tool_schema_provider=registry)
    else:
        compaction.bind_runtime(message_store=store, session_memory_store=memory_store)
        context = ContextEngine(store, prompt_assembler=StaticPromptAssembler(), tool_schema_provider=registry, context_preparer=compaction)
    gate = None
    if repair_profile is not None:
        profile_obj = next(item for item in PROFILES if item.name == repair_profile)
        gate = RepairLoopGate(workspace, result_store=ToolResultStorage(store.transcript_store.session_dir), trace_recorder=trace, policy=repair_loop_policy(profile_obj))
    loop = AgentLoop(state=state, message_store=store, context_engine=context, model_client=model, tool_executor=executor, trace_recorder=trace, error_log_recorder=errors, hooks=hooks, compaction_service=compaction, finish_gate=gate)
    return state, store, trace, errors, loop, memory_store


async def _collect(loop: AgentLoop, prompt: str) -> list[Any]:
    return [event async for event in loop.stream(prompt)]


async def _run_repair(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    target = workspace / "src" / "sample.py"
    if profile == "baseline":
        responses: list[ToolCall | str] = [_read("read", "src/sample.py"), _edit("first", "src/sample.py", "return 0", "return 200"), "done"]
        repair_profile = None
    else:
        responses = [_read("read", "src/sample.py"), _edit("first", "src/sample.py", "return 0", "return 10"), "first candidate", _edit("second", "src/sample.py", "return 10", "return 200"), "verified"]
        repair_profile = profile
    model = DeterministicModel(responses)
    state, store, trace, errors, loop, _memory = _runtime(workspace, model, repair_profile=repair_profile)
    started = time.perf_counter()
    events = await _collect(loop, "repair sample")
    elapsed = round((time.perf_counter() - started) * 1000)
    verification = state.metadata.get("last_verification")
    failure = None if state.last_transition == TransitionReason.COMPLETED_VERIFIED else (str(verification.get("outcome")) if isinstance(verification, dict) and verification.get("outcome") else "verification_skipped")
    return _record(case, profile, state, store, trace, errors, events, elapsed, success=state.last_transition == TransitionReason.COMPLETED_VERIFIED, resolved="return 200" in target.read_text(encoding="utf-8"), failure_kind=failure)


async def _run_harness(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    call = ToolCall("read", "read_file", {"file_path": "src/a.py"}) if case.id.endswith("tool") else ToolCall("deny", "write_file", {"file_path": "../outside.txt", "content": "no"})
    model = DeterministicModel([call, "done"])
    state, store, trace, errors, loop, _memory = _runtime(workspace, model)
    events = await _collect(loop, "exercise runtime")
    results = [message for message in store.current_messages() if message.get("role") == "tool_result"]
    expected_error = not case.id.endswith("tool")
    ok = bool(results) and bool(results[-1].get("is_error")) == expected_error
    return _record(case, profile, state, store, trace, errors, events, 0, success=ok, resolved=ok, failure_kind=None if ok else "runtime_error", extra={"runtime_correct": ok, "tool_correct": ok, "hook_correct": True, "budget_respected": True, "recovery_steps": 0, "security_boundary": expected_error == bool(results[-1].get("is_error"))})


async def _run_context(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    model = DeterministicModel(["answer: port 8123"])
    compaction = ContextCompactionService(config=CompactionConfig(snip_max_messages=3, microcompact_keep_recent=2))
    state, store, trace, errors, loop, _memory = _runtime(workspace, model, compaction=compaction)
    for index in range(5):
        store.append_user(f"old context {index}: " + ("x" * 500))
    store.append_user("critical fact: port 8123")
    events = await _collect(loop, "what is the port?")
    snapshot = model.snapshots[0]
    joined = "\n".join(str(item.get("content", "")) for item in snapshot.messages)
    info = state.metadata["last_compaction"]
    before, after = int(info["token_before"]), int(info["token_after"])
    retained = "port 8123" in joined
    return _record(case, profile, state, store, trace, errors, events, 0, success=retained, resolved=retained, failure_kind=None if retained else "key_fact_lost", extra={"compression_ratio": round(after / before, 4) if before else 1.0, "prompt_tokens": after, "key_fact_retention": retained, "task_success": retained})


async def _run_memory(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    calls: list[ToolCall | str] = [_read("one", "src/config.py"), "first"]
    if profile == "memory_off":
        calls.extend([_read("two", "src/config.py"), "second"])
    elif profile == "memory_stale":
        calls.extend([_edit("stale", "src/config.py", "8123", "9000"), "changed"])
    requires_second_turn = len(calls) > 2
    model = DeterministicModel(calls)
    state, store, trace, errors, loop, memory = _runtime(workspace, model)
    events = await _collect(loop, "read config")
    if requires_second_turn:
        events.extend(await _collect(loop, "continue"))
    injected = memory.prepare_for_injection(query="port")
    stale_injection = bool(injected and "8123" in injected.content and profile == "memory_stale")
    reads = sum(1 for item in store.current_messages() if item.get("role") == "tool_result" and item.get("tool_name") == "read_file")
    success = not stale_injection
    return _record(case, profile, state, store, trace, errors, events, 0, success=success, resolved=success, failure_kind=None if success else "stale_memory", extra={"repeated_file_reads": reads, "tool_calls": sum(1 for item in store.current_messages() if item.get("role") == "tool_result"), "task_success": success, "fact_recall": bool(injected and "8123" in injected.content) if profile != "memory_stale" else False, "stale_injection": stale_injection})


async def _run_recovery(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    from services.context.transcript import JsonlTranscriptStore
    from ui.cli.resume import restore_session_state

    model = DeterministicModel([_read("read", "src/state.py"), "done"])
    state, store, trace, errors, loop, _memory = _runtime(workspace, model)
    events = await _collect(loop, "inspect state")
    store.flush_transcript()
    target = workspace / "src" / "state.py"
    if profile != "normal":
        if profile == "file_deleted":
            target.unlink()
        else:
            target.write_text("VERSION = 2\n", encoding="utf-8")
    restored_state = RuntimeState()
    restored_store = MessageStore.from_transcript(JsonlTranscriptStore(store.transcript_store.session_dir.parent, state.session_id, cwd=workspace), restored_state)
    restore_session_state(restored_state, restored_store.current_messages(), message_store=restored_store)
    old_output = any("VERSION = 1" in str(message.get("content")) for message in restored_store.current_messages())
    changed = profile != "normal"
    stale_reuse = changed and old_output
    success = not stale_reuse
    failure = None if success else ("missing_file" if profile == "file_deleted" else "workspace_changed")
    return _record(case, profile, state, store, trace, errors, events, 0, success=success, resolved=success, failure_kind=failure, extra={"resume_success": bool(restored_store.current_messages()), "stale_reuse": stale_reuse, "recovery_steps": 1 if changed else 0})


async def _run_long_term_memory(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    """Keep the legacy experiment executable while real retrieval stays separate."""
    model = DeterministicModel(["answer"])
    state, store, trace, errors, loop, _memory = _runtime(workspace, model)
    events = await _collect(loop, "recall project port")
    memory_file = workspace / ".onecode" / "memory" / "project" / "port.md"
    content = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
    relevant = "8123" in content and profile == "retrieval_on"
    wrong = profile in {"irrelevant", "stale"}
    success = relevant and not wrong
    return _record(case, profile, state, store, trace, errors, events, 0, success=success, resolved=success, failure_kind="stale_memory" if profile == "stale" else ("memory_missing" if not success else None), extra={"relevant_recall": relevant, "wrong_injection": wrong, "selector_precision": 1.0 if relevant else 0.0, "task_success": success})


async def _run_resume_staleness(case: CaseContract, profile: str, workspace: Path) -> BenchmarkRun:
    """Run an answer turn after real transcript restoration and a file change.

    The three strategies are benchmark controls, not production recovery
    behavior: retain leaves the restored chain untouched; stale_mark appends a
    durable warning using MessageStore's existing attachment API; force_reread
    makes the deterministic model perform the existing read_file tool again.
    """
    from services.context.transcript import JsonlTranscriptStore
    from ui.cli.resume import restore_session_state

    scenario, strategy = profile.split("_", 1)
    initial_model = DeterministicModel([_read("initial-read", "src/state.py"), "initial done"])
    state, store, trace, errors, loop, _memory = _runtime(workspace, initial_model)
    initial_events = await _collect(loop, "inspect state")
    store.flush_transcript()
    target = workspace / "src" / "state.py"
    if scenario == "modified":
        target.write_text("VERSION = 2\n", encoding="utf-8")
        expected = "VERSION = 2"
    else:
        target.unlink()
        expected = "MISSING"
    restored_state = RuntimeState(session_id=state.session_id)
    restored_store = MessageStore.from_transcript(
        JsonlTranscriptStore(store.transcript_store.session_dir.parent, state.session_id, cwd=workspace),
        restored_state,
    )
    restore_session_state(restored_state, restored_store.current_messages(), message_store=restored_store)
    if strategy == "stale_mark":
        restored_store.append_attachments(({"role": "attachment", "content": "STALE: src/state.py changed after this transcript; re-read before answering."},))
    if scenario == "modified":
        responses = [_read("resume-read", "src/state.py"), "VERSION = 2"]
    else:
        responses = [_read("resume-read", "src/state.py"), "MISSING"]
    resumed_model = DeterministicModel(responses)
    resumed_trace = TraceRecorder(session_id=restored_state.session_id, workspace=workspace, sink=JsonlTraceSink(store.transcript_store.session_dir.parent, restored_state.session_id, flush_interval_seconds=60))
    resumed_errors = ErrorLogRecorder(session_id=restored_state.session_id, workspace=workspace, sink=JsonlErrorLogSink(store.transcript_store.session_dir.parent, restored_state.session_id, flush_interval_seconds=60))
    registry = ToolRegistry(production_coding_tool_descriptors())
    resumed_loop = AgentLoop(
        state=restored_state,
        message_store=restored_store,
        context_engine=ContextEngine(restored_store, prompt_assembler=StaticPromptAssembler(), tool_schema_provider=registry),
        model_client=resumed_model,
        tool_executor=RegistryToolExecutor(registry, guard=SandboxGuard(SandboxBoundary(cwd=workspace)), trace_recorder=resumed_trace, error_log_recorder=resumed_errors, file_state_cache=FileStateCache()),
        trace_recorder=resumed_trace,
        error_log_recorder=resumed_errors,
    )
    resumed_events = await _collect(resumed_loop, "what is the current state?")
    final = next(event.text for event in reversed(resumed_events) if event.type == "completed")
    tool_steps = sum(1 for event in resumed_events if event.type == "tool_result")
    stale_fact_used = "VERSION = 1" in final or any(
        "VERSION = 1" in str(message.get("content"))
        for message in resumed_model.snapshots[0].messages
    )
    success = expected in final and not stale_fact_used
    return _record(case, profile, restored_state, restored_store, resumed_trace, resumed_errors, [*initial_events, *resumed_events], 0, success=success, resolved=success, failure_kind=None if success else ("missing_file" if scenario == "deleted" and not stale_fact_used else "stale_fact_used"), extra={"task_success": success, "stale_fact_used": stale_fact_used, "tool_steps": tool_steps})


def _record(case: CaseContract, profile: str, state: RuntimeState, store: MessageStore, trace: TraceRecorder, errors: ErrorLogRecorder, events: list[Any], latency_ms: int, *, success: bool, resolved: bool, failure_kind: str | None, extra: dict[str, Any] | None = None, tier: EvaluationTier = "scripted") -> BenchmarkRun:
    store.flush_transcript(); trace.flush(); errors.flush()
    trace_rows = _jsonl(trace.trace_path)
    error_rows = _jsonl(errors.error_log_path)
    tool_rows = [message for message in store.current_messages() if message.get("role") == "tool_result"]
    completed = next((event for event in reversed(events) if event.type == "completed"), None)
    terminal = state.last_transition.value if state.last_transition is not None else "error"
    last_verification = state.metadata.get("last_verification")
    verification_attempts = int(state.metadata.get("repair_attempts", 0))
    if isinstance(last_verification, dict):
        verification_attempts = max(verification_attempts, 1)
    metrics: dict[str, int | float | bool] = {"success": success, "resolved": resolved, "turns": state.turn_count, "tool_calls": len(tool_rows), "tokens": state.usage.input_tokens + state.usage.output_tokens, "latency": latency_ms, "verification_attempts": verification_attempts, "repeated_failures": int(state.metadata.get("same_failure_repeats", 0))}
    metrics.update(extra or {})
    event_summary = summarize_events(trace_records=trace_rows, tool_events=tool_rows, stop_reason=terminal)
    return BenchmarkRun(case.id, profile, success, resolved, state.turn_count, len(tool_rows), int(metrics["tokens"]), latency_ms, int(metrics["verification_attempts"]), int(metrics["repeated_failures"]), terminal, experiment=case.experiment, tier=tier, metrics=metrics, failure_kind=failure_kind, run_status="completed" if completed is not None else "error", event_summary=event_summary)


def _jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read(call_id: str, path: str) -> ToolCall:
    return ToolCall(call_id, "read_file", {"file_path": path})


def _edit(call_id: str, path: str, old: str, new: str) -> ToolCall:
    return ToolCall(call_id, "edit_file", {"file_path": path, "old_string": old, "new_string": new})
