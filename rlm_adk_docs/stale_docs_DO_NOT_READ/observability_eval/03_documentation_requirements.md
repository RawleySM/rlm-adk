# Multi-Session Documentation & Observability Requirements

Perspective: **Multi-Session Historian** -- what observability data is needed to track, compare, and document agent activity across sessions and runs.

---

## 1. Session-Level Summaries

### 1.1 Run Identity Envelope

| Data Point | Description | Why It Matters | Storage Pattern |
|---|---|---|---|
| `trace_id` | Unique ID for this invocation | Primary key for all cross-session joins | `traces.trace_id` (already exists) |
| `request_id` | User-facing correlation ID | Links logs, events, and external systems to a single run | `traces.request_id` (already exists) |
| `session_id` | ADK session container | Groups multiple invocations within a single user session | `traces.session_id` (already exists) |
| `run_ordinal` | Monotonic counter within a session | Distinguishes retry vs. fresh run within one session | **Gap**: not tracked; derive from `ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY start_time)` or add explicit column |

### 1.2 Top-Level Run Metrics

| Data Point | Current Source | Cross-Session Value |
|---|---|---|
| Total wall-clock duration | `traces.total_execution_time_s` | Latency regression detection |
| Total input tokens | `traces.total_input_tokens` | Cost tracking and context-growth detection |
| Total output tokens | `traces.total_output_tokens` | Verbosity drift |
| Total LLM calls (reasoning + worker) | `traces.total_calls` | Efficiency regression |
| Reasoning iterations | `traces.iterations` | Convergence speed |
| Max depth reached | **Gap** | Recursive dispatch depth utilization vs. configured `app:max_depth` |
| Final answer length (chars) | `traces.final_answer_length` | Quality proxy: sudden drops signal regressions |
| Finish status | `traces.status` | Success/failure rate over time |
| Child dispatch count | `traces.child_dispatch_count` | Worker utilization trends |
| Total batch dispatches | **Gap** (obs key exists, not in traces enrichment) | Batching effectiveness |
| Artifact count and bytes | `traces.artifact_saves`, `traces.artifact_bytes_saved` | Output volume trends |

### 1.3 Error Summary

| Data Point | Current Source | Cross-Session Value |
|---|---|---|
| Finish reason counters (safety, recitation, max_tokens) | `traces.finish_safety_count`, etc. | Safety/truncation regression alerts |
| Child error counts by category | `traces.child_error_counts` (JSON) | Worker reliability trends |
| Structured output failures | `traces.structured_output_failures` | Schema adherence over time |
| Policy violations | **Gap**: `policy_violation` key exists but not captured in traces | Guardrail trigger frequency |

---

## 2. Run Comparison (A/B Analysis)

For meaningful A/B comparison (same prompt, different config), you need a **comparison key** that groups runs that should be compared, plus the **independent variables** that differ between them.

### 2.1 Required Comparison Dimensions

| Dimension | Current State | Recommendation |
|---|---|---|
| Prompt fingerprint | `traces.root_prompt_preview` (500 char truncation) | Add `root_prompt_hash` (SHA-256 of full prompt) for exact grouping. The preview is useful for human readability but not reliable for grouping. |
| Model version | `traces.model_usage_summary` (JSON) | Add `primary_model` column (the reasoning model) for fast filtering. Worker models may differ. |
| `app:max_depth` | Not persisted per-trace | **Gap**: Add `config_max_depth` column to traces |
| `app:max_iterations` | Not persisted per-trace | **Gap**: Add `config_max_iterations` column to traces |
| Worker concurrency / pool size | Not persisted | **Gap**: Add `config_worker_pool_size` |
| Target repo | `traces.repo_url` | Already available for repo-specific comparisons |

### 2.2 Comparison Query Pattern

```sql
-- A/B: same prompt, different models
SELECT primary_model,
       AVG(total_execution_time_s) AS avg_time,
       AVG(total_input_tokens + total_output_tokens) AS avg_tokens,
       AVG(final_answer_length) AS avg_answer_len,
       COUNT(*) AS runs
FROM traces
WHERE root_prompt_hash = ?
GROUP BY primary_model;
```

### 2.3 Missing: Per-Iteration Comparison

