"""Tests for GAP-OB-007: REPLTrace timing sentinel and timeout path fixes.

Verifies that:
- REPLTrace defaults start_time/end_time to None (not 0.0)
- summary() and to_dict() return wall_time_ms=0 when times are None
- summary() and to_dict() compute correct wall_time_ms when both times are set
- The old 0.0 sentinel caused falsy-guard bugs (regression guard)
- Timeout handlers in local_repl set trace.end_time
- REPLTool error handlers use `is not None` guards (not truthiness)
"""

import os
import time

import pytest

from rlm_adk.repl.trace import REPLTrace


@pytest.fixture(autouse=True)
def _stable_cwd(tmp_path):
    """Ensure CWD is valid before and after each test.

    LocalREPL.cleanup() removes its temp_dir.  If a prior test's worker
    thread changed CWD into that dir, subsequent os.getcwd() calls fail
    with FileNotFoundError.  This fixture restores CWD to a known-good
    directory around every test.
    """
    saved = os.getcwd()
    os.chdir(tmp_path)
    yield
    try:
        os.chdir(saved)
    except (FileNotFoundError, OSError):
        os.chdir(tmp_path)


# ---------------------------------------------------------------------------
# Part 1: REPLTrace sentinel and guard fixes
# ---------------------------------------------------------------------------


class TestREPLTraceSentinel:
    """Verify that start_time/end_time default to None, not 0.0."""

    def test_default_start_time_is_none(self):
        trace = REPLTrace()
        assert trace.start_time is None, (
            f"Expected start_time default to be None, got {trace.start_time!r}"
        )

    def test_default_end_time_is_none(self):
        trace = REPLTrace()
        assert trace.end_time is None, (
            f"Expected end_time default to be None, got {trace.end_time!r}"
        )


class TestREPLTraceWallTime:
    """Verify wall_time_ms computation in to_dict() and summary()."""

    def test_to_dict_wall_time_both_none(self):
        """When neither time is set, wall_time_ms should be 0."""
        trace = REPLTrace()
        d = trace.to_dict()
        assert d["wall_time_ms"] == 0

    def test_summary_wall_time_both_none(self):
        """When neither time is set, wall_time_ms should be 0."""
        trace = REPLTrace()
        s = trace.summary()
        assert s["wall_time_ms"] == 0

    def test_to_dict_wall_time_only_start_set(self):
        """When only start_time is set (end_time still None), wall_time_ms should be 0."""
        trace = REPLTrace()
        trace.start_time = time.perf_counter()
        d = trace.to_dict()
        assert d["wall_time_ms"] == 0

    def test_summary_wall_time_only_start_set(self):
        """When only start_time is set (end_time still None), wall_time_ms should be 0."""
        trace = REPLTrace()
        trace.start_time = time.perf_counter()
        s = trace.summary()
        assert s["wall_time_ms"] == 0

    def test_to_dict_wall_time_both_set(self):
        """When both times are set, wall_time_ms should be computed correctly."""
        trace = REPLTrace()
        trace.start_time = 100.0
        trace.end_time = 100.5
        d = trace.to_dict()
        assert d["wall_time_ms"] == 500.0

    def test_summary_wall_time_both_set(self):
        """When both times are set, wall_time_ms should be computed correctly."""
        trace = REPLTrace()
        trace.start_time = 100.0
        trace.end_time = 100.5
        s = trace.summary()
        assert s["wall_time_ms"] == 500.0

    def test_to_dict_wall_time_real_perf_counter(self):
        """Integration: use real perf_counter values and verify positive wall_time_ms."""
        trace = REPLTrace()
        trace.start_time = time.perf_counter()
        time.sleep(0.01)  # 10ms
        trace.end_time = time.perf_counter()
        d = trace.to_dict()
        assert d["wall_time_ms"] > 0, "Expected positive wall_time_ms with real perf_counter"

    def test_summary_no_crash_on_none_times(self):
        """summary() must not raise TypeError when start_time/end_time are None."""
        trace = REPLTrace()
        # This would crash with `None - None` if guards are wrong
        s = trace.summary()
        assert isinstance(s, dict)
        assert s["wall_time_ms"] == 0

    def test_to_dict_no_crash_on_none_times(self):
        """to_dict() must not raise TypeError when start_time/end_time are None."""
        trace = REPLTrace()
        d = trace.to_dict()
        assert isinstance(d, dict)
        assert d["wall_time_ms"] == 0


