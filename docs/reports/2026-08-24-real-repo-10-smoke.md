# Real-Repo-10 non-stream smoke report

## Scope

This is a one-repeat end-to-end smoke run over ten frozen real-repository
cases. It is deliberately separate from synthetic-fixture results and is not a
three-repeat score.

- Provider/model: fixed configured SiliconFlow provider and model from `.env`.
- Transport: `stream=false`.
- Reason: `stream=true` repeatedly hung in the provider SSE body-read phase.
  That is recorded as a provider transport issue and is not a model-capability
  result.
- Per-case budget: 8 model calls, 8 tool steps, 75 seconds wall clock; each
  provider call has a 25 second timeout.
- Agent input: frozen public issue summary plus an isolated base checkout only.
  Official patch, target path, and evaluator oracle remained outside the agent
  workspace.

## Integrity checks

- 10/10 `BenchmarkRun` records were written.
- 10/10 verifier outputs and patch artifacts were retained.
- Every verifier ran against the resulting base-derived workspace, not a gold
  patch workspace.
- The interrupted stream attempts were discarded and are not included here.

## Results

| Metric | Result |
| --- | ---: |
| Cases | 10 |
| Task success | 0/10 (0.0%) |
| Mean tool calls (std) | 4.9 (2.7) |
| Mean tokens (std) | 28,171.8 (26,670.3) |
| Mean latency (std) | 58,624.9 ms (17,227.4 ms) |
| Verification attempts | 1.0 per case |

Failure distribution:

- `wall_clock_budget_exceeded`: 4
- `provider_timeout`: 4
- `model_call_budget_exceeded`: 2

Terminal state was `tool_use` for 9 cases and `error` for 1. None reached a
model final answer; the evaluator consequently observed the original failing
behavior in every case. This makes the result a valid runtime/navigation and
provider-latency finding, not evidence that any production repair mechanism is
effective or ineffective.

## Interpretation

The fixed non-stream transport removes the SSE hang, but the current model and
budget combination does not finish even lightweight real-repository repairs.
The dominant limitation is the interaction of per-call latency and multi-step
repository navigation: four cases exhausted the 75-second wall clock, while
two exhausted the eight-call budget. Four provider timeouts also remain.

No production AgentLoop, Memory, Context, Repair, or Recovery behavior was
changed. The next measurement should only be considered after deciding whether
the fixed real-repo budget is intentionally this strict; changing it would be a
new experimental configuration, not a production change.

## Artifacts

- Machine-readable report: `benchmark-results/real-repo-10/smoke-nonstream/report.json`
- Per-case artifacts: `benchmark-results/real-repo-10/smoke-nonstream/artifacts/<case>/1/`
