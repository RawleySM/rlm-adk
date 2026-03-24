# Assertion Framework Design — Stdout Parsing and Graceful Error Reporting

**Author**: Reward-Anti-Hacker Agent
**Date**: 2026-03-24
**Status**: Design Plan (not yet implemented)

---

## Overview

This document designs a `StdoutParser`, `ParsedLog`, `ExpectedLineage`, and a suite of assertion functions that validate the **real** pipeline output produced by `InstrumentationPlugin` + `test_skill.py` + the dynamic instruction capture hook. Every assertion checks an observable side-effect of the pipeline, never a pre-seeded value. Failure messages include file, class, state key, expected vs actual, callback phase, and a "fix hint" pointing to the exact source location that writes the value being tested.

The framework integrates cleanly with pytest via a helper that collects all failures before raising, so the full diagnostic picture is visible in a single test run rather than halting at the first mismatch.

---

## 1. Complete Tag Format Specification

All tagged lines share the grammar:

```
[<FAMILY>:<fields>]
```

where `<fields>` is one or more `key=value` segments separated by `:` (for multi-segment families) or just `key=value` (for single-segment families). Values are terminated by `]` and may contain any characters except `]`.

### Family table

| Family | Producer | Grammar | Example |
|--------|----------|---------|---------|
| `TEST_SKILL` | `run_test_skill()` in `test_skill.py` | `[TEST_SKILL:key=value]` | `[TEST_SKILL:depth=0]` |
| `PLUGIN` | `InstrumentationPlugin` | `[PLUGIN:hook:agent_name:key=value]` | `[PLUGIN:before_model:reasoning_agent:call_num=1]` |
| `CALLBACK` | Local agent callbacks | `[CALLBACK:hook:agent_name:key=value]` | `[CALLBACK:before_tool:reasoning_agent:tool_name=execute_code]` |
| `STATE` | `InstrumentationPlugin._emit_state()` | `[STATE:scope:key=value]` | `[STATE:model_call_1:iteration_count=1]` |
| `TIMING` | `InstrumentationPlugin` | `[TIMING:label=ms]` | `[TIMING:model_call_1_ms=12.4]` |
| `DYN_INSTR` | `make_dyn_instr_capture_hook()` + REPL code | `[DYN_INSTR:key=value]` | `[DYN_INSTR:repo_url=resolved=True]` |
| `REPL_TRACE` | `REPLTracingPlugin` end-of-run artifact | `[REPL_TRACE:key=value]` | `[REPL_TRACE:execution_mode=async_rewrite]` |

### `TEST_SKILL` keys (canonical list)

All emitted by `run_test_skill()` in order:

```
depth                        — _rlm_state["_rlm_depth"]
rlm_agent_name               — _rlm_state["_rlm_agent_name"]
iteration_count              — _rlm_state["iteration_count"]
current_depth                — _rlm_state["current_depth"]
should_stop                  — _rlm_state["should_stop"]
state_keys_count             — len(state_snapshot)
state_keys                   — sorted list of all state_snapshot keys
repl_globals_count           — len(non-dunder globals)
llm_query_type               — type(llm_query).__name__ or "missing"
execution_mode               — "async_rewrite" | "thread_bridge" | "unknown"
has_repl_exec_in_globals     — bool: "_repl_exec" in globals()
calling_llm_query            — always True (emitted immediately before call)
child_result_preview         — first 120 chars of llm_query() return value
thread_bridge_latency_ms     — float ms for llm_query() round-trip
COMPLETE                     — always True (emitted after successful return)
summary                      — human-readable one-liner with depth/mode/latency/child_ok
```

### `PLUGIN` hooks (canonical list)

Emitted by `InstrumentationPlugin` for every agent in the invocation tree:

```
before_agent     — depth, fanout_idx, agent_type
after_agent      — depth, elapsed_ms
before_model     — call_num, model, depth, sys_instr_len, contents_count, tools_count
after_model      — call_num, finish_reason, func_calls, input_tokens, output_tokens, elapsed_ms
before_tool      — tool_name, depth, iteration_count, code_preview
after_tool       — tool_name, elapsed_ms, result_preview
```

### `STATE` scopes (canonical list)

```
model_call_<N>      — snapshot at before_model (iteration_count, should_stop, repl_did_expand)
before_agent:<key>  — curated state keys at before_agent (prefixed by "before_agent:")
after_agent:<key>   — curated state keys at after_agent (prefixed by "after_agent:")
pre_tool:<key>      — curated state keys before execute_code (prefixed by "pre_tool:")
```

### `DYN_INSTR` keys (canonical list)

```
user_ctx_keys             — sorted list of keys in user_ctx global (from REPL code)
arch_context_preview      — first 40 chars of user_ctx["arch_context.txt"]
repo_url=resolved=True    — bool: "{repo_url?}" absent from systemInstruction
root_prompt=resolved=...  — bool: "{root_prompt?}" absent
test_context=resolved=... — bool: "{test_context?}" absent
skill_instruction=resolved=... — bool: "{skill_instruction?}" absent
user_ctx_manifest=resolved=... — bool: "{user_ctx_manifest?}" absent
<key>_preview=<val>       — first 60 chars of state value for each resolved key
```

### `REPL_TRACE` keys (canonical list — produced by `REPLTracingPlugin` when `RLM_REPL_TRACE=2`)

These lines are emitted by `REPLTracingPlugin.after_run()` at end-of-run by serializing each `REPLTrace.to_dict()` entry as tagged lines. They appear in `instrumentation_log` or `repl_stdout`, not in the per-REPL block's stdout.

```
execution_mode            — "async_rewrite" | "thread_bridge" | "sync" (from REPLTrace.execution_mode)
wall_time_ms              — float: total execution time for the code block
llm_call_count            — int: number of llm_query() calls made (from len(REPLTrace.llm_calls))
peak_memory_bytes         — int: tracemalloc peak; > 0 only at trace_level=2 (RLM_REPL_TRACE=2)
data_flow_edges           — int: count of edges detected by DataFlowTracker (0 if no chained queries)
submitted_code_chars      — int: length of submitted code string
var_snapshots_count       — int: number of var snapshots taken (0 at trace_level < 1)
```

---

## 2. `StdoutParser` Class

