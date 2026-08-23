"""Shared contracts for independently interpretable benchmark experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvaluationTier = Literal["scripted", "real_model"]


@dataclass(frozen=True)
class FixtureSpec:
    """Files and settings copied into one fresh workspace for a case run."""

    files: dict[str, str] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseContract:
    """A falsifiable case: setup, required metrics, pass rule, and failure labels."""

    id: str
    experiment: str
    profile: str
    pass_condition: str
    required_metrics: tuple[str, ...]
    failure_taxonomy: tuple[str, ...]
    fixture: FixtureSpec = field(default_factory=FixtureSpec)
    scripted_metrics: dict[str, int | float | bool] = field(default_factory=dict)
    scripted_success: bool = True
    scripted_resolved: bool = True
    scripted_terminal_outcome: str = "pass"
    scripted_failure_kind: str | None = None


@dataclass(frozen=True)
class ExperimentDefinition:
    """One claim and its non-interchangeable metric vocabulary."""

    name: str
    description: str
    required_metrics: tuple[str, ...]
    failure_taxonomy: tuple[str, ...]
    supports_scripted: bool = True
    supports_real_model: bool = True
