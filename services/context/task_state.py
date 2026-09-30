"""Bounded current-task facts used to project active model context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any


class TaskPhase(StrEnum):
    EXPLORE = "explore"
    EDIT_READY = "edit_ready"
    VERIFY = "verify"


@dataclass(frozen=True)
class ConfirmedEvidence:
    tool_name: str
    path: str
    start_line: int
    end_line: int | None
    fingerprint: str
    summary: str
    artifact_ref: str | None = None
    summary_complete: bool = False


@dataclass
class TaskState:
    """Small, bounded state; the transcript remains the complete event log."""

    phase: TaskPhase
    candidate_paths: tuple[str, ...] = ()
    candidate_symbols: tuple[str, ...] = ()
    candidate_snippets: tuple[str, ...] = ()
    max_evidence: int = 6
    max_rejections: int = 6
    confirmed_evidence: list[ConfirmedEvidence] = field(default_factory=list)
    rejected_actions: list[str] = field(default_factory=list)
    changed_files: set[str] = field(default_factory=set)
    action_counts: dict[str, int] = field(default_factory=dict)

    def action_signature(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(tool_input, ensure_ascii=False, sort_keys=True, default=str)}"

    def observe_attempt(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[str, bool]:
        signature = self.action_signature(tool_name, tool_input)
        count = self.action_counts.get(signature, 0)
        self.action_counts[signature] = count + 1
        return signature, count > 0

    def redundant_read_reason(self, tool_input: dict[str, Any]) -> str | None:
        path = _path(tool_input)
        if not path:
            return None
        start, end = _range(tool_input)
        for evidence in self.confirmed_evidence:
            if evidence.tool_name != "read_file" or evidence.path != path:
                continue
            if not evidence.summary_complete:
                # The active context only contains a bounded summary; a later
                # targeted read can still be necessary to recover exact lines.
                continue
            if evidence.start_line <= start and (
                evidence.end_line is None
                or (end is not None and evidence.end_line >= end)
            ):
                return (
                    f"The requested range is already covered by confirmed evidence for {path} "
                    f"({evidence.start_line}-{evidence.end_line or 'EOF'}, fingerprint {evidence.fingerprint[:12]})."
                )
        return None

    def record_rejection(self, tool_name: str, reason: str) -> None:
        self.rejected_actions.append(f"{tool_name}: {reason}")
        if len(self.rejected_actions) > self.max_rejections:
            del self.rejected_actions[: len(self.rejected_actions) - self.max_rejections]

    def record_success(self, tool_name: str, tool_input: dict[str, Any], result: Any) -> None:
        metadata = dict(getattr(result, "metadata", {}) or {})
        if tool_name == "read_file":
            path = _path(tool_input) or str(metadata.get("path") or "")
            start, requested_end = _range(tool_input)
            line_count = metadata.get("line_count")
            end = requested_end
            if end is None and isinstance(line_count, int) and line_count > 0:
                end = start + line_count - 1
            fingerprint = _fingerprint_from_metadata(metadata) or sha256(str(getattr(result, "content", "")).encode("utf-8")).hexdigest()
            self._upsert_evidence(
                ConfirmedEvidence(
                    tool_name="read_file",
                    path=path,
                    start_line=start,
                    end_line=end,
                    fingerprint=fingerprint,
                    summary=_bounded_summary(str(getattr(result, "content", ""))),
                    artifact_ref=_artifact_ref(metadata),
                    summary_complete=_summary_is_complete(str(getattr(result, "content", ""))),
                )
            )
        elif tool_name in {"grep", "glob", "symbol_lookup", "search"}:
            self._upsert_evidence(
                ConfirmedEvidence(
                    tool_name=tool_name,
                    path=_path(tool_input),
                    start_line=1,
                    end_line=None,
                    fingerprint=sha256(str(getattr(result, "content", "")).encode("utf-8")).hexdigest(),
                    summary=_bounded_summary(str(getattr(result, "content", ""))),
                    artifact_ref=_artifact_ref(metadata),
                )
            )
        elif tool_name in {"edit_file", "write_file", "filewrite"}:
            path = _path(tool_input)
            if path:
                self.changed_files.add(path)

    def mark_edit_ready(self) -> None:
        self.phase = TaskPhase.EDIT_READY

    def render(self) -> str:
        lines = ["[task state]", f"Phase: {self.phase.value}"]
        if self.candidate_paths:
            lines.append("Candidate files: " + ", ".join(self.candidate_paths[:5]))
        if self.candidate_symbols:
            lines.append("Candidate symbols: " + ", ".join(self.candidate_symbols[:8]))
        if self.confirmed_evidence:
            lines.append("Confirmed evidence:")
            for item in self.confirmed_evidence[-self.max_evidence :]:
                location = f"{item.path}:{item.start_line}-{item.end_line or 'EOF'}" if item.path else item.tool_name
                reference = f" artifact={item.artifact_ref}" if item.artifact_ref else ""
                lines.append(f"- {location} [{item.fingerprint[:12]}]{reference}: {item.summary}")
        if self.changed_files:
            lines.append("Changed files: " + ", ".join(sorted(self.changed_files)))
        if self.rejected_actions:
            lines.append("Recent rejected/redundant actions:")
            lines.extend(f"- {item}" for item in self.rejected_actions[-3:])
        return "\n".join(lines)

    def _upsert_evidence(self, evidence: ConfirmedEvidence) -> None:
        self.confirmed_evidence = [
            item
            for item in self.confirmed_evidence
            if not (
                item.tool_name == evidence.tool_name
                and item.path == evidence.path
                and item.start_line == evidence.start_line
                and item.end_line == evidence.end_line
            )
        ]
        self.confirmed_evidence.append(evidence)
        if len(self.confirmed_evidence) > self.max_evidence:
            del self.confirmed_evidence[: len(self.confirmed_evidence) - self.max_evidence]


def _path(tool_input: dict[str, Any]) -> str:
    value = tool_input.get("file_path", tool_input.get("path", ""))
    return str(value).replace("\\", "/").lstrip("./") if value else ""


def _range(tool_input: dict[str, Any]) -> tuple[int, int | None]:
    start = max(1, int(tool_input.get("offset") or 1))
    limit = tool_input.get("limit")
    return start, None if limit is None else start + max(0, int(limit)) - 1


def _fingerprint_from_metadata(metadata: dict[str, Any]) -> str:
    fingerprint = metadata.get("fingerprint")
    if isinstance(fingerprint, dict):
        value = fingerprint.get("sha256")
        return str(value) if value else ""
    return ""


def _artifact_ref(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("stored_result_relative_path") or metadata.get("stored_result_path")
    return str(value) if value else None


def _bounded_summary(content: str, limit: int = 480) -> str:
    text = " ".join(content.split())
    if len(text) <= limit:
        return text
    head = max(1, limit * 2 // 3)
    tail = max(1, limit - head)
    return text[:head].rstrip() + " … " + text[-tail:].lstrip()


def _summary_is_complete(content: str, limit: int = 480) -> bool:
    return len(" ".join(content.split())) <= limit
