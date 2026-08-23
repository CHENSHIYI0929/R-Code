"""Run the frozen executable benchmark suite and persist reproducible evidence.

Examples:
    uv run python -m benchmarks.repair_loop.run_final_evaluation --tier scripted
    uv run python -m benchmarks.repair_loop.run_final_evaluation --tier real_model
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from typing import Iterable

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition
from benchmarks.repair_loop.experiments import context_compaction, harness_regression, repair_loop, resume_recovery, session_memory
from benchmarks.repair_loop.real_model import RealModelAdapter
from benchmarks.repair_loop.runner import run_experiment
from benchmarks.repair_loop.scripted import scripted_adapter
from benchmarks.repair_loop.summary import summarize_experiments
from benchmarks.repair_loop.types import BenchmarkRun


SUITE: tuple[tuple[ExperimentDefinition, tuple[CaseContract, ...]], ...] = (
    (harness_regression.DEFINITION, harness_regression.CASES),
    (repair_loop.DEFINITION, repair_loop.CASES),
    (context_compaction.DEFINITION, context_compaction.CASES),
    (session_memory.DEFINITION, session_memory.CASES),
    (resume_recovery.DEFINITION, resume_recovery.CASES),
)


async def run_suite(*, tier: str, repetitions: int, env_path: Path, output: Path) -> tuple[BenchmarkRun, ...]:
    output.mkdir(parents=True, exist_ok=True)
    real_adapter = RealModelAdapter(env_path, artifact_root=output / "artifacts") if tier == "real_model" else None
    all_runs: list[BenchmarkRun] = []
    for repetition in range(1, repetitions + 1):
        for definition, cases in SUITE:
            profiles = tuple(dict.fromkeys(case.profile for case in cases))
            runs = await run_experiment(
                definition,
                cases,
                profiles,
                real_adapter if real_adapter is not None else scripted_adapter,
                tier=tier,  # type: ignore[arg-type]
                model=real_adapter.model_label if real_adapter is not None else "scripted",
                decoding_params=real_adapter.decoding_params if real_adapter is not None else {},
                feature_flags={"frozen_suite": True, "repetition": bool(repetition)},
            )
            all_runs.extend(replace(run, metrics={**(run.metrics or {}), "repetition": repetition}) for run in runs)
    report = {
        "scope": "synthetic_fixture",
        "tier": tier,
        "repetitions": repetitions,
        "summary": summarize_experiments(tuple(all_runs)),
        "runs": [run.to_dict() for run in all_runs],
    }
    (output / f"{tier}-synthetic-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return tuple(all_runs)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("scripted", "real_model"), required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/final-evaluation"))
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    asyncio.run(run_suite(tier=args.tier, repetitions=args.repetitions, env_path=args.env, output=args.output))


if __name__ == "__main__":
    main()
