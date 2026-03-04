# FMEA Team H: Structured Output, Callback & Response Errors

*2026-03-01 by Showboat 0.6.0*

## FM-16: Structured Output Retry Exhaustion (RPN=50, Pathway: P6g)

**Failure Mode:** During structured output dispatch (`llm_query("prompt", output_schema=Schema)`),
the worker fails schema validation on all retry attempts (max_retries=2). The
`ReflectAndRetryToolPlugin` exhausts retries and the last attempt's partial/invalid
result is accepted as the worker's final output.

**Risk:** RPN=50. When retries exhaust, `_structured_result` on the worker may remain
`None` (no successful `set_model_response` ever fired), meaning `LLMResult.parsed`
will be `None`. The REPL code receives a text-only result string with no validated
schema data. If the code blindly accesses `.parsed["field"]`, it raises `TypeError`.

**Source Code Inspection:**

The retry pipeline has three key components: the `WorkerRetryPlugin` that detects
empty values, the `make_worker_tool_callbacks` that wires capture and retry logic
onto each worker, and the dispatch result-reading code that extracts structured
results.

```
=== WorkerRetryPlugin.extract_error_from_result (rlm_adk/callbacks/worker_retry.py:46-66) ===
```

```python
    async def extract_error_from_result(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[dict[str, Any]]:
        """Detect empty responses in set_model_response tool output."""
        if tool.name != "set_model_response":
            return None

        # Check if any value in the tool args is empty
        for key, value in tool_args.items():
            if isinstance(value, str) and not value.strip():
                return {
                    "error": "Empty value",
                    "details": f"Empty string for field '{key}'. The response must contain meaningful content.",
                }

        return None
```

```
=== make_worker_tool_callbacks after_tool_cb (rlm_adk/callbacks/worker_retry.py:91-118) ===
```

```python
    async def after_tool_cb(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: Any,
    ) -> Optional[dict[str, Any]]:
        """After-tool callback: capture structured result, delegate to plugin."""
        # On set_model_response success, store validated dict on the agent
        if tool.name == "set_model_response" and isinstance(tool_response, dict):
            agent = tool_context._invocation_context.agent
            agent._structured_result = tool_response  # type: ignore[attr-defined]
            logger.debug(
                "Captured structured result on %s: %s",
                getattr(agent, "name", "?"),
                list(tool_response.keys()),
            )

        # Delegate to plugin for extract_error_from_result checks
        return await plugin.after_tool_callback(
            tool=tool, tool_args=args,
            tool_context=tool_context, result=tool_response,
        )
```

```
=== Dispatch result reading (rlm_adk/dispatch.py:424-439) ===
```

```python
                    else:
                        # Extract structured result if available
                        structured = getattr(worker, "_structured_result", None)
                        if structured is not None:
                            result_text = json.dumps(structured)
                        else:
                            result_text = worker._result  # type: ignore[attr-defined]
                        all_results.append(LLMResult(
                            result_text,
                            error=False,
                            finish_reason=record.get("finish_reason"),
                            input_tokens=record.get("input_tokens", 0),
                            output_tokens=record.get("output_tokens", 0),
                            model=record.get("model"),
                            parsed=structured,
                        ))
```

```
=== Structured output wiring in dispatch (rlm_adk/dispatch.py:363-370) ===
```

```python
                    # Wire structured output when output_schema provided.
                    if output_schema is not None:
                        worker.output_schema = output_schema
                        worker.tools = [SetModelResponseTool(output_schema)]  # type: ignore[list-item]
                        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
                        worker.after_tool_callback = after_cb  # type: ignore[assignment]
                        worker.on_tool_error_callback = error_cb  # type: ignore[assignment]
                        worker._structured_result = None  # type: ignore[attr-defined]
```

**How the code handles FM-16:**

1. **Retry wiring:** When `output_schema` is provided, `dispatch.py` (lines 363-370)
   wires `SetModelResponseTool`, `WorkerRetryPlugin`-backed callbacks, and initializes
   `_structured_result = None` on the worker. The `make_worker_tool_callbacks(max_retries=2)`
   creates a fresh plugin instance per worker with a 2-retry budget.

