"""Executable post-resume stale-fact cases, without changing recovery code."""

from benchmarks.repair_loop.contracts import CaseContract, ExperimentDefinition, FixtureSpec

DEFINITION = ExperimentDefinition(
    "resume_staleness",
    "Changed files must not let a resumed task answer from an obsolete tool result.",
    ("task_success", "stale_fact_used", "tool_steps"),
    ("stale_fact_used", "missing_file"),
)

CASES = tuple(
    CaseContract(
        f"resume-{scenario}-{strategy}",
        DEFINITION.name,
        f"{scenario}_{strategy}",
        "resumed answer matches the current workspace state",
        DEFINITION.required_metrics,
        DEFINITION.failure_taxonomy,
        FixtureSpec({"src/state.py": "VERSION = 1\n"}),
    )
    for scenario in ("modified", "deleted")
    for strategy in ("retain", "stale_mark", "force_reread")
)
