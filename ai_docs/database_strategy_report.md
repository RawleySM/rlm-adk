# Database Strategy Report: SQLite vs PostgreSQL for rlm-adk

> **Date**: 2026-02-20
> **Agents**: LangFuse-Expert, ADK-Expert, Migration-Expert
> **Scope**: Session service, telemetry, and hybrid database architectures
> **Critical Context**: Traces serve **agent observability** (evaluation agents programmatically parsing traces), NOT human dashboards. Session rewind is an evaluation/tuning feature for trajectory correction.

---

## Executive Summary

Three research agents investigated database strategy across the Langfuse telemetry stack, Google ADK session service, and hybrid SQLite-to-PostgreSQL migration architectures. The consolidated findings are:

1. **Replacing Postgres with SQLite inside Langfuse is not feasible** (1/5 rating). Langfuse has 381 Postgres-specific Prisma migrations, 232+ raw SQL statements using Postgres syntax, and trace data lives in ClickHouse -- not Postgres. Swapping Postgres yields negligible simplification.

2. **ADK natively supports SQLite for sessions**. Four backends exist: InMemory, `SqliteSessionService` (aiosqlite), `DatabaseSessionService` (SQLAlchemy, supports Postgres/MySQL/SQLite), and VertexAI. Session rewind is fully functional on SQLite.

3. **The recommended architecture is a hybrid**: SQLite as the embedded runtime database for sessions + local traces, with end-of-session migration to Postgres for long-term storage, and a DuckDB analytics overlay for evaluation agents.

4. **Langfuse can be bypassed for the evaluation loop** by either querying ClickHouse directly (self-hosted advantage) or building a lightweight local trace store. Langfuse remains valuable for prompt management, datasets, and human-facing dashboards when needed.

---

## Part 1: Langfuse + SQLite Feasibility (LangFuse-Expert)

### Verdict: NOT FEASIBLE (1/5)

### What Lives Where in Langfuse

| Component | Database | Can Be Swapped? |
|---|---|---|
| Auth, tenancy, prompts, datasets, eval config | **PostgreSQL** | No -- 381 migrations, 232+ raw SQL, 13 array columns |
| Traces, observations, scores (ALL trace data) | **ClickHouse** | No -- mandatory, cannot self-host without it |
| Job queues, API key cache, rate limiting | **Redis** | No -- BullMQ hard dependency |
| Raw events, multi-modal attachments | **MinIO** | No -- durability layer |

### Hard Blockers for SQLite Substitution

- **381 Prisma migrations** are PostgreSQL-specific DDL
- **232 raw SQL statements** across 43 files use `ILIKE`, `::type` casts, `ARRAY[]` literals, `@>` containment
- **13 `String[]` columns** (tags, featureFlags, labels, etc.) have no SQLite equivalent
- **8 Hash indexes + 2 GIN indexes** have no SQLite equivalent
- **25 native enums** cast via `::"ObservationType"` syntax
- Even if Postgres were swapped, **ClickHouse + Redis + MinIO remain mandatory** -- dropping from 6 to 5 Docker services

### The Critical Insight

**Trace data never touches PostgreSQL.** All traces, observations, and scores live in ClickHouse. The evaluation agents need trace data, which means swapping Postgres gains them nothing. The correct optimization target is the ClickHouse query path, not the Postgres path.

### Langfuse Programmatic Access for Evaluation Agents

Langfuse provides full programmatic access without the UI:

| Method | Latency | Best For |
|---|---|---|
| Python SDK v3 (`langfuse.api.trace.list()`) | 10-100ms | Filtered trace retrieval with pagination |
| REST API (cursor-based pagination v2) | 10-100ms | Language-agnostic access |
| Direct ClickHouse query (`localhost:8123`) | Sub-10ms | Bulk analytics, aggregations, custom SQL |
| `langfuse.create_score()` | ~10ms | Writing evaluation results back |

**Recommendation**: For the evaluation loop hot path, query ClickHouse directly. For evaluation infrastructure (datasets, scoring configs), use the Langfuse SDK.

