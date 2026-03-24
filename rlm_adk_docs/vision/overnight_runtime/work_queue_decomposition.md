<!-- validated: 2026-03-22 -->

# Work Queue Decomposition

**Status:** Conceptual — no implementation yet

**What it does:** Breaks an overnight task into a managed queue of discrete work units with independent success/failure, enabling partial progress, priority reordering, and selective retry — instead of treating the overnight run as one monolithic atomic operation.

---

## The Monolith Problem

Today, an overnight run is a single `runner.run_async()` invocation. The entire task is one unit: it succeeds or fails as a whole. This is fine for 5-minute attended tasks. For 6-hour overnight analyses, it creates fragility:

- If work unit #47 out of 50 fails, you lose the context of the first 46 successes
- There's no way to prioritize which parts of a large task run first
- There's no way to skip known-problematic subtasks and continue with the rest
- There's no natural granularity for checkpointing, progress reporting, or budget allocation
- The user can't review partial results and steer the remaining work

Work queue decomposition solves this by making "unit of work" a first-class concept.

---

## Architecture

### Work Units

A work unit is an independently executable subtask with:

| Property | Type | Description |
|----------|------|-------------|
| `id` | `str` | Unique identifier |
| `description` | `str` | Human-readable task description |
| `prompt` | `str` | The actual prompt to execute |
| `priority` | `int` | Execution order (lower = higher priority) |
| `status` | `enum` | `pending` / `running` / `completed` / `failed` / `skipped` |
| `dependencies` | `list[str]` | IDs of work units that must complete first |
| `budget_allocation` | `dict` | Token/cost/time limits for this unit |
| `result_key` | `str` | State key where this unit's output is stored |
| `retry_count` | `int` | Times this unit has been retried |
| `max_retries` | `int` | Maximum retry attempts before marking failed |

### Queue Manager

The queue manager sits between the user's overnight prompt and the orchestrator execution loop. It is responsible for:

1. **Decomposition**: Breaking a high-level overnight prompt into work units
2. **Ordering**: Sorting units by priority and dependency constraints
3. **Dispatch**: Feeding units to the orchestrator one at a time (or in parallel batches for independent units)
4. **Result collection**: Capturing each unit's output and making it available to subsequent units
5. **Error isolation**: Marking failed units without killing the run
6. **Retry logic**: Re-attempting failed units with fresh context
7. **Progress tracking**: Maintaining the queue state for heartbeat and notification

### Where It Lives

The queue manager should be a **plugin** that wraps the standard orchestrator lifecycle. It is not a replacement for the orchestrator — it is a harness that invokes the orchestrator repeatedly with different prompts.

This is architecturally similar to `autonomous_self_improvement.md`'s cron-triggered agents, but within a single overnight session rather than across separate scheduled runs.

---

## Decomposition Strategies

### User-Specified

The user provides an explicit task list in their overnight prompt:

```
Analyze these 5 repositories overnight:
1. github.com/org/repo-alpha — security audit focus
2. github.com/org/repo-beta — performance profiling
3. github.com/org/repo-gamma — dependency analysis
4. github.com/org/repo-delta — test coverage gaps
5. github.com/org/repo-epsilon — documentation quality
```

The queue manager maps each numbered item to a work unit. Dependencies are inferred from ordering unless explicitly stated.

### Agent-Decomposed

The queue manager uses a lightweight planning LLM call to decompose a complex prompt into work units. This is a single-call decomposition, not the full Polya understanding workflow — budget should be minimal.

Example: "Audit the monorepo for security vulnerabilities across all microservices" → [enumerate services, audit auth-service, audit payment-service, audit user-service, synthesize findings].

### Template-Driven

For recurring overnight tasks (enabled by Capture Mode topology artifacts), the decomposition is pre-defined in the topology descriptor. The queue manager instantiates work units from the template with the current run's parameters.

---

## Execution Patterns

### Sequential

Work units execute one at a time, in priority order. Each unit sees the accumulated results of all completed prior units via state keys. Simplest pattern, easiest to reason about.

