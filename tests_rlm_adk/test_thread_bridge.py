"""Tests for rlm_adk.repl.thread_bridge -- sync bridge for cross-thread dispatch."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import sys
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

    def test_batched_thread_depth_limit(self) -> None:
        """GAP-CB-005: RuntimeError raised when thread depth exceeds max for batched calls."""
        from rlm_adk.repl.thread_bridge import _THREAD_DEPTH, make_sync_llm_query_batched

        async def counting_batched_async(prompts: list[str], **kwargs) -> list[str]:
            return [f"ok:{p}" for p in prompts]

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                counting_batched_async, loop, max_thread_depth=2
            )

            def _call_at_depth_limit():
                # First call should work (depth 0 -> 1 during call)
                result = llm_query_batched(["first"])
                assert result == ["ok:first"]

                # Manually set depth to the limit to simulate deep recursion
                _THREAD_DEPTH.set(2)
                with pytest.raises(RuntimeError, match="Thread depth limit exceeded: 2/2"):
                    llm_query_batched(["should_fail"])
                # Reset for cleanup
                _THREAD_DEPTH.set(0)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _call_at_depth_limit)

        loop.run_until_complete(_run())
        loop.close()

    def test_batched_thread_depth_resets_after_call(self) -> None:
        """GAP-CB-005: _THREAD_DEPTH resets to original value after batched call completes."""
        from rlm_adk.repl.thread_bridge import _THREAD_DEPTH, make_sync_llm_query_batched

        async def fake_batched_async(prompts: list[str], **kwargs) -> list[str]:
            return [f"ok:{p}" for p in prompts]

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                fake_batched_async, loop, max_thread_depth=5
            )

            def _check_depth_reset():
                assert _THREAD_DEPTH.get(0) == 0
                llm_query_batched(["a", "b"])
                # After the call, depth should be back to 0
                assert _THREAD_DEPTH.get(0) == 0

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _check_depth_reset)

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

    def test_execute_sync_capture_output_false_skips_stdout_swap(self) -> None:
        """GAP-TH-003: execute_sync(capture_output=False) does NOT replace
        sys.stdout/sys.stderr with StringIO.

        Verifies the executor parameter directly: when capture_output=False,
        whatever sys.stdout is at call time remains unchanged during execution."""
        from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig

        executor = IPythonDebugExecutor(config=REPLDebugConfig(backend="exec"))
        ns: dict = {"__builtins__": __builtins__}

        # Snapshot sys.stdout before the call
        original_stdout = sys.stdout

        # Code that captures the type of sys.stdout DURING execution
        executor.execute_sync(
            "import sys; _observed_stdout = sys.stdout",
            ns,
            capture_output=False,
        )
        observed = ns["_observed_stdout"]

        # sys.stdout during execution should be the SAME object as before,
        # NOT a StringIO replacement
        assert observed is original_stdout, (
            f"GAP-TH-003: execute_sync(capture_output=False) replaced sys.stdout. "
            f"Expected {type(original_stdout).__name__}, got {type(observed).__name__}"
        )

    def test_execute_sync_capture_output_true_swaps_stdout(self) -> None:
        """GAP-TH-003: execute_sync(capture_output=True) still swaps sys.stdout
        with StringIO (legacy behavior for _execute_code_inner)."""
        import io as _io

        from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig

        executor = IPythonDebugExecutor(config=REPLDebugConfig(backend="exec"))
        ns: dict = {"__builtins__": __builtins__}

        executor.execute_sync(
            "import sys; _observed_stdout_type = type(sys.stdout).__name__",
            ns,
            capture_output=True,
        )
        assert ns["_observed_stdout_type"] == "StringIO", (
            f"Expected StringIO, got {ns['_observed_stdout_type']}"
        )

    @pytest.mark.asyncio
    async def test_contextvar_capture_works_during_threadsafe_exec(self) -> None:
        """GAP-TH-003: ContextVar-based capture actually captures output in
        _execute_code_threadsafe via the _TaskLocalStream proxy, not
        the executor's StringIO swap.

        Temporarily restores the _TaskLocalStream proxy that local_repl.py
        installs at module load time (pytest replaces sys.stdout with its
        own capture object, hiding the proxy).  In production the proxy is
        always present."""
        from rlm_adk.repl.local_repl import (
            LocalREPL,
            _TaskLocalStream,
            _capture_stdout,
            _capture_stderr,
        )

        repl = LocalREPL(depth=1)
        # Temporarily restore the _TaskLocalStream proxy so the ContextVar
        # routing actually has a proxy to route through.
        saved_stdout = sys.stdout
        saved_stderr = sys.stderr
        sys.stdout = _TaskLocalStream(saved_stdout, _capture_stdout)
        sys.stderr = _TaskLocalStream(saved_stderr, _capture_stderr)
        try:
            result = await repl.execute_code_threaded(
                "print('contextvar_routed')"
            )
            assert "contextvar_routed" in result.stdout, (
                f"Output not captured via ContextVar path. stdout={result.stdout!r}"
            )
        finally:
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr
            repl.cleanup()

    def test_builtins_not_permanently_mutated(self) -> None:
        """GAP-TH-004: __builtins__ dict must NOT be permanently mutated by _execute_code_threadsafe.

        The combined dict spreads self.globals shallowly, so __builtins__ is shared
        by reference. Without a defensive copy, builtins["open"] = cwd_open mutates
        self.globals["__builtins__"] permanently. This test ensures the original
        builtins dict is left untouched after execution.
        """
        repl = self._make_repl()
        try:
            # Snapshot the original __builtins__["open"] before execution
            original_open = repl.globals["__builtins__"]["open"]

            repl._execute_code_threadsafe(
                "f = open('gap004.txt', 'w')\nf.write('test')\nf.close()"
            )

            # After execution, self.globals["__builtins__"]["open"] must still
            # be the original, NOT the cwd_open wrapper injected during execution.
            after_open = repl.globals["__builtins__"]["open"]
            assert after_open is original_open, (
                "GAP-TH-004: _execute_code_threadsafe permanently mutated "
                "self.globals['__builtins__']['open'] to cwd_open"
            )
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
            # Monkey-patch the sync path to explode if called -- proves
            # REPLTool uses the threaded path, not the sync fallback.
            repl.execute_code = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("sync execute_code was called instead of execute_code_threaded")
            )
            tc = _make_tool_context()
            result = await tool.run_async(
                args={"code": "x = 42\nprint(x)"},
                tool_context=tc,
            )
            assert "42" in result["stdout"]
            assert result["stderr"] == ""
            assert result["execution_mode"] == "thread_bridge"
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
    async def test_finalize_telemetry_called_on_repl_exception(self) -> None:
        """REPLTool's error-handling finalizer fires when execute_code_threaded raises.

        Note: this test mocks out execute_code_threaded entirely, so it validates
        the REPLTool exception-handling harness, not the thread bridge itself.
        Thread bridge dispatch is covered by test_dispatches_from_worker_thread
        and test_sync_llm_query_dispatches_from_worker_thread."""
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
    async def test_finalize_telemetry_called_on_repl_cancel(self) -> None:
        """REPLTool's error-handling finalizer fires on CancelledError.

        Note: this test mocks out execute_code_threaded entirely, so it validates
        the REPLTool cancellation-handling harness, not the thread bridge itself.
        Thread bridge dispatch is covered by test_dispatches_from_worker_thread
        and test_sync_llm_query_dispatches_from_worker_thread."""
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

    @pytest.mark.asyncio
    async def test_llm_query_without_bridge_raises(self) -> None:
        """Calling llm_query from REPL code without wired bridge fails with NameError."""
        repl, tool = self._make_repl_tool()
        try:
            # Do NOT call repl.set_llm_query_fns() — bridge is unwired
            tc = _make_tool_context()
            result = await tool.run_async(
                args={"code": "result = llm_query('hello')"},
                tool_context=tc,
            )
            assert "NameError" in result.get("stderr", "") or "not defined" in result.get(
                "stderr", ""
            )
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 7: Orchestrator sync bridge wiring
# ---------------------------------------------------------------------------


class TestOrchestratorWiring:
    """Cycle 7: Orchestrator wires sync bridge to REPL globals."""

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


# ---------------------------------------------------------------------------
# GAP-EL-007: Loop-aliveness check before run_coroutine_threadsafe
# ---------------------------------------------------------------------------


class TestLoopAlivenessCheck:
    """GAP-EL-007: RuntimeError raised when event loop is closed."""

    def test_llm_query_raises_on_closed_loop(self) -> None:
        """make_sync_llm_query closure raises RuntimeError when loop is closed."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def fake_async(prompt: str, **kwargs) -> str:
            return "should_never_run"

        loop = asyncio.new_event_loop()
        llm_query = make_sync_llm_query(fake_async, loop)
        loop.close()

        with pytest.raises(RuntimeError, match="parent orchestrator has already finished"):
            llm_query("hello")

    def test_llm_query_batched_raises_on_closed_loop(self) -> None:
        """make_sync_llm_query_batched closure raises RuntimeError when loop is closed."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def fake_batched_async(prompts: list[str], **kwargs) -> list[str]:
            return ["should_never_run"]

        loop = asyncio.new_event_loop()
        llm_query_batched = make_sync_llm_query_batched(fake_batched_async, loop)
        loop.close()

        with pytest.raises(RuntimeError, match="parent orchestrator has already finished"):
            llm_query_batched(["hello"])


# ---------------------------------------------------------------------------
# GAP-EL-003: CancelledError type mismatch between concurrent.futures / asyncio
# ---------------------------------------------------------------------------


class TestCancelledErrorBridge:
    """GAP-EL-003: concurrent.futures.CancelledError from future.result() must
    be caught and re-raised as RuntimeError so it does not escape as a
    non-asyncio CancelledError that repl_tool.py cannot match."""

    def test_llm_query_converts_cancelled_to_runtime_error(self) -> None:
        """When the underlying future is cancelled, llm_query raises RuntimeError."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        # Create an async callable that hangs forever (will be cancelled)
        async def hanging_query(prompt: str, **kwargs) -> str:
            await asyncio.sleep(999)
            return "never"

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query = make_sync_llm_query(hanging_query, loop, timeout=5.0)

            def _call_then_cancel():
                # Schedule the coroutine manually so we can cancel the future
                future = asyncio.run_coroutine_threadsafe(
                    hanging_query("test"), loop
                )
                future.cancel()
                # Verify the raw future raises concurrent.futures.CancelledError
                with pytest.raises(concurrent.futures.CancelledError):
                    future.result()

                # Now test the bridge closure: patch run_coroutine_threadsafe
                # to return a pre-cancelled future
                import unittest.mock as um

                cancelled_future: concurrent.futures.Future = concurrent.futures.Future()
                cancelled_future.cancel()
                cancelled_future.set_running_or_notify_cancel()

                with um.patch(
                    "rlm_adk.repl.thread_bridge.asyncio.run_coroutine_threadsafe",
                    return_value=cancelled_future,
                ):
                    with pytest.raises(
                        RuntimeError,
                        match="llm_query cancelled",
                    ):
                        llm_query("should_be_caught")

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _call_then_cancel)

        loop.run_until_complete(_run())
        loop.close()

    def test_llm_query_batched_converts_cancelled_to_runtime_error(self) -> None:
        """When the underlying future is cancelled, llm_query_batched raises RuntimeError."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def hanging_batched(prompts: list[str], **kwargs) -> list[str]:
            await asyncio.sleep(999)
            return []

        loop = asyncio.new_event_loop()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                hanging_batched, loop, timeout=5.0
            )

            def _call_then_cancel():
                import unittest.mock as um

                cancelled_future: concurrent.futures.Future = concurrent.futures.Future()
                cancelled_future.cancel()
                cancelled_future.set_running_or_notify_cancel()

                with um.patch(
                    "rlm_adk.repl.thread_bridge.asyncio.run_coroutine_threadsafe",
                    return_value=cancelled_future,
                ):
                    with pytest.raises(
                        RuntimeError,
                        match="llm_query cancelled",
                    ):
                        llm_query_batched(["should_be_caught"])

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                await loop.run_in_executor(pool, _call_then_cancel)

        loop.run_until_complete(_run())
        loop.close()

    @pytest.mark.asyncio
    async def test_repl_tool_catches_concurrent_futures_cancelled(self) -> None:
        """REPLTool catches concurrent.futures.CancelledError via the broadened handler."""
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.state import LAST_REPL_RESULT, depth_key
        from rlm_adk.tools.repl_tool import REPLTool

        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)
        try:
            # Make execute_code_threaded raise concurrent.futures.CancelledError
            async def _raise_cf_cancel(*a, **kw):
                raise concurrent.futures.CancelledError()

            repl.execute_code_threaded = _raise_cf_cancel
            tc = _make_tool_context()
            result = await tool.run_async(
                args={"code": "noop = 1"},
                tool_context=tc,
            )
            # Should be caught by the cancellation handler, not generic Exception
            assert "CancelledError" in result["stderr"]
            last_repl = tc.state.get(depth_key(LAST_REPL_RESULT, 0))
            assert last_repl is not None
            assert last_repl.get("cancelled") is True
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# GAP-CB-003: on_model_error_callback wired on reasoning agents
# ---------------------------------------------------------------------------


class TestReasoningOnModelErrorCallback:
    """GAP-CB-003: reasoning agents have on_model_error_callback wired."""

    def test_reasoning_agent_has_on_model_error_callback(self) -> None:
        """create_reasoning_agent() sets on_model_error_callback on the LlmAgent."""
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent(model="gemini-test")
        assert agent.on_model_error_callback is not None, (
            "GAP-CB-003: on_model_error_callback not wired on reasoning agent"
        )

    def test_child_reasoning_agent_has_on_model_error_callback(self) -> None:
        """create_child_orchestrator() reasoning agent also has on_model_error_callback."""
        from rlm_adk.agent import create_child_orchestrator

        child_orch = create_child_orchestrator(
            model="gemini-test",
            depth=1,
            prompt="test",
        )
        agent = child_orch.reasoning_agent
        assert agent.on_model_error_callback is not None, (
            "GAP-CB-003: on_model_error_callback not wired on child reasoning agent"
        )

    def test_reasoning_on_model_error_records_error_info(self) -> None:
        """reasoning_on_model_error stores error_type and truncated error on agent."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from rlm_adk.callbacks.reasoning import reasoning_on_model_error

        real_agent = SimpleNamespace(name="test_agent")
        real_inv = SimpleNamespace(agent=real_agent, branch=None, invocation_id="inv1")
        real_ctx = MagicMock()
        real_ctx._invocation_context = real_inv

        error = ValueError("something went wrong in model call")
        result = reasoning_on_model_error(real_ctx, error)

        # Should return None (let error propagate)
        assert result is None

        # Should have set _rlm_last_model_error on the agent
        assert hasattr(real_agent, "_rlm_last_model_error")
        err_info = real_agent._rlm_last_model_error
        assert err_info["error_type"] == "ValueError"
        assert "something went wrong" in err_info["error"]

    def test_reasoning_on_model_error_truncates_long_messages(self) -> None:
        """Error messages longer than 500 chars are truncated."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from rlm_adk.callbacks.reasoning import reasoning_on_model_error

        real_agent = SimpleNamespace(name="test_agent")
        real_inv = SimpleNamespace(agent=real_agent, branch=None, invocation_id="inv2")
        real_ctx = MagicMock()
        real_ctx._invocation_context = real_inv

        long_msg = "x" * 1000
        error = RuntimeError(long_msg)
        reasoning_on_model_error(real_ctx, error)

        err_info = real_agent._rlm_last_model_error
        assert len(err_info["error"]) == 500
        assert err_info["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# GAP-CB-007: child event drain in finally block
# ---------------------------------------------------------------------------


class TestChildEventDrainInFinally:
    """GAP-CB-007: verify child events are drained in the finally block
    when the reasoning agent raises an exception."""

    @pytest.mark.asyncio
    async def test_finally_drain_yields_queued_events(self) -> None:
        """Simulate the finally-block drain pattern: events queued during
        a failed execution are yielded before cleanup."""
        from google.adk.events import Event, EventActions

        queue: asyncio.Queue[Event] = asyncio.Queue()
        # Simulate two child events that accumulated during a failed run
        evt1 = Event(
            invocation_id="inv1",
            author="child_worker",
            actions=EventActions(state_delta={"child:key1": "val1"}),
        )
        evt2 = Event(
            invocation_id="inv1",
            author="child_worker",
            actions=EventActions(state_delta={"child:key2": "val2"}),
        )
        queue.put_nowait(evt1)
        queue.put_nowait(evt2)

        async def _gen_with_finally_drain():
            """Async generator that raises, then drains queue in finally."""
            try:
                yield Event(
                    invocation_id="inv1",
                    author="orchestrator",
                )
                raise RuntimeError("simulated transient error")
            finally:
                # This is the pattern we're adding to orchestrator.py
                if queue is not None:
                    while not queue.empty():
                        try:
                            event = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        try:
                            yield event
                        except GeneratorExit:
                            return

        collected = []
        try:
            async for evt in _gen_with_finally_drain():
                collected.append(evt)
        except RuntimeError:
            pass

        # The first event is the normal yield, then 2 from the drain
        assert len(collected) == 3
        assert collected[1] is evt1
        assert collected[2] is evt2

    @pytest.mark.asyncio
    async def test_finally_drain_skipped_when_queue_is_none(self) -> None:
        """When _child_event_queue is None (child re-emission disabled),
        the drain is safely skipped."""
        _child_event_queue = None

        async def _gen_no_queue():
            try:
                yield "normal_event"
                raise RuntimeError("boom")
            finally:
                if _child_event_queue is not None:
                    while not _child_event_queue.empty():
                        try:
                            event = _child_event_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        try:
                            yield event
                        except GeneratorExit:
                            return

        collected = []
        try:
            async for evt in _gen_no_queue():
                collected.append(evt)
        except RuntimeError:
            pass

        assert len(collected) == 1
        assert collected[0] == "normal_event"

    @pytest.mark.asyncio
    async def test_finally_drain_with_consumer_break(self) -> None:
        """When consumer stops iterating mid-drain (e.g. break in async for),
        the GeneratorExit guard prevents RuntimeError. Simulated by consuming
        only one drained event then breaking."""
        from google.adk.events import Event, EventActions

        queue: asyncio.Queue[Event] = asyncio.Queue()
        evt1 = Event(
            invocation_id="inv1",
            author="child",
            actions=EventActions(state_delta={"k": "v1"}),
        )
        evt2 = Event(
            invocation_id="inv1",
            author="child",
            actions=EventActions(state_delta={"k": "v2"}),
        )
        queue.put_nowait(evt1)
        queue.put_nowait(evt2)

        async def _gen_with_drain():
            try:
                yield "start"
                raise RuntimeError("simulated error")
            finally:
                if queue is not None:
                    while not queue.empty():
                        try:
                            event = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        try:
                            yield event
                        except GeneratorExit:
                            return

        collected = []
        # Consumer breaks after receiving the first drained event
        try:
            async for evt in _gen_with_drain():
                collected.append(evt)
                if evt is evt1:
                    break  # stop consuming mid-drain
        except RuntimeError:
            pass

        # Should have "start" + evt1, without RuntimeError from GeneratorExit
        assert len(collected) == 2
        assert collected[0] == "start"
        assert collected[1] is evt1
