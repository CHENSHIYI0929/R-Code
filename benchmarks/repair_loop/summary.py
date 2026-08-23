"""Aggregate repair benchmark records without a provider dependency."""

from __future__ import annotations

from collections import defaultdict
import statistics
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


def summarize_experiments(runs: tuple[BenchmarkRun, ...]) -> dict[str, dict[str, dict[str, dict[str, float | int | dict[str, int]]]]]:
    """Summarize each experiment/tier/profile separately; never manufacture a global score."""

    grouped: dict[tuple[str, str, str], list[BenchmarkRun]] = defaultdict(list)
    for run in runs:
        grouped[(run.experiment, run.tier, run.profile)].append(run)
    result: dict[str, dict[str, dict[str, dict[str, float | int | dict[str, int]]]]] = {}
    for (experiment, tier, profile), entries in grouped.items():
        aggregate: dict[str, float | int | dict[str, int]] = {
            "runs": len(entries),
            "success_rate": _rate(sum(item.success for item in entries), len(entries)),
            "resolved_rate": _rate(sum(item.resolved for item in entries), len(entries)),
            "failure_distribution": _distribution(item.failure_kind or "none" for item in entries),
            "run_status_distribution": _distribution(item.run_status for item in entries),
            "stop_reason_distribution": _distribution((item.event_summary.stop_reason if item.event_summary else item.terminal_outcome) for item in entries),
        }
        metric_names = sorted({name for entry in entries for name in (entry.metrics or {})})
        for name in metric_names:
            values = [entry.metrics[name] for entry in entries if entry.metrics and name in entry.metrics]
            numeric = [float(value) for value in values if isinstance(value, (int, float))]
            if numeric:
                mean = round(statistics.fmean(numeric), 4)
                aggregate[f"avg_{name}"] = mean
                aggregate[f"mean_{name}"] = mean
                aggregate[f"std_{name}"] = round(statistics.pstdev(numeric), 4) if len(numeric) > 1 else 0.0
                aggregate[f"range_{name}"] = round(max(numeric) - min(numeric), 4)
        result.setdefault(experiment, {}).setdefault(tier, {})[profile] = aggregate
    return result


def _distribution(values: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:  # type: ignore[union-attr]
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _average(values: Any) -> float:
    values = tuple(values)
    return round(sum(values) / len(values), 2) if values else 0.0
