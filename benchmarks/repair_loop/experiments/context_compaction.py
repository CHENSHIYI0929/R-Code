"""Context-length and compaction policy experiment contract."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("context_compaction", "Context stays useful as transcript length grows.", ("compression_ratio", "prompt_tokens", "key_fact_retention", "task_success", "latency"), ("context_overflow", "key_fact_lost", "compaction_failure"))
CASES = (
    CaseContract("context-short-none", DEFINITION.name, "short_no_compaction", "short context preserves all facts", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"notes.txt": "critical fact: port 8123\n"}), {"compression_ratio": 1.0, "prompt_tokens": 200, "key_fact_retention": 1.0, "task_success": True, "latency": 4}),
    CaseContract("context-long-compact", DEFINITION.name, "long_compaction", "compacted context retains critical fact", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"notes.txt": "critical fact: port 8123\n"}), {"compression_ratio": 0.35, "prompt_tokens": 700, "key_fact_retention": 1.0, "task_success": True, "latency": 8}),
)
