"""Cross-session long-term memory contrast contract."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("long_term_memory", "Cross-session retrieval improves relevant recall without wrong injection.", ("relevant_recall", "wrong_injection", "selector_precision", "task_success"), ("memory_missing", "irrelevant_memory", "stale_memory", "selector_miss"))
CASES = tuple(
    CaseContract(f"long-term-{profile}", DEFINITION.name, profile, "new session recalls only relevant durable facts", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({".onecode/memory/project/port.md": "port is 8123\n"}), {"relevant_recall": profile == "retrieval_on", "wrong_injection": profile in {"irrelevant", "stale"}, "selector_precision": 1.0 if profile == "retrieval_on" else 0.0, "task_success": profile == "retrieval_on", "latency": 6}, scripted_success=profile == "retrieval_on", scripted_resolved=profile == "retrieval_on", scripted_failure_kind="stale_memory" if profile == "stale" else None) for profile in ("off", "retrieval_on", "irrelevant", "stale")
)
