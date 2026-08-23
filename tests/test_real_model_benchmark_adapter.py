from __future__ import annotations

import asyncio

from benchmarks.repair_loop.experiments.harness_regression import CASES
from benchmarks.repair_loop.fixtures import fixture_workspace
from benchmarks.repair_loop.real_model import RealModelAdapter
from benchmarks.repair_loop.runtime_adapter import DeterministicModel, _read


def test_real_adapter_keeps_runtime_path_and_archives_artifacts(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ONECODE_PROVIDER_ID=siliconflow\nSILICONFLOW_MODEL=test-model\nSILICONFLOW_API_KEY=test-key\n", encoding="utf-8")
    adapter = RealModelAdapter(env, artifact_root=tmp_path / "artifacts", model_factory=lambda: DeterministicModel([_read("read", "src/a.py"), "value = 1"]))
    case = CASES[0]
    with fixture_workspace(case.fixture, root=tmp_path) as workspace:
        record = asyncio.run(adapter(case, case.profile, workspace, "real_model"))
    assert record.tier == "real_model"
    assert record.success is True
    assert list((tmp_path / "artifacts").rglob("record.json"))
