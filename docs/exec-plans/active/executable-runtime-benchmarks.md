# Executable Runtime Benchmarks

This ExecPlan is a living document. It follows `PLANS.md` in the repository
root and must be updated as work progresses.

## Purpose / Big Picture

The current benchmark reports predetermined case metadata as if it were an
observation. After this work, its Fake Model will only replay a deterministic
sequence of provider-neutral model events; `AgentLoop`, the real registry tool
executor, `RepairLoopGate`, context preparation, session-memory services, and
the persistent transcript/trace/error artifacts will perform the work. A reader
will be able to run the benchmark tests and see success, failure, metrics, and
failure labels derived from those artifacts rather than from declared metric
values.

This plan deliberately stops before a real-provider adapter. The executable
Fake Model is the required proof that the runtime measurement path is genuine;
a real provider must reuse that path later rather than introduce another
measurement implementation.

## Progress

- [x] (2026-08-23 00:00Z) Confirmed the existing `scripted_adapter` simply
  copies `CaseContract.scripted_metrics` into `BenchmarkRun`.
- [x] (2026-08-23 00:00Z) Confirmed `AgentLoop`, `RegistryToolExecutor`,
  `RepairLoopGate`, JSONL transcript, trace recorder, and error recorder can
  be constructed without a provider SDK.
- [x] (2026-08-23 00:00Z) Replaced declared-metric replay with a deterministic
  event-script model and executable benchmark adapter.
- [x] (2026-08-23 00:00Z) Made repair failure terminal status and
  `failure_kind` derive from the verifier report and loop transition.
- [x] (2026-08-23 00:00Z) Converted the selected harness, repair,
  context/compaction, session-memory, and resume/recovery cases to executable
  fixtures and added regression coverage.
- [x] (2026-08-23 00:00Z) Ran the full repository suite: 645 passed and 9
  pre-existing failures remain, including two sandbox-blocked MCP loopback
  tests and seven unrelated expectation mismatches.
- [x] (2026-08-23 00:00Z) Added the modified/deleted post-resume cases and
  compared transcript-retention, stale-warning, and forced-reread controls
  without changing recovery.

## Surprises & Discoveries

- Observation: unsuccessful scripted repair cases record
  `terminal_outcome="pass"` and `failure_kind=None`.
  Evidence: `benchmarks/repair_loop/experiments/repair_loop.py` sets only
  `scripted_success`/`scripted_resolved`; `scripted.py` defaults the terminal
  outcome to `pass` and failure kind to `None`.
- Observation: `ui/cli/app.py::build_runtime` always creates its model client
  from `workspace/.env`, so benchmark code should compose the provider-neutral
  runtime directly rather than require a real provider configuration.
  Evidence: `build_runtime` calls `create_model_client(workspace / ".env")`.
- Observation: restored transcripts retain the old successful `read_file` tool
  result after the underlying file is changed or removed.
  Evidence: the executable `file_modified` recovery case reports
  `stale_reuse=true` from the restored JSONL chain.
- Observation: retaining that old tool result causes a resumed task to answer
  `VERSION = 1` after both a file modification and deletion.
  Evidence: `resume_staleness` records `task_success=false`,
  `stale_fact_used=true`, and `tool_steps=0` for both retain cases; the other
  two benchmark controls succeed after one real `read_file` call.
- Observation: repair verification was intermittently exhausted because Python
  reused a same-second `.pyc` after source changed from `return 1` to the
  same-size `return 2`.
  Evidence: retained verifier artifacts alternated between the correct source
  and `assert 1 == 2`; changing the benchmark's final source size removes the
  cache ambiguity. This is a fixture issue, not a repair-policy finding.

## Decision Log

- Decision: assemble the existing provider-neutral runtime directly in the
  benchmark adapter instead of modifying production startup configuration.
  Rationale: this exercises the production loop, services, tools, gate and
  artifacts while preserving the rule that the task must not add runtime
  mechanisms or require a provider secret.
  Date/Author: 2026-08-23 / Codex.
