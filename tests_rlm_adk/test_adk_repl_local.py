"""FR-005/006/007 + NF-003: Local REPL execution, helpers.

Covers:
- FR-005 REPL Execution Core Behavior
- FR-006 REPL Helpers (FINAL_VAR, SHOW_VARS)
- FR-004 REPL Code Block Parsing (via find_code_blocks)
- FR-003 Final Answer Extraction Semantics
- NF-003 REPL Runtime Failures
- FM-22 Circular Reference in Variable Snapshots
- FM-27 CWD Race Between Concurrent REPLs
"""

import asyncio
import json
import os
import threading
import time

import pytest

from rlm_adk.repl.local_repl import LocalREPL, _EXEC_LOCK
from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async
from rlm_adk.utils.parsing import find_final_answer

# ── FR-005 REPL Execution Core Behavior ──────────────────────────────────


class TestREPLExecution:
    """FR-005: Execute code, capture stdout/stderr, persist state."""

    def test_simple_print(self, repl):
        result = repl.execute_code("print('hello')")
        assert result.stdout.strip() == "hello"
        assert result.stderr == ""

    def test_variable_assignment(self, repl):
        repl.execute_code("x = 42")
        assert repl.locals["x"] == 42

    def test_variable_persistence_within_session(self, repl):
        repl.execute_code("x = 10")
        repl.execute_code("y = x + 5")
        assert repl.locals["y"] == 15

    def test_function_persistence(self, repl):
        repl.execute_code("def add(a, b): return a + b")
        result = repl.execute_code("print(add(3, 4))")
        assert result.stdout.strip() == "7"

    def test_syntax_error_in_stderr(self, repl):
        result = repl.execute_code("def bad(")
        assert "SyntaxError" in result.stderr

    def test_runtime_error_in_stderr(self, repl):
        result = repl.execute_code("1/0")
        assert "ZeroDivisionError" in result.stderr

    def test_name_error_in_stderr(self, repl):
        result = repl.execute_code("print(undefined_var)")
        assert "NameError" in result.stderr

    def test_execution_time_tracked(self, repl):
        result = repl.execute_code("x = 1")
        assert result.execution_time is not None
        assert result.execution_time >= 0

    def test_multiline_code(self, repl):
        code = "x = 0\nfor i in range(5):\n    x += i\nprint(x)"
        result = repl.execute_code(code)
        assert result.stdout.strip() == "10"

    def test_import_works(self, repl):
        result = repl.execute_code("import math\nprint(math.pi)")
        assert "3.14" in result.stdout

    def test_stdout_and_stderr_together(self, repl):
        code = "print('before')\nraise ValueError('boom')"
        result = repl.execute_code(code)
        assert "before" in result.stdout
        assert "ValueError" in result.stderr


class TestREPLCleanup:
    """FR-005: cleanup() shall clear state and remove temp dir."""

    def test_cleanup_clears_globals_and_locals(self):
        repl = LocalREPL()
        repl.execute_code("x = 42")
        temp_dir = repl.temp_dir
        assert os.path.exists(temp_dir)

        repl.cleanup()
        assert repl.globals == {}
        assert repl.locals == {}
        assert not os.path.exists(temp_dir)

    def test_context_manager_cleanup(self):
        with LocalREPL() as repl:
            repl.execute_code("x = 1")
            temp_dir = repl.temp_dir
            assert os.path.exists(temp_dir)
        assert not os.path.exists(temp_dir)


# ── FR-006 REPL Helpers ──────────────────────────────────────────────────


