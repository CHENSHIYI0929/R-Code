"""Provider-neutral benchmark runner; adapters own workspace/model setup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from benchmarks.repair_loop.types import BenchmarkCase, BenchmarkProfile, BenchmarkRun

RunCase = Callable[[BenchmarkCase, BenchmarkProfile], Awaitable[BenchmarkRun]]


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
            records.append(record)
    return tuple(records)
