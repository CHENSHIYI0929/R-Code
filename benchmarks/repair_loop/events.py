"""Normalize R-Code events into explanatory benchmark metrics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkEventSummary:
    trace_events: int = 0
    tool_events: int = 0
    hook_events: int = 0
    memory_events: int = 0
    error_events: int = 0
    stop_reason: str = "unknown"

    def metrics(self) -> dict[str, int | str]:
        return {"trace_events": self.trace_events, "tool_events": self.tool_events, "hook_events": self.hook_events, "memory_events": self.memory_events, "error_events": self.error_events, "stop_reason": self.stop_reason}


def summarize_events(*, trace_records: Iterable[Mapping[str, Any]] = (), tool_events: Iterable[Mapping[str, Any]] = (), hook_events: Iterable[Mapping[str, Any]] = (), memory_events: Iterable[Mapping[str, Any]] = (), stop_reason: str | None = None) -> BenchmarkEventSummary:
    traces, tools, hooks, memories = tuple(trace_records), tuple(tool_events), tuple(hook_events), tuple(memory_events)
    errors = sum(1 for item in (*traces, *tools, *hooks, *memories) if _is_error(item))
    return BenchmarkEventSummary(len(traces), len(tools), len(hooks), len(memories), errors, stop_reason or _last_stop_reason(traces) or "unknown")


def _is_error(item: Mapping[str, Any]) -> bool:
    name = str(item.get("name", item.get("type", ""))).lower()
    attributes = item.get("attributes", item.get("metadata", {}))
    return "error" in name or "failed" in name or (isinstance(attributes, Mapping) and bool(attributes.get("error_type")))


def _last_stop_reason(records: tuple[Mapping[str, Any], ...]) -> str | None:
    for item in reversed(records):
        if item.get("name") in {"transition", "completed"}:
            attributes = item.get("attributes", {})
            if isinstance(attributes, Mapping):
                return str(attributes.get("transition", attributes.get("verification_outcome", ""))) or None
    return None
