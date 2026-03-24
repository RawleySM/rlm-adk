"""Tests for rlm_adk.repl.thread_bridge -- sync bridge for cross-thread dispatch."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import time
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Cycle 1-2: make_sync_llm_query -- basic dispatch, timeout, errors, depth
# ---------------------------------------------------------------------------


class TestMakeSyncLlmQuery:
    """Cycle 1-2: make_sync_llm_query factory and its sync closure."""

    def test_dispatches_from_worker_thread(self) -> None:
        """Sync wrapper dispatches async coroutine via run_coroutine_threadsafe
        from a worker thread and returns the result."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def fake_llm_query_async(prompt: str, **kwargs) -> str:
            await asyncio.sleep(0.01)
            return f"echo:{prompt}"

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query = make_sync_llm_query(fake_llm_query_async, loop)
            # Call from a worker thread (simulates REPL execution context)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(
                    pool, llm_query, "hello"
                )
            assert result == "echo:hello"

        loop.run_until_complete(_run())
        loop.close()

    def test_passes_keyword_args(self) -> None:
        """Keyword arguments (model=, output_schema=) pass through to async callable."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        captured_kwargs: dict = {}

        async def fake_llm_query_async(prompt: str, **kwargs) -> str:
            captured_kwargs.update(kwargs)
            return "ok"

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query = make_sync_llm_query(fake_llm_query_async, loop)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(
                    pool,
                    lambda: llm_query("test", model="gemini-pro", output_schema={"type": "string"}),
                )
            assert result == "ok"
            assert captured_kwargs["model"] == "gemini-pro"
            assert captured_kwargs["output_schema"] == {"type": "string"}

        loop.run_until_complete(_run())
        loop.close()

    # ---- Cycle 2: timeout, error propagation, thread depth limit ----

    def test_timeout_raises(self) -> None:
        """Sync wrapper raises TimeoutError when async dispatch exceeds timeout."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def slow_query(prompt: str, **kwargs) -> str:
            await asyncio.sleep(999)
            return "never"

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query = make_sync_llm_query(slow_query, loop, timeout=0.1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(TimeoutError):
                    await loop.run_in_executor(pool, llm_query, "hello")

        loop.run_until_complete(_run())
        loop.close()

    def test_error_propagation(self) -> None:
        """Exceptions from async dispatch propagate to calling worker thread."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def failing_query(prompt: str, **kwargs) -> str:
            raise ValueError("test error")

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query = make_sync_llm_query(failing_query, loop)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(ValueError, match="test error"):
                    await loop.run_in_executor(pool, llm_query, "hello")

        loop.run_until_complete(_run())
        loop.close()

    def test_thread_depth_limit(self) -> None:
        """RuntimeError raised when thread depth exceeds max_thread_depth."""
        from rlm_adk.repl.thread_bridge import _THREAD_DEPTH, make_sync_llm_query

        async def counting_query(prompt: str, **kwargs) -> str:
            return "ok"

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query = make_sync_llm_query(
                counting_query, loop, max_thread_depth=2
            )

            def _call_at_depth_limit():
                # First call should work (depth 0 -> 1 during call)
                result = llm_query("first")
                assert result == "ok"

                # Manually set depth to the limit to simulate deep recursion
                _THREAD_DEPTH.set(2)
                with pytest.raises(RuntimeError, match="Thread depth limit exceeded: 2/2"):
                    llm_query("should_fail")
                # Reset for cleanup
                _THREAD_DEPTH.set(0)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _call_at_depth_limit)

        loop.run_until_complete(_run())
        loop.close()


# ---------------------------------------------------------------------------
# Cycle 3: make_sync_llm_query_batched -- batched dispatch
# ---------------------------------------------------------------------------


class TestMakeSyncLlmQueryBatched:
    """Cycle 3: make_sync_llm_query_batched factory."""

    def test_batched_returns_list(self) -> None:
        """Batched wrapper returns a list matching input length."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def fake_batched_async(prompts: list[str], **kwargs) -> list[str]:
            return [f"echo:{p}" for p in prompts]

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                fake_batched_async, loop
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(
                    pool,
                    lambda: llm_query_batched(["a", "b", "c"]),
                )
            assert result == ["echo:a", "echo:b", "echo:c"]
            assert len(result) == 3

        loop.run_until_complete(_run())
        loop.close()

    def test_batched_runs_concurrently(self) -> None:
        """N children run concurrently: 3 x 0.1s sleeps complete in ~0.1s, not ~0.3s."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def slow_batched_async(prompts: list[str], **kwargs) -> list[str]:
            async def _one(p: str) -> str:
                await asyncio.sleep(0.1)
                return f"done:{p}"
            return await asyncio.gather(*[_one(p) for p in prompts])

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                slow_batched_async, loop
            )

            def _timed_call():
                start = time.monotonic()
                result = llm_query_batched(["a", "b", "c"])
                elapsed = time.monotonic() - start
                assert len(result) == 3
                # Should be ~0.1s (concurrent), not ~0.3s (sequential)
                assert elapsed < 0.25, f"Took {elapsed:.2f}s -- children ran sequentially"
                return result

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _timed_call)

        loop.run_until_complete(_run())
        loop.close()

    def test_batched_timeout(self) -> None:
        """Timeout raises TimeoutError for batched dispatch."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def slow_batched_async(prompts: list[str], **kwargs) -> list[str]:
            await asyncio.sleep(999)
            return []

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                slow_batched_async, loop, timeout=0.1
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(TimeoutError):
                    await loop.run_in_executor(
                        pool, lambda: llm_query_batched(["a"])
                    )

        loop.run_until_complete(_run())
        loop.close()

    def test_batched_error_propagation(self) -> None:
        """Exceptions from batched async dispatch propagate to worker thread."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def failing_batched_async(prompts: list[str], **kwargs) -> list[str]:
            raise ValueError("batch error")

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                failing_batched_async, loop
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(ValueError, match="batch error"):
                    await loop.run_in_executor(
                        pool, lambda: llm_query_batched(["a"])
                    )

        loop.run_until_complete(_run())
        loop.close()


# ---------------------------------------------------------------------------
# Cycle 4: LocalREPL._execute_code_threadsafe -- lock-free execution
# ---------------------------------------------------------------------------


class TestExecuteCodeThreadsafe:
    """Cycle 4: _execute_code_threadsafe on LocalREPL."""

    def _make_repl(self):
        from rlm_adk.repl.local_repl import LocalREPL
        return LocalREPL(depth=1)

    def test_executes_simple_code(self) -> None:
        """Simple code executes and returns (stdout, stderr, success)."""
        repl = self._make_repl()
        try:
            stdout, stderr, success = repl._execute_code_threadsafe("x = 42\nprint(x)")
            assert success is True
            assert "42" in stdout
            assert stderr == ""
        finally:
            repl.cleanup()

    def test_does_not_acquire_exec_lock(self) -> None:
        """_execute_code_threadsafe does NOT deadlock when _EXEC_LOCK is held."""
        from rlm_adk.repl.local_repl import _EXEC_LOCK

        repl = self._make_repl()
        result_holder: list = []
        error_holder: list = []

        def _hold_lock():
            """Hold _EXEC_LOCK for 3 seconds."""
            with _EXEC_LOCK:
                time.sleep(3)

        def _run_threadsafe():
            try:
                out, err, ok = repl._execute_code_threadsafe("y = 99\nprint(y)")
                result_holder.append((out, err, ok))
            except Exception as e:
                error_holder.append(e)

        try:
            lock_thread = threading.Thread(target=_hold_lock, daemon=True)
            lock_thread.start()
            # Give the lock thread a moment to acquire
            time.sleep(0.1)

            exec_thread = threading.Thread(target=_run_threadsafe, daemon=True)
            exec_thread.start()
            # Should complete well before the 3s lock hold
            exec_thread.join(timeout=2.0)

            assert not exec_thread.is_alive(), "_execute_code_threadsafe deadlocked on _EXEC_LOCK"
            assert len(error_holder) == 0, f"Unexpected error: {error_holder}"
            assert len(result_holder) == 1
            stdout, stderr, success = result_holder[0]
            assert success is True
            assert "99" in stdout
        finally:
            lock_thread.join(timeout=5)
            repl.cleanup()

    def test_captures_stdout_via_contextvar(self) -> None:
        """stdout/stderr captured via ContextVar, not global sys.stdout swap."""
        from rlm_adk.repl.local_repl import _capture_stdout

        repl = self._make_repl()
        try:
            # Verify no ContextVar buffer is set before the call
            assert _capture_stdout.get(None) is None

            stdout, stderr, success = repl._execute_code_threadsafe(
                "print('contextvar_test')"
            )
            assert success is True
            assert "contextvar_test" in stdout

            # After call, ContextVar should be cleaned up (no lingering buffer)
            assert _capture_stdout.get(None) is None
        finally:
            repl.cleanup()

    def test_updates_locals_on_success(self) -> None:
        """self.locals updated with new variables on success."""
        repl = self._make_repl()
        try:
            repl._execute_code_threadsafe("a = 10\nb = 20")
            assert repl.locals.get("a") == 10
            assert repl.locals.get("b") == 20
        finally:
            repl.cleanup()

    def test_sets_last_exec_error_on_failure(self) -> None:
        """self._last_exec_error set on execution failure."""
        repl = self._make_repl()
        try:
            stdout, stderr, success = repl._execute_code_threadsafe(
                "raise ValueError('boom')"
            )
            assert success is False
            assert repl._last_exec_error is not None
            assert "boom" in repl._last_exec_error
        finally:
            repl.cleanup()

    def test_uses_cwd_open_not_chdir(self) -> None:
        """open() inside code resolves to temp_dir, not process CWD."""
        repl = self._make_repl()
        try:
            repl._execute_code_threadsafe(
                "f = open('test_file.txt', 'w')\nf.write('hello')\nf.close()"
            )
            # File should exist in repl.temp_dir, not in process CWD
            expected_path = os.path.join(repl.temp_dir, "test_file.txt")
            assert os.path.exists(expected_path), (
                f"File not found at {expected_path}"
            )
            with open(expected_path) as f:
                assert f.read() == "hello"
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 5: LocalREPL.execute_code_threaded -- async wrapper with one-shot executor
# ---------------------------------------------------------------------------


class TestExecuteCodeThreaded:
    """Cycle 5: execute_code_threaded async wrapper."""

    def _make_repl(self, sync_timeout: float | None = None):
        from rlm_adk.repl.local_repl import LocalREPL
        repl = LocalREPL(depth=1, sync_timeout=sync_timeout)
        return repl

    @pytest.mark.asyncio
    async def test_returns_repl_result(self) -> None:
        """Returns a REPLResult with stdout, stderr, locals, execution_time."""
        from rlm_adk.types import REPLResult

        repl = self._make_repl()
        try:
            result = await repl.execute_code_threaded("x = 42\nprint(x)")
            assert isinstance(result, REPLResult)
            assert "42" in result.stdout
            assert result.stderr == ""
            assert "x" in result.locals
            assert result.locals["x"] == 42
            assert result.execution_time is not None
            assert result.execution_time >= 0
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_timeout_produces_error_result(self) -> None:
        """Code exceeding sync_timeout returns REPLResult with timeout error."""
        repl = self._make_repl(sync_timeout=0.5)
        try:
            # Inject a sleep function into REPL globals
            import time as _time
            repl.globals["_sleep"] = _time.sleep
            result = await repl.execute_code_threaded("_sleep(10)")
            assert "TimeoutError" in result.stderr or "timeout" in result.stderr.lower()
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_sets_trace_execution_mode(self) -> None:
        """When REPLTrace provided, trace.execution_mode is set to 'thread_bridge'."""
        from rlm_adk.repl.trace import REPLTrace

        repl = self._make_repl()
        trace = REPLTrace(
            submitted_code_chars=10,
            submitted_code_hash="abc",
            submitted_code_preview="x = 1",
        )
        try:
            result = await repl.execute_code_threaded("x = 1", trace=trace)
            assert trace.execution_mode == "thread_bridge"
            assert result.stdout == ""
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_one_shot_executor_cleanup(self) -> None:
        """One-shot ThreadPoolExecutor is cleaned up; thread count doesn't grow."""
        repl = self._make_repl()
        try:
            initial_threads = threading.active_count()
            for _ in range(5):
                await repl.execute_code_threaded("y = 1")
            # Allow a small margin for thread cleanup timing
            final_threads = threading.active_count()
            # Should not have accumulated 5 extra threads
            assert final_threads <= initial_threads + 2, (
                f"Thread leak: started with {initial_threads}, ended with {final_threads}"
            )
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 6: REPLTool thread bridge + _finalize_telemetry in finally
# ---------------------------------------------------------------------------


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Build a mock ToolContext with dict-backed .state."""
    ctx = MagicMock()
    ctx.state = dict(state or {})
    ctx.actions = MagicMock()
    return ctx


class TestREPLToolThreadBridge:
    """Cycle 6: REPLTool uses execute_code_threaded + finalize in finally."""

    def _make_repl_tool(self, *, telemetry_finalizer=None):
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.tools.repl_tool import REPLTool

        repl = LocalREPL(depth=1)
        tool = REPLTool(
            repl,
            max_calls=10,
            depth=0,
            telemetry_finalizer=telemetry_finalizer,
        )
        return repl, tool

    @pytest.mark.asyncio
    async def test_uses_thread_bridge_for_execution(self) -> None:
        """REPLTool calls repl.execute_code_threaded(), not repl.execute_code()."""
        repl, tool = self._make_repl_tool()
        try:
            tc = _make_tool_context()
            result = await tool.run_async(
                args={"code": "x = 42\nprint(x)"},
                tool_context=tc,
            )
            assert "42" in result["stdout"]
            assert result["stderr"] == ""
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_execution_mode_in_result(self) -> None:
        """LAST_REPL_RESULT contains execution_mode field."""
        from rlm_adk.state import LAST_REPL_RESULT, depth_key

        repl, tool = self._make_repl_tool()
        try:
            tc = _make_tool_context()
            await tool.run_async(
                args={"code": "y = 1"},
                tool_context=tc,
            )
            last_repl = tc.state.get(depth_key(LAST_REPL_RESULT, 0))
            assert last_repl is not None
            assert "execution_mode" in last_repl
            assert last_repl["execution_mode"] == "thread_bridge"
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_finalize_telemetry_called_on_success(self) -> None:
        """Telemetry finalizer is called on successful execution."""
        calls = []
        repl, tool = self._make_repl_tool(
            telemetry_finalizer=lambda key, res: calls.append((key, res)),
        )
        try:
            tc = _make_tool_context()
            await tool.run_async(
                args={"code": "z = 1"},
                tool_context=tc,
            )
            assert len(calls) == 1
            assert calls[0][0] == id(tc)
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_finalize_telemetry_called_on_exception(self) -> None:
        """Telemetry finalizer is called even when execute_code_threaded raises."""
        calls = []
        repl, tool = self._make_repl_tool(
            telemetry_finalizer=lambda key, res: calls.append((key, res)),
        )
        try:
            # Monkey-patch execute_code_threaded to raise
            async def _raise(*a, **kw):
                raise RuntimeError("injected error")

            repl.execute_code_threaded = _raise
            tc = _make_tool_context()
            result = await tool.run_async(
                args={"code": "noop = 1"},
                tool_context=tc,
            )
            # Should not crash — exception is caught and telemetry still fires
            assert "injected error" in result["stderr"]
            assert len(calls) == 1
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_finalize_telemetry_called_on_cancel(self) -> None:
        """Telemetry finalizer is called on CancelledError."""
        calls = []
        repl, tool = self._make_repl_tool(
            telemetry_finalizer=lambda key, res: calls.append((key, res)),
        )
        try:
            async def _cancel(*a, **kw):
                raise asyncio.CancelledError("test cancel")

            repl.execute_code_threaded = _cancel
            tc = _make_tool_context()
            result = await tool.run_async(
                args={"code": "noop = 1"},
                tool_context=tc,
            )
            assert "CancelledError" in result["stderr"]
            assert len(calls) == 1
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 7: Orchestrator sync bridge wiring
# ---------------------------------------------------------------------------


class TestOrchestratorWiring:
    """Cycle 7: Orchestrator wires sync bridge to REPL globals."""

    def test_sync_llm_query_wired_to_repl_globals(self) -> None:
        """After make_sync_llm_query, the returned closure is callable."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def fake_async(prompt, **kw):
            return f"result:{prompt}"

        loop = asyncio.new_event_loop()
        llm_query = make_sync_llm_query(fake_async, loop)
        # Simulate what orchestrator does: wire into repl globals
        assert callable(llm_query)
        loop.close()

    def test_sync_llm_query_dispatches_from_worker_thread(self) -> None:
        """Calling the wired sync llm_query from a worker thread succeeds."""
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.repl.thread_bridge import (
            make_sync_llm_query,
            make_sync_llm_query_batched,
        )

        async def fake_async(prompt, **kw):
            await asyncio.sleep(0.01)
            return f"result:{prompt}"

        async def fake_batched_async(prompts, **kw):
            return [f"result:{p}" for p in prompts]

        loop = asyncio.new_event_loop()
        repl = LocalREPL(depth=1)

        async def _run():
            # Wire sync bridge the same way the orchestrator will
            repl.set_llm_query_fns(
                make_sync_llm_query(fake_async, loop),
                make_sync_llm_query_batched(fake_batched_async, loop),
            )
            # Verify the globals are set
            assert callable(repl.globals.get("llm_query"))
            assert callable(repl.globals.get("llm_query_batched"))

            # Execute code that calls llm_query from a worker thread
            result = await repl.execute_code_threaded(
                "answer = llm_query('hello')\nprint(answer)"
            )
            assert "result:hello" in result.stdout
            assert repl.locals.get("answer") == "result:hello"

        try:
            loop.run_until_complete(_run())
        finally:
            repl.cleanup()
            loop.close()

    def test_orchestrator_imports_thread_bridge(self) -> None:
        """The orchestrator module can import thread bridge factories."""
        # This verifies the import path is valid, which will be used
        # in the orchestrator wiring code.
        from rlm_adk.repl.thread_bridge import (  # noqa: F401
            make_sync_llm_query,
            make_sync_llm_query_batched,
        )

        assert callable(make_sync_llm_query)
        assert callable(make_sync_llm_query_batched)


# ---------------------------------------------------------------------------
# Cycle 8: execution_mode in LAST_REPL_RESULT observability
# ---------------------------------------------------------------------------


class TestExecutionModeObservability:
    """Cycle 8: execution_mode flows through trace and LAST_REPL_RESULT."""

    @pytest.mark.asyncio
    async def test_last_repl_result_has_execution_mode(self) -> None:
        """LAST_REPL_RESULT state contains execution_mode key after run_async."""
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.state import LAST_REPL_RESULT, depth_key
        from rlm_adk.tools.repl_tool import REPLTool

        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)
        try:
            tc = _make_tool_context()
            await tool.run_async(
                args={"code": "x = 1"},
                tool_context=tc,
            )
            last_repl = tc.state.get(depth_key(LAST_REPL_RESULT, 0))
            assert last_repl is not None
            assert last_repl["execution_mode"] == "thread_bridge"
        finally:
            repl.cleanup()

    def test_trace_execution_mode_type(self) -> None:
        """REPLTrace.execution_mode accepts 'sync' and 'thread_bridge'."""
        from rlm_adk.repl.trace import REPLTrace

        # Default is "sync"
        t1 = REPLTrace(
            submitted_code_chars=5,
            submitted_code_hash="abc",
            submitted_code_preview="x=1",
        )
        assert t1.execution_mode == "sync"

        # Can be set to "thread_bridge"
        t2 = REPLTrace(
            submitted_code_chars=5,
            submitted_code_hash="abc",
            submitted_code_preview="x=1",
            execution_mode="thread_bridge",
        )
        assert t2.execution_mode == "thread_bridge"

    def test_trace_execution_mode_in_summary(self) -> None:
        """execution_mode appears in trace.summary() / to_dict()."""
        from rlm_adk.repl.trace import REPLTrace

        trace = REPLTrace(
            submitted_code_chars=5,
            submitted_code_hash="abc",
            submitted_code_preview="x=1",
            execution_mode="thread_bridge",
        )
        d = trace.to_dict()
        assert d["execution_mode"] == "thread_bridge"
