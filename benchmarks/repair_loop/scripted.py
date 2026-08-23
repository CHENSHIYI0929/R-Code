"""Deterministic adapter for fast regression checks without a model provider."""

from __future__ import annotations

from pathlib import Path

from benchmarks.repair_loop.contracts import CaseContract, EvaluationTier, ExperimentDefinition
from benchmarks.repair_loop.runner import run_experiment
from benchmarks.repair_loop.types import BenchmarkRun


async def scripted_adapter(case: CaseContract, profile: str, workspace: Path, tier: EvaluationTier) -> BenchmarkRun:
    """Return the declared deterministic observation after proving the fixture exists."""

    if tier != "scripted":
        raise ValueError("scripted_adapter cannot evaluate a real model")
    if not workspace.is_dir():
        raise AssertionError("benchmark fixture workspace was not created")
    metrics = dict(case.scripted_metrics)
    return BenchmarkRun(
        case_id=case.id,
        profile=profile,
        success=case.scripted_success,
        resolved=case.scripted_resolved,
        turns=int(metrics.get("turns", 0)),
        tool_calls=int(metrics.get("tool_calls", 0)),
        tokens=int(metrics.get("tokens", 0)),
        latency_ms=int(metrics.get("latency", metrics.get("latency_ms", 0))),
        verification_attempts=int(metrics.get("verification_attempts", 0)),
        same_failure_repeats=int(metrics.get("repeated_failures", metrics.get("same_failure_repeats", 0))),
        terminal_outcome=case.scripted_terminal_outcome,
        experiment=case.experiment,
        tier=tier,
        metrics=metrics,
        failure_kind=case.scripted_failure_kind,
    )


async def run_scripted(definition: ExperimentDefinition, cases: tuple[CaseContract, ...]) -> tuple[BenchmarkRun, ...]:
    profiles = tuple(dict.fromkeys(case.profile for case in cases))
    return await run_experiment(definition, cases, profiles, scripted_adapter)
