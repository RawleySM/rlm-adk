"""Tests for bifurcated worker wiring in dispatch (C3 fix).

Verifies that dispatch wires workers differently based on whether
worker_repl is provided:
1. When worker_repl is provided: worker gets REPLTool + output_schema
2. When worker_repl is None: worker gets explicit SetModelResponseTool
3. Cleanup resets all wiring (output_schema, tools, callbacks)
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures


# ── Helpers ──────────────────────────────────────────────────────────────


class SampleSchema(BaseModel):
    answer: str
    confidence: float = 0.0


def _make_invocation_context(invocation_id: str = "test") -> MagicMock:
    """Build a mock InvocationContext for dispatch closure tests."""
    ctx = MagicMock()
    ctx.invocation_id = invocation_id
    ctx.session.state = {}
    return ctx


def _patch_worker_run(worker, run_fn):
    """Patch run_async on a Pydantic LlmAgent using object.__setattr__."""
    object.__setattr__(worker, "run_async", run_fn)


# ── Bifurcated Wiring Tests ─────────────────────────────────────────────


class TestBifurcatedWiringWithRepl:
    """When worker_repl is provided, worker gets REPLTool + output_schema."""

    @pytest.mark.asyncio
    async def test_worker_gets_repl_tool_when_repl_provided(self):
        """With worker_repl, worker.tools should contain a REPLTool, not SetModelResponseTool."""
        from rlm_adk.tools.repl_tool import REPLTool

        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        captured_state = {}
        worker = pool._pools["test-model"].get_nowait()

        async def capture_run(_ctx):
            captured_state["output_schema"] = worker.output_schema
            captured_state["tools"] = list(worker.tools)
            captured_state["after_tool_callback"] = worker.after_tool_callback
            captured_state["on_tool_error_callback"] = worker.on_tool_error_callback
            worker._result = '{"answer": "test", "confidence": 0.9}'  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            worker._structured_result = {"answer": "test", "confidence": 0.9}  # type: ignore[attr-defined]
            return
            yield  # make it an async generator

        _patch_worker_run(worker, capture_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        mock_repl = MagicMock()  # stands in for LocalREPL

        llm_query_async, _, _ = create_dispatch_closures(
            pool, ctx, eq, worker_repl=mock_repl,
        )

        await llm_query_async("test prompt", output_schema=SampleSchema)

        assert captured_state["output_schema"] is SampleSchema
        assert len(captured_state["tools"]) > 0
        # The tool should be a REPLTool, not SetModelResponseTool
        tool = captured_state["tools"][0]
        assert isinstance(tool, REPLTool), f"Expected REPLTool, got {type(tool).__name__}"
        assert captured_state["after_tool_callback"] is not None
        assert captured_state["on_tool_error_callback"] is not None


class TestBifurcatedWiringWithoutRepl:
    """When worker_repl is None, worker gets SetModelResponseTool."""

    @pytest.mark.asyncio
    async def test_worker_gets_set_model_response_when_no_repl(self):
        """Without worker_repl, worker.tools should contain SetModelResponseTool."""
        from google.adk.tools.set_model_response_tool import SetModelResponseTool

        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        captured_state = {}
        worker = pool._pools["test-model"].get_nowait()

        async def capture_run(_ctx):
            captured_state["output_schema"] = worker.output_schema
            captured_state["tools"] = list(worker.tools)
            worker._result = '{"answer": "test", "confidence": 0.9}'  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            worker._structured_result = {"answer": "test", "confidence": 0.9}  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, capture_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()

        # No worker_repl parameter (or explicitly None)
        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)

        await llm_query_async("test prompt", output_schema=SampleSchema)

        assert captured_state["output_schema"] is SampleSchema
        assert len(captured_state["tools"]) > 0
        tool = captured_state["tools"][0]
        assert isinstance(tool, SetModelResponseTool), (
            f"Expected SetModelResponseTool, got {type(tool).__name__}"
        )


class TestBifurcatedWiringCleanup:
    """Cleanup resets all wiring regardless of repl presence."""

    @pytest.mark.asyncio
    async def test_cleanup_resets_all_attrs_with_repl(self):
        """After dispatch with worker_repl, worker attrs must be reset."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        worker = pool._pools["test-model"].get_nowait()

        async def noop_run(_):
            worker._result = "done"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, noop_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()
        mock_repl = MagicMock()

        llm_query_async, _, _ = create_dispatch_closures(
            pool, ctx, eq, worker_repl=mock_repl,
        )

        await llm_query_async("test", output_schema=SampleSchema)

        # Worker should be back in pool with attrs reset
        released = await pool.acquire()
        assert released.output_schema is None
        assert released.tools == []
        assert released.after_tool_callback is None
        assert released.on_tool_error_callback is None

    @pytest.mark.asyncio
    async def test_cleanup_resets_all_attrs_without_repl(self):
        """After dispatch without worker_repl, worker attrs must be reset."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        worker = pool._pools["test-model"].get_nowait()

        async def noop_run(_):
            worker._result = "done"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, noop_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        eq: asyncio.Queue = asyncio.Queue()

        llm_query_async, _, _ = create_dispatch_closures(pool, ctx, eq)

        await llm_query_async("test", output_schema=SampleSchema)

        released = await pool.acquire()
        assert released.output_schema is None
        assert released.tools == []
        assert released.after_tool_callback is None
        assert released.on_tool_error_callback is None


class TestCreateDispatchClosuresAcceptsWorkerRepl:
    """create_dispatch_closures should accept worker_repl parameter."""

    def test_signature_accepts_worker_repl(self):
        """create_dispatch_closures should have a worker_repl parameter."""
        import inspect
        sig = inspect.signature(create_dispatch_closures)
        assert "worker_repl" in sig.parameters, (
            f"create_dispatch_closures missing worker_repl parameter. "
            f"Params: {list(sig.parameters.keys())}"
        )
