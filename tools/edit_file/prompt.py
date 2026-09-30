"""Prompt text for the edit_file tool."""

PROMPT = """Use when:
- You need a small, targeted change in an existing file.
- You can provide enough exact surrounding text to identify the intended replacement.

Prefer instead:
- Use `write_file` when the entire file should be replaced or created from scratch.

Rules:
- Existing files must be read in this session before editing.
- The file version is checked against the last observed SHA-256 before every edit. Pass `expected_sha256` from a read or symbol lookup when preparing a local patch.
- `old_string` must match the current file content exactly.
- When a match is not unique, provide more surrounding context or set `replace_all=true` only if every occurrence should change.
- A missing file can only be created by passing an empty `old_string`.

Returns:
- A summary with the edited path and replacement count.

If it fails:
- If `old_string` is not found or has multiple matches, read the relevant lines and retry with a more precise string.
- If the file has not been read, read it first and then retry.
- If `file_version_mismatch` occurs, read the current file, locate the target again, and generate a fresh edit; do not replay the old patch.
"""