```python
"""stdout_parser.py — parse tagged diagnostic lines from instrumented pipeline runs.

Location: tests_rlm_adk/provider_fake/stdout_parser.py
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any


# ---------------------------------------------------------------------------
# Regex patterns for each tag family
# ---------------------------------------------------------------------------

# [TEST_SKILL:key=value]
_TEST_SKILL_RE = re.compile(r"\[TEST_SKILL:([^=\]]+)=([^\]]*)\]")

# [PLUGIN:hook:agent_name:key=value]
_PLUGIN_RE = re.compile(r"\[PLUGIN:([^:]+):([^:]+):([^=\]]+)=([^\]]*)\]")

# [CALLBACK:hook:agent_name:key=value]
_CALLBACK_RE = re.compile(r"\[CALLBACK:([^:]+):([^:]+):([^=\]]+)=([^\]]*)\]")

# [STATE:scope:key=value]  (scope may contain colons like "before_agent:")
# We capture everything between [STATE: and the first = as "scope:key",
# then split on the LAST colon before = to separate scope from key.
_STATE_RE = re.compile(r"\[STATE:([^=\]]+)=([^\]]*)\]")

# [TIMING:label=ms]  — label may contain underscores and digits
_TIMING_RE = re.compile(r"\[TIMING:([^=\]]+)=([^\]]*)\]")

# [DYN_INSTR:key=value]
_DYN_INSTR_RE = re.compile(r"\[DYN_INSTR:([^=\]]+)=([^\]]*)\]")

# [REPL_TRACE:key=value]
_REPL_TRACE_RE = re.compile(r"\[REPL_TRACE:([^=\]]+)=([^\]]*)\]")

# Known tag prefixes — used for malformed-line detection
_ALL_TAG_PREFIXES = re.compile(
    r"\[(TEST_SKILL|PLUGIN|CALLBACK|STATE|TIMING|DYN_INSTR|REPL_TRACE):"
)


@dataclasses.dataclass
class ReplTraceEntry:
    """One [REPL_TRACE:key=value] record from REPLTracingPlugin."""
    key: str
    value: str
    line_number: int


@dataclasses.dataclass
class PluginEntry:
    """One [PLUGIN:hook:agent:key=value] record."""
    hook: str
    agent_name: str
    key: str
    value: str
    line_number: int


@dataclasses.dataclass
class CallbackEntry:
    """One [CALLBACK:hook:agent:key=value] record."""
    hook: str
    agent_name: str
    key: str
    value: str
    line_number: int


@dataclasses.dataclass
class StateEntry:
    """One [STATE:scope:key=value] record."""
    scope: str       # e.g. "model_call_1", "before_agent", "pre_tool"
    key: str         # e.g. "iteration_count"
    value: str
    line_number: int


@dataclasses.dataclass
class TimingEntry:
    """One [TIMING:label=ms] record."""
    label: str
    value_ms: float   # parsed float; -1.0 if unparseable
    raw: str
    line_number: int


@dataclasses.dataclass
class ParsedLog:
    """Typed container for all tagged lines extracted from a stdout string.

    Attributes:
        test_skill: dict[key, last_value] from [TEST_SKILL:...] lines.
            When a key appears multiple times (e.g. state_keys on retry), the
            last value wins. Access via test_skill["depth"].
        plugin_entries: All [PLUGIN:...] records in emission order.
        callback_entries: All [CALLBACK:...] records in emission order.
        state_entries: All [STATE:...] records in emission order.
        timing_entries: All [TIMING:...] records in emission order.
        dyn_instr: dict[key, value] from [DYN_INSTR:...] lines.
        malformed_lines: Lines that matched the [TAG:...] pattern but
            could not be parsed. Stored for debugging, never crash.
        raw_stdout: The original stdout string.
    """
    test_skill: dict[str, str]
    plugin_entries: list[PluginEntry]
    callback_entries: list[CallbackEntry]
    state_entries: list[StateEntry]
    timing_entries: list[TimingEntry]
    dyn_instr: dict[str, str]
    repl_trace_entries: list[ReplTraceEntry]
    malformed_lines: list[str]
    raw_stdout: str

    # -----------------------------------------------------------------------
    # Convenience accessors
    # -----------------------------------------------------------------------

    def plugin_hooks(self, hook: str) -> list[PluginEntry]:
        """Return all plugin entries for a given hook name."""
        return [e for e in self.plugin_entries if e.hook == hook]

    def plugin_for_agent(self, hook: str, agent_name: str) -> list[PluginEntry]:
        """Return plugin entries for a specific hook + agent combination."""
        return [e for e in self.plugin_entries
                if e.hook == hook and e.agent_name == agent_name]

    def state_at_scope(self, scope: str) -> dict[str, str]:
        """Return last-seen value for each key within a given scope."""
        result: dict[str, str] = {}
        for e in self.state_entries:
            if e.scope == scope:
                result[e.key] = e.value
        return result

    def timing_for(self, label: str) -> float | None:
        """Return the last timing value for a label, or None if absent."""
        for e in reversed(self.timing_entries):
            if e.label == label:
                return e.value_ms
        return None

    def agent_names_seen(self) -> set[str]:
        """Set of all agent names that appear in plugin entries."""
        return {e.agent_name for e in self.plugin_entries}

    def repl_trace(self) -> dict[str, str]:
        """Return last-seen value for each REPL_TRACE key (dict form of trace summary)."""
        result: dict[str, str] = {}
        for e in self.repl_trace_entries:
            result[e.key] = e.value
        return result

    def repl_trace_float(self, key: str) -> float | None:
        """Return a REPL_TRACE value as float, or None if missing/unparseable."""
        raw = self.repl_trace().get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def test_skill_float(self, key: str) -> float | None:
        """Return a TEST_SKILL value as float, or None if missing/unparseable."""
        raw = self.test_skill.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def test_skill_bool(self, key: str) -> bool | None:
        """Return a TEST_SKILL value as bool, or None if missing."""
        raw = self.test_skill.get(key)
        if raw is None:
            return None
        return raw.lower() in ("true", "1", "yes")


def parse_stdout(raw_stdout: str) -> ParsedLog:
    """Parse all tagged diagnostic lines from a stdout string.

    Handles malformed lines gracefully: any line that partially matches a
    known tag family but cannot be fully parsed is added to malformed_lines
    rather than raising. Unknown tag families are silently ignored.

    Args:
        raw_stdout: The complete stdout string captured from an instrumented
            fixture run.

    Returns:
        ParsedLog with typed access to each tag family.
    """
    test_skill: dict[str, str] = {}
    plugin_entries: list[PluginEntry] = []
    callback_entries: list[CallbackEntry] = []
    state_entries: list[StateEntry] = []
    timing_entries: list[TimingEntry] = []
    dyn_instr: dict[str, str] = {}
    repl_trace_entries: list[ReplTraceEntry] = []
    malformed: list[str] = []

    for lineno, line in enumerate(raw_stdout.splitlines(), start=1):
        line = line.strip()
        if not line.startswith("["):
            continue

        # TEST_SKILL
        for m in _TEST_SKILL_RE.finditer(line):
            test_skill[m.group(1)] = m.group(2)

        # PLUGIN
        for m in _PLUGIN_RE.finditer(line):
            plugin_entries.append(PluginEntry(
                hook=m.group(1),
                agent_name=m.group(2),
                key=m.group(3),
                value=m.group(4),
                line_number=lineno,
            ))

        # CALLBACK
        for m in _CALLBACK_RE.finditer(line):
            callback_entries.append(CallbackEntry(
                hook=m.group(1),
                agent_name=m.group(2),
                key=m.group(3),
                value=m.group(4),
                line_number=lineno,
            ))

        # STATE — split "scope:key" on last colon
        for m in _STATE_RE.finditer(line):
            scope_key = m.group(1)  # e.g. "model_call_1:iteration_count"
            raw_value = m.group(2)
            # Split on last colon to separate scope from key
            if ":" in scope_key:
                scope, key = scope_key.rsplit(":", 1)
            else:
                scope, key = "", scope_key
            state_entries.append(StateEntry(
                scope=scope,
                key=key,
                value=raw_value,
                line_number=lineno,
            ))

        # TIMING
        for m in _TIMING_RE.finditer(line):
            try:
                ms = float(m.group(2))
            except ValueError:
                ms = -1.0
            timing_entries.append(TimingEntry(
                label=m.group(1),
                value_ms=ms,
                raw=m.group(2),
                line_number=lineno,
            ))

        # DYN_INSTR
        for m in _DYN_INSTR_RE.finditer(line):
            dyn_instr[m.group(1)] = m.group(2)

        # REPL_TRACE
        for m in _REPL_TRACE_RE.finditer(line):
            repl_trace_entries.append(ReplTraceEntry(
                key=m.group(1),
                value=m.group(2),
                line_number=lineno,
            ))

        # Detect partially-matching malformed lines (has known bracket prefix but didn't match)
        if _ALL_TAG_PREFIXES.search(line):
            matched = (
                bool(_TEST_SKILL_RE.search(line))
                or bool(_PLUGIN_RE.search(line))
                or bool(_CALLBACK_RE.search(line))
                or bool(_STATE_RE.search(line))
                or bool(_TIMING_RE.search(line))
                or bool(_DYN_INSTR_RE.search(line))
                or bool(_REPL_TRACE_RE.search(line))
            )
            if not matched:
                malformed.append(f"line {lineno}: {line}")

    return ParsedLog(
        test_skill=test_skill,
        plugin_entries=plugin_entries,
        callback_entries=callback_entries,
        state_entries=state_entries,
        timing_entries=timing_entries,
        dyn_instr=dyn_instr,
        repl_trace_entries=repl_trace_entries,
        malformed_lines=malformed,
        raw_stdout=raw_stdout,
    )
```

---

## 3. `ExpectedLineage` Dataclass

`ExpectedLineage` is a pure data container that specifies what the parsed log MUST contain. The assertion functions consume it to produce detailed failure reports.

