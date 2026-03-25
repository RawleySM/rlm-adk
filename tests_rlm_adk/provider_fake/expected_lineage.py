"""expected_lineage.py — expected pipeline state and assertion framework for skill_arch_test.

Location: tests_rlm_adk/provider_fake/expected_lineage.py

Contains:
- Expectation dataclasses for each assertion group
- ExpectedLineage container
- build_skill_arch_test_lineage() with conflict resolutions applied
- AssertionFailure, AssertionReport, and all assertion functions
- run_all_assertions() unified entry point
"""

from __future__ import annotations

import dataclasses
from typing import Any

from .stdout_parser import ParsedLog

# ---------------------------------------------------------------------------
# Expectation dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class StateKeyExpectation:
    """Expected value constraints for a single state key at a specific phase."""
    phase: str
    key: str
    operator: str
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class TestSkillExpectation:
    """Expected value for a [TEST_SKILL:key=value] tag."""
    key: str
    operator: str
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class PluginHookExpectation:
    """Expected plugin hook entry."""
    hook: str
    agent_name: str
    key: str
    operator: str
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class TimingExpectation:
    """Expected timing constraint."""
    label: str
    operator: str
    expected_ms: float
    source_file: str
    source_hint: str


@dataclasses.dataclass
class OrderingExpectation:
    """Assert that one hook appears before another in the log."""
    first_hook: str
    first_agent: str
    second_hook: str
    second_agent: str
    description: str


@dataclasses.dataclass
class DynInstrExpectation:
    """Expected [DYN_INSTR:key=value] assertion."""
    key: str
    operator: str
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class ReplTraceExpectation:
    """Expected [REPL_TRACE:key=value] assertion."""
    key: str
    operator: str
    expected: Any
    source_file: str
    source_hint: str
    required: bool = False


@dataclasses.dataclass
class ExpectedLineage:
    """Complete expected lineage for the skill_arch_test fixture."""
    state_key_expectations: list[StateKeyExpectation]
    test_skill_expectations: list[TestSkillExpectation]
    plugin_hook_expectations: list[PluginHookExpectation]
    timing_expectations: list[TimingExpectation]
    ordering_expectations: list[OrderingExpectation]
    dyn_instr_expectations: list[DynInstrExpectation]
    repl_trace_expectations: list[ReplTraceExpectation]


# ---------------------------------------------------------------------------
# build_skill_arch_test_lineage() — with conflict resolutions applied
# ---------------------------------------------------------------------------


