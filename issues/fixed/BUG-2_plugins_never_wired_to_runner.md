# BUG-2: Plugins never wired into the InMemoryRunner

## Location

`rlm_adk/agent.py` lines 134-154 (plugin construction) and lines 192-195 (runner creation)

## Description

`RLMAdkEngine.__init__` builds a `self.plugins` list containing `DepthGuardPlugin`, `CachePlugin`, `ObservabilityPlugin`, `PolicyPlugin`, and optionally `DebugLoggingPlugin`. However, `acompletion()` creates the `InMemoryRunner` without passing these plugins:

```python
runner = InMemoryRunner(
    agent=orchestrator,
    app_name="rlm_adk",
)
```

The plugins are constructed, stored on the engine instance, and never used. All plugin callback hooks (`before_model_callback`, `after_model_callback`, `on_model_error_callback`, `before_tool_callback`, `on_event_callback`, `after_run_callback`, `on_user_message_callback`) are never invoked by the ADK framework because the plugins are not registered with the runner.

## Impact

Every plugin-dependent behavior is dead at runtime:

| Plugin | Dead behavior |
|---|---|
| DepthGuardPlugin | Depth enforcement never triggers; model errors not caught |
| CachePlugin | No caching; cache hit/miss counters never increment |
| ObservabilityPlugin | No usage tracking; no timing; no audit trail |
| PolicyPlugin | No request_id generation; no blocked-pattern enforcement |
| DebugLoggingPlugin | No trace output |

## Fix

Pass plugins when constructing the runner. The ADK `InMemoryRunner` (or `Runner`) accepts a `plugins` parameter:

```python
runner = InMemoryRunner(
    agent=orchestrator,
    app_name="rlm_adk",
    plugins=self.plugins,          # <-- add this
)
```

Verify the exact parameter name against the ADK API version in use (`google-adk`).

## Affected SRS requirements

- PS-001 (Cache Plugin Behavior)
- PS-002 (Observability Plugin Behavior)
- PS-003 (Policy Plugin Behavior)
- AR-HIGH-002 (Model Error Handling)
- AR-HIGH-004 (Depth Semantics)
- FR-013 (Usage Tracking)