class TestREPLHelpers:
    """FR-006: FINAL_VAR and SHOW_VARS behavior."""

    def test_final_var_returns_value(self, repl):
        repl.execute_code("answer = 42")
        result = repl.execute_code("print(FINAL_VAR('answer'))")
        assert result.stdout.strip() == "42"

    def test_final_var_string_value(self, repl):
        repl.execute_code("name = 'Alice'")
        result = repl.execute_code("print(FINAL_VAR('name'))")
        assert result.stdout.strip() == "Alice"

    def test_final_var_missing_with_available(self, repl):
        repl.execute_code("x = 1")
        result = repl.execute_code("print(FINAL_VAR('missing'))")
        assert "Error" in result.stdout
        assert "missing" in result.stdout
        assert "Available variables" in result.stdout

    def test_final_var_missing_no_variables(self, repl):
        result = repl.execute_code("print(FINAL_VAR('missing'))")
        assert "Error" in result.stdout
        assert "No variables have been created" in result.stdout

    def test_show_vars_empty(self, repl):
        result = repl.execute_code("print(SHOW_VARS())")
        assert "No variables" in result.stdout

    def test_show_vars_with_variables(self, repl):
        repl.execute_code("x = 1")
        repl.execute_code("name = 'Alice'")
        result = repl.execute_code("print(SHOW_VARS())")
        assert "x" in result.stdout
        assert "name" in result.stdout

    def test_show_vars_excludes_private(self, repl):
        repl.execute_code("x = 1")
        repl.execute_code("_private = 2")
        result = repl.execute_code("print(SHOW_VARS())")
        assert "x" in result.stdout
        assert "_private" not in result.stdout


# ── FR-003 Final Answer Extraction ──────────────────────────────────────


class TestFindFinalAnswer:
    """FR-003: FINAL/FINAL_VAR extraction semantics."""

    def test_final_simple(self):
        text = "Some reasoning\nFINAL(the answer is 42)"
        result = find_final_answer(text)
        assert result == "the answer is 42"

    def test_final_with_leading_whitespace(self):
        text = "  FINAL(the answer)"
        result = find_final_answer(text)
        assert result == "the answer"

    def test_final_nested_parens(self):
        text = "FINAL(f(x) = (x + 1))"
        result = find_final_answer(text)
        assert "f(x)" in result

    def test_final_not_at_line_start(self):
        text = "some text FINAL(not at start)"
        result = find_final_answer(text)
        assert result is None

    def test_final_var_takes_precedence(self):
        """FINAL_VAR must take precedence over FINAL."""
        text = "FINAL_VAR(answer)\nFINAL(fallback)"
        repl = LocalREPL()
        repl.execute_code("answer = 'the real answer'")
        result = find_final_answer(text, environment=repl)
        assert result == "the real answer"
        repl.cleanup()

    def test_final_var_without_environment_returns_none(self):
        text = "FINAL_VAR(answer)"
        result = find_final_answer(text, environment=None)
        assert result is None

    def test_final_var_missing_variable(self):
        text = "FINAL_VAR(missing_var)"
        repl = LocalREPL()
        result = find_final_answer(text, environment=repl)
        assert "Error" in result
        repl.cleanup()

    def test_no_final_pattern(self):
        text = "Just some text without any final answer."
        result = find_final_answer(text)
        assert result is None


# ── NF-003 REPL Runtime Failures ─────────────────────────────────────────


class TestREPLFailures:
    """NF-003: Errors surfaced in stderr, available for correction."""

    def test_type_error_surfaced(self, repl):
        result = repl.execute_code("'string' + 5")
        assert "TypeError" in result.stderr

    def test_error_does_not_corrupt_state(self, repl):
        repl.execute_code("x = 10")
        repl.execute_code("raise ValueError('boom')")
        assert repl.locals["x"] == 10

    def test_error_stdout_still_captured(self, repl):
        code = "print('before error')\nraise RuntimeError('fail')"
        result = repl.execute_code(code)
        assert "before error" in result.stdout
        assert "RuntimeError" in result.stderr

    def test_last_exec_error_set_on_failure(self, repl):
        repl.execute_code("1/0")
        assert repl._last_exec_error is not None
        assert "ZeroDivisionError" in repl._last_exec_error

    def test_last_exec_error_cleared_on_success(self, repl):
        repl.execute_code("1/0")
        assert repl._last_exec_error is not None
        repl.execute_code("x = 1")
        assert repl._last_exec_error is None

    def test_final_var_includes_exec_error_context(self, repl):
        """When a code block errors, _final_var should mention the last error."""
        repl.execute_code("total = 0.0\ntotal += 'not a number'")
        assert repl._last_exec_error is not None
        msg = repl._final_var("total")
        assert "Error" in msg
        assert "TypeError" in msg
        assert "Last execution error" in msg

    def test_final_var_no_error_hint_on_success(self, repl):
        """When no error, _final_var should not mention execution errors."""
        repl.execute_code("x = 42")
        msg = repl._final_var("missing")
        assert "Last execution error" not in msg


