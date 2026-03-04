# FMEA Team E: Safety Filters & Empty Output

*2026-03-01T11:37:50Z by Showboat 0.6.0*
<!-- showboat-id: 9fd6ba1d-5f18-4003-9164-912398aa2104 -->

## FM-15: Empty reasoning_output (RPN=16, Pathway: P9)

**Failure Mode:** The reasoning agent returns an empty text response (no FINAL() marker, no
JSON, no content at all). This can happen when the model emits only thinking tokens, when
a safety filter strips the response, or when MAX_TOKENS truncation leaves nothing behind.

**Effect:** `find_final_answer("")` returns `None` because there is no text to parse.
The orchestrator detects the empty `final_answer` and yields a synthetic `[RLM ERROR]`
event with `SHOULD_STOP=True` — a graceful shutdown rather than an exception.

**Fixture:** `empty_reasoning_output.json` — two API calls:
1. `call_index=0` (reasoning): a normal `execute_code` function call (`x = 42`)
2. `call_index=1` (reasoning): an empty text response (`""`) with `finishReason=STOP`

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/empty_reasoning_output.json') as f:
    fixture = json.load(f)
for r in fixture['responses']:
    fc = r['body']['candidates'][0]['content']['parts'][0].get('functionCall')
    txt = r['body']['candidates'][0]['content']['parts'][0].get('text')
    fr = r['body']['candidates'][0].get('finishReason', '?')
    if fc:
        print(f'call_index={r[\"call_index\"]} ({r[\"caller\"]}): functionCall execute_code')
        print(f'  code: {fc[\"args\"][\"code\"]!r}')
    elif txt is not None:
        print(f'call_index={r[\"call_index\"]} ({r[\"caller\"]}): text={txt!r}  finishReason={fr}')
print()
print(f'Expected final_answer: {fixture[\"expected\"][\"final_answer\"]!r}')
print(f'Expected iterations:   {fixture[\"expected\"][\"total_iterations\"]}')
print(f'Expected model_calls:  {fixture[\"expected\"][\"total_model_calls\"]}')
"

```

```output
call_index=0 (reasoning): functionCall execute_code
  code: 'x = 42\nprint(f"x = {x}")'
call_index=1 (reasoning): text=''  finishReason=STOP

Expected final_answer: '[RLM ERROR] Reasoning agent completed without producing a structured final answer. Check output_schema wiring.'
Expected iterations:   1
Expected model_calls:  2
```

### Fixture anatomy: `empty_reasoning_output.json`

The fixture has exactly 2 mocked API responses:

- **call_index=0** (reasoning): The model emits a normal `functionCall` for `execute_code`
  with trivial code `x = 42; print(...)`. This succeeds — REPL iteration count goes to 1.
- **call_index=1** (reasoning): The model returns `text=""` with `finishReason=STOP`.
  ADK writes `""` into the output_key `reasoning_output`. The orchestrator then reads
  the empty string: `find_final_answer("")` returns `None`, `json.loads("")` raises
  `JSONDecodeError`, and the plain-text fallback is also empty.

The key insight: the model *did* call REPL once (so `ITERATION_COUNT=1`), but its
final response contained no extractable answer. The orchestrator must detect this
and emit a structured error — not crash, not silently return nothing.

```bash
grep -n "reasoning_output\|find_final_answer\|final_answer\|RLM ERROR\|SHOULD_STOP" rlm_adk/orchestrator.py
```

```output
6:2. Wires the reasoning_agent with tools=[REPLTool] (output_key="reasoning_output")
10:5. Extracts the final_answer from the output_key ("reasoning_output")
28:from rlm_adk.artifacts import save_final_answer
42:    SHOULD_STOP,
46:from rlm_adk.utils.parsing import find_final_answer
166:        # the final answer from the output_key ("reasoning_output") which ADK
228:            # --- Extract final_answer from output_key ---
232:            raw = ctx.session.state.get("reasoning_output", "")
233:            final_answer = ""
236:                final_answer = raw.get("final_answer", "")
242:                        final_answer = parsed.get("final_answer", raw)
244:                        final_answer = raw
247:                    parsed_final = find_final_answer(raw)
249:                        final_answer = parsed_final
252:                        final_answer = raw
254:            if final_answer:
256:                    f"[RLM] FINAL_ANSWER detected length={len(final_answer)}",
261:                await save_final_answer(ctx, answer=final_answer)
267:                        FINAL_ANSWER: final_answer,
268:                        SHOULD_STOP: True,
277:                        parts=[types.Part.from_text(text=final_answer)],
284:                    "Reasoning agent completed without a final_answer in output_key"
287:                    "[RLM ERROR] Reasoning agent completed without producing "
295:                        SHOULD_STOP: True,
```

### Error handling path in `orchestrator.py`

The critical path (lines 232-305) works as follows:

1. **Line 232:** `raw = ctx.session.state.get("reasoning_output", "")` — reads the ADK
   output_key. For this fixture, `raw` is `""` (the empty string from call_index=1).

2. **Lines 234-252:** The three-branch extraction cascade:
   - `isinstance(raw, dict)` → False (it is a string)
   - `json.loads("")` → raises `JSONDecodeError` → falls to the except branch
   - `find_final_answer("")` → returns `None` (no `FINAL()` marker found)
   - Fallback: `final_answer = raw` → still `""`

3. **Line 254:** `if final_answer:` → `""` is falsy, so we enter the `else` branch.

4. **Lines 286-305:** The `else` branch yields a synthetic error event:
   - `FINAL_ANSWER = "[RLM ERROR] Reasoning agent completed without producing a structured final answer. Check output_schema wiring."`
   - `SHOULD_STOP = True`
   - A content event with the error message is also yielded.

This is a **graceful degradation** — the caller gets a structured error, not an exception.

```bash
sed -n "280,305p" rlm_adk/orchestrator.py
```

```output
            else:
                # No final answer extracted -- reasoning agent may not have
                # produced a valid ReasoningOutput
                logger.warning(
                    "Reasoning agent completed without a final_answer in output_key"
                )
                exhausted_msg = (
                    "[RLM ERROR] Reasoning agent completed without producing "
                    "a structured final answer. Check output_schema wiring."
                )
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={
                        FINAL_ANSWER: exhausted_msg,
                        SHOULD_STOP: True,
                    }),
                )
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=exhausted_msg)],
                    ),
                )
