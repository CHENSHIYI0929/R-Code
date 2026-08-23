"""Ablation contract retained from the original repair-loop benchmark."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec
from benchmarks.repair_loop.types import PROFILES

DEFINITION = ExperimentDefinition("repair_loop", "Verification, parser, and retrieval ablation.", ("success", "resolved", "turns", "tool_calls", "tokens", "latency", "verification_attempts", "repeated_failures"), ("test_failed", "command_missing", "environment_blocked", "timeout", "repair_exhausted", "verification_skipped"))
CASES = tuple(
    CaseContract(
        f"repair-{profile.name}", DEFINITION.name, profile.name, "configured test passes or is correctly blocked", DEFINITION.required_metrics, DEFINITION.failure_taxonomy,
        FixtureSpec(
            {
                "src/sample.py": "def value():\n    return 0\n",
                "tests/test_sample.py": "from src.sample import value\n\ndef test_value():\n    assert value() == 200\n",
            },
            {"verification": {"commands": ["python -m pytest tests/test_sample.py -q"]}},
        ),
    ) for profile in PROFILES
)