```python
"""expected_lineage.py — expected pipeline state for skill_arch_test fixture.

Location: tests_rlm_adk/provider_fake/expected_lineage.py
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class StateKeyExpectation:
    """Expected value constraints for a single state key at a specific phase."""
    phase: str                  # e.g. "model_call_1", "pre_tool", "before_agent"
    key: str                    # state key name
    operator: str               # "eq", "contains", "gt", "gte", "not_none", "oneof", "type"
    expected: Any               # the expected value or operand
    source_file: str            # where this value is written in production code
    source_hint: str            # e.g. "rlm_adk/tools/repl_tool.py:220 — _rlm_state injection"
    required: bool = True       # if False, absence is allowed (key may not exist)


@dataclasses.dataclass
class TestSkillExpectation:
    """Expected value for a [TEST_SKILL:key=value] tag."""
    key: str
    operator: str               # "eq", "contains", "gt", "gte", "not_none", "oneof", "in"
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class PluginHookExpectation:
    """Expected plugin hook entry."""
    hook: str                   # "before_agent", "before_model", "after_tool", etc.
    agent_name: str             # agent name or "*" for any
    key: str                    # key within the hook's output
    operator: str
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class TimingExpectation:
    """Expected timing constraint."""
    label: str                  # timing label
    operator: str               # "gt", "gte", "lt"
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
    operator: str               # "eq", "contains", "not_contains"
    expected: Any
    source_file: str
    source_hint: str
    required: bool = True


@dataclasses.dataclass
class ReplTraceExpectation:
    """Expected [REPL_TRACE:key=value] assertion.

    Only meaningful when RLM_REPL_TRACE >= 1 (set by the instrumented runner).
    required=False by default: if the key is absent (trace disabled), the
    assertion is skipped rather than failing. If the key IS present but
    violates the operator constraint, it always fails.
    """
    key: str
    operator: str               # "eq", "gt", "gte", "not_none", "oneof"
    expected: Any
    source_file: str
    source_hint: str
    required: bool = False      # absent = skip, present-but-wrong = fail


@dataclasses.dataclass
class ExpectedLineage:
    """Complete expected lineage for the skill_arch_test fixture.

    Encodes the full set of assertions against the pipeline's real
    observable outputs. Each field is a list of expectations; the
    assertion functions iterate over them and collect all failures.
    """
    state_key_expectations: list[StateKeyExpectation]
    test_skill_expectations: list[TestSkillExpectation]
    plugin_hook_expectations: list[PluginHookExpectation]
    timing_expectations: list[TimingExpectation]
    ordering_expectations: list[OrderingExpectation]
    dyn_instr_expectations: list[DynInstrExpectation]
    repl_trace_expectations: list[ReplTraceExpectation]


def build_skill_arch_test_lineage() -> ExpectedLineage:
    """Build the ExpectedLineage for the skill_arch_test fixture.

    Every expectation references the exact file and line where the
    value is written in production code. This is the canonical list
    of what the assertion framework verifies.
    """
    state_keys = [
        # --- State at first model call (iteration_count must be 1) ---
        StateKeyExpectation(
            phase="model_call_1",
            key="iteration_count",
            operator="eq",
            expected="1",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py — iteration counter incremented before reasoning_agent.run_async()",
        ),
        StateKeyExpectation(
            phase="model_call_1",
            key="should_stop",
            operator="eq",
            expected="False",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py — should_stop initialized to False at start of run",
        ),
        StateKeyExpectation(
            phase="model_call_1",
            key="repl_did_expand",
            operator="eq",
            expected="False",  # before execute_code runs
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — repl_did_expand written by REPLTool after skill expansion; False at model call 1 (before tool runs)",
        ),
        # --- State at pre_tool (before execute_code runs) ---
        StateKeyExpectation(
            phase="pre_tool",
            key="iteration_count",
            operator="eq",
            expected="1",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — iteration_count flushed to tool_context.state by flush_fn() in dispatch.py",
        ),
        # --- State after tool (repl_did_expand must be True after expansion) ---
        StateKeyExpectation(
            phase="after_agent:repl_did_expand",  # captured in after_agent state dump
            key="repl_did_expand",
            operator="eq",
            expected="True",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — repl_did_expand written True by REPLTool.run_async() after SkillRegistry.expand() returns non-empty expansion",
            required=False,  # only present if skill expanded
        ),
    ]

    test_skill = [
        # --- Core state injection assertions ---
        TestSkillExpectation(
            key="depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py:220 — _rlm_depth injected into _rlm_state from REPLTool._rlm_depth constructor field",
        ),
        TestSkillExpectation(
            key="rlm_agent_name",
            operator="eq",
            expected="reasoning_agent",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — _rlm_agent_name injected from tool_context.agent_name into _rlm_state",
        ),
        TestSkillExpectation(
            key="iteration_count",
            operator="eq",
            expected="1",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — iteration_count pulled from EXPOSED_STATE_KEYS snapshot built in REPLTool.run_async()",
        ),
        TestSkillExpectation(
            key="current_depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — current_depth pulled from depth-scoped state key via depth_key(CURRENT_DEPTH, depth)",
        ),
        TestSkillExpectation(
            key="should_stop",
            operator="eq",
            expected="False",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — should_stop pulled from EXPOSED_STATE_KEYS; set True only by policy plugin or max_iterations reached",
        ),
        TestSkillExpectation(
            key="state_keys_count",
            operator="gte",
            expected=6,   # at minimum: _rlm_depth, _rlm_agent_name, _rlm_fanout_idx, iteration_count, current_depth, should_stop
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — _rlm_state built from EXPOSED_STATE_KEYS union {_rlm_depth, _rlm_agent_name, _rlm_fanout_idx}",
        ),
        # --- REPL globals assertions ---
        TestSkillExpectation(
            key="repl_globals_count",
            operator="gt",
            expected=5,   # at minimum: llm_query, llm_query_batched, _rlm_state, TestSkillResult, run_test_skill + builtins
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — REPL globals injected by REPLTool before execution: llm_query, llm_query_batched, _rlm_state, skill expansions",
        ),
        # --- llm_query type (must be a real callable, not missing or broken) ---
        TestSkillExpectation(
            key="llm_query_type",
            operator="eq",
            expected="function",
            source_file="rlm_adk/dispatch.py",
            source_hint="dispatch.py — llm_query injected as async-rewritten closure or thread-bridge sync callable; type() is always 'function'",
        ),
        # --- execution mode (either path is valid) ---
        TestSkillExpectation(
            key="execution_mode",
            operator="oneof",
            expected=["async_rewrite", "thread_bridge"],
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — execution_mode detected inside skill source: 'async_rewrite' if _repl_exec in globals, 'thread_bridge' otherwise",
        ),
        # --- child dispatch assertions ---
        TestSkillExpectation(
            key="calling_llm_query",
            operator="eq",
            expected="True",
            source_file="rlm_adk/skills/test_skill.py",
            source_hint="test_skill.py — [TEST_SKILL:calling_llm_query=True] emitted immediately before llm_query() call to confirm dispatch was attempted",
        ),
        TestSkillExpectation(
            key="child_result_preview",
            operator="contains",
            expected="arch_test_ok",
            source_file="rlm_adk/dispatch.py",
            source_hint="dispatch.py — child orchestrator at depth=1 must return 'arch_test_ok' via set_model_response; LLMResult str extraction in _read_child_completion()",
        ),
        TestSkillExpectation(
            key="thread_bridge_latency_ms",
            operator="gt",
            expected=0.0,
            source_file="rlm_adk/skills/test_skill.py",
            source_hint="test_skill.py — latency measured via time.perf_counter() around llm_query() call; must be > 0 for any real dispatch",
        ),
        # --- completion assertions ---
        TestSkillExpectation(
            key="COMPLETE",
            operator="eq",
            expected="True",
            source_file="rlm_adk/skills/test_skill.py",
            source_hint="test_skill.py — [TEST_SKILL:COMPLETE=True] only emitted if run_test_skill() returns without exception; absence means skill execution failed",
        ),
    ]

    plugin_hooks = [
        # --- before_agent must fire for root reasoning_agent ---
        PluginHookExpectation(
            hook="before_agent",
            agent_name="reasoning_agent",
            key="depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/agent.py",
            source_hint="agent.py — _rlm_depth=0 set on root reasoning_agent at construction; InstrumentationPlugin.before_agent_callback reads it via getattr(agent, '_rlm_depth', 0)",
        ),
        # --- before_model must fire at least once for reasoning_agent ---
        PluginHookExpectation(
            hook="before_model",
            agent_name="reasoning_agent",
            key="call_num",
            operator="gte",
            expected=1,
            source_file="proposals/thread_bridge_plan_B/instrumented_runner_design.md",
            source_hint="InstrumentationPlugin.before_model_callback — call_num is a monotonic counter; must reach at least 1 for reasoning agent",
        ),
        # --- sys_instr_len must be non-zero (dynamic instruction resolved) ---
        PluginHookExpectation(
            hook="before_model",
            agent_name="reasoning_agent",
            key="sys_instr_len",
            operator="gt",
            expected=0,
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py — RLM_STATIC_INSTRUCTION + resolved RLM_DYNAMIC_INSTRUCTION assembled into systemInstruction; zero length means instruction assembly failed",
        ),
        # --- before_tool must fire for execute_code ---
        PluginHookExpectation(
            hook="before_tool",
            agent_name="reasoning_agent",
            key="tool_name",
            operator="eq",
            expected="execute_code",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — REPLTool.name == 'execute_code'; InstrumentationPlugin.before_tool_callback fires before REPLTool.run_async()",
        ),
        # --- after_model must fire for reasoning_agent (confirms model loop completed) ---
        PluginHookExpectation(
            hook="after_model",
            agent_name="reasoning_agent",
            key="finish_reason",
            operator="eq",
            expected="STOP",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py — reasoning_agent.run_async() exits when finish_reason=STOP and set_model_response is called; after_model fires on each LLM response",
        ),
    ]

    timings = [
        # --- agent timing must be non-negative ---
        TimingExpectation(
            label="agent_reasoning_agent_ms",
            operator="gte",
            expected_ms=0.0,
            source_file="proposals/thread_bridge_plan_B/instrumented_runner_design.md",
            source_hint="InstrumentationPlugin.after_agent_callback — emits [TIMING:agent_<name>_ms=<elapsed>]; negative means start time was not recorded",
        ),
        # --- at least one model call must be timed ---
        TimingExpectation(
            label="model_call_1_ms",
            operator="gte",
            expected_ms=0.0,
            source_file="proposals/thread_bridge_plan_B/instrumented_runner_design.md",
            source_hint="InstrumentationPlugin.after_model_callback — emits [TIMING:model_call_<N>_ms=<elapsed>]; call 1 is the first reasoning model call",
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
            description="before_model must fire before before_tool (model decides to call execute_code)",
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
        # --- All placeholders must be resolved (absent from systemInstruction) ---
        DynInstrExpectation(
            key="repo_url=resolved=True",
            operator="eq",
            expected="True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py:93 — RLM_DYNAMIC_INSTRUCTION contains '{repo_url?}'; ADK resolves from session state key 'repo_url' seeded in initial_state",
        ),
        DynInstrExpectation(
            key="root_prompt=resolved=True",
            operator="eq",
            expected="True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py:93 — '{root_prompt?}' placeholder; resolved from 'root_prompt' seeded in initial_state",
        ),
        DynInstrExpectation(
            key="skill_instruction=resolved=True",
            operator="eq",
            expected="True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py:93 — '{skill_instruction?}' placeholder; resolved from DYN_SKILL_INSTRUCTION = 'skill_instruction' in session state",
        ),
        DynInstrExpectation(
            key="user_ctx_manifest=resolved=True",
            operator="eq",
            expected="True",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py Path B (lines 428-468) — builds user_ctx_manifest from user_provided_ctx dict; written as DYN_USER_CTX_MANIFEST = 'user_ctx_manifest'; unresolved means Path B did not run",
        ),
        # --- user_ctx must be loaded into REPL globals (Path B side-effect) ---
        DynInstrExpectation(
            key="user_ctx_keys",
            operator="contains",
            expected="arch_context.txt",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py Path B — pre-loads repl.globals['user_ctx'] = _pre_seeded dict from USER_PROVIDED_CTX; REPL code prints sorted(user_ctx.keys())",
        ),
    ]

    # --- REPLTrace expectations (active when RLM_REPL_TRACE=2 is set by runner) ---
    # All required=False: skipped if absent (trace disabled), fail if present but wrong.
    # When required=True, the instrumented runner MUST set RLM_REPL_TRACE=2 before running.
    repl_trace = [
        # execution_mode must be a known value (never "unknown")
        ReplTraceExpectation(
            key="execution_mode",
            operator="oneof",
            expected=["async_rewrite", "thread_bridge", "sync"],
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py — REPLTrace.execution_mode field; set to 'sync' by default, overwritten to 'async_rewrite' or 'thread_bridge' by REPLTool based on has_llm_calls()",
            required=True,  # required=True because runner sets RLM_REPL_TRACE=2 explicitly
        ),
        # wall_time_ms must be > 0 (timing callback fired)
        ReplTraceExpectation(
            key="wall_time_ms",
            operator="gt",
            expected=0.0,
            source_file="rlm_adk/repl/ipython_executor.py",
            source_hint="ipython_executor.py — _pre_run_cell sets trace.start_time, _post_run_cell sets trace.end_time via register_trace_callbacks(); both fire via IPython event system",
            required=True,
        ),
        # llm_call_count must be >= 1 (at least one llm_query dispatched)
        ReplTraceExpectation(
            key="llm_call_count",
            operator="gte",
            expected=1,
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py — REPLTrace.record_llm_start() called by dispatch.py before each llm_query(); count = len(REPLTrace.llm_calls)",
            required=True,
        ),
        # peak_memory_bytes must be > 0 at trace_level=2 (tracemalloc active)
        ReplTraceExpectation(
            key="peak_memory_bytes",
            operator="gt",
            expected=0,
            source_file="rlm_adk/repl/ipython_executor.py",
            source_hint="ipython_executor.py — _post_run_cell calls tracemalloc.get_traced_memory() and sets trace.peak_memory_bytes when trace_level >= 2 (RLM_REPL_TRACE=2)",
            required=True,  # required because runner sets RLM_REPL_TRACE=2
        ),
        # submitted_code_chars must be > 0 (code was actually submitted)
        ReplTraceExpectation(
            key="submitted_code_chars",
            operator="gt",
            expected=0,
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py — REPLTool.run_async() sets trace.submitted_code_chars = len(expanded_code) before calling execute_code()",
            required=True,
        ),
        # data_flow_edges: not asserting a specific count (depends on prompt content),
        # but if present must be a non-negative integer
        ReplTraceExpectation(
            key="data_flow_edges",
            operator="gte",
            expected=0,
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py — DataFlowTracker.get_edges() count; 0 is valid if child_result 'arch_test_ok' is short enough not to fingerprint-match; > 0 means response was fed into a later prompt",
            required=False,  # may legitimately be 0
        ),
        # var_snapshots_count must be >= 0 (0 is valid at trace_level=1)
        ReplTraceExpectation(
            key="var_snapshots_count",
            operator="gte",
            expected=0,
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py — REPLTrace.snapshot_vars() called at trace_level >= 1; count may be 0 if no user-visible variables were defined before snapshot",
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
```

