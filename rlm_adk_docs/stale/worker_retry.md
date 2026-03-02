# Structured Output Self-Healing (Worker Retry)

Workers dispatched via `llm_query()` support validated structured output through
Pydantic schemas. When `output_schema=MySchema` is passed, ADK's self-healing
pipeline validates the response and retries on failure with reflection guidance.

```
llm_query("analyze this", output_schema=MySchema)
  -> LLMResult with .parsed = {"answer": "42", "score": 0.95}
```

---

## Files

| File | Role |
|------|------|
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin` + `make_worker_tool_callbacks()` factory |
| `rlm_adk/dispatch.py` | `output_schema` wiring, structured result extraction, local accumulators |
| `rlm_adk/types.py` | `LLMResult.parsed` field (line 66) |
| `rlm_adk/state.py` | State key constants for dispatch event emissions |
| `tests_rlm_adk/test_adk_worker_retry.py` | 19 unit tests across 7 TDD cycles |
| `tests_rlm_adk/test_structured_output_e2e.py` | E2E provider-fake structured output tests |
| `tests_rlm_adk/fixtures/provider_fake/structured_output_*.json` | E2E fixture scenarios |

---

## Classes and Functions

### `LLMResult` (`rlm_adk/types.py:43`)

`str` subclass carrying worker call metadata. The `parsed` field surfaces
validated structured output:

```python
class LLMResult(str):
    error: bool = False
    error_category: str | None = None
    parsed: dict | None = None  # Set when output_schema used
    # ... other fields ...
```

Without `output_schema`, `parsed` stays `None`. With it, `parsed` contains
the validated dict from `SetModelResponseTool.run_async`.

### `WorkerRetryPlugin` (`rlm_adk/callbacks/worker_retry.py:24`)

Extends `ReflectAndRetryToolPlugin`. Overrides `extract_error_from_result`
to detect empty string values in `set_model_response` tool results.

```python
class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    def __init__(
        self,
        max_retries: int = 2,
        format_validator: Callable[[dict], str | None] | None = None,
    ): ...

    async def extract_error_from_result(
        self, *, tool, tool_args, tool_context, result
    ) -> Optional[dict[str, Any]]: ...
```

- Guards on `tool.name == "set_model_response"` (ignores all other tools)
- Checks each string field in `tool_args` for blank content
- Delegates to optional `format_validator` for custom schema-level checks
- Returns `{"error": ..., "details": ...}` on failure, `None` on success

### `make_worker_tool_callbacks()` (`rlm_adk/callbacks/worker_retry.py:67`)

Factory returning `(after_tool_cb, on_tool_error_cb)` with positional-arg
signatures matching `LlmAgent`'s `AfterToolCallback` / `OnToolErrorCallback`.

```python
def make_worker_tool_callbacks(max_retries: int = 2) -> tuple[Any, Any]:
```

Creates one shared `WorkerRetryPlugin` instance, then closes over it in two
async callbacks:

- **`after_tool_cb(tool, args, tool_context, tool_response)`** — On
  `set_model_response` success, writes `tool_response` to
  `agent._structured_result` via `tool_context._invocation_context.agent`.
  Delegates to `plugin.after_tool_callback` for semantic error detection.

- **`on_tool_error_cb(tool, args, tool_context, error)`** — Delegates to
  `plugin.on_tool_error_callback` for retry counting and reflection guidance.

**Parameter naming is critical:** ADK calls agent-level callbacks with keyword
args `args=` and `tool_response=` (not `tool_args` / `result`). Plugin-level
callbacks use `tool_args=` and `result=`. The wrappers bridge this mismatch.

### Dispatch Wiring (`rlm_adk/dispatch.py:394-402`)

Inside `llm_query_batched_async`, when `output_schema is not None`:

```python
worker.tools = [SetModelResponseTool(output_schema)]
after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
worker.after_tool_callback = after_cb
worker.on_tool_error_callback = error_cb
worker._structured_result = None
```

`worker.output_schema` is intentionally **not** set — doing so would cause
`_OutputSchemaRequestProcessor` to inject a second `SetModelResponseTool`.

Result extraction (`dispatch.py:462-476`):

```python
structured = getattr(worker, "_structured_result", None)
if structured is not None:
    result_text = json.dumps(structured)
