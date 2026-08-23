from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec
from benchmarks.repair_loop.events import summarize_events
from benchmarks.repair_loop.experiments import (
    context_compaction,
    harness_regression,
    hook_policy,
    long_term_memory,
    repair_loop,
    resume_recovery,
    session_memory,
    tool_result_store,
)
from benchmarks.repair_loop.runner import run_experiment
from benchmarks.repair_loop.scripted import run_scripted
from benchmarks.repair_loop.summary import summarize_experiments
from benchmarks.repair_loop.types import BenchmarkRun


@pytest.mark.parametrize(
    "module",
    (harness_regression, repair_loop, context_compaction, session_memory, long_term_memory, resume_recovery),
)
def test_priority_experiments_run_scripted_cases_and_publish_required_metrics(module) -> None:
    records = asyncio.run(run_scripted(module.DEFINITION, module.CASES))

    assert records
    for record in records:
        assert record.tier == "scripted"
        assert set(module.DEFINITION.required_metrics) <= set(record.metrics or {})
        assert record.experiment == module.DEFINITION.name


def test_runner_creates_distinct_fixture_workspace_for_each_case_profile(tmp_path: Path) -> None:
    definition = ExperimentDefinition("fixture_isolation", "fixture isolation", ("observed",), ("fixture_error",))
    cases = (
        CaseContract("one", definition.name, "profile", "file exists", definition.required_metrics, definition.failure_taxonomy, FixtureSpec({"data.txt": "one"}), {"observed": 1}),
        CaseContract("two", definition.name, "profile", "file exists", definition.required_metrics, definition.failure_taxonomy, FixtureSpec({"data.txt": "two"}), {"observed": 1}),
    )
    seen: list[Path] = []

    async def adapter(case, profile, workspace, tier):
        seen.append(workspace)
        assert (workspace / "data.txt").read_text(encoding="utf-8") == case.id
        return BenchmarkRun(case.id, profile, True, True, 0, 0, 0, 0, 0, 0, "pass", experiment=definition.name, tier=tier, metrics={"observed": 1})

    records = asyncio.run(run_experiment(definition, cases, ("profile",), adapter, workspace_root=tmp_path))

    assert len(records) == 2
    assert len(set(seen)) == 2
    assert all(not path.exists() for path in seen)


def test_layered_summary_keeps_experiments_separate() -> None:
    records = asyncio.run(run_scripted(session_memory.DEFINITION, session_memory.CASES)) + asyncio.run(run_scripted(long_term_memory.DEFINITION, long_term_memory.CASES))

    summary = summarize_experiments(records)

    assert set(summary) == {"session_memory", "long_term_memory"}
    assert "memory_on" in summary["session_memory"]["scripted"]
    assert "retrieval_on" in summary["long_term_memory"]["scripted"]
    assert "avg_fact_recall" in summary["session_memory"]["scripted"]["memory_on"]


@pytest.mark.parametrize("module", (tool_result_store, hook_policy))
def test_non_priority_experiments_publish_contracts(module) -> None:
    assert module.CASES
    assert module.DEFINITION.required_metrics
    assert all(case.failure_taxonomy for case in module.CASES)


def test_runner_rejects_missing_required_metric() -> None:
    definition = ExperimentDefinition("metric_validation", "metric validation", ("required",), ("bad",))
    case = CaseContract("missing", definition.name, "profile", "requires metric", definition.required_metrics, definition.failure_taxonomy)

    async def adapter(case, profile, workspace, tier):
        return BenchmarkRun(case.id, profile, True, True, 0, 0, 0, 0, 0, 0, "pass", experiment=definition.name, tier=tier, metrics={})

    with pytest.raises(ValueError, match="missing metrics"):
        asyncio.run(run_experiment(definition, (case,), ("profile",), adapter))


def test_runner_rejects_failure_outside_the_case_taxonomy() -> None:
    definition = ExperimentDefinition("taxonomy", "taxonomy", ("metric",), ("known_failure",))
    case = CaseContract("unknown", definition.name, "profile", "failure must be classified", definition.required_metrics, definition.failure_taxonomy)

    async def adapter(case, profile, workspace, tier):
        return BenchmarkRun(case.id, profile, False, False, 0, 0, 0, 0, 0, 0, "error", experiment=definition.name, tier=tier, metrics={"metric": 1}, failure_kind="unknown_failure", run_status="error")

    with pytest.raises(ValueError, match="unknown failure kind"):
        asyncio.run(run_experiment(definition, (case,), ("profile",), adapter))


def test_run_gets_reproducible_metadata_and_event_explanations() -> None:
    definition = ExperimentDefinition("metadata", "metadata", ("trace_events",), ("error",))
    case = CaseContract("record", definition.name, "profile", "record metadata", definition.required_metrics, definition.failure_taxonomy)

    async def adapter(case, profile, workspace, tier):
        events = summarize_events(
            trace_records=({"name": "transition", "attributes": {"transition": "completed_verified"}},),
            tool_events=({"type": "tool_result"},),
            hook_events=({"type": "post_tool_use"},),
            memory_events=({"type": "memory_updated"},),
        )
        return BenchmarkRun(case.id, profile, True, True, 1, 1, 1, 1, 0, 0, "pass", experiment=definition.name, tier=tier, metrics={}, event_summary=events)

    records = asyncio.run(run_experiment(definition, (case,), ("profile",), adapter, model="fake-model", decoding_params={"temperature": 0}, feature_flags={"memory": True}))

    record = records[0]
    assert record.metadata is not None
    assert record.metadata.model == "fake-model"
    assert record.metadata.feature_flags["memory"] is True
    assert record.metadata.fixture_hash
    assert record.metrics is not None and record.metrics["trace_events"] == 1
    assert record.event_summary is not None and record.event_summary.stop_reason == "completed_verified"


def test_summary_separates_tiers_and_reports_stability_and_failures() -> None:
    runs = (
        BenchmarkRun("a", "p", True, True, 0, 0, 0, 0, 0, 0, "pass", experiment="stability", tier="real_model", metrics={"latency": 10}, run_status="completed"),
        BenchmarkRun("b", "p", False, False, 0, 0, 0, 0, 0, 0, "blocked", experiment="stability", tier="real_model", metrics={"latency": 14}, run_status="blocked", failure_kind="timeout"),
        BenchmarkRun("c", "p", True, True, 0, 0, 0, 0, 0, 0, "pass", experiment="stability", tier="scripted", metrics={"latency": 1}),
    )

    summary = summarize_experiments(runs)

    real = summary["stability"]["real_model"]["p"]
    assert real["mean_latency"] == 12.0
    assert real["std_latency"] == 2.0
    assert real["range_latency"] == 4.0
    assert real["failure_distribution"] == {"none": 1, "timeout": 1}
    assert real["run_status_distribution"] == {"completed": 1, "blocked": 1}
