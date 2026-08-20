"""Bounded workspace-only retrieval for a failed verification."""

from __future__ import annotations

from pathlib import Path

from services.repair.types import FailureEvidence, RepositorySnippet


class RepositoryRetriever:
    def __init__(self, workspace: Path, *, max_snippets: int = 8) -> None:
        self.workspace = workspace.resolve()
        self.max_snippets = max_snippets

    def retrieve(
        self,
        evidence: tuple[FailureEvidence, ...],
        changed_files: tuple[str, ...],
    ) -> tuple[RepositorySnippet, ...]:
        selected: list[RepositorySnippet] = []
        used: set[tuple[str, int]] = set()
        for item in evidence:
            if item.file_path:
                self._add_path(selected, used, item.file_path, item.line, "verification evidence")
        for path in changed_files:
            self._add_path(selected, used, path, None, "changed in this session")
        symbols = tuple(item.symbol for item in evidence if item.symbol)
        for symbol in symbols:
            self._add_symbol_hits(selected, used, symbol)
        return tuple(selected[: self.max_snippets])

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
