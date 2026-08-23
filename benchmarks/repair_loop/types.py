"""Durable records for repair-loop ablation experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class BenchmarkProfile:
    name: Literal["baseline", "verification_only", "parser", "full"]
    verification_enabled: bool
    failure_parser_enabled: bool
    repository_retrieval_enabled: bool


PROFILES: tuple[BenchmarkProfile, ...] = (
    BenchmarkProfile("baseline", False, False, False),
    BenchmarkProfile("verification_only", True, False, False),
    BenchmarkProfile("parser", True, True, False),
    BenchmarkProfile("full", True, True, True),
)


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    category: Literal["python_bug_fix", "pytest_failure_repair", "missing_implementation", "regression_repair"]
    prompt: str
    verification: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class BenchmarkRun:
    case_id: str
    profile: str
    success: bool
    resolved: bool
    turns: int
    tool_calls: int
    tokens: int
    latency_ms: int
    verification_attempts: int
    same_failure_repeats: int
    terminal_outcome: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