2. **Soft error detection:** `WorkerRetryPlugin.extract_error_from_result()` (line 46-66)
   checks each field in the `set_model_response` tool args for empty strings. If found,
   it returns an error dict that triggers the parent `ReflectAndRetryToolPlugin` to
   decrement the retry counter and return reflection guidance to the model.

3. **Hard error handling:** `on_tool_error_cb` (lines 120-140) intercepts `ValueError`
   / `ValidationError` from `SetModelResponseTool` and delegates to the plugin. On
   first retry attempt, it returns reflection guidance. After `max_retries` exhausted,
   it re-raises the exception.

4. **Result extraction on exhaustion:** When retries exhaust, the worker completes
   via `worker_after_model` (which reads the final text response). The dispatch
   result-reading code at line 426 checks `_structured_result`. Since no successful
   `set_model_response` fired, `_structured_result` remains `None`. The code falls
   through to `result_text = worker._result` (line 430), producing an `LLMResult`
   with `parsed=None` and `error=False`. **This is the core gap**: the result is
   marked as success (`error=False`) even though structured validation failed.

5. **No error flag on exhausted retries:** The `LLMResult` does not carry any
   indication that structured output validation was attempted and failed. REPL code
   that calls `result.parsed["field"]` will get a `TypeError: 'NoneType' is not subscriptable`.

**Testability Assessment:** Provider-fake e2e testable. A fixture can script 3
worker API calls (initial + 2 retries) where each `set_model_response` functionCall
has empty/invalid args. The test asserts `result.parsed is None` and verifies
`error=False` (current behavior) or `error=True` (if fixed). Unit tests exist in
`test_adk_worker_retry.py` (classes `TestWorkerRetryPlugin`, `TestMakeWorkerToolCallbacks`)
covering individual retry mechanics, but no e2e fixture exercises the full exhaustion path.

**Recommended Test Scenario:** `structured_output_retry_exhaustion.json` fixture:
- call 0: reasoning emits `execute_code` with `llm_query("prompt", output_schema=Schema)`
- call 1: worker returns `set_model_response` with empty `summary` field (retry 1)
- call 2: worker returns `set_model_response` with empty `summary` field (retry 2)
- call 3: worker returns `set_model_response` with empty `summary` field (retry exhausted)
- call 4: reasoning sees result, returns FINAL
- Assert: `LLMResult.parsed is None`, REPL code handles gracefully

**Gaps:**
- No e2e fixture exercises the retry-exhausted code path end-to-end
- `LLMResult` does not signal `error=True` when `_structured_result` is `None` but `output_schema` was requested
- No observability counter tracks structured output validation failures
- Unit tests cover individual retry steps but not the full pipeline from dispatch through result extraction

---

## FM-18: Malformed JSON from Gemini API (RPN=24, Pathway: P2b/P6d)

**Failure Mode:** The Gemini API returns a response with HTTP 200 but the body
contains malformed or truncated JSON. The SDK fails to parse the response body,
raising an exception before any ADK callback fires.

**Risk:** RPN=24. The SDK's HTTP retry mechanism handles this at the transport level
for transient cases. For worker calls, if the SDK retry also receives malformed JSON,
the exception propagates to `worker_on_model_error` which converts it to
`LLMResult(error=True)`. For reasoning calls, the exception propagates to the
orchestrator's retry loop.

**Source Code Inspection:**

The ScenarioRouter in the provider-fake test infrastructure already supports a
`malformed_json` fault type, but no fixture currently uses it.

```
=== ScenarioRouter fault_type handling (tests_rlm_adk/provider_fake/fixtures.py:152-169) ===
```

```python
            # Check fault injection first
            if idx in self._faults:
                fault = self._faults[idx]
                fault_type = fault.get("fault_type", "http_error")

                if fault_type == "malformed_json":
                    # Return a special sentinel -- the server will write raw text
                    return -1, {"_raw": fault.get("body_raw", "{bad json")}

                status = fault.get("status", 500)
                body = fault.get("body", {
                    "error": {"code": status, "message": "Injected fault", "status": "INTERNAL"}
                })
                logger.info(
                    "Fixture %s: call #%d -> fault %d (%s)",
                    self.scenario_id, idx, status, fault_type,
                )
                return status, body
```

```
=== FakeGeminiServer malformed JSON response (tests_rlm_adk/provider_fake/server.py:108-115) ===
```

