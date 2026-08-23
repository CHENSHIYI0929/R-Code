from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.runtime_state import RuntimeState
from services.repair import FailureParser, RepairLoopGate, RepositoryRetriever
from services.repair.fingerprint import fingerprint_failure
from utils.toolResultStorage import ToolResultStorage


def test_failure_parser_extracts_pytest_path_line_node_and_exception() -> None:
    output = "FAILED tests/test_widget.py::test_empty - AssertionError: expected []\nwidgets/parser.py:42: ValueError: empty input"

    evidence = FailureParser().parse(output)

    assert evidence[0].test_node_id == "tests/test_widget.py::test_empty"
    assert any(item.file_path == "widgets/parser.py" and item.line == 42 for item in evidence)
    assert any(item.exception_type == "ValueError" for item in evidence)


def test_retriever_returns_evidence_and_changed_file_snippets(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "parser.py"
    source.write_text("one\ntwo\nraise ValueError('bad')\nfour\n", encoding="utf-8")
    evidence = FailureParser().parse("src/parser.py:3: ValueError: bad")

    snippets = RepositoryRetriever(tmp_path).retrieve(evidence, ("src/parser.py",))

    assert snippets
    assert snippets[0].path == "src/parser.py"
    assert "ValueError" in snippets[0].content


def test_gate_failure_creates_repair_attachment_and_artifact(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / ".onecode").mkdir()
    (tmp_path / ".onecode" / "settings.json").write_text(
        json.dumps({"verification": {"commands": ["python -c 'import sys; print(\"src/a.py:4: AssertionError: bad\"); sys.exit(1)'" ]}}),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\ny\nz\nraise AssertionError\n", encoding="utf-8")
    state = RuntimeState()
    state.metadata["files_changed"] = ["src/a.py"]
    gate = RepairLoopGate(tmp_path, result_store=ToolResultStorage(tmp_path / "session"))

    decision = asyncio.run(gate.evaluate(state, final_text="done", assistant_message=None))

    assert decision.outcome == "continue"
    assert decision.attachment is not None
    payload = decision.attachment["attachment"]
    assert payload["type"] == "repair_feedback"
    assert Path(payload["artifact_path"]).is_file()


def test_gate_passes_only_after_configured_check_succeeds(tmp_path: Path) -> None:
    (tmp_path / ".onecode").mkdir()
    (tmp_path / ".onecode" / "settings.json").write_text(
        json.dumps({"verification": {"commands": ["python -c 'print(\"ok\")'" ]}}),
        encoding="utf-8",
    )
    state = RuntimeState()
    state.metadata["files_changed"] = ["src/a.py"]
    gate = RepairLoopGate(tmp_path, result_store=ToolResultStorage(tmp_path / "session"))

    decision = asyncio.run(gate.evaluate(state, final_text="done", assistant_message=None))

    assert decision.outcome == "pass"
    assert decision.report is not None and decision.report.status == "passed"


def test_gate_blocks_environment_failure_without_requesting_code_repair(tmp_path: Path) -> None:
    (tmp_path / ".onecode").mkdir()
    (tmp_path / ".onecode" / "settings.json").write_text(
        json.dumps({"verification": {"commands": [{"argv": ["definitely-not-a-command"]}]}}),
        encoding="utf-8",
    )
    state = RuntimeState()
    state.metadata["files_changed"] = ["src/a.py"]

    decision = asyncio.run(RepairLoopGate(tmp_path, result_store=ToolResultStorage(tmp_path / "session")).evaluate(state, final_text="done", assistant_message=None))

    assert decision.outcome == "blocked"
    assert decision.report is not None and decision.report.outcome == "command_missing"


def test_failure_fingerprint_ignores_ephemeral_temp_path_and_large_number() -> None:
    first = FailureParser().parse("FAILED tests/test_x.py::test_x - ValueError: /tmp/run-1234/cache 20240101")
    second = FailureParser().parse("FAILED tests/test_x.py::test_x - ValueError: /tmp/run-9876/cache 20250909")

    assert fingerprint_failure(first, outcome="test_failed") == fingerprint_failure(second, outcome="test_failed")