The `per_iteration_breakdown` JSON blob captures token usage per reasoning turn. For A/B analysis, this needs to be queryable:
- **Option A**: Keep JSON, parse in application layer (current approach).
- **Option B**: Normalize into a `trace_iterations` table with `(trace_id, iteration, input_tokens, output_tokens, finish_reason, agent_type)`. This enables SQL-native comparison of convergence curves across runs.

Recommendation: Option B for any serious cross-run analysis tooling.

---

## 3. Regression Detection

### 3.1 Key Regression Signals

| Signal | Metric | Alert Condition | Current Coverage |
|---|---|---|---|
| Answer quality degradation | `final_answer_length` | Drops >50% vs. 7-day rolling mean for same prompt hash | Partially: length exists, no prompt hash for grouping |
| Token cost inflation | `total_input_tokens + total_output_tokens` | >2x vs. baseline for same prompt hash | Partially: tokens exist, no baseline infrastructure |
| Convergence slowdown | `iterations` | >1.5x vs. baseline | Partially: iteration count exists |
| Error rate spike | `child_error_counts` | Any error category >0 where baseline was 0 | Available via JSON parsing |
| Safety filter triggers | `finish_safety_count` | Any non-zero where baseline was 0 | Available |
| Timeout rate | Worker timeouts in `child_error_counts` | Increase from baseline | Available via JSON parsing |
| Structured output failure rate | `structured_output_failures / child_dispatch_count` | >10% failure rate | Both fields available |

### 3.2 Missing: Baseline Infrastructure

No mechanism currently exists to:
1. Define a "baseline" run or set of runs for a given prompt/config combination
2. Automatically compare new runs against that baseline
3. Emit alerts or annotations when regression thresholds are crossed

**Recommendation**: Add a `baselines` table:
```sql
CREATE TABLE baselines (
    baseline_id     TEXT PRIMARY KEY,
    prompt_hash     TEXT NOT NULL,
    primary_model   TEXT,
    config_hash     TEXT,
    created_at      REAL,
    avg_tokens      INTEGER,
    avg_time_s      REAL,
    avg_iterations  INTEGER,
    avg_answer_len  INTEGER,
    sample_count    INTEGER
);
```

---

## 4. Trace Lineage (Dispatch Tree Reconstruction)

### 4.1 Current State

The RLM-ADK architecture supports recursive dispatch: the reasoning agent calls `execute_code`, which may invoke `llm_query` / `llm_query_batched`, dispatching workers. At depth > 0, a child orchestrator can itself dispatch further workers.

**What exists**:
- `depth_key(key, depth)` suffixes state keys with `@dN` for depth isolation
- `child_obs_key(depth, fanout_idx)` produces `obs:child_summary@dNfM` keys
- `session_state_events` table parses `@dN` and `@dNfM` suffixes into `key_depth` and `key_fanout` columns
- `telemetry` table has a `depth` column (default 0)

**What is missing**:
- **Parent trace linkage**: No `parent_trace_id` or `parent_request_id` column in `traces`. A depth-1 child run cannot be linked back to its depth-0 parent trace.
- **Dispatch tree table**: No dedicated table that records `(parent_trace_id, child_trace_id, depth, fanout_idx, prompt_preview, result_preview)`.
- **Fanout position**: The `telemetry` table does not record which fanout index a worker call belongs to within a batch.

### 4.2 Recommendation: `dispatch_tree` Table

```sql
CREATE TABLE dispatch_tree (
    edge_id           TEXT PRIMARY KEY,
    parent_trace_id   TEXT NOT NULL,
    child_trace_id    TEXT,          -- NULL if worker (no sub-trace)
    depth             INTEGER NOT NULL,
    fanout_idx        INTEGER,       -- position within batch
    dispatch_type     TEXT NOT NULL,  -- 'single' | 'batch'
    prompt_hash       TEXT,
    prompt_preview    TEXT,
    result_preview    TEXT,
    latency_ms        REAL,
    status            TEXT,          -- 'ok' | 'error' | 'timeout'
    error_category    TEXT
);
```

This enables full tree reconstruction:
```sql
-- Reconstruct full dispatch tree for a root trace
WITH RECURSIVE tree AS (
    SELECT * FROM dispatch_tree WHERE parent_trace_id = ?
    UNION ALL
    SELECT d.* FROM dispatch_tree d
    JOIN tree t ON d.parent_trace_id = t.child_trace_id
)
SELECT * FROM tree ORDER BY depth, fanout_idx;
```

