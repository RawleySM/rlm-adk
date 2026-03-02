"""Tests for WorkerRetryPlugin structured output self-healing.

Covers:
- Cycle 0: No ctx.session.state reads in dispatch.py
- Cycle 1: LLMResult.parsed field
- Cycle 2: WorkerRetryPlugin subclass
- Cycle 3: make_worker_tool_callbacks() wrappers
- Cycle 4: llm_query_async accepts output_schema
- Cycle 5: Worker gets schema + tools + callbacks when output_schema provided
- Cycle 6: Structured result extraction into LLMResult.parsed
- Cycle 7: BUG-13 patch wrapper suppresses retry responses (FM-21)
- Cycle 8: BUG-13 patch idempotency (FM-21)
- FM-16 (Item 19): after_tool_cb delegation with empty value triggers retry
"""

import asyncio
import inspect
import json
from unittest.mock import MagicMock

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.types import LLMResult


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_invocation_context(invocation_id: str = "test") -> MagicMock:
    """Build a mock InvocationContext for dispatch closure tests."""
    ctx = MagicMock()
    ctx.invocation_id = invocation_id
    # Provide session.state as a real dict so closures can interact with it
    ctx.session.state = {}
    return ctx


# ── Cycle 0: No ctx.session.state reads in dispatch.py ──────────────────


class TestDispatchNoSessionStateReads:
    """Dispatch closures must not read from ctx.session.state."""

    def test_dispatch_source_has_no_session_state_reads(self):
        """Verify dispatch.py contains zero ctx.session.state references in code."""
        from rlm_adk import dispatch

        source = inspect.getsource(dispatch)
        lines = source.split("\n")
        code_lines = [
            ln
            for ln in lines
            if "ctx.session.state" in ln
            and not ln.strip().startswith("#")
            and not ln.strip().startswith('"')
            and not ln.strip().startswith("'")
            and not ln.strip().startswith("-")  # docstring bullet points
            and "no direct" not in ln  # docstring references
        ]
        assert code_lines == [], f"Found ctx.session.state reads: {code_lines}"


# ── Cycle 1: LLMResult.parsed field ─────────────────────────────────────


class TestLLMResultParsed:
    def test_parsed_default_none(self):
        r = LLMResult("hello")
        assert r.parsed is None

    def test_parsed_carries_dict(self):
        r = LLMResult('{"a":1}', parsed={"a": 1})
        assert r.parsed == {"a": 1}
        assert str(r) == '{"a":1}'

    def test_parsed_backward_compat(self):
        r = LLMResult("text", error=True, error_category="TIMEOUT")
        assert r.error is True
        assert r.parsed is None


# ── Cycle 2: WorkerRetryPlugin subclass ──────────────────────────────────


class TestWorkerRetryPlugin:
    def test_inherits_reflect_and_retry(self):
        from google.adk.plugins.reflect_retry_tool_plugin import (
            ReflectAndRetryToolPlugin,
        )

        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin(max_retries=2)
        assert isinstance(plugin, ReflectAndRetryToolPlugin)

    @pytest.mark.asyncio
    async def test_extract_error_empty_response(self):
        """set_model_response with empty string should return error."""
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin()
        tool = MagicMock()
        tool.name = "set_model_response"
        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={"summary": ""},
            tool_context=MagicMock(),
            result={"summary": ""},
        )
        assert error is not None
        assert "empty" in error["details"].lower()

    @pytest.mark.asyncio
    async def test_extract_error_valid_response_returns_none(self):
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin()
        tool = MagicMock()
        tool.name = "set_model_response"
        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={"summary": "ok"},
            tool_context=MagicMock(),
            result={"summary": "ok"},
        )
        assert error is None

    @pytest.mark.asyncio
    async def test_extract_error_ignores_other_tools(self):
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin()
        tool = MagicMock()
        tool.name = "some_other_tool"
        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={},
            tool_context=MagicMock(),
            result={},
        )
        assert error is None


# ── Cycle 3: make_worker_tool_callbacks() wrappers ───────────────────────


