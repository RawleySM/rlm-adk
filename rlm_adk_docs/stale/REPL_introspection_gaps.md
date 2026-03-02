# PLAN: Close REPL Introspection Gaps via Object-Carrier Pattern

## Problem Summary

7 confirmed gaps prevent introspection into the REPL's actual runtime behavior,
specifically the worker sub-LM calls that execute via `llm_query()` inside code blocks:

| Gap | Description | Root Cause |
|-----|-------------|------------|
| 1 | `REPLResult.llm_calls` always empty | `_pending_llm_calls` never appended to; dispatch closures have no REPL reference |
| 2 | Worker prompts discarded | `worker._pending_prompt = None` in finally block (dispatch.py:360) |
| 3 | Worker responses discarded | `worker._result = None` in finally block (dispatch.py:361) |
| 4 | Token counts never read | `worker._result_usage` populated but never consumed downstream |
| 5 | `format_execution_result()` drops variable values | Shows only names, not values (parsing.py:136) |
| 6 | `REPLResult.execution_time` unused | Populated but never read by orchestrator/formatting |
| 7 | `worker._result_error` cleared silently | Errors logged but not persisted in any structure |

## Constraint: Object-Carrier Pattern ONLY

**DO NOT** use `temp:` state relay. Three disqualifying problems:
1. Race condition under ParallelAgent (shared state dict)
2. Depends on ADK `State.__setitem__` dual-write (TODO to change)
3. Stripped at event drain by `_trim_temp_delta_state()`

## Architecture: Data Flow

```
worker_before_model         worker_after_model / on_error
    │                              │
    │  _pending_prompt             │  _call_record = {prompt, response, tokens, model, error}
    │  (already exists)            │  (NEW — on agent object)
    ▼                              ▼
┌─────────────────────────────────────────────────┐
│            dispatch closure                      │
│  llm_query_batched_async()                       │
│                                                  │
│  After ParallelAgent completes:                  │
│    for worker in workers:                        │
│      record = worker._call_record                │
│      if record: call_log_sink.append(record)     │
│                                                  │
│  finally: worker._call_record = None             │
└─────────────────────────────────────────────────┘
                    │
                    │ call_log_sink is repl._pending_llm_calls
                    ▼
┌─────────────────────────────────────────────────┐
│            LocalREPL.execute_code_async()         │
│                                                  │
│  _pending_llm_calls accumulates during exec      │
│  REPLResult.llm_calls = _pending_llm_calls.copy()│
└─────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  format_execution_result(result)                 │
│  Now includes: llm_calls summary + var values    │
│  → fed back into message_history for next iter   │
└─────────────────────────────────────────────────┘
```

## Key Design Decision: Closure → REPL Data Flow

The dispatch closure `llm_query_batched_async` is called from WITHIN REPL-executed code
(via AST-rewritten `await llm_query_async(prompt)`). The REPL creates `REPLResult`.

**Solution**: Pass a `call_log_sink: list` reference when creating dispatch closures.
The closure appends `RLMChatCompletion` records to this sink after each batch.
The orchestrator passes `repl._pending_llm_calls` as the sink.

This works because:
- `_pending_llm_calls` is reset at start of each `execute_code`/`execute_code_async`
- It's copied into `REPLResult.llm_calls` at the end
- The list reference is stable within a single code execution

## Implementation Steps

### Step 1: Add `_call_record` to worker callbacks (`rlm_adk/callbacks/worker.py`)

**worker_after_model** (line 71-106): After existing result carrier writes, add:
```python
agent._call_record = {
    "prompt": getattr(agent, "_pending_prompt", None),
    "response": response_text,
    "input_tokens": agent._result_usage["input_tokens"],
    "output_tokens": agent._result_usage["output_tokens"],
    "model": getattr(llm_response, "model_version", None),
    "error": False,
}
```

**worker_on_model_error** (line 109-133): After existing error writes, add:
```python
agent._call_record = {
    "prompt": getattr(agent, "_pending_prompt", None),
    "response": error_msg,
    "input_tokens": 0,
    "output_tokens": 0,
    "model": None,
    "error": True,
}
```

### Step 2: Initialize `_call_record` on worker creation (`rlm_adk/dispatch.py`)

**_create_worker** (line 128-134): Add after existing carrier attrs:
```python
worker._call_record = None  # type: ignore[attr-defined]
```

### Step 3: Accept `call_log_sink` in `create_dispatch_closures` (`rlm_adk/dispatch.py`)

**create_dispatch_closures** signature (line 201-225): Add parameter:
```python
def create_dispatch_closures(
    worker_pool: WorkerPool,
    ctx: InvocationContext,
    event_queue: asyncio.Queue[Event],
    call_log_sink: list | None = None,      # NEW
) -> tuple[Any, Any]:
```