```python
        # Handle malformed JSON fault
        if status_code == -1:
            raw = response_body.get("_raw", "{bad json")
            return web.Response(
                text=raw,
                content_type="application/json",
                status=200,
            )
```

```
=== worker_on_model_error (rlm_adk/callbacks/worker.py:111-147) ===
```

```python
def worker_on_model_error(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
    error: Exception,
) -> LlmResponse | None:
    """Handle worker LLM errors gracefully without crashing ParallelAgent."""
    agent = callback_context._invocation_context.agent
    error_msg = f"[Worker {agent.name} error: {type(error).__name__}: {error}]"

    agent._result = error_msg  # type: ignore[attr-defined]
    agent._result_ready = True  # type: ignore[attr-defined]
    agent._result_error = True  # type: ignore[attr-defined]

    # Write error call record onto agent object for dispatch closure
    agent._call_record = {  # type: ignore[attr-defined]
        "prompt": getattr(agent, "_pending_prompt", None),
        "response": error_msg,
        "input_tokens": 0,
        "output_tokens": 0,
        "model": None,
        "finish_reason": None,
        "error": True,
        "error_category": _classify_error(error),
        "http_status": getattr(error, "code", None),
    }

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=error_msg)],
        )
    )
```

```
=== _classify_error (rlm_adk/callbacks/worker.py:22-37) ===
```

```python
def _classify_error(error: Exception) -> str:
    """Classify an exception into an error category for observability."""
    code = getattr(error, "code", None)
    if isinstance(error, asyncio.TimeoutError):
        return "TIMEOUT"
    if code == 429:
        return "RATE_LIMIT"
    if code in (401, 403):
        return "AUTH"
    if code and isinstance(code, int) and code >= 500:
        return "SERVER"
    if code and isinstance(code, int) and code >= 400:
        return "CLIENT"
    if isinstance(error, (ConnectionError, OSError)):
        return "NETWORK"
    return "UNKNOWN"
```

**How the code handles FM-18:**

1. **SDK transport layer:** When the Gemini API returns HTTP 200 with a malformed
   JSON body, the `google.genai` SDK attempts to parse the response. The JSON
   parse failure raises an exception (likely `json.JSONDecodeError` or a
   SDK-internal `ClientError`). If the SDK's `HttpRetryOptions` are configured
   (they are for workers: `attempts=2`), the SDK may retry the request before
   surfacing the error.

2. **Error callback isolation:** For worker calls, if the SDK retry also fails,
   the exception propagates through ADK's `BaseLlmFlow` to
   `worker_on_model_error` (lines 111-147). This callback catches the exception,
   writes error metadata onto the worker object, and returns a synthetic
   `LlmResponse` so `ParallelAgent` does not crash.

3. **Error classification gap:** `_classify_error()` (lines 22-37) inspects the
   exception's `.code` attribute. A JSON parse error typically has no `.code`,
   is not a `TimeoutError`, `ConnectionError`, or `OSError`, so it falls through
   to `"UNKNOWN"`. There is no explicit `"MALFORMED_JSON"` or `"PARSE_ERROR"`
   category.

4. **Server-side fault support:** The `ScenarioRouter` (fixtures.py lines 157-159)
   and `FakeGeminiServer` (server.py lines 108-115) already support `fault_type:
   "malformed_json"` by returning a raw text response with `content_type:
   application/json` and status 200. The sentinel status code `-1` signals the
   server to bypass JSON serialization and send raw bytes.

5. **No fixture exercises this path:** Despite the infrastructure being ready,
   no fixture JSON file uses `fault_type: "malformed_json"`. The entire
   malformed-JSON error path is untested end-to-end.

**Testability Assessment:** Provider-fake e2e testable. The `ScenarioRouter` and
`FakeGeminiServer` already implement the `malformed_json` fault type. A new fixture
only needs to inject the fault at a worker call index. The SDK's behavior when
receiving malformed JSON at HTTP 200 needs empirical validation -- the SDK may
raise `ClientError`, `JSONDecodeError`, or wrap the error differently depending
on version.

**Recommended Test Scenario:** `worker_malformed_json.json` fixture:
- call 0: reasoning emits `execute_code` with `llm_query("prompt")`
- call 1: worker receives malformed JSON fault (`fault_type: "malformed_json"`, `body_raw: "{truncated`)
- call 2: worker SDK retry succeeds (normal response)
- call 3: reasoning returns FINAL with recovered answer
- Assert: transparent recovery (same as FM-09 pattern); if SDK retry also fails, assert `LLMResult.error=True` and `error_category` is populated

