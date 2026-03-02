# Doc Review: Three Plugins Missing from Architecture Section 7

**Date:** 2026-02-28
**Section:** architecture.md Section 7 (Plugin System)
**Severity:** Documentation gap (no code defect)

## Summary

Section 7 of `rlm_adk_docs/architecture.md` documents six plugins (7.1-7.6) but three additional plugins exist in the codebase that are not covered:

1. **PolicyPlugin** (`rlm_adk/plugins/policy.py`)
2. **ContextWindowSnapshotPlugin** (`rlm_adk/plugins/context_snapshot.py`)
3. **MigrationPlugin** (`rlm_adk/plugins/migration.py`)

All three are exported from `rlm_adk/plugins/__init__.py`.

## Missing Plugin Details

### PolicyPlugin (`rlm_adk/plugins/policy.py`)

Auth/safety guardrails plugin. Uses the intervene pattern (can short-circuit).

| Callback | Action |
|---|---|
| `on_user_message_callback` | Generates `REQUEST_ID` (uuid) and `IDEMPOTENCY_KEY` (SHA-256 of user+session+message). |
| `before_model_callback` | Checks prompt text against `blocked_patterns` regex list. On match: sets `POLICY_VIOLATION` in state, returns an `LlmResponse` with violation message (short-circuits). |
| `before_tool_callback` | Checks `tool.required_auth_level` against `state["user:auth_level"]`. Returns error dict if unauthorized. |

Constructor args: `blocked_patterns: list[str] | None`.

### ContextWindowSnapshotPlugin (`rlm_adk/plugins/context_snapshot.py`)

Opt-in via `RLM_CONTEXT_SNAPSHOTS=1`. Captures full context window decomposition to JSONL files. Already referenced in the env vars table (Section 10, line 727) but not documented in Section 7.

| Callback | Action |
|---|---|
| `before_model_callback` | Stashes a mutable reference to `LlmRequest` keyed by agent name (for concurrent worker safety via `asyncio.Lock`). |
| `after_model_callback` | Decomposes the (now-mutated) `LlmRequest` into typed chunks (static_instruction, dynamic_instruction, user_prompt, repl_code, repl_output, etc.). Pairs with `usage_metadata` token counts. Writes JSONL to `.adk/context_snapshots.jsonl` and model outputs to `.adk/model_outputs.jsonl`. |
| `on_model_error_callback` | Flushes pending entry with error flag. |
| `after_run_callback` | Closes JSONL file handles. |

Architecture note: Plugins fire BEFORE agent callbacks. The plugin stores a reference in `before_model_callback`, then reads the mutated request in `after_model_callback` (after agent callbacks have run).

### MigrationPlugin (`rlm_adk/plugins/migration.py`)

Opt-in via `RLM_MIGRATION_ENABLED=1` + `RLM_POSTGRES_URL`. End-of-session batch migration from SQLite to PostgreSQL.

| Callback | Action |
|---|---|
| `after_run_callback` | Reads session+events from local SQLite. Upserts session to Postgres. Batch-inserts events with `ON CONFLICT DO NOTHING`. Sets `MIGRATION_STATUS`/`MIGRATION_TIMESTAMP` in state. Optionally prunes old local sessions (FIFO, configurable retention count). |

Env vars: `RLM_MIGRATION_ENABLED`, `RLM_POSTGRES_URL`, `RLM_SESSION_DB`, `RLM_MIGRATION_RETENTION`.

## Recommendation

Add subsections 7.7, 7.8, and 7.9 to architecture.md documenting these three plugins. Also add the MigrationPlugin env vars to the Section 10 table.
