# Layered Benchmark Report — 2026-08-23

> Superseded for the selected experiments: the executable adapter introduced
> after this report drives the real provider-neutral R-Code runtime. See
> `docs/exec-plans/active/executable-runtime-benchmarks.md`. The historical
> numbers below describe the pre-change declared-metric replay and must not be
> used as current effectiveness evidence.

## Scope and reproducibility

- Repository revision: `822e6ae3683acc4748685f4331d016a5ea1752d3` (`main`)
- Benchmark contract: `layered-v1`
- Selected experiments: Harness Regression, Repair Loop, Context & Compaction,
  Session Memory, and Resume & Recovery.
- Scripted tier: every case/profile was run three times, producing 54 records.
- Production-path regression: 85 focused tests passed.
- Full suite: 643 passed, 9 failed (details below).

The Scripted tier is a deterministic harness check, not an end-to-end agent
evaluation. `benchmarks/repair_loop/scripted.py` returns each case's declared
`scripted_metrics`; it proves fixture isolation, record validation, and summary
stability, but does not invoke a model, tool executor, repair gate, compactor,
memory updater, or resume command. Its `std = 0` results therefore demonstrate
only repeatability of the fixture/aggregation pipeline.

No real-model records are present. The repository has no `.env`, and the active
benchmark plan explicitly lists the provider-specific real-model adapter as a
remaining gap. Consequently no fixed provider/model/key exists to run the
requested three repetitions without adding configuration and an adapter.

## Scripted results (mean ± population std; n = 3 per case/profile)

| Experiment / profile | Core result | Key metrics | Failure distribution |
| --- | --- | --- | --- |
| Harness / scripted_baseline | success 100% (6 records) | runtime/tool/hook/budget/security correctness: 1.00 ± 0.00; recovery steps 0.50 ± 0.50; tool calls 0.50 ± 0.50 | none: 6 |
| Repair / baseline | success/resolved 0% / 0% | turns 2.00 ± 0.00; calls 3.00 ± 0.00; tokens 120.00 ± 0.00; verification 0.00 ± 0.00 | `none`: 3 (see oracle issue) |
| Repair / verification_only | success/resolved 0% / 0% | turns 2.00 ± 0.00; calls 3.00 ± 0.00; tokens 120.00 ± 0.00; verification 1.00 ± 0.00 | `none`: 3 (see oracle issue) |
| Repair / parser | success/resolved 0% / 100% | turns 2.00 ± 0.00; calls 3.00 ± 0.00; tokens 120.00 ± 0.00; verification 1.00 ± 0.00 | none: 3 |
| Repair / full | success/resolved 100% / 100% | turns 2.00 ± 0.00; calls 3.00 ± 0.00; tokens 120.00 ± 0.00; verification 1.00 ± 0.00 | none: 3 |
| Context / short_no_compaction | task success 100% | prompt tokens 200.00 ± 0.00; compression ratio 1.00 ± 0.00; key-fact retention 1.00 ± 0.00 | none: 3 |
| Context / long_compaction | task success 100% | prompt tokens 700.00 ± 0.00; compression ratio 0.35 ± 0.00; key-fact retention 1.00 ± 0.00 | none: 3 |
| Memory / memory_off | task success 100% | repeated reads 2.00 ± 0.00; calls 3.00 ± 0.00; stale injection 0.00 ± 0.00 | none: 3 |
| Memory / memory_on | task success 100% | repeated reads 1.00 ± 0.00; calls 2.00 ± 0.00; stale injection 0.00 ± 0.00 | none: 3 |
| Memory / memory_irrelevant | task success 100% | fact recall 0.00 ± 0.00; repeated reads 1.00 ± 0.00; calls 2.00 ± 0.00 | none: 3 |
| Memory / memory_stale | task success 0% | stale injection 1.00 ± 0.00; repeated reads 1.00 ± 0.00; calls 2.00 ± 0.00 | stale_memory: 3 |
| Recovery / normal | recovered/success 100% | resume success 1.00 ± 0.00; stale reuse 0.00 ± 0.00; steps 0.00 ± 0.00 | none: 3 |
| Recovery / each invalidation case | recovered/success 100% (15 records) | resume success 0.00 ± 0.00; stale reuse 0.00 ± 0.00; steps 1.00 ± 0.00 | workspace_changed: 6; missing_file: 3; stale_memory: 3; configuration_changed: 3 |