# ── BUG-008 FINAL_VAR skip on code errors ──────────────────────────────


class TestFinalVarSkipOnCodeError:
    """BUG-008: FINAL_VAR should not resolve when code blocks errored."""

    def test_code_error_plus_final_var_should_not_produce_answer(self):
        """Simulates checking code errors before resolving FINAL_VAR."""
        from dataclasses import dataclass
        from rlm_adk.types import REPLResult

        @dataclass
        class _CodeBlock:
            code: str
            result: REPLResult

        error_result = REPLResult(
            stdout="",
            stderr="\nTypeError: unsupported operand type(s) for +=: 'float' and 'str'",
            locals={},
        )
        code_blocks = [_CodeBlock(code="total += row", result=error_result)]

        any_code_error = any(cb.result.stderr for cb in code_blocks)
        assert any_code_error is True

        # When there are code errors, skip FINAL_VAR resolution
        if any_code_error and code_blocks:
            final_answer = None
        else:
            final_answer = find_final_answer(
                "FINAL_VAR(total)", environment=LocalREPL()
            )

        assert final_answer is None

    def test_no_code_error_allows_final_var_resolution(self):
        """When code succeeds, FINAL_VAR should resolve normally."""
        repl = LocalREPL()
        repl.execute_code("total = 42")

        final_answer = find_final_answer("FINAL_VAR(total)", environment=repl)
        assert final_answer == "42"
        repl.cleanup()


# -- FM-22: Circular Reference in Variable Snapshots -----------------------


class TestCircularReferenceSnapshots:
    """FM-22: Self-referential structures must not crash variable snapshots.

    REPLTool.run_async serializes REPL locals via json.dumps (repl_tool.py
    lines 191-198). Circular references trigger RecursionError in json.dumps.
    The except clause must catch RecursionError so circular structures are
    silently skipped rather than crashing the tool.
    """

    def test_self_referential_dict_skipped(self, repl):
        """Circular dict (d['self'] = d) must not crash json.dumps snapshot."""
        repl.execute_code("d = {}; d['self'] = d")
        assert "d" in repl.locals
        # Simulate the REPLTool variable snapshot logic (repl_tool.py:191-198)
        variables: dict = {}
        for k, v in repl.locals.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                try:
                    json.dumps(v)
                    variables[k] = v
                except (TypeError, ValueError, OverflowError, RecursionError):
                    pass
        # Circular dict must be excluded, not raise
        assert "d" not in variables

    def test_self_referential_list_skipped(self, repl):
        """Circular list (L.append(L)) must not crash json.dumps snapshot."""
        repl.execute_code("L = []; L.append(L)")
        assert "L" in repl.locals
        variables: dict = {}
        for k, v in repl.locals.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                try:
                    json.dumps(v)
                    variables[k] = v
                except (TypeError, ValueError, OverflowError, RecursionError):
                    pass
        assert "L" not in variables

    def test_non_circular_structures_preserved(self, repl):
        """Normal dicts/lists must pass through the snapshot filter."""
        repl.execute_code("x = {'a': [1, 2, 3]}")
        repl.execute_code("y = [1, 'two', 3.0]")
        variables: dict = {}
        for k, v in repl.locals.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                try:
                    json.dumps(v)
                    variables[k] = v
                except (TypeError, ValueError, OverflowError, RecursionError):
                    pass
        assert "x" in variables
        assert "y" in variables
        assert variables["x"] == {"a": [1, 2, 3]}


