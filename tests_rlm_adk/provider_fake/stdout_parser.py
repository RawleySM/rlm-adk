"""stdout_parser.py — parse tagged diagnostic lines from instrumented pipeline runs.

Location: tests_rlm_adk/provider_fake/stdout_parser.py
"""

from __future__ import annotations

import dataclasses
import re

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

        matched_any = False

        # TEST_SKILL
        for m in _TEST_SKILL_RE.finditer(line):
            test_skill[m.group(1)] = m.group(2)
            matched_any = True

        # PLUGIN
        for m in _PLUGIN_RE.finditer(line):
            plugin_entries.append(PluginEntry(
                hook=m.group(1),
                agent_name=m.group(2),
                key=m.group(3),
                value=m.group(4),
                line_number=lineno,
            ))
            matched_any = True

        # CALLBACK
        for m in _CALLBACK_RE.finditer(line):
            callback_entries.append(CallbackEntry(
                hook=m.group(1),
                agent_name=m.group(2),
                key=m.group(3),
                value=m.group(4),
                line_number=lineno,
            ))
            matched_any = True

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
            matched_any = True

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
            matched_any = True

        # DYN_INSTR
        for m in _DYN_INSTR_RE.finditer(line):
            dyn_instr[m.group(1)] = m.group(2)
            matched_any = True

        # REPL_TRACE
        for m in _REPL_TRACE_RE.finditer(line):
            repl_trace_entries.append(ReplTraceEntry(
                key=m.group(1),
                value=m.group(2),
                line_number=lineno,
            ))
            matched_any = True

        # Detect partially-matching malformed lines
        if not matched_any and _ALL_TAG_PREFIXES.search(line):
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
