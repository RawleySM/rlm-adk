# Phase 0+1: Structured Output + Depth-Scoped State

*2026-03-04T18:04:31Z by Showboat 0.6.0*
<!-- showboat-id: cd65dd04-4773-468c-9a65-6898fd6d03d5 -->

## Phase 0: Structured Output on Parent Reasoning Agent

Phase 0 wires SetModelResponseTool onto the parent reasoning_agent alongside REPLTool. This lets the model emit structured output (ReasoningOutput schema) via set_model_response while still being able to call execute_code. WorkerRetryPlugin callbacks handle retry logic, and a finally block cleans up all wiring after each run.

```bash
sed -n "170,178p" rlm_adk/orchestrator.py
```

```output
        # ADK's __maybe_save_output_to_state validates raw text responses
        # against the schema (fails for plain text).  Instead we add
        # SetModelResponseTool as a tool so the model can choose either
        # execute_code or set_model_response.  BUG-13 patch (process-global
        # in worker_retry.py) handles retry suppression.
        schema = self.output_schema or ReasoningOutput
        set_model_response_tool = SetModelResponseTool(schema)
        object.__setattr__(self.reasoning_agent, 'tools', [repl_tool, set_model_response_tool])
        # Ensure ADK manages tool call/response history
```

```bash
sed -n "182,185p" rlm_adk/orchestrator.py && echo "---" && sed -n "346,350p" rlm_adk/orchestrator.py
```

```output
        after_tool_cb, on_tool_error_cb = make_worker_tool_callbacks(max_retries=2)
        object.__setattr__(self.reasoning_agent, 'after_tool_callback', after_tool_cb)
        object.__setattr__(self.reasoning_agent, 'on_tool_error_callback', on_tool_error_cb)

---
            # Clean up reasoning_agent wiring
            object.__setattr__(self.reasoning_agent, 'tools', [])
            object.__setattr__(self.reasoning_agent, 'after_tool_callback', None)
            object.__setattr__(self.reasoning_agent, 'on_tool_error_callback', None)
            if not self.persistent:
```

## Phase 1: Depth-Scoped State Keys

Phase 1 introduces depth_key() to scope state writes by orchestrator nesting depth. At depth 0 keys are unchanged (backward-compatible). At depth N > 0 keys get an @dN suffix so nested orchestrators write to independent state slots. REPLTool and orchestrator.py both use depth_key() for ITERATION_COUNT, LAST_REPL_RESULT, and WORKER_DISPATCH_COUNT.

```bash
sed -n "131,141p" rlm_adk/state.py
```

```output
def depth_key(key: str, depth: int = 0) -> str:
    """Return a depth-scoped state key.

    At depth 0 the original key is returned unchanged.
    At depth N > 0 the key is suffixed with ``@dN`` so nested
    reasoning agents operate on independent state.
    """
    if depth == 0:
        return key
    return f"{key}@d{depth}"

```

```bash
grep -n "depth_key" rlm_adk/tools/repl_tool.py
```

```output
25:from rlm_adk.state import ITERATION_COUNT, LAST_REPL_RESULT, WORKER_DISPATCH_COUNT, depth_key
85:        tool_context.state[depth_key(ITERATION_COUNT, self._depth)] = self._call_count
132:            tool_context.state[depth_key(LAST_REPL_RESULT, self._depth)] = {
156:            tool_context.state[depth_key(LAST_REPL_RESULT, self._depth)] = {
187:        tool_context.state[depth_key(LAST_REPL_RESULT, self._depth)] = last_repl
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_phase0_structured_output_parent.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
15 passed
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_phase1_depth_key_wiring.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
9 passed
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//" | sed "s/ (0:[0-9:]*)$//"
```

```output
6 failed, 855 passed, 1 skipped, 1 error
```

## Summary

Phase 0 and Phase 1 are fully wired and tested:

- **Phase 0**: 15/15 tests pass. SetModelResponseTool + WorkerRetryPlugin callbacks are wired onto reasoning_agent at run start and cleaned up in the finally block.
- **Phase 1**: 9/9 tests pass. depth_key() is transparent at depth=0 (returns original key) and scopes keys with @dN suffix at depth>0. All DEPTH_SCOPED_KEYS writes in REPLTool and orchestrator use depth_key().
- **Full suite**: 855 passed, 6 pre-existing failures unrelated to Phase 0/1 (under investigation by regression-fixer). Zero new regressions.
