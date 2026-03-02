# BUG-11: ADK session service strips `temp:` state keys from Event state_delta

## Severity

**Critical** — causes the reasoning agent to loop indefinitely without progress.

## Symptom

When running `adk run --replay`, the reasoning agent repeats the same first step
(e.g. `os.listdir()`) on every iteration. It never sees REPL execution results,
conversation history, or iteration count. The debug log shows `prompt_chars=0`,
`history_msgs=0`, and `iter=0` on every call despite the orchestrator advancing.

## Location

`rlm_adk/orchestrator.py` — all `yield Event(state_delta={...})` calls that
include `temp:` prefixed keys.

## Root Cause

The orchestrator communicates iteration state to callbacks via
`yield Event(actions=EventActions(state_delta={TEMP_KEY: value}))`. All RLM
invocation-scoped keys use the `temp:` prefix (e.g. `temp:message_history`,
`temp:iteration_count`, `temp:current_depth`).

However, ADK's `BaseSessionService.append_event()` **strips all `temp:` prefixed
keys** from the event's `state_delta` before applying it to the session:

```python
# google/adk/sessions/base_session_service.py
def _trim_temp_delta_state(self, event: Event) -> Event:
    event.actions.state_delta = {
        key: value
        for key, value in event.actions.state_delta.items()
        if not key.startswith(State.TEMP_PREFIX)   # ← strips "temp:*"
    }
    return event
```

This means `temp:message_history` is **never written to `session.state`**. When
the reasoning agent's `before_model_callback` reads it:

```python
# rlm_adk/callbacks/reasoning.py
message_history = callback_context.state.get(TEMP_MESSAGE_HISTORY, [])
```

…it always gets `[]`. The model never sees conversation history or REPL output.

### Why some temp: keys work

Direct writes from callbacks (`callback_context.state[key] = value`) bypass the
session service entirely — `State.__setitem__` writes straight into the
`session.state` dict:

```python
# google/adk/sessions/state.py
def __setitem__(self, key, value):
    self._value[key] = value   # _value IS session.state
    self._delta[key] = value
```

This is why `TEMP_LAST_REASONING_RESPONSE` (written by `reasoning_after_model`)
works when the orchestrator reads it back via `ctx.session.state.get(...)`.

### The asymmetry

| Mechanism | temp: keys applied? | Used by |
|---|---|---|
| `callback_context.state[key] = val` | **Yes** (direct dict write) | Callbacks |
| `yield Event(state_delta={key: val})` | **No** (stripped by session service) | Orchestrator |

## Affected State Keys

All `temp:` keys set via Event `state_delta` in the orchestrator:

- `temp:message_history` — **critical**: reasoning agent sees empty history every iteration
- `temp:iteration_count` — debug logs always show `iter=0`
- `temp:current_depth` — depth tracking broken
- `temp:root_prompt` — root prompt not available to callbacks
- `temp:repo_url` — repo URL not available to callbacks
- `temp:should_stop` / `temp:final_answer` — stop signaling
- `temp:last_repl_result` — REPL result metadata
- `temp:worker_events_drained` / `temp:worker_results_committed` — worker lifecycle

Non-temp keys (`repo_url`, `root_prompt` via `DYN_*`) are unaffected.

## Fix

Write `temp:` keys directly to `ctx.session.state` instead of routing them
through Event `state_delta`. Non-temp keys should remain in events for
persistence.

**Before** (broken):
```python
yield Event(
    invocation_id=ctx.invocation_id,
    author=self.name,
    actions=EventActions(state_delta={
        TEMP_MESSAGE_HISTORY: current_prompt,
    }),
)
```

**After** (fixed):
```python
ctx.session.state[TEMP_MESSAGE_HISTORY] = current_prompt
```

Apply this pattern to all six `yield Event(state_delta=...)` sites in
`orchestrator.py` that include `temp:` keys:

1. **Initial state** (line ~131): Split temp vs non-temp; write temp directly,
   yield Event only for `DYN_ROOT_PROMPT` / `DYN_REPO_URL`.
2. **Message history injection** (line ~150): Write directly.
3. **Worker events drained** (line ~172): Write directly.
4. **Final answer detected** (line ~244): Write directly.
5. **Iteration state update** (line ~279): Write directly.
6. **Max iterations exhausted** (line ~314): Write directly.

## Reproduction

```bash
uv run adk run --replay tests_rlm_adk/replay/test_basic_context.json rlm_adk
```

Observe: reasoning agent loops on the same step every iteration, `prompt_chars=0`
and `history_msgs=0` in every debug log line.

## Related

- ADK source: `google/adk/sessions/base_session_service.py` — `_trim_temp_delta_state`
- ADK source: `google/adk/sessions/state.py` — `State.__setitem__` direct-write path
- ADK source: `google/adk/flows/llm_flows/base_llm_flow.py` — plugin before_model
  runs before agent before_model (line ~981 vs ~995)
