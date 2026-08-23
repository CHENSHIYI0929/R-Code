"""Hook adapter for deterministic session-memory updates."""

from __future__ import annotations

from typing import Any

from services.compaction.session_memory import SessionMemoryStore
from services.hooks import HookResult


class SessionMemoryToolUpdater:
    def __init__(self, store: SessionMemoryStore) -> None:
        self._store = store

    def on_tool_result(self, payload: dict[str, Any]) -> HookResult:
        try:
            self._store.update_from_tool_payload(payload)
            return HookResult()
        except Exception as exc:
            return HookResult(metadata={"session_memory_tool_update_error": type(exc).__name__})
