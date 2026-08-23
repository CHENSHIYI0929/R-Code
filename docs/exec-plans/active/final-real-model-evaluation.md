# Final Real-Model Evaluation

This ExecPlan is a living document and follows `PLANS.md` in the repository root.

## Purpose / Big Picture

R-Code now has executable deterministic tests. This plan adds a benchmark-only
real-model adapter that passes a fixed configured model through the same
`AgentLoop`, tool registry, guard, repair gate, verifier, transcript, trace,
and `BenchmarkRun` path. It then evaluates a separately reported collection of
small fixed-commit public-repository repair tasks. The final result is a
reproducible evidence package rather than a synthetic score.

## Progress

- [x] (2026-08-23 00:00Z) Confirmed the local SiliconFlow provider/model/key
  configuration is populated without exposing its secret.
- [x] Add and test the real-model adapter without changing CLI startup.
- [x] Freeze and run the existing synthetic suite three times per case/profile.
- [ ] Select 10–20 small public fixed-commit tasks with independent verifiers.
- [ ] Run real-repository tasks, retain artifacts, and generate separated final reports.

## Surprises & Discoveries

- Observation: the existing fixture lifecycle removes workspaces after a run.
  Evidence: `benchmarks/repair_loop/fixtures.py::fixture_workspace` uses
  `TemporaryDirectory`; real evaluation needs an artifact-copy step before it
  exits.
- Observation: the unprivileged process cannot resolve the configured provider
  hostname; the privileged smoke test connected but remained in a streaming
  response during the repair case and was manually cancelled after exceeding a
  reasonable smoke duration.
  Evidence: the unprivileged trace raised `httpx.ConnectError` and the
  privileged cancellation stack was blocked in `response.aiter_lines()`.
- Observation: the frozen deterministic suite produced 54 completed records
  (18 case/profile contracts x 3 repetitions). Verification-only, parser and
  full repair completed verified in all three repetitions; baseline correctly
  remained `verification_skipped`.

## Decision Log

- Decision: the real adapter receives an already configured provider-neutral
  model client and calls the benchmark runtime composition directly.
  Rationale: `ui/cli/app.py::build_runtime` owns interactive CLI assembly and
  `.env` startup; using it would change the evaluation surface and violate the
  requirement not to alter CLI startup.
  Date/Author: 2026-08-23 / Codex.

## Outcomes & Retrospective

Pending implementation.

## Context and Orientation

`benchmarks/repair_loop/runtime_adapter.py` composes the production runtime for
deterministic tests. Its `_runtime` function creates the real loop, registry
executor, sandbox guard, verifier, JSONL transcript/trace/error recorders, and
`BenchmarkRun` recorder. The only deterministic component is
`DeterministicModel`. A real adapter must replace only that component with
`infrastructure.providers.factory.create_model_client`, while retaining all
other construction and artifact parsing.

## Plan of Work

Add a real adapter and an artifact archive hook to the benchmark runner. Freeze
the current synthetic case definitions before the first paid invocation. Run
all selected experiments three times with one fixed provider/model and decoding
configuration. Each run writes an immutable JSON record and copies its session
artifacts to a timestamped results directory. Add public-repository task
manifests containing clone URL, commit, prompt, and argv verifier. Clone only
fixed commits into isolated workspaces and report those records under a distinct
`real_repo` experiment/tier namespace. Never combine fixture and repository
results into a single success rate.

## Validation and Acceptance

The real adapter must be testable with a fake `ModelClient`, preserve real
artifact paths, and be capable of one successful fixed-model Harness run. Every
report row must include commit, fixture/task hash, provider/model, decoding
parameters, benchmark version, and artifact directory. Report outputs must
separate synthetic and real-repository tables and distributions.

Revision note (2026-08-23): created when final real-model evaluation was
authorized after deterministic benchmark stabilization.
