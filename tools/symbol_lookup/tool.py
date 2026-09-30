"""Guarded Python AST localization tool."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from services.tools.python_symbols import enclosing_symbol, parse_symbols
from services.tools.types import (
    ToolCallClassification, ToolDescriptor, ToolExecutionResult, ToolResultPolicy,
    ToolRuntime, ToolTarget, ValidationResult, is_guard_policy_allowed,
)
from tools.symbol_lookup.prompt import PROMPT
from utils.text_io import decode_text


INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string"},
        "name": {"type": "string"},
        "line": {"type": "integer", "minimum": 1},
    },
    "required": ["file_path"],
    "additionalProperties": False,
}


def descriptor() -> ToolDescriptor:
    return ToolDescriptor(
        name="symbol_lookup",
        description="Locate Python classes, functions, and methods with ast.",
        input_schema=INPUT_SCHEMA,
        handler=_handle,
        prompt=PROMPT,
        search_hint="locate Python definitions by name or line",
        validate_input=_validate,
        classify_input=_classify,
    )


def _validate(tool_input: dict[str, Any], runtime: ToolRuntime) -> ValidationResult:
    del runtime
    if not tool_input["file_path"].strip():
        return ValidationResult.failure("file_path must not be empty.")
    if "name" in tool_input and not tool_input["name"].strip():
        return ValidationResult.failure("name must not be empty.")
    line = tool_input.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        return ValidationResult.failure("line must be a positive integer.")
    return ValidationResult.success()


def _classify(tool_input: dict[str, Any], runtime: ToolRuntime) -> ToolCallClassification:
    del runtime
    path = tool_input["file_path"]
    return ToolCallClassification(
        read_only=True,
        modifies_filesystem=False,
        concurrency_safe=True,
        targets=(ToolTarget(kind="file", operation="read", value=path),),
        result_policy=ToolResultPolicy(max_result_size_chars=20_000, persist_when_exceeded=True),
        permission_subject=f"symbol_lookup:{path}",
    )


def _handle(tool_input: dict[str, Any], runtime: ToolRuntime) -> ToolExecutionResult:
    if runtime.guard is None:
        raise RuntimeError("symbol_lookup requires a sandbox guard.")
    policy = runtime.guard.check_path(tool_input["file_path"], operation="read")
    if not is_guard_policy_allowed(policy, runtime):
        payload = policy.to_tool_error()
        if policy.action == "ask":
            payload["error"] = "path_guard_ask_required"
        return ToolExecutionResult("", "symbol_lookup", json.dumps(payload), True, metadata={"error": payload["error"]})
    path = policy.normalized_path
    if path.suffix != ".py" or not path.is_file():
        return ToolExecutionResult("", "symbol_lookup", "Target must be an existing Python file.", True, metadata={"error": "not_python_file"})
    data = path.read_bytes()
    if len(data) > 1_000_000:
        return ToolExecutionResult("", "symbol_lookup", "Python file is too large for AST lookup; use text search.", True, metadata={"error": "file_too_large"})
    try:
        symbols = parse_symbols(decode_text(data))
    except SyntaxError as exc:
        return ToolExecutionResult("", "symbol_lookup", f"Python syntax error at line {exc.lineno}: {exc.msg}", True, metadata={"error": "syntax_error", "line": exc.lineno})
    name = tool_input.get("name")
    line = tool_input.get("line")
    if name:
        symbols = tuple(item for item in symbols if item.name == name or item.qualified_name == name)
    if line is not None:
        match = enclosing_symbol(symbols, line)
        symbols = (match,) if match else ()
    payload = {
        "path": str(path),
        "symbols": [{"path": str(path), **item.__dict__} for item in symbols[:100]],
        "truncated": len(symbols) > 100,
    }
    return ToolExecutionResult("", "symbol_lookup", json.dumps(payload, ensure_ascii=False), metadata={"path": str(path), "fingerprint": {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}})
