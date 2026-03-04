# FMEA Team D: Structured Output & Iteration Limits

*2026-03-01T11:37:40Z by Showboat 0.6.0*
<!-- showboat-id: 4f561ccd-5a00-4a1a-ae96-3313b39619c1 -->

## FM-17: Structured Output Batched K>1 (RPN=90, Pathway: P6g)

**Failure Mode:** Multiple concurrent workers each wire `SetModelResponseTool` + `WorkerRetryPlugin` simultaneously when `llm_query_batched(prompts, output_schema=Schema)` dispatches K>1 workers.

**Risk:** The BUG-13 monkey-patch on `_output_schema_processor.get_structured_model_response()` is **process-global**. All K concurrent workers share the same patched function. If the patch fails or is absent, workers terminate prematurely on retry-guidance responses, breaking structured output validation for the entire batch.

**Fixture:** `structured_output_batched_k3.json` — 3 parallel workers with `SentimentResult` schema.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/structured_output_batched_k3.json') as f:
    fixture = json.load(f)

for resp in fixture['responses']:
    fc = resp['body']['candidates'][0]['content']['parts'][0].get('functionCall')
    if fc and fc['name'] == 'execute_code':
        print('=== REPL code from fixture (call_index={}) ==='.format(resp['call_index']))
        print(fc['args']['code'])
        print()

for resp in fixture['responses']:
    fc = resp['body']['candidates'][0]['content']['parts'][0].get('functionCall')
    if fc and fc['name'] == 'set_model_response':
        print('Worker (call_index={}): set_model_response -> {}'.format(
            resp['call_index'], json.dumps(fc['args'])))

print()
print('Expected final_answer:', fixture['expected']['final_answer'])
print('Expected total_model_calls:', fixture['expected']['total_model_calls'])
"

```

```output
=== REPL code from fixture (call_index=0) ===
from pydantic import BaseModel

class SentimentResult(BaseModel):
    sentiment: str
    confidence: float

prompts = ["Review: Great product!", "Review: Terrible quality", "Review: Love it!"]
results = llm_query_batched(prompts, output_schema=SentimentResult)
positive = sum(1 for r in results if r.parsed and r.parsed.get("sentiment") == "positive")
negative = sum(1 for r in results if r.parsed and r.parsed.get("sentiment") == "negative")
print(f"Results: {positive} positive, {negative} negative")
for i, r in enumerate(results):
    print(f"  Review {i+1}: {r.parsed}")

Worker (call_index=1): set_model_response -> {"sentiment": "positive", "confidence": 0.95}
Worker (call_index=2): set_model_response -> {"sentiment": "negative", "confidence": 0.88}
Worker (call_index=3): set_model_response -> {"sentiment": "positive", "confidence": 0.92}

Expected final_answer: 3 sentiments: 2 positive, 1 negative
Expected total_model_calls: 5
```

### Fixture Anatomy

The fixture scripts a 5-call conversation:

1. **call_index=0 (reasoning):** Emits `execute_code` with REPL code that defines a `SentimentResult` Pydantic schema and calls `llm_query_batched(prompts, output_schema=SentimentResult)` with K=3.
2. **call_index=1-3 (workers):** Each worker responds with `set_model_response` containing `{"sentiment": ..., "confidence": ...}` — the ADK structured output pathway.
3. **call_index=4 (reasoning):** Sees aggregated results (2 positive, 1 negative) and returns `FINAL(...)`.

The critical path: K=3 means `dispatch.py` creates a `ParallelAgent` with 3 sub-agents, each independently wired with `SetModelResponseTool` + `WorkerRetryPlugin`. All 3 run concurrently through the same BUG-13-patched postprocessor.

```bash
echo "=== dispatch.py: Structured output wiring (per-worker) ===" && sed -n "362,371p" rlm_adk/dispatch.py && echo && echo "=== dispatch.py: ParallelAgent creation for K>1 ===" && sed -n "384,400p" rlm_adk/dispatch.py
```

```output
=== dispatch.py: Structured output wiring (per-worker) ===

                    # Wire structured output when output_schema provided.
                    if output_schema is not None:
                        worker.output_schema = output_schema
                        worker.tools = [SetModelResponseTool(output_schema)]  # type: ignore[list-item]
                        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
                        worker.after_tool_callback = after_cb  # type: ignore[assignment]
                        worker.on_tool_error_callback = error_cb  # type: ignore[assignment]
                        worker._structured_result = None  # type: ignore[attr-defined]