### Parallel-Independent

Independent work units (no dependencies) execute concurrently using the existing `asyncio.Semaphore` concurrency model. Results are collected when all parallel units complete.

### DAG

Work units form a directed acyclic graph of dependencies. The queue manager dispatches units whose dependencies are satisfied, maximizing parallelism within dependency constraints.

### Pipeline

Work units are stages in a pipeline. Each stage's output feeds into the next stage's input. The queue manager serializes execution and manages the data handoff.

---

## Error Isolation

The key property: **a failed work unit does not kill the run**. The queue manager:

1. Marks the unit as `failed`
2. Records the error in the unit's result
3. Checks whether any dependent units can still proceed (some might have the failed unit as an optional dependency)
4. Marks units with hard dependencies on the failed unit as `skipped`
5. Continues with the next eligible unit

After all units are processed, the queue manager produces a summary:
- N completed, M failed, K skipped
- Which units succeeded and their outputs
- Which units failed and why
- Whether the overall task is considered successful despite partial failures

### Retry Strategy

Failed units can be retried with:
- **Same prompt, fresh context**: Maybe a transient error
- **Modified prompt**: If the error suggests the prompt needs adjustment
- **Reduced scope**: If the unit was too large, decompose it further

Retries consume from the unit's individual budget allocation, not the global budget. This prevents a single problematic unit from draining the entire run.

---

## State Management

### Per-Unit State Isolation

Each work unit gets its own namespace in session state, scoped by unit ID:

```
wq:unit:audit-auth-service:status = "completed"
wq:unit:audit-auth-service:result = {structured output}
wq:unit:audit-auth-service:tokens_consumed = 45231
```

### Cross-Unit Communication

Units can read prior units' results via well-known state key patterns. The queue manager injects a `_wq_completed_results` dict into each unit's REPL globals containing the results of all completed predecessor units.

### Queue-Level State

```
wq:total_units = 5
wq:completed = 3
wq:failed = 1
wq:skipped = 1
wq:running = 0
```

All state writes follow AR-CRIT-001 (via `tool_context.state` or `EventActions`).

---

## Interaction with Other Overnight Runtime Features

### Budget Governance

The global budget is subdivided across work units. Each unit gets an allocation. The queue manager enforces per-unit budgets independently of the global budget. If the global budget is exhausted, all remaining units are marked `skipped`.

### Checkpoint-Resume

The work queue state IS the checkpoint. On resume, the queue manager inspects each unit's status and resumes from the first `pending` or `failed` (retryable) unit. Completed units are not re-executed.

This makes checkpoint-resume almost trivial for work queue runs — the queue state is inherently checkpointable.

### Watchdog

The watchdog monitors per-unit health in addition to global health. A single unit that stalls should trigger a unit-level timeout, not a global kill. The watchdog can fail a unit while keeping the run alive.

### Heartbeat

Heartbeats include work queue progress: "3/5 units complete, currently running: audit-payment-service." This gives the sleeping user a clear sense of progress that's harder to derive from raw token counts.

### Capture Mode

Each completed work unit is a potential Capture Mode candidate. A queue of 5 repository audits might produce 5 topology captures if each audit used a novel approach. The queue manager should flag which units are capture-eligible based on the same novelty/success criteria as the main Capture Mode detect phase.

---

## Open Design Questions

- Should the queue manager support dynamic unit creation mid-run? A running unit might discover that its subtask is actually 3 subtasks. Allowing dynamic creation is powerful but complicates progress tracking.
- How to handle cross-unit dependencies when a dependency fails? The dependent unit can be skipped, retried with a placeholder, or given a modified prompt that acknowledges the missing dependency.
- Should the user be able to reprioritize the queue mid-run (via a notification channel or dashboard interaction)? This requires a control plane, which connects to the interactive dashboard vision.
- Is the queue manager a plugin or a new orchestrator subclass? A plugin is less invasive but has limited control over the execution loop. A subclass has full control but is a bigger architectural change.
