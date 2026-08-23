"""Fresh workspace lifecycle for benchmark cases."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from typing import Iterator

from benchmarks.repair_loop.contracts import FixtureSpec


@contextmanager
def fixture_workspace(spec: FixtureSpec, *, root: Path | None = None) -> Iterator[Path]:
    """Yield a clean case workspace, removing it after the adapter returns."""

    with tempfile.TemporaryDirectory(prefix="r-code-benchmark-", dir=root) as directory:
        workspace = Path(directory)
        for relative, content in spec.files.items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if spec.settings:
            settings = workspace / ".onecode" / "settings.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps(spec.settings), encoding="utf-8")
        yield workspace
