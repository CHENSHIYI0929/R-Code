"""Within-session memory contrast experiment contract."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("session_memory", "Session memory reduces repeated inspection without injecting stale facts.", ("repeated_file_reads", "tool_calls", "task_success", "fact_recall", "stale_injection"), ("memory_missing", "irrelevant_memory", "stale_memory"))
CASES = tuple(
    CaseContract(f"session-{profile}", DEFINITION.name, profile, "task result uses only valid session facts", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"src/config.py": "PORT = 8123\n"}), {"repeated_file_reads": 2 if profile == "memory_off" else 1, "tool_calls": 3 if profile == "memory_off" else 2, "task_success": profile != "memory_stale", "fact_recall": profile != "memory_irrelevant", "stale_injection": profile == "memory_stale", "latency": 5}, scripted_success=profile != "memory_stale", scripted_resolved=profile != "memory_stale", scripted_failure_kind="stale_memory" if profile == "memory_stale" else None) for profile in ("memory_off", "memory_on", "memory_irrelevant", "memory_stale")
)