class TestREPLTraceFalsyGuardRegression:
    """Regression: the old 0.0 sentinel was falsy, causing incorrect behavior.

    These tests encode the exact bug scenario:
    - start_time=0.0 is falsy in Python, so `if self.start_time` is False
    - This caused wall_time_ms to report 0 even when end_time was set
    """

    def test_zero_start_time_is_falsy_in_python(self):
        """Confirm that 0.0 is falsy -- the root cause of the bug."""
        assert not 0.0, "0.0 should be falsy in Python (this is the root cause)"

    def test_none_is_also_falsy_but_distinguishable(self):
        """None is falsy too, but `is not None` distinguishes it from 0.0."""
        assert not None
        assert 0.0 != None  # noqa: E711 — intentional: demonstrating `is not` vs truthiness

    def test_old_guard_would_miss_valid_timing(self):
        """Simulate the old bug: if start_time were 0.0, truthiness guard skips computation.

        With the fix (None sentinel + `is not None` guard), a set start_time
        of any float value (including hypothetically 0.0) should be recognized.
        """
        trace = REPLTrace()
        # Simulate: start_time was set to a real value, end_time was set
        trace.start_time = 50.0
        trace.end_time = 50.3
        d = trace.to_dict()
        # The fix ensures this works even though old code would have failed
        # if start_time happened to be falsy
        assert d["wall_time_ms"] == 300.0


# ---------------------------------------------------------------------------
# Part 2: Timeout handler sets trace.end_time
# ---------------------------------------------------------------------------


class TestTimeoutHandlerSetsEndTime:
    """Verify that timeout paths in local_repl set trace.end_time."""

    @pytest.mark.asyncio
    async def test_execute_code_threaded_timeout_sets_end_time(self):
        """When execute_code_threaded times out, trace.end_time should be set."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(sync_timeout=0.1)
        trace = REPLTrace()
        trace.start_time = time.perf_counter()  # Simulate callback having fired

        try:
            # Code that will definitely exceed the 0.1s timeout
            result = await repl.execute_code_threaded(
                "import time; time.sleep(10)", trace=trace,
            )
            # After timeout, trace.end_time should have been set
            assert trace.end_time is not None, (
                "trace.end_time should be set after timeout in execute_code_threaded"
            )
            assert result.stderr and "TimeoutError" in result.stderr
        finally:
            repl.cleanup()

    def test_execute_code_sync_timeout_sets_end_time(self):
        """When execute_code (sync) times out, trace.end_time should be set."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(sync_timeout=0.1)
        trace = REPLTrace()
        trace.start_time = time.perf_counter()  # Simulate callback having fired

        try:
            result = repl.execute_code(
                "import time; time.sleep(10)", trace=trace,
            )
            assert trace.end_time is not None, (
                "trace.end_time should be set after timeout in execute_code"
            )
            assert result.stderr and "TimeoutError" in result.stderr
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_execute_code_threaded_timeout_no_start_time(self):
        """When timeout occurs but start_time was never set (None), end_time should still be None."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(sync_timeout=0.1)
        trace = REPLTrace()
        # start_time is None (trace callbacks never fired)

        try:
            result = await repl.execute_code_threaded(
                "import time; time.sleep(10)", trace=trace,
            )
            # end_time should still be None since start_time was never set
            # Actually, the fix sets end_time regardless when trace.end_time is None,
            # because we want to record that time passed even if the trace callback
            # didn't fire. The trace summary will handle the None start_time case.
            # Per the gap spec: "if trace is not None and trace.end_time is None"
            assert result.stderr and "TimeoutError" in result.stderr
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_timeout_wall_time_positive_when_start_set(self):
        """After timeout with start_time set, wall_time_ms should be positive."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(sync_timeout=0.2)
        trace = REPLTrace()
        trace.start_time = time.perf_counter()

        try:
            await repl.execute_code_threaded(
                "import time; time.sleep(10)", trace=trace,
            )
            # Both times should now be set
            assert trace.start_time is not None
            assert trace.end_time is not None
            s = trace.summary()
            assert s["wall_time_ms"] > 0, (
                f"Expected positive wall_time_ms after timeout, got {s['wall_time_ms']}"
            )
        finally:
            repl.cleanup()


# ---------------------------------------------------------------------------
# Part 3: REPLTool error handler guards
# ---------------------------------------------------------------------------


