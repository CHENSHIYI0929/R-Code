"""Project a bounded task-state view while retaining the durable transcript."""

from __future__ import annotations

import inspect
from typing import Any, Iterable

from core.runtime_state import RuntimeState
from services.context.snapshot import PreparedContext
from services.context.task_state import TaskPhase, TaskState


_SEARCH_TOOLS = frozenset({"glob", "grep", "search", "symbol_lookup"})
_NAVIGATION_AND_EDIT_TOOLS = frozenset({"glob", "grep", "search", "symbol_lookup", "read_file", "edit_file", "write_file", "filewrite"})


class TaskStateContextPreparer:
    def __init__(self, task_state: TaskState, inner: Any | None = None) -> None:
        self.task_state = task_state
        self.inner = inner

    async def prepare(self, messages: tuple[dict[str, Any], ...], state: RuntimeState) -> PreparedContext:
        if getattr(getattr(state, "last_transition", None), "value", None) == "verification_failed_retry":
            self.task_state.mark_edit_ready()
        hidden = set(state.metadata.get("phase_hidden_tools", ()))
        hidden.difference_update(_NAVIGATION_AND_EDIT_TOOLS)
        if self.task_state.phase == TaskPhase.EDIT_READY:
            hidden.update(_SEARCH_TOOLS)
        elif self.task_state.phase == TaskPhase.VERIFY:
            hidden.update(_NAVIGATION_AND_EDIT_TOOLS)
        state.metadata["phase_hidden_tools"] = tuple(sorted(hidden))
        state.metadata["task_phase"] = self.task_state.phase.value

        prepared: Iterable[dict[str, Any]] | PreparedContext = messages
        if self.inner is not None:
            prepared = self.inner.prepare(messages, state)
            if inspect.isawaitable(prepared):
                prepared = await prepared
        usage_hints: dict[str, Any] = {}
        transcript_refs: tuple[str, ...] = ()
        if isinstance(prepared, PreparedContext):
            projected = tuple(prepared.messages)
            usage_hints = dict(prepared.usage_hints)
            transcript_refs = tuple(prepared.transcript_refs)
        else:
            projected = tuple(prepared)

        output: list[dict[str, Any]] = []
        replaced_navigation_hint = False
        for message in projected:
            content = message.get("content")
            if (
                isinstance(content, str)
                and content.startswith("[first-pass localization hint]")
                and (self.task_state.confirmed_evidence or self.task_state.action_counts)
            ):
                if not replaced_navigation_hint:
                    output.append(_task_state_message(self.task_state))
                    replaced_navigation_hint = True
                continue
            output.append(message)
        if self.task_state.confirmed_evidence and not replaced_navigation_hint:
            output.append(_task_state_message(self.task_state))
        return PreparedContext(tuple(output), usage_hints=usage_hints, transcript_refs=transcript_refs)


def _task_state_message(task_state: TaskState) -> dict[str, Any]:
    return {
        "role": "user",
        "content": task_state.render(),
        "metadata": {
            "synthetic": True,
            "source": "task_state",
            "task_phase": task_state.phase.value,
        },
    }
