"""Ablation contract retained from the original repair-loop benchmark."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec
from benchmarks.repair_loop.types import PROFILES

DEFINITION = ExperimentDefinition("repair_loop", "Verification, parser, and retrieval ablation.", ("success", "resolved", "turns", "tool_calls", "tokens", "latency", "verification_attempts", "repeated_failures"), ("test_failed", "command_missing", "environment_blocked", "timeout", "repair_exhausted"))
CASES = tuple(
    CaseContract(
        f"repair-{profile.name}", DEFINITION.name, profile.name, "configured test passes or is correctly blocked", DEFINITION.required_metrics, DEFINITION.failure_taxonomy,
        FixtureSpec({"tests/test_sample.py": "def test_sample(): assert True\n"}),
        {"success": profile.name == "full", "resolved": profile.name in {"parser", "full"}, "turns": 2, "tool_calls": 3, "tokens": 120, "latency": 10, "verification_attempts": int(profile.verification_enabled), "repeated_failures": 0},
        scripted_success=profile.name == "full", scripted_resolved=profile.name in {"parser", "full"},
    ) for profile in PROFILES
)
