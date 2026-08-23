"""Reproducibility metadata attached to every benchmark run."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from benchmarks.repair_loop.contracts import FixtureSpec

BENCHMARK_VERSION = "layered-v1"


@dataclass(frozen=True)
class ReproducibilityMetadata:
    git_commit: str
    branch: str
    benchmark_version: str
    fixture_hash: str
    model: str
    decoding_params: dict[str, Any]
    feature_flags: dict[str, bool]


def fixture_hash(spec: FixtureSpec) -> str:
    payload = {"files": dict(sorted(spec.files.items())), "settings": spec.settings}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def collect_metadata(spec: FixtureSpec, *, model: str, decoding_params: dict[str, Any] | None = None, feature_flags: dict[str, bool] | None = None, repository: Path | None = None) -> ReproducibilityMetadata:
    repository = repository or Path.cwd()
    return ReproducibilityMetadata(_git(repository, "rev-parse", "HEAD"), _git(repository, "branch", "--show-current"), BENCHMARK_VERSION, fixture_hash(spec), model, dict(decoding_params or {}), dict(feature_flags or {}))


def with_fixture(metadata: ReproducibilityMetadata, spec: FixtureSpec) -> ReproducibilityMetadata:
    return replace(metadata, fixture_hash=fixture_hash(spec))


def _git(repository: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repository), *args], text=True, stderr=subprocess.DEVNULL).strip() or "detached"
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
