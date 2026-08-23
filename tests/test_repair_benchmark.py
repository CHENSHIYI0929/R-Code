from __future__ import annotations

import asyncio

from benchmarks.repair_loop.runner import run_profiles
from benchmarks.repair_loop.profiles import repair_loop_policy
from benchmarks.repair_loop.summary import summarize_runs
from benchmarks.repair_loop.types import BenchmarkCase, PROFILES, BenchmarkRun


def test_benchmark_runner_covers_each_case_profile_pair_and_summarizes() -> None:
    case = BenchmarkCase("case-1", "python_bug_fix", "fix it", (("python", "-m", "pytest"),))

    async def run_case(received_case, profile):
        return BenchmarkRun(
            case_id=received_case.id,
            profile=profile.name,
            success=profile.name == "full",
            resolved=profile.name in {"parser", "full"},
            turns=2,
            tool_calls=3,
            tokens=100,
            latency_ms=50,
            verification_attempts=1 if profile.verification_enabled else 0,
            same_failure_repeats=0,
            terminal_outcome="pass",
        )

    records = asyncio.run(run_profiles((case,), PROFILES, run_case))
    summary = summarize_runs(records)

    assert [record.profile for record in records] == [profile.name for profile in PROFILES]
    assert summary["full"]["success_rate"] == 1.0
    assert summary["baseline"]["avg_verification_attempts"] == 0.0
    assert repair_loop_policy(PROFILES[-1]).enable_repository_retrieval is True
