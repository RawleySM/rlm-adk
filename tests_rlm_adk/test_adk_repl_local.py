"""FR-005/006/007 + NF-003: Local REPL execution, helpers.

Covers:
- FR-005 REPL Execution Core Behavior
- FR-006 REPL Helpers (FINAL_VAR, SHOW_VARS)
- FR-004 REPL Code Block Parsing (via find_code_blocks)
- FR-003 Final Answer Extraction Semantics
- NF-003 REPL Runtime Failures
"""

import os

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.utils.parsing import find_code_blocks, find_final_answer

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


# ── FR-004 REPL Code Block Parsing ──────────────────────────────────────


class TestFindCodeBlocks:
    """FR-004: Only fenced blocks tagged 'repl' shall be extracted."""

    def test_single_block(self):
        text = "Here is code:\n```repl\nprint('hi')\n```\nDone."
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0] == "print('hi')"

    def test_multiple_blocks_preserve_order(self):
        text = "```repl\nx = 1\n```\nSome text\n```repl\ny = 2\n```"
        blocks = find_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0] == "x = 1"
        assert blocks[1] == "y = 2"

    def test_non_repl_fences_ignored(self):
        text = "```python\nx = 1\n```\n```repl\ny = 2\n```\n```javascript\nvar z = 3;\n```"
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0] == "y = 2"

    def test_no_blocks_returns_empty(self):
        text = "No code blocks here."
        blocks = find_code_blocks(text)
        assert blocks == []

    def test_multiline_block(self):
        text = "```repl\nfor i in range(3):\n    print(i)\n```"
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert "for i in range(3):" in blocks[0]


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
