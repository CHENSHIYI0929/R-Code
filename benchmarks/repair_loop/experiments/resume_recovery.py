"""Resume and invalidation contract for session persistence."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition("resume_recovery", "Resume restores valid state and invalidates stale workspace facts.", ("resume_success", "stale_reuse", "recovery_steps"), ("missing_file", "workspace_changed", "stale_memory", "configuration_changed"))
_FAILURE_BY_PROFILE = {"file_modified": "workspace_changed", "file_deleted": "missing_file", "workspace_changed": "workspace_changed", "stale_memory": "stale_memory", "config_changed": "configuration_changed"}
CASES = tuple(
    CaseContract(f"resume-{profile}", DEFINITION.name, profile, "resume either restores safely or reports recovery", DEFINITION.required_metrics, DEFINITION.failure_taxonomy, FixtureSpec({"src/state.py": "VERSION = 1\n"})) for profile in ("normal", "file_modified", "file_deleted", "workspace_changed", "stale_memory", "config_changed")
)
