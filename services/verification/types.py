"""Provider-neutral verification command records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VerificationOutcome = Literal[
    "passed",
    "test_failed",
    "command_missing",
    "environment_blocked",
    "timeout",
    "permission_denied",
]


@dataclass(frozen=True)
class VerificationCommand:
    """A validated command expressed as argv, never a shell program."""

    display: str
    argv: tuple[str, ...] = ()
    configuration_error: str | None = None

