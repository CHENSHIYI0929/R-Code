# Layered Runtime Evaluation

This ExecPlan is a living document and follows `PLANS.md` in the repository root.

## Purpose / Big Picture

R-Code needs separate evidence for runtime correctness, repair-loop improvement,
context management, memory, recovery, result storage, and policy hooks. After
this work, each concern has a versioned case contract and isolated fixture
workspace, while every run still produces one compatible `BenchmarkRun` record
and a common summary.

## Progress

- [x] (2026-08-23 00:00Z) Inspected the existing repair-loop benchmark contract.
- [x] (2026-08-23 00:00Z) Added shared contracts, isolated fixture workspaces, and generic runner/summary.
- [x] (2026-08-23 00:00Z) Added runnable scripted experiments for harness, repair, context/compaction, session memory, long-term memory, and resume/recovery.
- [x] (2026-08-23 00:00Z) Added contracts for tool-result-store and hook/policy experiments.
- [x] (2026-08-23 00:00Z) Added focused tests and ran the benchmark test set.
- [x] (2026-08-23 00:00Z) Added reproducibility metadata, normalized event explanations, tier-separated summaries, and repeat-run stability statistics.

## Surprises & Discoveries

- Observation: `BenchmarkRun` and `summarize_runs` currently encode only repair-loop metrics.
  Evidence: `benchmarks/repair_loop/types.py` has fixed repair fields and `summary.py` hard-codes those averages.

## Decision Log

- Decision: extend `BenchmarkRun` additively with `experiment`, `tier`, generic metrics, and failure kind.
  Rationale: existing repair tests and any JSONL consumers keep their historical required fields.
  Date/Author: 2026-08-23 / Codex.
- Decision: use temporary workspace factories rather than repository fixtures for scripted evaluation.
  Rationale: every profile/case receives a clean writable workspace and no case leaks memory, configuration, or edits to another.
  Date/Author: 2026-08-23 / Codex.
- Decision: preserve terminal samples as `completed`, `blocked`, or `error` instead of filtering failures before aggregation.
  Rationale: provider reliability and blocked verification are evidence, not noise; dropping them would inflate success claims.
  Date/Author: 2026-08-23 / Codex.

## Outcomes & Retrospective

The benchmark package now has a common contract and fixture lifecycle while
retaining the original repair-loop API. The first six experiment modules run
deterministically through `scripted_adapter`; all eight can use a real-model
adapter through `run_experiment`. `summarize_experiments` returns nested
experiment/profile groups, intentionally avoiding an invalid global score.
Each record now has reproducibility metadata and may carry a normalized summary
of trace, tool, hook, memory, and stop events. Summaries isolate scripted from
real-model results and provide mean, population standard deviation, range, and
failure/status distributions for repeated numeric observations.

Validation evidence:

    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m pytest tests/test_repair_benchmark.py tests/test_layered_benchmark_experiments.py -q
    19 passed

    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m compileall benchmarks
    completed without syntax errors

## Context and Orientation

The existing `benchmarks/repair_loop` package evaluates four RepairLoopPolicy
variants. The new `contracts.py` will describe every experiment without importing
the production runtime. `fixtures.py` makes a temporary workspace for each run.
`runner.py` accepts either a scripted adapter or a real-model adapter. Experiment
modules define cases and their metric vocabulary; they do not define a global
score because each module proves a distinct claim.

## Plan of Work

Add common records and make old repair records compatible. Add a generic
`run_experiment` function that validates experiment, case, profile, tier, and
metric contract. Add eight experiment modules: the first six include deterministic
scripted runners and default cases; the final two expose their case contracts and
use the same runner when adapters are supplied. Preserve `run_profiles` and its
summary output. Tests will assert fixture isolation, contract validation,
individual metric groups, scripted execution, and the legacy repair API.

## Concrete Steps

From the repository root run:

    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m pytest tests/test_repair_benchmark.py tests/test_layered_benchmark_experiments.py -q
    UV_CACHE_DIR="$PWD/.uv-cache" uv run python -m compileall benchmarks

## Validation and Acceptance

Each of the first six experiment modules must run its default scripted cases,
create a distinct temporary workspace per run, and return records whose metrics
include the vocabulary named in the task. The common summary must keep separate
experiment/profile groups and must not merge them into one score.

## Idempotence and Recovery

Fixture workspaces are created below a caller-provided temporary root and removed
after each run. The code writes no production runtime state. Re-running a suite
therefore creates new isolated fixtures and does not alter source workspaces.

## Interfaces and Dependencies

`run_experiment(definition, cases, profiles, adapter, workspace_root, tier)` is
the public async execution interface. The adapter receives `(case, profile,
workspace, tier)` and returns `BenchmarkRun`. Scripted adapters use metadata in
the case contract; real-model adapters construct R-Code in the supplied isolated
workspace. `summarize_experiments` returns separate maps keyed by experiment and
profile.
