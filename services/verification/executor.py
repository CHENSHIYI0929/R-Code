"""Safe, observable execution of workspace verification commands."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shlex
import signal
import time
from typing import Any

from services.observability import TraceRecorder
from services.repair.types import CheckResult, VerificationReport
from services.verification.types import VerificationCommand, VerificationOutcome
from utils.toolResultStorage import ToolResultStorage

_SHELL_TOKENS = frozenset({"|", "||", "&&", ";", ">", ">>", "<", "<<", "&"})


def parse_verification_commands(raw_commands: object) -> tuple[VerificationCommand, ...]:
    """Parse legacy string config and preferred ``{argv: [...]}`` config.

    Strings remain supported when they are a single argv command. Shell syntax
    is deliberately rejected rather than silently executed through a shell.
    """

    if not isinstance(raw_commands, list):
        return ()
    commands: list[VerificationCommand] = []
    for item in raw_commands:
        if isinstance(item, str) and item.strip():
            commands.append(_parse_legacy_command(item))
        elif isinstance(item, dict):
            argv = item.get("argv")
            if isinstance(argv, list) and argv and all(isinstance(part, str) and part for part in argv):
                commands.append(VerificationCommand(" ".join(argv), tuple(argv)))
            else:
                commands.append(VerificationCommand("<invalid verification command>", configuration_error="verification command requires a non-empty string argv array"))
    return tuple(commands)


def _parse_legacy_command(command: str) -> VerificationCommand:
    try:
        argv = tuple(shlex.split(command, posix=os.name != "nt"))
    except ValueError as exc:
        return VerificationCommand(command, configuration_error=f"invalid verification command: {exc}")
    if not argv:
        return VerificationCommand(command, configuration_error="verification command is empty")
    if any(token in _SHELL_TOKENS or "$(`" in token or "$(" in token or "`" in token for token in argv):
        return VerificationCommand(command, configuration_error="shell operators and command substitution are unsupported; configure verification.commands with an argv object")
    return VerificationCommand(command, argv)


class VerificationExecutor:
    """Run checks inside one workspace and retain their combined output."""

    def __init__(
        self,
        workspace: Path,
        *,
        result_store: ToolResultStorage,
        trace_recorder: TraceRecorder | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.workspace = workspace.resolve()
        self.result_store = result_store
        self.trace_recorder = trace_recorder or TraceRecorder.noop()
        self.timeout_seconds = timeout_seconds

    def bind_result_store(self, result_store: ToolResultStorage) -> None:
        self.result_store = result_store

    async def execute(
        self,
        commands: tuple[VerificationCommand, ...],
        *,
        attempt: int,
    ) -> VerificationReport:
        checks = tuple([await self._run(command) for command in commands])
        full_output = "\n\n".join(f"$ {check.command}\n{check.output}" for check in checks)
        ref = self.result_store.persist_tool_result(
            tool_call_id=f"verification-{attempt}",
            tool_name="verification",
            content=full_output,
        )
        outcome = _aggregate_outcome(checks)
        status = "passed" if outcome == "passed" else ("failed" if outcome == "test_failed" else "blocked")
        self.trace_recorder.event(
            "verification_finished",
            {"attempt": attempt, "check_count": len(checks), "outcome": outcome, "status": status},
        )
        return VerificationReport(status, checks, fingerprint="", artifact_path=str(ref.absolute_path), outcome=outcome)

    async def _run(self, command: VerificationCommand) -> CheckResult:
        started = time.monotonic()
        if command.configuration_error:
            return _check(command, None, command.configuration_error, started, "environment_blocked")
        try:
            process = await asyncio.create_subprocess_exec(
                *command.argv,
                cwd=self.workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=os.name != "nt",
                **_windows_process_group_kwargs(),
            )
        except FileNotFoundError as exc:
            return _check(command, None, str(exc), started, "command_missing")
        except PermissionError as exc:
            return _check(command, None, str(exc), started, "permission_denied")
        except OSError as exc:
            return _check(command, None, str(exc), started, "environment_blocked")
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            await _stop_process_group(process)
            self.trace_recorder.event("verification_timeout", {"command": command.display, "timeout_seconds": self.timeout_seconds})
            return _check(command, None, f"Verification timed out after {self.timeout_seconds:g} seconds.", started, "timeout")
        output = stdout.decode("utf-8", errors="replace")
        return _check(command, process.returncode, output, started, _classify_exit(process.returncode, output))


def _windows_process_group_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(__import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0)}


async def _stop_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        return
    except asyncio.TimeoutError:
        pass
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    await process.wait()


def _check(command: VerificationCommand, exit_code: int | None, output: str, started: float, outcome: VerificationOutcome) -> CheckResult:
    status = "passed" if outcome == "passed" else ("failed" if outcome == "test_failed" else "blocked")
    return CheckResult(command.display, exit_code, output, int((time.monotonic() - started) * 1000), status, outcome)


def _classify_exit(exit_code: int, output: str) -> VerificationOutcome:
    if exit_code == 0:
        return "passed"
    lowered = output.lower()
    if exit_code == 126 or "permission denied" in lowered:
        return "permission_denied"
    if exit_code == 127 or "command not found" in lowered:
        return "command_missing"
    if "no module named pytest" in lowered or "no module named" in lowered and "pytest" in lowered:
        return "environment_blocked"
    return "test_failed"


def _aggregate_outcome(checks: tuple[CheckResult, ...]) -> VerificationOutcome:
    outcomes = {check.outcome or ("passed" if check.status == "passed" else "test_failed") for check in checks}
    for outcome in ("permission_denied", "command_missing", "environment_blocked", "timeout", "test_failed"):
        if outcome in outcomes:
            return outcome  # type: ignore[return-value]
    return "passed"
