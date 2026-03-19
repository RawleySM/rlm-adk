<!-- generated: 2026-03-18 -->
<!-- revised: 2026-03-18 — incorporates red-team review findings -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Add `.adk/` Data Janitor — Plugin + Standalone Script

## Context

RLM-ADK accumulates telemetry (SQLite), session state (SQLite), artifacts (versioned files), and JSONL snapshots in `rlm_adk/.adk/`. Over time these grow unbounded. Build a **time-based retention system** with independent policies per data type, delivered as both an ADK plugin (primary — runs after each agent run, zero concurrency issues) and a standalone CLI script (fallback — for manual cleanup or cron scheduling). Research indicates SQLite performs well up to ~50 GB on SSDs with WAL mode, but for a personal dev agent's telemetry, time-based retention (not size-based) is the correct framing — it produces predictable, deterministic cleanup regardless of relative data sizes ([SQLite limits](https://sqlite.org/limits.html), [2025 benchmarks](https://markaicode.com/sqlite-4-production-database-benchmarks-pitfalls/)).

### Why time-based, not size-based

The original v1 prompt used a size-based waterfall (artifacts → traces → sessions). Red-team review exposed fundamental problems with that approach:

- **Unpredictable behavior:** Whether sessions get touched depends on artifact sizes — same script produces radically different outcomes depending on data ratios.
- **Artifact version preservation defeats itself:** Most artifacts have only `versions/0/`, making every file the "newest version." Phase 1 would reclaim nothing.
- **`.adk/` contains non-data dirs** (e.g. dashboard files) that inflate size calculations but are untouched by pruning, causing the janitor to over-prune data to compensate.

Time-based retention with independent per-type policies is simpler, predictable, and what every mature log/telemetry system uses (logrotate, journald, Prometheus).

## Original Transcription

> Please build a cron job script that runs let's say, every ten minutes and check the memory storage and file accumulation of my tele telemetry trace session data in this SQL lite files. But also the artifacts, generated and clean out the oldest data under a limit or to to bring the entire repo to a a limit that I'd like you to web search it would be a, a good limit, that doesn't slow things down.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

### 1. Spawn a `Janitor-Core` teammate to create `rlm_adk/scripts/adk_janitor.py` — the standalone cleanup script.

The script must:
- Accept CLI args:
  - `--trace-retention-days` (default 14) — delete traces older than N days
  - `--session-retention-count` (default 50) — keep N most recent sessions
  - `--artifact-retention-days` (default 30) — delete artifact session dirs older than N days
  - `--jsonl-max-mb` (default 10) — truncate JSONL files to last N MB
  - `--adk-dir` (default: auto-resolve to `rlm_adk/.adk/` — see path resolution note below)
  - `--dry-run` (report only, no deletes)
  - `--verbose`
- Use only stdlib (`sqlite3`, `pathlib`, `argparse`, `os`, `time`, `logging`). No external dependencies.
- Exit 0 on success, exit 1 on error (with traceback to stderr).
- Must be runnable standalone: `.venv/bin/python rlm_adk/scripts/adk_janitor.py` (use direct path, NOT `python -m` — avoids PYTHONPATH issues in cron environments).
- **Graceful no-op on fresh install:** If `.adk/` does not exist, or any expected DB/directory is missing, log "nothing to clean" and exit 0. Do not crash.

#### Phase 1 — Traces DB pruning (`traces.db`)

- **CRITICAL: `traces.db` has NO foreign key constraints.** The schema defines zero `FOREIGN KEY` declarations (see `sqlite_tracing.py` L209-321). The janitor must manually delete from all 4 tables by `trace_id`:
  ```sql
  DELETE FROM session_state_events WHERE trace_id IN (...)
  DELETE FROM telemetry WHERE trace_id IN (...)
  DELETE FROM spans WHERE trace_id IN (...)
  DELETE FROM traces WHERE trace_id IN (...)
  ```
- **Never delete running traces.** Filter: `WHERE status != 'running'` on all deletes.
- **Smart pruning order:** Delete `status='completed'` traces first (oldest-first by `start_time`). Only after all completed traces beyond the retention window are gone, consider non-completed/non-running traces. This preserves diagnostic value — a 3-day-old crash trace is more important than a 1-hour-old successful run.
- **Minimum retention floor:** Always keep at least 10 traces regardless of age.
- Delete in batches of 50 trace_ids per transaction.
- **Do NOT use full `VACUUM`.** Full VACUUM temporarily doubles the DB size and requires an exclusive lock that can invalidate the `SqliteTracingPlugin`'s long-lived `self._conn` (held open for plugin lifetime, see `sqlite_tracing.py` L368). Instead:
  1. On first ever janitor run against a DB, check `PRAGMA auto_vacuum`. If it returns 0 (none), set `PRAGMA auto_vacuum = INCREMENTAL` — this requires a one-time full `VACUUM` to restructure the DB, which is safe because the janitor only runs post-run or standalone.
  2. On subsequent runs, call `PRAGMA incremental_vacuum(1000)` (reclaim up to 1000 pages) after deletes. This is non-blocking, does not require an exclusive lock, and does not invalidate open connections.
  3. If any SQLite operation fails with `SQLITE_BUSY` (database is locked), log a warning and skip — retry next cycle. Do not crash.