### Alternative: Arize Phoenix

Phoenix supports **SQLite as its default storage** and runs as a single Docker container with no ClickHouse/Redis/MinIO dependencies. It's compatible with OpenInference (same instrumentation rlm-adk already uses). Trade-off: less mature prompt management and evaluation features than Langfuse.

---

## Part 2: ADK Session Service Architecture (ADK-Expert)

### Session Service Backends (ADK v1.25.0)

| Backend | Persistence | Concurrency | JSON Querying | Overhead |
|---|---|---|---|---|
| `InMemorySessionService` | None | Single process | N/A (Python dicts) | Minimal |
| `SqliteSessionService` | File-based | 1 writer, N readers | TEXT (json_extract) | Low |
| `DatabaseSessionService` (SQLite) | File-based | 1 writer + asyncio.Lock | TEXT (JSON serialized) | Medium |
| `DatabaseSessionService` (Postgres) | Server-based | Row-level locking | Native JSONB | Medium |
| `VertexAiSessionService` | Cloud | Managed | N/A | API calls |

### Session Data Model

```
Session
  ├── id, app_name, user_id
  ├── state: dict[str, Any]        # Accumulated from event deltas
  ├── events: list[Event]           # Chronological event history
  └── last_update_time: float

Event (extends LlmResponse)
  ├── invocation_id                 # Groups events within one user turn
  ├── author                        # 'user' or agent name
  ├── content                       # Full model response (Parts)
  ├── usage_metadata                # Token counts
  ├── actions: EventActions
  │     ├── state_delta             # State changes this event
  │     ├── artifact_delta          # Artifact version changes
  │     ├── transfer_to_agent       # Agent transfer directive
  │     └── rewind_before_invocation_id  # Rewind target
  └── timestamp
```

### Session Rewind for Evaluation Agents

**How it works**: `Runner.rewind_async()` is an append-only operation:
1. Finds the target `invocation_id`
2. Replays state deltas to compute reverse delta
3. Restores artifact versions
4. Appends a new REWIND event (original events remain in storage)

**Key properties for evaluation**:
- **Granularity**: Invocation-level (entire user turn), not individual events
- **Append-only**: All events (including rewound ones) remain queryable -- evaluation agents see the full trajectory history
- **State scoping**: Only session-scoped state is restored (not `app:` or `user:` prefixed state)
- **No native forking**: Rewind modifies the existing session. Fork requires manual event copying to a new session.

**Evaluation agent rewind pattern**:
1. Load session, scan events for divergence point
2. Create a NEW session, copy events up to divergence (preserves original)
3. Run agent on new session with modified parameters
4. Compare trajectories across both sessions

### Current rlm-adk Gap

`create_rlm_runner()` at `rlm_adk/agent.py:339` returns `InMemoryRunner` with hardcoded `InMemorySessionService`. This needs modification to accept a custom session service parameter.

### Recommendation for Evaluation Use Case

| Use Case | Recommended Backend |
|---|---|
| Local development, single eval agent | `SqliteSessionService` |
| Concurrent eval agents, production | `DatabaseSessionService` (PostgreSQL) |
| Cloud deployment | `VertexAiSessionService` |
| Quick prototyping | `InMemorySessionService` (current) |

---

## Part 3: Hybrid Architecture Strategies (Migration-Expert)

### Current State

- **Session service**: `InMemoryRunner` (volatile), BUT `.adk/session.db` already exists with 7 sessions, 159 events (~1.2 MB) from ADK CLI usage
- **Telemetry**: Langfuse Docker Compose stack (Postgres + ClickHouse + Redis + MinIO, ~2-4 GB RAM)
- **Artifacts**: `InMemoryArtifactService` (volatile)

### Strategy A: Runtime SQLite with Threshold-Based Migration

```
Agent Execution                     Migration Trigger
     │                                    │
     v                                    v
[SQLite WAL]  ── writes ──>  [sessions + traces tables]
     │                                    │
     │ (concurrent reads)        (row count > N or size > M)
     v                                    │
[Eval Agent]                              v
                                   [migration script]
                                          │
                                          v
                                    [PostgreSQL]
```

