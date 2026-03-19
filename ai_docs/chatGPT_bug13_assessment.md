Verdict: **verified for plugin `after_model_callback` on current `adk-python` main**. The statement is correct **as written for plugin callbacks**, but it would be **wrong if generalized to all `after_model_callback`s**, because the agent-level/canonical `after_model_callback` path is wired differently. ([GitHub][1])

The docs say callback state writes are supposed to be tracked into a subsequent event delta: ADK’s state docs say direct writes like `callback_context.state['my_key'] = ...` are “automatically tracked,” and the callback best-practices page says modifications are tracked in the subsequent `Event.actions.state_delta`. The callbacks overview also presents `after_model_callback` as a normal lifecycle hook for modifying the returned `LlmResponse`. ([Google GitHub][2])

The source code explains why the plugin path breaks that expectation. In ADK Python, `CallbackContext` is now just an alias of `Context`. `Context.__init__` binds state tracking to a specific `EventActions` object: it sets `self._event_actions = event_actions or EventActions()` and then builds `State(..., delta=self._event_actions.state_delta)`. So whether a state write lands in a yielded event depends on whether the context was constructed with the **same** `EventActions` that the eventual event will carry. ([GitHub][3])

In `base_llm_flow.py`, the framework first creates `callback_context = CallbackContext(invocation_context, event_actions=model_response_event.actions)`. That properly wires the context to the event that will later be yielded. But when plugin `after_model_callback` is actually invoked, ADK does **not** pass that prepared context. It calls `run_after_model_callback(callback_context=CallbackContext(invocation_context), llm_response=llm_response)`, i.e. a fresh context with fresh `EventActions`. Immediately after that, the agent-level/canonical `after_model_callback` path uses the correctly prepared `callback_context` that *is* wired to `model_response_event.actions`. ([GitHub][1])

So the practical consequence is exactly what Claude Code claimed: **writes to `callback_context.state` inside a plugin `after_model_callback` will not land in the yielded model event’s `actions.stateDelta`**, because they are being recorded against an unshared `EventActions` object. By contrast, **agent-level/canonical `after_model_callback` state writes should be attached correctly**, because that path uses the wired `callback_context`. ([GitHub][1])

The issues page supports the broader pattern, though I did not find one filed on this exact wiring bug. Issue **#2992** shows that callback state writes in other callback paths do produce yielded state-delta events, which is consistent with the documented model. Issue **#4182** shows a separate live-mode bug where `state_delta` can exist backend-side but still fail to reach WebSocket clients, so mismatches between state mutation and emitted event deltas are already a known class of problem in the tracker. ([GitHub][4])

One more nuance: the `State` implementation currently updates both the underlying `_value` and the `_delta` on `__setitem__`, so a plugin `after_model_callback` write may still mutate in-memory session state during that invocation. But because that delta is attached to the wrong `EventActions`, it is **not** the documented “tracked via yielded event/state_delta” path. ([GitHub][5])

The clean takeaway is:

* **Plugin `after_model_callback`**: Claude’s statement is **correct**. ([GitHub][1])
* **Agent-level/canonical `after_model_callback`**: Claude’s statement is **not** correct if applied there. ([GitHub][1])
* If you need a supported `after_model_callback` output-side mutation today, ADK explicitly added `LlmResponse.custom_metadata` for tagging responses from `after_model_callback`, which is safer than relying on plugin-state-to-event-delta in this path. ([GitHub][6])

If you want, I can turn this into a tight bug report with exact file/line references and a one-line patch.

