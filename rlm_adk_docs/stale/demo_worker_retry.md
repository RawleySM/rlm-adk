# Structured Output Self-Healing for Worker Dispatch

*2026-02-27T12:17:47Z by Showboat 0.6.0*
<!-- showboat-id: 3695f3e9-3f6a-42bd-b83b-c1b7a9a00fec -->

Workers dispatched via `llm_query()` now support validated structured output via Pydantic schemas. When `output_schema=MySchema` is passed, ADK's self-healing pipeline (SetModelResponseTool + ReflectAndRetryToolPlugin) validates the response and retries on failure. Additionally, all `ctx.session.state` reads in dispatch.py were replaced with local accumulators (AR-CRIT-001).

## 1. LLMResult.parsed field — backward-compatible structured output carrier

```bash
sed -n "43,72p" rlm_adk/types.py
```

```output
class LLMResult(str):
    """String subclass carrying worker call metadata.

    Backward-compatible: passes isinstance(x, str), works in f-strings,
    concatenation, etc. But REPL code can inspect error state:

        result = llm_query("prompt")
        if result.error:
            if result.error_category == "TIMEOUT":
                raise RuntimeError(f"Worker timed out: {result}")
            elif result.error_category == "RATE_LIMIT":
                await asyncio.sleep(5)
                result = llm_query("prompt")  # retry
    """

    error: bool = False
    error_category: str | None = None  # TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, FORMAT, UNKNOWN
    http_status: int | None = None
    finish_reason: str | None = None  # STOP, SAFETY, RECITATION, MAX_TOKENS
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    wall_time_ms: float = 0.0
    parsed: dict | None = None  # Validated structured output (set when output_schema used)

    def __new__(cls, text: str, **kwargs: Any) -> "LLMResult":
        instance = super().__new__(cls, text)
        for k, v in kwargs.items():
            setattr(instance, k, v)
        return instance
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.types import LLMResult

# Plain text — backward compatible
r1 = LLMResult('hello world')
print(f'str(r1) = {str(r1)!r}')
print(f'r1.parsed = {r1.parsed}')
print(f'isinstance(r1, str) = {isinstance(r1, str)}')

# Structured output — parsed carries validated dict
r2 = LLMResult('{\"answer\":\"42\",\"score\":0.95}', parsed={'answer': '42', 'score': 0.95})
print(f'str(r2) = {str(r2)!r}')
print(f'r2.parsed = {r2.parsed}')
print(f'r2.parsed[\"answer\"] = {r2.parsed[\"answer\"]!r}')
"

```

```output
str(r1) = 'hello world'
r1.parsed = None
isinstance(r1, str) = True
str(r2) = '{"answer":"42","score":0.95}'
r2.parsed = {'answer': '42', 'score': 0.95}
r2.parsed["answer"] = '42'
```

## 2. WorkerRetryPlugin — extends ADK's ReflectAndRetryToolPlugin

```bash
sed -n "24,54p" rlm_adk/callbacks/worker_retry.py
```

```output
class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    """Extends ReflectAndRetryToolPlugin for set_model_response validation.

    Detects empty values in set_model_response tool results and triggers
    retry via the parent class's reflection/retry mechanism.
    """

    def __init__(self, max_retries: int = 2):
        super().__init__(max_retries=max_retries)

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

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import asyncio
from unittest.mock import MagicMock
from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin
from google.adk.plugins.reflect_retry_tool_plugin import ReflectAndRetryToolPlugin

plugin = WorkerRetryPlugin(max_retries=2)
print(f'isinstance(plugin, ReflectAndRetryToolPlugin) = {isinstance(plugin, ReflectAndRetryToolPlugin)}')

# Empty response triggers error
tool = MagicMock(); tool.name = 'set_model_response'
err = asyncio.run(plugin.extract_error_from_result(
    tool=tool, tool_args={'summary': ''}, tool_context=MagicMock(), result={'summary': ''}
))
print(f'empty response error = {err}')

# Valid response passes
ok = asyncio.run(plugin.extract_error_from_result(
    tool=tool, tool_args={'summary': 'good'}, tool_context=MagicMock(), result={'summary': 'good'}
))
print(f'valid response error = {ok}')
"

```

```output
isinstance(plugin, ReflectAndRetryToolPlugin) = True
empty response error = {'error': 'Empty value', 'details': "Empty string for field 'summary'. The response must contain meaningful content."}
valid response error = None
```

