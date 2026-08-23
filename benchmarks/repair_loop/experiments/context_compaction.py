"""Context-length and compaction policy experiment contract."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("context_compaction", "Context stays useful as transcript length grows.", ("compression_ratio", "prompt_tokens", "key_fact_retention", "task_success", "latency"), ("context_overflow", "key_fact_lost", "compaction_failure"))
CASES = (
    CaseContract("context-short-none", DEFINITION.name, "short_no_compaction", "runtime context preserves the critical fact", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"notes.txt": "critical fact: port 8123\n"})),
    CaseContract("context-long-compact", DEFINITION.name, "long_compaction", "runtime compaction retains the critical fact", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"notes.txt": "critical fact: port 8123\n"})),
)
