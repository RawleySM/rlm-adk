"""Tests for dispatch.py fixes:
- Worker-object initialization (_result, _result_ready, _result_error)
- No direct ctx.session.state writes in dispatch
- on_model_error_callback registration on workers
"""

import ast
import inspect
import textwrap
from unittest.mock import MagicMock

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures


class TestWorkerObjectInitialization:
    """Workers created by _create_worker must have result carrier attributes."""

    def test_worker_has_result_attr(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert hasattr(worker, "_result")
        assert worker._result is None

    def test_worker_has_result_ready_attr(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert hasattr(worker, "_result_ready")
        assert worker._result_ready is False

    def test_worker_has_result_error_attr(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert hasattr(worker, "_result_error")
        assert worker._result_error is False


class TestWorkerErrorCallbackRegistration:
    """Workers must have on_model_error_callback registered."""

    def test_worker_has_on_model_error_callback(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert worker.on_model_error_callback is not None

    def test_worker_error_callback_is_worker_on_model_error(self):
        from rlm_adk.callbacks.worker import worker_on_model_error
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert worker.on_model_error_callback is worker_on_model_error


class TestNoDirectSessionStateWritesInDispatch:
    """dispatch.py must NOT contain any ctx.session.state[...] = ... writes.

    All state mutations must go through Event objects via event_queue.
    Reads from ctx.session.state.get() are acceptable.
    """

    def test_no_session_state_subscript_assign(self):
        """Static analysis: no ctx.session.state[key] = value in dispatch module."""
        from rlm_adk import dispatch
        source = textwrap.dedent(inspect.getsource(dispatch))
        tree = ast.parse(source)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if _is_session_state_subscript(target):
                        violations.append(
                            f"Line ~{node.lineno}: {ast.dump(target)}"
                        )

        assert violations == [], (
            f"Direct ctx.session.state writes found in dispatch.py: {violations}"
        )


class TestDispatchEmitsEventsForAccounting:
    """The dispatch closure should emit Event objects via event_queue for
    state accounting instead of writing directly to ctx.session.state."""

    @pytest.mark.asyncio
    async def test_empty_prompts_still_returns_empty(self):
        """Baseline: empty prompts returns []."""
        pool = WorkerPool(default_model="m", pool_size=1)
        pool.ensure_initialized()
        ctx = MagicMock()
        ctx.session.state = {}
        ctx.invocation_id = "test-inv"

        _, batched_fn, _ = create_dispatch_closures(pool, ctx)
        results = await batched_fn([])
        assert results == []


def _is_session_state_subscript(node: ast.AST) -> bool:
    """Check if an AST node is a subscript assignment to ctx.session.state[...]."""
    if not isinstance(node, ast.Subscript):
        return False
    # Look for pattern: *.session.state[...]
    value = node.value
    if isinstance(value, ast.Attribute) and value.attr == "state":
        inner = value.value
        if isinstance(inner, ast.Attribute) and inner.attr == "session":
            return True
    return False