```

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput -q 2>&1 | grep -E "passed|PASSED|FAILED|ERROR" | sed "s/ in [0-9.]*s//"
```

```output
3 passed, 7 warnings
```

### FM-15 Summary

All 3 tests pass:
- `test_contract` — validates final_answer, iterations (1), and model_calls (2)
- `test_error_message_format` — confirms FINAL_ANSWER starts with `[RLM ERROR]` and
  mentions `output_schema`
- `test_single_repl_iteration` — confirms exactly 1 REPL call before the empty output

**Key finding:** The orchestrator's empty-output guard (lines 280-305) is exercised
and correctly produces a structured `[RLM ERROR]` event rather than silently returning
nothing or raising an exception. The `SHOULD_STOP=True` flag ensures the Runner
terminates the session cleanly.

**Risk assessment (RPN=16):** Low risk, well-handled. The only residual concern is
that the error message is generic — it does not indicate *why* the response was empty
(safety filter, MAX_TOKENS, or model choice). A future improvement could inspect
`finishReason` from the last LlmResponse to provide a more specific diagnostic.

---

## FM-24/25: Worker SAFETY Finish Reason (RPN=48/75, Pathway: P6d)

**Failure Modes:**
- **FM-24** (RPN=48): Reasoning agent receives a SAFETY-filtered response — but in
  this fixture, the SAFETY filter hits the *worker*, not the reasoning agent itself.
- **FM-25** (RPN=75): Worker response has `finishReason=SAFETY` with empty content.
  `worker_after_model` extracts `""` as the response text. The dispatch closure creates
  an `LLMResult("")` with `error=False` — the empty result is treated as a valid
  (but vacuous) response, not an error.

**Effect:** REPL code receives an empty string from `llm_query()`. If the REPL code
does not check for empty results, it may silently proceed with incorrect data.
In this fixture, the REPL code explicitly checks `if not str(result).strip()` and
reports the safety-filtered result.

**Fixture:** `worker_safety_finish.json` — three API calls:
1. `call_index=0` (reasoning): `execute_code` with `llm_query("Generate content")`
2. `call_index=1` (worker): empty text response with `finishReason=SAFETY`
3. `call_index=2` (reasoning): model observes the REPL output and emits `FINAL()`

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/worker_safety_finish.json') as f:
    fixture = json.load(f)
