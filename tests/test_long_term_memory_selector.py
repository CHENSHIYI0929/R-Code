from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from core.runtime_state import RuntimeState
from services.memory.auto_store import LongTermMemoryStore
from services.memory.context_preparer import RelevantMemoryContextPreparer
from services.memory.selector import RelevantMemorySelector
from services.memory.types import LongTermMemoryFile
from services.model.stream import ModelStreamEvent


class FakeModel:
    def __init__(self, text: str) -> None:
        self.text = text

    async def stream(self, snapshot) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.message_completed(
            assistant_message={"role": "assistant", "content": self.text},
            final_text=self.text,
        )


def test_selector_accepts_json_and_filters_unknown_items():
    catalog = tuple(
        LongTermMemoryFile(
            path=Path(f"{name}.md"),
            relative_path=f"{name}.md",
            name=name,
            description=name,
            type="project",
            mtime=1.0,
        )
        for name in ("a", "b", "c", "d", "e", "f")
    )
    selector = RelevantMemorySelector(
        FakeModel(
            '{"selected_memories":["a.md","missing.md","b.md","c.md","d.md","e.md","f.md"]}'
        )
    )

    selected = asyncio.run(
        selector.select(
            ({"role": "user", "content": "hello"},),
            RuntimeState(),
            catalog,
        )
    )

    assert [item.relative_path for item in selected] == [
        "a.md",
        "b.md",
        "c.md",
        "d.md",
        "e.md",
    ]


def test_selector_returns_empty_on_invalid_json():
    memory = LongTermMemoryFile(
        path=Path("a.md"),
        relative_path="a.md",
        name="a",
        description="a",
        type="project",
        mtime=1.0,
    )

    selected = asyncio.run(
        RelevantMemorySelector(FakeModel("not json")).select(
            (),
            RuntimeState(),
            (memory,),
        )
    )

    assert selected == ()


def test_retrieved_memory_attachment_has_audit_fields(tmp_path: Path):
    store = LongTermMemoryStore(tmp_path / "repo")
    store.ensure_exists()
    (store.memory_dir / "auth.md").write_text(
        "---\nname: Auth\ndescription: Authentication details\ntype: project\n---\nUse retry.",
        encoding="utf-8",
    )
    state = RuntimeState()
    preparer = RelevantMemoryContextPreparer(
        store,
        RelevantMemorySelector(FakeModel('{"selected_memories":["auth.md"]}')),
    )

    prepared = asyncio.run(
        preparer.prepare(({"role": "user", "content": "authentication"},), state)
    )

    attachment = prepared.messages[-1]
    assert attachment["metadata"]["source_refs"] == ["auth.md"]
    assert attachment["metadata"]["rank"] == 1
    assert attachment["metadata"]["selection_reason"] == "long_term_selector"
    assert state.metadata["long_term_memory_retrieval"] == [
        {
            "path": "auth.md",
            "source_refs": ["auth.md"],
            "rank": 1,
            "selection_reason": "long_term_selector",
        }
    ]
