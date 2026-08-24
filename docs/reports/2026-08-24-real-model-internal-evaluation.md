# Real-Model Internal Evaluation — 2026-08-24

## Scope and reproducibility

This report covers the frozen synthetic-fixture suite only: 54 records (18
case/profile contracts x 3 repetitions), fixed local provider/model config,
streaming transport, and benchmark-only budgets. Every run has a fixture hash,
git commit, model/config metadata, JSONL trace/transcript/error artifacts, and
a record under `benchmark-results/final-evaluation/artifacts/`. It is not a
real-repository score and must not be combined with a future repo score.

## Results

| Experiment | Result | Main failure distribution |
| --- | --- | --- |
| Harness | 4/6 success | 2 `policy_denied` records with zero model tokens/tool calls |
| Repair baseline | 0/3 | 3 `provider_timeout` |
| Repair verification_only | 0/3 | 3 `provider_timeout` |
| Repair parser | 0/3 | 3 `provider_timeout` |
| Repair full | 0/3 | 3 `provider_timeout` |
| Context short | 1/3 | 2 `key_fact_lost` |
| Context long/compaction | 0/3 | 3 `key_fact_lost` |
| Session memory on | 1/3 | 2 `memory_missing` |
| Session memory off/irrelevant/stale | 0/9 | 9 `memory_missing` |
| Resume/recovery | 0/18 | 15 `workspace_changed`, 3 `missing_file` |

Repair latency mean/std (ms): baseline 50,795/19,458;
verification-only 40,451/21,391; parser 25,231/309; full 25,011/2. All repair
profiles are dominated by provider timeout, so the data does not establish a
verification/parser/full mechanism difference.

## Interpretation

The only demonstrated real-model benefit so far is the constrained navigation
smoke: after providing the fixture map, stream completed verified in three
correct tool steps with no invalid-path call. The broad synthetic suite does
not yet demonstrate repair, compaction, memory, or recovery gains because its
outcomes are dominated by provider timeouts or model task failures.

The two Harness `policy_denied` records are not evidence that Guard failed:
both contain zero model tokens and zero tool calls, so they are provider-stage
failures currently classified by the Harness expectation branch. This is an
evaluation classification issue to correct before claiming a Harness rate.

## Next action

Do not begin real-repository tasks or modify production logic yet. First fix
only the Harness provider-stage classification, then rerun the affected
Harness case and use bounded, navigation-capable prompts to isolate whether
Repair failures remain provider dominated. Only a stable internal real-model
result should gate the separate 10–20 fixed-commit repository evaluation.