## 3. make_worker_tool_callbacks() — positional-arg wrappers for LlmAgent

```bash
sed -n "57,114p" rlm_adk/callbacks/worker_retry.py
```

```output
def make_worker_tool_callbacks(
    max_retries: int = 2,
) -> tuple[Any, Any]:
    """Create agent-level tool callback wrappers backed by WorkerRetryPlugin.

    Returns (after_tool_cb, on_tool_error_cb) with positional-arg signatures
    matching LlmAgent's AfterToolCallback and OnToolErrorCallback types.

    The after_tool_cb captures validated structured results on the worker
    agent's _structured_result attribute when set_model_response succeeds.

    The on_tool_error_cb delegates to the plugin for retry counting and
    reflection guidance generation.

    Args:
        max_retries: Maximum retry attempts for validation errors.

    Returns:
        Tuple of (after_tool_callback, on_tool_error_callback) callables.
    """
    plugin = WorkerRetryPlugin(max_retries=max_retries)

    async def after_tool_cb(
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[dict[str, Any]]:
        """After-tool callback: capture structured result, delegate to plugin."""
        # On set_model_response success, store validated dict on the agent
        if tool.name == "set_model_response" and isinstance(result, dict):
            agent = tool_context._invocation_context.agent
            agent._structured_result = result  # type: ignore[attr-defined]
            logger.debug(
                "Captured structured result on %s: %s",
                getattr(agent, "name", "?"),
                list(result.keys()),
            )

        # Delegate to plugin for extract_error_from_result checks
        return await plugin.after_tool_callback(
            tool=tool, tool_args=tool_args,
            tool_context=tool_context, result=result,
        )

    async def on_tool_error_cb(
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict[str, Any]]:
        """On-tool-error callback: delegate to plugin for retry/reflection."""
        return await plugin.on_tool_error_callback(
            tool=tool, tool_args=tool_args,
            tool_context=tool_context, error=error,
        )

    return after_tool_cb, on_tool_error_cb
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import asyncio
from unittest.mock import MagicMock
from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
print(f'after_cb callable: {callable(after_cb)}')
print(f'error_cb callable: {callable(error_cb)}')

# After callback captures structured result on agent
tool = MagicMock(); tool.name = 'set_model_response'
agent = MagicMock(); agent._structured_result = None
tc = MagicMock(); tc._invocation_context.agent = agent; tc.invocation_id = 'inv-1'

asyncio.run(after_cb(tool, {'title': 'Test', 'score': 0.9}, tc, {'title': 'Test', 'score': 0.9}))
print(f'agent._structured_result = {agent._structured_result}')

# Error callback returns reflection guidance on first failure
error = ValueError('bad schema')
guidance = asyncio.run(error_cb(tool, {'bad': 'data'}, tc, error))
print(f'reflection_guidance present: {\"reflection_guidance\" in guidance}')
"

```

```output
after_cb callable: True
error_cb callable: True
agent._structured_result = {'title': 'Test', 'score': 0.9}
reflection_guidance present: True
```

## 4. Dispatch wiring — output_schema configures workers per-dispatch

```bash
sed -n "393,400p" rlm_adk/dispatch.py
```

```output
                    # Wire structured output when output_schema provided
                    if output_schema is not None:
                        worker.output_schema = output_schema
                        worker.tools = [SetModelResponseTool(output_schema)]  # type: ignore[list-item]
                        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
                        worker.after_tool_callback = after_cb  # type: ignore[assignment]
                        worker.on_tool_error_callback = error_cb  # type: ignore[assignment]
                        worker._structured_result = None  # type: ignore[attr-defined]
```

After dispatch, structured results are extracted from `worker._structured_result` into `LLMResult.parsed`. The worker is then cleaned up (schema, tools, callbacks reset) so it can be reused.

```bash
sed -n "460,474p" rlm_adk/dispatch.py
```

```output
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

## 5. State discipline — local accumulators replace ctx.session.state reads

```bash
sed -n "11,16p" rlm_adk/dispatch.py
```

```output