else:
    result_text = worker._result
all_results.append(LLMResult(result_text, ..., parsed=structured))
```

Cleanup in `finally` resets `tools`, `after_tool_callback`,
`on_tool_error_callback`, and `_structured_result`.

---

## State Keys

All written via `EventActions(state_delta={...})` on `Event` objects placed in
`event_queue` — never via `ctx.session.state` directly (AR-CRIT-001).

| Constant | Value | Purpose |
|----------|-------|---------|
| `WORKER_DISPATCH_COUNT` | `worker_dispatch_count` | Running dispatch total |
| `OBS_WORKER_TOTAL_DISPATCHES` | `obs:worker_total_dispatches` | Observability alias |
| `OBS_WORKER_TOTAL_BATCH_DISPATCHES` | `obs:worker_total_batch_dispatches` | Count of k>1 dispatches |
| `OBS_WORKER_DISPATCH_LATENCY_MS` | `obs:worker_dispatch_latency_ms` | Per-batch elapsed ms list |
| `WORKER_DIRTY_READ_COUNT` | `worker_dirty_read_count` | Workers whose results were read |
| `OBS_WORKER_DIRTY_READ_MISMATCHES` | `obs:worker_dirty_read_mismatches` | Workers with no result ready |

Local accumulators in `create_dispatch_closures` replace all `ctx.session.state`
reads. State is emitted as absolute values via `state_delta`, not incremental
deltas. No `temp:` prefix (ADK strips `temp:` from event stream).

---

## google-adk Components

### `ReflectAndRetryToolPlugin`

**File:** `.venv/.../google/adk/plugins/reflect_retry_tool_plugin.py`
**Chain:** `ReflectAndRetryToolPlugin` -> `BasePlugin` -> `ABC`

Core retry mechanism. Intercepts tool failures and generates structured
reflection guidance for model self-correction.

```python
def __init__(self, name="reflect_retry_tool_plugin", max_retries=3,
             throw_exception_if_retry_exceeded=True,
             tracking_scope=TrackingScope.INVOCATION): ...
```

Key methods (all keyword-only signatures):

| Method | Line | What it does |
|--------|------|-------------|
| `after_tool_callback(*, tool, tool_args, tool_context, result)` | 138 | Calls `extract_error_from_result`; routes errors to `_handle_tool_error` |
| `on_tool_error_callback(*, tool, tool_args, tool_context, error)` | 204 | Routes directly to `_handle_tool_error` |
| `extract_error_from_result(*, tool, tool_args, tool_context, result)` | 177 | Default: returns `None`. Override point for custom detection |
| `_handle_tool_error(tool, tool_args, tool_context, error)` | 225 | Tracks retries per `(invocation_id, tool.name)` under `asyncio.Lock`; returns guidance or raises |
| `_create_tool_reflection_response(tool, tool_args, error, count)` | 299 | Formats `ToolFailureResponse` with error details + retry guidance |

Internal state: `_scoped_failure_counters: dict[str, PerToolFailuresCounter]`
keyed by `invocation_id`, protected by `asyncio.Lock`.

`ToolFailureResponse` model (line 44):
```python
class ToolFailureResponse(BaseModel):
    response_type: str = "ERROR_HANDLED_BY_REFLECT_AND_RETRY_PLUGIN"
    error_type: str = ""
    error_details: str = ""
    retry_count: int = 0
    reflection_guidance: str = ""
```

### `SetModelResponseTool`

**File:** `.venv/.../google/adk/tools/set_model_response_tool.py`
**Chain:** `SetModelResponseTool` -> `BaseTool` -> `ABC`

Validates structured output against Pydantic schemas.

```python
def __init__(self, output_schema: type[BaseModel]): ...
```

- Dynamically builds `inspect.Signature` from `output_schema.model_fields`
- Tool name is always `"set_model_response"`
- `_get_declaration()` produces `FunctionDeclaration` for the LLM request

```python
async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> dict[str, Any]:
    validated_response = self.output_schema.model_validate(args)  # raises ValidationError
    return validated_response.model_dump()
