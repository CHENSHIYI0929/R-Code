"""Session-local Markdown memory for compaction continuity."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from core.runtime_state import RuntimeState
from services.compaction.token_estimator import estimate_messages_tokens
from services.memory.validation import is_injectable, validate_memory_item
from services.observability import TraceRecorder
from services.subagents.types import SubagentRequest, SubagentResult


SESSION_MEMORY_EXTRACTION_KEY = "session_memory_extraction"


@dataclass(frozen=True)
class SessionMemory:
    content: str
    state: "SessionMemoryState | None" = None
    last_summarized_message_uuid: str = ""
    updated_at: str = ""
    covered_turn_count: int = 0
    source: str = "rule"

    @property
    def is_empty(self) -> bool:
        if self.state is not None:
            task = self.state.task_state
            return not (
                self.state.recent_files
                or self.state.file_summaries
                or self.state.episodic_notes
                or any(task.get(key) for key in ("goal", "constraints", "current_plan", "confirmed_findings", "open_questions", "errors", "next_action"))
            )
        body = _strip_front_matter(self.content).strip()
        return not body or body == "# Session Memory"


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    mtime_ns: int
    size: int
    content_hash: str


@dataclass(frozen=True)
class FileSummary:
    path: str
    fingerprint: FileFingerprint
    summary: str
    observed_range: tuple[int, int] | None = None
    findings: tuple[str, ...] = ()
    stale: bool = False
    stale_reason: str = ""


@dataclass(frozen=True)
class SessionMemoryState:
    schema_version: int = 2
    task_state: dict[str, Any] = field(default_factory=lambda: {
        "goal": "", "constraints": [], "current_plan": [], "confirmed_findings": [],
        "open_questions": [], "errors": [], "next_action": "",
    })
    recent_files: tuple[str, ...] = ()
    file_summaries: tuple[FileSummary, ...] = ()
    episodic_notes: tuple[Any, ...] = ()


@dataclass(frozen=True)
class MemoryFact:
    value: str
    source: str
    priority: int
    observed_at: str
    source_refs: tuple[str, ...] = ()
    stale: bool = False


FACT_PRIORITY = {"speculation": 1, "llm_extraction": 2, "tool": 3, "user": 4}


@dataclass(frozen=True)
class ExtractionResult:
    facts: tuple[MemoryFact, ...] = ()
    task_updates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionMemoryExtractionPolicy:
    minimum_message_tokens_to_init: int = 10_000
    minimum_tokens_between_update: int = 5_000
    tool_calls_between_updates: int = 3


@dataclass(frozen=True)
class SessionMemoryExtractionDecision:
    should_extract: bool
    reason: str
    message_tokens: int
    tool_call_count: int
    token_delta: int
    tool_call_delta: int


@dataclass(frozen=True)
class SessionMemoryExtractionJob:
    messages: tuple[dict[str, Any], ...]
    decision: SessionMemoryExtractionDecision
    parent_session_id: str
    parent_tool_call_id: str


class SessionMemorySubagentRunner(Protocol):
    async def run(self, request: SubagentRequest) -> SubagentResult: ...


class SessionMemoryStore:
    """Read and write `.onecode/sessions/<session_id>/session-memory.md` only."""

    def __init__(self, session_dir: Path | str) -> None:
        self._session_dir = Path(session_dir)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._session_dir / "session-memory.md"

    @property
    def state_path(self) -> Path:
        return self._session_dir / "session-memory.json"

    def read(self) -> SessionMemory | None:
        if not self.path.exists() and not self.state_path.exists():
            return None
        content = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        metadata = _parse_front_matter(content)
        state = self.read_state()
        return SessionMemory(
            content=content,
            state=state,
            last_summarized_message_uuid=metadata.get("last_summarized_message_uuid", ""),
            updated_at=metadata.get("updated_at", ""),
            covered_turn_count=_int_or_zero(metadata.get("covered_turn_count")),
            source=metadata.get("source", "rule"),
        )

    def write(self, memory: SessionMemory) -> None:
        with self._lock:
            if memory.state is not None:
                self.write_state(memory.state, metadata=memory)
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(_render_memory(memory), encoding="utf-8")

    def read_state(self) -> SessionMemoryState | None:
        """Read only the canonical JSON state; Markdown is never an input."""
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return _state_from_dict(raw)
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None

    def write_state(self, state: SessionMemoryState, *, metadata: SessionMemory | None = None) -> SessionMemory:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rendered = _render_structured_memory(state)
            memory = SessionMemory(
                content=rendered,
                state=state,
                last_summarized_message_uuid=(metadata.last_summarized_message_uuid if metadata else ""),
                updated_at=(metadata.updated_at if metadata else _now()),
                covered_turn_count=(metadata.covered_turn_count if metadata else 0),
                source=(metadata.source if metadata else "runtime"),
            )
            _atomic_write(self.state_path, json.dumps(_state_to_dict(state), ensure_ascii=False, indent=2))
            _atomic_write(self.path, _render_memory(memory))
            return memory

    def update_from_tool_payload(self, payload: dict[str, Any]) -> None:
        """Persist deterministic file/command facts from a completed tool hook."""
        result = payload.get("result")
        if result is None:
            return
        tool_name = getattr(result, "tool_name", "")
        metadata = getattr(result, "metadata", {}) or {}
        is_error = bool(getattr(result, "is_error", False))
        tool_input = payload.get("tool_input") or {}
        with self._lock:
            state = self.read_state() or SessionMemoryState()
            summaries = {item.path: item for item in state.file_summaries}
            recent = list(state.recent_files)
            errors = list(state.task_state.get("errors", []))
            path = metadata.get("path") if isinstance(metadata, dict) else None
            if tool_name == "read_file" and not is_error and isinstance(path, str):
                summary = _observe_file(Path(path), tool_input, str(getattr(result, "content", "")))
                if summary is not None:
                    summaries[path] = summary
                    recent = [path, *[item for item in recent if item != path]][:20]
            elif tool_name in {"edit_file", "write_file", "filewrite"} and not is_error and isinstance(path, str):
                if path in summaries:
                    old = summaries[path]
                    summaries[path] = replace(old, stale=True, stale_reason="written_after_summary")
            elif tool_name == "bash" and is_error and isinstance(metadata, dict):
                errors.append({"tool": "bash", "command": tool_input.get("command", ""), "exit_code": metadata.get("exit_code"), "error": metadata.get("error", "command_failed")})
                errors = errors[-20:]
            else:
                return
            task_state = dict(state.task_state)
            task_state["errors"] = errors
            self.merge_state(replace(state, task_state=task_state, recent_files=tuple(recent), file_summaries=tuple(summaries.values())), source="tool")

    def merge_state(self, incoming: SessionMemoryState, *, source: str) -> SessionMemory:
        """Merge through the single writer, keeping higher-priority facts."""
        with self._lock:
            current = self.read_state() or SessionMemoryState()
            priority = FACT_PRIORITY.get(source, FACT_PRIORITY["speculation"])
            task = dict(current.task_state)
            for key, value in incoming.task_state.items():
                existing_priority = int(task.get(f"_{key}_priority", 0) or 0)
                if value and priority >= existing_priority:
                    task[key] = value
                    task[f"_{key}_priority"] = priority
            summaries = {item.path: item for item in current.file_summaries}
            # File observations and invalidations are deterministic tool facts;
            # lower-priority extraction cannot overwrite them.
            if priority >= FACT_PRIORITY["tool"]:
                summaries.update({item.path: item for item in incoming.file_summaries})
            notes = _dedupe_memory_items((*current.episodic_notes, *incoming.episodic_notes))
            return self.write_state(replace(current, task_state=task, recent_files=tuple(dict.fromkeys((*incoming.recent_files, *current.recent_files)))[:20], file_summaries=tuple(summaries.values()), episodic_notes=notes))

    def merge_extraction(self, extraction: ExtractionResult) -> SessionMemory:
        task = dict(extraction.task_updates)
        task["confirmed_findings"] = [fact.__dict__ for fact in extraction.facts if not fact.stale]
        return self.merge_state(SessionMemoryState(task_state=task), source="llm_extraction")

    def validated_for_injection(
        self,
        workspace: Path | str | None = None,
        *,
        query: str = "",
    ) -> SessionMemory | None:
        """Return the compact core/relevant projection after validation.

        The canonical JSON state retains stale material for audit.  The
        returned Markdown is a model-facing projection only.
        """
        memory = self.read()
        if memory is None:
            return memory
        if memory.state is None:
            # Compatibility for pre-JSON sessions: never treat Markdown as
            # canonical state, but still avoid re-injecting its full body.
            return replace(memory, content=_render_legacy_injection(memory.content))
        changed = False
        summaries: list[FileSummary] = []
        for item in memory.state.file_summaries:
            validation = validate_memory_item(item, workspace=workspace)
            next_item = (
                item
                if validation.injectable
                else replace(item, stale=True, stale_reason=validation.reason)
            )
            changed = changed or next_item != item
            summaries.append(next_item)
        state = replace(memory.state, file_summaries=tuple(summaries))
        if changed:
            memory = self.write_state(state, metadata=memory)
        return replace(memory, content=_render_injection_memory(state, query=query))

    def prepare_for_injection(
        self,
        *,
        query: str = "",
        workspace: Path | str | None = None,
    ) -> SessionMemory | None:
        """Explicit name for the model-facing validated Session Memory view."""

        return self.validated_for_injection(workspace, query=query)


class SessionMemoryUpdater:
    """Rule-based first version of per-turn session memory updates."""

    def __init__(
        self,
        store: SessionMemoryStore,
        *,
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self._store = store
        self._trace_recorder = trace_recorder or TraceRecorder.noop()

    @property
    def store(self) -> SessionMemoryStore:
        return self._store

    async def update_after_turn(
        self,
        messages: tuple[dict[str, Any], ...],
        state: RuntimeState,
    ) -> None:
        if state.metadata.get("query_source") == "compact":
            return
        try:
            memory = build_rule_based_memory(messages, state)
            self._store.write(memory)
            state.metadata["session_memory"] = {
                "path": str(self._store.path),
                "updated_at": memory.updated_at,
                "covered_turn_count": memory.covered_turn_count,
                "last_summarized_message_uuid": memory.last_summarized_message_uuid,
            }
            self._trace_recorder.event(
                "session_memory_update",
                {
                    "status": "success",
                    "path": self._store.path,
                    "covered_turn_count": memory.covered_turn_count,
                    "estimated_tokens": estimate_messages_tokens(messages),
                },
            )
        except Exception as exc:
            self._trace_recorder.event(
                "session_memory_update",
                {"status": "failed", "error_type": type(exc).__name__},
            )


class SessionMemoryExtractionService:
    """Use a restricted fork child to maintain session-local memory."""

    def __init__(
        self,
        store: SessionMemoryStore,
        *,
        subagent_runner: SessionMemorySubagentRunner,
        policy: SessionMemoryExtractionPolicy | None = None,
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self._store = store
        self._subagent_runner = subagent_runner
        self._policy = policy or SessionMemoryExtractionPolicy()
        self._trace_recorder = trace_recorder or TraceRecorder.noop()
        self._lock = asyncio.Lock()
        self._active_done = asyncio.Event()
        self._active_done.set()

    @property
    def store(self) -> SessionMemoryStore:
        return self._store

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    async def maybe_extract_after_model_response(
        self,
        messages: tuple[dict[str, Any], ...],
        state: RuntimeState,
        *,
        assistant_message: dict[str, Any],
        tool_calls: tuple[Any, ...],
        usage: Any | None = None,
    ) -> None:
        """Evaluate extraction only.

        Production CLI wiring injects a background scheduler that calls
        ``prepare_extraction_job`` and runs the returned job in a dream task.
        This method intentionally does not run the fork child synchronously.
        """

        job = self.prepare_extraction_job(
            messages,
            state,
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            usage=usage,
        )
        if job is not None:
            _merge_extraction_metadata(
                state,
                {"last_status": "not_scheduled", "running": False},
            )
            self._active_done.set()

    def prepare_extraction_job(
        self,
        messages: tuple[dict[str, Any], ...],
        state: RuntimeState,
        *,
        assistant_message: dict[str, Any],
        tool_calls: tuple[Any, ...],
        usage: Any | None = None,
    ) -> SessionMemoryExtractionJob | None:
        """Return a background extraction job when thresholds are met."""

        _ = assistant_message, usage
        if state.metadata.get("query_source") == "compact":
            return None
        if state.metadata.get("memory_extraction_agent") is True:
            return None

        decision = should_extract_memory(
            messages,
            state,
            self._policy,
            last_response_had_tool_calls=bool(tool_calls),
        )
        _merge_extraction_metadata(
            state,
            {
                "path": str(self._store.path),
                "message_tokens": decision.message_tokens,
                "tool_call_count": decision.tool_call_count,
                "last_decision": decision.reason,
                "running": self.is_running,
            },
        )
        if not decision.should_extract:
            self._trace_decision("skipped", decision)
            return None
        if self._lock.locked():
            _merge_extraction_metadata(
                state,
                {"last_status": "skipped_running", "running": True},
            )
            self._trace_decision("skipped_running", decision)
            return None

        started_at = _now()
        _merge_extraction_metadata(
            state,
            {
                "last_status": "scheduled",
                "last_started_at": started_at,
                "running": True,
                "path": str(self._store.path),
            },
        )
        self._active_done.clear()
        self._trace_decision("scheduled", decision)
        return SessionMemoryExtractionJob(
            messages=tuple(messages),
            decision=decision,
            parent_session_id=state.session_id,
            parent_tool_call_id=f"session-memory-{state.turn_count}",
        )

    def record_background_task(self, state: RuntimeState, task_id: str) -> None:
        _merge_extraction_metadata(
            state,
            {
                "background_task_id": task_id,
                "last_status": "scheduled",
                "running": True,
            },
        )

    def record_background_cancelled(self, state: RuntimeState) -> None:
        _merge_extraction_metadata(
            state,
            {
                "last_status": "killed",
                "last_completed_at": _now(),
                "running": False,
            },
        )
        self._active_done.set()

    async def run_extraction_job(
        self,
        job: SessionMemoryExtractionJob,
        state: RuntimeState,
    ) -> dict[str, Any]:
        """Run a prepared extraction job in a background task."""

        current_decision = job.decision
        async with self._lock:
            _merge_extraction_metadata(
                state,
                {
                    "last_status": "running",
                    "running": True,
                    "path": str(self._store.path),
                },
            )
            try:
                request = SubagentRequest(
                    prompt=_memory_extraction_prompt(
                        current_memory=self._store.read(),
                    ),
                    subagent_type=None,
                    parent_session_id=job.parent_session_id,
                    parent_tool_call_id=job.parent_tool_call_id,
                    metadata={
                        "purpose": "session_memory_extraction",
                    },
                )
                result = await self._subagent_runner.run(request)
                if result.is_error:
                    raise RuntimeError(result.final_text)
                extraction = _parse_extraction_result(result.final_text)
                self._store.merge_extraction(extraction)
                _merge_extraction_metadata(
                    state,
                    {
                        "last_status": "success",
                        "last_completed_at": _now(),
                        "last_extracted_token_count": current_decision.message_tokens,
                        "last_extracted_tool_call_count": (
                            current_decision.tool_call_count
                        ),
                        "last_result_session_id": result.session_id,
                        "running": False,
                        "resume_generation": _resume_generation(state),
                    },
                )
                state.metadata.pop("session_memory_resume_needs_extraction", None)
                self._trace_recorder.event(
                    "session_memory_extraction_completed",
                    {
                        "status": "success",
                        "path": self._store.path,
                        "message_tokens": current_decision.message_tokens,
                        "tool_call_count": current_decision.tool_call_count,
                        "child_session_id": result.session_id,
                    },
                )
                return {
                    "summary": "Session memory updated.",
                    "result_session_id": result.session_id,
                    "memory_path": str(self._store.path),
                }
            except asyncio.CancelledError:
                _merge_extraction_metadata(
                    state,
                    {
                        "last_status": "killed",
                        "last_completed_at": _now(),
                        "running": False,
                    },
                )
                self._trace_recorder.event(
                    "session_memory_extraction_cancelled",
                    {"path": self._store.path},
                )
                raise
            except Exception as exc:
                _merge_extraction_metadata(
                    state,
                    {
                        "last_status": "failed",
                        "last_completed_at": _now(),
                        "last_error_type": type(exc).__name__,
                        "running": False,
                    },
                )
                self._trace_recorder.event(
                    "session_memory_extraction_failed",
                    {
                        "error_type": type(exc).__name__,
                        "path": self._store.path,
                    },
                )
                return {
                    "summary": "Session memory update failed.",
                    "error_type": type(exc).__name__,
                    "memory_path": str(self._store.path),
                }
            finally:
                self._active_done.set()

    async def wait_for_current_extraction(self, state: RuntimeState) -> None:
        """Wait for an in-flight extraction before compaction consumes memory."""

        if self._active_done.is_set() and not self._lock.locked():
            return
        _merge_extraction_metadata(state, {"last_status": "waiting", "running": True})
        await self._active_done.wait()
        _merge_extraction_metadata(state, {"running": False})

    def _trace_decision(
        self,
        status: str,
        decision: SessionMemoryExtractionDecision,
    ) -> None:
        self._trace_recorder.event(
            "session_memory_extraction_decision",
            {
                "status": status,
                "reason": decision.reason,
                "message_tokens": decision.message_tokens,
                "tool_call_count": decision.tool_call_count,
                "token_delta": decision.token_delta,
                "tool_call_delta": decision.tool_call_delta,
            },
        )


def should_extract_memory(
    messages: tuple[dict[str, Any], ...],
    state: RuntimeState,
    policy: SessionMemoryExtractionPolicy,
    *,
    last_response_had_tool_calls: bool,
) -> SessionMemoryExtractionDecision:
    message_tokens = estimate_messages_tokens(messages)
    tool_call_count = count_tool_calls(messages)
    extraction_state = _extraction_metadata(state)
    last_tokens = _int_or_zero(extraction_state.get("last_extracted_token_count"))
    last_tool_calls = _int_or_zero(
        extraction_state.get("last_extracted_tool_call_count")
    )
    token_delta = message_tokens - last_tokens
    tool_call_delta = tool_call_count - last_tool_calls

    if message_tokens < policy.minimum_message_tokens_to_init:
        return SessionMemoryExtractionDecision(
            False,
            "below_initial_token_threshold",
            message_tokens,
            tool_call_count,
            token_delta,
            tool_call_delta,
        )
    if state.metadata.get("session_memory_resume_needs_extraction") is True:
        return SessionMemoryExtractionDecision(
            True,
            "resume_initial_extraction",
            message_tokens,
            tool_call_count,
            token_delta,
            tool_call_delta,
        )
    if token_delta < policy.minimum_tokens_between_update:
        return SessionMemoryExtractionDecision(
            False,
            "insufficient_token_delta",
            message_tokens,
            tool_call_count,
            token_delta,
            tool_call_delta,
        )
    if tool_call_delta >= policy.tool_calls_between_updates:
        return SessionMemoryExtractionDecision(
            True,
            "token_and_tool_growth",
            message_tokens,
            tool_call_count,
            token_delta,
            tool_call_delta,
        )
    if not last_response_had_tool_calls:
        return SessionMemoryExtractionDecision(
            True,
            "token_growth_after_text_response",
            message_tokens,
            tool_call_count,
            token_delta,
            tool_call_delta,
        )
    return SessionMemoryExtractionDecision(
        False,
        "insufficient_tool_call_delta",
        message_tokens,
        tool_call_count,
        token_delta,
        tool_call_delta,
    )


def count_tool_calls(messages: tuple[dict[str, Any], ...]) -> int:
    count = 0
    for message in messages:
        if message.get("role") != "assistant":
            continue
        count += _count_tool_calls_field(message.get("tool_calls"))
        content = message.get("content")
        if isinstance(content, list):
            count += sum(1 for block in content if _is_tool_use_block(block))
    return count


def build_rule_based_memory(
    messages: tuple[dict[str, Any], ...],
    state: RuntimeState,
) -> SessionMemory:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    last_uuid = _message_uuid(messages[-1], len(messages) - 1) if messages else ""
    user_messages = [_text_content(message.get("content")) for message in messages if message.get("role") == "user"]
    assistant_messages = [
        _text_content(message.get("content"))
        for message in messages
        if message.get("role") == "assistant"
    ]
    tool_results = [
        message
        for message in messages
        if message.get("role") == "tool_result"
    ]
    files_read = sorted(str(path) for path in state.metadata.get("files_read", set()))
    files_changed = sorted(str(path) for path in state.metadata.get("files_changed", set()))
    errors = [
        f"{message.get('tool_name', 'tool')} {message.get('tool_call_id', '')}: {_preview(message.get('content'))}"
        for message in tool_results
        if message.get("is_error") is True
    ]
    body = "\n".join(
        [
            "# Session Memory",
            "",
            "## Current Goal",
            _last_nonempty(user_messages) or "Not yet established.",
            "",
            "## User Constraints",
            _bullet_lines(_recent_nonempty(user_messages, 5)),
            "",
            "## Key Findings",
            _bullet_lines(_recent_nonempty(assistant_messages, 5)),
            "",
            "## Files Read",
            _bullet_lines(files_read) if files_read else "- None recorded.",
            "",
            "## Files Changed",
            _bullet_lines(files_changed) if files_changed else "- None recorded.",
            "",
            "## Errors And Fixes",
            _bullet_lines(errors) if errors else "- None recorded.",
            "",
            "## Pending Work",
            "- Continue from the latest user request and preserved recent messages.",
            "",
            "## Next Step",
            _last_nonempty(user_messages) or "Wait for the next user request.",
            "",
        ]
    )
    return SessionMemory(
        content=body,
        last_summarized_message_uuid=last_uuid,
        updated_at=now,
        covered_turn_count=state.turn_count,
        source="rule",
    )


def _render_memory(memory: SessionMemory) -> str:
    body = _strip_front_matter(memory.content).lstrip()
    return "\n".join(
        [
            "---",
            f"last_summarized_message_uuid: {memory.last_summarized_message_uuid}",
            f"updated_at: {memory.updated_at}",
            f"covered_turn_count: {memory.covered_turn_count}",
            f"source: {memory.source}",
            "---",
            body,
        ]
    )


def _state_to_dict(state: SessionMemoryState) -> dict[str, Any]:
    return {
        "schema_version": state.schema_version,
        "task_state": state.task_state,
        "recent_files": list(state.recent_files),
        "file_summaries": [
            {"path": item.path, "fingerprint": item.fingerprint.__dict__, "summary": item.summary,
             "observed_range": list(item.observed_range) if item.observed_range else None,
             "findings": list(item.findings), "stale": item.stale, "stale_reason": item.stale_reason}
            for item in state.file_summaries
        ],
        "episodic_notes": list(state.episodic_notes),
    }


def _state_from_dict(raw: Any) -> SessionMemoryState:
    if not isinstance(raw, dict):
        raise ValueError("session memory state must be an object")
    summaries = []
    for item in raw.get("file_summaries", []):
        if not isinstance(item, dict) or not isinstance(item.get("fingerprint"), dict):
            continue
        fingerprint = item["fingerprint"]
        summaries.append(FileSummary(
            path=str(item.get("path", "")),
            fingerprint=FileFingerprint(str(fingerprint.get("path", item.get("path", ""))), int(fingerprint.get("mtime_ns", 0)), int(fingerprint.get("size", 0)), str(fingerprint.get("content_hash", ""))),
            summary=str(item.get("summary", "")),
            observed_range=tuple(item["observed_range"]) if isinstance(item.get("observed_range"), list) and len(item["observed_range"]) == 2 else None,
            findings=tuple(str(value) for value in item.get("findings", []) if isinstance(value, str)),
            stale=bool(item.get("stale", False)), stale_reason=str(item.get("stale_reason", "")),
        ))
    task_state = raw.get("task_state") if isinstance(raw.get("task_state"), dict) else {}
    notes = tuple(
        value for value in raw.get("episodic_notes", []) if isinstance(value, (str, dict))
    )
    return SessionMemoryState(task_state=task_state, recent_files=tuple(str(value) for value in raw.get("recent_files", []) if isinstance(value, str)), file_summaries=tuple(summaries), episodic_notes=notes)


def _render_structured_memory(state: SessionMemoryState) -> str:
    task = state.task_state
    fresh = [item for item in state.file_summaries if not item.stale]
    lines = ["# Session Memory", "", "## Current Goal", str(task.get("goal") or "Not yet established."), "", "## User Constraints", _bullet_lines([str(item) for item in task.get("constraints", [])]), "", "## Confirmed Findings", _bullet_lines([_memory_item_text(item) for item in task.get("confirmed_findings", [])]), "", "## Relevant Files"]
    lines.extend(f"- {item.path}: {item.summary}" for item in fresh) if fresh else lines.append("- None recorded.")
    lines.extend(["", "## Errors And Fixes", _bullet_lines([str(item) for item in task.get("errors", [])]), "", "## Pending Work", _bullet_lines([str(item) for item in task.get("current_plan", [])]), "", "## Episodic Notes", _bullet_lines([_memory_item_text(item) for item in state.episodic_notes]), "", "## Next Step", str(task.get("next_action") or "Continue from recent messages.")])
    return "\n".join(lines) + "\n"


def _render_injection_memory(state: SessionMemoryState, *, query: str) -> str:
    """Render only durable core state plus a small query-relevant tail."""

    task = state.task_state
    stale_files = {item.path for item in state.file_summaries if not is_injectable(item)}
    recent_files = [path for path in state.recent_files if path not in stale_files]
    core = [
        "# Session Memory",
        "",
        "## Core Memory",
        f"Goal: {task.get('goal') or 'Not yet established.'}",
        "Constraints:",
        _bullet_lines([str(item) for item in task.get("constraints", [])]),
        "Current plan:",
        _bullet_lines([str(item) for item in task.get("current_plan", [])]),
        f"Next action: {task.get('next_action') or 'Continue from recent messages.'}",
        "Recent files:",
        _bullet_lines(recent_files),
    ]
    candidates = [*task.get("confirmed_findings", []), *state.episodic_notes]
    relevant = _select_relevant_memory_items(candidates, query=query, limit=5)
    core.extend(["", "## Relevant Memory", _bullet_lines([_memory_item_text(item) for item in relevant])])
    return "\n".join(core) + "\n"


def _render_legacy_injection(content: str) -> str:
    """Bound legacy Markdown sessions without ever writing them back to JSON."""

    body = _strip_front_matter(content)
    goal = _legacy_section(body, "Current Goal") or "Not yet established."
    constraints = _legacy_section(body, "User Constraints")
    plan = _legacy_section(body, "Pending Work")
    next_action = _legacy_section(body, "Next Step") or "Continue from recent messages."
    recent_files = _legacy_section(body, "Files Read") or _legacy_section(body, "Relevant Files")
    relevant = _legacy_section(body, "Key Findings") or _legacy_section(body, "Episodic Notes")
    return "\n".join(
        [
            "# Session Memory",
            "",
            "## Core Memory",
            f"Goal: {goal}",
            "Constraints:",
            constraints or "- None recorded.",
            "Current plan:",
            plan or "- Continue from recent messages.",
            f"Next action: {next_action}",
            "Recent files:",
            recent_files or "- None recorded.",
            "",
            "## Relevant Memory",
            relevant or "- None recorded.",
        ]
    ) + "\n"


def _legacy_section(body: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else ""


def _select_relevant_memory_items(
    items: list[Any], *, query: str, limit: int,
) -> list[Any]:
    query_words = set(_memory_words(query))
    scored: list[tuple[int, int, Any]] = []
    for index, item in enumerate(items):
        if not is_injectable(item):
            continue
        text = _memory_item_text(item)
        overlap = len(query_words.intersection(_memory_words(text)))
        # Preserve recency/order as the stable tie-breaker.  With no query,
        # this is a bounded recent-memory fallback rather than full injection.
        scored.append((overlap, -index, item))
    scored.sort(reverse=True, key=lambda value: (value[0], value[1]))
    if query_words and any(score > 0 for score, _, _ in scored):
        scored = [entry for entry in scored if entry[0] > 0]
    return [item for _, _, item in scored[:limit] if _memory_item_text(item)]


def _memory_item_text(item: Any) -> str:
    if isinstance(item, dict):
        value = item.get("value", item.get("note", item.get("text", "")))
        return str(value)
    return str(item)


def _memory_words(value: str) -> tuple[str, ...]:
    return tuple(
        word.lower()
        for word in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", value)
        if len(word) > 1 or "\u4e00" <= word <= "\u9fff"
    )


def _dedupe_memory_items(items: tuple[Any, ...]) -> tuple[Any, ...]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _observe_file(path: Path, tool_input: dict[str, Any], content: str) -> FileSummary | None:
    try:
        resolved = path.resolve()
        raw = resolved.read_bytes()
        stat = resolved.stat()
    except OSError:
        return None
    offset = tool_input.get("offset", 1)
    line_count = max(0, content.count("\n") + (1 if content else 0))
    preview = " ".join(content.split())[:500] or "File observed."
    return FileSummary(str(resolved), FileFingerprint(str(resolved), stat.st_mtime_ns, stat.st_size, hashlib.sha256(raw).hexdigest()), f"Read from line {offset}; {line_count} displayed line(s). {preview}", (int(offset) if isinstance(offset, int) else 1, line_count))


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _legacy_state(content: str) -> SessionMemoryState:
    """Preserve legacy/LLM Markdown as an episodic note during migration."""
    body = _strip_front_matter(content).strip()
    return SessionMemoryState(episodic_notes=(body,) if body else ())


def _parse_front_matter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip()
    return metadata


def _strip_front_matter(content: str) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return content


def _message_uuid(message: dict[str, Any], index: int) -> str:
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("message_uuid")
        if isinstance(value, str) and value:
            return value
    return f"message-{index + 1}"


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return "" if content is None else str(content)


def _preview(value: Any, limit: int = 160) -> str:
    text = " ".join(_text_content(value).split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def _recent_nonempty(values: list[str], limit: int) -> list[str]:
    return [value for value in values if value.strip()][-limit:]


def _last_nonempty(values: list[str]) -> str:
    recent = _recent_nonempty(values, 1)
    return recent[0] if recent else ""


def _bullet_lines(values: list[str]) -> str:
    if not values:
        return "- None recorded."
    return "\n".join(f"- {_preview(value)}" for value in values)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or "0")
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _extraction_metadata(state: RuntimeState) -> dict[str, Any]:
    value = state.metadata.get(SESSION_MEMORY_EXTRACTION_KEY)
    if isinstance(value, dict):
        return value
    value = {}
    state.metadata[SESSION_MEMORY_EXTRACTION_KEY] = value
    return value


def _merge_extraction_metadata(
    state: RuntimeState,
    updates: dict[str, Any],
) -> None:
    metadata = dict(_extraction_metadata(state))
    metadata.update(updates)
    state.metadata[SESSION_MEMORY_EXTRACTION_KEY] = metadata


def _resume_generation(state: RuntimeState) -> int:
    value = state.metadata.get("session_memory_resume_generation", 0)
    return _int_or_zero(value)


def _count_tool_calls_field(value: Any) -> int:
    if value in (None, "", (), []):
        return 0
    if isinstance(value, dict):
        return 1
    try:
        return sum(1 for _item in value)
    except TypeError:
        return 0


def _is_tool_use_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    block_type = block.get("type")
    return block_type in {"tool_use", "function_call"} and bool(
        block.get("name") or block.get("id") or block.get("tool_call_id")
    )


def _memory_extraction_prompt(
    *,
    current_memory: SessionMemory | None,
) -> str:
    current = current_memory.content if current_memory is not None else ""
    return "\n".join(
        [
            "Extract durable session facts. Do not call tools and do not edit files.",
            "",
            "Rules:",
            "- Return only JSON: {\"facts\":[{\"value\":str,\"source_refs\":[str]}],\"task_updates\":{...}}.",
            "- Facts are lower-priority LLM extraction; only include durable, non-speculative facts.",
            "- Do not include stale file conclusions, todos, or unverified errors.",
            "",
            "Current session memory:",
            current.strip() or "(missing)",
        ]
    )


def _parse_extraction_result(text: str) -> ExtractionResult:
    try:
        raw = json.loads(text.strip())
    except (TypeError, ValueError):
        return ExtractionResult()
    if not isinstance(raw, dict):
        return ExtractionResult()
    facts: list[MemoryFact] = []
    for item in raw.get("facts", []):
        if not isinstance(item, dict) or not isinstance(item.get("value"), str):
            continue
        refs = item.get("source_refs", ())
        refs = refs if isinstance(refs, list) else ()
        facts.append(MemoryFact(item["value"], "llm_extraction", FACT_PRIORITY["llm_extraction"], _now(), tuple(str(ref) for ref in refs), bool(item.get("stale", False))))
    updates = raw.get("task_updates") if isinstance(raw.get("task_updates"), dict) else {}
    return ExtractionResult(tuple(facts), dict(updates))
