"""Dependency-free, tolerant JavaScript/TypeScript symbol indexing.

This is intentionally a structural index rather than a compiler.  It extracts
the declarations that are useful for repository localization while continuing
to work on incomplete files produced during an edit.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class JavaScriptSymbol:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int


_DECLARATION = re.compile(
    r"(?m)^[ \t]*(?:export\s+(?:default\s+)?)?(?:(async)\s+)?(function|class)\s+([A-Za-z_$][\w$]*)"
)
_VARIABLE = re.compile(
    r"(?ms)^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"(?:\s*:[^=\n]+)?\s*=\s*(?:async\s+)?"
    r"(?:\([^;{}]{0,400}?\)|[A-Za-z_$][\w$]*)(?:\s*:\s*[^=\n]+)?\s*=>"
)
_CALLBACK = re.compile(
    r"(?m)^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"(?:\s*:[^=\n]+)?\s*=\s*(?:React\.)?(useCallback|useMemo)\s*\("
)
_METHOD = re.compile(
    r"(?m)^[ \t]*(?:(?:public|private|protected|static|readonly|abstract|async|get|set)\s+)*"
    r"([A-Za-z_$][\w$]*)\s*(?:<[^>{}]+>)?\s*\([^;{}]*\)\s*(?::\s*[^={]+)?\s*\{"
)


def parse_symbols(source: str) -> tuple[JavaScriptSymbol, ...]:
    """Return useful JS/TS declarations without requiring Node or tree-sitter."""

    masked = _mask_comments_and_strings(source)
    lines = _line_starts(source)
    raw: list[tuple[str, str, int, int]] = []

    for match in _DECLARATION.finditer(masked):
        kind = "class" if match.group(2) == "class" else "function"
        raw.append((match.group(3), kind, match.start(), _declaration_end(masked, match.end())))
    for match in _VARIABLE.finditer(masked):
        raw.append((match.group(1), "arrow_function", match.start(), _declaration_end(masked, match.end())))
    for match in _CALLBACK.finditer(masked):
        raw.append((match.group(1), "callback", match.start(), _declaration_end(masked, match.end())))

    classes = tuple(item for item in raw if item[1] == "class")
    for class_name, _kind, class_start, class_end in classes:
        body_start = masked.find("{", class_start, class_end + 1)
        if body_start < 0:
            continue
        for match in _METHOD.finditer(masked, body_start + 1, class_end):
            name = match.group(1)
            if name in {"if", "for", "while", "switch", "catch", "function"}:
                continue
            raw.append((name, f"method:{class_name}", match.start(), _declaration_end(masked, match.end())))

    # Deduplicate callback patterns that also matched the general arrow rule.
    unique: dict[tuple[str, int], tuple[str, str, int, int]] = {}
    for item in raw:
        key = (item[0], item[2])
        prior = unique.get(key)
        if prior is None or item[1] == "callback":
            unique[key] = item

    containers = sorted(unique.values(), key=lambda item: (item[2], -(item[3] - item[2])))
    found: list[JavaScriptSymbol] = []
    for name, kind, start, end in containers:
        if kind.startswith("method:"):
            parent = kind.split(":", 1)[1]
            public_kind = "method"
        else:
            parents = [item for item in containers if item[2] < start < item[3] and item[1] in {"function", "arrow_function", "callback"}]
            parent = min(parents, key=lambda item: item[3] - item[2])[0] if parents else ""
            public_kind = kind
        qualified = f"{parent}.{name}" if parent else name
        found.append(JavaScriptSymbol(name, qualified, public_kind, _line_number(lines, start), _line_number(lines, end)))
    return tuple(sorted(found, key=lambda item: (item.start_line, item.end_line, item.name)))


def _declaration_end(masked: str, search_from: int) -> int:
    brace = masked.find("{", search_from)
    newline = masked.find("\n", search_from)
    if brace < 0 or (newline >= 0 and brace > newline + 400):
        return newline if newline >= 0 else len(masked)
    depth = 0
    for index in range(brace, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(masked)


def _line_starts(source: str) -> tuple[int, ...]:
    return (0, *(index + 1 for index, value in enumerate(source) if value == "\n"))


def _line_number(starts: tuple[int, ...], offset: int) -> int:
    import bisect

    return bisect.bisect_right(starts, offset)


def _mask_comments_and_strings(source: str) -> str:
    """Preserve offsets/newlines while hiding comments and quoted contents."""

    chars = list(source)
    index = 0
    state: str | None = None
    while index < len(chars):
        char = chars[index]
        nxt = chars[index + 1] if index + 1 < len(chars) else ""
        if state is None and char == "/" and nxt == "/":
            state = "line_comment"
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        if state is None and char == "/" and nxt == "*":
            state = "block_comment"
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        if state is None and char in {"'", '"', "`"}:
            state = char
            chars[index] = " "
            index += 1
            continue
        if state == "line_comment":
            if char == "\n":
                state = None
            else:
                chars[index] = " "
        elif state == "block_comment":
            if char == "*" and nxt == "/":
                chars[index] = chars[index + 1] = " "
                state = None
                index += 1
            elif char != "\n":
                chars[index] = " "
        elif state in {"'", '"', "`"}:
            if char == "\\":
                chars[index] = " "
                if index + 1 < len(chars) and chars[index + 1] != "\n":
                    chars[index + 1] = " "
                    index += 1
            elif char == state:
                chars[index] = " "
                state = None
            elif char != "\n":
                chars[index] = " "
        index += 1
    return "".join(chars)
