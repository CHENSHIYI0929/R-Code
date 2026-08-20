# Implement failure-aware retrieval and verification-gated completion

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. It follows `PLANS.md` at the repository root.

## Purpose / Big Picture

After this work, an agent that changes repository files cannot silently finish merely because its model response contains no further tool calls. The runtime treats that response as a candidate finish, runs configured verification commands, and completes only after they pass. A failed command is parsed into paths, line numbers, test identifiers, and exception details; a bounded repository retrieval then supplies the next agent iteration with a durable repair-feedback attachment. This makes the observable loop: edit, verify, fail, retrieve evidence, repair, and verify again.

## Progress

- [x] (2026-08-20 01:00Z) Read runtime, context, tool, hook, observability, active-plan, and technical-debt architecture documents; selected an injected finish gate rather than extending the observation-only `TurnStopped` hook.
- [x] (2026-08-20 01:18Z) Added provider-neutral repair records, local verification runner, failure parser, and workspace-bounded retriever in `services/repair/`.
- [x] (2026-08-20 01:21Z) Added candidate-finish gate handling and verification/retry terminal transitions to `core/loop.py`.
- [x] (2026-08-20 01:24Z) Added `repair_feedback` attachment projection and wired `RepairLoopGate` into CLI construction and session result-store rebinding.
- [x] (2026-08-20 01:28Z) Added focused unit/integration tests and passed targeted loop, repair, attachment, runtime, resume, and import-boundary suites.

## Surprises & Discoveries

- Observation: `TransitionReason.STOP_HOOK_CONTINUE` already exists but `TurnStopped` is deliberately observation-only and its hook result is ignored by the loop.
  Evidence: `core/loop.py` calls `_after_turn_stopped()` immediately before `completed`; `docs/design-docs/hook-architecture.md` labels the event "观察".
- Observation: the sandboxed `uv` invocation cannot initialize its cache outside the workspace, and approval retry was unavailable; the repository's installed Python environment can run the focused tests directly.
  Evidence: `uv` reported `failed to open .../.cache/uv/.../.git: Operation not permitted`; `python -m pytest ...` passed below.
- Observation: CLI test modules importing the Bash tool cannot collect in the installed Python environment because `tree_sitter_bash` is absent.
  Evidence: `ModuleNotFoundError: No module named 'tree_sitter_bash'` from `tools/bash/parser.py`; unrelated resume/runtime tests still passed.

## Decision Log

- Decision: Use an injected `FinishGate` protocol and a `RepairLoopGate` implementation rather than overloading hooks.
  Rationale: Verification is a control-flow decision with durable state and must not be lost when hook exceptions are isolated. The loop remains unaware of command syntax, failure parsing, and retrieval details.
  Date/Author: 2026-08-20 / Codex
- Decision: Trigger automatic verification only when the executor has recorded changed files in `RuntimeState.metadata["files_changed"]`.
  Rationale: This makes normal read-only questions complete normally while every file-changing agent turn is gated.
  Date/Author: 2026-08-20 / Codex
- Decision: Start with deterministic local retrieval, not embeddings or a vector database.
  Rationale: failure paths, tests, changed files, and symbol text are available immediately and are explainable, bounded, and dependency-free.
  Date/Author: 2026-08-20 / Codex
- Decision: Treat a missing verification command as a terminal blocked state once files changed, rather than silently passing or retrying.
  Rationale: a gated finish must be honest about unverified modifications; retrying cannot install or invent the missing check.
  Date/Author: 2026-08-20 / Codex

## Outcomes & Retrospective

Implemented Phase 1–3. A changed-file candidate finish now runs `.onecode/settings.json` `verification.commands`, or the conservative Python-project default `uv run python -m pytest tests -q`. Failed output is saved through `ToolResultStorage`, parsed, retrieved against the workspace, and appended as `repair_feedback`; a pass emits `completed_verified`. The deterministic first retrieval intentionally does not yet use git diff, dependency graph analysis, embeddings, or targeted-test selection. Focused repair/loop tests passed 24/24; CLI-resume/runtime/import-boundary tests passed 16/16. The only environment gap was missing `tree_sitter_bash`, which prevented collection of unrelated CLI modules importing the Bash tool.

## Context and Orientation

`core/loop.py` owns the agent lifecycle. It streams a model response, executes requested tools, and currently completes as soon as a completed model response has no actual tool calls. The loop may depend on provider-neutral service contracts, but it must not import concrete command runners or retrieval code.

