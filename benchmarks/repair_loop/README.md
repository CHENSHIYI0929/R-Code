# Repair Loop Benchmark

This package defines layered evaluation rather than a single score. Every run
emits a compatible `BenchmarkRun`, but `summarize_experiments()` keeps results
separate by experiment and profile. The experiment modules cover Harness
Regression, Repair Loop, Context & Compaction, Session Memory, Long-term
Memory, Resume / Recovery, Tool Result Store, and Hook & Policy.

The original Repair Loop profiles remain `baseline`, `verification_only`,
`parser`, and `full`; `summarize_runs()` remains its compatibility summary.
The first six modules include deterministic scripted cases. Every generic run
receives an independently-created fixture workspace. A real-model adapter uses
the identical case/profile/workspace interface.

Every `run_experiment()` record receives `ReproducibilityMetadata`: git commit,
branch, benchmark version, fixture hash, model, decoding parameters, and feature
flags. A real-model adapter must preserve `completed`, `blocked`, and `error`
samples. It may attach normalized trace, tool, hook, memory, and stop events as
`BenchmarkEventSummary`; the common summary keeps scripted and real-model runs
separate and reports failure/status distributions plus mean, standard deviation,
and range for every numeric metric.

An adapter must create a clean workspace copy for every case/profile pair,
construct the selected runtime policy, run the configured model, and return the
record. Keeping that provider-specific work outside this package makes local
replay, CI, and a real remote provider comparable.