class TestMakeWorkerToolCallbacks:
    @pytest.mark.asyncio
    async def test_returns_two_callables(self):
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
        assert callable(after_cb)
        assert callable(error_cb)

    @pytest.mark.asyncio
    async def test_after_cb_stores_structured_result(self):
        """On set_model_response success, validated dict stored on agent."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, _ = make_worker_tool_callbacks()
        tool = MagicMock()
        tool.name = "set_model_response"
        agent = MagicMock()
        agent._structured_result = None
        tool_context = MagicMock()
        tool_context._invocation_context.agent = agent
        tool_context.invocation_id = "inv-1"

        result = {"title": "Test", "score": 0.9}
        await after_cb(tool, {"title": "Test", "score": 0.9}, tool_context, result)

        assert agent._structured_result == {"title": "Test", "score": 0.9}

    @pytest.mark.asyncio
    async def test_after_cb_ignores_non_set_model_response(self):
        """Other tools should not set _structured_result."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, _ = make_worker_tool_callbacks()
        tool = MagicMock()
        tool.name = "some_tool"
        agent = MagicMock()
        agent._structured_result = None
        tool_context = MagicMock()
        tool_context._invocation_context.agent = agent
        tool_context.invocation_id = "inv-1"

        await after_cb(tool, {"data": "value"}, tool_context, {"data": "value"})

        assert agent._structured_result is None

    @pytest.mark.asyncio
    async def test_error_cb_returns_reflection_on_error(self):
        """Errors should produce reflection guidance, not raise (first attempt)."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        _, error_cb = make_worker_tool_callbacks(max_retries=2)
        tool = MagicMock()
        tool.name = "set_model_response"
        tool_context = MagicMock()
        tool_context.invocation_id = "inv-1"
        error = ValueError("bad schema")

        guidance = await error_cb(tool, {"bad": "data"}, tool_context, error)

        assert guidance is not None
        assert "reflection_guidance" in guidance

    @pytest.mark.asyncio
    async def test_error_cb_raises_after_max_retries(self):
        """After max_retries exhausted, should raise the error."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        _, error_cb = make_worker_tool_callbacks(max_retries=1)
        tool = MagicMock()
        tool.name = "set_model_response"
        tool_context = MagicMock()
        tool_context.invocation_id = "inv-1"
        error = ValueError("bad schema")

        # First attempt: reflection guidance
        r1 = await error_cb(tool, {}, tool_context, error)
        assert r1 is not None

        # Second attempt: should raise
        with pytest.raises(ValueError, match="bad schema"):
            await error_cb(tool, {}, tool_context, error)


# ── Cycle 4: llm_query_async accepts output_schema ──────────────────────


class TestDispatchOutputSchema:
    @pytest.mark.asyncio
    async def test_llm_query_async_signature_accepts_output_schema(self):
        """llm_query_async should accept output_schema kwarg."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)
        sig = inspect.signature(llm_query_async)
        assert "output_schema" in sig.parameters

    @pytest.mark.asyncio
    async def test_llm_query_batched_async_signature_accepts_output_schema(self):
        """llm_query_batched_async should accept output_schema kwarg."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        _, llm_query_batched_async, _ = create_dispatch_closures(pool, ctx, eq)
        sig = inspect.signature(llm_query_batched_async)
        assert "output_schema" in sig.parameters


# ── Cycle 5: Worker gets schema + tools + callbacks ──────────────────────


def _patch_worker_run(worker, run_fn):
    """Patch run_async on a Pydantic LlmAgent using object.__setattr__."""
    object.__setattr__(worker, "run_async", run_fn)


class TestDispatchSchemaWiring:
    @pytest.mark.asyncio
    async def test_dispatch_with_schema_sets_worker_attrs(self):
        """Full dispatch with output_schema should configure worker."""
        from pydantic import BaseModel

        class TestSchema(BaseModel):
            answer: str

        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        captured_state = {}
        worker = pool._pools["test-model"].get_nowait()

        async def capture_run(_ctx):
            captured_state["output_schema"] = worker.output_schema
            captured_state["tools"] = list(worker.tools)
            captured_state["after_tool_callback"] = worker.after_tool_callback
            captured_state["on_tool_error_callback"] = worker.on_tool_error_callback
            worker._result = '{"answer": "test"}'  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            worker._structured_result = {"answer": "test"}  # type: ignore[attr-defined]
            return
            yield  # make it an async generator

        _patch_worker_run(worker, capture_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)

        await llm_query_async("test prompt", output_schema=TestSchema)

        assert captured_state["output_schema"] is TestSchema
        assert len(captured_state["tools"]) > 0
        assert captured_state["after_tool_callback"] is not None
        assert captured_state["on_tool_error_callback"] is not None

    @pytest.mark.asyncio
    async def test_dispatch_cleanup_resets_schema_attrs(self):
        """After dispatch, worker schema/tools/callbacks must be reset."""
        from pydantic import BaseModel

        class TestSchema(BaseModel):
            answer: str

        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        worker = pool._pools["test-model"].get_nowait()

        async def noop_run(_):
            worker._result = "done"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield  # make it an async generator

        _patch_worker_run(worker, noop_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)

        await llm_query_async("test", output_schema=TestSchema)

        # Worker should be back in pool with attrs reset
        released = await pool.acquire()
        assert released.output_schema is None
        assert released.tools == []
        assert released.after_tool_callback is None
        assert released.on_tool_error_callback is None