---

## 5. Historical Trends

### 5.1 Time-Series Metrics

| Metric | Aggregation | Query Support |
|---|---|---|
| Token cost per day | `SUM(total_input_tokens + total_output_tokens)` grouped by `DATE(start_time, 'unixepoch')` | Supported: `traces.start_time` is indexed |
| Average iterations per run | `AVG(iterations)` over sliding window | Supported |
| Error rate per day | `COUNT(CASE WHEN status != 'completed') / COUNT(*)` | Supported |
| P50/P95 latency | `total_execution_time_s` percentiles | Supported via SQLite `NTILE` or application-layer |
| Worker dispatch efficiency | `child_dispatch_count / iterations` | Both fields available |

### 5.2 Missing: Cost Estimation

Token counts exist but there is no price-per-token metadata to convert to dollar cost. Options:
- Add a `model_pricing` reference table with `(model_name, input_price_per_1k, output_price_per_1k, effective_date)`
- Compute cost in the query layer: `(input_tokens * input_price + output_tokens * output_price) / 1000`

### 5.3 Missing: Trend Annotations

No mechanism to annotate time-series data with code changes, config changes, or model version upgrades. A simple `annotations` table would support this:
```sql
CREATE TABLE annotations (
    annotation_id TEXT PRIMARY KEY,
    timestamp     REAL NOT NULL,
    category      TEXT,  -- 'code_change' | 'config_change' | 'model_upgrade'
    description   TEXT,
    git_commit    TEXT
);
```

---

## 6. Reproducibility

### 6.1 Data Needed to Replay a Run

| Data Point | Current State | Gap |
|---|---|---|
| Full prompt text | `root_prompt_preview` (truncated to 500 chars) | **Critical gap**: Full prompt must be stored for replay. Add `root_prompt_full` as TEXT or store as artifact. |
| Model name + version | `model_usage_summary` JSON | Partially available; exact model version string (e.g., `gemini-3-pro-preview-20260301`) should be a first-class column |
| System instruction | Not stored | **Gap**: The reasoning agent's system instruction is assembled at runtime. Store it (or its hash) for reproducibility. |
| `app:max_depth` | Not stored per-trace | **Gap**: Store as trace column |
| `app:max_iterations` | Not stored per-trace | **Gap**: Store as trace column |
| Worker pool size | Not stored | **Gap**: Store as trace column |
| Worker timeout | Not stored | **Gap**: `RLM_WORKER_TIMEOUT` env var value |
| HTTP retry config | Not stored | **Gap**: `attempts`, `initial_delay`, `max_delay` |
| Temperature / generation config | Not stored | **Gap**: If non-default generation config is used, store it |
| Random seeds | Not applicable (no explicit randomness beyond LLM sampling) | N/A |
| REPL namespace state | Not stored beyond `LAST_REPL_RESULT` | **Gap**: For full replay, the REPL's initial namespace (helper functions, imports) should be captured |
| LLM response sequence | `telemetry` table captures per-call tokens/timing | For deterministic replay, would need full response text; this is expensive and likely only needed for debugging specific runs |

### 6.2 Recommendation: Replay Manifest

At run start, serialize a `replay_manifest` JSON artifact:
```json
{
  "trace_id": "abc123",
  "root_prompt": "full prompt text...",
  "system_instruction_hash": "sha256:...",
  "model": "gemini-3-pro-preview",
  "max_depth": 3,
  "max_iterations": 10,
  "worker_pool_size": 5,
  "worker_timeout_s": 180,
  "http_retry": {"attempts": 3, "initial_delay": 1.0, "max_delay": 60.0},
  "generation_config": {},
  "git_commit": "abc1234",
  "timestamp": 1709712000.0
}
```

Store as an ADK artifact keyed by `trace_id`. This makes any run reproducible (modulo LLM non-determinism).

---

## 7. Artifact Versioning

### 7.1 Current State