**llm_query_batched_async** (after reading results from workers, ~line 327-342):
After the result-reading loop, add call_record accumulation:
```python
# Accumulate call records into sink for REPLResult.llm_calls
if call_log_sink is not None:
    for worker in workers:
        record = getattr(worker, "_call_record", None)
        if record:
            call_log_sink.append(RLMChatCompletion(
                root_model=record.get("model") or "unknown",
                prompt=record["prompt"] or "",
                response=record["response"],
                usage_summary=UsageSummary(model_usage_summaries={
                    (record.get("model") or "unknown"): ModelUsageSummary(
                        total_calls=1,
                        total_input_tokens=record["input_tokens"],
                        total_output_tokens=record["output_tokens"],
                    )
                }),
                execution_time=dispatch_elapsed_ms / 1000,
            ))
```

**finally block** (line 358-367): Add cleanup:
```python
worker._call_record = None  # type: ignore[attr-defined]
```

### Step 4: Wire `call_log_sink` from orchestrator → dispatch (`rlm_adk/orchestrator.py`)

**_run_async_impl** (~line 114-117): Pass REPL's accumulator:
```python
llm_query_async, llm_query_batched_async = create_dispatch_closures(
    self.worker_pool, ctx, event_queue,
    call_log_sink=repl._pending_llm_calls,  # NEW
)
```

### Step 5: Fix `format_execution_result()` to include variable values (`rlm_adk/utils/parsing.py`)

**format_execution_result** (line 111-141): Change variable display:
```python
# Before (Gap 5):
important_vars[key] = ""
# After:
str_val = repr(value)
if len(str_val) > 200:
    str_val = str_val[:200] + "..."
important_vars[key] = str_val
```

And update the format line:
```python
# Before:
result_parts.append(f"REPL variables: {list(important_vars.keys())}\n")
# After:
var_lines = [f"  {k} = {v}" for k, v in important_vars.items()]
result_parts.append("REPL variables:\n" + "\n".join(var_lines) + "\n")
```

### Step 6: Add llm_calls summary to format_execution_result (`rlm_adk/utils/parsing.py`)

After variable display, add worker call summary:
```python
if result.llm_calls:
    call_lines = []
    for call in result.llm_calls:
        prompt_preview = (call.prompt[:80] + "...") if isinstance(call.prompt, str) and len(call.prompt) > 80 else call.prompt
        resp_preview = call.response[:80] + "..." if len(call.response) > 80 else call.response
        tokens = call.usage_summary.model_usage_summaries
        total_in = sum(m.total_input_tokens for m in tokens.values())
        total_out = sum(m.total_output_tokens for m in tokens.values())
        call_lines.append(
            f"  [{call.root_model}] prompt={prompt_preview!r} → "
            f"response={resp_preview!r} (in={total_in}, out={total_out})"
        )
    result_parts.append("Worker LLM calls:\n" + "\n".join(call_lines) + "\n")
```

## Red/Green TDD Test Plan

### Test File: `tests_rlm_adk/test_call_record.py`

**Test 1 (RED→GREEN): worker_after_model writes _call_record**
- Create a mock LlmAgent with carrier attrs
- Call `worker_after_model` with a mock CallbackContext and LlmResponse
- Assert `agent._call_record` has correct prompt, response, tokens, model, error=False

**Test 2 (RED→GREEN): worker_on_model_error writes error _call_record**
- Same setup but call `worker_on_model_error`
- Assert `agent._call_record` has error=True, response=error_msg

**Test 3 (RED→GREEN): _call_record initialized on worker creation**
- Create WorkerPool, acquire worker
- Assert `worker._call_record is None`

**Test 4 (RED→GREEN): dispatch closure populates call_log_sink**
- Use a list as call_log_sink
- Run dispatch closure through a FakeGeminiServer with single worker call
- Assert call_log_sink has 1 RLMChatCompletion with correct fields

**Test 5 (RED→GREEN): format_execution_result includes variable values**
- Create REPLResult with locals={"x": 42, "name": "test"}
- Assert format output contains "x = 42" and "name = 'test'"

**Test 6 (RED→GREEN): format_execution_result includes llm_calls summary**
- Create REPLResult with populated llm_calls list
- Assert format output contains "Worker LLM calls:" and prompt/response previews

**Test 7 (RED→GREEN): E2E multi_iteration_with_workers populates llm_calls**
- Extend existing e2e test infrastructure or add contract assertion
- Run multi_iteration_with_workers fixture
- Assert the REPL execution path populated llm_calls (requires exposing iteration data)

### New Fixture: `tests_rlm_adk/fixtures/provider_fake/worker_call_record.json`

Dedicated fixture for testing call_record capture: single iteration with 2 worker calls,
then FINAL. Validates that both call records are captured with correct prompt/response/tokens.

## Import Changes

`rlm_adk/dispatch.py` needs:
```python
from rlm_adk.types import RLMChatCompletion, UsageSummary, ModelUsageSummary
```

## Risk Assessment

- **Low risk**: _call_record is a new attribute, doesn't interfere with existing carrier attrs
- **Low risk**: call_log_sink is optional (default None), backward compatible
- **Low risk**: format changes are additive (more info, not less)
- **No ADK internals touched**: All data flows on Python objects, not ADK state
