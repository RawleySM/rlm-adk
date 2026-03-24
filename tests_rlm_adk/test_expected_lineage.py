"""Unit tests for expected_lineage.py — assertion framework for skill_arch_test."""

import pytest

from tests_rlm_adk.provider_fake.expected_lineage import (
    _MISSING,
    AssertionFailure,
    DynInstrExpectation,
    ExpectedLineage,
    OrderingExpectation,
    PluginHookExpectation,
    ReplTraceExpectation,
    StateKeyExpectation,
    TestSkillExpectation,
    TimingExpectation,
    _eval_operator,
    assert_dyn_instr,
    assert_orderings,
    assert_plugin_hooks,
    assert_repl_trace,
    assert_state_keys,
    assert_test_skill_tags,
    assert_timings,
    build_skill_arch_test_lineage,
    run_all_assertions,
)
from tests_rlm_adk.provider_fake.stdout_parser import parse_stdout


def _empty_lineage(**overrides) -> ExpectedLineage:
    """Build a minimal ExpectedLineage with all empty lists, then override specific fields."""
    defaults = dict(
        state_key_expectations=[],
        test_skill_expectations=[],
        plugin_hook_expectations=[],
        timing_expectations=[],
        ordering_expectations=[],
        dyn_instr_expectations=[],
        repl_trace_expectations=[],
    )
    defaults.update(overrides)
    return ExpectedLineage(**defaults)


# ---------------------------------------------------------------------------
# _eval_operator
# ---------------------------------------------------------------------------


class TestEvalOperator:
    def test_eq_strings(self):
        assert _eval_operator("eq", "0", "0") is True
        assert _eval_operator("eq", "0", "1") is False

    def test_eq_coerces_to_str(self):
        assert _eval_operator("eq", 0, "0") is True
        assert _eval_operator("eq", "True", True) is True

    def test_contains(self):
        assert _eval_operator("contains", "arch_test_ok results", "arch_test_ok") is True
        assert _eval_operator("contains", "hello", "world") is False

    def test_not_contains(self):
        assert _eval_operator("not_contains", "hello", "world") is True
        assert _eval_operator("not_contains", "hello world", "world") is False

    def test_gt(self):
        assert _eval_operator("gt", "10", 5) is True
        assert _eval_operator("gt", "5", 5) is False
        assert _eval_operator("gt", "not_a_number", 5) is False

    def test_gte(self):
        assert _eval_operator("gte", "5", 5) is True
        assert _eval_operator("gte", "4", 5) is False

    def test_lt(self):
        assert _eval_operator("lt", "3", 5) is True
        assert _eval_operator("lt", "5", 5) is False

    def test_not_none(self):
        assert _eval_operator("not_none", "value", None) is True
        assert _eval_operator("not_none", None, None) is False
        assert _eval_operator("not_none", _MISSING, None) is False

    def test_oneof(self):
        assert (
            _eval_operator("oneof", "thread_bridge", ["async_rewrite", "thread_bridge"])
            is True
        )
        assert (
            _eval_operator("oneof", "unknown", ["async_rewrite", "thread_bridge"]) is False
        )

    def test_in(self):
        assert _eval_operator("in", "hello world", "hello") is True

    def test_type(self):
        assert _eval_operator("type", [1, 2], "list") is True
        assert _eval_operator("type", "hi", "str") is True
        assert _eval_operator("type", "hi", "int") is False

    def test_unknown_operator(self):
        assert _eval_operator("unknown_op", "a", "b") is False


# ---------------------------------------------------------------------------
# assert_test_skill_tags
# ---------------------------------------------------------------------------