[1]: https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py "adk-python/src/google/adk/flows/llm_flows/base_llm_flow.py at main · google/adk-python · GitHub"
[2]: https://google.github.io/adk-docs/sessions/state/ "State - Agent Development Kit (ADK)"
[3]: https://github.com/google/adk-python/blob/main/src/google/adk/agents/callback_context.py "adk-python/src/google/adk/agents/callback_context.py at main · google/adk-python · GitHub"
[4]: https://github.com/google/adk-python/issues/2992 "state delta event from before_agent_callback has is_final_response() == True · Issue #2992 · google/adk-python · GitHub"
[5]: https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/sessions/state.py "raw.githubusercontent.com"
[6]: https://github.com/google/adk-python/blob/main/CHANGELOG.md "adk-python/CHANGELOG.md at main · google/adk-python · GitHub"


Here’s a paste-ready bug report.

## Bug: plugin `after_model_callback` receives an unwired `CallbackContext`, so `callback_context.state[...] = ...` does not land in the yielded model event’s `actions.state_delta`

### Summary

In ADK Python, plugin `after_model_callback` is currently invoked with a fresh `CallbackContext(invocation_context)` instead of the already-prepared `callback_context` that is wired to `model_response_event.actions`. Because `CallbackContext` is just an alias of `Context`, and `Context` binds `state` writes to the supplied `EventActions.state_delta`, state writes made from a plugin `after_model_callback` are recorded on a different `EventActions` object and therefore do **not** appear in the yielded model event’s `actions.state_delta`. By contrast, the agent-level/canonical `after_model_callback` path *is* passed the wired `callback_context` and should work as documented. ([GitHub][1])

### Why this looks like a bug, not just a docs mismatch

The callback docs explicitly describe `after_model_callback` as a place for “parsing structured data from the LLM response and storing it in `callback_context.state`.” The state docs also say state changes made through callback context are automatically part of the event’s `state_delta`. That documented contract matches the agent-level/canonical path, but not the plugin `after_model_callback` path. ([Google GitHub][2])

### Exact source references showing the bug

In `src/google/adk/flows/llm_flows/base_llm_flow.py`, ADK first creates a correctly wired context using `event_actions=model_response_event.actions` at lines 2663–2666. But the plugin callback is then invoked with a fresh `CallbackContext(invocation_context)` at lines 2673–2677 instead of that wired context. ([GitHub][1])

In the same function, the agent-level/canonical `after_model_callback` path uses the already-prepared `callback_context` at lines 2694–2698, which is the behavior plugin callbacks appear to need as well. ([GitHub][1])

In `src/google/adk/agents/callback_context.py`, `CallbackContext` is just `Context` at lines 315–317. In `src/google/adk/agents/context.py`, `Context.__init__` stores `self._event_actions = event_actions or EventActions()` and constructs `State(..., delta=self._event_actions.state_delta)` at lines 1216–1224. The `state` property then returns that delta-aware state object at lines 1264–1274. This means the correctness of `callback_context.state[...] = ...` depends on the context being constructed with the same `EventActions` that the eventual event will emit. ([GitHub][3])

In `src/google/adk/events/event_actions.py`, `state_delta` is the event field that carries state changes at lines 561–563. In `src/google/adk/sessions/state.py`, `State.__setitem__` writes into both `_value` and `_delta` at lines 462–472. So plugin `after_model_callback` writes may mutate in-memory state for that context, but their delta is attached to the wrong `EventActions`, which is why it does not surface on the yielded event. ([GitHub][4])

### Minimal repro

Create a plugin with `after_model_callback` that does `callback_context.state["temp:test_key"] = "x"` and run an `LlmAgent` through `Runner.run_async`. Observe that the yielded model response event does not carry that key in `event.actions.state_delta`, even though the same pattern is documented as valid and works through other callback paths. The issue tracker already contains adjacent state-delta/event-emission bugs, which makes this behavior consistent with an implementation gap rather than an intended API distinction. ([Google GitHub][2])

### Expected behavior

Plugin `after_model_callback` should receive the same `callback_context` object that is already wired to `model_response_event.actions`, so that `callback_context.state[...] = ...` lands in the yielded event’s `actions.state_delta`, matching the documented callback and state behavior. ([GitHub][1])

