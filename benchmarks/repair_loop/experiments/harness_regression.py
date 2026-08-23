"""Fake-model regression contract for runtime harness behavior."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition(
    "harness_regression",
    "Runtime, tools, hooks, budgets, recovery, and sandbox policy remain deterministic.",
    ("runtime_correct", "tool_correct", "hook_correct", "budget_respected", "recovery_steps", "security_boundary"),
    ("runtime_error", "tool_error", "hook_error", "budget_exceeded", "recovery_exhausted", "policy_denied"),
)
CASES = (
    CaseContract("harness-runtime-tool", DEFINITION.name, "scripted_baseline", "scripted runtime returns the expected tool result", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"src/a.py": "value = 1\n"}), {"runtime_correct": True, "tool_correct": True, "hook_correct": True, "budget_respected": True, "recovery_steps": 1, "security_boundary": True, "tool_calls": 1, "latency": 3}),
    CaseContract("harness-policy-deny", DEFINITION.name, "scripted_baseline", "outside-workspace write is denied before execution", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec(), {"runtime_correct": True, "tool_correct": True, "hook_correct": True, "budget_respected": True, "recovery_steps": 0, "security_boundary": True, "tool_calls": 0, "latency": 1}),
)