for r in fixture['responses']:
    fc = r['body']['candidates'][0]['content']['parts'][0].get('functionCall')
    txt = r['body']['candidates'][0]['content']['parts'][0].get('text')
    fr = r['body']['candidates'][0].get('finishReason', '?')
    caller = r['caller']
    ci = r['call_index']
    if fc:
        print(f'call_index={ci} ({caller}): functionCall execute_code')
        print(f'  code: {fc[\"args\"][\"code\"]!r}')
    elif txt is not None:
        trunc = txt[:80] + '...' if len(txt) > 80 else txt
        print(f'call_index={ci} ({caller}): text={trunc!r}  finishReason={fr}')
print()
print(f'Expected final_answer: {fixture[\"expected\"][\"final_answer\"]!r}')
print(f'Expected iterations:   {fixture[\"expected\"][\"total_iterations\"]}')
print(f'Expected model_calls:  {fixture[\"expected\"][\"total_model_calls\"]}')
"

```

```output
call_index=0 (reasoning): functionCall execute_code
  code: 'result = llm_query("Generate content")\nif not str(result).strip():\n    print("Worker returned empty (safety filtered)")\nelse:\n    print(f"Got: {result}")'
call_index=1 (worker): text=''  finishReason=SAFETY
call_index=2 (reasoning): text='The worker query was blocked by the safety filter and returned empty content.\n\nF...'  finishReason=STOP

Expected final_answer: 'Worker returned empty (safety filtered)'
Expected iterations:   1
Expected model_calls:  3
```

### Fixture anatomy: `worker_safety_finish.json`

Three mocked API responses trace the full pathway:

1. **call_index=0** (reasoning): The model calls `execute_code` with REPL code that
   dispatches a worker via `llm_query("Generate content")` and then checks the result.
   The code explicitly branches on `not str(result).strip()` to detect an empty response.

2. **call_index=1** (worker): The worker response has `text=""` and
   `finishReason=SAFETY`. This simulates Gemini's safety filter blocking the generated
   content entirely. The `worker_after_model` callback extracts `""` and writes it as
   `agent._result`. Critically, `_result_error` is NOT set — an empty SAFETY response
   is indistinguishable from a legitimate empty answer at the dispatch level.

3. **call_index=2** (reasoning): The model sees stdout `"Worker returned empty
   (safety filtered)"` and produces `FINAL(Worker returned empty (safety filtered))`.

The fixture proves that REPL-level defensive coding (checking for empty results)
is currently the *only* protection against safety-filtered worker responses.

```bash
sed -n "63,108p" rlm_adk/callbacks/worker.py
```

```output
def worker_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract response text, write to state output_key and agent object.

    Writes result onto the agent object (_result, _result_ready, _call_record)
    for the dispatch closure to read after ParallelAgent completes.
    Also writes to callback_context.state[output_key] for ADK persistence.
    """
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    agent = callback_context._invocation_context.agent

    # Write result onto agent object for dispatch closure reads
    agent._result = response_text  # type: ignore[attr-defined]
    agent._result_ready = True  # type: ignore[attr-defined]

    # Extract usage from response metadata
    usage = llm_response.usage_metadata
    input_tokens = 0
    output_tokens = 0
    if usage:
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    # Write call record onto agent object for dispatch closure to accumulate
    agent._call_record = {  # type: ignore[attr-defined]
        "prompt": getattr(agent, "_pending_prompt", None),
        "response": response_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": getattr(llm_response, "model_version", None),
        "finish_reason": str(llm_response.finish_reason) if llm_response.finish_reason else None,
        "error": False,
    }

    # Write to the worker's output_key in state (for ADK persistence)
    output_key = getattr(agent, "output_key", None)
    if output_key:
        callback_context.state[output_key] = response_text

    return None
```

### Error handling path in `callbacks/worker.py`

The `worker_after_model` callback (lines 63-108) processes ALL worker responses
including safety-filtered ones:

1. **Lines 73-76:** Text extraction joins all non-thought parts. For a SAFETY finish,
   `llm_response.content.parts[0].text` is `""`, so `response_text = ""`.

2. **Lines 81-82:** The empty string is written to `agent._result` and
   `agent._result_ready = True`. No error flag is set.

3. **Lines 93-101:** The call record is written with `"error": False` and
   `"finish_reason": "SAFETY"`. The `finish_reason` is recorded but NOT used to
   flag the result as an error.