---

## 4. `AssertionFailure` and Assertion Functions

### 4.1 `AssertionFailure` dataclass

```python
@dataclasses.dataclass
class AssertionFailure:
    """One failed assertion with full diagnostic context.

    Designed so a debugging coding agent can immediately identify:
    - The exact value that was wrong
    - Where that value is produced in the source
    - What to check to fix it
    """
    group: str              # "test_skill" | "plugin_hook" | "state_key" | "timing" | "ordering" | "dyn_instr"
    phase: str              # callback/hook phase where the mismatch occurred
    key: str                # the state key or tag key that failed
    expected: Any           # expected value or constraint operand
    actual: Any             # what was actually observed (or MISSING sentinel)
    operator: str           # the comparison operator that failed
    source_file: str        # file in the production codebase that writes this value
    source_hint: str        # specific class/method/line with action description
    fix_hint: str           # targeted suggestion for where to look

    MISSING: str = dataclasses.field(default="<MISSING>", init=False, repr=False)

    def format(self) -> str:
        """Format this failure as a multi-line human-readable block."""
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


_MISSING = "<MISSING>"
```

### 4.2 Operator evaluation

```python
def _eval_operator(operator: str, actual: Any, expected: Any) -> bool:
    """Evaluate a single operator constraint. Returns True if constraint passes."""
    if operator == "eq":
        # Coerce both sides to str for tag comparisons (all tags are strings)
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
        # actual is a string; expected is a substring to find in actual
        return str(expected) in str(actual)
    elif operator == "type":
        type_map = {"list": list, "dict": dict, "str": str, "int": int, "float": float, "bool": bool}
        return isinstance(actual, type_map.get(str(expected), object))
    return False
```

### 4.3 Individual assertion group functions

