"""Provider-neutral benchmark runner; adapters own workspace/model setup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from benchmarks.repair_loop.contracts import CaseContract, EvaluationTier, ExperimentDefinition, FixtureSpec
from benchmarks.repair_loop.fixtures import fixture_workspace
from benchmarks.repair_loop.metadata import collect_metadata, with_fixture
from benchmarks.repair_loop.types import BenchmarkCase, BenchmarkProfile, BenchmarkRun

RunCase = Callable[[BenchmarkCase, BenchmarkProfile], Awaitable[BenchmarkRun]]
RunExperimentCase = Callable[[CaseContract, str, Path, EvaluationTier], Awaitable[BenchmarkRun]]


async def run_profiles(
    cases: tuple[BenchmarkCase, ...],
    profiles: tuple[BenchmarkProfile, ...],
    run_case: RunCase,
) -> tuple[BenchmarkRun, ...]:
    """Run every case/profile pair in deterministic order."""

    records: list[BenchmarkRun] = []
    for profile in profiles:
        for case in cases:
            record = await run_case(case, profile)
            if record.case_id != case.id or record.profile != profile.name:
                raise ValueError("benchmark adapter returned a record for a different case or profile")
            legacy_fixture = FixtureSpec(files={"benchmark-case.json": json.dumps({"id": case.id, "prompt": case.prompt, "verification": case.verification}, sort_keys=True)})
            records.append(replace(record, metadata=record.metadata or collect_metadata(legacy_fixture, model="scripted" if record.tier == "scripted" else "unspecified", feature_flags={f"profile:{profile.name}": True})))
    return tuple(records)


async def run_experiment(
    definition: ExperimentDefinition,
    cases: tuple[CaseContract, ...],
    profiles: tuple[str, ...],
    adapter: RunExperimentCase,
    *,
    workspace_root: Path | None = None,
    tier: EvaluationTier = "scripted",
    model: str | None = None,
    decoding_params: dict[str, Any] | None = None,
    feature_flags: dict[str, bool] | None = None,
) -> tuple[BenchmarkRun, ...]:
    """Run independent case/profile fixtures without mixing experiment claims."""

    if tier == "scripted" and not definition.supports_scripted:
        raise ValueError(f"{definition.name} does not support scripted evaluation")
    if tier == "real_model" and not definition.supports_real_model:
        raise ValueError(f"{definition.name} does not support real-model evaluation")
    records: list[BenchmarkRun] = []
    for profile in profiles:
        for case in cases:
            if case.experiment != definition.name or case.profile != profile:
                continue
            with fixture_workspace(case.fixture, root=workspace_root) as workspace:
                record = await adapter(case, profile, workspace, tier)
            metadata = record.metadata or collect_metadata(
                case.fixture,
                model=model or ("scripted" if tier == "scripted" else "unspecified"),
                decoding_params=decoding_params,
                feature_flags={**(feature_flags or {}), f"profile:{profile}": True},
            )
            record = replace(record, metadata=with_fixture(metadata, case.fixture))
            if record.event_summary is not None:
                event_metrics = {
                    name: value
                    for name, value in record.event_summary.metrics().items()
                    if isinstance(value, (int, float, bool))
                }
                record = replace(record, metrics={**(record.metrics or {}), **event_metrics})
            _validate_record(definition, case, profile, record, tier)
            records.append(record)
    return tuple(records)


def _validate_record(definition: ExperimentDefinition, case: CaseContract, profile: str, record: BenchmarkRun, tier: EvaluationTier) -> None:
    if (record.experiment, record.case_id, record.profile, record.tier) != (definition.name, case.id, profile, tier):
        raise ValueError("benchmark adapter returned a record with mismatched experiment, case, profile, or tier")
    metric_names = set(record.metrics or {})
    required = set(definition.required_metrics) | set(case.required_metrics)
    missing = required - metric_names
    if missing:
        raise ValueError(f"benchmark record is missing metrics: {', '.join(sorted(missing))}")
    allowed_failures = set(definition.failure_taxonomy) | set(case.failure_taxonomy) | {"provider_timeout", "invalid_response", "model_call_budget_exceeded", "tool_budget_exceeded", "wall_clock_budget_exceeded", "provider_error"}
    if not record.success:
        if record.failure_kind is None:
            raise ValueError("an unsuccessful benchmark record requires failure_kind")
        if record.terminal_outcome in {"pass", "completed_verified"}:
            raise ValueError("an unsuccessful benchmark record cannot have a pass terminal outcome")
    if record.failure_kind is not None and record.failure_kind not in allowed_failures:
        raise ValueError(f"benchmark record has an unknown failure kind: {record.failure_kind}")
    if record.metadata is None:
        raise ValueError("benchmark record is missing reproducibility metadata")