- Decision: case contracts will declare fixture files, deterministic model
  event scripts, and semantic assertions, but never observed numeric metrics
  or terminal status.
  Rationale: setup and oracle are necessary test input; measurements must be
  derived from runtime output.
  Date/Author: 2026-08-23 / Codex.
- Decision: a changed-file resume is recorded as an observed stale-reuse
  failure, rather than being labelled recovered from its scenario name.
  Rationale: the persisted tool result remains visible after restore; the
  benchmark must report actual behavior even when it contradicts prior claims.
  Date/Author: 2026-08-23 / Codex.

## Outcomes & Retrospective

The selected benchmark cases now drive the real provider-neutral loop and real
artifact writers. `tests/test_layered_benchmark_experiments.py` proves an
unverified baseline is non-pass/non-null-failure and a changed-file resume is
reported as stale reuse. Focused validation passed 22 tests in 7.42 seconds.
The real-provider adapter remains intentionally out of scope. Full-suite
validation completed with 645 passed and the same nine unrelated failures that
preceded this work; no benchmark-specific failure was added.

## Context and Orientation

`benchmarks/repair_loop/contracts.py` defines immutable case metadata and
`benchmarks/repair_loop/runner.py` gives each case an isolated temporary
workspace. `benchmarks/repair_loop/scripted.py` is currently misleading: it
constructs a result entirely from the declared `scripted_*` fields. The common
record is `benchmarks/repair_loop/types.py::BenchmarkRun`; its `metrics`,
`failure_kind`, `run_status`, and optional event summary are what summaries
consume.

The production runtime starts at `core/loop.py::AgentLoop`. It asks a
`ModelClient` for `ModelStreamEvent` values, executes real tool calls via a
`ToolExecutor`, persists messages through `MessageStore`, records events with
`TraceRecorder`, logs unrecovered errors using `ErrorLogRecorder`, and passes
candidate completion through `RepairLoopGate`. `RegistryToolExecutor` and the
descriptors from `tools/` perform real file operations inside the fixture
workspace. `RepairLoopGate` executes configured verification commands without a
shell and produces a structured `VerificationReport`. The benchmark adapter can
use these public services directly and must not stub their outputs.

An event script is the ordered set of model responses used by the Fake Model.
It may contain a tool call or a final assistant message. The Fake Model may
validate the received snapshot for test assertions, but it must not calculate a
benchmark metric or decide pass/failure. An artifact is a JSONL transcript,
trace, error log, verifier report, or real workspace file produced by the
runtime.

## Plan of Work

First replace the scripted model contract with an event-script contract and a
small provider-neutral Fake Model in `benchmarks/repair_loop/scripted.py`.
Construct a benchmark runtime in a new benchmark-local module using
`RuntimeState`, `MessageStore`, JSONL trace/error sinks, `ToolRegistry`,
`RegistryToolExecutor`, `SandboxGuard`, `ContextEngine`, compaction/session
memory services where required, and `RepairLoopGate` for repair profiles. The
adapter will collect all `AgentEvent` values, flush recorders, read artifacts,
and derive counts, stop reason, verification result, tool calls, tokens, and
failure labels. It will create a `BenchmarkRun` only after semantic case
assertions pass; an assertion mismatch is a benchmark error, not a fabricated
successful record.

Repair profiles will run a real edit followed by real verification. Baseline
will omit the gate; verification-only/parser/full will attach a `RepairLoopGate`
with the policy obtained from `repair_loop_policy`. A failing verifier run must
produce `run_status="completed"`, a non-pass terminal outcome, and a concrete
allowed failure label; a pass must only be reported after the verifier passes.
Parser/retrieval differences will be asserted from repair feedback evidence and
snippets, not declared booleans.