```python
def assert_test_skill_tags(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert all TestSkillExpectations against the parsed TEST_SKILL tags.

    Returns a list of failures (empty = all passed). Never raises.
    Checks real pipeline outputs: _rlm_state injection, skill expansion,
    child dispatch result, and latency — all produced by the real pipeline.
    """
    failures: list[AssertionFailure] = []
    for exp in lineage.test_skill_expectations:
        raw = log.test_skill.get(exp.key, _MISSING)

        if raw == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="test_skill",
                    phase="repl_stdout",
                    key=exp.key,
                    expected=exp.expected,
                    actual=_MISSING,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=(
                        f"[TEST_SKILL:{exp.key}=...] line absent from REPL stdout. "
                        f"Check that run_test_skill() was actually called and that "
                        f"SkillRegistry.expand() injected the skill source correctly. "
                        f"Verify REPL stdout is captured via InstrumentedContractResult.repl_stdout. "
                        f"Source: {exp.source_file}"
                    ),
                ))
            continue

        # For numeric operators, parse the value
        actual: Any = raw
        if exp.operator in ("gt", "gte", "lt", "lte"):
            try:
                actual = float(raw)
            except ValueError:
                failures.append(AssertionFailure(
                    group="test_skill",
                    phase="repl_stdout",
                    key=exp.key,
                    expected=exp.expected,
                    actual=raw,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=f"Value for {exp.key!r} is not numeric: {raw!r}. Check {exp.source_file}",
                ))
                continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="test_skill",
                phase="repl_stdout",
                key=exp.key,
                expected=exp.expected,
                actual=actual,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=_build_fix_hint("test_skill", exp.key, exp.operator, exp.expected, actual, exp.source_hint),
            ))
    return failures


def assert_plugin_hooks(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert all PluginHookExpectations against parsed PLUGIN entries.

    Each failure identifies the specific hook, agent, and key that was wrong,
    plus the source location in the plugin that emits it.
    """
    failures: list[AssertionFailure] = []
    for exp in lineage.plugin_hook_expectations:
        # Collect all entries matching this hook + agent
        if exp.agent_name == "*":
            entries = [e for e in log.plugin_entries if e.hook == exp.hook]
        else:
            entries = [e for e in log.plugin_entries
                      if e.hook == exp.hook and e.agent_name == exp.agent_name]

        # Find entries with matching key
        matching = [e for e in entries if e.key == exp.key]

        if not matching:
            if exp.required:
                failures.append(AssertionFailure(
                    group="plugin_hook",
                    phase=f"{exp.hook}:{exp.agent_name}",
                    key=exp.key,
                    expected=exp.expected,
                    actual=_MISSING,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=(
                        f"[PLUGIN:{exp.hook}:{exp.agent_name}:{exp.key}=...] absent. "
                        f"Check InstrumentationPlugin.{exp.hook}_callback() in "
                        f"proposals/thread_bridge_plan_B/instrumented_runner_design.md. "
                        f"Ensure InstrumentationPlugin is registered in the plugin list passed "
                        f"to run_instrumented_fixture(). Source: {exp.source_file}"
                    ),
                ))
            continue

        # Take the first matching entry's value (hooks fire in order)
        entry = matching[0]
        actual: Any = entry.value
        if exp.operator in ("gt", "gte", "lt", "lte", "gte"):
            try:
                actual = float(entry.value)
            except ValueError:
                pass

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="plugin_hook",
                phase=f"{exp.hook}:{exp.agent_name}",
                key=exp.key,
                expected=exp.expected,
                actual=actual,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=_build_fix_hint(
                    f"plugin:{exp.hook}:{exp.agent_name}", exp.key,
                    exp.operator, exp.expected, actual, exp.source_hint
                ),
            ))
    return failures


def assert_state_keys(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert StateKeyExpectations against STATE entries in the parsed log.

    Each STATE entry corresponds to a curated key captured by InstrumentationPlugin
    at a specific callback hook. Failures identify the exact phase where
    the key had the wrong value.
    """
    failures: list[AssertionFailure] = []
    for exp in lineage.state_key_expectations:
        scope_entries = log.state_at_scope(exp.phase)
        actual = scope_entries.get(exp.key, _MISSING)

        if actual == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="state_key",
                    phase=exp.phase,
                    key=exp.key,
                    expected=exp.expected,
                    actual=_MISSING,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=(
                        f"[STATE:{exp.phase}:{exp.key}=...] absent. "
                        f"InstrumentationPlugin._emit_state() only emits keys in CURATED_STATE_KEYS "
                        f"or matching CURATED_STATE_PREFIXES (rlm_adk/state.py). "
                        f"Check that {exp.key!r} is in CURATED_STATE_KEYS or has a matching prefix. "
                        f"Source: {exp.source_file}"
                    ),
                ))
            continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="state_key",
                phase=exp.phase,
                key=exp.key,
                expected=exp.expected,
                actual=actual,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=_build_fix_hint(
                    f"state:{exp.phase}", exp.key,
                    exp.operator, exp.expected, actual, exp.source_hint
                ),
            ))
    return failures


def assert_timings(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert TimingExpectations against TIMING entries."""
    failures: list[AssertionFailure] = []
    for exp in lineage.timing_expectations:
        actual_ms = log.timing_for(exp.label)
        if actual_ms is None:
            failures.append(AssertionFailure(
                group="timing",
                phase="instrumentation",
                key=exp.label,
                expected=f"{exp.operator} {exp.expected_ms}ms",
                actual=_MISSING,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=(
                    f"[TIMING:{exp.label}=...] absent. "
                    f"Check InstrumentationPlugin.after_agent_callback() / after_model_callback(). "
                    f"These emit TIMING lines only on successful hook completion. "
                    f"If the hook raised an exception it is swallowed — check for malformed_lines. "
                    f"Source: {exp.source_file}"
                ),
            ))
            continue

        if not _eval_operator(exp.operator, actual_ms, exp.expected_ms):
            failures.append(AssertionFailure(
                group="timing",
                phase="instrumentation",
                key=exp.label,
                expected=f"{exp.operator} {exp.expected_ms}ms",
                actual=actual_ms,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=f"Timing {exp.label!r} = {actual_ms}ms failed {exp.operator} {exp.expected_ms}ms. Check {exp.source_file}",
            ))
    return failures


def assert_orderings(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert OrderingExpectations — that one hook appears before another."""
    failures: list[AssertionFailure] = []

    for exp in lineage.ordering_expectations:
        # Find first line number for each hook+agent pair
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
                group="ordering",
                phase="log_sequence",
                key=f"{exp.first_hook}:{exp.first_agent}",
                expected=f"appears before {exp.second_hook}:{exp.second_agent}",
                actual=_MISSING,
                operator="before",
                source_file="proposals/thread_bridge_plan_B/instrumented_runner_design.md",
                source_hint=exp.description,
                fix_hint=f"Hook {exp.first_hook!r} for agent {exp.first_agent!r} never appeared. Check InstrumentationPlugin registration.",
            ))
        elif second_lineno is None:
            failures.append(AssertionFailure(
                group="ordering",
                phase="log_sequence",
                key=f"{exp.second_hook}:{exp.second_agent}",
                expected=f"appears after {exp.first_hook}:{exp.first_agent}",
                actual=_MISSING,
                operator="before",
                source_file="proposals/thread_bridge_plan_B/instrumented_runner_design.md",
                source_hint=exp.description,
                fix_hint=f"Hook {exp.second_hook!r} for agent {exp.second_agent!r} never appeared. Check InstrumentationPlugin registration.",
            ))
        elif first_lineno >= second_lineno:
            failures.append(AssertionFailure(
                group="ordering",
                phase="log_sequence",
                key=f"{exp.first_hook}:{exp.first_agent} before {exp.second_hook}:{exp.second_agent}",
                expected=f"line({exp.first_hook}) < line({exp.second_hook})",
                actual=f"line({exp.first_hook})={first_lineno} >= line({exp.second_hook})={second_lineno}",
                operator="before",
                source_file="proposals/thread_bridge_plan_B/instrumented_runner_design.md",
                source_hint=exp.description,
                fix_hint=(
                    f"Ordering violation: {exp.description}. "
                    f"ADK callback lifecycle guarantees this order — if it's reversed, "
                    f"check whether InstrumentationPlugin is correctly inheriting from BasePlugin "
                    f"and not short-circuiting the callback chain by returning a non-None value."
                ),
            ))
    return failures


def assert_dyn_instr(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert DynInstrExpectations against parsed DYN_INSTR entries."""
    failures: list[AssertionFailure] = []
    for exp in lineage.dyn_instr_expectations:
        actual = log.dyn_instr.get(exp.key, _MISSING)

        if actual == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="dyn_instr",
                    phase="systemInstruction_capture",
                    key=exp.key,
                    expected=exp.expected,
                    actual=_MISSING,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=(
                        f"[DYN_INSTR:{exp.key}=...] absent. "
                        f"This tag is emitted by make_dyn_instr_capture_hook() or by the "
                        f"REPL code block in skill_arch_test.json responses[0]. "
                        f"Check that dyn_instr_capture_hook is wired to reasoning_agent.before_model_callback "
                        f"before running the fixture (via object.__setattr__ in test setup). "
                        f"Source: {exp.source_file}"
                    ),
                ))
            continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="dyn_instr",
                phase="systemInstruction_capture",
                key=exp.key,
                expected=exp.expected,
                actual=actual,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=_build_fix_hint(
                    "dyn_instr", exp.key, exp.operator, exp.expected, actual, exp.source_hint
                ),
            ))
    return failures


def assert_repl_trace(
    log: ParsedLog,
    lineage: ExpectedLineage,
) -> list[AssertionFailure]:
    """Assert ReplTraceExpectations against parsed REPL_TRACE entries.

    REPLTrace data is only present when RLM_REPL_TRACE >= 1. Expectations with
    required=False are silently skipped when the key is absent. Expectations
    with required=True fail if the key is absent, which will happen if the
    instrumented runner forgot to set RLM_REPL_TRACE=2.
    """
    failures: list[AssertionFailure] = []
    trace = log.repl_trace()

    for exp in lineage.repl_trace_expectations:
        raw = trace.get(exp.key, _MISSING)

        if raw == _MISSING:
            if exp.required:
                failures.append(AssertionFailure(
                    group="repl_trace",
                    phase="repl_trace_plugin",
                    key=exp.key,
                    expected=exp.expected,
                    actual=_MISSING,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=(
                        f"[REPL_TRACE:{exp.key}=...] absent. "
                        f"This key is only emitted when RLM_REPL_TRACE >= 1. "
                        f"Verify the instrumented runner sets os.environ['RLM_REPL_TRACE'] = '2' "
                        f"before calling run_instrumented_fixture(). "
                        f"Also confirm REPLTracingPlugin is in the plugin list and that "
                        f"REPLTrace is passed to LocalREPL.execute_code(). "
                        f"Source: {exp.source_file}"
                    ),
                ))
            continue

        # Parse numeric values for comparison operators
        actual: Any = raw
        if exp.operator in ("gt", "gte", "lt", "lte"):
            try:
                actual = float(raw)
            except ValueError:
                failures.append(AssertionFailure(
                    group="repl_trace",
                    phase="repl_trace_plugin",
                    key=exp.key,
                    expected=exp.expected,
                    actual=raw,
                    operator=exp.operator,
                    source_file=exp.source_file,
                    source_hint=exp.source_hint,
                    fix_hint=f"REPL_TRACE key {exp.key!r} is not numeric: {raw!r}. Check {exp.source_file}",
                ))
                continue

        if not _eval_operator(exp.operator, actual, exp.expected):
            failures.append(AssertionFailure(
                group="repl_trace",
                phase="repl_trace_plugin",
                key=exp.key,
                expected=exp.expected,
                actual=actual,
                operator=exp.operator,
                source_file=exp.source_file,
                source_hint=exp.source_hint,
                fix_hint=_build_fix_hint(
                    "repl_trace", exp.key, exp.operator, exp.expected, actual, exp.source_hint
                ),
            ))
    return failures
```

### 4.4 Fix-hint builder

```python
def _build_fix_hint(
    group: str,
    key: str,
    operator: str,
    expected: Any,
    actual: Any,
    source_hint: str,
) -> str:
    """Build a targeted fix hint from the assertion context."""
    if operator == "eq":
        return (
            f"Key {key!r} in group {group!r}: got {actual!r}, expected {expected!r}. "
            f"Check: {source_hint}"
        )
    elif operator in ("gt", "gte"):
        return (
            f"Key {key!r} in group {group!r}: got {actual} which fails {operator} {expected}. "
            f"If actual is 0 or negative, the pipeline step that writes this value did not run. "
            f"Check: {source_hint}"
        )
    elif operator == "contains":
        return (
            f"Key {key!r} in group {group!r}: expected substring {expected!r} not found in {actual!r}. "
            f"Check: {source_hint}"
        )
    elif operator == "oneof":
        return (
            f"Key {key!r} in group {group!r}: got {actual!r}, expected one of {expected!r}. "
            f"Check: {source_hint}"
        )
    else:
        return f"Key {key!r} in group {group!r}: constraint {operator}({expected!r}) failed with actual={actual!r}. Check: {source_hint}"
```

---

## 5. Unified Assertion Runner and Failure Report

### 5.1 `AssertionReport` dataclass

```python
@dataclasses.dataclass
class AssertionReport:
    """Aggregated result of all assertion groups against a ParsedLog.

    Designed for pytest: call report.raise_if_failed() to get a single
    AssertionError with the complete multi-group diagnostic if any group failed.
    """
    failures: list[AssertionFailure]
    groups_checked: list[str]
    log: ParsedLog

    @property
    def passed(self) -> bool:
        return len(self.failures) == 0

    def failures_in_group(self, group: str) -> list[AssertionFailure]:
        return [f for f in self.failures if f.group == group]

    def format_report(self) -> str:
        """Multi-line human-readable report of all failures, grouped by phase."""
        if self.passed:
            return f"PASS: all {len(self.groups_checked)} assertion groups passed."

        lines = [
            f"FAIL: {len(self.failures)} assertion(s) failed across {len(self.groups_checked)} group(s).",
            f"Groups checked: {', '.join(self.groups_checked)}",
            "",
        ]

        # Group failures by group name
        by_group: dict[str, list[AssertionFailure]] = {}
        for f in self.failures:
            by_group.setdefault(f.group, []).append(f)

        for group_name, group_failures in by_group.items():
            lines.append(f"--- Group: {group_name} ({len(group_failures)} failure(s)) ---")
            for f in group_failures:
                lines.append(f.format())
            lines.append("")

        # Include malformed line warnings
        if self.log.malformed_lines:
            lines.append(f"--- Malformed tagged lines ({len(self.log.malformed_lines)}) ---")
            for ml in self.log.malformed_lines[:10]:
                lines.append(f"  {ml}")
            if len(self.log.malformed_lines) > 10:
                lines.append(f"  ... and {len(self.log.malformed_lines) - 10} more")

        return "\n".join(lines)

    def raise_if_failed(self) -> None:
        """Raise AssertionError with the full report if any failures exist."""
        if not self.passed:
            raise AssertionError(self.format_report())
```