Alternative exhaustion scenario:
- call 1 and call 2 both return malformed JSON
- Assert: `worker_on_model_error` fires, `LLMResult(error=True)`, error_category reflects the parse failure

**Gaps:**
- No fixture uses `fault_type: "malformed_json"` despite infrastructure support
- `_classify_error()` has no explicit category for JSON parse errors (falls to `"UNKNOWN"`)
- SDK behavior on malformed JSON at HTTP 200 is undocumented -- unknown whether `HttpRetryOptions` retries on parse errors vs. only HTTP status codes
- No test verifies that the raw bytes from `FakeGeminiServer` actually trigger the expected SDK exception path

---

## FM-20: worker_after_model Callback Exception (RPN=24, Pathway: P6e)

**Failure Mode:** An unhandled exception inside `worker_after_model` (e.g.,
`AttributeError` from a Pydantic attribute write failing due to an ADK API change,
or `TypeError` from unexpected `llm_response` shape) propagates through ADK's
`BaseLlmFlow`. ADK does **not** route callback exceptions through
`on_model_error_callback` -- that callback only fires for model/API errors. The
exception may crash the `ParallelAgent`, taking down all workers in the batch.

**Risk:** RPN=24. Severity is 8 (entire batch crash) but occurrence is 1 (requires
ADK API break or unexpected response shape). If one worker's callback fails in a
K>1 batch, all K workers may fail, producing K error results.

**Source Code Inspection:**

```
=== worker_after_model (rlm_adk/callbacks/worker.py:63-108) ===
```

```python
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

Key observations from the source:

- **No try/except wrapper:** The entire function body from line 63 to 108 has
  zero exception handling. Every statement executes unguarded.

- **Private API access (line 78):** `callback_context._invocation_context.agent`
  accesses a private attribute. If ADK changes this internal API, the callback
  raises `AttributeError`.

- **Dynamic attribute writes (lines 81-82):** `agent._result = response_text` and
  `agent._result_ready = True` write custom attributes onto a Pydantic model.
  These succeed because Pydantic's `model_config` for `LlmAgent` allows extra
  attributes, but a future ADK version could restrict this.

- **Generator expression (lines 74-76):** `part.text for part in llm_response.content.parts
  if part.text and not part.thought` -- if `part` is an unexpected type lacking
  `.text` or `.thought`, this raises `AttributeError` inside the generator.

- **State write (line 106):** `callback_context.state[output_key] = response_text`
  could raise if the state backend rejects the write (e.g., serialization failure).

```
=== Dispatch exception handler (rlm_adk/dispatch.py:505-510) ===
```

```python
            except Exception as e:
                logger.error(f"Worker dispatch error in batch {batch_num}: {e}")
                all_results.extend([
                    LLMResult(f"Error: {e}", error=True, error_category="UNKNOWN")
                    for _ in batch_prompts
                ])
