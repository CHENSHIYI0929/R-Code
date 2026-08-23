"""Within-session memory contrast experiment contract."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("session_memory", "Session memory reduces repeated inspection without injecting stale facts.", ("repeated_file_reads", "tool_calls", "task_success", "fact_recall", "stale_injection"), ("memory_missing", "irrelevant_memory", "stale_memory"))
CASES = tuple(
    CaseContract(f"session-{profile}", DEFINITION.name, profile, "task result uses only valid session facts", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"src/config.py": "PORT = 8123\n"})) for profile in ("memory_off", "memory_on", "memory_irrelevant", "memory_stale")
)