def build_skill_arch_test_lineage() -> ExpectedLineage:
    """Build the ExpectedLineage for the expanded skill_arch_test fixture.

    15-call fixture: 4 tools x 3 depths (list_skills, load_skill, execute_code,
    set_model_response at d0/d1/d2), plus llm_query_batched with 2 prompts.

    Anti-reward-hacking: every assertion depends on real pipeline execution.
    Removed: repl_did_expand (dead signal), should_stop at model_call_1 (default check).
    Strengthened: execution_mode uses eq not oneof, worker_thread_name added.
    """
    state_keys = [
        # --- iteration_count=0 at first model call (before any tool runs) ---
        StateKeyExpectation(
            phase="model_call_1",
            key="iteration_count",
            operator="eq",
            expected="0",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py — initial state yields iteration_count=0",
        ),
        # NOTE: Removed should_stop at model_call_1 (was reward-hackable: dict.get default)
        # NOTE: Removed repl_did_expand (dead signal: source expansion path deleted)
    ]

    test_skill = [
        # --- Depth verification (STRONG: _rlm_depth from REPLTool state injection) ---
        TestSkillExpectation(
            key="depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — _rlm_depth injected into _rlm_state; proves REPLTool ran at d=0",
        ),
        # --- Agent name (STRONG: from tool_context.agent_name) ---
        TestSkillExpectation(
            key="rlm_agent_name",
            operator="eq",
            expected="reasoning_agent",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — _rlm_agent_name from tool context",
        ),
        # --- iteration_count=1 inside TEST_SKILL (STRONG: REPLTool incremented) ---
        TestSkillExpectation(
            key="iteration_count",
            operator="eq",
            expected="1",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — REPLTool increments _call_count to 1 before first execute_code",
        ),
        # --- current_depth=0 (STRONG: from depth-scoped state) ---
        TestSkillExpectation(
            key="current_depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — current_depth from EXPOSED_STATE_KEYS snapshot",
        ),
        # --- should_stop inside skill: '?' because it's None before any tool completes ---
        TestSkillExpectation(
            key="should_stop",
            operator="eq",
            expected="?",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — should_stop in EXPOSED_STATE_KEYS but None; skill defaults to '?'",
        ),
        # --- state_keys_count (STRONG: proves _rlm_state was built) ---
        TestSkillExpectation(
            key="state_keys_count",
            operator="gte",
            expected=6,
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — _rlm_state from EXPOSED_STATE_KEYS + 3 lineage metadata keys",
        ),
        # --- llm_query_fn_type (STRONG: proves loader wrapper injected the closure) ---
        TestSkillExpectation(
            key="llm_query_fn_type",
            operator="eq",
            expected="function",
            source_file="rlm_adk/dispatch.py",
            source_hint="dispatch.py — llm_query injected as closure; type() is 'function'",
        ),
        # --- execution_mode STRICT eq (fixed from oneof, now runtime-detected) ---
        TestSkillExpectation(
            key="execution_mode",
            operator="eq",
            expected="thread_bridge",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py — runtime detection: thread_bridge if not MainThread",
        ),
        # --- worker_thread_name (NEW, STRONG: proves REPL runs in worker thread) ---
        TestSkillExpectation(
            key="worker_thread_name",
            operator="not_contains",
            expected="MainThread",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py — threading.current_thread().name; must NOT be MainThread",
        ),
        # --- calling_llm_query (STRONG: emitted before llm_query() call) ---
        TestSkillExpectation(
            key="calling_llm_query",
            operator="eq",
            expected="True",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py — emitted immediately before llm_query_fn() call",
        ),
        # --- child_result_preview (STRONG: requires full depth=2 chain) ---
        TestSkillExpectation(
            key="child_result_preview",
            operator="contains",
            expected="child_confirmed_depth2",
            source_file="rlm_adk/dispatch.py",
            source_hint="dispatch.py — child at d1 returns 'child_confirmed_depth2: depth2_leaf_ok' via depth=2 chain",
        ),
        # --- thread_bridge_latency_ms (STRONG: measured via perf_counter) ---
        TestSkillExpectation(
            key="thread_bridge_latency_ms",
            operator="gt",
            expected=0.0,
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py — latency measured via time.perf_counter() around llm_query()",
        ),
        # --- COMPLETE (STRONG: only emitted if run_test_skill returns without error) ---
        TestSkillExpectation(
            key="COMPLETE",
            operator="eq",
            expected="True",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py — only emitted if the entire function ran without exception",
        ),
    ]

    plugin_hooks = [
        PluginHookExpectation(
            hook="before_agent",
            agent_name="reasoning_agent",
            key="depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/agent.py",
            source_hint="agent.py — _rlm_depth=0 on root reasoning_agent",
        ),
        PluginHookExpectation(
            hook="before_model",
            agent_name="reasoning_agent",
            key="call_num",
            operator="gte",
            expected=1,
            source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
            source_hint="InstrumentationPlugin.before_model_callback — monotonic counter",
        ),
        PluginHookExpectation(
            hook="before_model",
            agent_name="reasoning_agent",
            key="sys_instr_len",
            operator="gt",
            expected=0,
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py — RLM_STATIC_INSTRUCTION + resolved RLM_DYNAMIC_INSTRUCTION",
        ),
        # --- execute_code tool (STRONG: before_tool fires for real tool invocations) ---
        PluginHookExpectation(
            hook="before_tool",
            agent_name="reasoning_agent",
            key="tool_name",
            operator="eq",
            expected="execute_code",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — REPLTool.name == 'execute_code'",
        ),
        # --- set_model_response tool at root (NEW: proves upward flow at d0) ---
        PluginHookExpectation(
            hook="before_tool",
            agent_name="reasoning_agent",
            key="tool_name",
            operator="eq",
            expected="set_model_response",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="ADK SetModelResponseTool fires before_tool for root reasoning_agent",
        ),
        PluginHookExpectation(
            hook="after_model",
            agent_name="reasoning_agent",
            key="finish_reason",
            operator="eq",
            expected="STOP",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py — reasoning_agent finishes with STOP",
        ),
    ]

    timings = [
        TimingExpectation(
            label="agent_reasoning_agent_ms",
            operator="gte",
            expected_ms=0.0,
            source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
            source_hint="InstrumentationPlugin.after_agent_callback — emits [TIMING:agent_<name>_ms=<elapsed>]",
        ),
        TimingExpectation(
            label="model_call_1_ms",
            operator="gte",
            expected_ms=0.0,
            source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
            source_hint="InstrumentationPlugin.after_model_callback — emits [TIMING:model_call_<N>_ms=<elapsed>]",
        ),
    ]

    orderings = [
        OrderingExpectation(
            first_hook="before_agent",
            first_agent="reasoning_agent",
            second_hook="before_model",
            second_agent="reasoning_agent",
            description="before_agent must fire before before_model (agent lifecycle order)",
        ),
        OrderingExpectation(
            first_hook="before_model",
            first_agent="reasoning_agent",
            second_hook="before_tool",
            second_agent="reasoning_agent",
            description="before_model must fire before before_tool (model decides to call tool)",
        ),
        OrderingExpectation(
            first_hook="before_tool",
            first_agent="reasoning_agent",
            second_hook="after_tool",
            second_agent="reasoning_agent",
            description="before_tool must fire before after_tool (tool bracket pair is closed)",
        ),
    ]

    dyn_instr = [
        DynInstrExpectation(
            key="repo_url",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py — '{repo_url?}' resolved from session state key 'repo_url'",
        ),
        DynInstrExpectation(
            key="root_prompt",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py — '{root_prompt?}' resolved from 'root_prompt' in session state",
        ),
        DynInstrExpectation(
            key="test_context",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py — '{test_context?}' resolved from raw key 'test_context'",
        ),
        DynInstrExpectation(
            key="skill_instruction",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py — '{skill_instruction?}' resolved from DYN_SKILL_INSTRUCTION",
        ),
        DynInstrExpectation(
            key="user_ctx_manifest",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py Path B — builds user_ctx_manifest from user_provided_ctx dict",
        ),
        DynInstrExpectation(
            key="user_ctx_keys",
            operator="contains",
            expected="arch_context.txt",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py Path B — pre-loads repl.globals['user_ctx']",
        ),
    ]

    repl_trace = [
        ReplTraceExpectation(
            key="execution_mode",
            operator="eq",
            expected="thread_bridge",
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py — REPLTrace.execution_mode field",
            required=False,
        ),
        ReplTraceExpectation(
            key="wall_time_ms",
            operator="gt",
            expected=0.0,
            source_file="rlm_adk/repl/ipython_executor.py",
            source_hint="ipython_executor.py — pre_run_cell/post_run_cell timing callbacks",
            required=False,
        ),
        ReplTraceExpectation(
            key="llm_call_count",
            operator="gte",
            expected=1,
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py — REPLTrace.record_llm_start() called by dispatch.py",
            required=False,
        ),
        ReplTraceExpectation(
            key="submitted_code_chars",
            operator="gt",
            expected=0,
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — trace.submitted_code_chars = len(expanded_code)",
            required=False,
        ),
    ]

    return ExpectedLineage(
        state_key_expectations=state_keys,
        test_skill_expectations=test_skill,
        plugin_hook_expectations=plugin_hooks,
        timing_expectations=timings,
        ordering_expectations=orderings,
        dyn_instr_expectations=dyn_instr,
        repl_trace_expectations=repl_trace,
    )


