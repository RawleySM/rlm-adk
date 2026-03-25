"""Unit tests for instrumented_runner.py components and test_skill.py registration."""

from __future__ import annotations

import sys

from tests_rlm_adk.provider_fake.instrumented_runner import (
    _build_state_key_timeline,
    _capture_stdout,
)


class TestBuildStateKeyTimeline:
    """Tests for _build_state_key_timeline(log) parsing."""

    def test_basic_scoped_entries(self):
        log = "[STATE:model_call_1:iteration_count=0]\n[STATE:post_tool:iteration_count=1]\n"
        timeline = _build_state_key_timeline(log)
        assert "iteration_count" in timeline
        entries = timeline["iteration_count"]
        assert entries[0] == ("model_call_1", "0")
        assert entries[1] == ("post_tool", "1")

    def test_multiple_keys(self):
        log = "[STATE:model_call_1:iteration_count=0]\n[STATE:model_call_1:should_stop=False]\n"
        timeline = _build_state_key_timeline(log)
        assert "iteration_count" in timeline
        assert "should_stop" in timeline

    def test_no_scope_defaults_to_global(self):
        log = "[STATE:iteration_count=5]\n"
        timeline = _build_state_key_timeline(log)
        assert timeline["iteration_count"][0][0] == "global"
        assert timeline["iteration_count"][0][1] == "5"

    def test_complex_scope_with_colons(self):
        log = "[STATE:pre_tool:obs:reasoning_retry_count=3]\n"
        timeline = _build_state_key_timeline(log)
        # rsplit(":", 1) on "pre_tool:obs:reasoning_retry_count" => ("pre_tool:obs", "reasoning_retry_count")
        assert "reasoning_retry_count" in timeline
        assert timeline["reasoning_retry_count"][0] == ("pre_tool:obs", "3")

    def test_empty_log(self):
        assert _build_state_key_timeline("") == {}

    def test_non_state_lines_ignored(self):
        log = "[PLUGIN:before_model:agent:key=val]\n[TEST_SKILL:depth=0]\nplain text\n"
        assert _build_state_key_timeline(log) == {}

    def test_line_without_equals_ignored(self):
        log = "[STATE:malformed_no_equals]\n"
        assert _build_state_key_timeline(log) == {}

    def test_state_transition_tracking(self):
        """Timeline captures the lifecycle of a key across phases."""
        log = (
            "[STATE:model_call_1:repl_did_expand=False]\n"
            "[STATE:pre_tool:repl_did_expand=False]\n"
            "[STATE:post_tool:repl_did_expand=True]\n"
            "[STATE:after_agent:repl_did_expand=True]\n"
        )
        timeline = _build_state_key_timeline(log)
        entries = timeline["repl_did_expand"]
        assert len(entries) == 4
        # Transition from False to True at post_tool
        assert entries[0][1] == "False"
        assert entries[2][1] == "True"

    def test_value_with_equals_sign(self):
        """Values containing '=' should be preserved (only first '=' splits)."""
        log = "[STATE:post_tool:formula=a=b+c]\n"
        timeline = _build_state_key_timeline(log)
        assert "formula" in timeline
        assert timeline["formula"][0] == ("post_tool", "a=b+c")

    def test_multiple_entries_same_key_accumulate(self):
        """Multiple STATE lines for the same key build a list."""
        log = "[STATE:t1:x=1]\n[STATE:t2:x=2]\n[STATE:t3:x=3]\n"
        timeline = _build_state_key_timeline(log)
        assert len(timeline["x"]) == 3
        assert [v for _, v in timeline["x"]] == ["1", "2", "3"]


class TestCaptureStdout:
    """Tests for _capture_stdout() TeeWriter context manager."""

    def test_captures_printed_output(self):
        with _capture_stdout() as captured:
            print("hello world")
        assert "hello world" in captured.getvalue()

    def test_multiple_prints(self):
        with _capture_stdout() as captured:
            print("line 1")
            print("line 2")
        val = captured.getvalue()
        assert "line 1" in val
        assert "line 2" in val

    def test_restores_stdout(self):
        original = sys.stdout
        with _capture_stdout():
            pass
        assert sys.stdout is original

    def test_restores_stdout_on_exception(self):
        original = sys.stdout
        try:
            with _capture_stdout():
                raise ValueError("test error")
        except ValueError:
            pass
        assert sys.stdout is original

    def test_captures_flush(self):
        with _capture_stdout() as captured:
            print("flushed", flush=True)
        assert "flushed" in captured.getvalue()

    def test_empty_capture(self):
        with _capture_stdout() as captured:
            pass
        assert captured.getvalue() == ""

    def test_write_returns_length(self):
        """TeeWriter.write() returns len(text) per the io protocol."""
        with _capture_stdout():
            n = sys.stdout.write("abc")
        assert n == 3


class TestTestSkillRegistration:
    """Tests that test_skill is discovered and loaded by the skill loader."""

    def test_skill_dir_discovered(self):
        from rlm_adk.skills.loader import discover_skill_dirs

        dirs = discover_skill_dirs(enabled_skills={"test_skill"})
        names = [d.name for d in dirs]
        assert "test_skill" in names

    def test_skill_exports_collected(self):
        from rlm_adk.skills.loader import collect_skill_repl_globals

        collected = collect_skill_repl_globals(enabled_skills={"test_skill"})
        assert "run_test_skill" in collected
        assert "TestSkillResult" in collected

    def test_run_test_skill_is_wrapped(self):
        """run_test_skill has llm_query_fn param, so loader wraps it."""
        from rlm_adk.skills.loader import collect_skill_repl_globals

        collected = collect_skill_repl_globals(enabled_skills={"test_skill"})
        fn = collected["run_test_skill"]
        # The wrapper is a functools.wraps'd function
        assert callable(fn)
        # Calling without llm_query wired should raise
        import pytest

        with pytest.raises(RuntimeError, match="llm_query"):
            fn(child_prompt="test")

    def test_llm_query_fn_auto_injected(self):
        """When repl_globals has llm_query, it's auto-injected."""
        from rlm_adk.skills.loader import collect_skill_repl_globals

        repl_globals: dict = {}
        collected = collect_skill_repl_globals(
            enabled_skills={"test_skill"},
            repl_globals=repl_globals,
        )
        # Simulate llm_query being wired into REPL globals
        repl_globals["llm_query"] = lambda prompt: f"echo: {prompt}"

        result = collected["run_test_skill"](
            child_prompt="hello",
            rlm_state={"_rlm_depth": 0},
        )
        assert "echo: hello" in result.child_result

    def test_no_expansion_needed(self):
        """Module-import skills don't need source expansion."""
        from rlm_adk.skills.test_skill import run_test_skill

        # Direct import works -- this is a real Python module
        assert callable(run_test_skill)
