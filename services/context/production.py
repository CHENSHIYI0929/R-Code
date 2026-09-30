"""Shared production ContextEngine composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.context_engine import ContextEngine
from prompts.assembler import DynamicPromptAssembler
from services.attachments import AttachmentContextPreparer
from services.context.message_store import MessageStore
from services.context.task_state import TaskState
from services.context.task_state_preparer import TaskStateContextPreparer
from services.memory import RelevantMemoryContextPreparer


def build_production_context_engine(
    *,
    workspace: Path,
    message_store: MessageStore,
    registry: Any,
    compaction_service: Any | None,
    skill_provider: Any | None = None,
    instruction_memory_loader: Any | None = None,
    long_term_memory_provider: Any | None = None,
    long_term_memory_store: Any | None = None,
    memory_selector: Any | None = None,
    task_state: TaskState | None = None,
) -> ContextEngine:
    """Build the context path used by production CLI and benchmarks.

    Optional capabilities are disabled by passing ``None``; the assembler,
    preparer ordering, attachment projection, and tool-schema path remain the
    same rather than falling back to a benchmark-specific implementation.
    """

    inner = compaction_service
    if long_term_memory_store is not None and memory_selector is not None:
        inner = RelevantMemoryContextPreparer(
            long_term_memory_store,
            memory_selector,
            inner=inner,
        )
    preparer: Any = AttachmentContextPreparer(inner)
    if task_state is not None:
        preparer = TaskStateContextPreparer(task_state, inner=preparer)
    return ContextEngine(
        message_store,
        prompt_assembler=DynamicPromptAssembler(
            workspace,
            tool_registry=registry,
            skill_provider=skill_provider,
            instruction_memory_loader=instruction_memory_loader,
            long_term_memory_provider=long_term_memory_provider,
        ),
        tool_schema_provider=registry,
        context_preparer=preparer,
    )