# ---------------------------------------------------------------------------
# Assertion infrastructure
# ---------------------------------------------------------------------------

_MISSING = "<MISSING>"


@dataclasses.dataclass
class AssertionFailure:
    """One failed assertion with full diagnostic context."""
    group: str
    phase: str
    key: str
    expected: Any
    actual: Any
    operator: str
    source_file: str
    source_hint: str
    fix_hint: str

    def format(self) -> str:
        lines = [
            f"  FAIL [{self.group}] phase={self.phase!r} key={self.key!r}",
            f"    operator : {self.operator}",
            f"    expected : {self.expected!r}",
            f"    actual   : {self.actual!r}",
            f"    source   : {self.source_file}",
            f"    detail   : {self.source_hint}",
            f"    fix hint : {self.fix_hint}",
        ]
        return "\n".join(lines)


@dataclasses.dataclass
class AssertionReport:
    """Aggregated result of all assertion groups."""
    failures: list[AssertionFailure]
    groups_checked: list[str]
    log: ParsedLog

    @property
    def passed(self) -> bool:
        return len(self.failures) == 0

    def failures_in_group(self, group: str) -> list[AssertionFailure]:
        return [f for f in self.failures if f.group == group]

    def format_report(self) -> str:
        if self.passed:
            return f"PASS: all {len(self.groups_checked)} assertion groups passed."

        lines = [
            f"FAIL: {len(self.failures)} assertion(s) failed across {len(self.groups_checked)} group(s).",
            f"Groups checked: {', '.join(self.groups_checked)}",
            "",
        ]

        by_group: dict[str, list[AssertionFailure]] = {}
        for f in self.failures:
            by_group.setdefault(f.group, []).append(f)

        for group_name, group_failures in by_group.items():
            lines.append(f"--- Group: {group_name} ({len(group_failures)} failure(s)) ---")
            for f in group_failures:
                lines.append(f.format())
            lines.append("")

        if self.log.malformed_lines:
            lines.append(f"--- Malformed tagged lines ({len(self.log.malformed_lines)}) ---")
            for ml in self.log.malformed_lines[:10]:
                lines.append(f"  {ml}")
            if len(self.log.malformed_lines) > 10:
                lines.append(f"  ... and {len(self.log.malformed_lines) - 10} more")

        return "\n".join(lines)

    def raise_if_failed(self) -> None:
        if not self.passed:
            raise AssertionError(self.format_report())


