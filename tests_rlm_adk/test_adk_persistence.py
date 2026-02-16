"""FR-008/009: Persistent session state and non-persistent isolation.

Covers:
- FR-008: Persistent mode - contexts accumulate, histories accumulate, vars persist
- FR-009: Non-persistent mode - fresh REPL per completion, no var leakage
"""

from rlm_adk.repl.local_repl import LocalREPL

# ── FR-008 Persistent Session State ──────────────────────────────────────


class TestPersistentContextAccumulation:
    """FR-008: Contexts shall accumulate as context_0..N."""

    def test_add_context_increments_count(self):
        repl = LocalREPL(context_payload="first")
        assert repl.get_context_count() == 1

        repl.add_context("second")
        assert repl.get_context_count() == 2
        repl.cleanup()

    def test_context_0_alias_is_context(self):
        repl = LocalREPL(context_payload="first")
        result = repl.execute_code("print(context)")
        assert "first" in result.stdout
        repl.cleanup()

    def test_multiple_contexts_accessible(self):
        repl = LocalREPL(context_payload="first")
        repl.add_context("second")
        result = repl.execute_code("print(context_0)")
        assert "first" in result.stdout
        result = repl.execute_code("print(context_1)")
        assert "second" in result.stdout
        repl.cleanup()

    def test_dict_context_accumulation(self):
        repl = LocalREPL(context_payload={"a": 1})
        repl.add_context({"b": 2})
        result = repl.execute_code("print(context_0['a'], context_1['b'])")
        assert "1" in result.stdout
        assert "2" in result.stdout
        repl.cleanup()


class TestPersistentHistoryAccumulation:
    """FR-008: Histories shall accumulate as history_0..N."""

    def test_add_history_increments_count(self):
        repl = LocalREPL()
        assert repl.get_history_count() == 0

        history = [{"role": "user", "content": "hello"}]
        repl.add_history(history)
        assert repl.get_history_count() == 1
        repl.cleanup()

    def test_history_0_alias_is_history(self):
        repl = LocalREPL()
        history = [{"role": "user", "content": "first turn"}]
        repl.add_history(history)
        assert "history" in repl.locals
        assert repl.locals["history"] == history
        repl.cleanup()

    def test_multiple_histories(self):
        repl = LocalREPL()
        h0 = [{"role": "user", "content": "turn 0"}]
        h1 = [{"role": "user", "content": "turn 1"}]
        repl.add_history(h0)
        repl.add_history(h1)
        assert repl.get_history_count() == 2
        assert repl.locals["history_0"][0]["content"] == "turn 0"
        assert repl.locals["history_1"][0]["content"] == "turn 1"
        repl.cleanup()

    def test_histories_are_deep_copied(self):
        """FR-008: Stored histories must be copied, not referenced."""
        repl = LocalREPL()
        original = [{"role": "user", "content": "original"}]
        repl.add_history(original)

        # Mutate the original
        original[0]["content"] = "mutated"

        # Stored copy should be unaffected
        assert repl.locals["history_0"][0]["content"] == "original"
        repl.cleanup()


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

    def test_context_not_shared(self):
        repl1 = LocalREPL(context_payload="session1_data")
        repl1.cleanup()

        repl2 = LocalREPL()
        result = repl2.execute_code("print(context)")
        assert "NameError" in result.stderr
        repl2.cleanup()

    def test_cleanup_removes_all_state(self):
        repl = LocalREPL(context_payload="test")
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
