# Executable Fake-Model Benchmark — 2026-08-23

All observations below come from the executable adapter: the deterministic
model emits only tool calls or final messages, while `AgentLoop`, real file
tools, `RepairLoopGate`, verifier, JSONL transcript, trace, and error recorder
run in fresh fixture workspaces.

## Run summary

- Experiments: Harness, Repair, Context/Compaction, Session Memory,
  Resume/Recovery, and two new post-resume stale-fact scenarios.
- Records: 24. Successes: 13.
- Failure distribution: `verification_skipped`: 1; `test_failed`: 3;
  `workspace_changed`: 4; `missing_file`: 1; `stale_fact_used`: 2.
- Stop reasons: `completed`: 21; `repair_exhausted`: 3.

## Core observations

| Experiment | Result | Core runtime-derived metrics |
| --- | --- | --- |
| Harness | 2/2 success | each case: 1 tool call, 4 tokens, `completed` |
| Repair / baseline | unsuccessful by design | 2 calls, 6 tokens, 0 verifier attempts, `completed`, `verification_skipped` |
| Repair / verification_only, parser, full | 0/3 success | each: 3 calls, 10 tokens, 2 verification attempts, 2 repeated failures, `repair_exhausted`, `test_failed` |
| Context/Compaction | 2/2 success | 0 calls, 2 tokens, compression ratio 0.2227, projected prompt 204 tokens, key fact retained |
| Session Memory / off | success | 2 reads/calls, 8 tokens, stale injection false |
| Session Memory / on or irrelevant | success | 1 read/call, 4 tokens, stale injection false |
| Session Memory / stale | success | 1 read, 2 calls, 8 tokens, stale injection false |
| Resume / unchanged | success | resume success true, stale reuse false, 0 recovery steps |
| Resume / changed or deleted | unsuccessful | resume success true, stale reuse true, 1 recovery step; modified => `workspace_changed`, deleted => `missing_file` |

The repair profiles are now truthful failures rather than synthetic pass
records. Their common failure is a repeated real verifier failure, so none yet
demonstrates a parser/retrieval benefit. This is evidence to inspect before
claiming an ablation result.

## Post-resume stale-fact cases

The cases first run a real `read_file`, persist/restore the transcript, mutate
or delete `src/state.py`, then execute a resumed answer turn.

| Scenario | Strategy | task_success | stale_fact_used | tool_steps |
| --- | --- | ---: | ---: | ---: |
| file modified | retain old transcript | 0 | 1 | 0 |
| file modified | append stale warning | 1 | 0 | 1 |
| file modified | force re-read | 1 | 0 | 1 |
| file deleted | retain old transcript | 0 | 1 | 0 |
| file deleted | append stale warning | 1 | 0 | 1 |
| file deleted | force re-read | 1 | 0 | 1 |

This confirms a real runtime failure mode: a resumed task can answer from a
persisted obsolete tool result. No production recovery change is made in this
iteration. `restore_session_state()` reconstructs cache entries from the
*current* filesystem and the transcript does not retain an observation-time
file fingerprint, so it cannot accurately identify stale historical reads. A
blind warning for every past read would create false positives and the fake
model alone does not establish real-model compliance with such a warning.

## Follow-up recovery fix

The benchmark-driven minimal fix is now implemented and covered by regression
tests. New `read_file` results store `fingerprint.path`, `sha256`, `mtime`,
`size`, and `observed_at`. Resume checks only records with that complete
fingerprint. A changed or deleted file replaces the active in-memory historical
result with an untrusted re-read instruction and removes it from `files_read`;
the old JSONL record is never rewritten. Legacy reads with no fingerprint are
left unchanged.

The modified/deleted post-resume cases now both report
`task_success=1`, `stale_fact_used=0`, and one fresh tool step for every
comparison control. The repair fixture was also corrected: its previous
same-second, same-size source edit could reuse a stale Python `.pyc`, creating
false `repair_exhausted` results. With a size-changing final edit, three repeats
each give `verification_only`, `parser`, and `full` 3/3
`completed_verified`; baseline remains intentionally unverified.

## Decision

The production recovery fix is deliberately limited to fingerprinted future
reads and active in-memory resume state. The next step is a fresh three-repeat
run of the selected executable benchmark set, then a real-model adapter using
the same artifact-derived metrics.
