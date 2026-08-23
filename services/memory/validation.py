"""Shared, fail-closed validation for memory items before model injection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MemoryValidation:
    injectable: bool
    reason: str = ""


def validate_memory_item(
    item: Any,
    *,
    workspace: Path | str | None = None,
) -> MemoryValidation:
    """Validate an item without deleting it from its audit store.

    The function intentionally uses a small structural protocol: structured
    facts and frontmatter dictionaries may expose ``stale``; file summaries
    additionally expose ``path`` and ``fingerprint``.  This keeps the session
    and long-term stores independent while giving both the same fail-closed
    injection decision.
    """

    stale = _item_value(item, "stale", False)
    if stale is True or str(stale).lower() in {"true", "1", "yes"}:
        return MemoryValidation(False, "marked_stale")

    fingerprint = _item_value(item, "fingerprint")
    path_value = _item_value(item, "path")
    if fingerprint is None or path_value is None or workspace is None:
        return MemoryValidation(True)

    try:
        root = Path(workspace).resolve()
        path = Path(str(path_value)).resolve()
        path.relative_to(root)
        raw = path.read_bytes()
        size = int(_item_value(fingerprint, "size", -1))
        content_hash = str(_item_value(fingerprint, "content_hash", ""))
    except (OSError, TypeError, ValueError):
        return MemoryValidation(False, "file_missing_or_outside_workspace")
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != content_hash:
        return MemoryValidation(False, "file_changed")
    return MemoryValidation(True)


def is_injectable(item: Any, *, workspace: Path | str | None = None) -> bool:
    """Return whether an auditable memory item may be sent to a model."""

    return validate_memory_item(item, workspace=workspace).injectable


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)
