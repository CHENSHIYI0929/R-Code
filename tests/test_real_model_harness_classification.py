from __future__ import annotations

import asyncio

from benchmarks.repair_loop.experiments.harness_regression import CASES
from benchmarks.repair_loop.fixtures import fixture_workspace
from benchmarks.repair_loop.real_model import RealModelAdapter
from services.model.types import ProviderError


class TimeoutModel:
    async def stream(self, snapshot):
        raise ProviderError("timeout", error_type="timeout_error")
        yield  # pragma: no cover


def test_harness_provider_timeout_is_not_misclassified_as_policy_denied(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ONECODE_PROVIDER_ID=siliconflow\nSILICONFLOW_MODEL=test\nSILICONFLOW_API_KEY=test\n", encoding="utf-8")
    case = CASES[1]
    adapter = RealModelAdapter(env, model_factory=TimeoutModel)
    with fixture_workspace(case.fixture, root=tmp_path) as workspace:
        record = asyncio.run(adapter(case, case.profile, workspace, "real_model"))
    assert record.success is False
    assert record.failure_kind == "provider_timeout"
    assert record.tool_calls == 0
