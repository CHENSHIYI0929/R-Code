"""Provider-neutral records used by the verification repair loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from services.verification.types import VerificationOutcome


VerificationStatus = Literal["passed", "failed", "blocked", "skipped"]


@dataclass(frozen=True)
class CheckResult:
    command: str
    exit_code: int | None
    output: str
    duration_ms: int
    status: VerificationStatus
    outcome: VerificationOutcome | None = None


@dataclass(frozen=True)
class VerificationReport:
    status: VerificationStatus
    checks: tuple[CheckResult, ...]
    fingerprint: str
    artifact_path: str | None = None
    outcome: VerificationOutcome | None = None


@dataclass(frozen=True)
class FailureEvidence:
    category: str
    message: str
    file_path: str | None = None
    line: int | None = None
    symbol: str | None = None
    test_node_id: str | None = None
    exception_type: str | None = None


@dataclass(frozen=True)
class RepositorySnippet:
    path: str
    start_line: int
    end_line: int
    content: str
    reason: str


@dataclass(frozen=True)
class FileCandidate:
    path: str
    score: float
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class SymbolCandidate:
    path: str
    symbol: str
    kind: str
    start_line: int
    end_line: int
    score: float
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalResult:
    files: tuple[FileCandidate, ...] = ()
    symbols: tuple[SymbolCandidate, ...] = ()
    snippets: tuple[RepositorySnippet, ...] = ()


@dataclass(frozen=True)
class DiffHunk:
    path: str
    start_line: int
    end_line: int
    symbol: str | None = None


@dataclass(frozen=True)
class RepairContextBundle:
    attempt: int
    report: VerificationReport
    evidence: tuple[FailureEvidence, ...]
    snippets: tuple[RepositorySnippet, ...]
    changed_files: tuple[str, ...]
    current_diff: tuple[DiffHunk, ...] = ()
    candidate_files: tuple[FileCandidate, ...] = ()
    candidate_symbols: tuple[SymbolCandidate, ...] = ()