### 5.2 `run_all_assertions` — unified entry point

```python
def run_all_assertions(
    log: ParsedLog,
    lineage: ExpectedLineage,
    *,
    groups: list[str] | None = None,
) -> AssertionReport:
    """Run all assertion groups and collect every failure before returning.

    Args:
        log: ParsedLog from parse_stdout().
        lineage: ExpectedLineage specifying what is expected.
        groups: Optional list of group names to check. If None, all groups
            are checked. Valid values: "test_skill", "plugin_hook", "state_key",
            "timing", "ordering", "dyn_instr".

    Returns:
        AssertionReport with all failures. Call report.raise_if_failed() in
        pytest to get a single AssertionError with the complete diagnostic.

    Design: collects ALL failures before returning. This gives the debugging
    agent the complete picture in one run rather than halting at the first
    mismatch (which would require re-running the expensive provider-fake fixture
    repeatedly to discover each failure).
    """
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
```

---

## 6. Error Message Format Specification

### 6.1 Structure of a well-formed failure message

Every `AssertionFailure.format()` output follows this layout:

```
  FAIL [<group>] phase=<phase> key=<key>
    operator : <operator>
    expected : <expected value or constraint>
    actual   : <observed value or "<MISSING>">
    source   : <file path in production codebase>
    detail   : <class/method/line with action description>
    fix hint : <targeted debugging instruction>
```

### 6.2 Concrete examples of good failure messages

**Example A — `_rlm_state` injection not reaching REPL**

```
  FAIL [test_skill] phase='repl_stdout' key='depth'
    operator : eq
    expected : '0'
    actual   : '<MISSING>'
    source   : rlm_adk/tools/repl_tool.py
    detail   : repl_tool.py:220 — _rlm_depth injected into _rlm_state from REPLTool._rlm_depth constructor field
    fix hint : [TEST_SKILL:depth=...] line absent from REPL stdout. Check that run_test_skill() was
               actually called and that SkillRegistry.expand() injected the skill source correctly.
               Verify REPL stdout is captured via InstrumentedContractResult.repl_stdout.
               Source: rlm_adk/tools/repl_tool.py
```

**Example B — child dispatch returned wrong value**

```
  FAIL [test_skill] phase='repl_stdout' key='child_result_preview'
    operator : contains
    expected : 'arch_test_ok'
    actual   : 'None'
    source   : rlm_adk/dispatch.py
    detail   : dispatch.py — child orchestrator at depth=1 must return 'arch_test_ok' via set_model_response;
               LLMResult str extraction in _read_child_completion()
    fix hint : Key 'child_result_preview' in group 'test_skill': expected substring 'arch_test_ok' not
               found in 'None'. Check: dispatch.py — child orchestrator at depth=1 must return 'arch_test_ok'
               via set_model_response; LLMResult str extraction in _read_child_completion()
```

**Example C — dynamic instruction placeholder not resolved**

```
  FAIL [dyn_instr] phase='systemInstruction_capture' key='user_ctx_manifest=resolved=True'
    operator : eq
    expected : 'True'
    actual   : 'False'
    source   : rlm_adk/orchestrator.py
    detail   : orchestrator.py Path B (lines 428-468) — builds user_ctx_manifest from user_provided_ctx dict;
               written as DYN_USER_CTX_MANIFEST = 'user_ctx_manifest'; unresolved means Path B did not run
    fix hint : Key 'user_ctx_manifest=resolved=True' in group 'dyn_instr': got 'False', expected 'True'.
               Check: orchestrator.py Path B (lines 428-468). Confirm initial_state['user_provided_ctx']
               is a non-empty dict in skill_arch_test.json. If Path B's conditional check fails,
               user_ctx_manifest is never written and ADK leaves the placeholder raw.
```

**Example D — hook ordering violation**

```
  FAIL [ordering] phase='log_sequence' key='before_model:reasoning_agent before before_tool:reasoning_agent'
    operator : before
    expected : 'line(before_model) < line(before_tool)'
    actual   : 'line(before_model)=44 >= line(before_tool)=12'
    source   : proposals/thread_bridge_plan_B/instrumented_runner_design.md
    detail   : before_model must fire before before_tool (model decides to call execute_code)
    fix hint : Ordering violation: before_model must fire before before_tool (model decides to call execute_code).
               ADK callback lifecycle guarantees this order — if it's reversed, check whether
               InstrumentationPlugin is correctly inheriting from BasePlugin and not short-circuiting
               the callback chain by returning a non-None value.
```

**Example E — plugin hook missing (InstrumentationPlugin not registered)**

```
  FAIL [plugin_hook] phase='before_agent:reasoning_agent' key='depth'
    operator : eq
    expected : '0'
    actual   : '<MISSING>'
    source   : rlm_adk/agent.py
    detail   : agent.py — _rlm_depth=0 set on root reasoning_agent at construction;
               InstrumentationPlugin.before_agent_callback reads it via getattr(agent, '_rlm_depth', 0)
    fix hint : [PLUGIN:before_agent:reasoning_agent:depth=...] absent. Check InstrumentationPlugin.before_agent_callback()
               in proposals/thread_bridge_plan_B/instrumented_runner_design.md. Ensure InstrumentationPlugin is
               registered in the plugin list passed to run_instrumented_fixture().
               Source: rlm_adk/agent.py
```

### 6.3 Aggregated report header

When `AssertionReport.format_report()` is called after multiple failures:

```
FAIL: 3 assertion(s) failed across 4 group(s).
Groups checked: test_skill, plugin_hook, state_key, ordering

--- Group: test_skill (1 failure(s)) ---
  FAIL [test_skill] phase='repl_stdout' key='child_result_preview'
    ...

--- Group: plugin_hook (1 failure(s)) ---
  FAIL [plugin_hook] phase='before_model:reasoning_agent' key='sys_instr_len'
    ...

--- Group: ordering (1 failure(s)) ---
  FAIL [ordering] phase='log_sequence' key='...'
    ...

--- Malformed tagged lines (0) ---
```

---

## 7. Debug Instrumentation Layer

The instrumented runner activates three environment variables before calling `run_instrumented_fixture()`. These form the "debug instrumentation layer" — they are set exclusively for this e2e test fixture and must not be set in normal test runs or CI.

### 7.1 `RLM_REPL_TRACE=2` — Full REPL tracing with memory

**Source**: `rlm_adk/repl/local_repl.py:290` reads `os.environ.get("RLM_REPL_TRACE", "0")`.

**What it activates**:
- Level 1: LLM call timing (`REPLTrace.record_llm_start/end`), variable snapshots (`snapshot_vars`), `DataFlowTracker` fingerprint checks
- Level 2: + `tracemalloc` memory tracking via IPython `pre_run_cell`/`post_run_cell` callbacks registered in `IPythonDebugExecutor.register_trace_callbacks()`

**How callbacks fire**: `IPythonDebugExecutor.register_trace_callbacks(trace, trace_level=2)` registers `_pre_run_cell` (starts timer + `tracemalloc.start()`) and `_post_run_cell` (reads peak memory + sets `trace.end_time`) via `shell.events.register()`. Crucially, these are IPython event callbacks — **no code is injected into user code**, so line numbers in tracebacks are never shifted.

**What `REPLTracingPlugin` emits**: At run end, `REPLTracingPlugin.after_run()` iterates over collected `REPLTrace` objects and emits `[REPL_TRACE:key=value]` tagged lines for each field in `REPLTrace.summary()`. These appear in `instrumentation_log`.

**Runner setup**:
```python
os.environ["RLM_REPL_TRACE"] = "2"
```

### 7.2 `RLM_REPL_XMODE=Verbose` — IPython verbose traceback mode (NEW)

**Source**: `rlm_adk/repl/ipython_executor.py:54` reads `os.environ.get("RLM_REPL_XMODE", "Context")` into `REPLDebugConfig.xmode`. Applied at `IPythonDebugExecutor.__init__()` line 100 via `self._shell.InteractiveTB.set_mode(mode=self._config.xmode)`.

**What it activates**: IPython's `Verbose` traceback mode dumps **local variable values at each stack frame** when an exception propagates through REPL-executed code. In the default `Context` mode, only source lines appear. In `Verbose` mode, each frame shows all local variables — `timestamps`, `_rlm_state`, `child_result`, `state_snapshot`, etc. — without any extra `print()` statements.

**When it matters**: If `run_test_skill()` raises inside a provider-fake run, the traceback in `stderr` will contain variable values from every frame. This is the primary debugging surface for thread-bridge failures where `llm_query()` itself raises.

**Stderr parsing**: The assertion framework's `AssertionReport.format_report()` includes `log.malformed_lines` warnings. A future enhancement can parse Verbose tracebacks from the `result.repl_stderr` string (not currently a field of `ParsedLog`). For now, the runner should attach `result.repl_stderr` to the `AssertionError` message when failures occur:

```python
# In run_instrumented_fixture's error path:
if result.repl_stderr:
    raise AssertionError(
        report.format_report()
        + "\n\n--- REPL stderr (Verbose xmode traceback) ---\n"
        + result.repl_stderr[:3000]
    )
```

**Note on `repl_stderr` in `ParsedLog`**: The current `ParsedLog` parses only stdout. Verbose xmode tracebacks land in stderr. The `parse_stdout()` function should accept an optional `raw_stderr` parameter in a future revision so traceback locals can be extracted as structured data. For now, raw stderr is included in the `AssertionError` message as plain text.