# ---------------------------------------------------------------------------
# Operator evaluation
# ---------------------------------------------------------------------------


def _eval_operator(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "eq":
        return str(actual) == str(expected)
    elif operator == "contains":
        return isinstance(actual, str) and str(expected) in actual
    elif operator == "not_contains":
        return isinstance(actual, str) and str(expected) not in actual
    elif operator == "gt":
        try:
            return float(actual) > float(expected)
        except (ValueError, TypeError):
            return False
    elif operator == "gte":
        try:
            return float(actual) >= float(expected)
        except (ValueError, TypeError):
            return False
    elif operator == "lt":
        try:
            return float(actual) < float(expected)
        except (ValueError, TypeError):
            return False
    elif operator == "not_none":
        return actual is not None and actual != _MISSING
    elif operator == "oneof":
        return str(actual) in [str(v) for v in expected]
    elif operator == "in":
        return str(expected) in str(actual)
    elif operator == "type":
        type_map = {"list": list, "dict": dict, "str": str, "int": int, "float": float, "bool": bool}
        return isinstance(actual, type_map.get(str(expected), object))
    return False


def _build_fix_hint(
    group: str, key: str, operator: str, expected: Any, actual: Any, source_hint: str,
) -> str:
    if operator == "eq":
        return f"Key {key!r} in group {group!r}: got {actual!r}, expected {expected!r}. Check: {source_hint}"
    elif operator in ("gt", "gte"):
        return (
            f"Key {key!r} in group {group!r}: got {actual} which fails {operator} {expected}. "
            f"If actual is 0 or negative, the pipeline step that writes this value did not run. "
            f"Check: {source_hint}"
        )
    elif operator == "contains":
        return f"Key {key!r} in group {group!r}: expected substring {expected!r} not found in {actual!r}. Check: {source_hint}"
    elif operator == "oneof":
        return f"Key {key!r} in group {group!r}: got {actual!r}, expected one of {expected!r}. Check: {source_hint}"
    else:
        return f"Key {key!r} in group {group!r}: constraint {operator}({expected!r}) failed with actual={actual!r}. Check: {source_hint}"


# ---------------------------------------------------------------------------
# Assertion group functions
# ---------------------------------------------------------------------------


def _make_missing_fix_hint(group: str, key: str, source_file: str) -> str:
    return (
        f"[{group}:{key}=...] absent from log. "
        f"Check that the pipeline step that writes this value ran correctly. "
        f"Source: {source_file}"
    )


def assert_test_skill_tags(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []
    for exp in lineage.test_skill_expectations:
        raw = log.test_skill.get(exp.key, _MISSING)

        if raw == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="test_skill", phase="repl_stdout", key=exp.key,
                    expected=exp.expected, actual=_MISSING, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=_make_missing_fix_hint("TEST_SKILL", exp.key, exp.source_file),
                ))
            continue

        actual: Any = raw
        if exp.operator in ("gt", "gte", "lt"):
            try:
                actual = float(raw)
            except ValueError:
                failures.append(AssertionFailure(
                    group="test_skill", phase="repl_stdout", key=exp.key,
                    expected=exp.expected, actual=raw, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=f"Value for {exp.key!r} is not numeric: {raw!r}. Check {exp.source_file}",
                ))
                continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="test_skill", phase="repl_stdout", key=exp.key,
                expected=exp.expected, actual=actual, operator=exp.operator,
                source_file=exp.source_file, source_hint=exp.source_hint,
                fix_hint=_build_fix_hint("test_skill", exp.key, exp.operator, exp.expected, actual, exp.source_hint),
            ))
    return failures


