<!-- validated: 2026-03-22 -->

# Checkpoint-Resume for Long-Running Sessions

**Status:** Conceptual — no implementation yet

**What it does:** Enables overnight runs to survive interruptions (process crash, machine restart, API outage, watchdog kill) by periodically checkpointing session state to durable storage, and resuming from the last checkpoint rather than restarting from scratch.

---

## Why This Matters for Overnight Runs

A 6-hour overnight analysis that crashes at hour 5 loses all work. The user wakes up to nothing. The existing `SqliteSessionService` persists state across invocations, but the ADK Runner's `run_async` is a single continuous execution — there is no built-in mechanism to resume a partially-completed run.

The gap is between session persistence (which exists) and execution continuity (which does not).

---

## Checkpoint Architecture

### What Gets Checkpointed

A checkpoint is a frozen snapshot of everything needed to resume the run from that point:

| Component | Source | Serialization |
|-----------|--------|---------------|
| Session state | `ctx.session.state` | Already JSON-serializable by ADK contract |
| REPL namespace (serializable subset) | `LocalREPL.locals` | JSON-serializable locals only (same filter as REPLTool return value) |
| Artifact manifest | FileArtifactService | List of saved artifact keys + versions |
| Dispatch state | Accumulator snapshots from `flush_fn` | Already JSON via state delta |
| Iteration position | `ITERATION_COUNT`, `CURRENT_DEPTH` | State keys (already persisted) |
| Active child dispatches | Child orchestrator status | Completion status + partial results |
| Telemetry snapshot | SqliteTracingPlugin tables | Already durable (SQLite) |

### What Does NOT Get Checkpointed

- The model's internal context window (not accessible or restorable)
- In-flight API calls (must be retried on resume)
- Async event queue contents (drained before checkpoint)
- Non-serializable REPL locals (file handles, sockets, custom objects)

The model context gap is the fundamental design constraint. On resume, the reasoning agent starts with a fresh context window. The resumed session must reconstruct enough context from checkpointed state for the model to continue meaningfully.

---

## Checkpoint Triggers

### Periodic

Every N iterations or every M minutes (whichever comes first). Default: every 5 iterations or every 10 minutes.

### Event-Driven

- After each successful child dispatch batch (results are expensive to recompute)
- After each artifact save (durable output produced)
- Before watchdog Tier 3/4 interventions (preserve state before forced action)
- On graceful shutdown signal (SIGTERM, SIGINT)

### Explicit

The model itself could request a checkpoint via a REPL primitive: `checkpoint("analysis phase complete")`. This gives the agent agency over its own resilience. The checkpoint label becomes a named resumption point.

---

## Resume Strategy

### Context Reconstruction

On resume, the system cannot just "unpause" the model. It must construct a new invocation that picks up where the last one left off. The resume prompt should include:

1. **Original root prompt** (from checkpoint)
2. **Progress summary** — what has been accomplished so far, synthesized from:
   - Artifact manifest (what outputs exist)
   - State key values (iteration count, depth reached, dispatch counts)
   - REPL locals snapshot (intermediate variables and their values)
   - Last N REPL code blocks and their results (from artifacts)
3. **Remaining work** — what the agent was doing when checkpointed, derived from:
   - Active iteration position
   - Any pending child dispatches that hadn't completed
   - The last REPL code block's intent (from the submitted code artifact)
4. **Instruction to continue** — explicit framing that this is a resumed session, not a fresh start

### Resume Modes

**Continue** — Pick up the current task from the checkpoint. The agent reviews its progress summary and continues working.

**Retry-from-checkpoint** — Re-attempt the last failed operation with fresh model context. Useful after watchdog kills where the agent was stuck but the underlying task is still valid.

**Branch** — Resume from a checkpoint but with a modified prompt or different strategy. Enables the user to review partial overnight results and redirect in the morning.

---

## Checkpoint Storage

Checkpoints should be stored as versioned artifacts via the existing `FileArtifactService`:

```
.adk/artifacts/
  checkpoint_iter_5.json      # Iteration-triggered
  checkpoint_batch_done.json  # Event-triggered
  checkpoint_user_label.json  # Explicit checkpoint
```

Each checkpoint is a self-contained JSON document with all restorable state. The artifact versioning system already handles naming and ordering.

---

## Interaction with Existing Systems

### Session Service

The `SqliteSessionService` already persists `session.state` after each event. Checkpoints extend this by also capturing REPL namespace and execution position in a single atomic artifact.

### Artifact Service

Checkpoints are artifacts. This means they inherit versioning, persistence guarantees, and the existing save/load API.

### Watchdog

The watchdog should trigger a checkpoint before any Tier 3 or Tier 4 intervention. This ensures that forced synthesis or hard kills don't lose accumulated work.

### Capture Mode

If a run resumes from a checkpoint and eventually succeeds, Capture Mode should have access to the full execution history — including the pre-checkpoint work. The checkpoint artifacts serve as the bridge.

---

## Open Design Questions

- How much REPL context to include in the resume prompt? Too little and the model is disoriented. Too much and we waste context window on stale intermediate state.
- Should checkpoints include the raw code artifacts, or just references to them? Including them makes checkpoints self-contained but larger.
- How does checkpoint-resume interact with `persistent` REPL mode? A persistent REPL is already designed to survive across invocations, but it doesn't currently checkpoint its namespace.
- Should there be a maximum number of checkpoints retained? Old checkpoints from a completed run are just artifact bloat.
- Can the resume prompt be generated by a lightweight LLM call (summarize progress from checkpoint data), or should it be a deterministic template? The latter is cheaper and more predictable; the former might produce better context.

---

## Non-Goals

- **Full replay from checkpoint**: This is not about replaying the exact same model calls. The model will generate different responses on resume. The goal is continuity of task progress, not deterministic replay.
- **Distributed execution**: Checkpoints are single-machine, single-process. Multi-machine coordination is a different (much harder) problem.
- **Context window persistence**: We cannot save and restore the model's internal state. Resume always means a fresh context window with reconstructed context.
