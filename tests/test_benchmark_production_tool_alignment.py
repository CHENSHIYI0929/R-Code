from benchmarks.repair_loop.runtime_adapter import _runtime, DeterministicModel
from ui.cli.app import production_coding_tool_descriptors


def test_benchmark_uses_production_coding_tool_entrypoint(tmp_path):
    _state, _store, _trace, _errors, loop, _memory = _runtime(tmp_path, DeterministicModel(["done"]))
    benchmark_names = {descriptor.name for descriptor in loop.context_engine._tool_schema_provider.descriptors()}
    production_names = {descriptor.name for descriptor in production_coding_tool_descriptors()}
    assert benchmark_names == production_names == {"read_file", "edit_file", "write_file", "glob", "grep"}
