"""Stable, evidence-based failure identities for bounded repair attempts."""

from __future__ import annotations

import hashlib
import re

from services.repair.types import FailureEvidence
from services.verification.types import VerificationOutcome

_TEMP_PATH = re.compile(r"(?:/tmp/|/var/folders/|[A-Za-z]:\\\\(?:Temp|Users)\\\\)[^\s:'\"]+")
_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d{4,}\b")
_SPACE = re.compile(r"\s+")


def fingerprint_failure(
    evidence: tuple[FailureEvidence, ...],
    *,
    outcome: VerificationOutcome,
) -> str:
    """Return a compact identity that ignores ephemeral diagnostics."""

    fields = [outcome]
    for item in evidence[:12]:
        fields.append("|".join((
            item.test_node_id or "",
            item.exception_type or "",
            item.file_path or "",
            str(item.line or ""),
            _normalize_message(item.message),
        )))
    canonical = "\n".join(sorted(fields))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _normalize_message(message: str) -> str:
    value = _TEMP_PATH.sub("<temp>", message)
    value = _HEX.sub("<hex>", value)
    value = _NUMBER.sub("<number>", value)
    return _SPACE.sub(" ", value).strip().lower()[:500]