### Actual behavior

Plugin `after_model_callback` receives a new `CallbackContext(invocation_context)` with fresh `EventActions`, so state writes are not attached to `model_response_event.actions.state_delta` and do not appear on the yielded event. The agent-level/canonical `after_model_callback` path does not have this problem because it uses the correctly wired context. ([GitHub][1])

## Alternative, currently working paths for mutating data after model

### 1) Agent-level / canonical `after_model_callback`

The canonical agent-level path in `base_llm_flow.py` uses the prepared `callback_context` created with `event_actions=model_response_event.actions` at lines 2663–2666, and passes that exact object into `agent.canonical_after_model_callbacks` at lines 2694–2698. This is the source-backed path that should preserve `state_delta` correctly after model execution. ([GitHub][1])

The public ADK API docs also define `after_model_callback` as an `LlmAgent` field, reinforcing that this agent-level path is the standard callback surface. ([Google GitHub][5])

### 2) `LlmResponse.custom_metadata`

`LlmResponse` has a dedicated `custom_metadata: Optional[dict[str, Any]]` field in `src/google/adk/models/llm_response.py` at lines 777–784, documented as an optional JSON-serializable key-value label for the response. ADK’s v0.3.0 release notes explicitly say this field was added so `LlmResponse` can be tagged via `after_model_callback`. This gives users a supported “after model” mutation path that does not rely on `EventActions.state_delta` wiring. ([GitHub][6])

## Proposed fix

In `src/google/adk/flows/llm_flows/base_llm_flow.py`, change the plugin invocation from passing `CallbackContext(invocation_context)` to passing the already-created `callback_context`.

Current behavior at lines 2673–2677: plugin manager is called with `callback_context=CallbackContext(invocation_context)`. The fix is to pass `callback_context=callback_context` instead, so plugin and canonical after-model callbacks share the same event-bound `EventActions`. ([GitHub][1])

## Suggested regression tests

Add one test proving that a plugin `after_model_callback` state write appears in the yielded event’s `actions.state_delta`, mirroring the documented callback-state behavior. Add a second test confirming the existing agent-level/canonical `after_model_callback` path still emits the delta. Add a third test confirming `llm_response.custom_metadata` remains a valid alternative tagging path in `after_model_callback`. ([Google GitHub][2])

## Related tracker context

I did not find a GitHub issue that exactly names this plugin `after_model_callback` wiring mismatch, but the tracker does contain nearby bugs around callback-driven `state_delta` emission and missing post-processing metadata on emitted events, including issue #2992 and issue #1693. That makes this report fit an existing class of event/callback wiring problems in ADK Python. ([GitHub][7])

If you want, I can also turn this into a tighter GitHub-issue version with a one-line diff and a minimal repro script.

[1]: https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py "adk-python/src/google/adk/flows/llm_flows/base_llm_flow.py at main · google/adk-python · GitHub"
[2]: https://google.github.io/adk-docs/callbacks/types-of-callbacks/ "Types of callbacks - Agent Development Kit (ADK)"
[3]: https://github.com/google/adk-python/blob/main/src/google/adk/agents/callback_context.py "adk-python/src/google/adk/agents/callback_context.py at main · google/adk-python · GitHub"
[4]: https://github.com/google/adk-python/blob/main/src/google/adk/events/event_actions.py "adk-python/src/google/adk/events/event_actions.py at main · google/adk-python · GitHub"
[5]: https://google.github.io/adk-docs/api-reference/python/google-adk.html "Submodules - Agent Development Kit documentation"
[6]: https://github.com/google/adk-python/blob/main/src/google/adk/models/llm_response.py "adk-python/src/google/adk/models/llm_response.py at main · google/adk-python · GitHub"
[7]: https://github.com/google/adk-python/issues/2992 "state delta event from before_agent_callback has is_final_response() == True · Issue #2992 · google/adk-python · GitHub"
