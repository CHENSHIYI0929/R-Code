"""Deterministic adapter for fast regression checks without a model provider."""

from __future__ import annotations

from pathlib import Path

from benchmarks.repair_loop.contracts import CaseContract, EvaluationTier, ExperimentDefinition
from benchmarks.repair_loop.runtime_adapter import executable_adapter
from benchmarks.repair_loop.runner import run_experiment
from benchmarks.repair_loop.types import BenchmarkRun


async def scripted_adapter(case: CaseContract, profile: str, workspace: Path, tier: EvaluationTier) -> BenchmarkRun:
    """Run deterministic model output through the real R-Code runtime."""

    if tier != "scripted":
        raise ValueError("scripted_adapter cannot evaluate a real model")
    if not workspace.is_dir():
        raise AssertionError("benchmark fixture workspace was not created")
    return await executable_adapter(case, profile, workspace, tier)


async def run_scripted(definition: ExperimentDefinition, cases: tuple[CaseContract, ...]) -> tuple[BenchmarkRun, ...]:
    profiles = tuple(dict.fromkeys(case.profile for case in cases))
    return await run_experiment(definition, cases, profiles, scripted_adapter)
