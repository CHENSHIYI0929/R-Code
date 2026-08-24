"""Run frozen real-repository cases through the executable R-Code runtime.

The evaluator is intentionally outside the agent workspace.  The agent receives
only a public issue summary and a clean base checkout; it never receives the
official patch, target file, or verifier implementation.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Iterable

from benchmarks.repair_loop.contracts import CaseContract
from benchmarks.repair_loop.provider_smoke import BoundedSmokeClient
from benchmarks.repair_loop.real_model import _timed_collect
from benchmarks.repair_loop.runtime_adapter import _record, _runtime
from benchmarks.repair_loop.summary import summarize_experiments
from benchmarks.repair_loop.types import BenchmarkRun
from infrastructure.providers.factory import resolve_config
from infrastructure.providers.http import HttpxAsyncHttpTransport


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks" / "real_repo" / "smoke_manifest.json"
CACHE_ROOTS = {
    "pallets/click": Path("/private/tmp/r-code-real-repo-click"),
    "pallets/jinja": Path("/private/tmp/r-code-real-repo-jinja-515"),
    "pallets/werkzeug": Path("/private/tmp/r-code-real-repo-werkzeug-2467"),
}
PY310 = "/private/tmp/r-code-real-repo-werkzeug-2467/.venv/bin/python"
PY39 = "/private/tmp/r-code-real-repo-jinja-515/.venv39/bin/python"
PYCLICK = "/private/tmp/r-code-real-repo-click/.venv/bin/python"

# These are concise, frozen renderings of public issue descriptions. They do
# not name a target file, PR, verifier, or expected patch.
ISSUE_INPUTS = {
    "click-2939": "Click's CliRunner pipeline aborts when input is exhausted. Preserve normal pipeline output and avoid an unexpected exception.",
    "jinja-515": "URL encoding query-string values must escape slash characters instead of leaving them unescaped.",
    "werkzeug-2465": "A documented public routing API import is no longer available. Restore the documented public API behavior.",
    "werkzeug-2467": "With strict slashes disabled, a leaf route should match its trailing-slash form when no more-specific route exists.",
    "werkzeug-2471": "Routing should prefer the route with the correct static path weighting rather than an overly general alternative.",
    "werkzeug-2485": "Inspecting an unbound LocalProxy for wrapped-object metadata should not raise a request-context-style runtime error.",
    "werkzeug-2985": "Stringifying request environment headers incorrectly produces an empty-looking result; preserve the rendered headers.",
    "werkzeug-2993": "URL host construction mishandles bare IPv6 server addresses and must produce a valid host representation.",
    "werkzeug-2994": "MultiDict-style constructors must treat bytes as one value rather than expanding bytes into integers.",
    "werkzeug-2988": "TypeConversionDict.get must accept a conversion callable in its public type signature.",
}


def _command(case_id: str, workspace: Path) -> tuple[list[str], dict[str, str]]:
    code: dict[str, str] = {
        "click-2939": "import click; from click.testing import CliRunner; "
        "cli=click.Group(chain=True,invoke_without_command=True); "
        "cli.params.append(click.Option(['-f'],type=click.File('r'))); "
        "exec(\"@cli.result_callback()\\ndef p(ps,f):\\n i=(x.rstrip('\\\\r\\\\n') for x in f)\\n [click.echo(x) for x in i]\\n\"); "
        "r=CliRunner().invoke(cli,['-f','-'],input='foo\\nbar'); "
        "print(repr(r.exception),repr(r.output)); raise SystemExit(0 if not r.exception and r.output.splitlines()==['foo','bar'] else 1)",
        "jinja-515": "from jinja2.utils import unicode_urlencode; v=unicode_urlencode('/',for_qs=True); print(repr(v)); raise SystemExit(v!='%2F')",
        "werkzeug-2465": "from werkzeug.routing import ValidationError; print(ValidationError.__name__)",
        "werkzeug-2467": "from werkzeug.routing import Map,Rule; m=Map([Rule('/path',endpoint='leaf')],strict_slashes=False); v=m.bind('example.org','/').match('/path/',method='GET'); print(repr(v)); raise SystemExit(v!=('leaf',{}))",
        "werkzeug-2471": "from werkzeug.routing import Map,Rule; m=Map([Rule('/<path:path>/c',endpoint='simple'),Rule('/<path:path>/<a>/<b>',endpoint='complex')]); v=m.bind('localhost',path_info='/a/b/c').match(); print(repr(v)); raise SystemExit(v!=('simple',{'path':'a/b'}))",
        "werkzeug-2485": "from contextvars import ContextVar; from werkzeug.local import LocalProxy; c=ContextVar('v'); p=LocalProxy(c); v=p.__wrapped__; print(repr(v)); raise SystemExit(v is not c)",
        "werkzeug-2985": "from werkzeug.datastructures import EnvironHeaders; v=str(EnvironHeaders({'CONTENT_LENGTH':'50','HTTP_HOST':'test'})); print(repr(v)); raise SystemExit(v!='Content-Length: 50\\r\\nHost: test\\r\\n\\r\\n')",
        "werkzeug-2993": "from werkzeug.sansio.utils import get_host; v=get_host('http',None,('::1',8080)); print(repr(v)); raise SystemExit(v!='[::1]:8080')",
        "werkzeug-2994": "from werkzeug.datastructures import iter_multi_items; v=list(iter_multi_items({'a':b'ab'})); print(repr(v)); raise SystemExit(v!=[('a',b'ab')])",
    }
    env = dict(os.environ)
    if case_id == "jinja-515":
        python = PY39
        env["PYTHONPATH"] = str(workspace)
    elif case_id == "click-2939":
        python = PYCLICK
        env["PYTHONPATH"] = str(workspace / "src")
    elif case_id == "werkzeug-2988":
        oracle = workspace.parent / "evaluator-oracle.py"
        oracle.write_text("from werkzeug.datastructures import TypeConversionDict\n\ndef parse_int(value: str) -> int:\n    return int(value)\ndata: TypeConversionDict[str, str] = TypeConversionDict()\nresult: int | None = data.get('foo', type=parse_int)\n", encoding="utf-8")
        env["MYPYPATH"] = str(workspace / "src")
        return [PY310, "-m", "mypy", "--config-file", "/dev/null", "--python-version", "3.10", "--follow-imports=silent", "--no-incremental", str(oracle)], env
    else:
        python = PY310
        env["PYTHONPATH"] = str(workspace / "src")
    return [python, "-c", code[case_id]], env


def _checkout(case: dict[str, Any], parent: Path) -> Path:
    source = CACHE_ROOTS[str(case["repo"])]
    workspace = parent / "workspace"
    subprocess.run(["git", "-C", str(source), "worktree", "add", "--detach", str(workspace), str(case["base_commit"])], check=True, capture_output=True, text=True)
    return workspace


def _remove_worktree(case: dict[str, Any], workspace: Path) -> None:
    source = CACHE_ROOTS[str(case["repo"])]
    subprocess.run(["git", "-C", str(source), "worktree", "remove", "--force", str(workspace)], check=False, capture_output=True, text=True)


async def _run_case(case: dict[str, Any], *, adapter: BoundedSmokeClient, output: Path, repetition: int) -> BenchmarkRun:
    with tempfile.TemporaryDirectory(prefix=f"r-code-{case['case_id']}-", dir="/private/tmp") as directory:
        parent = Path(directory)
        workspace = _checkout(case, parent)
        try:
            state, store, trace, errors, loop, _memory = _runtime(workspace, adapter)
            prompt = "You are fixing a bug in this repository. Use the available navigation tools to locate the cause, make the smallest correct source change, then give a final answer.\n\nIssue:\n" + ISSUE_INPUTS[str(case["case_id"])]
            # A real-repo smoke must have a hard, short per-case budget. The
            # bounded client separately caps each provider call at 25 seconds.
            events, elapsed = await _timed_collect(loop, prompt, max_tool_steps=8, max_wall_clock_seconds=75)
            command, environment = _command(str(case["case_id"]), workspace)
            verifier = subprocess.run(command, cwd=workspace, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            diff = subprocess.run(["git", "diff", "--exit-code"], cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            benchmark_error = state.metadata.get("benchmark_error")
            success = verifier.returncode == 0
            failure = None if success else (str(benchmark_error) if benchmark_error else ("no_patch" if diff.returncode == 0 else "verifier_failed"))
            contract = CaseContract(str(case["case_id"]), "real_repo", "full", "hidden verifier passes", ("task_success",), ("provider_timeout", "invalid_response", "model_call_budget_exceeded", "tool_budget_exceeded", "wall_clock_budget_exceeded", "no_patch", "verifier_failed"))
            record = _record(contract, "full", state, store, trace, errors, events, elapsed, success=success, resolved=success, failure_kind=failure, tier="real_model", extra={"task_success": success, "verification_attempts": 1, "verifier_returncode": verifier.returncode, "repetition": repetition})
            destination = output / "artifacts" / str(case["case_id"]) / str(repetition)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "verifier.txt").write_text(verifier.stdout, encoding="utf-8")
            (destination / "patch.diff").write_text(diff.stdout, encoding="utf-8")
            if (workspace / ".onecode").exists():
                shutil.copytree(workspace / ".onecode", destination / ".onecode")
            (destination / "record.json").write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return record
        finally:
            _remove_worktree(case, workspace)


async def run(*, repetitions: int, output: Path, env_path: Path, dry_run: bool) -> tuple[BenchmarkRun, ...]:
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    if len(cases) != 10:
        raise ValueError("real-repo manifest must contain exactly 10 frozen cases")
    for case in cases:
        source = CACHE_ROOTS[str(case["repo"])]
        if not (source / ".git").exists():
            raise RuntimeError(f"missing source cache for {case['case_id']}: {source}")
        subprocess.run(["git", "-C", str(source), "cat-file", "-e", f"{case['base_commit']}^{{commit}}"], check=True)
    if dry_run:
        return ()
    config = resolve_config(env_path)
    output.mkdir(parents=True, exist_ok=True)
    records: list[BenchmarkRun] = []
    for repetition in range(1, repetitions + 1):
        for case in cases:
            model = BoundedSmokeClient(config, async_transport=HttpxAsyncHttpTransport(provider_id=config.provider_id), mode="nonstream", call_timeout_seconds=25)
            model.max_model_calls = 8
            records.append(await _run_case(case, adapter=model, output=output, repetition=repetition))
    report = {"scope": "real_repository", "repetitions": repetitions, "model": f"{config.provider_id}/{config.model}", "stream": False, "transport_note": "stream=true was excluded after SSE body-read hangs; this is a provider transport issue, not a model-capability result.", "summary": summarize_experiments(tuple(records)), "runs": [item.to_dict() for item in records]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return tuple(records)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/real-repo-10"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(run(repetitions=args.repetitions, output=args.output, env_path=args.env, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