**Runner setup**:
```python
os.environ["RLM_REPL_XMODE"] = "Verbose"
```

### 7.3 `RLM_REPL_DEBUG=1` — IPython debug flag (NEW)

**Source**: `rlm_adk/repl/ipython_executor.py:48` reads `os.environ.get("RLM_REPL_DEBUG", "0") == "1"` into `REPLDebugConfig.debug`.

**What it activates**: Sets `REPLDebugConfig.debug = True`. In `IPythonDebugExecutor.execute_sync()`, when `debug=True` AND `ipython_embed=True`, an embedded IPython shell opens on exception (`_embed_on_exception`). In the e2e test context, `ipython_embed` is left False (it requires a TTY), so `RLM_REPL_DEBUG=1` alone does not open an interactive shell. Its primary effect in this context is enabling additional diagnostic logging from the executor and making `REPLDebugConfig.debug` available for downstream checks (e.g. a future `debug_dump_namespace()` path).

**When to use**: Set this alongside `RLM_REPL_TRACE=2` to get maximal diagnostic output. In CI, leave unset.

**Runner setup**:
```python
os.environ["RLM_REPL_DEBUG"] = "1"
```

### 7.4 Complete runner env setup block

```python
def _set_debug_instrumentation_env() -> dict[str, str | None]:
    """Set debug instrumentation env vars for the skill_arch_test fixture.

    Returns the saved env state for restoration after the run.
    Only set these for architecture e2e tests — NOT in normal CI fixture runs.
    """
    saved = {
        "RLM_REPL_TRACE": os.environ.get("RLM_REPL_TRACE"),
        "RLM_REPL_XMODE": os.environ.get("RLM_REPL_XMODE"),
        "RLM_REPL_DEBUG": os.environ.get("RLM_REPL_DEBUG"),
    }
    os.environ["RLM_REPL_TRACE"] = "2"     # full tracing + tracemalloc
    os.environ["RLM_REPL_XMODE"] = "Verbose"  # local vars in tracebacks
    os.environ["RLM_REPL_DEBUG"] = "1"     # enable debug flag on executor
    return saved


def _restore_debug_instrumentation_env(saved: dict[str, str | None]) -> None:
    """Restore env vars after a debug instrumented run."""
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val
```

Usage in test:
```python
@pytest.mark.asyncio
async def test_skill_arch_e2e():
    saved = _set_debug_instrumentation_env()
    try:
        result = await run_instrumented_fixture(fixture_path)
    finally:
        _restore_debug_instrumentation_env(saved)
    ...
```

### 7.5 `REPL_TRACE` assertion group: what it verifies

The `assert_repl_trace()` function (Section 4.3) verifies that:

1. **`execution_mode`** is a known value — confirms `REPLTrace.execution_mode` was set by `REPLTool`, not left at the default `"sync"` (which would mean the trace was never updated from its initial state).
2. **`wall_time_ms > 0`** — confirms both `pre_run_cell` and `post_run_cell` callbacks fired via IPython's event system. Zero means `_post_run_cell` never ran, which indicates the IPython shell was not used (backend fell back to raw `exec()`).
3. **`llm_call_count >= 1`** — confirms `REPLTrace.record_llm_start()` was called at least once, proving `dispatch.py`'s call path reaches `trace.record_llm_start()` before dispatching.
4. **`peak_memory_bytes > 0`** — confirms `tracemalloc` ran at trace level 2. Zero means `register_trace_callbacks()` didn't receive `trace_level=2`, which means `RLM_REPL_TRACE` was not read as `"2"` by `local_repl.py:290`.
5. **`submitted_code_chars > 0`** — confirms `REPLTool.run_async()` set `trace.submitted_code_chars` before calling `execute_code()`, verifying the trace object was actually threaded through the call chain.

---

## 8. Reward-Hacking Prevention Documentation

### 8.1 What reward-hacking would look like

Reward-hacking in this context means fixtures or assertions that report success without the pipeline actually executing the behavior under test. Concrete forms:

1. **Pre-seeding test-skill outputs**: The fixture pre-populates `LAST_REPL_RESULT` or `repl_did_expand` with `True` before the run so assertions pass without the REPL executing.
2. **Mocking llm_query in test setup**: The test replaces `llm_query` with a stub returning `"arch_test_ok"` directly, bypassing the real child dispatch loop in `dispatch.py`.
3. **Asserting fixture JSON fields instead of runtime output**: Checking `fixture["expected"]["final_answer"]` rather than `plugin_result.contract.checks`.
4. **Pre-populating `_captured_system_instruction_0`**: Setting the state key before the run so the dynamic instruction capture hook writes over a pre-set value.

### 8.2 Why each assertion tests REAL pipeline behavior

| Assertion | What it tests | Why it can't be reward-hacked |
|-----------|--------------|-------------------------------|
| `TEST_SKILL:depth=0` | `_rlm_state["_rlm_depth"]` injected by `REPLTool.run_async()` at line 220 | Value comes from the REPL namespace at runtime; not in any state key the fixture can seed |
| `TEST_SKILL:child_result_preview contains arch_test_ok` | Return value of `llm_query()` round-trip via real `dispatch.py` child orchestrator | `"arch_test_ok"` comes from fixture response call_index=1 (worker), processed by the real `_read_child_completion()` path in dispatch.py; not in session state |
| `TEST_SKILL:execution_mode in [async_rewrite, thread_bridge]` | Whether `_repl_exec` is in globals (AST rewriter) or not (thread bridge) | Detected inside expanded skill source at runtime; cannot be seeded |
| `TEST_SKILL:COMPLETE=True` | Successful return from `run_test_skill()` without exception | Only emitted as the last line of the function body; a failed or skipped skill execution never emits it |
| `PLUGIN:before_agent:reasoning_agent:depth=0` | `_rlm_depth` on the reasoning agent via `InstrumentationPlugin.before_agent_callback` | Plugin fires on the live agent instance; the value comes from `getattr(agent, '_rlm_depth', 0)` |
| `PLUGIN:before_model:reasoning_agent:sys_instr_len>0` | Length of the assembled `systemInstruction` from the real ADK `LlmRequest` | `llm_request.config.system_instruction` is assembled by ADK from static + resolved dynamic instruction at model call time |
| `DYN_INSTR:user_ctx_manifest=resolved=True` | Whether `{user_ctx_manifest?}` is absent from the live `systemInstruction` text | Captured from the real `LlmRequest` in `dyn_instr_capture_hook(callback_context, llm_request)` |
| `STATE:model_call_1:repl_did_expand=False` | State key value at the before_model hook (before execute_code runs) | `InstrumentationPlugin.before_model_callback` reads from `callback_context.state` which is the live ADK session state |
| Ordering: `before_agent` before `before_model` | ADK callback lifecycle ordering | Based on line numbers in the captured stdout, which reflects actual emission order during the real run |
| `REPL_TRACE:wall_time_ms > 0` | IPython `pre_run_cell`/`post_run_cell` callbacks fired | Timing set by `_pre_run_cell`/`_post_run_cell` registered via `shell.events.register()` in `ipython_executor.py`; zero only if IPython backend was not used |
| `REPL_TRACE:peak_memory_bytes > 0` | `tracemalloc` ran at trace level 2 | Only nonzero if `tracemalloc.start()` ran in `_pre_run_cell` and `get_traced_memory()` ran in `_post_run_cell`; confirms `RLM_REPL_TRACE=2` was read correctly by `local_repl.py:290` |
| `REPL_TRACE:llm_call_count >= 1` | `REPLTrace.record_llm_start()` was called in dispatch path | Called by `dispatch.py` before each `llm_query()` dispatch; cannot be faked without bypassing the real dispatch machinery |

### 8.3 Anti-reward-hack fixture rules enforced by the design

**Rule 1**: The `skill_arch_test.json` fixture does NOT pre-populate `repl_did_expand`, `LAST_REPL_RESULT`, or any `TEST_SKILL` keys in `initial_state`. The only `initial_state` keys are the dynamic instruction seeds (`user_provided_ctx`, `repo_url`, `root_prompt`, `test_context`, `skill_instruction`) — which are inputs to the pipeline, not outputs.

**Rule 2**: The child worker response (call_index=1) uses `set_model_response` with `final_answer: "arch_test_ok"`. The skill's `child_result_preview` assertion checks for `"arch_test_ok"` in the REPL stdout — the only way this appears there is if `dispatch.py._read_child_completion()` correctly extracted the `LLMResult` from the child agent's response and the skill's print statement executed.

**Rule 3**: `parse_stdout()` operates on the `repl_stdout` string from `InstrumentedContractResult.repl_stdout`, which is captured via `io.StringIO` redirect during the actual REPL execution. It is never pre-populated or mocked.

**Rule 4**: The `dyn_instr_capture_hook` writes `_captured_system_instruction_0` from the live `llm_request.config.system_instruction` object — not from session state keys. The only way this value contains the resolved placeholder content is if ADK's template engine ran on the real session state.

---

## 9. Pytest Integration

### 9.1 Pattern for a single test using the full assertion suite

