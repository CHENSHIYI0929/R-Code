# Repair Loop Benchmark

This package defines the comparable part of Repair Loop evaluation. The four
profiles are `baseline`, `verification_only`, `parser`, and `full`. Each run
emits a `BenchmarkRun` record; `summarize_runs()` reports success/resolved rate,
turns, tool calls, tokens, latency, verification attempts, and repeated
failures.

An adapter must create a clean workspace copy for every case/profile pair,
construct the selected runtime policy, run the configured model, and return the
record. Keeping that provider-specific work outside this package makes local
replay, CI, and a real remote provider comparable.