# ── Cycle 6: Structured result extraction into LLMResult.parsed ──────────


class TestStructuredResultExtraction:
    @pytest.mark.asyncio
    async def test_structured_result_populates_parsed(self):
        """When worker._structured_result is set, LLMResult.parsed should contain it."""
        from pydantic import BaseModel

        class TestSchema(BaseModel):
            answer: str
            score: float

        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        worker = pool._pools["test-model"].get_nowait()

        async def mock_run(_):
            worker._result = '{"answer":"test","score":0.95}'  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            worker._structured_result = {"answer": "test", "score": 0.95}  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, mock_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)

        result = await llm_query_async("analyze this", output_schema=TestSchema)

        assert result.parsed is not None
        assert result.parsed["answer"] == "test"
        assert result.parsed["score"] == 0.95
        assert '"answer"' in str(result)

    @pytest.mark.asyncio
    async def test_no_schema_result_has_no_parsed(self):
        """Without output_schema, result.parsed should be None."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        worker = pool._pools["test-model"].get_nowait()

        async def mock_run(_):
            worker._result = "plain text response"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, mock_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)

        result = await llm_query_async("just a question")

        assert result.parsed is None
        assert str(result) == "plain text response"


# ── Cycle 7: BUG-13 patch wrapper suppresses retry responses (FM-21) ────


class TestPatchWrapperSuppressesRetryResponse:
    """Directly test _retry_aware_get_structured_model_response wrapper."""

    def test_suppress_retry_response_returns_none(self):
        """When function_response contains REFLECT_AND_RETRY_RESPONSE_TYPE sentinel,
        the patched wrapper should return None (suppressing premature termination)."""
        from google.adk.events import Event
        from google.adk.plugins.reflect_retry_tool_plugin import (
            REFLECT_AND_RETRY_RESPONSE_TYPE,
        )
        from google.genai import types

        from rlm_adk.callbacks.worker_retry import _bug13_stats

        import google.adk.flows.llm_flows._output_schema_processor as _osp

        # Verify the patch is installed
        assert getattr(_osp.get_structured_model_response, "_rlm_patched", False), \
            "BUG-13 patch not installed on get_structured_model_response"

        # Build a mock function_response_event with the retry sentinel
        retry_payload = {
            "response_type": REFLECT_AND_RETRY_RESPONSE_TYPE,
            "reflection_guidance": "Please fix the empty field",
        }
        event = Event(
            invocation_id="test-inv",
            author="worker",
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name="set_model_response",
                            response=retry_payload,
                        )
                    )
                ],
            ),
        )

        # Record suppress_count before the call
        before_count = _bug13_stats["suppress_count"]

        result = _osp.get_structured_model_response(event)

        # The wrapper should return None for retry responses
        assert result is None, (
            f"Expected None for retry sentinel, got {result!r}"
        )

        # Verify suppress_count was incremented
        assert _bug13_stats["suppress_count"] == before_count + 1

    def test_normal_response_passes_through(self):
        """A normal set_model_response (no retry sentinel) should pass through unchanged."""
        from google.adk.events import Event
        from google.genai import types

        import google.adk.flows.llm_flows._output_schema_processor as _osp

        normal_payload = {"answer": "The result", "score": 0.95}
        event = Event(
            invocation_id="test-inv",
            author="worker",
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name="set_model_response",
                            response=normal_payload,
                        )
                    )
                ],
            ),
        )

        result = _osp.get_structured_model_response(event)

        # Should return a JSON string (not None)
        assert result is not None, "Normal response should not be suppressed"
        parsed = json.loads(result)
        assert parsed["answer"] == "The result"
        assert parsed["score"] == 0.95

    def test_non_set_model_response_returns_none(self):
        """An event without set_model_response should return None."""
        from google.adk.events import Event
        from google.genai import types

        import google.adk.flows.llm_flows._output_schema_processor as _osp

        event = Event(
            invocation_id="test-inv",
            author="worker",
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name="execute_code",
                            response={"output": "hello"},
                        )
                    )
                ],
            ),
        )

        result = _osp.get_structured_model_response(event)
        assert result is None


# ── Cycle 8: BUG-13 patch idempotency (FM-21) ───────────────────────────


class TestPatchIdempotency:
    """Calling _patch_output_schema_postprocessor() multiple times must install
    the wrapper exactly once."""

    def test_patch_idempotency(self):
        """Second call to _patch_output_schema_postprocessor() is a no-op.

        The wrapper checks for the _rlm_patched sentinel attribute and returns
        early if already patched. Verify the function reference does not change.
        """
        from rlm_adk.callbacks.worker_retry import _patch_output_schema_postprocessor

        import google.adk.flows.llm_flows._output_schema_processor as _osp

        # The patch is already installed at module import time.
        # Capture the current wrapper reference.
        first_ref = _osp.get_structured_model_response
        assert getattr(first_ref, "_rlm_patched", False), \
            "Patch should already be installed"

        # Call the patch function again
        _patch_output_schema_postprocessor()

        # The reference should be identical (no double-wrapping)
        second_ref = _osp.get_structured_model_response
        assert first_ref is second_ref, (
            "Calling _patch_output_schema_postprocessor() twice should not "
            "double-wrap the function. The _rlm_patched guard should prevent this."
        )


# ── FM-16 (Item 19): after_tool_cb empty value triggers retry ────────────


class TestAfterToolCallbackEmptyValueRetry:
    """FM-16: after_tool_cb -> plugin.after_tool_callback delegation with empty
    value triggers extract_error_from_result and retry engagement."""

    @pytest.mark.asyncio
    async def test_empty_value_in_set_model_response_returns_retry_guidance(self):
        """When set_model_response has an empty string value, after_tool_cb
        should return a retry guidance dict (not None)."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, _ = make_worker_tool_callbacks(max_retries=2)
        tool = MagicMock()
        tool.name = "set_model_response"
        agent = MagicMock()
        agent.name = "worker_test"
        agent._structured_result = None
        tool_context = MagicMock()
        tool_context._invocation_context.agent = agent
        tool_context.invocation_id = "inv-test"

        # Empty string value should trigger extract_error_from_result
        tool_response = {"summary": "   "}
        result = await after_cb(
            tool, {"summary": "   "}, tool_context, tool_response,
        )

        # The plugin should detect the empty value and return retry guidance
        assert result is not None, (
            "Expected retry guidance dict for empty value, got None"
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_nonempty_value_does_not_trigger_retry(self):
        """When set_model_response has valid values, after_tool_cb should
        capture the result and return None (no retry)."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, _ = make_worker_tool_callbacks(max_retries=2)
        tool = MagicMock()
        tool.name = "set_model_response"
        agent = MagicMock()
        agent.name = "worker_test"
        agent._structured_result = None
        tool_context = MagicMock()
        tool_context._invocation_context.agent = agent
        tool_context.invocation_id = "inv-test"

        tool_response = {"summary": "A valid summary of the analysis"}
        result = await after_cb(
            tool, {"summary": "A valid summary of the analysis"},
            tool_context, tool_response,
        )

        # No retry needed - result should be None
        assert result is None
        # Structured result should be captured on agent
        assert agent._structured_result == tool_response

    @pytest.mark.asyncio
    async def test_multiple_empty_fields_triggers_retry(self):
        """Multiple empty fields should still trigger retry."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, _ = make_worker_tool_callbacks(max_retries=2)
        tool = MagicMock()
        tool.name = "set_model_response"
        agent = MagicMock()
        agent.name = "worker_test"
        agent._structured_result = None
        tool_context = MagicMock()
        tool_context._invocation_context.agent = agent
        tool_context.invocation_id = "inv-test"

        tool_response = {"title": "", "body": ""}
        result = await after_cb(
            tool, {"title": "", "body": ""},
            tool_context, tool_response,
        )

        assert result is not None
        assert isinstance(result, dict)
