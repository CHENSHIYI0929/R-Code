from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from core.context_engine import ContextEngine
from core.loop import AgentLoop
from core.runtime_state import RuntimeState
from core.transitions import TransitionReason
from services.attachments.types import AttachmentMessage
from services.context.message_store import MessageStore
from services.model.stream import ModelStreamEvent


@dataclass
class _Model:
    responses: list[str]
    calls: int = 0

    async def stream(self, snapshot):
        del snapshot
        self.calls += 1
        text = self.responses.pop(0)
        yield ModelStreamEvent.message_completed(
            assistant_message={"role": "assistant", "content": text},
            final_text=text,
        )


class _Executor:
    async def execute(self, tool_calls, state):
        del tool_calls, state
        if False:
            yield None


class _Gate:
    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, state, *, final_text, assistant_message):
        del state, final_text, assistant_message
        self.calls += 1
        if self.calls == 1:
            return type("Decision", (), {"outcome": "continue", "message": "failed", "attachment": AttachmentMessage({"type": "repair_feedback", "attempt": 1}).to_message()})()
        return type("Decision", (), {"outcome": "pass", "message": "passed", "attachment": None})()


def test_failed_candidate_finish_retries_with_repair_context_then_verifies(tmp_path: Path) -> None:
    state = RuntimeState()
    store = MessageStore.ephemeral(session_id=state.session_id)
    model = _Model(["first finish", "verified finish"])
    gate = _Gate()
    loop = AgentLoop(
        state=state,
        message_store=store,
        context_engine=ContextEngine(store),
        model_client=model,
        tool_executor=_Executor(),
        finish_gate=gate,
    )

    async def collect():
        return [event async for event in loop.stream("fix it")]

    events = asyncio.run(collect())

    assert model.calls == 2
    assert gate.calls == 2
    assert TransitionReason.VERIFICATION_FAILED_RETRY.value in [event.transition for event in events]
    assert events[-1].metadata["verification_outcome"] == "pass"
    assert state.last_transition == TransitionReason.COMPLETED_VERIFIED
    assert any(message.get("attachment", {}).get("type") == "repair_feedback" for message in store.current_messages())
