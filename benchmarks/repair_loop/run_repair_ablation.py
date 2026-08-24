from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from benchmarks.repair_loop.experiments.repair_loop import CASES, DEFINITION
from benchmarks.repair_loop.real_model import RealModelAdapter
from benchmarks.repair_loop.runner import run_experiment
from benchmarks.repair_loop.summary import summarize_experiments


async def main() -> None:
    output = Path("benchmark-results/repair-ablation")
    adapter = RealModelAdapter(".env", artifact_root=output / "artifacts", max_model_calls=8, max_tool_steps=8, max_wall_clock_seconds=120)
    rows = []
    for repetition in range(1, 4):
        runs = await run_experiment(DEFINITION, CASES, tuple(case.profile for case in CASES), adapter, tier="real_model", model=adapter.model_label, decoding_params=adapter.decoding_params, feature_flags={"controlled_navigation_prompt": True, "stream": True})
        rows.extend(replace(run, metrics={**(run.metrics or {}), "repetition": repetition}) for run in runs)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps({"runs": [row.to_dict() for row in rows], "summary": summarize_experiments(tuple(rows))}, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
