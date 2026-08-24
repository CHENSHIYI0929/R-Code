# Final Internal Benchmark Report — 2026-08-24

## Scope

This report separates the controlled synthetic internal evaluations from any
future real-repository score. All runs use the fixed local provider/model
configuration, streaming transport, fresh fixtures, production-aligned core
coding tools, JSONL artifacts, and benchmark-only budgets.

Sources: `benchmark-results/repair-ablation/report.json` (12 records) and
`benchmark-results/internal-mechanisms/report.json` (42 records).

## Repair Loop (4 profiles x 3)

| Profile | success | mean tool calls | mean latency | mean verification attempts |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0/3, by definition | 4.00 | 33.98s | 0 |
| verification_only | 3/3 | 4.00 | 30.49s | 1 |
| parser | 3/3 | 3.33 | 29.23s | 1 |
| full | 3/3 | 4.33 | 51.66s | 1 |

Verification has a demonstrated benefit: it is the difference between an
unverified baseline and 3/3 verified completions. Parser and full add no
observed success benefit in this small fixture; parser has the lowest observed
cost, while full is materially slower. Do not claim a parser/retrieval quality
gain from this data.

## Harness, context, memory, recovery

| Mechanism | Evidence | Cost / limitation |
| --- | --- | --- |
| Harness | 6/6 success; no provider timeout classification leak | narrow two-case fixture only |
| Context/compaction | short and long 3/3 key-fact/task success | long fixture is small; no large-context claim |
| Session memory | on: 3/3 with 1.33 mean tools / 4,462 mean tokens vs off: 2.0 / 5,365 | stale profile 0/3, correctly reports `stale_memory` rather than silently succeeding |
| Resume/recovery | normal, modified, workspace/config changed each 3/3; stale-memory 2/3 | deleted file 0/3 (`missing_file`), mean 4.67 tools / 42.03s |

## What is supported

- Production-aligned navigation plus a constrained task prompt can complete a
  small verified repair reliably.
- Verification is necessary for a trustworthy repair terminal outcome.
- Session memory reduces observed repeated inspection cost in this fixture.
- Fingerprinted resume protects changed-file recovery in this fixture.

## What is not supported

- No evidence that full repair policy outperforms parser or verification-only.
- No evidence that compaction handles production-scale contexts.
- Deleted-file recovery is not reliable enough for a positive claim.
- Synthetic fixture success is not a real-repository success rate.

## Next step

Proceed to a separately reported 10–20 fixed-commit real-repository issue
suite only. Do not give target files; retain the production-aligned
`glob/grep/read/edit/write` navigation surface, fixed verifier commands, commit
hashes, artifacts, and the same bounded model configuration. Keep its success
rate separate from this report.