#### Phase 2 — Session DB pruning (`session.db`)

- **Coordinate with `MigrationPlugin._prune_local_sessions()`** (`migration.py` L348-394). That plugin already prunes sessions by count with `retention_count` (default 50) in `after_run_callback`. The janitor should use the **same approach** as MigrationPlugin to avoid conflicting strategies:
  - `PRAGMA foreign_keys = ON` (required — `session.db` DOES have FK with `ON DELETE CASCADE` on the events table, but SQLite FKs are OFF by default per-connection)
  - Delete oldest sessions by `update_time ASC`, keeping `--session-retention-count` most recent
  - The janitor's default of 50 matches MigrationPlugin's default, so they reinforce rather than race
- **Same `incremental_vacuum` strategy as Phase 1** (not full VACUUM).

#### Phase 3 — Artifact pruning (`.adk/artifacts/`)

- **Session-scoped deletion, not version-scoped.** The original v1 approach (delete old versions, keep newest) fails because most artifacts have only `versions/0/`. Instead:
  1. List all session directories under `artifacts/users/{user_id}/sessions/`.
  2. For each session dir, find the newest `mtime` across all files within it.
  3. If that newest mtime is older than `--artifact-retention-days`, delete the entire session directory tree.
  4. **Cross-reference with `session.db`:** If the janitor deleted a session in Phase 2, also delete its corresponding artifact directory. If an artifact session dir exists with no matching session in `session.db`, it is an orphan — delete it.
- Clean up empty parent directories after deletion.

#### Phase 4 — JSONL file rotation (`context_snapshots.jsonl`, `model_outputs.jsonl`)