```

The dispatch closure's outer `except Exception` at line 505 catches any
exception that propagates out of `ParallelAgent.run_async()` or
`worker.run_async()`. This is the safety net that prevents the entire
orchestrator from crashing. However, it produces error results for **all**
workers in the batch, even those that completed successfully before the
exception.

**How the code handles FM-20:**

1. **No internal error handling:** `worker_after_model` has zero try/except blocks.
   Any exception propagates directly out of the callback.

2. **ADK does not intercept callback errors:** ADK's `BaseLlmFlow` calls
   `after_model_callback` after the model response is received. If the callback
   raises, ADK does **not** route the error to `on_model_error_callback` (that
   callback is only for errors during the model call itself). The exception
   propagates up through the agent's `run_async`.

3. **ParallelAgent blast radius:** If one worker's callback raises inside a
   `ParallelAgent` dispatch, the exception may cancel or crash sibling workers
   depending on how `asyncio.gather` handles the failure internally. The dispatch
   closure's `except Exception` (line 505) catches the propagated error and
   converts all batch results to error `LLMResult` objects.

4. **Partial results lost:** Workers that completed successfully before the
   exception have valid `_result` and `_result_ready` on their objects, but the
   `except` handler at line 505 discards them -- it creates error results for
   **all** `batch_prompts`, not just the failed worker.

**Testability Assessment:** Unit testable via mock injection. Patch
`worker_after_model` or inject a callback that raises, then verify the dispatch
closure's `except Exception` catches it and produces error results. Not directly
testable via provider-fake fixtures because the fault occurs in callback code,
not in the API response. Requires a monkeypatch or a dedicated test harness.

**Recommended Test Scenario:** Unit test in `tests_rlm_adk/test_adk_callbacks.py`:
- Create a real `LlmAgent` worker with `after_model_callback` that raises `AttributeError`
- Wire it into a dispatch closure
- Patch `run_async` to call the callback directly
- Assert: dispatch returns `LLMResult(error=True, error_category="UNKNOWN")` for all batch prompts
- Assert: `finally` block still runs (worker cleanup, pool release)

Alternative architectural fix: wrap `worker_after_model` body in try/except,
falling back to setting `_result_error=True` and `_result_ready=True` on the
agent object so the dispatch closure can distinguish the failed worker from
successful ones.

**Gaps:**
- `worker_after_model` has zero try/except protection (lines 63-108)
- ADK does not route callback exceptions through `on_model_error_callback`
- Dispatch `except Exception` (line 505) discards successful results from other workers in the same batch
- No test verifies behavior when `worker_after_model` raises
- No logging or observability counter for callback exceptions

---

## FM-21: BUG-13 Patch Import Failure (RPN=18, Module import)

**Failure Mode:** The BUG-13 workaround in `worker_retry.py` monkey-patches a
private ADK internal module (`google.adk.flows.llm_flows._output_schema_processor`).
If an ADK version update removes, renames, or restructures this internal module,
the import at line 167 raises `ImportError`. Because the patch is applied at
module-level (line 200), this `ImportError` cascades: `worker_retry.py` fails to
import, `dispatch.py` (which imports `make_worker_tool_callbacks` from
`worker_retry`) fails to import, and `orchestrator.py` (which imports from
`dispatch`) fails to import. The entire package becomes unusable.

**Risk:** RPN=18. Severity is 9 (complete package failure) but occurrence is 2
(only on ADK version upgrade) and detection is 1 (immediate `ImportError` on first
use, obvious in traceback). The low detection score reflects that the failure is
loud and unmistakable -- but that loudness means the system is completely
non-functional rather than degraded.

**Source Code Inspection:**

```
=== Top-level imports (rlm_adk/callbacks/worker_retry.py:17-27) ===
```

```python
import json as _json
import logging
from typing import Any, Optional