```

### `_OutputSchemaRequestProcessor`

**File:** `.venv/.../google/adk/flows/llm_flows/_output_schema_processor.py`
**Chain:** `_OutputSchemaRequestProcessor` -> `BaseLlmRequestProcessor`

Activates when ALL three conditions hold:
1. `agent.output_schema` is set
2. `agent.tools` is non-empty
3. `can_use_output_schema_with_tools(agent.canonical_model)` returns `False`

On Google AI Studio (non-Vertex), condition 3 is always met. When active,
injects a NEW `SetModelResponseTool(agent.output_schema)` plus usage instructions.

**This is why dispatch.py does NOT set `worker.output_schema`** — it would cause
a duplicate tool injection.

### `ToolContext`

**File:** `.venv/.../google/adk/tools/tool_context.py`
**Chain:** `ToolContext` -> `CallbackContext` -> `ReadonlyContext`

Key attribute used: `_invocation_context.agent` (private API) — returns the
`LlmAgent` worker, allowing `after_tool_cb` to write `_structured_result`.

### `BaseTool`, `BasePlugin`

**Files:** `.venv/.../google/adk/tools/base_tool.py`, `.venv/.../google/adk/plugins/base_plugin.py`

Type annotations for callback parameters. `BasePlugin` defines **keyword-only**
callback signatures; `LlmAgent` defines **positional-arg** callback signatures.

### `functions.py` (ADK internal)

**File:** `.venv/.../google/adk/flows/llm_flows/functions.py`

`_execute_single_function_call_async` (line 414) is the call chain router:

1. Plugin `before_tool_callback`
2. Agent `canonical_before_tool_callbacks`
3. `tool.run_async(args=..., tool_context=...)` — **ValidationError raised here**
4. On exception: `_run_on_tool_error_callbacks` -> plugin then agent error callbacks
5. Plugin `after_tool_callback`
6. Agent `canonical_after_tool_callbacks` — **`_structured_result` captured here**

---

## API Wire Format

Structured output workers receive `functionCall` responses from the Gemini API,
not `text` responses. The model calls the `set_model_response` tool with
structured arguments matching the Pydantic schema.

**functionCall response (worker step 1):**
```json
{
  "candidates": [{
    "content": {
      "role": "model",
      "parts": [{
        "functionCall": {
          "name": "set_model_response",
          "args": {"summary": "Market trending up", "confidence": 0.92}
        }
      }]
    },
    "finishReason": "STOP"
  }],
  "usageMetadata": { "promptTokenCount": 100, "candidatesTokenCount": 30, "totalTokenCount": 130 },
  "modelVersion": "gemini-fake"
}
```

**Confirmation text response (worker step 2):**
After ADK executes the tool and feeds the `FunctionResponse` back, the model
produces a plain text response to close the tool loop:
```json
{
  "candidates": [{
    "content": {
      "role": "model",
      "parts": [{"text": "Response set."}]
    },
    "finishReason": "STOP"
  }],
  "usageMetadata": { "promptTokenCount": 150, "candidatesTokenCount": 5, "totalTokenCount": 155 },
  "modelVersion": "gemini-fake"
}
```

The worker ends up with both `_result` (text from step 2) and
`_structured_result` (validated dict from step 1). Dispatch extraction
(`dispatch.py:462-476`) prefers `_structured_result` when present.

### API Call Counts Per Worker

| Scenario | API calls | Breakdown |
|----------|-----------|-----------|
| Happy path (valid on first try) | 2 | functionCall + confirmation text |
| 1 retry (ValidationError or empty field) | 4 | bad functionCall + reflection fed back + corrected functionCall + confirmation text |
| N retries then success | 2 + 2×N | N×(bad functionCall + reflection) + corrected functionCall + confirmation text |
| Retries exhausted (max_retries=2) | 4 | 2×(bad functionCall + reflection) + raise on 3rd attempt (no more API calls) |

### Parallel Worker Ordering Constraint

For `llm_query_batched` with K>1 and `output_schema`, each worker makes
multiple round-trips to the Gemini API. `ParallelAgent` runs workers
concurrently on the same asyncio event loop. The FIFO interleaving of API
calls to a provider-fake server is non-deterministic — Worker 1's second
call may arrive before or after Worker 2's first call.

**Impact on provider-fake fixtures:** K>1 batched structured output is
unreliable with FIFO-ordered fixture responses. Workarounds:
- Use K=1 for structured output batched tests (exercises the batched code
  path without `ParallelAgent`)
- Make all parallel worker responses identical (order doesn't matter)
- Test K>1 structured output via unit tests with mocked `run_async`

---

## Retry Event Process Flow

When `llm_query("prompt", output_schema=MySchema)` encounters invalid output:

```
1. DISPATCH WIRING
   dispatch.py:394-402
   ┌──────────────────────────────────────────────────┐
   │ worker.tools = [SetModelResponseTool(MySchema)]  │
   │ worker.after_tool_callback = after_tool_cb       │
   │ worker.on_tool_error_callback = on_tool_error_cb │
   │ worker._structured_result = None                 │
   └──────────────────────────────────────────────────┘
                         │
