"""Project durable attachment messages into provider-visible messages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.runtime_state import RuntimeState
from services.plans.attachments import (
    build_plan_mode_attachment,
    build_plan_mode_exit_attachment,
    build_plan_mode_reentry_attachment,
)


class AttachmentProjector:
    def project(
        self,
        messages: tuple[dict[str, Any], ...],
        state: RuntimeState,
    ) -> tuple[dict[str, Any], ...]:
        """Replace internal attachment roles before provider payload creation."""

        _ = state
        projected: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") != "attachment":
                projected.append(deepcopy(message))
                continue
            projected.extend(_project_attachment_message(message))
        return tuple(projected)


def _project_attachment_message(message: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    attachment = message.get("attachment")
    if not isinstance(attachment, dict):
        return (_notice("Unsupported attachment message with missing payload."),)
    attachment_type = attachment.get("type")
    if attachment_type == "file":
        return _project_file(attachment, message)
    if attachment_type == "skill":
        return (_project_skill(attachment),)
    if attachment_type == "directory":
        return (_project_directory(attachment),)
    if attachment_type == "edited_text_file":
        return (_project_edited_text_file(attachment),)
    if attachment_type == "queued_command":
        return (
            _notice(
                f"[queued command from coordinator]\n{attachment.get('content', '')}"
            ),
        )
    if attachment_type == "background_task_notification":
        return (_notice(_background_task_notification_content(attachment)),)
    if attachment_type in {"relevant_memories", "nested_memory"}:
        return (_notice(_memory_content(attachment)),)
    if attachment_type == "plan_mode":
        return _project_plan_mode(attachment)
    if attachment_type == "hook_result":
        return (_notice(f"[hook result]\n{attachment.get('content', '')}"),)
    if attachment_type == "repair_feedback":
        return (_project_repair_feedback(attachment),)
    if attachment_type == "navigation_hint":
        return (_project_navigation_hint(attachment),)
    if attachment_type == "attachment_error":
        return (_notice(_error_content(attachment)),)
    return (_notice(f"Unsupported attachment type: {attachment_type}"),)


def _project_plan_mode(attachment: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Render the new structured plan-mode attachment into a provider-visible
    user message.

    The projector treats plan_mode as a first-class attachment variant. We
    rebuild the payload through ``services.plans.attachments`` so the
    formatting stays in one place; legacy attachments (no ``variant`` key)
    fall back to the intro form.
    """

    plan_path = str(attachment.get("plan_path", ""))
    plan_content = str(attachment.get("plan_content", ""))
    variant = str(attachment.get("variant", "intro"))

    if variant == "reentry":
        payload = build_plan_mode_reentry_attachment(plan_path, plan_content)
    elif variant == "exit":
        payload = build_plan_mode_exit_attachment(plan_path, plan_content)
    else:
        payload = build_plan_mode_attachment(plan_path, plan_content=plan_content)

    return (
        {
            "role": "user",
            "content": payload["content"],
            "metadata": {
                "synthetic": True,
                "source": "attachment",
                "attachment_type": "plan_mode",
                "plan_path": plan_path,
                "variant": variant,
            },
        },
    )


