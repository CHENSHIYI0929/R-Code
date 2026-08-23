"""Contract for hook ordering and deny-first policy effects."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("hook_policy", "Hooks observe outcomes while policy denies remain non-overridable.", ("post_tool_use_correct", "tool_error_correct", "policy_correct", "memory_hook_correct", "agent_loop_impact"), ("hook_error", "policy_denied", "memory_hook_error"))
CASES = (
    CaseContract("hook-success", DEFINITION.name, "post_tool_use", "successful tool call updates hook-derived memory", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"src/a.py": "x = 1\n"}), {"post_tool_use_correct": True, "tool_error_correct": True, "policy_correct": True, "memory_hook_correct": True, "agent_loop_impact": 0}),
    CaseContract("hook-deny", DEFINITION.name, "policy_deny", "deny prevents tool execution while ToolError hook observes it", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec(), {"post_tool_use_correct": True, "tool_error_correct": True, "policy_correct": True, "memory_hook_correct": True, "agent_loop_impact": 0}),
)