2. ADK LLM FLOW          ▼
   worker.run_async(ctx) → BaseLlmFlow step loop
                         │
3. MODEL CALLS TOOL       ▼
   Model produces FunctionCall: set_model_response(summary="")
                         │
4. VALIDATION             ▼
   SetModelResponseTool.run_async:
     self.output_schema.model_validate(args)
     ┌─────────────────────┬──────────────────────┐
     │ Hard error           │ Soft error            │
     │ (ValidationError)    │ (empty string passes) │
     └────────┬────────────┴──────────┬───────────┘
              │                       │
5a. ERROR PATH ▼                5b. SUCCESS PATH ▼
   functions.py:512              functions.py:539
   _run_on_tool_error_callbacks  after_tool_callback chain
              │                       │
              ▼                       ▼
   on_tool_error_cb              after_tool_cb calls
   → plugin.on_tool_error_cb     plugin.after_tool_callback
              │                  → extract_error_from_result
              │                  → detects empty string
              │                       │
              └───────────┬───────────┘
                          │
6. RETRY DECISION         ▼
   ReflectAndRetryToolPlugin._handle_tool_error:
     scope_key = tool_context.invocation_id
     current_retries = counter[tool.name] + 1
     ┌──────────────────────────┬─────────────────────┐
     │ retries <= max_retries   │ retries > max_retries│
     │ (e.g. 1 <= 2)           │                      │
     └──────────┬───────────────┴──────────┬──────────┘
                │                          │
7a. GUIDANCE    ▼                    7b.   ▼ RAISE
   _create_tool_reflection_response     raise error
   Returns ToolFailureResponse:
   {
     "response_type": "ERROR_HANDLED_...",
     "error_details": "ValidationError: ...",
     "reflection_guidance": "The call to tool
       `set_model_response` failed.\n\n
       **Error Details:**\n..."
   }
                │
8. MODEL RETRY  ▼
   ADK wraps guidance as FunctionResponse event
   → feeds back into next LLM turn as context
   → model produces corrected FunctionCall
                │
9. VALIDATION   ▼
   SetModelResponseTool.run_async:
     model_validate(args) → PASSES
     returns model_dump()  → {"summary": "A real summary"}
                │
10. CAPTURE     ▼
   after_tool_cb (worker_retry.py:97-99):
     agent._structured_result = tool_response
                │
10b. CONFIRM    ▼
   ADK wraps tool result as FunctionResponse event
   → feeds back into next LLM turn as context
   → model produces confirmation text (2nd API call)
   → text written to worker._result by after_model_callback
   (dispatch ignores _result when _structured_result is set)
                │
11. EXTRACTION  ▼
   dispatch.py:462-476:
     structured = worker._structured_result
     result = LLMResult(json.dumps(structured), parsed=structured)
                │
12. CLEANUP     ▼
   dispatch.py finally block:
     worker.tools = []
     worker.after_tool_callback = None
     worker.on_tool_error_callback = None
     worker._structured_result = None
   → worker returned to pool