**Pros**: Continuous migration, Postgres always near-current
**Cons**: Complex concurrent migration logic, write-lock contention during migration

### Strategy B: End-of-Session Migration (RECOMMENDED)

```
Agent Session Start                     Agent Session End
       │                                       │
       v                                       v
[SQLite WAL] <── writes                  [Migration Script]
       │                                       │
       │ (reads during session)                v
       v                                 [PostgreSQL]
[Eval Agent]                                   │
       │                                       v
       v                              [Historical Queries]
[Local optimization loop]
```

**Pros**: No concurrent migration, simpler error handling, SQLite as durable cache
**Cons**: Delayed Postgres availability (acceptable for eval use case)

**Migration triggers**:
- `after_run_callback` in a plugin (primary -- ADK already supports this pattern)
- `atexit` handler (fallback for graceful shutdown)
- Signal handlers for container shutdown
- Startup scan for unmigrated sessions (crash recovery)

**Capacity management**:
- FIFO pruning of oldest migrated sessions
- Configurable retention (e.g., `RLM_LOCAL_RETENTION_SESSIONS=50`)
- `VACUUM` after bulk deletes

### Strategy C: Direct PostgreSQL (Current Approach)

| Dimension | Assessment |
|---|---|
| Resource overhead | 2-4 GB RAM for Docker Compose stack |
| Startup latency | 15-30 seconds |
| Eval agent latency | 10-100ms (HTTP API) vs sub-ms (local SQLite) |
| Offline development | Requires Docker running |

### Comparison Matrix

| Dimension | Strategy A (Threshold) | Strategy B (End-of-Session) | Strategy C (Direct Postgres) |
|---|---|---|---|
| **Eval agent latency** | Sub-millisecond | Sub-millisecond | 10-100ms |
| **Implementation complexity** | High | Medium | Low (existing) |
| **Infrastructure during dev** | SQLite only | SQLite only | Full Docker stack |
| **Memory footprint** | ~10-50 MB | ~10-50 MB | 2-4 GB |
| **Startup time** | Instant | Instant | 15-30 seconds |
| **Crash recovery** | Partial risk | Clean (SQLite is durable) | Clean |
| **Concurrent eval agents** | WAL mode (1 writer) | WAL mode (1 writer) | Full MVCC |
| **Offline capable** | Yes | Yes | No |

### DuckDB Analytics Layer

For evaluation agents running analytical queries (aggregations, comparisons, window functions), DuckDB provides 10-100x speedup over SQLite for analytical workloads:

- **Columnar storage**: Scans only needed columns
- **Vectorized execution**: Optimized for aggregation queries
- **Native SQLite reading**: `ATTACH 'traces.db' AS traces (TYPE sqlite)` -- zero-copy access
- **Embedded**: No server process, same deployment model as SQLite

Pattern: SQLite handles the **write path** (OLTP inserts from running agent), DuckDB handles the **read path** (OLAP analytics from evaluation agents).

### Alternative Technologies Worth Monitoring

| Technology | Relevance | Maturity |
|---|---|---|
| **DuckDB** | Analytics overlay for SQLite trace data | Production-ready |
| **Arize Phoenix** | Langfuse alternative with native SQLite support | Maturing |
| **libSQL / Turso** | SQLite fork with embedded replicas + sync | Early (Python SDK immature) |
| **LanceDB** | Vector + structured data for semantic trace search | Future consideration |
| **sqlite-otel** | OTel collector that writes to SQLite | Viable but adds Go binary |

---

## Consolidated Recommendations

### Immediate (Phase 1-2): Session Persistence + Local Traces

1. **Modify `create_rlm_runner()`** to accept a `session_service` parameter
2. **Default to `SqliteSessionService`** (`db_path=".adk/session.db"`) instead of `InMemorySessionService`
3. **Switch artifact service** to `FileArtifactService` (`.adk/artifacts/`) for rewind support
4. **Create `SqliteTracingPlugin`** that captures span-like data from ADK callbacks to a local `traces.db`
5. **Keep `LangfuseTracingPlugin` as optional** -- both can run simultaneously

