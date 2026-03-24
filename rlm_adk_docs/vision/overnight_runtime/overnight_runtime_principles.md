<!-- validated: 2026-03-22 -->

# Overnight Runtime Principles

Design philosophy for long-running unattended agent execution. These principles sit alongside `evolution_principles.md` — that document defines what the agent should become over time; this document defines how it should behave when no one is watching.

---

## The agent must be a responsible steward of resources it was given

An overnight run is pre-authorized access to API endpoints, compute time, and storage. The agent does not get to consume without limit just because no one is watching. Every unattended session should have an explicit budget envelope, and the agent should optimize within that envelope rather than merely against the task.

See: [budget_governance.md](budget_governance.md)

## The agent must fail gracefully, not catastrophically

Unattended failure must be bounded. A single failing subtask should not cascade into total loss of all work. The agent should isolate failures, preserve partial results, and leave a clear record of what went wrong so the user can diagnose and retry in the morning.

See: [watchdog_and_circuit_breaker.md](watchdog_and_circuit_breaker.md), [work_queue_decomposition.md](work_queue_decomposition.md)

## The agent must be resumable, not restartable

Overnight work should survive interruptions. A 6-hour run that crashes at hour 5 should lose minutes of work, not hours. The system should checkpoint aggressively and resume cheaply, treating long-running execution as a series of durably-recorded increments rather than one fragile continuous process.

See: [checkpoint_resume.md](checkpoint_resume.md)

## The agent must communicate at human pace, not machine pace

The sleeping user cannot consume real-time output. Progress signals should be periodic, tiered by severity, and delivered through channels the user will actually see (phone notification, email, dashboard). The agent should produce a concise morning summary that respects the user's time.

See: [heartbeat_and_notification.md](heartbeat_and_notification.md)

## The agent must distinguish exploration from progress

In an attended session, exploration is visible and implicitly authorized by the user's continued presence. In an unattended session, exploration is invisible and potentially wasteful. The agent must have an explicit model of "am I making progress toward the goal?" and self-correct when it is not. This is not the same as preventing all exploration — some tasks require it. But the agent should know the difference and budget accordingly.

See: [watchdog_and_circuit_breaker.md](watchdog_and_circuit_breaker.md) (progress detection)

## The agent must leave the workspace cleaner than it found it

An overnight run that produces hundreds of intermediate artifacts, temp files, and debug outputs has failed even if the final answer is correct. The agent should organize its outputs, clean up transient artifacts, and produce a clear artifact manifest. The user should be able to find and understand the results without archaeology.

## The agent must be auditable after the fact

Every decision made during an overnight run — what to work on, what to skip, when to retry, when to give up — must be traceable from the telemetry record. The existing SqliteTracingPlugin provides the infrastructure; overnight runtime features must write their decisions into it. The user should be able to reconstruct the agent's reasoning chain from the trace, not just its outputs.

---

## Relationship to Evolution Principles

The evolution principles say the agent should get better over time. The overnight runtime principles say the agent should be trustworthy enough to run unsupervised. These reinforce each other:

- **Self-improvement** (evolution) requires **reliable execution** (overnight) — you can't learn from runs that crash without records
- **Gap awareness** (evolution) requires **progress detection** (overnight) — the agent must know what it doesn't know about its own execution health
- **Documentation maintenance** (evolution) requires **auditability** (overnight) — overnight runs should update their own docs when they discover drift
- **Topology optimization** (evolution) requires **budget-aware execution** (overnight) — topology selection should factor in resource efficiency, not just quality

---

## Build Order

The overnight runtime features have a natural dependency order:

1. **Watchdog & Circuit Breaker** — Foundation. Without this, nothing else is safe to run unattended.
2. **Budget Governance** — Required before any real unattended use. Prevents runaway costs.
3. **Heartbeat & Notification** — Quality of life for the user. Builds trust in unattended execution.
4. **Checkpoint-Resume** — Resilience. Required for runs longer than ~2 hours where the cost of restart is unacceptable.
5. **Work Queue Decomposition** — Sophistication. Enables complex multi-part overnight tasks. Builds on all prior features.

Each feature is independently valuable, but the full stack is multiplicatively more powerful than any individual feature.
