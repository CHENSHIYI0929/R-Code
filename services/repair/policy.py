"""Mechanism switches used by repair-loop experiments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairLoopPolicy:
    """Keep experiment switches outside the generic agent loop."""

    enable_failure_parser: bool = True
    enable_repository_retrieval: bool = True
