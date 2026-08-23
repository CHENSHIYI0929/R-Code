from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from benchmarks.repair_loop.provider_smoke import run_smoke


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--timeout-seconds", type=float, default=45)
    parser.add_argument("--max-model-calls", type=int, default=12)
    parser.add_argument("--max-tool-steps", type=int, default=12)
    parser.add_argument("--max-wall-clock-seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/provider-smoke.json"))
    args = parser.parse_args()
    async def run():
        return {mode: await run_smoke(env_path=args.env, mode=mode, timeout_seconds=args.timeout_seconds, max_model_calls=args.max_model_calls, max_tool_steps=args.max_tool_steps, max_wall_clock_seconds=args.max_wall_clock_seconds) for mode in ("nonstream", "stream")}
    result = asyncio.run(run())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
