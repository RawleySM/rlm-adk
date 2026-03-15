"""Tests for IPython observability features (verbose tracebacks, event callbacks, result capture).

RED/GREEN TDD: Tests written before implementation.
"""

from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.trace import REPLTrace

# ── Feature 1: Verbose Tracebacks ─────────────────────────────────────────


class TestVerboseTracebacks:
    """Feature 1: Configurable traceback mode via RLM_REPL_XMODE env var."""

    def test_default_xmode_is_context(self):
        """Without env var, xmode should default to Context."""
        cfg = REPLDebugConfig.from_env()
        assert cfg.xmode == "Context"

    def test_xmode_from_env_verbose(self, monkeypatch):
        """RLM_REPL_XMODE=Verbose should set xmode to Verbose."""
        monkeypatch.setenv("RLM_REPL_XMODE", "Verbose")
        cfg = REPLDebugConfig.from_env()
        assert cfg.xmode == "Verbose"

    def test_xmode_from_env_minimal(self, monkeypatch):
        """RLM_REPL_XMODE=Minimal should set xmode to Minimal."""
        monkeypatch.setenv("RLM_REPL_XMODE", "Minimal")
        cfg = REPLDebugConfig.from_env()
        assert cfg.xmode == "Minimal"

    def test_verbose_traceback_includes_local_vars(self, monkeypatch):
        """With xmode=Verbose, error tracebacks should include local variable values."""
        monkeypatch.setenv("RLM_REPL_XMODE", "Verbose")
        cfg = REPLDebugConfig.from_env()
        executor = IPythonDebugExecutor(config=cfg)
        ns = {"__builtins__": __builtins__}

        code = """\
def foo():
    x = 42
    y = "hello"
    raise ValueError("test error")

foo()
"""
        stdout, stderr, success = executor.execute_sync(code, ns)
        assert success is False
        assert "ValueError" in stderr
        # Verbose mode should show local variables in traceback
        # IPython Verbose mode shows "x = 42" and "y = 'hello'" in the frame
        assert "x" in stderr and "42" in stderr

    def test_xmode_applied_to_shell(self, monkeypatch):
        """The executor should apply xmode to the IPython shell's InteractiveTB."""
        monkeypatch.setenv("RLM_REPL_XMODE", "Verbose")
        cfg = REPLDebugConfig.from_env()
        executor = IPythonDebugExecutor(config=cfg)
        if executor._shell is not None:
            # The shell's InteractiveTB mode should be set
            assert executor._shell.InteractiveTB.mode == "Verbose"


# ── Feature 2: Event Callbacks (pre_run_cell / post_run_cell) ─────────────