def assert_plugin_hooks(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []
    for exp in lineage.plugin_hook_expectations:
        if exp.agent_name == "*":
            entries = [e for e in log.plugin_entries if e.hook == exp.hook]
        else:
            entries = [e for e in log.plugin_entries if e.hook == exp.hook and e.agent_name == exp.agent_name]

        matching = [e for e in entries if e.key == exp.key]

        if not matching:
            if exp.required:
                failures.append(AssertionFailure(
                    group="plugin_hook", phase=f"{exp.hook}:{exp.agent_name}", key=exp.key,
                    expected=exp.expected, actual=_MISSING, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=_make_missing_fix_hint(f"PLUGIN:{exp.hook}:{exp.agent_name}", exp.key, exp.source_file),
                ))
            continue

        # Check if ANY matching entry satisfies the operator (not just the first).
        # This handles cases where the same hook fires multiple times with different values
        # (e.g., before_tool fires for both execute_code and set_model_response).
        any_passed = False
        last_actual: Any = _MISSING
        for entry in matching:
            actual: Any = entry.value
            if exp.operator in ("gt", "gte", "lt"):
                try:
                    actual = float(entry.value)
                except ValueError:
                    pass
            last_actual = actual
            if _eval_operator(exp.operator, actual, exp.expected):
                any_passed = True
                break

        if not any_passed:
            failures.append(AssertionFailure(
                group="plugin_hook", phase=f"{exp.hook}:{exp.agent_name}", key=exp.key,
                expected=exp.expected, actual=last_actual, operator=exp.operator,
                source_file=exp.source_file, source_hint=exp.source_hint,
                fix_hint=_build_fix_hint(f"plugin:{exp.hook}:{exp.agent_name}", exp.key, exp.operator, exp.expected, last_actual, exp.source_hint),
            ))
    return failures


def assert_state_keys(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []
    for exp in lineage.state_key_expectations:
        scope_entries = log.state_at_scope(exp.phase)
        actual = scope_entries.get(exp.key, _MISSING)

        if actual == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="state_key", phase=exp.phase, key=exp.key,
                    expected=exp.expected, actual=_MISSING, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=_make_missing_fix_hint(f"STATE:{exp.phase}", exp.key, exp.source_file),
                ))
            continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="state_key", phase=exp.phase, key=exp.key,
                expected=exp.expected, actual=actual, operator=exp.operator,
                source_file=exp.source_file, source_hint=exp.source_hint,
                fix_hint=_build_fix_hint(f"state:{exp.phase}", exp.key, exp.operator, exp.expected, actual, exp.source_hint),
            ))
    return failures