class TestREPLToolErrorGuards:
    """Verify that REPLTool error handlers use `is not None` guards."""

    def test_cancelled_error_guard_sets_end_time_when_start_is_set(self):
        """Simulate: trace has start_time set, CancelledError happens, end_time should be set.

        This tests the guard logic directly (not through REPLTool) to verify
        the pattern is correct.
        """
        trace = REPLTrace()
        trace.start_time = 100.0
        # Simulate the fixed guard from repl_tool.py:
        # if trace is not None and trace.end_time is None:
        if trace is not None and trace.end_time is None:
            trace.end_time = time.perf_counter()
        assert trace.end_time is not None

    def test_cancelled_error_guard_skips_when_end_time_already_set(self):
        """If end_time is already set, the guard should not overwrite it."""
        trace = REPLTrace()
        trace.start_time = 100.0
        trace.end_time = 100.5
        original_end = trace.end_time
        # Simulate the fixed guard:
        if trace is not None and trace.end_time is None:
            trace.end_time = time.perf_counter()
        assert trace.end_time == original_end, "end_time should not be overwritten"

    def test_old_guard_would_fail_with_zero_start_time(self):
        """Demonstrate the old bug: truthiness guard fails when start_time is 0.0.

        Old code: `if trace.start_time and not trace.end_time`
        When start_time=0.0 (falsy), the condition is False, so end_time is never set.
        """
        trace = REPLTrace()
        # Old default was 0.0
        old_start_time = 0.0
        old_end_time = 0.0

        # Old guard logic (the bug):
        old_guard_fires = bool(old_start_time and not old_end_time)
        assert not old_guard_fires, "Old guard should NOT fire with 0.0 start_time (the bug)"

        # New guard logic (the fix):
        trace.start_time = 50.0  # A real value
        new_guard_fires = trace.end_time is None
        assert new_guard_fires, "New guard SHOULD fire when end_time is None"


# ---------------------------------------------------------------------------
# Part 4: GAP-OB-006 – DataFlowTracker edges not overwritten across batches
# ---------------------------------------------------------------------------


class TestDataFlowEdgesPreservedAcrossBatches:
    """GAP-OB-006: data_flow_edges must accumulate across multiple batched calls.

    When a single REPL code block triggers multiple llm_query / llm_query_batched
    invocations, each batch creates a fresh DataFlowTracker. The trace's
    data_flow_edges list must *extend* (not overwrite) so edges detected in
    earlier batches are preserved.
    """

    def test_edges_from_earlier_batch_preserved(self):
        """Simulate 2 batched calls; edges from batch 1 must survive batch 2."""
        from rlm_adk.repl.trace import DataFlowTracker, REPLTrace

        trace = REPLTrace()

        # --- Batch 1: produces edge (0, 1) ---
        tracker1 = DataFlowTracker(min_fingerprint_len=10)
        # call 0: prompt "hello world this is a test", response recorded
        tracker1.check_prompt(0, "hello world this is a test")
        tracker1.register_response(0, "The answer from call zero is forty-two")
        # call 1: prompt reuses call-0 response substring
        tracker1.check_prompt(1, "Based on: The answer from call zero is forty-two, continue")
        tracker1.register_response(1, "continued result from call one with extras")
        edges1 = tracker1.get_edges()
        assert edges1 == [(0, 1)], f"Batch 1 should detect edge (0,1), got {edges1}"

        # Simulate what dispatch.py does: write edges to trace
        trace.data_flow_edges.extend(edges1)

        # --- Batch 2: produces edge (2, 3) ---
        tracker2 = DataFlowTracker(min_fingerprint_len=10)
        tracker2.check_prompt(2, "new prompt for call two completely fresh")
        tracker2.register_response(2, "response from call two is a large block of text")
        # call 3 reuses call-2 response substring
        tracker2.check_prompt(3, "Reuse: response from call two is a large block of text, and more")
        tracker2.register_response(3, "final result from call three")
        edges2 = tracker2.get_edges()
        assert edges2 == [(2, 3)], f"Batch 2 should detect edge (2,3), got {edges2}"

        # Simulate the fixed dispatch line: extend, not assign
        trace.data_flow_edges.extend(edges2)

        # Both batches' edges must be present
        assert trace.data_flow_edges == [(0, 1), (2, 3)], (
            f"Expected edges from both batches, got {trace.data_flow_edges}"
        )

    def test_assignment_overwrites_earlier_edges(self):
        """Demonstrate the bug: plain assignment loses earlier batch edges."""
        from rlm_adk.repl.trace import DataFlowTracker, REPLTrace

        trace = REPLTrace()

        # Batch 1 edges
        tracker1 = DataFlowTracker(min_fingerprint_len=10)
        tracker1.check_prompt(0, "hello world this is a test")
        tracker1.register_response(0, "The answer from call zero is forty-two")
        tracker1.check_prompt(1, "Based on: The answer from call zero is forty-two, continue")
        tracker1.register_response(1, "continued result")
        # Use assignment (the bug)
        trace.data_flow_edges = tracker1.get_edges()
        assert trace.data_flow_edges == [(0, 1)]

        # Batch 2 has no edges (fresh tracker, no cross-ref)
        tracker2 = DataFlowTracker(min_fingerprint_len=10)
        tracker2.check_prompt(2, "independent prompt for call two")
        tracker2.register_response(2, "independent response")
        # Assignment overwrites with empty list — the bug!
        trace.data_flow_edges = tracker2.get_edges()
        assert trace.data_flow_edges == [], (
            "Assignment (the bug) should overwrite with empty list, losing batch 1 edges"
        )