**This is the core of FM-25 (RPN=75):** An empty SAFETY response is treated as a
successful result. The dispatch closure wraps it in `LLMResult("")` with `error=False`.
REPL code that does `result = llm_query(...)` gets an empty string that is truthy
as an `LLMResult` (it is a `str` subclass), but `str(result).strip()` is falsy.

Compare with `worker_on_model_error` (lines 111-147) which DOES set `_result_error=True`
— but that callback only fires for HTTP errors, not for safety-filtered 200 responses.

```bash
grep -n "_result_error\|error.*True\|_classify_error" rlm_adk/callbacks/worker.py
```

```output
22:def _classify_error(error: Exception) -> str:
127:    agent._result_error = True  # type: ignore[attr-defined]
137:        "error": True,
138:        "error_category": _classify_error(error),
```

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorkerSafetyFinish -q 2>&1 | grep -E "passed|PASSED|FAILED|ERROR" | sed "s/ in [0-9.]*s//"
```

```output
4 passed, 13 warnings
```

### FM-24/25 Summary

All 4 tests pass:
- `test_contract` — validates final_answer matches `"Worker returned empty (safety filtered)"`,
  iterations=1, model_calls=3
- `test_safety_detected_in_final_answer` — confirms `"safety filtered"` appears in FINAL_ANSWER
- `test_single_iteration` — confirms the safety-filtered response was handled in 1 REPL iteration
  (no retry loop)
- `test_worker_dispatch_counted` — confirms WORKER_DISPATCH_COUNT >= 1 (the safety-filtered
  worker still counts as a dispatch)

**Key finding:** The `worker_after_model` callback does NOT flag SAFETY-finished responses
as errors. The call record has `"error": False` and `"finish_reason": "SAFETY"`, but the
`LLMResult` wrapper does not expose the finish_reason to REPL code. This means:

1. **REPL code must defensively check for empty results.** The fixture demonstrates
   this pattern: `if not str(result).strip():` — but production REPL code generated by
   the reasoning agent may not always include this check.

2. **The `finish_reason` is recorded but never surfaced.** The call record captures
   `"finish_reason": "SAFETY"` for observability, but `LLMResult` (a `str` subclass)
   has no `.finish_reason` attribute accessible to REPL code.

3. **Potential improvement (FM-25, RPN=75):** The `worker_after_model` callback could
   detect `finishReason=SAFETY` and set `_result_error=True` with
   `error_category="SAFETY"`, making the empty response distinguishable from a legitimate
   empty answer. This would allow `LLMResult.error` to be `True` for safety-filtered
   responses, giving REPL code a reliable signal.

---

## Combined Run: Both Fixture Test Classes

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput tests_rlm_adk/test_fmea_e2e.py::TestWorkerSafetyFinish -v 2>&1 | grep -E "PASSED|FAILED|ERROR|passed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_contract PASSED [ 14%]
tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_error_message_format PASSED [ 28%]
tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_single_repl_iteration PASSED [ 42%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerSafetyFinish::test_contract PASSED [ 57%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerSafetyFinish::test_safety_detected_in_final_answer PASSED [ 71%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerSafetyFinish::test_single_iteration PASSED [ 85%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerSafetyFinish::test_worker_dispatch_counted PASSED [100%]
======================== 7 passed, 19 warnings ========================
```

## Team E Conclusions

**7/7 tests pass** across both fixtures.

| Fixture | FM | RPN | Tests | Status |
|---|---|---|---|---|
| `empty_reasoning_output.json` | FM-15 | 16 | 3 | PASS |
| `worker_safety_finish.json` | FM-24/25 | 48/75 | 4 | PASS |

### Observations

1. **FM-15 (Empty reasoning_output)** has robust handling: the orchestrator's
   `else` branch (lines 280-305) catches the empty output and emits a structured
   `[RLM ERROR]` event. RPN=16 is appropriate — low occurrence, high detection.

2. **FM-25 (Worker SAFETY finish)** has a higher residual risk (RPN=75) because
   the empty result passes through `worker_after_model` as `error=False`. The
   defense relies entirely on REPL code checking for empty strings — a pattern
   the reasoning model must learn, not one enforced by the framework.

3. **Gap for future work:** `worker_after_model` could inspect `llm_response.finish_reason`
   and flag `SAFETY`/`MAX_TOKENS` finishes as soft errors on the `LLMResult` object,
   giving REPL code a reliable `.safety_filtered` or `.truncated` attribute to check.