### Medium-term (Phase 3): Evaluation Agent Interface

6. **Build `TraceReader` class** wrapping DuckDB reads against SQLite trace data
7. **Expose evaluation queries**: `get_session_traces()`, `get_divergence_points()`, `compare_sessions()`
8. **Integrate with session rewind**: Load session at divergence point, fork to new session, re-execute

### Long-term (Phase 4-5): Migration Pipeline

9. **Create `MigrationPlugin`** with `after_run_callback` hook for end-of-session batch migration to Postgres
10. **Implement capacity management**: FIFO pruning, configurable retention, startup unmigrated-session scan
11. **Consider direct ClickHouse queries** for historical analysis across the full trace corpus

### What NOT to Do

- Do NOT attempt to replace Postgres inside Langfuse with SQLite
- Do NOT remove ClickHouse from the Langfuse stack
- Do NOT use `InMemorySessionService` for anything beyond quick prototyping
- Do NOT enable WAL mode without `PRAGMA busy_timeout` (risk of SQLITE_BUSY errors)

### Optimal SQLite Configuration

```sql
PRAGMA journal_mode = WAL;          -- concurrent readers + single writer
PRAGMA synchronous = NORMAL;         -- balance durability vs speed
PRAGMA busy_timeout = 5000;          -- 5s wait on lock contention
PRAGMA cache_size = -64000;          -- 64MB page cache
PRAGMA temp_store = MEMORY;          -- temp tables in RAM
PRAGMA mmap_size = 268435456;        -- 256MB memory-mapped I/O
PRAGMA wal_autocheckpoint = 1000;    -- checkpoint every 1000 pages
```

### Dependencies to Add

```toml
# pyproject.toml additions
"aiosqlite>=0.20.0",           # SQLite async driver (for SqliteSessionService)
"duckdb>=1.0.0",               # Analytics engine for evaluation agents
# Optional, for Postgres long-term storage:
"sqlalchemy[asyncio]>=2.0",    # ORM for DatabaseSessionService
"asyncpg>=0.29.0",             # Postgres async driver
```

---

## Sources

### Langfuse
- [Langfuse Database Architecture](https://langfuse.com/handbook/product-engineering/architecture)
- [Langfuse Infrastructure Evolution (v3)](https://langfuse.com/blog/2024-12-langfuse-v3-infrastructure-evolution)
- [ClickHouse Self-Hosted](https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse)
- [Query Data via SDKs](https://langfuse.com/docs/api-and-data-platform/features/query-via-sdk)
- [External Evaluation Pipelines Cookbook](https://langfuse.com/guides/cookbook/example_external_evaluation_pipelines)
- [GitHub Discussion #976 - Alternative DB Support](https://github.com/orgs/langfuse/discussions/976)
- [Database Overview - DeepWiki](https://deepwiki.com/langfuse/langfuse/3.1-database-overview)

### Google ADK
- [ADK Session Management](https://google.github.io/adk-docs/sessions/session/)
- [ADK Session Rewind](https://google.github.io/adk-docs/sessions/session/rewind/)
- [ADK State Management](https://google.github.io/adk-docs/sessions/state/)
- [ADK Python Repository](https://github.com/google/adk-python)
- [DatabaseSessionService Postgres Issue #4366](https://github.com/google/adk-python/issues/4366)

### Database Technologies
- [SQLite WAL Mode](https://sqlite.org/wal.html)
- [DuckDB vs SQLite Comparison](https://motherduck.com/learn-more/duckdb-vs-sqlite-databases/)
- [pgloader SQLite to Postgres](https://pgloader.readthedocs.io/en/latest/ref/sqlite.html)
- [libSQL / Turso Embedded Replicas](https://turso.tech/blog/local-first-cloud-connected-sqlite-with-turso-embedded-replicas)
- [Arize Phoenix Docker Deployment](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [SQLite Performance Tuning](https://phiresky.github.io/blog/2020/sqlite-performance-tuning/)
