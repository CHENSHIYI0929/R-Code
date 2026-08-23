"""Contract for direct versus externally stored large tool results."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("tool_result_store", "Large results can be referenced without losing required information.", ("prompt_tokens", "task_success", "information_loss"), ("result_missing", "reference_unreadable", "information_lost"))
CASES = (
    CaseContract("result-direct", DEFINITION.name, "direct_context", "full tool output remains available", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"large.txt": "x" * 2048}), {"prompt_tokens": 2100, "task_success": True, "information_loss": False}),
    CaseContract("result-external", DEFINITION.name, "external_reference", "summary/reference preserves the required fact", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"large.txt": "x" * 2048}), {"prompt_tokens": 200, "task_success": True, "information_loss": False}),
)