def assert_timings(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []
    for exp in lineage.timing_expectations:
        actual_ms = log.timing_for(exp.label)
        if actual_ms is None:
            failures.append(AssertionFailure(
                group="timing", phase="instrumentation", key=exp.label,
                expected=f"{exp.operator} {exp.expected_ms}ms", actual=_MISSING,
                operator=exp.operator, source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=_make_missing_fix_hint("TIMING", exp.label, exp.source_file),
            ))
            continue

        if not _eval_operator(exp.operator, actual_ms, exp.expected_ms):
            failures.append(AssertionFailure(
                group="timing", phase="instrumentation", key=exp.label,
                expected=f"{exp.operator} {exp.expected_ms}ms", actual=actual_ms,
                operator=exp.operator, source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=f"Timing {exp.label!r} = {actual_ms}ms failed {exp.operator} {exp.expected_ms}ms. Check {exp.source_file}",
            ))
    return failures


def assert_orderings(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []

    for exp in lineage.ordering_expectations:
        first_lineno: int | None = None
        for e in log.plugin_entries:
            if e.hook == exp.first_hook and e.agent_name == exp.first_agent:
                first_lineno = e.line_number
                break

        second_lineno: int | None = None
        for e in log.plugin_entries:
            if e.hook == exp.second_hook and e.agent_name == exp.second_agent:
                second_lineno = e.line_number
                break

        if first_lineno is None:
            failures.append(AssertionFailure(
                group="ordering", phase="log_sequence",
                key=f"{exp.first_hook}:{exp.first_agent}",
                expected=f"appears before {exp.second_hook}:{exp.second_agent}",
                actual=_MISSING, operator="before",
                source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
                source_hint=exp.description,
                fix_hint=f"Hook {exp.first_hook!r} for agent {exp.first_agent!r} never appeared.",
            ))
        elif second_lineno is None:
            failures.append(AssertionFailure(
                group="ordering", phase="log_sequence",
                key=f"{exp.second_hook}:{exp.second_agent}",
                expected=f"appears after {exp.first_hook}:{exp.first_agent}",
                actual=_MISSING, operator="before",
                source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
                source_hint=exp.description,
                fix_hint=f"Hook {exp.second_hook!r} for agent {exp.second_agent!r} never appeared.",
            ))
        elif first_lineno >= second_lineno:
            failures.append(AssertionFailure(
                group="ordering", phase="log_sequence",
                key=f"{exp.first_hook}:{exp.first_agent} before {exp.second_hook}:{exp.second_agent}",
                expected=f"line({exp.first_hook}) < line({exp.second_hook})",
                actual=f"line({exp.first_hook})={first_lineno} >= line({exp.second_hook})={second_lineno}",
                operator="before",
                source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
                source_hint=exp.description,
                fix_hint=f"Ordering violation: {exp.description}. Check InstrumentationPlugin callback chain.",
            ))
    return failures


def assert_dyn_instr(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []
    for exp in lineage.dyn_instr_expectations:
        actual = log.dyn_instr.get(exp.key, _MISSING)

        if actual == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="dyn_instr", phase="systemInstruction_capture", key=exp.key,
                    expected=exp.expected, actual=_MISSING, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=_make_missing_fix_hint("DYN_INSTR", exp.key, exp.source_file),
                ))
            continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="dyn_instr", phase="systemInstruction_capture", key=exp.key,
                expected=exp.expected, actual=actual, operator=exp.operator,
                source_file=exp.source_file, source_hint=exp.source_hint,
                fix_hint=_build_fix_hint("dyn_instr", exp.key, exp.operator, exp.expected, actual, exp.source_hint),
            ))
    return failures


