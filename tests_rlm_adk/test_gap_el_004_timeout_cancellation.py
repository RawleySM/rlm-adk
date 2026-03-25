"""Tests for GAP-EL-004: Timeout cancellation prevents orphaned child dispatches.

When execute_code_threaded times out at 30s, orphaned worker threads must NOT
be able to submit new llm_query() calls (which would consume API quota for up
to 300s each).  The fix introduces a threading.Event cancellation token that is:
  - passed into make_sync_llm_query / make_sync_llm_query_batched
  - checked BEFORE run_coroutine_threadsafe
  - set by execute_code_threaded on TimeoutError
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import threading

import pytest

# ---------------------------------------------------------------------------
# Test 1: make_sync_llm_query accepts a `cancelled` event parameter
# ---------------------------------------------------------------------------


class TestCancelledEventSignature:
    """The bridge factory functions accept an optional cancelled event."""

    def test_make_sync_llm_query_accepts_cancelled_param(self) -> None:
        """make_sync_llm_query has a 'cancelled' keyword parameter."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        sig = inspect.signature(make_sync_llm_query)
        assert "cancelled" in sig.parameters, (
            "make_sync_llm_query must accept a 'cancelled' parameter"
        )
        param = sig.parameters["cancelled"]
        assert param.default is None, (
            "cancelled parameter must default to None for backward compat"
        )

    def test_make_sync_llm_query_batched_accepts_cancelled_param(self) -> None:
        """make_sync_llm_query_batched has a 'cancelled' keyword parameter."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        sig = inspect.signature(make_sync_llm_query_batched)
        assert "cancelled" in sig.parameters, (
            "make_sync_llm_query_batched must accept a 'cancelled' parameter"
        )
        param = sig.parameters["cancelled"]
        assert param.default is None, (
            "cancelled parameter must default to None for backward compat"
        )


# ---------------------------------------------------------------------------
# Test 2: llm_query raises RuntimeError when cancelled event is set
# ---------------------------------------------------------------------------


class TestCancelledEventBlocks:
    """When the cancelled event is set, llm_query raises immediately."""

    def test_llm_query_raises_when_cancelled(self) -> None:
        """Calling llm_query() after cancelled.set() raises RuntimeError."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def fake_llm_query_async(prompt: str, **kwargs) -> str:
            await asyncio.sleep(0.01)
            return f"echo:{prompt}"

        loop = asyncio.new_event_loop()
        cancelled = threading.Event()
        cancelled.set()  # Pre-set: simulate timeout already fired

        async def _run():
            llm_query = make_sync_llm_query(
                fake_llm_query_async, loop, cancelled=cancelled
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(RuntimeError, match="cancel"):
                    await loop.run_in_executor(pool, llm_query, "hello")

        loop.run_until_complete(_run())
        loop.close()

    def test_llm_query_batched_raises_when_cancelled(self) -> None:
        """Calling llm_query_batched() after cancelled.set() raises RuntimeError."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched

        async def fake_batched_async(prompts: list[str], **kwargs) -> list[str]:
            return [f"echo:{p}" for p in prompts]

        loop = asyncio.new_event_loop()
        cancelled = threading.Event()
        cancelled.set()

        async def _run():
            llm_query_batched = make_sync_llm_query_batched(
                fake_batched_async, loop, cancelled=cancelled
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(RuntimeError, match="cancel"):
                    await loop.run_in_executor(
                        pool, lambda: llm_query_batched(["a", "b"])
                    )

        loop.run_until_complete(_run())
        loop.close()


# ---------------------------------------------------------------------------
# Test 3: cancelled event is checked BEFORE run_coroutine_threadsafe
# ---------------------------------------------------------------------------


class TestCancelledCheckOrder:
    """The cancelled check must happen before submitting work to the loop."""

    def test_cancelled_prevents_coroutine_submission(self) -> None:
        """When cancelled is set, no coroutine is submitted to the event loop.

        We verify this by checking that the async function is never called.
        """
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        call_count = 0

        async def tracking_query(prompt: str, **kwargs) -> str:
            nonlocal call_count
            call_count += 1
            return "should not reach"

        loop = asyncio.new_event_loop()
        cancelled = threading.Event()
        cancelled.set()

        async def _run():
            llm_query = make_sync_llm_query(
                tracking_query, loop, cancelled=cancelled
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    await loop.run_in_executor(pool, llm_query, "hello")
                except RuntimeError:
                    pass

        loop.run_until_complete(_run())
        loop.close()

        assert call_count == 0, (
            f"Async function was called {call_count} times but should not "
            "have been called at all — cancelled check must happen BEFORE "
            "run_coroutine_threadsafe"
        )


# ---------------------------------------------------------------------------
# Test 4: execute_code_threaded sets the cancelled event on timeout
# ---------------------------------------------------------------------------


class TestExecuteCodeThreadedCancellation:
    """execute_code_threaded sets a cancelled event when TimeoutError fires."""

    @pytest.mark.asyncio
    async def test_timeout_sets_cancelled_event(self) -> None:
        """When code times out, the REPL's _cancelled event is set."""
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        repl = LocalREPL(depth=1, sync_timeout=0.5)

        async def slow_llm_query_async(prompt: str, **kwargs) -> str:
            await asyncio.sleep(10)  # Will exceed the 0.5s sync_timeout
            return f"echo:{prompt}"

        # Wire bridge closures using the REPL's own _cancelled event
        loop = asyncio.get_running_loop()
        llm_query = make_sync_llm_query(
            slow_llm_query_async, loop, cancelled=repl._cancelled,
        )
        repl.set_llm_query_fns(llm_query, llm_query)

        # Code that calls llm_query — will block until timeout fires
        code = (
            "try:\n"
            "    result1 = llm_query('first')\n"
            "except Exception:\n"
            "    pass\n"
        )

        try:
            result = await repl.execute_code_threaded(code)
            # After timeout, the cancelled event should be set
            assert repl._cancelled.is_set(), (
                "execute_code_threaded must set _cancelled on timeout"
            )
            assert "TimeoutError" in result.stderr
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_cancelled_cleared_on_next_execution(self) -> None:
        """A new execute_code_threaded call clears the cancelled event
        from a previous timeout (edge case #5 from understand doc)."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1, sync_timeout=0.5)

        try:
            # Manually set cancelled to simulate a previous timeout
            repl._cancelled.set()
            assert repl._cancelled.is_set()

            # Execute simple code (no llm_query) — should clear cancelled
            result = await repl.execute_code_threaded("x = 42\nprint(x)")
            assert not repl._cancelled.is_set(), (
                "execute_code_threaded must clear _cancelled at start"
            )
            assert "42" in result.stdout
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# Test 5: Normal execution (no timeout) does not set cancelled
# ---------------------------------------------------------------------------


class TestNormalExecutionNotCancelled:
    """When code completes normally, cancelled event is NOT set."""

    def test_no_cancellation_on_success(self) -> None:
        """Successful execution does not trigger cancellation."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def fast_query(prompt: str, **kwargs) -> str:
            return f"echo:{prompt}"

        loop = asyncio.new_event_loop()
        cancelled = threading.Event()

        async def _run():
            llm_query = make_sync_llm_query(
                fast_query, loop, cancelled=cancelled
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(pool, llm_query, "hello")
            assert result == "echo:hello"
            assert not cancelled.is_set(), (
                "cancelled event must NOT be set on successful execution"
            )

        loop.run_until_complete(_run())
        loop.close()


# ---------------------------------------------------------------------------
# Test 6: Backward compatibility — None cancelled works like before
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing code that does not pass cancelled still works."""

    def test_no_cancelled_param_works(self) -> None:
        """make_sync_llm_query without cancelled= works as before."""
        from rlm_adk.repl.thread_bridge import make_sync_llm_query

        async def fake_query(prompt: str, **kwargs) -> str:
            return f"echo:{prompt}"

        loop = asyncio.new_event_loop()

        async def _run():
            # No cancelled= parameter — must work exactly as before
            llm_query = make_sync_llm_query(fake_query, loop)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = await loop.run_in_executor(pool, llm_query, "hello")
            assert result == "echo:hello"

        loop.run_until_complete(_run())
        loop.close()
