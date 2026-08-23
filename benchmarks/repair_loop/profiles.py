"""Map benchmark profiles to the production repair-gate switches."""

from __future__ import annotations

from benchmarks.repair_loop.types import BenchmarkProfile
from services.repair import RepairLoopPolicy


def repair_loop_policy(profile: BenchmarkProfile) -> RepairLoopPolicy:
    """Return the policy an adapter supplies when verification is enabled."""

    if not profile.verification_enabled:
        raise ValueError("baseline has no RepairLoopGate; do not request a repair policy")
    return RepairLoopPolicy(
        enable_failure_parser=profile.failure_parser_enabled,
        enable_repository_retrieval=profile.repository_retrieval_enabled,
    )
