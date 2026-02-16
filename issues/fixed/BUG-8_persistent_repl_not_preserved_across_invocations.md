# BUG-8: Persistent REPL not preserved across invocations

## Location

`rlm_adk/orchestrator.py` lines 80-83 (inside `_run_async_impl`)

## Description

When `persistent=True`, the expectation is that the REPL environment survives across multiple `completion()` calls so that variables, contexts, and histories accumulate. However, the orchestrator creates a new `LocalREPL` as a local variable inside `_run_async_impl` on every invocation:

```python
async def _run_async_impl(
    self, ctx: InvocationContext
) -> AsyncGenerator[Event, None]:
    # ...
    # Initialize REPL environment
    repl = LocalREPL(
        context_payload=self.context_payload,
        depth=1,
    )
```

Since `repl` is a local variable, it is destroyed when `_run_async_impl` returns. The next call to `completion()` creates a fresh `LocalREPL` with no memory of prior turns. The `finally` block at the end only skips `cleanup()` when `persistent=True` (line 254), but this merely avoids deleting the temp directory of an already-orphaned REPL -- it doesn't preserve the REPL instance itself.

Additionally, `RLMAdkEngine.acompletion()` creates a new `RLMOrchestratorAgent` on every call (agent.py line 183), so even if the REPL were stored on the orchestrator as an instance field, it would be discarded with the orchestrator.

## Impact

- `persistent=True` has no effect -- every `completion()` call starts with a blank REPL
- Contexts do not accumulate as `context_0..N` across turns
- Histories are not stored or accessible in subsequent turns
- Variables set in one completion are lost in the next
- FR-008 (Persistent Session State) and FR-009 (Non-Persistent Isolation -- the contrast) cannot be meaningfully validated
- The `add_history()` calls at lines 190 and 251 store history into a REPL that is about to be garbage-collected

## Fix

The REPL must be long-lived when `persistent=True`. Two options:

### Option A: Store the REPL on the engine (simplest)

Move REPL ownership to `RLMAdkEngine` so it persists across calls:

```python
class RLMAdkEngine:
    def __init__(self, ...):
        # ...
        self._persistent_repl: LocalREPL | None = None

    async def acompletion(self, prompt, root_prompt=None):
        if self.persistent:
            if self._persistent_repl is None:
                self._persistent_repl = LocalREPL(depth=1)
            repl = self._persistent_repl
            repl.add_context(prompt)  # appends as context_N
        else:
            repl = LocalREPL(context_payload=prompt, depth=1)

        # Pass repl to orchestrator instead of context_payload
        orchestrator = create_rlm_orchestrator(
            model=self.model,
            repl=repl,  # new parameter
            root_prompt=root_prompt,
            # ...
        )
        # ...
```

### Option B: Store state in ADK session

Serialize REPL state (locals, context count, history count) into session state between invocations and restore on the next call. This is more ADK-idiomatic but requires careful serialization of arbitrary Python objects.

Option A is recommended for the local execution path. Option B would be needed for isolated (cloud) environments but those are out of scope.

In either case, `close()` on the engine should call `repl.cleanup()` on the persistent REPL.

## Affected SRS requirements

- FR-008 (Persistent Session State)
- FR-009 (Non-Persistent Isolation -- meaningless without working persistence to contrast)
- FR-010 (Prompt Awareness -- context/history counts always 0/1 without accumulation)
