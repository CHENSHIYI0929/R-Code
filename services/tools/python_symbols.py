"""Small, syntax-only Python symbol index for local source files."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class PythonSymbol:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int


def parse_symbols(source: str) -> tuple[PythonSymbol, ...]:
    """List definitions without resolving imports or building a code graph."""

    tree = ast.parse(source)
    found: list[PythonSymbol] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[tuple[str, bool]] = []

        def _definition(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> None:
            start = min((item.lineno for item in node.decorator_list), default=node.lineno)
            qualified = ".".join((*(name for name, _ in self.parents), node.name))
            found.append(PythonSymbol(node.name, qualified, kind, start, node.end_lineno or node.lineno))
            self.parents.append((node.name, isinstance(node, ast.ClassDef)))
            self.generic_visit(node)
            self.parents.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._definition(node, "class")

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._definition(node, "method" if self.parents and self.parents[-1][1] else "function")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._definition(node, "method" if self.parents and self.parents[-1][1] else "function")

    Visitor().visit(tree)
    return tuple(found)


def enclosing_symbol(symbols: tuple[PythonSymbol, ...], line: int) -> PythonSymbol | None:
    matches = (item for item in symbols if item.start_line <= line <= item.end_line)
    return min(matches, key=lambda item: (item.end_line - item.start_line, -item.start_line), default=None)
