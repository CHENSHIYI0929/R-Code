"""Bounded diff locations and AST associations for the current session."""

from __future__ import annotations

from dataclasses import replace
import difflib
from pathlib import Path

from services.repair.types import DiffHunk, FailureEvidence
from services.tools.python_symbols import enclosing_symbol, parse_symbols

MAX_DIFF_FILE_CHARS = 200_000


def current_diff_hunks(workspace: Path, baselines: dict[str, str | None], changed_files: tuple[str, ...]) -> tuple[DiffHunk, ...]:
    root = workspace.resolve()
    hunks: list[DiffHunk] = []
    for raw_path in changed_files[:40]:
        path = (root / raw_path).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if ".onecode" in relative.parts or not path.is_file():
            continue
        before = baselines.get(str(path))
        if before is None or len(before) > MAX_DIFF_FILE_CHARS:
            continue
        try:
            after = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(after) > MAX_DIFF_FILE_CHARS:
            continue
        old_lines, new_lines = before.splitlines(), after.splitlines()
        if max(len(old_lines), len(new_lines)) > 5_000:
            continue
        symbols = ()
        if path.suffix == ".py":
            try:
                symbols = parse_symbols(after)
            except SyntaxError:
                pass
        for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            start = min(max(1, j1 + 1), max(1, len(new_lines)))
            end = max(start, j2)
            symbol = enclosing_symbol(symbols, start)
            hunks.append(DiffHunk(relative.as_posix(), start, end, symbol.qualified_name if symbol else None))
            if len(hunks) >= 80:
                return tuple(hunks)
    return tuple(hunks)


def associate_evidence_symbols(workspace: Path, evidence: tuple[FailureEvidence, ...]) -> tuple[FailureEvidence, ...]:
    root = workspace.resolve()
    enriched: list[FailureEvidence] = []
    for item in evidence:
        if not item.file_path or not item.line or not item.file_path.endswith(".py"):
            enriched.append(item)
            continue
        path = (root / item.file_path).resolve()
        try:
            relative = path.relative_to(root)
            if ".onecode" in relative.parts:
                raise ValueError("internal path")
            source = path.read_text(encoding="utf-8", errors="replace")
            if len(source) > MAX_DIFF_FILE_CHARS:
                raise ValueError("file too large")
            symbols = parse_symbols(source)
        except (ValueError, OSError, SyntaxError):
            enriched.append(item)
            continue
        symbol = enclosing_symbol(symbols, item.line)
        enriched.append(replace(item, symbol=symbol.qualified_name) if symbol else item)
    return tuple(enriched)
