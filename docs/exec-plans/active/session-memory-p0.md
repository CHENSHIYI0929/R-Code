# Implement structured, fresh Session Memory

This ExecPlan is a living document and follows `PLANS.md` at the repository root.

## Purpose / Big Picture

After this work, successful file reads record durable, structured facts for the current session; writes invalidate old file facts; and compaction never injects a file summary whose on-disk content changed. `session-memory.json` is the only source of truth; Markdown is a readable render-only artifact.

## Progress

- [x] (2026-08-23) Read the memory, compaction, tool-executor, retrieval, active-plan, and technical-debt code paths.
- [x] (2026-08-23) Recorded the P0 design and began the focused baseline test command.
- [x] (2026-08-23) Added structured JSON state, render-only Markdown, and atomic state writes.
- [x] (2026-08-23) Added post-tool and tool-error fact updates through the existing hook registry.
- [x] (2026-08-23) Added SHA-256 freshness validation before session-memory compaction.
- [x] (2026-08-23) Repaired the invalid `R-CodeError` identifier as `RCodeError` and reran focused regression tests (62 passed).

## Surprises & Discoveries

- Observation: `PostToolUse` runs before executor-owned `files_read`/`files_changed` updates.
  Evidence: `services/tools/executor.py` invokes the hook before `_apply_success_side_effects`.
- Observation: the current long-term selector catches model failures, but topic reads are not caught by its preparer. This is deliberately out of P0 scope and remains work for long-term retrieval validation.

## Decision Log

- Decision: implement only P0 now: structured Session Memory, tool-driven updates, and freshness validation.
  Rationale: items 4--6 consume the same state but expand compaction and long-term-memory policy.
  Date/Author: 2026-08-23 / Codex.
- Decision: keep `session-memory.md` as rendered compatibility output and store canonical state in `session-memory.json`.
  Rationale: current Markdown frontmatter parser has only flat string support; a sidecar preserves a typed, evolvable schema.
  Date/Author: 2026-08-23 / Codex.

## Outcomes & Retrospective

The P0 implementation keeps the AgentLoop and executor public protocols unchanged. It adds a session-local JSON state file, preserves the readable Markdown artifact, and uses existing hooks rather than tool-name branches in the loop. The invalid `R-CodeError` identifier was corrected to `RCodeError`; focused regression tests passed with `62 passed in 0.45s`. Long-term promotion and retrieval validation remain intentionally outside this P0 change.

Revision outcome (2026-08-23): JSON is now the only Session Memory source of truth. Session extraction children have an empty tool registry and return `ExtractionResult` JSON for parent-side `merge_state()`; Markdown is render-only. Focused session, compaction, long-term retrieval, subagent, executor, and error tests passed with `50 passed`.

## Context and Orientation

`services/compaction/session_memory.py` owns session-local continuity memory. `ContextCompactionService._try_session_memory_compact` reads it and creates a compact summary plus recent message tail. `RegistryToolExecutor` emits `PostToolUse` after a successful concrete tool handler and emits `ToolError` for failures. CLI runtime composition in `ui/cli/app.py` owns the shared hook registry and the SessionMemoryStore.

Freshness means a stored file summary is eligible for injection only when its path still exists inside the workspace and its SHA-256 content digest matches the digest recorded when it was observed. A stale summary remains stored for audit but is omitted from rendered injected memory.

## Plan of Work

Add typed state and a JSON sidecar in `services/compaction/session_memory.py`; Markdown is rendered only and never parsed for state. Add a tool fact updater that consumes existing hook payloads. It records only deterministic facts: observed file path, bounded preview, fingerprint, writes invalidating prior summaries, and bash failure metadata. Add a validator to SessionMemoryStore and call it from `_try_session_memory_compact` before passing the rendered memory to `_compact_messages`.

Wire the updater in `ui/cli/app.py` after creating the store. Add focused tests for persistence, file update/invalidation, and stale suppression. Run focused regression tests and then the full test suite.

## Concrete Steps

From `/Users/chenshiyi/Downloads/R-Code`, run:

    uv run python -m pytest tests/test_session_memory_compaction.py tests/test_session_memory_extraction.py tests/test_tool_registry_and_executor.py tests/test_file_tools_guard.py -q

Then run the new tests and the complete suite:

    uv run python -m pytest tests/test_session_memory_structured.py tests/test_session_memory_tool_updates.py tests/test_session_memory_freshness.py -q
    uv run python -m pytest tests -q

## Validation and Acceptance

Tests must demonstrate that a file read produces a fresh structured summary; a successful edit makes it stale; changing the file outside R-Code makes it stale before compaction; compaction excludes stale content while retaining recent messages; and Markdown cannot override canonical JSON.

## Idempotence and Recovery

State writes use a temporary file and replace operation. If JSON is missing or invalid, the store returns an empty state rather than parsing Markdown or blocking a user turn.

## Interfaces and Dependencies

The final store will expose `read_state()`, `write_state(state)`, `update_from_tool_payload(payload)`, and `validated_for_injection(workspace)`. These are internal services: `AgentLoop` and `ToolExecutor.execute()` keep their public protocols unchanged.

Revision note (2026-08-23): updated after repairing the collection blocker and passing focused regression tests.
