from __future__ import annotations

import asyncio
from pathlib import Path

from core.runtime_state import RuntimeState
from services.context.message_store import MessageStore
from services.guard import SandboxBoundary, SandboxGuard
from services.tools.executor import RegistryToolExecutor
from services.tools.registry import ToolRegistry
from services.tools.types import ToolCall
from tools.read_file import descriptor as read_file_descriptor
from ui.cli.resume import restore_session_state


def _read_result(workspace: Path) -> tuple[dict, MessageStore]:
    state = RuntimeState(session_id="fingerprint")
    store = MessageStore(transcript_root=workspace / ".onecode" / "sessions", session_id=state.session_id, cwd=workspace, flush_interval_seconds=60)
    executor = RegistryToolExecutor(ToolRegistry((read_file_descriptor(),)), guard=SandboxGuard(SandboxBoundary(cwd=workspace)))

    async def run():
        return [update.result async for update in executor.execute((ToolCall("read", "read_file", {"file_path": "state.py"}),), state) if update.result]

    result = asyncio.run(run())[0]
    store.append_tool_results([result])
    return store.current_messages()[0], store


def test_resume_marks_changed_fingerprinted_read_untrusted(tmp_path: Path) -> None:
    target = tmp_path / "state.py"; target.write_text("VERSION = 1\n", encoding="utf-8")
    message, store = _read_result(tmp_path)
    target.write_text("VERSION = 2\n", encoding="utf-8")
    state = RuntimeState()
    restore_session_state(state, (message,), message_store=store)
    restored = store.current_messages()[0]
    assert restored["metadata"]["trust_status"] == "stale"
    assert "VERSION = 1" not in restored["content"]
    assert str(target) not in state.metadata.get("files_read", set())


def test_resume_marks_deleted_fingerprinted_read_untrusted(tmp_path: Path) -> None:
    target = tmp_path / "state.py"; target.write_text("VERSION = 1\n", encoding="utf-8")
    message, store = _read_result(tmp_path)
    target.unlink()
    state = RuntimeState()
    restore_session_state(state, (message,), message_store=store)
    assert store.current_messages()[0]["metadata"]["trust_status"] == "missing"


def test_resume_keeps_legacy_read_without_fingerprint(tmp_path: Path) -> None:
    target = str(tmp_path / "state.py")
    store = MessageStore.ephemeral(session_id="legacy")
    store.append_tool_results([])
    state = RuntimeState()
    legacy = {"role": "tool_result", "tool_name": "read_file", "tool_call_id": "old", "content": "1\tlegacy", "is_error": False, "metadata": {"path": target, "offset": 1}}
    restore_session_state(state, (legacy,), message_store=store)
    assert "restored_read_status" not in state.metadata