The scripted repair ablation encodes the expected ordering
`baseline < verification_only < parser < full` only in declared Boolean fields:
0/0/0/100% success, and 0/0/100/100% resolved. It does **not** measure actual
repair behavior, and all profiles have identical declared turns, calls, tokens,
latency, and repeated failures.

## Retained non-success and anomaly cases

- `repair-baseline`, repetitions 1–3: `success=false`, `resolved=false`, but
  `terminal_outcome=pass` and `failure_kind=null`.
- `repair-verification_only`, repetitions 1–3: same contradictory status.
- `repair-parser`, repetitions 1–3: `success=false`, `resolved=true`, but
  `terminal_outcome=pass` and `failure_kind=null`.
- `session-memory_stale`, repetitions 1–3: `success=false`,
  `failure_kind=stale_memory`, `stale_injection=true`, `task_success=false`.
- Recovery expected-invalidations, each repeated three times: `file_modified`
  and `workspace_changed` => `workspace_changed`; `file_deleted` =>
  `missing_file`; `stale_memory` => `stale_memory`; `config_changed` =>
  `configuration_changed`. All report stale reuse false and one recovery step.

These records are retained as the benchmark's current failure corpus. The three
repair status contradictions are a reporting/oracle defect: an unsuccessful run
must not be summarized as terminal `pass` with failure `none`.

## Production-path validation

Focused suite (85 passed in 2.90s): repair services/loop, verification executor,
benchmark contracts, compaction/context, session-memory compaction/extraction,
CLI resume, runtime integration, model retry, and import boundaries.

Full suite (643 passed, 9 failed in 9.86s):

| Failure | Classification |
| --- | --- |
| `test_bash_descriptor_schema_and_prompt` | implementation/expectation mismatch: prompt lacks `Tree-sitter` |
| `test_banner_shows_only_product_workspace_and_model` | CLI output truncates workspace path expected by test |
| `test_user_submitted_uses_reverse_style_dark`; `test_restored_user_messages_use_explicit_reverse_style` | renderer emits plain text, test expects ANSI styling |
| MCP SSE and streamable HTTP discovery/call tests | environment-blocked: sandbox denies loopback `bind(127.0.0.1, 0)` |
| `test_catalog_contains_builtin_providers` | expected `claude-openai-compatible` missing from catalog |
| `test_root_worktree_does_not_allow_arbitrary_paths` | guard returned `allow`, test expects `ask` |
| `test_registry_generates_search_tool_schemas_and_prompts` | prompt format changed from `glob:` / `grep:` expectation |

## Evidence-based conclusion

What is supported now:

- The benchmark record, fixture-isolation, and aggregation pipeline is stable
  under deterministic replay.
- The selected production mechanisms have focused regression coverage and pass.
- The intended safe-recovery behavior is represented in scripted cases: stale
  reuse is false and invalidation requires one recovery step.

What has no demonstrated benefit yet:

- Repair-loop gains for verification/parser/retrieval on actual code changes.
- Memory savings or stale-injection resistance under a real agent trajectory.
- Compaction token reduction while retaining facts in a real long context.
- Resume/recovery effectiveness against persisted, changed runtime state.

The main failure causes are (1) a benchmark design that replays expected metric
values rather than executing the runtime, (2) no real-model adapter or fixed
provider configuration, (3) repair benchmark status/failure taxonomy that hides
unsuccessful runs, and (4) nine unrelated full-suite regressions/environment
blocks.

## Highest-value next step

Do not add another runtime mechanism. First make the evaluation real: implement
one provider-neutral test adapter that constructs the existing runtime in each
fixture, drives a fixed scripted/fake `ModelClient` through real tool and gate
calls, derives metrics from trace/transcript/error artifacts, and makes
`failure_kind` mandatory when `success=false`. Once that adapter produces
non-declared measurements, add the fixed real-provider adapter/config and repeat
each case/profile three times. This turns the current contracts into evidence
rather than claims.
