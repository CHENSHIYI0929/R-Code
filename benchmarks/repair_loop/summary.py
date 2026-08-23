"""Aggregate repair benchmark records without a provider dependency."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from benchmarks.repair_loop.types import BenchmarkRun


def summarize_runs(runs: tuple[BenchmarkRun, ...]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[BenchmarkRun]] = defaultdict(list)
    for run in runs:
        grouped[run.profile].append(run)
    summary: dict[str, dict[str, float | int]] = {}
    for profile, entries in grouped.items():
        total = len(entries)
        summary[profile] = {
            "runs": total,
            "success_rate": _rate(sum(item.success for item in entries), total),
            "resolved_rate": _rate(sum(item.resolved for item in entries), total),
            "avg_turns": _average(item.turns for item in entries),
            "avg_tool_calls": _average(item.tool_calls for item in entries),
            "avg_tokens": _average(item.tokens for item in entries),
            "avg_latency_ms": _average(item.latency_ms for item in entries),
            "avg_verification_attempts": _average(item.verification_attempts for item in entries),
            "avg_same_failure_repeats": _average(item.same_failure_repeats for item in entries),
        }
    return summary


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _average(values: Any) -> float:
    values = tuple(values)
    return round(sum(values) / len(values), 2) if values else 0.0