```python
"""test_skill_arch_e2e.py — pytest integration for assertion framework.

Location: tests_rlm_adk/test_skill_arch_e2e.py
"""

import pytest
import rlm_adk.skills.test_skill  # noqa: F401 — side-effect: populates SkillRegistry

from tests_rlm_adk.provider_fake.stdout_parser import parse_stdout, run_all_assertions
from tests_rlm_adk.provider_fake.expected_lineage import build_skill_arch_test_lineage


@pytest.mark.asyncio
async def test_skill_arch_e2e():
    """Full architecture e2e: skill expansion + child dispatch + dynamic instruction."""
    from pathlib import Path
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_instrumented_fixture,  # new variant that includes InstrumentationPlugin
    )

    fixture_path = Path("tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json")
    result = await run_instrumented_fixture(fixture_path)

    # 1. Contract must pass first (fixture response sequence consumed correctly)
    assert result.contract.passed, result.contract.diagnostics()

    # 2. Parse all tagged lines from the instrumented stdout
    combined_stdout = result.repl_stdout + "\n" + result.instrumentation_log
    log = parse_stdout(combined_stdout)

    # 3. Build expected lineage
    lineage = build_skill_arch_test_lineage()

    # 4. Run all assertions — collect ALL failures before raising
    report = run_all_assertions(log, lineage)

    # 5. Raise with the full diagnostic report if anything failed
    report.raise_if_failed()
```

### 9.2 Running individual assertion groups

For targeted debugging during development:

```python
@pytest.mark.asyncio
async def test_skill_arch_state_injection_only():
    """Narrowed: assert only TEST_SKILL state injection tags."""
    ...
    report = run_all_assertions(log, lineage, groups=["test_skill"])
    report.raise_if_failed()


@pytest.mark.asyncio
async def test_skill_arch_dynamic_instruction_only():
    """Narrowed: assert only dynamic instruction resolution."""
    ...
    report = run_all_assertions(log, lineage, groups=["dyn_instr"])
    report.raise_if_failed()


@pytest.mark.asyncio
async def test_skill_arch_repl_trace_only():
    """Narrowed: assert only REPLTrace data (requires RLM_REPL_TRACE=2)."""
    saved = _set_debug_instrumentation_env()
    try:
        ...
        report = run_all_assertions(log, lineage, groups=["repl_trace"])
    finally:
        _restore_debug_instrumentation_env(saved)
    report.raise_if_failed()
```

### 9.3 Pytest fixture for reuse across test modules

```python
# In conftest.py:

import pytest
from tests_rlm_adk.provider_fake.stdout_parser import ParsedLog, parse_stdout

@pytest.fixture(scope="session")
async def skill_arch_log() -> ParsedLog:
    """Run the skill_arch_test fixture once and return the parsed log.

    Session-scoped so the expensive fixture run is shared across all
    test functions that need it.
    """
    import rlm_adk.skills.test_skill  # noqa: F401
    from pathlib import Path
    from tests_rlm_adk.provider_fake.contract_runner import run_instrumented_fixture

    fixture_path = Path("tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json")
    result = await run_instrumented_fixture(fixture_path)
    assert result.contract.passed, result.contract.diagnostics()
    combined = result.repl_stdout + "\n" + result.instrumentation_log
    return parse_stdout(combined)


def test_state_injection(skill_arch_log):
    from tests_rlm_adk.provider_fake.stdout_parser import run_all_assertions
    from tests_rlm_adk.provider_fake.expected_lineage import build_skill_arch_test_lineage
    report = run_all_assertions(skill_arch_log, build_skill_arch_test_lineage(), groups=["test_skill", "state_key"])
    report.raise_if_failed()


def test_plugin_hooks(skill_arch_log):
    from tests_rlm_adk.provider_fake.stdout_parser import run_all_assertions
    from tests_rlm_adk.provider_fake.expected_lineage import build_skill_arch_test_lineage
    report = run_all_assertions(skill_arch_log, build_skill_arch_test_lineage(), groups=["plugin_hook", "ordering"])
    report.raise_if_failed()
```

### 9.4 Output in pytest when a failure occurs

pytest captures stdout and the `AssertionError` message together. The format produces a readable block in `pytest -v` output:

```
FAILED tests_rlm_adk/test_skill_arch_e2e.py::test_skill_arch_e2e - AssertionError: FAIL: 2 assertion(s) failed across 6 group(s).
Groups checked: test_skill, plugin_hook, state_key, timing, ordering, dyn_instr

--- Group: test_skill (1 failure(s)) ---
  FAIL [test_skill] phase='repl_stdout' key='child_result_preview'
    operator : contains
    expected : 'arch_test_ok'
    actual   : 'None'
    source   : rlm_adk/dispatch.py
    detail   : dispatch.py — child orchestrator at depth=1 must return 'arch_test_ok' via set_model_response
    fix hint : expected substring 'arch_test_ok' not found in 'None'. Check dispatch.py _read_child_completion()

--- Group: dyn_instr (1 failure(s)) ---
  FAIL [dyn_instr] phase='systemInstruction_capture' key='user_ctx_manifest=resolved=True'
    operator : eq
    expected : 'True'
    actual   : 'False'
    source   : rlm_adk/orchestrator.py
    detail   : orchestrator.py Path B (lines 428-468) — builds user_ctx_manifest from user_provided_ctx dict
    fix hint : Confirm initial_state['user_provided_ctx'] is a non-empty dict in skill_arch_test.json.
```

---

## 10. Files to Create

| File | Action | Description |
|------|--------|-------------|
| `tests_rlm_adk/provider_fake/stdout_parser.py` | **Create** | `StdoutParser` via `parse_stdout()`, `ParsedLog`, all tag-family dataclasses |
| `tests_rlm_adk/provider_fake/expected_lineage.py` | **Create** | `ExpectedLineage`, all `*Expectation` dataclasses, `build_skill_arch_test_lineage()` |
| `tests_rlm_adk/provider_fake/assertion_runner.py` | **Create** | `AssertionFailure`, `AssertionReport`, all `assert_*` functions, `run_all_assertions()`, `_build_fix_hint()` |
| `tests_rlm_adk/test_skill_arch_e2e.py` | **Create** | Pytest test module using the framework |

Note: `stdout_parser.py` and `assertion_runner.py` are split so `parse_stdout()` can be imported independently in contexts where only parsing (not assertion) is needed (e.g., interactive debugging or REPL inspection).

---

## 11. Key Design Decisions

### Decision 1: Collect all failures before raising

`run_all_assertions()` runs every group and collects every failure before returning an `AssertionReport`. Only `raise_if_failed()` converts them to an `AssertionError`. This avoids the frustrating "fix one thing, re-run, discover the next thing" loop that is especially costly when each fixture run exercises a real provider-fake server.

### Decision 2: `_MISSING` sentinel instead of `None`

`None` is a valid actual value for some state keys (e.g. `should_stop` before it's set). Using the string `"<MISSING>"` as a sentinel makes it unambiguous in failure messages whether a key was absent vs present with a `None` value.

### Decision 3: `source_file` + `source_hint` on every expectation

Every expectation carries two provenance fields: `source_file` (the file in the production codebase) and `source_hint` (the class/method/line with a description of what it does). This is the data that makes failure messages immediately actionable for a debugging coding agent — it eliminates the need to search for where a value comes from.

### Decision 4: Operator strings match the `$op` vocabulary from `fixtures.py`

The operator strings (`eq`, `contains`, `gt`, `gte`, `not_none`, `oneof`) align with the existing `$contains`, `$gt`, `$not_none`, `$oneof` operators in `fixtures.py:_match_value()`. This makes the framework consistent with the existing contract matcher vocabulary and reduces cognitive overhead when reading assertions.

### Decision 5: `parse_stdout` is non-destructive and malformed-line tolerant

The parser never raises. Malformed lines are collected in `ParsedLog.malformed_lines` and included in the `AssertionReport` as warnings. This prevents a single misformatted print from silently killing the entire assertion suite and gives the debugging agent a list of lines to investigate.

### Decision 6: `ExpectedLineage` is a plain dataclass, not YAML/JSON config

The expectations are Python code rather than a declarative config format. This allows `source_file` and `source_hint` to carry rich strings, allows `operator` to be validated at import time, and keeps the expectations close to the test code where they're used. If a key constant changes in `state.py`, the `expected_lineage.py` import fails immediately rather than silently passing with stale values.

### Decision 7: `ReplTraceExpectation.required=False` by default, overridden to `True` for keys that are gated on `RLM_REPL_TRACE=2`

Most `ReplTraceExpectation` entries default to `required=False` so that the assertion group doesn't fail in runs where tracing is disabled. The instrumented runner sets `RLM_REPL_TRACE=2` before each e2e run, so in that context the `required=True` expectations (`execution_mode`, `wall_time_ms`, `llm_call_count`, `peak_memory_bytes`, `submitted_code_chars`) must all be present. The `required=True` default would be wrong for a general test suite where tracing is not always activated. This design matches the "fail if present but wrong, skip if absent unless required" semantics described for `ReplTraceExpectation`.

### Decision 8: Verbose xmode tracebacks go to stderr, not to `ParsedLog`

`RLM_REPL_XMODE=Verbose` causes IPython to emit local variable dumps to stderr when REPL code raises. These are not tagged lines and cannot be parsed by `parse_stdout()`. The design documents this explicitly: `parse_stdout()` operates on stdout only, and `result.repl_stderr` is attached to the `AssertionError` message as raw text. A future revision may add `parse_stderr()` to extract variable names and values from Verbose tracebacks, but for the current design the raw text is sufficient for a debugging agent to locate the failure.

### Decision 9: Debug env vars use save/restore, not pytest fixtures

The three debug env vars (`RLM_REPL_TRACE`, `RLM_REPL_XMODE`, `RLM_REPL_DEBUG`) are set via `_set_debug_instrumentation_env()` / `_restore_debug_instrumentation_env()` rather than pytest fixtures. This keeps the env manipulation co-located with the fixture run call in the test body, making it explicit that the e2e architecture test deliberately enables non-default behavior. A session-scoped pytest fixture could share the saved env, but would obscure that these vars affect the global process environment.
