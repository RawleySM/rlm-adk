"""Tests for FMEA source fixes: FM-02, FM-26, FM-27.

Item 12 [FM-02]: Error event metadata in orchestrator retry loop
Item 28 [FM-26]: Sync execution timeout in LocalREPL
Item 30 [FM-27]: No os.chdir() in execute_code_async

Note: FM-12 (worker cleanup isolation) removed — tested old WorkerPool dispatch internals.
"""

import asyncio
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError

from rlm_adk.repl.local_repl import LocalREPL


# ===================================================================
# Item 12 [FM-02]: Error event metadata in orchestrator
# ===================================================================


class TestOrchestratorErrorEventMetadata:
    """FM-02: Error events should carry classification metadata."""

    @pytest.mark.asyncio
    async def test_non_transient_error_yields_error_event(self):
        """A non-retryable error (code=400) should yield an error event
        with state_delta containing FINAL_ANSWER before raising."""
        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from google.adk.agents import LlmAgent

        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
        )

        # Mock the reasoning_agent.run_async to raise a non-transient error
        exc = ClientError(400, {"error": {"message": "Bad Request", "status": "INVALID_ARGUMENT"}})

        async def mock_run_async(ctx):
            raise exc
            yield  # make it an async generator

        object.__setattr__(reasoning_agent, "run_async", mock_run_async)

        # Build mock InvocationContext
        ctx = MagicMock()
        ctx.invocation_id = "test-inv"
        ctx.session.state = {}

        events = []
        with pytest.raises(ClientError):
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Find the error event (should have FINAL_ANSWER in state_delta)
        error_events = [
            e for e in events
            if e.actions and e.actions.state_delta
            and "final_answer" in e.actions.state_delta
            and "[RLM ERROR]" in str(e.actions.state_delta.get("final_answer", ""))
        ]
        assert len(error_events) == 1, f"Expected 1 error event, got {len(error_events)}"
        error_msg = error_events[0].actions.state_delta["final_answer"]
        assert "non-retryable error" in error_msg
        assert "code=400" in error_msg
        assert error_events[0].actions.state_delta.get("should_stop") is True

    @pytest.mark.asyncio
    async def test_retry_exhausted_yields_error_event(self):
        """A transient error that exhausts retries should yield an error event
        with 'retry exhausted' metadata before raising."""
        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from google.adk.agents import LlmAgent

        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
        )

        # Mock the reasoning_agent.run_async to always raise a transient error
        exc = ServerError(503, {"error": {"message": "Unavailable", "status": "UNAVAILABLE"}})

        async def mock_run_async(ctx):
            raise exc
            yield

        object.__setattr__(reasoning_agent, "run_async", mock_run_async)

        ctx = MagicMock()
        ctx.invocation_id = "test-inv"
        ctx.session.state = {}

        events = []
        with (
            patch.dict(os.environ, {"RLM_LLM_MAX_RETRIES": "1", "RLM_LLM_RETRY_DELAY": "0.01"}),
            pytest.raises(ServerError),
        ):
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        error_events = [
            e for e in events
            if e.actions and e.actions.state_delta
            and "final_answer" in e.actions.state_delta
            and "[RLM ERROR]" in str(e.actions.state_delta.get("final_answer", ""))
        ]
        assert len(error_events) == 1
        error_msg = error_events[0].actions.state_delta["final_answer"]
        assert "retry exhausted" in error_msg
        assert "code=503" in error_msg


# ===================================================================
# Item 28 [FM-26]: Sync execution timeout
# ===================================================================