*[Added — the original transcription didn't mention these, but they are append-only files that grow unbounded. Written by `ContextWindowSnapshotPlugin` (agent.py L453-457). Not covered by any other pruning phase.]*

- If `context_snapshots.jsonl` exceeds `--jsonl-max-mb`:
  1. Read the file, keep only the last `--jsonl-max-mb` worth of bytes (truncate from the front, preserving complete trailing lines).
  2. Write back. This is a simple tail-truncation — no parsing needed, just seek to `filesize - limit`, scan forward to the next newline, and keep from there.
- Same for `model_outputs.jsonl`.

#### Summary output

- Always log a final summary line: `"Janitor: reclaimed {X} MB — {T} traces pruned, {S} sessions pruned, {A} artifact dirs removed, {J} MB JSONL truncated"`.
- With `--verbose`, log every individual delete action.
- With `--dry-run`, prefix all actions with `[DRY RUN]` and do not execute any deletes/truncations.

#### Path resolution

- **Do NOT copy `_package_dir()` from `agent.py` L98.** That function uses `Path(__file__).resolve().parent` which resolves to the directory of the file it's defined in. Since the janitor lives at `rlm_adk/scripts/adk_janitor.py`, naively copying this pattern resolves to `rlm_adk/scripts/`, not `rlm_adk/`.
- Instead: `Path(__file__).resolve().parent.parent / ".adk"` (go up from `scripts/` to `rlm_adk/`, then into `.adk/`). Or accept `--adk-dir` explicitly. Both must work.

### 2. Spawn a `Janitor-Plugin` teammate to create `rlm_adk/plugins/janitor.py` — an ADK plugin that runs cleanup after each agent run.

*[Added — the original transcription only mentioned cron, but an ADK plugin is the better primary delivery mechanism. It runs only when the tool is actually used, has no concurrency issues (the run is over), runs in the correct Python environment, and follows the pattern already established by `MigrationPlugin.after_run_callback()`.]*

The plugin must:
- Subclass `BasePlugin` with `name="janitor"`.
- Accept constructor args matching the CLI defaults: `trace_retention_days=14`, `session_retention_count=50`, `artifact_retention_days=30`, `jsonl_max_mb=10`.
- Implement `after_run_callback(*, invocation_context: InvocationContext)` that calls the same core pruning logic as the standalone script.
- **Factor the pruning logic into a shared module** (`rlm_adk/scripts/janitor_core.py`) that both the CLI script and the plugin import. Do not duplicate pruning code.
- Wire the plugin in `_default_plugins()` in `agent.py`, controlled by env var `RLM_JANITOR=1` (default off — user opts in). When enabled, it should run **after** `MigrationPlugin` in plugin order to avoid racing on session pruning.

### 3. Spawn a `Cron-Wirer` teammate to create `rlm_adk/scripts/install_janitor_cron.sh` — a shell script that installs/updates the crontab entry.

The shell script must:
- Add a crontab entry: `*/10 * * * * /absolute/path/to/.venv/bin/python /absolute/path/to/rlm_adk/scripts/adk_janitor.py >> /absolute/path/to/.adk/janitor.log 2>&1`
  - Log file goes in `.adk/janitor.log` (NOT `/tmp/` — an unbounded file in `/tmp/` persists across reboots and is never cleaned).
  - Use absolute paths (cron has minimal `$PATH`).
- Be idempotent — if the entry already exists, replace it (don't duplicate). Use a marker comment like `# rlm-adk-janitor` for grep-based detection.
- Auto-detect paths relative to the script's own location.
- Support `--remove` flag to uninstall the cron entry.
- Print what it did to stdout.

### 4. Spawn a `Schema-Inspector` teammate to add schema introspection to `janitor_core.py`.

- For `traces.db`: Verify the expected 4 tables (`traces`, `spans`, `telemetry`, `session_state_events`) exist via `SELECT name FROM sqlite_master WHERE type='table'`. If any are missing, log a warning and skip trace pruning. Check for `start_time` and `status` columns on `traces` via `PRAGMA table_info(traces)`.
  - *[Rationale: `SqliteTracingPlugin._migrate_schema()` (L392) evolves the schema over time. The janitor's hardcoded table knowledge may become stale.]*
- For `session.db`: Introspect via `PRAGMA table_info(...)` and `SELECT name FROM sqlite_master` to discover the session table name (`sessions`) and its timestamp column (`update_time`). If schema doesn't match expectations, log a warning and skip session pruning.
- If schema doesn't match expectations, log a warning and skip that phase — do not crash.

## Provider-Fake Fixture & TDD

**Fixture:** Not applicable — this is standalone cleanup logic with no ADK agent pipeline involvement.

**TDD approach:**

1. **Red:** Write `tests_rlm_adk/test_adk_janitor.py`. Create a test that builds a synthetic `.adk/` directory in `tmp_path` with:
   - A `traces.db` with the full 4-table schema + 20 sample traces (15 completed, 3 errored, 2 running) spanning 30 days
   - A `session.db` with the ADK sessions/events schema + 60 sample sessions
   - Artifact session dirs with varying mtimes
   - A 15 MB `context_snapshots.jsonl` file
   Run the janitor with `--trace-retention-days 7 --session-retention-count 10 --artifact-retention-days 14 --jsonl-max-mb 5`. Assert:
   - Only completed traces older than 7 days are deleted
   - Running traces are preserved regardless of age
   - Errored traces are preserved (deleted only after completed traces)
   - At least 10 traces remain (minimum floor)
   - 50 oldest sessions are deleted (60 - 10 retention)
   - Old artifact session dirs are gone
   - `context_snapshots.jsonl` is ~5 MB
2. **Green:** Implement core pruning logic. Run, confirm pass.
3. **Red:** Write test for `--dry-run` — assert nothing is deleted but summary is printed.
4. **Green:** Implement dry-run flag.
5. **Red:** Write test for manual cascade delete on `traces.db` — assert spans/telemetry/session_state_events rows are removed when their parent trace is deleted (NOT via FK CASCADE — verify manual DELETE).
6. **Green:** Implement manual cascade logic.
7. **Red:** Write test that `PRAGMA foreign_keys = ON` is set before session deletes — insert a session with events, delete the session, assert events are cascade-deleted.
8. **Green:** Verify FK enable in session pruning code.
9. **Red:** Write test for orphan artifact cleanup — create artifact dir for a session_id that doesn't exist in `session.db`, assert it gets cleaned up.
10. **Green:** Implement cross-reference logic.
11. **Red:** Write test for fresh install (empty/missing `.adk/`) — assert exit 0 with no errors.
12. **Green:** Implement graceful no-op.
13. **Red:** Write test for `SQLITE_BUSY` handling — mock `sqlite3.connect` to raise `OperationalError("database is locked")`, assert janitor logs warning and exits 0 (not crash).
14. **Green:** Implement busy-handling.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the janitor correctly prunes a synthetic `.adk/` directory across all four phases.

## Considerations

- **`SqliteTracingPlugin` holds a long-lived connection** (`self._conn` at L368). Full `VACUUM` from an external process can invalidate this connection mid-run, causing `SQLITE_SCHEMA` errors. The `incremental_vacuum` approach avoids this entirely.
- **MigrationPlugin coordination:** Both the janitor plugin and `MigrationPlugin` prune sessions. Using the same retention strategy (count-based, `update_time ASC`) and wiring the janitor plugin after MigrationPlugin in plugin order ensures they reinforce rather than race. The janitor's session pruning is effectively a no-op when MigrationPlugin has already pruned — this is by design.
- **Cron log rotation:** The janitor log at `.adk/janitor.log` should itself be managed. The cron installer should add a logrotate config or the janitor script should truncate its own log when it exceeds 1 MB (simple: check size on startup, truncate if over).
- **No AR-CRIT-001 concerns:** Both the standalone script and the plugin's `after_run_callback` operate outside the active ADK event loop. State mutation rules don't apply.
- **`__init__.py`:** Create `rlm_adk/scripts/__init__.py` so the module structure is clean.
- **Exclude known non-data paths from size reporting:** If adding a `--report` mode that shows disk usage, exclude `chrome-dev-profile/` and other non-telemetry directories from the breakdown to avoid confusion.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/agent.py` | `_package_dir()` | L98 | Resolves `.adk/` base directory — janitor must NOT naively copy this |
| `rlm_adk/agent.py` | `_DEFAULT_DB_PATH` | L116 | Default session DB: `.adk/session.db` |
| `rlm_adk/agent.py` | `_DEFAULT_ARTIFACT_ROOT` | L117 | Default artifact root: `.adk/artifacts` |
| `rlm_adk/agent.py` | `SqliteTracingPlugin` wiring | L426 | Traces DB: `.adk/traces.db` |
| `rlm_adk/agent.py` | `ContextWindowSnapshotPlugin` wiring | L453-457 | JSONL output paths |
| `rlm_adk/plugins/sqlite_tracing.py` | `_SCHEMA_SQL` | L209 | 4-table schema — **NO foreign keys** |
| `rlm_adk/plugins/sqlite_tracing.py` | `traces.start_time` | L215 | REAL (epoch) — sort key for age-based pruning |
| `rlm_adk/plugins/sqlite_tracing.py` | `traces.status` | L217 | `'running'` filter for safe deletes |
| `rlm_adk/plugins/sqlite_tracing.py` | `self._conn` | L368 | Long-lived connection — VACUUM invalidates it |
| `rlm_adk/plugins/sqlite_tracing.py` | `_migrate_schema()` | L392 | Schema evolution — janitor must introspect, not hardcode |
| `rlm_adk/plugins/sqlite_tracing.py` | Index definitions | L313-321 | `idx_traces_start` on `traces(start_time)` |
| `rlm_adk/plugins/migration.py` | `MigrationPlugin.__init__` | L54 | `retention_count` param (default 50) |
| `rlm_adk/plugins/migration.py` | `_prune_local_sessions()` | L348 | Existing session pruner — janitor must coordinate |
| `rlm_adk/plugins/migration.py` | `PRAGMA foreign_keys = ON` | L362 | Required for `session.db` cascade deletes |
| `rlm_adk/plugins/context_snapshot.py` | `ContextWindowSnapshotPlugin` | L47 | Writes unbounded JSONL files |
| `rlm_adk/services.py` | `_rlm_session_factory` | L22 | CLI session service registration |
| `rlm_adk/services.py` | `_rlm_artifact_factory` | L41 | CLI artifact service registration |
| `rlm_adk/artifacts.py` | `save_repl_code` | L162 | Writes `repl_code_d{D}_f{F}_iter_{N}_turn_{M}.py` artifacts |
| `rlm_adk/artifacts.py` | `save_final_answer` | L332 | Writes `final_answer_d{D}_f{F}.md` artifacts |
| `rlm_adk_docs/artifacts_and_session.md` | Disk layout | L102-112 | Artifact versioning directory structure |
| `ai_docs/adk_sqlite_session_service_docs.md` | Session schema | L104-105 | FK with `ON DELETE CASCADE` on events table |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow Observability and Artifacts & Session branches)
3. `rlm_adk_docs/artifacts_and_session.md` — artifact versioning layout, session service details
4. `rlm_adk_docs/observability.md` — traces.db schema context and plugin architecture
5. `rlm_adk/plugins/migration.py` — existing session pruning logic to coordinate with
6. `ai_docs/adk_sqlite_session_service_docs.md` — session.db schema and FK behavior