`RuntimeState.metadata` is the session-local fact store. The tool executor already appends successfully edited paths to `files_changed`. `MessageStore.append_attachments()` persists durable internal attachment messages to the session transcript; `AttachmentProjector` converts those messages into provider-visible synthetic user messages just before each model call.

`ToolResultStorage` writes complete large results below `.onecode/sessions/<session>/tool-results/`. Verification output must use it so compact feedback can point to complete evidence. `TraceRecorder` records concise event facts and must receive verification and retrieval events.

## Plan of Work

Create `services/repair/` with small provider-neutral immutable records: a check result, verification report, parsed failure evidence, repository snippet, repair bundle, and finish decision. `RepairLoopGate` will discover commands from `.onecode/settings.json` under `verification.commands`; when absent, it uses the repository's Python test command if a `tests/` directory is present. A subprocess runner receives a command only from this trusted project configuration/default and enforces a timeout. It persists combined output as an artifact.

The parser will recognize Python/pytest file-location lines, traceback locations, pytest node ids, exception types, and generic `path:line` diagnostics. The retriever will never escape its workspace. It will collect nearby lines for evidence paths and changed paths, then search at most a bounded number of repository text files for a parsed symbol. Every selected snippet records why it was selected.

Add `FinishGate` to `core/loop.py` as a protocol. On a model response without tool calls, call it before `TurnStopped`. A continue decision appends its repair attachment, emits a retry transition, and starts another model iteration. A pass decision permits the normal completion. A blocked or exhausted decision emits a terminal transition and completion metadata rather than claiming verified success.

Add a `repair_feedback` attachment projection. Wire a gate into `ui/cli/app.py`; ensure `CliRuntime.with_session()` binds it to the newly created session result store. Add tests for parser/retriever behavior, attachment projection, pass/fail gate decisions, and a loop sequence where the first candidate finish fails then a second repaired response passes.

## Concrete Steps

Run from `/Users/chenshiyi/Downloads/R-Code`:

    uv run python -m pytest tests/test_repair_loop.py tests/test_repair_services.py tests/test_attachment_projector.py tests/test_loop.py -q
    uv run python -m pytest tests/test_import_boundaries.py -q
    uv run python -m compileall core services ui

The focused test run must show a failed verification yielding a `verification_failed_retry` transition and a projected `[repair feedback]` message; it must show `completed_verified` only after a passing report.

Completed evidence:

    python -m pytest tests/test_repair_services.py tests/test_repair_loop.py tests/test_attachment_projector.py tests/test_loop.py -q
    24 passed in 0.20s

    python -m pytest tests/test_cli_resume.py tests/test_runtime_integration.py tests/test_import_boundaries.py -q
    16 passed in 0.23s

## Validation and Acceptance

The feature is accepted when an AgentLoop with changed files and a failing check does not emit completion immediately, receives a durable repair attachment, and makes another model call. It is accepted when a passing check subsequently emits `completed_verified`. It is accepted when unmodified/read-only turns still complete without executing verification, and when an unavailable verification command is reported as `verification_blocked` rather than as a code failure.

## Idempotence and Recovery

All changes are additive. Re-running tests is safe. Verification artifacts are content-addressed through `ToolResultStorage`; repeated identical output reuses its file. If a verification command is unavailable, the gate stops with a clear blocked status and preserves output instead of retrying indefinitely. The gate limits repair attempts and identical failure fingerprints.

## Artifacts and Notes

The durable artifact path is `.onecode/sessions/<session>/tool-results/verification-<attempt>.txt`. Model-visible repair feedback includes a bounded output preview plus this path, so a later agent can use `read_file` to inspect the complete result.

## Interfaces and Dependencies

`services.repair.RepairLoopGate` must implement:

    async def evaluate(
        self,
        state: RuntimeState,
        *,
        final_text: str,
        assistant_message: dict[str, Any] | None,
    ) -> FinishDecision

`FinishDecision` must expose `outcome` (`pass`, `continue`, `blocked`, or `exhausted`), optional attachment, verification report, and a human-readable message. `core.loop.AgentLoop` depends only on that protocol. The repair service may use `RuntimeState` for session metadata, `ToolResultStorage` for artifacts, and `TraceRecorder` for events.

Revision note (2026-08-20): created before implementation to record the selected finish-gate design and its required observable behavior.

Revision note (2026-08-20): implementation completed for Phase 1–3; updated progress, findings, outcomes, and concrete test evidence.
