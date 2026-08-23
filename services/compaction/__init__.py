"""Context compaction helpers and service types."""

from services.compaction.service import ContextCompactionService
from services.compaction.session_memory import (
    FileFingerprint,
    FileSummary,
    ExtractionResult,
    MemoryFact,
    SessionMemory,
    SessionMemoryExtractionDecision,
    SessionMemoryExtractionJob,
    SessionMemoryExtractionPolicy,
    SessionMemoryExtractionService,
    SessionMemoryStore,
    SessionMemoryState,
    SessionMemoryUpdater,
    count_tool_calls,
    should_extract_memory,
)
from services.compaction.session_memory_hooks import SessionMemoryToolUpdater
from services.compaction.token_estimator import (
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_snapshot_tokens,
)
from services.compaction.types import (
    CompactBoundary,
    CompactionConfig,
    CompactionResult,
    CompactionTrigger,
)

__all__ = [
    "CompactBoundary",
    "CompactionConfig",
    "CompactionResult",
    "CompactionTrigger",
    "ContextCompactionService",
    "FileFingerprint",
    "FileSummary",
    "ExtractionResult",
    "MemoryFact",
    "SessionMemory",
    "SessionMemoryExtractionDecision",
    "SessionMemoryExtractionJob",
    "SessionMemoryExtractionPolicy",
    "SessionMemoryExtractionService",
    "SessionMemoryStore",
    "SessionMemoryState",
    "SessionMemoryUpdater",
    "SessionMemoryToolUpdater",
    "count_tool_calls",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "estimate_snapshot_tokens",
    "should_extract_memory",
]