State mutation discipline:
- All state writes go through Event objects via event_queue (AR-CRIT-001).
- Local accumulators in the closure replace ctx.session.state reads.
- Worker results are read from agent objects (_result, _result_ready) not state.
"""
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import inspect
from rlm_adk import dispatch

source = inspect.getsource(dispatch)
lines = source.split('\n')
code_lines = [
    ln for ln in lines
    if 'ctx.session.state' in ln
    and not ln.strip().startswith('#')
    and not ln.strip().startswith('\"')
    and not ln.strip().startswith(\"'\")
    and not ln.strip().startswith('-')
    and 'no direct' not in ln
]
print(f'ctx.session.state reads in dispatch.py code: {len(code_lines)}')
print('AR-CRIT-001 compliance: PASS' if len(code_lines) == 0 else 'AR-CRIT-001 compliance: FAIL')
"

```

```output
ctx.session.state reads in dispatch.py code: 0
AR-CRIT-001 compliance: PASS
```

## 6. Test suite — 19 tests across 7 TDD cycles

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_adk_worker_retry.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
19 passed
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_adk_worker_retry.py -v --tb=no 2>&1 | grep "PASSED\|FAILED" | sed "s/ PASSED/: PASS/" | sed "s/ FAILED/: FAIL/"
```

```output
tests_rlm_adk/test_adk_worker_retry.py::TestDispatchNoSessionStateReads::test_dispatch_source_has_no_session_state_reads: PASS [  5%]
tests_rlm_adk/test_adk_worker_retry.py::TestLLMResultParsed::test_parsed_default_none: PASS [ 10%]
tests_rlm_adk/test_adk_worker_retry.py::TestLLMResultParsed::test_parsed_carries_dict: PASS [ 15%]
tests_rlm_adk/test_adk_worker_retry.py::TestLLMResultParsed::test_parsed_backward_compat: PASS [ 21%]
tests_rlm_adk/test_adk_worker_retry.py::TestWorkerRetryPlugin::test_inherits_reflect_and_retry: PASS [ 26%]
tests_rlm_adk/test_adk_worker_retry.py::TestWorkerRetryPlugin::test_extract_error_empty_response: PASS [ 31%]
tests_rlm_adk/test_adk_worker_retry.py::TestWorkerRetryPlugin::test_extract_error_valid_response_returns_none: PASS [ 36%]
tests_rlm_adk/test_adk_worker_retry.py::TestWorkerRetryPlugin::test_extract_error_ignores_other_tools: PASS [ 42%]
tests_rlm_adk/test_adk_worker_retry.py::TestMakeWorkerToolCallbacks::test_returns_two_callables: PASS [ 47%]
tests_rlm_adk/test_adk_worker_retry.py::TestMakeWorkerToolCallbacks::test_after_cb_stores_structured_result: PASS [ 52%]
tests_rlm_adk/test_adk_worker_retry.py::TestMakeWorkerToolCallbacks::test_after_cb_ignores_non_set_model_response: PASS [ 57%]
tests_rlm_adk/test_adk_worker_retry.py::TestMakeWorkerToolCallbacks::test_error_cb_returns_reflection_on_error: PASS [ 63%]
tests_rlm_adk/test_adk_worker_retry.py::TestMakeWorkerToolCallbacks::test_error_cb_raises_after_max_retries: PASS [ 68%]
tests_rlm_adk/test_adk_worker_retry.py::TestDispatchOutputSchema::test_llm_query_async_signature_accepts_output_schema: PASS [ 73%]
tests_rlm_adk/test_adk_worker_retry.py::TestDispatchOutputSchema::test_llm_query_batched_async_signature_accepts_output_schema: PASS [ 78%]
tests_rlm_adk/test_adk_worker_retry.py::TestDispatchSchemaWiring::test_dispatch_with_schema_sets_worker_attrs: PASS [ 84%]
tests_rlm_adk/test_adk_worker_retry.py::TestDispatchSchemaWiring::test_dispatch_cleanup_resets_schema_attrs: PASS [ 89%]
tests_rlm_adk/test_adk_worker_retry.py::TestStructuredResultExtraction::test_structured_result_populates_parsed: PASS [ 94%]
tests_rlm_adk/test_adk_worker_retry.py::TestStructuredResultExtraction::test_no_schema_result_has_no_parsed: PASS [100%]
```

All 19 tests pass across 7 TDD cycles: state discipline (Cycle 0), LLMResult.parsed (Cycle 1), WorkerRetryPlugin (Cycle 2), callback wrappers (Cycle 3), output_schema parameter (Cycle 4), dispatch wiring (Cycle 5), and structured result extraction (Cycle 6).