from google.adk.plugins.reflect_retry_tool_plugin import (
    REFLECT_AND_RETRY_RESPONSE_TYPE,
    ReflectAndRetryToolPlugin,
)
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
```

```
=== _patch_output_schema_postprocessor (rlm_adk/callbacks/worker_retry.py:162-200) ===
```

```python
def _patch_output_schema_postprocessor() -> None:
    """Install a retry-aware wrapper around get_structured_model_response.

    Idempotent -- safe to call multiple times.
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

```
=== dispatch.py import of worker_retry (rlm_adk/dispatch.py:37) ===
```

```python
from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks
```

Key observations:

- **Private module path (line 167):** `import google.adk.flows.llm_flows._output_schema_processor`
  -- the leading underscore signals this is a private implementation detail of
  ADK. Private modules carry no stability guarantees across versions.

- **Import-time execution (line 200):** `_patch_output_schema_postprocessor()` is
  called at module scope, meaning the import of `_osp` at line 167 executes during
  `import rlm_adk.callbacks.worker_retry`. If the import fails, the entire module
  fails to load.

- **Cascade path:** `dispatch.py` line 37 imports `make_worker_tool_callbacks` from
  `worker_retry`. If `worker_retry` fails to import, `dispatch.py` also fails.
  `orchestrator.py` imports from `dispatch.py`, so the cascade reaches the
  top-level entry point.

- **No defensive import:** There is no `try/except ImportError` around the private
  module import. The patch function assumes the module exists.

- **Idempotency guard (line 170):** The `_rlm_patched` sentinel prevents
  double-patching but does not help if the initial import fails.

**How the code handles FM-21:**

1. **No handling:** There is no defensive import (`try/except ImportError`) around
   the private ADK module import at line 167. The code assumes the module path
   `google.adk.flows.llm_flows._output_schema_processor` is stable.

2. **Import-time side effect:** The `_patch_output_schema_postprocessor()` call at
   line 200 executes during module load. This means the failure occurs at import
   time, not at runtime when a structured output dispatch is attempted. The
   failure is not deferrable.

3. **Complete cascade:** Because the patch is unconditionally applied at import
   time, and `dispatch.py` unconditionally imports from `worker_retry.py`, an
   ADK version that removes the private module makes the entire `rlm_adk` package
   unimportable.

4. **Correct current behavior:** On the current ADK version, the module exists
   at `.venv/lib/python3.12/site-packages/google/adk/flows/llm_flows/_output_schema_processor.py`,
   and the patch installs correctly. The risk is entirely forward-looking.

**Testability Assessment:** Not testable via provider-fake. This is a module-level
import failure that cannot be triggered by fixture scenarios. Requires a unit test
that uses `unittest.mock.patch` to simulate the `ImportError` and verifies either
graceful degradation or clear error messaging.

**Recommended Test Scenario:** Unit test in `tests_rlm_adk/test_adk_worker_retry.py`:
- `test_patch_graceful_on_missing_module`: Use `unittest.mock.patch.dict("sys.modules", {"google.adk.flows.llm_flows._output_schema_processor": None})` to simulate the module being absent
- Call `_patch_output_schema_postprocessor()` and verify it either:
  - (a) Raises `ImportError` (current behavior -- document it)
  - (b) Logs a warning and skips the patch (recommended fix)
- `test_patch_does_not_break_non_structured_dispatch`: Verify that when the patch
  is not installed (e.g., import failed gracefully), non-structured-output worker
  dispatch still works correctly
- `test_cascade_import_failure`: Verify the import chain `worker_retry -> dispatch -> orchestrator` and document the blast radius

Alternative architectural fix: wrap the import and patch in try/except:
```python
def _patch_output_schema_postprocessor() -> None:
    try:
        import google.adk.flows.llm_flows._output_schema_processor as _osp
    except ImportError:
        logger.warning("BUG-13 patch skipped: _output_schema_processor not found")
        return
    # ... rest of patch
```
This would degrade gracefully: structured output retry would not work (workers
would terminate prematurely on retry), but all other functionality remains intact.

**Gaps:**
- No try/except ImportError around the private module import (line 167)
- Module-level execution (line 200) means failure is immediate and total
- No unit test verifies behavior when the ADK internal module is absent
- No version check or compatibility assertion documents which ADK versions the patch supports
- The patch depends on two private ADK internals: the module path and the `get_structured_model_response` function signature

---

## Summary

| FM | Name | RPN | Testability | Current Coverage | Key Finding |
|----|------|-----|-------------|------------------|-------------|
| FM-16 | Structured Output Retry Exhaustion | 50 | Provider-fake e2e | Unit tests only (no e2e) | `LLMResult(error=False, parsed=None)` on exhaustion -- no error signal to REPL code |
| FM-18 | Malformed JSON from Gemini API | 24 | Provider-fake e2e (infra ready) | Zero (infrastructure exists but unused) | `ScenarioRouter` supports `malformed_json` fault_type but no fixture uses it; `_classify_error` has no parse-error category |
| FM-20 | worker_after_model Callback Exception | 24 | Unit test with monkeypatch | Zero | No try/except in 46-line callback body; dispatch `except Exception` discards successful sibling results |
| FM-21 | BUG-13 Patch Import Failure | 18 | Unit test (mock sys.modules) | Zero | No defensive import; cascades to total package failure on ADK version change |

**Key architectural insight:** These four failure modes expose a common pattern:
the structured output self-healing pipeline (FM-16, FM-21) and the worker callback
layer (FM-18, FM-20) both lack defensive error boundaries. The retry plugin
correctly handles the happy path and single-retry recovery but does not signal
failure on exhaustion. The callback functions operate without try/except protection,
relying on the dispatch closure's broad `except Exception` as the only safety net --
and that safety net discards valid results from successful sibling workers. The
BUG-13 monkey-patch is architecturally fragile by necessity (it patches private
ADK internals), but the lack of a defensive import makes the fragility catastrophic
rather than graceful.