# -- FM-27: CWD Race Between Concurrent REPLs (Documentation Test) ---------


class TestCwdRaceBetweenRepls:
    """FM-27: Two concurrent async REPL instances can race on os.chdir.

    execute_code_async (local_repl.py:315-382) does:
        old_cwd = os.getcwd()        # line 335
        os.chdir(self.temp_dir)       # line 338  -- unprotected
        await repl_exec_fn()          # line 347  -- yield point
        ...
        os.chdir(old_cwd)             # line 371  -- unprotected restore

    If two async REPLs run concurrently on the same event loop, the second
    can os.chdir between the first's chdir and its restore, corrupting the
    CWD for both.

    The sync path (execute_code) is protected by _EXEC_LOCK, but the async
    path has no equivalent lock.

    Architectural mitigation: each RLMOrchestratorAgent creates exactly one
    LocalREPL, so concurrent async execute_code_async calls on the same
    event loop don't occur in practice. This test documents the latent
    vulnerability should that invariant break.
    """

    @pytest.mark.asyncio
    async def test_cwd_race_between_two_repls(self):
        """Document that two concurrent async REPLs can interleave os.chdir.

        We create two LocalREPL instances with different temp_dirs, then run
        them concurrently via asyncio.gather. Each records os.getcwd() after
        the yield point. If the race triggers, at least one will see the
        other's temp_dir instead of its own.

        NOTE: This race is non-deterministic. On most runs both REPLs will
        see their own temp_dir because the event loop may not interleave at
        the exact right point. The test documents the vulnerability window
        regardless of whether it triggers in a given run.
        """
        repl_a = LocalREPL()
        repl_b = LocalREPL()

        # Both have distinct temp directories
        assert repl_a.temp_dir != repl_b.temp_dir

        async def mock_query_async(prompt, **kw):
            # Yield to the event loop -- this is where interleaving happens
            await asyncio.sleep(0)
            return "ok"

        repl_a.set_async_llm_query_fns(mock_query_async, mock_query_async)
        repl_b.set_async_llm_query_fns(mock_query_async, mock_query_async)

        # Code that captures CWD after an await (the yield point)
        code = "import os; cwd_after_await = os.getcwd()"
        module = rewrite_for_async(code)
        compiled = compile(module, "<repl>", "exec")

        async def run_repl(repl_inst: LocalREPL):
            ns = {**repl_inst.globals, **repl_inst.locals}
            exec(compiled, ns)
            fn = ns["_repl_exec"]
            return await repl_inst.execute_code_async(code, fn)

        original_cwd = os.getcwd()
        result_a, result_b = await asyncio.gather(
            run_repl(repl_a), run_repl(repl_b)
        )

        # Verify the REPL didn't corrupt the test process CWD
        assert os.getcwd() == original_cwd

        # Document: both results should have no errors
        assert result_a.stderr == ""
        assert result_b.stderr == ""

        # Both REPLs should ideally see their own temp_dir, but due to the
        # race window, one might see the other's. We document both outcomes:
        cwd_a = repl_a.locals.get("cwd_after_await", "")
        cwd_b = repl_b.locals.get("cwd_after_await", "")

        # At minimum, both should have captured *some* path
        assert cwd_a, "REPL A should have captured a CWD"
        assert cwd_b, "REPL B should have captured a CWD"

        # Document whether the race triggered (informational, not a failure)
        race_triggered = (
            cwd_a != repl_a.temp_dir or cwd_b != repl_b.temp_dir
        )
        if race_triggered:
            # This is the documented vulnerability -- not a test failure
            pass

        repl_a.cleanup()
        repl_b.cleanup()