=== dispatch.py: ParallelAgent creation for K>1 ===
                else:
                    parallel = ParallelAgent(
                        name=f"batch_{batch_num}_{len(workers)}",
                        sub_agents=list(workers),  # type: ignore[arg-type]
                    )
                    try:
                        await asyncio.wait_for(
                            _consume_events(parallel.run_async(ctx)),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        for w in workers:
                            if not getattr(w, '_result_ready', False):
                                w._result = f"[Worker {w.name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
                                w._result_ready = True  # type: ignore[attr-defined]
                                w._result_error = True  # type: ignore[attr-defined]

```

```bash
echo "=== worker_retry.py: BUG-13 process-global monkey-patch ===" && sed -n "160,201p" rlm_adk/callbacks/worker_retry.py
```

```output
=== worker_retry.py: BUG-13 process-global monkey-patch ===


def _patch_output_schema_postprocessor() -> None:
    """Install a retry-aware wrapper around get_structured_model_response.

    Idempotent — safe to call multiple times.
    """
    import google.adk.flows.llm_flows._output_schema_processor as _osp

    # Guard against double-patching
    if getattr(_osp.get_structured_model_response, "_rlm_patched", False):
        return

    _original = _osp.get_structured_model_response

    def _retry_aware_get_structured_model_response(
        function_response_event,
    ) -> str | None:
        result = _original(function_response_event)
        if result is None:
            return None
        try:
            parsed = _json.loads(result)
        except (ValueError, TypeError):
            return result
        if (
            isinstance(parsed, dict)
            and parsed.get("response_type") == REFLECT_AND_RETRY_RESPONSE_TYPE
        ):
            logger.debug(
                "BUG-13 patch: suppressing postprocessor for ToolFailureResponse"
            )
            return None
        return result

    _retry_aware_get_structured_model_response._rlm_patched = True  # type: ignore[attr-defined]
    _osp.get_structured_model_response = _retry_aware_get_structured_model_response


# Apply the patch at import time so it is active before any worker dispatch.
_patch_output_schema_postprocessor()
```

### How Structured Output K>1 Works

**Per-worker wiring (dispatch.py lines 364-370):** When `output_schema` is provided, each worker gets:
- `worker.output_schema = SentimentResult` (the Pydantic model)
- `worker.tools = [SetModelResponseTool(SentimentResult)]` -- ADK's built-in tool that validates JSON against the schema
- `worker.after_tool_callback` and `worker.on_tool_error_callback` from `make_worker_tool_callbacks()` -- the `WorkerRetryPlugin` callbacks that detect empty fields and trigger reflection/retry

**ParallelAgent dispatch (dispatch.py lines 385-388):** For K=3, a `ParallelAgent` wraps all 3 workers and runs them concurrently via `asyncio.wait_for`.

**BUG-13 patch (worker_retry.py lines 162-200):** This is the critical piece. ADK's `_output_schema_processor.get_structured_model_response()` terminates a worker's agent loop whenever it sees a `set_model_response` function response -- even if that response is a retry-guidance `ToolFailureResponse`. The monkey-patch intercepts the call, checks for the `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel, and returns `None` to suppress premature termination.

**Residual risk:** The patch is process-global -- installed once at import time via `_patch_output_schema_postprocessor()`. All K=3 concurrent workers share the same patched function. This is safe under Python's GIL for CPython (asyncio is single-threaded), but if ADK ever changes to multi-process workers, the patch would need to be applied per-process.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3 -q --no-header -p no:warnings 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
4 passed
```

### FM-17 Results

All 4 tests pass:
- `test_contract` -- basic fixture contract (final_answer, iterations, model_calls)
- `test_all_workers_produced_results` -- `WORKER_DISPATCH_COUNT == 3`, final_answer contains "2 positive" and "1 negative"
- `test_with_plugins_no_crash` -- full plugin stack (observability + sqlite + repl tracing) runs without error; REPL snapshots contain `trace_summary`
- `test_tool_result_marks_llm_calls` -- `function_response` has `llm_calls_made=True`

**Conclusion:** The process-global BUG-13 patch correctly handles K=3 concurrent structured-output workers. Each worker independently validates its `set_model_response` against the `SentimentResult` schema, the `WorkerRetryPlugin` callbacks capture `_structured_result` on each worker agent, and the dispatch closure reads `result.parsed` to provide the aggregated dict to REPL code.

---

## FM-03: REPLTool Call Limit Exceeded (RPN=30, Pathway: P2d)

**Failure Mode:** The model keeps calling `execute_code` beyond the configured `max_calls` limit. The `REPLTool` returns `_CALL_LIMIT_MSG` in stderr but does not enforce a hard stop -- the limit is advisory.

**Risk:** If the model ignores the limit message and keeps calling `execute_code`, it enters an infinite loop. ADK has no built-in tool-call ceiling, so the only safeguard is the model obeying the stderr guidance.

**Fixture:** `max_iterations_exceeded.json` -- `max_calls=2`, model makes 3 `execute_code` calls, gets limit message on the 3rd, then produces `FINAL`.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/max_iterations_exceeded.json') as f:
    fixture = json.load(f)

print('Config: max_iterations={}, max_retries={}'.format(
    fixture['config']['max_iterations'], fixture['config'].get('max_retries', 'default')))
print()

for resp in fixture['responses']:
    parts = resp['body']['candidates'][0]['content']['parts'][0]
    fc = parts.get('functionCall')
    text = parts.get('text')
    if fc:
        print('call_index={} ({}): execute_code -> {!r}'.format(
            resp['call_index'], resp['caller'], fc['args']['code'][:60]))
    elif text:
        print('call_index={} ({}): text -> {!r}'.format(
            resp['call_index'], resp['caller'], text[:80]))
print()
print('Expected final_answer:', fixture['expected']['final_answer'])
print('Expected total_iterations:', fixture['expected']['total_iterations'])
print('Expected total_model_calls:', fixture['expected']['total_model_calls'])
"

```

```output
Config: max_iterations=2, max_retries=0

call_index=0 (reasoning): execute_code -> 'x = 10\nprint(f"x = {x}")'
call_index=1 (reasoning): execute_code -> 'y = x + 20\nprint(f"y = {y}")'
call_index=2 (reasoning): execute_code -> 'print(f"result: {y}")'
call_index=3 (reasoning): text -> 'I have reached the REPL call limit. Based on the computations so far, x=10 and y'

Expected final_answer: Completed with limit
Expected total_iterations: 3
Expected total_model_calls: 4
```

### Fixture Anatomy

The fixture scripts a 4-call conversation with `max_iterations=2` (wired as `max_calls` on REPLTool):

1. **call_index=0:** `execute_code` with `x = 10` (call_count=1, within limit)
2. **call_index=1:** `execute_code` with `y = x + 20` (call_count=2, at limit)
3. **call_index=2:** `execute_code` with `print(...)` (call_count=3, exceeds limit -- gets `_CALL_LIMIT_MSG` in stderr instead of executing)
4. **call_index=3:** Text response -- model acknowledges limit and returns `FINAL(Completed with limit)`

Key: The 3rd `execute_code` call is not blocked at the ADK level -- REPLTool still increments `_call_count` and `ITERATION_COUNT`, but returns the limit message instead of executing the code. The model must decide to stop.

```bash
echo "=== repl_tool.py: _CALL_LIMIT_MSG constant ===" && grep -n "_CALL_LIMIT_MSG" rlm_adk/tools/repl_tool.py && echo && echo "=== repl_tool.py: Call limit check in run_async ===" && sed -n "80,91p" rlm_adk/tools/repl_tool.py
```

```output
=== repl_tool.py: _CALL_LIMIT_MSG constant ===
27:_CALL_LIMIT_MSG = "REPL call limit reached. Submit your final answer now."
87:                "stderr": _CALL_LIMIT_MSG,

=== repl_tool.py: Call limit check in run_async ===

        self._call_count += 1
        # Track iteration count in session state for observability
        tool_context.state[ITERATION_COUNT] = self._call_count
        if self._call_count > self._max_calls:
            return {
                "stdout": "",
                "stderr": _CALL_LIMIT_MSG,
                "variables": {},
                "llm_calls_made": False,
                "call_number": self._call_count,
            }
```

### How the Call Limit Works

**`repl_tool.py` line 27:** The limit message is a constant: `"REPL call limit reached. Submit your final answer now."`

**`repl_tool.py` lines 81-91:** On every `run_async` call:
1. `_call_count` is incremented unconditionally
2. `ITERATION_COUNT` is written to `tool_context.state` (observability tracking)
3. If `_call_count > _max_calls`, the tool returns immediately with `_CALL_LIMIT_MSG` in `stderr` -- no code is executed

**The advisory nature:** The tool returns a dict with `stderr` containing the limit message, but it does not raise an exception, set `end_invocation`, or signal ADK to stop the agent loop. The model receives the limit message as a normal `function_response` and must choose to stop calling the tool. If the model ignores the message, it can call `execute_code` indefinitely -- each call will increment `_call_count` and return the same limit message.

**Design trade-off:** A hard stop (e.g., raising an exception or setting `end_invocation=True`) would prevent the model from producing a `FINAL(...)` answer. The advisory approach lets the model gracefully wrap up with a final answer that acknowledges the limit.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestMaxIterationsExceeded -q --no-header -p no:warnings 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
4 passed
```

### FM-03 Results

All 4 tests pass:
- `test_contract` -- basic fixture contract (final_answer, iterations, model_calls)
- `test_limit_enforced` -- `ITERATION_COUNT == 3` (the blocked call is still counted)
- `test_limit_message_in_stderr` -- third `function_response` contains "REPL call limit reached" in stderr
- `test_final_answer_acknowledges_limit` -- `FINAL_ANSWER` contains "Completed with limit"

**Conclusion:** The advisory call limit works as designed. The 3rd call is blocked (code not executed), the model receives the limit message, and it produces a graceful final answer. The test validates the full chain: `_call_count` tracking, `_CALL_LIMIT_MSG` delivery, `ITERATION_COUNT` state write, and model compliance.

**Open residual risk:** If the model does not comply (keeps calling `execute_code`), there is no hard stop. Each subsequent call will return the same limit message and increment `ITERATION_COUNT`. Mitigation would require either ADK-level `max_tool_calls` support or setting `end_invocation=True` in the tool response EventActions.