- ADK artifact system tracks `(filename, version)` pairs via `artifact_delta` in events
- `ObservabilityPlugin` counts artifact saves and bytes
- `SqliteTracingPlugin` records artifact events in `session_state_events`
- No content storage in SQLite (artifacts are in ADK's artifact store)

### 7.2 Cross-Run Artifact Comparison

| Requirement | Current Support | Gap |
|---|---|---|
| List all artifacts produced by a run | `session_state_events` WHERE `key_category = 'obs_artifact'` | Supported |
| Diff artifacts across runs | Not supported | **Gap**: Need artifact content hash per version. Add `artifact_content_hash` to SSE or a dedicated `artifact_versions` table |
| Track which code block produced an artifact | Not directly linked | **Gap**: Need `telemetry_id` or `iteration` correlation with artifact events |
| Artifact size trends | `traces.artifact_bytes_saved` | Supported for totals; per-artifact sizes not broken out |

### 7.3 Recommendation: `artifact_versions` Table

```sql
CREATE TABLE artifact_versions (
    version_id      TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    filename        TEXT NOT NULL,
    version         INTEGER NOT NULL,
    content_hash    TEXT,       -- SHA-256 of content
    size_bytes      INTEGER,
    mime_type       TEXT,
    iteration       INTEGER,   -- which reasoning iteration produced it
    created_at      REAL
);
```

Cross-run diff query:
```sql
-- Find artifacts that changed between two runs of the same prompt
SELECT a.filename, a.content_hash AS hash_a, b.content_hash AS hash_b
FROM artifact_versions a
JOIN artifact_versions b ON a.filename = b.filename
WHERE a.trace_id = ? AND b.trace_id = ?
  AND a.content_hash != b.content_hash;
```

---

## 8. Configuration Tracking

### 8.1 Current Gaps

The traces table captures runtime *results* but not the *configuration inputs* that produced them. This makes it impossible to answer: "What changed between a fast run and a slow run?"

### 8.2 Required Configuration Fields

| Config | Source | Storage Recommendation |
|---|---|---|
| `app:max_depth` | App-scoped state key | `traces.config_max_depth` INTEGER |
| `app:max_iterations` | App-scoped state key | `traces.config_max_iterations` INTEGER |
| Worker pool size | `WorkerPool.__init__` param | `traces.config_pool_size` INTEGER |
| Worker timeout | `RLM_WORKER_TIMEOUT` env var | `traces.config_worker_timeout_s` INTEGER |
| HTTP retry attempts | `HttpRetryOptions.attempts` | `traces.config_http_retries` INTEGER |
| Reasoning model | Agent factory param | `traces.config_reasoning_model` TEXT |
| Worker model | Dispatch config | `traces.config_worker_model` TEXT |
| Structured output max retries | Dispatch config | `traces.config_schema_retries` INTEGER |
| REPL max calls | `REPLTool.max_calls` | `traces.config_repl_max_calls` INTEGER |
| REPL trace level | `RLM_REPL_TRACE` env var | `traces.config_repl_trace_level` INTEGER |
| Git commit hash | `git rev-parse HEAD` at startup | `traces.git_commit` TEXT |

### 8.3 Configuration Fingerprint

For fast A/B grouping, compute a `config_hash` from all config fields:
```python
config_hash = hashlib.sha256(json.dumps(sorted_config_dict).encode()).hexdigest()[:16]
```

Add as `traces.config_hash` to enable:
```sql
-- All runs with identical configuration
SELECT * FROM traces WHERE config_hash = ?;

-- Compare two configurations
SELECT config_hash, AVG(total_execution_time_s), AVG(total_input_tokens)
FROM traces
WHERE root_prompt_hash = ?
GROUP BY config_hash;
```

---

## Summary of Gaps

| Priority | Gap | Impact |
|---|---|---|
| **P0** | Full prompt text not stored (only 500-char preview) | Blocks reproducibility and prompt-level A/B grouping |
| **P0** | Configuration inputs not persisted per-trace | Blocks meaningful A/B comparison and regression root-cause analysis |
| **P1** | No parent-child trace linkage for recursive dispatch | Cannot reconstruct dispatch trees across depth levels |
| **P1** | No prompt hash for run grouping | Cannot reliably group runs by prompt for comparison |
| **P1** | No normalized iteration table | Per-iteration token analysis requires JSON parsing |
| **P2** | No baseline infrastructure | Regression detection is manual |
| **P2** | No artifact content hashing | Cannot diff code artifacts across runs |
| **P2** | No cost estimation metadata | Token counts exist but dollar cost requires external lookup |
| **P3** | No trend annotations | Cannot correlate metric changes with code/config changes |
| **P3** | System instruction not stored | Partial reproducibility gap |
