"""FR-008/009: Persistent session state and non-persistent isolation.

Covers:
- FR-008: Persistent mode - histories accumulate, vars persist
- FR-009: Non-persistent mode - fresh REPL per completion, no var leakage
"""

from rlm_adk.repl.local_repl import LocalREPL

# ── FR-008 Persistent Session State ──────────────────────────────────────


class TestPersistentVariables:
    """FR-008: Variables must persist across turns in same persistent session."""

    def test_vars_persist_across_executions(self):
        repl = LocalREPL()
        repl.execute_code("x = 10")
        repl.execute_code("y = x + 5")
        assert repl.locals["x"] == 10
        assert repl.locals["y"] == 15
        repl.cleanup()

    def test_function_persists(self):
        repl = LocalREPL()
        repl.execute_code("def double(n): return n * 2")
        result = repl.execute_code("print(double(21))")
        assert result.stdout.strip() == "42"
        repl.cleanup()


# ── FR-009 Non-Persistent Isolation ──────────────────────────────────────


class TestNonPersistentIsolation:
    """FR-009: Fresh REPL per completion, no leakage between sessions."""

    def test_separate_repls_isolated(self):
        repl1 = LocalREPL()
        repl1.execute_code("secret = 42")
        repl1.cleanup()

        repl2 = LocalREPL()
        result = repl2.execute_code("print(secret)")
        assert "NameError" in result.stderr
        repl2.cleanup()

    def test_cleanup_removes_all_state(self):
        repl = LocalREPL()
        repl.execute_code("x = 1")
        repl.cleanup()
        assert repl.locals == {}
        assert repl.globals == {}

    def test_default_is_non_persistent(self):
        """Default mode shall be non-persistent unless explicitly enabled."""
        # By default, each LocalREPL is independent - no shared state
        repl1 = LocalREPL()
        repl1.execute_code("shared = True")

        repl2 = LocalREPL()
        result = repl2.execute_code("print(shared)")
        assert "NameError" in result.stderr

        repl1.cleanup()
        repl2.cleanup()
