<!-- validated: 2026-03-22 -->

# Budget Governance for Unattended Runs

**Status:** Conceptual — no implementation yet

**What it does:** Enforces token, cost, and time budgets for overnight agent sessions so that unattended execution cannot exceed pre-authorized resource consumption. The agent becomes a responsible consumer of its own API access.

---

## Why Budgets Are Different Overnight

In an attended session, the user is the budget controller. They see tokens accumulating in the ObservabilityPlugin output, they feel the session dragging, they ctrl-C when it's enough.

In an overnight run, none of those feedback loops exist. The agent runs until it finishes, hits a hard limit, or crashes. Without explicit budget governance:

- A recursive analysis with `max_depth=3` and generous iteration limits can make hundreds of API calls
- Each API call to Gemini Pro costs tokens; the cumulative spend is invisible until the billing dashboard updates
- An agent that "succeeds" by exploring every possible angle may use 10x the tokens needed for a focused analysis
- The difference between a $2 run and a $50 run is often just the absence of a "that's enough" signal

Budget governance gives the overnight run that signal automatically.

---

## Budget Dimensions

### Token Budget

Total input + output tokens across all model calls (root + children). This is the most direct proxy for API cost.

| Parameter | Default | Env Var |
|-----------|---------|---------|
| Max total tokens | 2,000,000 | `RLM_BUDGET_MAX_TOKENS` |
| Warning threshold | 75% | `RLM_BUDGET_WARN_PCT` |

The existing `ObservabilityPlugin` already tracks `_total_input_tokens` and `_total_output_tokens`. The budget governor reads these counters. For child orchestrators (which ObservabilityPlugin doesn't see), the `SqliteTracingPlugin` telemetry table is the authoritative source.

### Cost Budget

Dollar-denominated ceiling. Requires a cost model that maps (model, input_tokens, output_tokens) to cost. The existing `LiteLLMCostTrackingPlugin` already provides this for models in LiteLLM's pricing database.

| Parameter | Default | Env Var |
|-----------|---------|---------|
| Max cost (USD) | $10.00 | `RLM_BUDGET_MAX_COST` |

### Time Budget

Wall-clock limit for the entire run. Prevents overnight runs from continuing into the next workday.

| Parameter | Default | Env Var |
|-----------|---------|---------|
| Max wall-clock time | 8 hours | `RLM_BUDGET_MAX_TIME` |

### Iteration Budget (existing)

`RLM_MAX_ITERATIONS` already caps REPLTool calls. This remains the inner loop limit. Budget governance adds outer-loop limits that span the full run including child dispatches.

---

## Budget Allocation Strategy

A flat budget ceiling is a blunt instrument. The agent should be able to allocate its budget across phases of work, not just burn through a pool.

### Phase-Aware Allocation

If the overnight task has identifiable phases (e.g., understand → plan → execute → validate), the agent should be able to allocate budget proportionally:

| Phase | Budget Share | Rationale |
|-------|-------------|-----------|
| Understanding/exploration | 30% | Front-loaded discovery |
| Core execution | 50% | The actual work |
| Synthesis/validation | 15% | Final answer quality |
| Reserve | 5% | Error recovery, retries |

The phase proportions could be fixed defaults, skill-specific overrides, or dynamically adjusted by the agent itself (via a budget management REPL primitive).

### Child Budget Inheritance

When the root orchestrator dispatches children, how much of its remaining budget does each child get? Options:

**Equal split**: Each child in a batch gets `remaining / batch_size`. Simple but rigid.

**Priority-weighted**: The dispatch closure assigns priority weights to children. Higher-priority children get larger budget shares.

**Elastic with ceiling**: Each child gets a generous allocation but with a per-child ceiling. Unused budget returns to the pool. This matches the existing `asyncio.Semaphore` concurrency pattern — the semaphore limits parallelism, the budget limits total consumption.

---

## Budget Enforcement Points

### Pre-Model Check

Before each model call, check remaining budget. If exhausted, do not call the model. Instead, inject a "budget exhausted — synthesize final answer now" instruction (same mechanism as watchdog Tier 3).

**Where**: A `before_model_callback` on the reasoning agent or a check inside `REPLTool.run_async` before AST execution.

### Pre-Dispatch Check

Before each child dispatch, check whether the child's estimated cost fits within remaining budget. If not, return a budget-exhaustion `LLMResult` instead of spawning the child.

**Where**: `dispatch.py`, in the `llm_query_batched_async` closure, before calling `create_child_orchestrator`.

### Post-Model Accounting

After each model call, update the running token/cost tally. If the warning threshold is crossed, write a budget warning into dynamic instruction state.

**Where**: The existing `ObservabilityPlugin.after_model_callback` already accumulates tokens. Budget governance extends this with threshold checks.

---

## Budget Reporting

### During Run

Budget status should be visible in the state stream (for SqliteTracingPlugin to capture) and in any heartbeat/notification channel:

```
Budget: 847,231 / 2,000,000 tokens (42%)
Cost: $3.17 / $10.00 (32%)
Time: 2h 14m / 8h 00m (28%)
```

### Post-Run

The budget summary should appear in:
- The final ObservabilityPlugin log line
- A dedicated row or column set in the `traces` table
- The checkpoint artifact (if checkpointing is active)

### Budget Overrun Artifact

If a run is terminated for budget reasons, it should produce a `budget_overrun.json` artifact containing:
- What budget was exceeded
- Total consumption by dimension
- Breakdown by phase/depth/child
- What work was completed before termination
- Suggested budget for a retry (based on extrapolation from completed work)

---

## Interaction with Existing Systems

### ObservabilityPlugin

Budget governance consumes ObservabilityPlugin's token counters. It should NOT duplicate counting logic. If ObservabilityPlugin doesn't fire for children (known limitation), the budget governor must use SqliteTracingPlugin's telemetry table for child accounting.

### Watchdog

Budget exhaustion is one of the watchdog's termination conditions. The budget governor and watchdog should be coordinated — the budget governor sets thresholds, the watchdog enforces them via its tiered intervention system.

### LiteLLMCostTrackingPlugin

Provides the cost model for dollar-denominated budgets. If LiteLLM doesn't have pricing for the active model, the cost budget degrades to token-only governance (with a warning).

### Capture Mode

Budget data is valuable Capture Mode evidence. A topology that consistently uses 500K tokens is worth knowing about when the system later decides whether to re-invoke that topology under a budget constraint.

---

## Open Design Questions

- Should budget be per-run or per-session? A session with multiple invocations might want a cumulative budget, especially for cron-triggered autonomous tasks.
- How to handle budget-constrained resume? If a checkpoint-resumed run inherits the budget from the original run, a partially-consumed budget might be too small for the remaining work.
- Should the agent be able to request a budget increase mid-run (via a notification to the user), or is the budget strictly pre-authorized?
- How to price thinking/reasoning tokens vs output tokens? Some models charge differently for extended thinking.
