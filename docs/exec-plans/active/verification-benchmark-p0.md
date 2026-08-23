# Verification and Repair Benchmark P0

This ExecPlan is a living document. It follows `PLANS.md` from the repository
root and must be updated as work proceeds.

## Purpose / Big Picture

R-Code must not treat every non-zero verification exit as a code bug. After
this work, a repair gate runs configured checks without a shell, records a
structured reason when a check cannot run, and only asks the model to repair a
real test failure. A benchmark package can then compare baseline, verification,
parser, and retrieval variants using one shared set of metrics.

## Progress

- [x] (2026-08-23 00:00Z) Inspected the current repair gate, loop boundary,
  tool executor, settings compatibility, and existing repair tests.
- [x] (2026-08-23 00:00Z) Added the verification execution service and routed `RepairLoopGate` through it.
- [x] (2026-08-23 00:00Z) Added outcome classification and stable evidence-based fingerprinting.
- [x] (2026-08-23 00:00Z) Added benchmark manifests, profile definitions, record format, and summary tests.
- [x] (2026-08-23 00:00Z) Ran focused tests, integration/import-boundary tests, and compile checks.

## Surprises & Discoveries

- Observation: the existing gate executes config text through
  `asyncio.create_subprocess_shell` and hashes the entire output.
  Evidence: `services/repair/gate.py` before this plan owns `_verify()` and
  constructs its fingerprint from `status + full_output`.
- Observation: the available Python interpreter cannot collect the full suite.
  Evidence: `python -m pytest tests -q` stops before test execution because
  `tools/bash/parser.py` cannot import `tree_sitter_bash`; 13 Bash/CLI modules
  report the same missing dependency.

## Decision Log

- Decision: keep `core/loop.py` unchanged and inject all repair behavior through
  its existing `FinishGate` protocol.
  Rationale: the loop is deliberately capability-neutral and already has the
  retry, blocked, exhausted, and verified-completion transitions needed here.
  Date/Author: 2026-08-23 / Codex.
- Decision: retain coarse report `status` and add an additive `outcome` field.
  Rationale: CLI and historic trace consumers can continue to read status while
  new gate logic distinguishes test failures from execution failures.
  Date/Author: 2026-08-23 / Codex.
- Decision: treat shell grammar in legacy command strings as unsupported rather
  than preserving shell execution.
  Rationale: a verification command is project configuration, but it still
  must not bypass the runtime's execution boundary. argv configuration is
  deterministic and portable.
  Date/Author: 2026-08-23 / Codex.

## Outcomes & Retrospective

`VerificationExecutor` now owns argv-only process launch, result persistence,
outcome classification, trace emission, and timeout cleanup. The gate keeps its
existing FinishGate contract and retries only `test_failed`; its fingerprint is
derived from normalized parser evidence. The benchmark package provides the
four ablation profiles and deterministic aggregation contract, while leaving
model/provider and workspace-copy ownership to an adapter.

Validation evidence:

    python -m pytest tests/test_repair_services.py tests/test_repair_loop.py tests/test_verification_executor.py tests/test_repair_benchmark.py -q
    13 passed

    python -m pytest tests/test_attachment_projector.py tests/test_cli_resume.py tests/test_runtime_integration.py tests/test_import_boundaries.py -q
    21 passed

    python -m pytest tests/test_repair_services.py tests/test_repair_loop.py tests/test_verification_executor.py tests/test_repair_benchmark.py tests/test_attachment_projector.py tests/test_cli_resume.py tests/test_runtime_integration.py tests/test_import_boundaries.py -q
    33 passed

The remaining deliberate gap is a provider-specific benchmark adapter that
creates clean task workspaces and writes real run JSONL. It is separated from
the benchmark core so it can be selected after a target model/provider is
chosen.

## Context and Orientation

`core/loop.py` calls a `FinishGate` only after the model finishes without tool
calls. `services/repair/gate.py` is that gate: it decides whether to pass,
retry with a `repair_feedback` attachment, block, or exhaust attempts.
`services/repair/parser.py` derives failure evidence and
`services/repair/retriever.py` selects workspace snippets. The new
`services/verification/` package will own process execution and report facts;
it must not import `core` or concrete tools. `benchmarks/repair_loop/` is an
evaluation-only package and likewise must not alter normal CLI operation.

## Plan of Work

Create `services/verification/types.py` with `VerificationCommand`, the
six-value `VerificationOutcome`, and report-compatible data fields. Create
`services/verification/executor.py` with
`VerificationExecutor.execute(commands, attempt) -> VerificationReport`.
It converts compatible legacy strings using `shlex.split`, rejects shell
operators, starts argv with workspace cwd, and kills an isolated process group
on timeout. It writes one combined artifact through `ToolResultStorage` and
emits verification trace events.

Move classification and stable fingerprint construction into small pure
services. Update `RepairLoopGate` to compose these services; it must retry only
`test_failed`. Add `RepairLoopPolicy` so benchmark profiles can turn parsing
and retrieval on or off without adding mode checks to the main loop.

Create benchmark task manifests and a reusable asynchronous runner that emits
one JSON-compatible record per profile/case run. Its summary computes success,
resolved, turns, tool calls, tokens, latency, verification attempts, and same
failure repeats. A provider-specific adapter may later construct isolated task
workspaces; this P0 package intentionally defines and tests the stable harness
contract first.

## Concrete Steps

From the repository root run:

    uv run python -m pytest tests/test_repair_services.py tests/test_repair_loop.py tests/test_verification_executor.py tests/test_repair_benchmark.py -q
    uv run python -m compileall core services benchmarks
    uv run python -m pytest tests/test_import_boundaries.py -q

The focused suite must show all tests passing. The compile command must report
no syntax errors, and import-boundary tests must continue to pass.

## Validation and Acceptance

Use a temporary workspace whose verification command exits one to prove that
the gate returns `continue`, creates a stored artifact, and injects repair
feedback. Use a nonexistent executable and a timeout command to prove the gate
returns `blocked` rather than retrying code changes. Run benchmark summary tests
with four profile records and observe the per-profile aggregate metrics.

## Idempotence and Recovery

All changes are additive except that unsafe shell syntax in verification config
is rejected. A project can recover by changing the old string to an argv object.
Artifact persistence remains under the session directory and is safe to repeat.

## Interfaces and Dependencies

`services/verification/executor.py` exports:

    class VerificationExecutor:
        async def execute(
            self, commands: tuple[VerificationCommand, ...], *, attempt: int
        ) -> VerificationReport: ...

`services/repair/gate.py` accepts an optional executor and policy but retains
its existing constructor arguments. `VerificationReport.status` remains the
coarse historical field; `VerificationReport.outcome` is additive. Benchmark
execution accepts an injected async callable so no model provider is coupled to
the benchmark core.
