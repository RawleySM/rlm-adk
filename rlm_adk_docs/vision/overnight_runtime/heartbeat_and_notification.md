<!-- validated: 2026-03-22 -->

# Heartbeat & Progress Notification

**Status:** Conceptual — no implementation yet

**What it does:** Provides asynchronous progress reporting for unattended overnight runs so the user can passively monitor status without being present. The agent tells you how it's doing while you sleep — and wakes you up if something goes wrong.

---

## The Communication Gap

Today's RLM runtime communicates through two channels:

1. **Synchronous CLI output** — requires a human watching the terminal
2. **Post-hoc trace analysis** — requires the run to finish

Neither works for overnight runs. The user needs a third channel: **asynchronous progress signals** that arrive at the user's pace, not the agent's pace.

---

## Heartbeat Architecture

### Heartbeat Events

A periodic signal emitted by the running agent that says "I am alive and making progress." The heartbeat carries a lightweight status payload, not a full trace dump.

**Emission frequency**: Configurable, default every 10 minutes or every 5 iterations (whichever comes first). The frequency should decrease as the run stabilizes (adaptive backoff).

**Payload**:

```
{
  "timestamp": "2026-03-23T03:45:12Z",
  "run_id": "abc-123",
  "status": "running",
  "iteration": 17,
  "depth": 0,
  "tokens_consumed": 423891,
  "budget_pct": 42,
  "artifacts_saved": 8,
  "child_dispatches_completed": 12,
  "last_meaningful_progress": "2026-03-23T03:42:01Z",
  "current_activity": "analyzing repository structure",
  "watchdog_status": "green"
}
```

The `current_activity` field is derived from the most recent REPL code submission or dynamic instruction state — a one-line summary of what the agent is doing right now.

### Heartbeat Sink

Where heartbeats go. The system should support multiple sinks simultaneously:

| Sink | Mechanism | Latency | Best For |
|------|-----------|---------|----------|
| Local file | Append to `.adk/heartbeat.jsonl` | None | Post-hoc review, dashboard polling |
| SQLite | Row in `traces.db` heartbeat table | None | Query-based monitoring |
| Desktop notification | `notify-send` / OS notification API | Immediate | Same-machine monitoring |
| Email | SMTP or Gmail API | Minutes | Sleep-compatible, failure alerts |
| Slack/Discord webhook | HTTP POST | Seconds | Team visibility |
| Mobile push | ntfy.sh or similar | Seconds | True fire-and-forget overnight |

The user configures which sinks are active via environment variables. Default: local file only.

---

## Notification Tiers

Not every event deserves the same urgency. Notifications are tiered by severity:

### Tier 0 — Silent Heartbeat

Written to local file/SQLite only. No push notification. This is the "I'm alive" signal for passive monitoring.

**Frequency**: Every 10 minutes.

### Tier 1 — Progress Milestone

Emitted when something genuinely meaningful happens:
- Major phase completion (e.g., understanding phase → execution phase)
- Large artifact produced (e.g., analysis report, code generation)
- Significant child dispatch batch completed
- Budget threshold crossed (50%, 75%)

**Channel**: Local file + configured push channels (if any).

### Tier 2 — Warning

Emitted when something looks concerning but the run is continuing:
- Watchdog status changed to `yellow`
- Error rate elevated
- Budget approaching limit (>85%)
- Progress stalled (no meaningful progress for 30+ minutes)
- Retry loop detected but not yet critical

**Channel**: All configured channels. If email is configured, send.

### Tier 3 — Critical / Run Terminated

Emitted when the run stops:
- Run completed successfully
- Watchdog killed the run
- Budget exhausted
- Unrecoverable error
- Process signal (SIGTERM)

**Channel**: All configured channels. This is the "wake up" notification.

**Payload for Tier 3**: Includes a summary of what was accomplished, what artifacts were produced, and (for failures) what went wrong. This is the email/notification the user reads in the morning.

---

## Morning Summary

When the overnight run completes (success or failure), the system should produce a **morning summary artifact** — a concise, human-readable report of what happened while the user slept.

Contents:

1. **Outcome**: Success / Partial / Failed / Killed
2. **Duration**: Wall-clock time and active processing time
3. **Resource consumption**: Tokens, estimated cost, API calls
4. **Work completed**: List of produced artifacts with brief descriptions
5. **Progress timeline**: Key milestones with timestamps
6. **Issues encountered**: Errors, retries, watchdog interventions
7. **Recommendations**: If failed/partial, what to try next; if successful, what to review first

This summary should be:
- Saved as `.adk/artifacts/morning_summary.md`
- Included in the Tier 3 notification payload
- Formatted as readable markdown (not JSON) so the user can scan it quickly

---

## Interaction with Existing Systems

### ObservabilityPlugin

Heartbeat reads from ObservabilityPlugin's counters for the status payload. The heartbeat is a periodic snapshot of observability state, not a duplicate counter.

### SqliteTracingPlugin

Heartbeats can be stored as rows in a `heartbeats` table alongside the existing `traces` and `telemetry` tables. This enables post-hoc queries like "show me the heartbeat timeline for run X."

### Watchdog

The watchdog status is a field in every heartbeat. When the watchdog escalates tiers, it triggers a corresponding notification. The heartbeat system is the watchdog's notification channel.

### Dashboard

The live NiceGUI dashboard could poll `.adk/heartbeat.jsonl` or the heartbeats table to show real-time status. This turns the current snapshot-oriented dashboard into a live monitor suitable for overnight runs.

### Checkpoint-Resume

A heartbeat immediately after a checkpoint gives the user confidence that progress was saved. On resume, a Tier 1 notification informs the user that the run has restarted.

---

## Configuration

```bash
# Enable heartbeat (default: file only)
RLM_HEARTBEAT_ENABLED=true
RLM_HEARTBEAT_INTERVAL_MINUTES=10

# Push notification channels
RLM_HEARTBEAT_NTFY_TOPIC=rlm-overnight       # ntfy.sh push notifications
RLM_HEARTBEAT_EMAIL=user@example.com          # Email for Tier 2+
RLM_HEARTBEAT_WEBHOOK_URL=https://...         # Slack/Discord webhook

# Notification thresholds
RLM_HEARTBEAT_STALL_MINUTES=30               # Minutes without progress before Tier 2 warning
```

---

## Open Design Questions

- Should the heartbeat include a "progress percentage" estimate? This would require the agent to know how much work remains, which is often unknowable. A misleading progress bar might be worse than no progress bar.
- How to generate the `current_activity` summary without spending tokens? It should be derived from existing state (last code submission, current skill instruction), not from an LLM summarization call.
- Should the morning summary be generated by the agent itself (LLM call on the accumulated telemetry) or deterministically assembled from structured data? The former is richer; the latter is cheaper and guaranteed.
- Should heartbeats be encrypted or access-controlled when sent to external channels? The heartbeat payload includes task descriptions that may be sensitive.