def _project_file(
    attachment: dict[str, Any],
    message: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    metadata = (
        message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    )
    attachment_id = str(
        metadata.get("attachment_id") or attachment.get("id") or "unknown"
    )
    call_id = f"attachment_read_{attachment_id}"
    path = str(attachment.get("path", ""))
    arguments: dict[str, Any] = {"file_path": path}
    offset = attachment.get("offset")
    limit = attachment.get("limit")
    if isinstance(offset, int):
        arguments["offset"] = offset
    if isinstance(limit, int):
        arguments["limit"] = limit
    details = "\n".join(f"- {key}: {value}" for key, value in arguments.items())
    notice = (
        "[attachment file]\n"
        f"Synthetic call id: {call_id}\n"
        "Equivalent tool: read_file\n"
        f"{details}\n\n"
        "Result:\n"
        f"{attachment.get('content', '')}"
    )
    if attachment.get("truncated") is True:
        notice += (
            "\n\n[Attachment content was truncated; use read_file if more detail is needed.]"
        )
    return (
        {
            "role": "user",
            "content": notice,
            "metadata": {
                "synthetic": True,
                "source": "attachment",
                "attachment_type": "file",
            },
        },
    )


def _project_directory(attachment: dict[str, Any]) -> dict[str, Any]:
    entries = attachment.get("entries")
    names = (
        "\n".join(f"- {name}" for name in entries)
        if isinstance(entries, list)
        else ""
    )
    truncated = "\n[Directory listing truncated]" if attachment.get("truncated") else ""
    return _notice(
        f"[directory attachment]\nPath: {attachment.get('path', '')}\nEntries:\n{names}{truncated}"
    )


def _project_edited_text_file(attachment: dict[str, Any]) -> dict[str, Any]:
    return _notice(
        "A previously read text file was edited outside the model-visible tool "
        f"call flow.\nPath: {attachment.get('path', '')}\nDiff:\n{attachment.get('diff', '')}"
    )


def _project_skill(attachment: dict[str, Any]) -> dict[str, Any]:
    """Project a loaded skill as runtime-provided user context."""

    args = str(attachment.get("args", ""))
    source = str(attachment.get("source", ""))
    name = str(attachment.get("skill_name", "unknown"))
    content = str(attachment.get("content", ""))
    return {
        "role": "user",
        "content": (
            f"[skill loaded: {name}]\n"
            f"Arguments: {args}\n"
            f"Source: {source}\n\n"
            f"{content}"
        ),
        "metadata": {
            "synthetic": True,
            "source": "attachment",
            "attachment_type": "skill",
        },
    }


def _project_repair_feedback(attachment: dict[str, Any]) -> dict[str, Any]:
    evidence = attachment.get("evidence") if isinstance(attachment.get("evidence"), list) else []
    snippets = attachment.get("snippets") if isinstance(attachment.get("snippets"), list) else []
    hunks = attachment.get("current_diff") if isinstance(attachment.get("current_diff"), list) else []
    evidence_text = "\n".join(
        f"- {item.get('file_path') or 'unknown'}:{item.get('line') or '?'} {item.get('exception_type') or item.get('category')}: {item.get('message', '')}"
        for item in evidence[:8] if isinstance(item, dict)
    ) or "- No structured diagnostic was recognized; inspect the verification artifact."
    snippet_text = "\n\n".join(
        f"[{item.get('path')}:{item.get('start_line')}-{item.get('end_line')} — {item.get('reason')}]\n{item.get('content', '')}"
        for item in snippets[:8] if isinstance(item, dict)
    ) or "(No additional repository snippets were found.)"
    hunk_text = "\n".join(
        f"- {item.get('path')}:{item.get('start_line')}-{item.get('end_line')} {item.get('symbol') or ''}"
        for item in hunks[:12] if isinstance(item, dict)
    ) or "- No current diff hunks were available."
    return _notice(
        "[repair feedback]\n"
        f"Verification attempt: {attachment.get('attempt', '?')}\n"
        f"Full verification artifact: {attachment.get('artifact_path', '')}\n"
        f"Changed files: {', '.join(str(x) for x in attachment.get('changed_files', []))}\n\n"
        "Current diff locations (localization only):\n" + hunk_text + "\n\n"
        "Failure evidence:\n" + evidence_text + "\n\n"
        "Retrieved repository context:\n" + snippet_text + "\n\n"
        "Repair the diagnosed issue, then run verification before finishing."
    )


def _project_navigation_hint(attachment: dict[str, Any]) -> dict[str, Any]:
    files = attachment.get("candidate_files") if isinstance(attachment.get("candidate_files"), list) else []
    symbols = attachment.get("candidate_symbols") if isinstance(attachment.get("candidate_symbols"), list) else []
    snippets = attachment.get("snippets") if isinstance(attachment.get("snippets"), list) else []
    file_text = "\n".join(f"- {item.get('path')} (score={item.get('score')}, signals={', '.join(item.get('signals', []))})" for item in files[:5] if isinstance(item, dict)) or "- No confident file candidate."
    symbol_text = "\n".join(f"- {item.get('path')}::{item.get('symbol')} [{item.get('kind')}]" for item in symbols[:8] if isinstance(item, dict)) or "- No confident symbol candidate."
    snippet_text = "\n\n".join(f"[{item.get('path')}:{item.get('start_line')}-{item.get('end_line')}]\n{item.get('content', '')}" for item in snippets[:3] if isinstance(item, dict))
    return _notice(
        "[first-pass localization hint]\n"
        f"Navigation stage: {attachment.get('navigation_stage', 'explore')}\n"
        "These candidates were ranked from the issue text and repository structure. They are navigation hints, not a prescribed patch; verify the evidence before editing.\n\n"
        f"Candidate files:\n{file_text}\n\nCandidate symbols:\n{symbol_text}"
        + (f"\n\nBounded excerpts:\n{snippet_text}" if snippet_text else "")
    )


def _notice(content: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": content,
        "metadata": {"synthetic": True, "source": "attachment"},
    }


def _memory_content(attachment: dict[str, Any]) -> str:
    return (
        f"[memory attachment]\nPath: {attachment.get('path', '')}\n"
        f"{attachment.get('content', '')}"
    )


def _background_task_notification_content(attachment: dict[str, Any]) -> str:
    return "\n".join(
        [
            "<task_notification>",
            f"<task_id>{attachment.get('task_id', '')}</task_id>",
            f"<task_type>{attachment.get('task_type', '')}</task_type>",
            f"<output_file>{attachment.get('output_file', '')}</output_file>",
            f"<status>{attachment.get('status', '')}</status>",
            f"<summary>{attachment.get('summary', '')}</summary>",
            "</task_notification>",
        ]
    )


def _error_content(attachment: dict[str, Any]) -> str:
    return (
        "[attachment resolution error]\n"
        f"Mention: {attachment.get('mention', '')}\n"
        f"Error: {attachment.get('error', '')}\n"
        f"Message: {attachment.get('message', '')}"
    )