The remaining selected experiments will use real tool calls and persisted
artifacts: harness checks a real read plus a denied outside write; context forces
compaction with a small configured budget and verifies the retained fact in the
actual snapshot; session memory performs two turns and compares actual read-call
counts and injected memory; recovery persists a session, mutates its fixture,
restores through the existing resume/recovery path, and reads resulting state.
If a capability has no existing runtime behavior needed for the old contract,
the case is narrowed or removed rather than simulated.

Tests in `tests/test_layered_benchmark_experiments.py` and
`tests/test_repair_benchmark.py` will assert that case definitions no longer
contain observation metrics, that file contents/verifier output/transcript/trace
drive the records, and that an intentionally failing repair has a non-pass
terminal outcome and a non-null failure kind. Existing production tests remain
unchanged except where their public APIs need a benchmark-safe composition.

## Concrete Steps

Run from `/Users/chenshiyi/Downloads/R-Code`:

    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m pytest \
      tests/test_repair_benchmark.py tests/test_layered_benchmark_experiments.py \
      tests/test_repair_loop.py tests/test_verification_executor.py -q

Then execute each selected benchmark case three times through the executable
adapter and serialize the returned records only after the run completes. The
expected result is nonzero trace/transcript artifacts, real workspace file
changes for repair cases, and no `success=false` record whose terminal outcome
is `pass` or whose failure kind is absent.

Finally run:

    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m compileall benchmarks
    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m pytest tests -q

## Validation and Acceptance

Acceptance is behavioral. An executable repair failure must visibly execute the
fixture verification command, enter a verification-failed or repair-exhausted
transition, write verifier evidence, and return a non-pass terminal outcome
with an allowed failure label. A successful repair must change the fixture and
pass the configured verification command. The benchmark must receive its tool
result from the real executor and its metric counts from JSONL/loop events; a
test that alters a declared old `scripted_metrics` value must not alter the
observation because that field will no longer exist.

## Idempotence and Recovery

Every execution remains inside `fixture_workspace`, so reruns receive new
directories and cannot edit the repository. Recorders are flushed before
artifact inspection. If a fixture verification command fails unexpectedly, keep
the produced `BenchmarkRun` as a failure result with paths to its artifacts;
only adapter/programming errors use `run_status="error"`.

## Artifacts and Notes

The current report at `docs/reports/2026-08-23-layered-benchmark-report.md`
documents why the declared-metric adapter is insufficient and records the
baseline failure corpus. It should be replaced or supplemented only with
artifact-derived results after this plan is complete.

## Interfaces and Dependencies

The executable adapter must retain this callable public shape so
`run_experiment` needs no new runner logic:

    async def scripted_adapter(
        case: CaseContract,
        profile: str,
        workspace: Path,
        tier: EvaluationTier,
    ) -> BenchmarkRun

`CaseContract` must expose deterministic setup and expected semantic outcomes,
not observed metrics. The adapter may depend on `core`, `services`, `tools`, and
the benchmark package; production modules must not depend on benchmarks. The
real-model adapter is explicitly out of scope for this plan.

Revision note (2026-08-23): created after the user directed that benchmark
metrics be derived from real runtime artifacts before any real-model work.

Revision note (2026-08-23): implemented the executable adapter, terminal
failure invariant, selected case conversion, and focused tests; documented the
observed resume stale-reuse behavior.

Revision note (2026-08-23): recorded full-suite validation (645 passed, 9
pre-existing failures) and marked the plan implementation complete.

Revision note (2026-08-23): added and executed post-resume stale-fact cases.
They prove the failure but no production recovery change was made because the
current transcript lacks an observation-time file fingerprint needed to target
invalidation safely.

Revision note (2026-08-23): implemented the minimal fingerprinted-read resume
fix. Changed/deleted fingerprinted results are untrusted in the active resumed
chain, legacy results are untouched, and focused recovery tests pass. Repair
trace analysis found a same-size Python bytecode-cache fixture artifact; the
fixture now changes source size and repair profiles pass deterministically.