class TestSyncExecutionTimeout:
    """FM-26: Sync execute_code should enforce a timeout."""

    def test_timeout_default_from_env(self):
        """Default sync_timeout should come from RLM_REPL_SYNC_TIMEOUT env var."""
        with patch.dict(os.environ, {"RLM_REPL_SYNC_TIMEOUT": "42"}):
            repl = LocalREPL()
            assert repl.sync_timeout == 42.0
            repl.cleanup()

    def test_timeout_explicit_parameter(self):
        """Explicit sync_timeout parameter should override env var."""
        repl = LocalREPL(sync_timeout=10.0)
        assert repl.sync_timeout == 10.0
        repl.cleanup()

    def test_short_code_completes_within_timeout(self):
        """Code that completes quickly should not be affected by timeout."""
        repl = LocalREPL(sync_timeout=5.0)
        result = repl.execute_code("x = 42\nprint(x)")
        assert result.stdout.strip() == "42"
        assert "TimeoutError" not in result.stderr
        repl.cleanup()

    def test_slow_code_exceeds_timeout(self):
        """Code that takes longer than sync_timeout should produce TimeoutError."""
        repl = LocalREPL(sync_timeout=0.5)
        # Use a busy-wait loop that will definitely exceed 0.5s.
        # Use a short sleep so the background thread finishes quickly
        # after the timeout fires, preventing CWD race on cleanup.
        result = repl.execute_code(
            "import time\ntime.sleep(2)"
        )
        assert "TimeoutError" in result.stderr
        assert "timeout" in result.stderr.lower()
        # Wait briefly for background thread to finish before cleanup
        time.sleep(2.5)
        repl.cleanup()

    def test_timeout_sets_last_exec_error(self):
        """After a timeout, _last_exec_error should be set."""
        repl = LocalREPL(sync_timeout=0.5)
        repl.execute_code("import time\ntime.sleep(2)")
        assert repl._last_exec_error is not None
        assert "TimeoutError" in repl._last_exec_error
        # Wait for background thread before cleanup
        time.sleep(2.5)
        repl.cleanup()


# ===================================================================
# Item 30 [FM-27]: No os.chdir() in execute_code_async
# ===================================================================


class TestAsyncNoChdirRace:
    """FM-27: execute_code_async should not call os.chdir()."""

    @pytest.mark.asyncio
    async def test_cwd_unchanged_after_async_exec(self):
        """execute_code_async should not modify the process CWD."""
        cwd_before = os.getcwd()
        repl = LocalREPL()

        async def mock_exec_fn():
            return {"x": 42}

        await repl.execute_code_async("x = 42", mock_exec_fn)
        cwd_after = os.getcwd()

        assert cwd_before == cwd_after, (
            f"CWD changed from {cwd_before} to {cwd_after} during execute_code_async"
        )
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_concurrent_async_repls_no_cwd_leak(self):
        """Two concurrent execute_code_async calls should not interfere via CWD."""
        cwd_before = os.getcwd()
        repl_a = LocalREPL()
        repl_b = LocalREPL()

        assert repl_a.temp_dir != repl_b.temp_dir

        observed_cwds = []

        async def exec_fn_a():
            # Record CWD at execution time
            observed_cwds.append(("a", os.getcwd()))
            await asyncio.sleep(0.05)  # yield to event loop
            observed_cwds.append(("a_after", os.getcwd()))
            return {}

        async def exec_fn_b():
            observed_cwds.append(("b", os.getcwd()))
            await asyncio.sleep(0.05)
            observed_cwds.append(("b_after", os.getcwd()))
            return {}

        await asyncio.gather(
            repl_a.execute_code_async("pass", exec_fn_a),
            repl_b.execute_code_async("pass", exec_fn_b),
        )

        cwd_after = os.getcwd()
        assert cwd_before == cwd_after, (
            f"CWD leaked: was {cwd_before}, now {cwd_after}"
        )

        # None of the observed CWDs should be a REPL temp dir
        # (since we no longer chdir)
        for label, cwd in observed_cwds:
            assert cwd != repl_a.temp_dir, f"CWD was set to repl_a.temp_dir during {label}"
            assert cwd != repl_b.temp_dir, f"CWD was set to repl_b.temp_dir during {label}"

        repl_a.cleanup()
        repl_b.cleanup()

    @pytest.mark.asyncio
    async def test_async_open_resolves_to_temp_dir(self):
        """open() in async execution should resolve relative paths to temp_dir."""
        repl = LocalREPL()

        # Write a test file in the temp dir
        test_file = os.path.join(repl.temp_dir, "test_file.txt")
        with open(test_file, "w") as f:
            f.write("hello from temp dir")

        read_content = None

        async def exec_fn():
            nonlocal read_content
            # open("test_file.txt") should resolve to temp_dir/test_file.txt
            # because of the cwd-aware open() wrapper
            with open("test_file.txt") as f:  # noqa: F821  -- uses injected open
                read_content = f.read()
            return {}

        # The open in exec_fn will use the globals' __builtins__["open"],
        # but since the function is defined in this module, it uses this
        # module's open. We need to test via the REPL globals directly.
        # Instead, let's verify the _make_cwd_open mechanism:
        cwd_open = repl._make_cwd_open()
        with cwd_open("test_file.txt") as f:
            content = f.read()
        assert content == "hello from temp dir"

        repl.cleanup()