class TestEventCallbacks:
    """Feature 2: Replace trace header/footer code injection with IPython event callbacks."""

    def test_trace_timing_via_callbacks_sync(self, monkeypatch):
        """Trace start/end times should be set via callbacks, not code injection."""
        monkeypatch.setenv("RLM_REPL_TRACE", "1")
        repl = LocalREPL()
        trace = REPLTrace()
        result = repl.execute_code("x = 42", trace=trace)
        assert trace.start_time > 0
        assert trace.end_time >= trace.start_time
        assert result.trace is not None
        assert result.trace["wall_time_ms"] > 0
        repl.cleanup()

    def test_trace_timing_via_callbacks_no_code_injection(self, monkeypatch):
        """With trace_level=1, no TRACE_HEADER/FOOTER code should be injected.
        Verify by checking that _rlm_time is NOT in the namespace after execution."""
        monkeypatch.setenv("RLM_REPL_TRACE", "1")
        repl = LocalREPL()
        trace = REPLTrace()
        repl.execute_code("x = 42", trace=trace)
        # _rlm_time was a side effect of the old code injection approach
        # With callbacks, it should NOT appear in the combined namespace
        assert "_rlm_time" not in repl.locals
        assert "_rlm_time" not in repl.globals
        repl.cleanup()

    def test_trace_memory_via_callbacks(self, monkeypatch):
        """With trace_level=2, tracemalloc should be handled via callbacks."""
        monkeypatch.setenv("RLM_REPL_TRACE", "2")
        repl = LocalREPL()
        trace = REPLTrace()
        # Allocate some memory to get a nonzero peak
        repl.execute_code("data = [i for i in range(10000)]", trace=trace)
        assert trace.start_time > 0
        assert trace.end_time >= trace.start_time
        assert trace.peak_memory_bytes > 0
        repl.cleanup()

    def test_trace_memory_not_active_at_level_1(self, monkeypatch):
        """trace_level=1 should NOT activate tracemalloc."""
        monkeypatch.setenv("RLM_REPL_TRACE", "1")
        repl = LocalREPL()
        trace = REPLTrace()
        repl.execute_code("data = [i for i in range(1000)]", trace=trace)
        assert trace.peak_memory_bytes == 0
        repl.cleanup()

    def test_no_trace_header_footer_in_code(self, monkeypatch):
        """Verify no TRACE_HEADER/FOOTER strings are injected into user code."""
        monkeypatch.setenv("RLM_REPL_TRACE", "2")
        repl = LocalREPL()
        trace = REPLTrace()
        # Code that would fail if trace header/footer is injected
        # (because injected code adds lines that shift line numbers)
        code = "x = 1\ny = 2\nz = x + y"
        result = repl.execute_code(code, trace=trace)
        assert result.stderr == ""
        assert repl.locals.get("z") == 3
        # _rlm_tracemalloc should NOT be in namespace (old injection artifact)
        assert "_rlm_tracemalloc" not in repl.locals
        repl.cleanup()

    def test_trace_timing_preserved_on_error(self, monkeypatch):
        """Trace timing should be set even when code raises an error."""
        monkeypatch.setenv("RLM_REPL_TRACE", "1")
        repl = LocalREPL()
        trace = REPLTrace()
        result = repl.execute_code("raise ValueError('boom')", trace=trace)
        assert trace.start_time > 0
        assert trace.end_time >= trace.start_time
        assert "ValueError" in result.stderr
        repl.cleanup()

    def test_correct_line_numbers_in_errors(self, monkeypatch):
        """Error line numbers should NOT be offset by injected header code."""
        monkeypatch.setenv("RLM_REPL_TRACE", "2")
        repl = LocalREPL()
        trace = REPLTrace()
        code = "x = 1\ny = 2\nraise ValueError('line 3 error')"
        result = repl.execute_code(code, trace=trace)
        assert "ValueError" in result.stderr
        # The error should reference line 3 (the actual user code line),
        # not a shifted line number from injected header code.
        # With code injection, the header adds ~8 lines, so line 3 becomes ~11.
        # With callbacks, line 3 stays line 3.
        assert "line 3" in result.stderr or "line 3" in str(result.trace)
        repl.cleanup()


# ── Feature 3: Capture ExecutionResult.result ─────────────────────────────


class TestCaptureExecutionResult:
    """Feature 3: Capture the last expression value from IPython's run_cell."""

    def test_last_expression_captured_in_locals(self, repl):
        """The value of the last expression should be stored as _ in locals."""
        result = repl.execute_code("x = 10\nx + 5")
        # The last expression (x + 5 = 15) should be captured
        assert result.locals.get("_last_expr") == 15

    def test_last_expression_none_for_statement(self, repl):
        """When the last line is a statement (not expression), no result captured."""
        result = repl.execute_code("x = 10")
        assert result.locals.get("_last_expr") is None

    def test_last_expression_string(self, repl):
        """String expression results should be captured."""
        result = repl.execute_code("'hello' + ' world'")
        assert result.locals.get("_last_expr") == "hello world"

    def test_last_expression_list(self, repl):
        """List expression results should be captured."""
        result = repl.execute_code("[1, 2, 3]")
        assert result.locals.get("_last_expr") == [1, 2, 3]

    def test_last_expression_not_pollute_namespace(self, repl):
        """The _last_expr key should NOT appear in user-visible SHOW_VARS."""
        repl.execute_code("[1, 2, 3]")
        show_result = repl.execute_code("print(SHOW_VARS())")
        # _last_expr starts with underscore, so should be filtered by SHOW_VARS
        assert "_last_expr" not in show_result.stdout

    def test_last_expression_available_for_data_flow(self, repl):
        """The captured result should be available for data flow tracking."""
        result = repl.execute_code("42 * 2")
        assert result.locals.get("_last_expr") == 84

    def test_print_does_not_set_last_expr(self, repl):
        """print() returns None, so _last_expr should be None."""
        result = repl.execute_code("print('hello')")
        assert result.locals.get("_last_expr") is None

    def test_last_expression_on_error(self, repl):
        """On error, _last_expr should be None."""
        result = repl.execute_code("1/0")
        assert result.locals.get("_last_expr") is None
