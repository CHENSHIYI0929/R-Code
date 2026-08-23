from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from services.verification.executor import VerificationExecutor, parse_verification_commands
from utils.toolResultStorage import ToolResultStorage


def _executor(tmp_path: Path, *, timeout_seconds: float = 1.0) -> VerificationExecutor:
    return VerificationExecutor(tmp_path, result_store=ToolResultStorage(tmp_path / "session"), timeout_seconds=timeout_seconds)


def test_legacy_command_becomes_argv_without_a_shell(tmp_path: Path) -> None:
    commands = parse_verification_commands([f"{sys.executable} -c 'print(\"ok\")'"])

    report = asyncio.run(_executor(tmp_path).execute(commands, attempt=1))

    assert report.status == "passed"
    assert report.outcome == "passed"
    assert report.artifact_path is not None and Path(report.artifact_path).is_file()


def test_shell_syntax_is_blocked_instead_of_being_executed(tmp_path: Path) -> None:
    commands = parse_verification_commands(["python -m pytest && echo unsafe"])

    report = asyncio.run(_executor(tmp_path).execute(commands, attempt=1))

    assert report.status == "blocked"
    assert report.outcome == "environment_blocked"
    assert "shell operators" in report.checks[0].output


def test_missing_command_is_classified_as_environment_problem(tmp_path: Path) -> None:
    report = asyncio.run(_executor(tmp_path).execute(parse_verification_commands([{"argv": ["missing"]}]), attempt=1))

    assert report.status == "blocked"
    assert report.outcome == "command_missing"


def test_timeout_is_classified_and_process_is_reaped(tmp_path: Path) -> None:
    command = parse_verification_commands([{"argv": [sys.executable, "-c", "import time; time.sleep(10)"]}])

    report = asyncio.run(_executor(tmp_path, timeout_seconds=0.05).execute(command, attempt=1))

    assert report.status == "blocked"
    assert report.outcome == "timeout"
    assert report.checks[0].exit_code is None
