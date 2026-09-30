"""Bounded workspace-only retrieval for a failed verification."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from services.repair.types import DiffHunk, FailureEvidence, FileCandidate, RepositorySnippet, RetrievalResult, SymbolCandidate
from services.tools.js_ts_symbols import parse_symbols as parse_js_ts_symbols
from services.tools.python_symbols import parse_symbols


RetrievalStrategy = Literal["text", "symbol", "failure_aware"]
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_IGNORED = frozenset({"assert", "error", "exception", "failed", "failure", "return", "test", "tests", "true", "false", "none", "expected", "actual"})


class RepositoryRetriever:
    def __init__(self, workspace: Path, *, max_snippets: int = 8) -> None:
        self.workspace = workspace.resolve()
        self.max_snippets = max_snippets

    def retrieve(
        self,
        evidence: tuple[FailureEvidence, ...],
        changed_files: tuple[str, ...],
        current_diff: tuple[DiffHunk, ...] = (),
    ) -> tuple[RepositorySnippet, ...]:
        return self.retrieve_ranked(evidence, changed_files, current_diff).snippets

    def retrieve_ranked(
        self,
        evidence: tuple[FailureEvidence, ...],
        changed_files: tuple[str, ...] = (),
        current_diff: tuple[DiffHunk, ...] = (),
        *,
        strategy: RetrievalStrategy = "failure_aware",
    ) -> RetrievalResult:
        """Return bounded ranked candidates plus the compatible snippet view."""

        file_scores: dict[str, tuple[float, set[str], int | None]] = {}
        symbol_scores: dict[tuple[str, str], SymbolCandidate] = {}

        def add_file(raw_path: str, score: float, signal: str, line: int | None = None) -> None:
            relative = self._relative_path(raw_path)
            if relative is None:
                return
            previous_score, signals, previous_line = file_scores.get(relative, (0.0, set(), None))
            contribution = 0.0 if signal in signals else score
            signals.add(signal)
            file_scores[relative] = (previous_score + contribution, signals, previous_line or line)

        changed = {relative for path in changed_files if (relative := self._relative_path(path)) is not None}
        for item in evidence:
            if item.file_path:
                add_file(item.file_path, 100.0 + (35.0 if self._relative_path(item.file_path) in changed else 0.0), "stack_trace", item.line)
        if strategy == "failure_aware":
            for hunk in current_diff:
                add_file(hunk.path, 140.0, "current diff hunk", hunk.start_line)
                if hunk.symbol:
                    symbol_scores[(hunk.path, hunk.symbol)] = SymbolCandidate(
                        hunk.path,
                        hunk.symbol,
                        "unknown",
                        hunk.start_line,
                        hunk.end_line,
                        140.0,
                        ("failure_feedback_diff",),
                    )
            for path in changed_files:
                add_file(path, 75.0, "changed_file")

        tokens = self._query_tokens(evidence)
        for path in self._source_files():
            relative = path.relative_to(self.workspace).as_posix()
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lowered = source.lower()
            matches = tuple(token for token in tokens if token.lower() in lowered)
            if matches:
                add_file(relative, min(60.0, 8.0 * len(matches)), "grep_text")
            if strategy == "text":
                continue
            try:
                symbols = parse_symbols(source) if path.suffix in {".py", ".pyi"} else parse_js_ts_symbols(source)
            except SyntaxError:
                continue
            evidence_symbols = {item.symbol.split(".")[-1] for item in evidence if item.symbol}
            for symbol in symbols:
                exact = symbol.name in evidence_symbols or symbol.name.lower() in {token.lower() for token in tokens}
                if not exact:
                    continue
                score = 95.0 + (30.0 if relative in changed and strategy == "failure_aware" else 0.0)
                signal = "ast_symbol" if path.suffix in {".py", ".pyi"} else "structural_symbol"
                candidate = SymbolCandidate(relative, symbol.qualified_name, symbol.kind, symbol.start_line, symbol.end_line, score, (signal,))
                prior = symbol_scores.get((relative, symbol.qualified_name))
                if prior is None or candidate.score > prior.score:
                    symbol_scores[(relative, symbol.qualified_name)] = candidate
                add_file(relative, 45.0, signal, symbol.start_line)

        files = tuple(
            FileCandidate(path, round(score, 3), tuple(sorted(signals)))
            for path, (score, signals, _line) in sorted(file_scores.items(), key=lambda item: (-item[1][0], item[0]))[: self.max_snippets * 4]
        )
        symbols = tuple(sorted(symbol_scores.values(), key=lambda item: (-item.score, item.path, item.start_line)))[: self.max_snippets * 4]
        selected: list[RepositorySnippet] = []
        used: set[tuple[str, int]] = set()
        for candidate in files:
            _score, _signals, line = file_scores[candidate.path]
            self._add_path(selected, used, candidate.path, line, ", ".join(candidate.signals))
        return RetrievalResult(files, symbols, tuple(selected[: self.max_snippets]))

    def _source_files(self) -> tuple[Path, ...]:
        found: list[Path] = []
        for path in sorted(self.workspace.rglob("*"), key=lambda item: item.as_posix()):
            if len(found) >= 240:
                break
            if path.is_file() and ".onecode" not in path.parts and path.suffix in {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx"}:
                found.append(path)
        return tuple(found)

    @staticmethod
    def _query_tokens(evidence: tuple[FailureEvidence, ...]) -> tuple[str, ...]:
        values: list[str] = []
        for item in evidence:
            values.extend((item.message, item.symbol or "", item.exception_type or "", item.test_node_id or ""))
        tokens = {match.group(0) for value in values for match in _TOKEN.finditer(value) if match.group(0).lower() not in _IGNORED}
        tokens.update(part for token in tuple(tokens) for part in token.split("_") if len(part) >= 3 and part.lower() not in _IGNORED)
        return tuple(sorted(tokens, key=lambda value: (-len(value), value))[:24])

    def _relative_path(self, raw_path: str) -> str | None:
        path = (self.workspace / raw_path).resolve()
        try:
            return path.relative_to(self.workspace).as_posix()
        except ValueError:
            return None

    def _add_path(self, selected: list[RepositorySnippet], used: set[tuple[str, int]], raw_path: str, line: int | None, reason: str) -> None:
        if len(selected) >= self.max_snippets:
            return
        path = (self.workspace / raw_path).resolve()
        try:
            relative = path.relative_to(self.workspace)
        except ValueError:
            return
        if not path.is_file() or ".onecode" in relative.parts:
            return
        start = max(1, (line or 1) - 8)
        key = (relative.as_posix(), start)
        if key in used:
            return
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        excerpt = lines[start - 1 : min(len(lines), start + 23)]
        if not excerpt:
            return
        used.add(key)
        selected.append(RepositorySnippet(relative.as_posix(), start, start + len(excerpt) - 1, "\n".join(excerpt), reason))

    def _add_symbol_hits(self, selected: list[RepositorySnippet], used: set[tuple[str, int]], symbol: str) -> None:
        if not symbol or len(selected) >= self.max_snippets:
            return
        scanned = 0
        for path in self.workspace.rglob("*"):
            if scanned >= 120 or len(selected) >= self.max_snippets:
                return
            if not path.is_file() or ".onecode" in path.parts or path.suffix not in {".py", ".ts", ".js"}:
                continue
            scanned += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for index, value in enumerate(lines, 1):
                if symbol in value:
                    self._add_path(selected, used, str(path.relative_to(self.workspace)), index, f"reference to failure symbol {symbol}")
                    break