def assert_repl_trace(log: ParsedLog, lineage: ExpectedLineage) -> list[AssertionFailure]:
    failures: list[AssertionFailure] = []
    trace = log.repl_trace()

    for exp in lineage.repl_trace_expectations:
        raw = trace.get(exp.key, _MISSING)

        if raw == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="repl_trace", phase="repl_trace_plugin", key=exp.key,
                    expected=exp.expected, actual=_MISSING, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=_make_missing_fix_hint("REPL_TRACE", exp.key, exp.source_file),
                ))
            continue

        actual: Any = raw
        if exp.operator in ("gt", "gte", "lt"):
            try:
                actual = float(raw)
            except ValueError:
                failures.append(AssertionFailure(
                    group="repl_trace", phase="repl_trace_plugin", key=exp.key,
                    expected=exp.expected, actual=raw, operator=exp.operator,
                    source_file=exp.source_file, source_hint=exp.source_hint,
                    fix_hint=f"REPL_TRACE key {exp.key!r} is not numeric: {raw!r}. Check {exp.source_file}",
                ))
                continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="repl_trace", phase="repl_trace_plugin", key=exp.key,
                expected=exp.expected, actual=actual, operator=exp.operator,
                source_file=exp.source_file, source_hint=exp.source_hint,
                fix_hint=_build_fix_hint("repl_trace", exp.key, exp.operator, exp.expected, actual, exp.source_hint),
            ))
    return failures


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def run_all_assertions(
    log: ParsedLog,
    lineage: ExpectedLineage,
    *,
    groups: list[str] | None = None,
) -> AssertionReport:
    """Run all assertion groups and collect every failure before returning."""
    all_failures: list[AssertionFailure] = []
    checked: list[str] = []

    _ALL_GROUPS = [
        "test_skill", "plugin_hook", "state_key", "timing",
        "ordering", "dyn_instr", "repl_trace",
    ]
    active = groups if groups is not None else _ALL_GROUPS

    if "test_skill" in active:
        all_failures.extend(assert_test_skill_tags(log, lineage))
        checked.append("test_skill")

    if "plugin_hook" in active:
        all_failures.extend(assert_plugin_hooks(log, lineage))
        checked.append("plugin_hook")

    if "state_key" in active:
        all_failures.extend(assert_state_keys(log, lineage))
        checked.append("state_key")

    if "timing" in active:
        all_failures.extend(assert_timings(log, lineage))
        checked.append("timing")

    if "ordering" in active:
        all_failures.extend(assert_orderings(log, lineage))
        checked.append("ordering")

    if "dyn_instr" in active:
        all_failures.extend(assert_dyn_instr(log, lineage))
        checked.append("dyn_instr")

    if "repl_trace" in active:
        all_failures.extend(assert_repl_trace(log, lineage))
        checked.append("repl_trace")

    return AssertionReport(failures=all_failures, groups_checked=checked, log=log)