```

---

## Design Decisions

**Why not set `worker.output_schema`?** — `_OutputSchemaRequestProcessor`
activates when `output_schema + tools` are both set and
`can_use_output_schema_with_tools()` returns `False` (always on Google AI
Studio). It injects its own `SetModelResponseTool`, duplicating ours.

**Why positional-arg wrappers?** — ADK agent-level callbacks (`LlmAgent.after_tool_callback`)
use positional args with names `args=` and `tool_response=`. Plugin-level
callbacks (`BasePlugin.after_tool_callback`) use keyword-only `tool_args=` and
`result=`. The wrappers bridge this mismatch.

**Why local accumulators?** — AR-CRIT-001: `ctx.session.state` reads bypass
event tracking. All state writes go through `EventActions(state_delta={})` on
`Event` objects in the `event_queue`. Local variables in the closure track
running totals without touching session state.

**Why `_structured_result` on the agent?** — `SetModelResponseTool.run_async`
returns a dict to ADK's tool execution loop, which passes it through
`after_tool_callback`. But the dispatch loop reads results from worker objects
after `run_async` completes. The `_structured_result` attribute bridges these
two worlds — the callback writes it, dispatch reads it.

**Why `object.__setattr__` in tests?** — `LlmAgent` is a Pydantic model.
Normal `setattr` for non-model fields raises `ValueError`. Tests use
`object.__setattr__(worker, "run_async", mock_fn)` to bypass Pydantic's
`__setattr__` override.

---

## E2E Provider-Fake Testing

### Fixture Design for Structured Output

Provider-fake fixtures script Gemini API responses in FIFO order via
`ScenarioRouter`. Structured output workers require `functionCall` responses
(not `text`), and each worker needs at least 2 API calls.

**Fixture JSON for a structured output worker (happy path):**
```json
{
  "call_index": 1,
  "caller": "worker",
  "status": 200,
  "body": {
    "candidates": [{
      "content": {
        "role": "model",
        "parts": [{
          "functionCall": {
            "name": "set_model_response",
            "args": {"summary": "Market trending up", "confidence": 0.92}
          }
        }]
      },
      "finishReason": "STOP",
      "index": 0
    }],
    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 30, "totalTokenCount": 130},
    "modelVersion": "gemini-fake"
  }
}
```
Followed by a confirmation text response at the next call index.

**Fixture JSON for a ValidationError retry:**
The first functionCall has args that fail Pydantic validation (e.g., missing
required field, wrong type). ADK catches the `ValidationError`, the
`on_tool_error_callback` returns reflection guidance, and ADK feeds it back
as a `FunctionResponse`. The next scripted response should be a corrected
`functionCall`.

### REPL Code in Reasoning Responses

Reasoning agent responses contain REPL code blocks that define Pydantic
schemas and call `llm_query()` / `llm_query_batched()` with `output_schema`.
The AST rewriter transforms these to async calls. Example REPL code:

```python
from pydantic import BaseModel

class AnalysisResult(BaseModel):
    summary: str
    confidence: float

result = llm_query("Analyze the data", output_schema=AnalysisResult)
print(f"Parsed: {result.parsed}")
```

### Call Count Arithmetic

For a fixture with reasoning + structured output workers:

```
total_model_calls = reasoning_calls + sum(worker_api_calls)

where worker_api_calls per worker:
  happy path:     2  (functionCall + text)
  with N retries: 2 + 2*N  (N*(bad + reflection feedback) + good + text)
```

### Iteration Count (`ITERATION_COUNT`)

The orchestrator loop is `for i in range(max_iterations)`. The state key
is set to `i + 1` (1-indexed). FINAL detection emits `ITERATION_COUNT: i + 1`
and returns immediately. End-of-iteration (non-FINAL) also emits `i + 1`.

Key: if FINAL is detected at loop index `i`, the iteration count is `i + 1`,
regardless of how many reasoning calls occurred within that iteration (REPL
execution + FINAL detection can happen in the same outer loop pass).

### Test Files

| File | Coverage |
|------|----------|
| `tests_rlm_adk/test_adk_worker_retry.py` | 19 unit tests across 7 TDD cycles |
| `tests_rlm_adk/fixtures/provider_fake/structured_output_*.json` | E2E provider-fake fixtures |
| `tests_rlm_adk/test_structured_output_e2e.py` | E2E contract + assertion tests |