class TestAssertTestSkillTags:
    def test_passing_eq(self):
        log = parse_stdout("[TEST_SKILL:depth=0]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_test_skill_tags(log, lineage)
        assert failures == []

    def test_failing_eq(self):
        log = parse_stdout("[TEST_SKILL:depth=1]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_test_skill_tags(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == "1"
        assert failures[0].expected == "0"

    def test_missing_required_key(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                    required=True,
                ),
            ]
        )
        failures = assert_test_skill_tags(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == _MISSING

    def test_missing_optional_key_no_failure(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                    required=False,
                ),
            ]
        )
        failures = assert_test_skill_tags(log, lineage)
        assert failures == []

    def test_numeric_gt(self):
        log = parse_stdout("[TEST_SKILL:latency_ms=45.2]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="latency_ms",
                    operator="gt",
                    expected=0.0,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_test_skill_tags(log, lineage) == []

    def test_non_numeric_for_gt_fails(self):
        log = parse_stdout("[TEST_SKILL:latency_ms=not_a_number]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="latency_ms",
                    operator="gt",
                    expected=0.0,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_test_skill_tags(log, lineage)
        assert len(failures) == 1

    def test_contains_operator(self):
        log = parse_stdout("[TEST_SKILL:child_result_preview=arch_test_ok done]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="child_result_preview",
                    operator="contains",
                    expected="arch_test_ok",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_test_skill_tags(log, lineage) == []

    def test_oneof_operator(self):
        log = parse_stdout("[TEST_SKILL:execution_mode=thread_bridge]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="execution_mode",
                    operator="oneof",
                    expected=["async_rewrite", "thread_bridge"],
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_test_skill_tags(log, lineage) == []


# ---------------------------------------------------------------------------
# assert_plugin_hooks
# ---------------------------------------------------------------------------


class TestAssertPluginHooks:
    def test_passing(self):
        log = parse_stdout("[PLUGIN:before_agent:reasoning_agent:depth=0]")
        lineage = _empty_lineage(
            plugin_hook_expectations=[
                PluginHookExpectation(
                    hook="before_agent",
                    agent_name="reasoning_agent",
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_plugin_hooks(log, lineage) == []

    def test_missing_required(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            plugin_hook_expectations=[
                PluginHookExpectation(
                    hook="before_agent",
                    agent_name="reasoning_agent",
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert len(assert_plugin_hooks(log, lineage)) == 1

    def test_wrong_value(self):
        log = parse_stdout("[PLUGIN:before_agent:reasoning_agent:depth=1]")
        lineage = _empty_lineage(
            plugin_hook_expectations=[
                PluginHookExpectation(
                    hook="before_agent",
                    agent_name="reasoning_agent",
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_plugin_hooks(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == "1"

    def test_wildcard_agent(self):
        log = parse_stdout("[PLUGIN:before_model:any_agent:call_num=1]")
        lineage = _empty_lineage(
            plugin_hook_expectations=[
                PluginHookExpectation(
                    hook="before_model",
                    agent_name="*",
                    key="call_num",
                    operator="gte",
                    expected=1,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_plugin_hooks(log, lineage) == []


# ---------------------------------------------------------------------------
# assert_state_keys
# ---------------------------------------------------------------------------


class TestAssertStateKeys:
    def test_passing(self):
        log = parse_stdout("[STATE:model_call_1:iteration_count=0]")
        lineage = _empty_lineage(
            state_key_expectations=[
                StateKeyExpectation(
                    phase="model_call_1",
                    key="iteration_count",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_state_keys(log, lineage) == []

    def test_missing_required(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            state_key_expectations=[
                StateKeyExpectation(
                    phase="model_call_1",
                    key="iteration_count",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert len(assert_state_keys(log, lineage)) == 1

    def test_wrong_value(self):
        log = parse_stdout("[STATE:model_call_1:iteration_count=5]")
        lineage = _empty_lineage(
            state_key_expectations=[
                StateKeyExpectation(
                    phase="model_call_1",
                    key="iteration_count",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_state_keys(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == "5"
        assert failures[0].group == "state_key"

    def test_missing_optional_no_failure(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            state_key_expectations=[
                StateKeyExpectation(
                    phase="model_call_1",
                    key="iteration_count",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                    required=False,
                ),
            ]
        )
        assert assert_state_keys(log, lineage) == []


# ---------------------------------------------------------------------------
# assert_timings
# ---------------------------------------------------------------------------


class TestAssertTimings:
    def test_passing(self):
        log = parse_stdout("[TIMING:agent_reasoning_agent_ms=50.0]")
        lineage = _empty_lineage(
            timing_expectations=[
                TimingExpectation(
                    label="agent_reasoning_agent_ms",
                    operator="gte",
                    expected_ms=0.0,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_timings(log, lineage) == []

    def test_missing(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            timing_expectations=[
                TimingExpectation(
                    label="agent_ms",
                    operator="gte",
                    expected_ms=0.0,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_timings(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == _MISSING

    def test_value_fails_constraint(self):
        log = parse_stdout("[TIMING:agent_ms=3.0]")
        lineage = _empty_lineage(
            timing_expectations=[
                TimingExpectation(
                    label="agent_ms",
                    operator="gt",
                    expected_ms=10.0,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_timings(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == 3.0


# ---------------------------------------------------------------------------
# assert_orderings
# ---------------------------------------------------------------------------


class TestAssertOrderings:
    def test_correct_order(self):
        stdout = (
            "[PLUGIN:before_agent:reasoning_agent:depth=0]\n"
            "[PLUGIN:before_model:reasoning_agent:call_num=1]"
        )
        log = parse_stdout(stdout)
        lineage = _empty_lineage(
            ordering_expectations=[
                OrderingExpectation(
                    first_hook="before_agent",
                    first_agent="reasoning_agent",
                    second_hook="before_model",
                    second_agent="reasoning_agent",
                    description="agent before model",
                ),
            ]
        )
        assert assert_orderings(log, lineage) == []

    def test_reversed_order_fails(self):
        stdout = (
            "[PLUGIN:before_model:reasoning_agent:call_num=1]\n"
            "[PLUGIN:before_agent:reasoning_agent:depth=0]"
        )
        log = parse_stdout(stdout)
        lineage = _empty_lineage(
            ordering_expectations=[
                OrderingExpectation(
                    first_hook="before_agent",
                    first_agent="reasoning_agent",
                    second_hook="before_model",
                    second_agent="reasoning_agent",
                    description="agent before model",
                ),
            ]
        )
        assert len(assert_orderings(log, lineage)) == 1

    def test_missing_first_hook(self):
        log = parse_stdout("[PLUGIN:before_model:reasoning_agent:call_num=1]")
        lineage = _empty_lineage(
            ordering_expectations=[
                OrderingExpectation(
                    first_hook="before_agent",
                    first_agent="reasoning_agent",
                    second_hook="before_model",
                    second_agent="reasoning_agent",
                    description="test",
                ),
            ]
        )
        assert len(assert_orderings(log, lineage)) == 1

    def test_missing_second_hook(self):
        log = parse_stdout("[PLUGIN:before_agent:reasoning_agent:depth=0]")
        lineage = _empty_lineage(
            ordering_expectations=[
                OrderingExpectation(
                    first_hook="before_agent",
                    first_agent="reasoning_agent",
                    second_hook="before_model",
                    second_agent="reasoning_agent",
                    description="test",
                ),
            ]
        )
        assert len(assert_orderings(log, lineage)) == 1


# ---------------------------------------------------------------------------
# assert_dyn_instr
# ---------------------------------------------------------------------------


class TestAssertDynInstr:
    def test_passing_contains(self):
        log = parse_stdout("[DYN_INSTR:repo_url=resolved=True]")
        lineage = _empty_lineage(
            dyn_instr_expectations=[
                DynInstrExpectation(
                    key="repo_url",
                    operator="contains",
                    expected="resolved=True",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        assert assert_dyn_instr(log, lineage) == []

    def test_missing_required(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            dyn_instr_expectations=[
                DynInstrExpectation(
                    key="repo_url",
                    operator="contains",
                    expected="resolved=True",
                    source_file="test.py",
                    source_hint="hint",
                    required=True,
                ),
            ]
        )
        assert len(assert_dyn_instr(log, lineage)) == 1

    def test_missing_optional_no_failure(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            dyn_instr_expectations=[
                DynInstrExpectation(
                    key="repo_url",
                    operator="contains",
                    expected="resolved=True",
                    source_file="test.py",
                    source_hint="hint",
                    required=False,
                ),
            ]
        )
        assert assert_dyn_instr(log, lineage) == []

    def test_wrong_value_fails(self):
        log = parse_stdout("[DYN_INSTR:repo_url=resolved=False]")
        lineage = _empty_lineage(
            dyn_instr_expectations=[
                DynInstrExpectation(
                    key="repo_url",
                    operator="eq",
                    expected="resolved=True",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        failures = assert_dyn_instr(log, lineage)
        assert len(failures) == 1
        assert failures[0].group == "dyn_instr"


# ---------------------------------------------------------------------------
# assert_repl_trace
# ---------------------------------------------------------------------------


class TestAssertReplTrace:
    def test_passing(self):
        log = parse_stdout("[REPL_TRACE:execution_mode=thread_bridge]")
        lineage = _empty_lineage(
            repl_trace_expectations=[
                ReplTraceExpectation(
                    key="execution_mode",
                    operator="oneof",
                    expected=["async_rewrite", "thread_bridge", "sync"],
                    source_file="test.py",
                    source_hint="hint",
                    required=True,
                ),
            ]
        )
        assert assert_repl_trace(log, lineage) == []

    def test_missing_not_required_skips(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            repl_trace_expectations=[
                ReplTraceExpectation(
                    key="execution_mode",
                    operator="oneof",
                    expected=["async_rewrite", "thread_bridge"],
                    source_file="test.py",
                    source_hint="hint",
                    required=False,
                ),
            ]
        )
        assert assert_repl_trace(log, lineage) == []

    def test_missing_required_fails(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            repl_trace_expectations=[
                ReplTraceExpectation(
                    key="execution_mode",
                    operator="oneof",
                    expected=["async_rewrite", "thread_bridge"],
                    source_file="test.py",
                    source_hint="hint",
                    required=True,
                ),
            ]
        )
        assert len(assert_repl_trace(log, lineage)) == 1

    def test_present_but_wrong_always_fails(self):
        log = parse_stdout("[REPL_TRACE:execution_mode=unknown_mode]")
        lineage = _empty_lineage(
            repl_trace_expectations=[
                ReplTraceExpectation(
                    key="execution_mode",
                    operator="oneof",
                    expected=["async_rewrite", "thread_bridge"],
                    source_file="test.py",
                    source_hint="hint",
                    required=False,
                ),
            ]
        )
        assert len(assert_repl_trace(log, lineage)) == 1

    def test_numeric_gt(self):
        log = parse_stdout("[REPL_TRACE:wall_time_ms=50.3]")
        lineage = _empty_lineage(
            repl_trace_expectations=[
                ReplTraceExpectation(
                    key="wall_time_ms",
                    operator="gt",
                    expected=0.0,
                    source_file="test.py",
                    source_hint="hint",
                    required=True,
                ),
            ]
        )
        assert assert_repl_trace(log, lineage) == []

    def test_non_numeric_for_gt_fails(self):
        log = parse_stdout("[REPL_TRACE:wall_time_ms=NaN_text]")
        lineage = _empty_lineage(
            repl_trace_expectations=[
                ReplTraceExpectation(
                    key="wall_time_ms",
                    operator="gt",
                    expected=0.0,
                    source_file="test.py",
                    source_hint="hint",
                    required=True,
                ),
            ]
        )
        failures = assert_repl_trace(log, lineage)
        assert len(failures) == 1
        assert failures[0].actual == "NaN_text"


# ---------------------------------------------------------------------------
# run_all_assertions
# ---------------------------------------------------------------------------


class TestRunAllAssertions:
    def test_all_pass(self):
        log = parse_stdout("[TEST_SKILL:COMPLETE=True]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="COMPLETE",
                    operator="eq",
                    expected="True",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        report = run_all_assertions(log, lineage)
        assert report.passed
        assert "PASS" in report.format_report()

    def test_failure_report(self):
        log = parse_stdout("[TEST_SKILL:depth=1]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        report = run_all_assertions(log, lineage)
        assert not report.passed
        assert "FAIL" in report.format_report()
        assert len(report.failures) == 1

    def test_groups_filter(self):
        log = parse_stdout("[TEST_SKILL:depth=1]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ],
            timing_expectations=[
                TimingExpectation(
                    label="missing_ms",
                    operator="gte",
                    expected_ms=0.0,
                    source_file="test.py",
                    source_hint="hint",
                ),
            ],
        )
        # Only check timing group — test_skill failure should not appear
        report = run_all_assertions(log, lineage, groups=["timing"])
        assert "test_skill" not in report.groups_checked
        assert "timing" in report.groups_checked

    def test_raise_if_failed(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        report = run_all_assertions(log, lineage)
        with pytest.raises(AssertionError, match="FAIL"):
            report.raise_if_failed()

    def test_raise_if_passed_is_noop(self):
        log = parse_stdout("[TEST_SKILL:depth=0]")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ]
        )
        report = run_all_assertions(log, lineage)
        report.raise_if_failed()  # should not raise

    def test_failures_in_group(self):
        log = parse_stdout("")
        lineage = _empty_lineage(
            test_skill_expectations=[
                TestSkillExpectation(
                    key="depth",
                    operator="eq",
                    expected="0",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ],
            dyn_instr_expectations=[
                DynInstrExpectation(
                    key="repo_url",
                    operator="contains",
                    expected="True",
                    source_file="test.py",
                    source_hint="hint",
                ),
            ],
        )
        report = run_all_assertions(log, lineage)
        assert len(report.failures_in_group("test_skill")) == 1
        assert len(report.failures_in_group("dyn_instr")) == 1
        assert len(report.failures_in_group("timing")) == 0

    def test_all_groups_checked_by_default(self):
        log = parse_stdout("")
        lineage = _empty_lineage()
        report = run_all_assertions(log, lineage)
        assert len(report.groups_checked) == 7
        assert report.passed


# ---------------------------------------------------------------------------
# build_skill_arch_test_lineage structure
# ---------------------------------------------------------------------------


class TestBuildLineageStructure:
    def test_returns_expected_lineage(self):
        lineage = build_skill_arch_test_lineage()
        assert isinstance(lineage, ExpectedLineage)

    def test_has_all_groups(self):
        lineage = build_skill_arch_test_lineage()
        assert len(lineage.state_key_expectations) >= 3
        assert len(lineage.test_skill_expectations) >= 10
        assert len(lineage.plugin_hook_expectations) >= 4
        assert len(lineage.timing_expectations) >= 2
        assert len(lineage.ordering_expectations) >= 3
        assert len(lineage.dyn_instr_expectations) >= 5
        assert len(lineage.repl_trace_expectations) >= 5

    def test_resolution_a_iteration_count(self):
        """Resolution A: model_call_1 has iteration_count=0, TEST_SKILL has =1."""
        lineage = build_skill_arch_test_lineage()
        state_mc1 = [
            e
            for e in lineage.state_key_expectations
            if e.phase == "model_call_1" and e.key == "iteration_count"
        ]
        assert state_mc1[0].expected == "0"  # NOT "1"

        ts_iter = [e for e in lineage.test_skill_expectations if e.key == "iteration_count"]
        assert ts_iter[0].expected == "1"  # REPLTool incremented

    def test_resolution_c_dyn_instr_keys(self):
        """Resolution C: DYN_INSTR keys use contains operator, not compound key."""
        lineage = build_skill_arch_test_lineage()
        repo = [e for e in lineage.dyn_instr_expectations if e.key == "repo_url"]
        assert len(repo) >= 1
        assert repo[0].operator == "contains"
        assert repo[0].expected == "resolved=True"

    def test_resolution_d_repl_trace_not_required(self):
        """Resolution D: All REPL_TRACE expectations have required=False."""
        lineage = build_skill_arch_test_lineage()
        for exp in lineage.repl_trace_expectations:
            assert exp.required is False, f"REPL_TRACE key {exp.key!r} should be required=False"


# ---------------------------------------------------------------------------
# AssertionFailure formatting
# ---------------------------------------------------------------------------


class TestAssertionFailureFormat:
    def test_format_includes_all_fields(self):
        f = AssertionFailure(
            group="test_skill",
            phase="repl_stdout",
            key="depth",
            expected="0",
            actual="1",
            operator="eq",
            source_file="repl_tool.py",
            source_hint="line 220",
            fix_hint="check depth",
        )
        text = f.format()
        assert "FAIL" in text
        assert "test_skill" in text
        assert "depth" in text
        assert "repl_tool.py" in text
