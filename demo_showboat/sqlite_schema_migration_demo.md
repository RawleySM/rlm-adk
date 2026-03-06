# SQLite Schema Migration & Telemetry Wiring

Implements forward-compatible schema migration for `SqliteTracingPlugin` and wires
three new trace-level columns (`config_json`, `prompt_hash`, `max_depth_reached`)
plus four new telemetry-level columns (`agent_type`, `prompt_chars`, `system_chars`,
`call_number`).

## What was implemented

1. **`_migrate_schema()`** -- inspects existing tables via `PRAGMA table_info` and
   runs `ALTER TABLE ... ADD COLUMN` for any columns present in the canonical schema
   but missing from the on-disk DB. This lets old databases upgrade in-place without
   data loss.

2. **`config_json`** (traces) -- JSON blob capturing `app:max_depth`,
   `app:max_iterations` from session state plus `RLM_MAX_DEPTH`,
   `RLM_MAX_CONCURRENT_CHILDREN`, `RLM_WORKER_TIMEOUT`, `RLM_ADK_MODEL` from
   environment. Written at trace start in `before_run_callback`.

3. **`prompt_hash`** (traces) -- SHA-256 hex digest of `root_prompt` from session
   state. Written at trace end in `after_run_callback`. Enables cross-run dedup
   and prompt-level analytics.

4. **`max_depth_reached`** (traces) -- Computed at trace end by scanning telemetry
   `agent_name` values for `_d(\d+)` patterns. Tracks the deepest child-dispatch
   layer that actually executed.

5. **Telemetry column wiring** -- `before_model_callback` now reads
   `CONTEXT_WINDOW_SNAPSHOT` from callback state to populate `agent_type`,
   `prompt_chars`, `system_chars`, and reads `OBS_TOTAL_CALLS` for `call_number`.

---

## Demo: Schema migration adds missing columns

Run against an old-schema DB to prove migration adds the new columns:

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_plugins_sqlite_tracing.py -v \
  -k "test_migrate_adds_enriched_columns_to_old_schema or test_migrate_adds_missing_telemetry_columns or test_migrate_adds_config_prompt_depth_columns"
```

Expected: 3 passed. These tests create a DB with the minimal original schema (only
base columns), instantiate the plugin (which triggers `_migrate_schema`), then verify
via `PRAGMA table_info` that all enriched columns are present.

---

## Demo: config_json persistence

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_plugins_sqlite_tracing.py -v \
  -k "TestConfigPersistence"
```

Expected: 4 passed. Covers:
- Column exists in fresh schema
- `app:max_depth` / `app:max_iterations` from state are stored
- `RLM_MAX_DEPTH` etc. env vars are captured with `env_` prefix
- Empty config produces valid JSON `{}`

---

## Demo: prompt_hash is SHA-256

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_plugins_sqlite_tracing.py -v \
  -k "TestPromptHash"
```

Expected: 4 passed. Covers:
- Column exists
- Hash matches `hashlib.sha256(root_prompt.encode()).hexdigest()`
- NULL when no `root_prompt` in state
- Deterministic: same prompt produces same hash across runs

Inline verification:

```python
import hashlib
prompt = "Analyze this repository"
h = hashlib.sha256(prompt.encode()).hexdigest()
assert len(h) == 64  # 256 bits = 64 hex chars
assert h == hashlib.sha256(prompt.encode()).hexdigest()  # deterministic
```

---

## Demo: max_depth_reached tracks deepest layer

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_plugins_sqlite_tracing.py -v \
  -k "TestMaxDepthReached"
```

Expected: 4 passed. Covers:
- Column exists
- Agent names `child_reasoning_d1`, `child_reasoning_d2` yield `max_depth_reached=2`
- Only `reasoning_agent` (no `_dN` suffix) yields `max_depth_reached=0`
- No telemetry rows at all yields `max_depth_reached=0`

The depth is extracted via `re.compile(r'_d(\d+)')` scan over `DISTINCT agent_name`
from the telemetry table for the current trace.

---

## Demo: Telemetry columns populated

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_plugins_sqlite_tracing.py -v \
  -k "TestTelemetryColumnPopulation"
```

Expected: 2 passed. Covers:
- `agent_type`, `prompt_chars`, `system_chars` read from `CONTEXT_WINDOW_SNAPSHOT`
  dict in callback state
- `call_number` read from `obs:total_calls` in callback state

---

## Full suite (all 18 new tests)

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_plugins_sqlite_tracing.py -v \
  -k "TestSchemaMigration or TestConfigPersistence or TestPromptHash or TestMaxDepthReached or TestMigrationNewColumns or TestTelemetryColumnPopulation"
```

Expected: 18 passed.

---

## Code quality notes

1. **Double schema execution in `_init_db`** -- `_SCHEMA_SQL` is run once before
   migration (to handle fresh DBs) and again after migration (to create indexes
   on newly-added columns). Both calls are wrapped in bare `except Exception: pass`.
   This is intentional but hides real errors. A targeted `sqlite3.OperationalError`
   catch would be safer.

2. **`max_depth_reached` computation queries the DB** -- The `after_run_callback`
   runs a `SELECT DISTINCT agent_name FROM telemetry WHERE trace_id = ?` query to
   compute depth. This is correct but couples the trace-enrichment logic to the
   telemetry table. If telemetry writes fail silently, `max_depth_reached` will
   read as 0 even when children executed. An in-memory accumulator (like the
   existing `_agent_span_stack`) could track max depth with no DB dependency.

3. **`_pending_model_telemetry` keyed by model string** -- If two concurrent model
   calls use the same model string, the second `before_model_callback` overwrites
   the first pending entry, orphaning the first telemetry row (it will never get
   its `end_time`/`duration_ms` updated). This is pre-existing and not introduced
   by this change, but worth noting for future hardening. Keying by `telemetry_id`
   or using a stack would fix it.

4. **`config_json` always written, even when empty** -- `json.dumps({})` is stored
   rather than NULL. The test `test_config_json_none_when_no_config` asserts this
   is valid JSON, which is fine, but it means you cannot distinguish "no config
   captured" from "config was empty" at the SQL level. Minor -- probably the right
   tradeoff for query simplicity.

5. **No test for `config_json` surviving migration** -- The `TestMigrationNewColumns`
   test checks column existence but does not verify that `before_run_callback`
   successfully writes `config_json` on a migrated (old-schema) DB. The existing
   `test_after_run_succeeds_on_migrated_schema` covers the `after_run` path but
   does not check `config_json` specifically. Low risk since `before_run` uses a
   straightforward INSERT.
