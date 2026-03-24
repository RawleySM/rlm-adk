"""Unit tests for stdout_parser.py — tagged line parsing from instrumented runs."""

from tests_rlm_adk.provider_fake.stdout_parser import ParsedLog, parse_stdout


class TestParseTestSkillTags:
    """[TEST_SKILL:key=value] parsing."""

    def test_single_tag(self):
        log = parse_stdout("[TEST_SKILL:depth=0]")
        assert log.test_skill == {"depth": "0"}

    def test_multiple_tags(self):
        log = parse_stdout("[TEST_SKILL:depth=0]\n[TEST_SKILL:mode=thread_bridge]")
        assert log.test_skill["depth"] == "0"
        assert log.test_skill["mode"] == "thread_bridge"

    def test_last_value_wins_on_duplicate_key(self):
        log = parse_stdout("[TEST_SKILL:depth=0]\n[TEST_SKILL:depth=1]")
        assert log.test_skill["depth"] == "1"

    def test_empty_value(self):
        log = parse_stdout("[TEST_SKILL:key=]")
        assert log.test_skill["key"] == ""

    def test_value_with_special_chars(self):
        log = parse_stdout(
            "[TEST_SKILL:summary=depth=0 mode=thread_bridge latency_ms=45.2]"
        )
        assert "depth=0" in log.test_skill["summary"]

    def test_boolean_value(self):
        log = parse_stdout("[TEST_SKILL:COMPLETE=True]")
        assert log.test_skill["COMPLETE"] == "True"


class TestParsePluginEntries:
    """[PLUGIN:hook:agent:key=value] parsing."""

    def test_basic_plugin_entry(self):
        log = parse_stdout("[PLUGIN:before_agent:reasoning_agent:depth=0]")
        assert len(log.plugin_entries) == 1
        e = log.plugin_entries[0]
        assert e.hook == "before_agent"
        assert e.agent_name == "reasoning_agent"
        assert e.key == "depth"
        assert e.value == "0"
        assert e.line_number == 1

    def test_multiple_plugin_entries(self):
        stdout = (
            "[PLUGIN:before_agent:rlm_orchestrator:depth=0]\n"
            "[PLUGIN:before_model:reasoning_agent:call_num=1]\n"
            "[PLUGIN:after_model:reasoning_agent:finish_reason=STOP]"
        )
        log = parse_stdout(stdout)
        assert len(log.plugin_entries) == 3
        assert log.plugin_entries[1].key == "call_num"

    def test_line_numbers_preserved(self):
        stdout = "some text\n[PLUGIN:before_agent:agent_a:key=val]"
        log = parse_stdout(stdout)
        assert log.plugin_entries[0].line_number == 2


class TestParseCallbackEntries:
    """[CALLBACK:hook:agent:key=value] parsing."""

    def test_basic_callback(self):
        log = parse_stdout(
            "[CALLBACK:before_model:reasoning_agent:depth=0,fanout=0,iteration=0]"
        )
        assert len(log.callback_entries) == 1
        e = log.callback_entries[0]
        assert e.hook == "before_model"
        assert e.agent_name == "reasoning_agent"
        assert e.key == "depth"
        # value includes everything after first = up to ]
        assert "0,fanout=0,iteration=0" in e.value


class TestParseStateEntries:
    """[STATE:scope:key=value] parsing with last-colon splitting."""

    def test_scoped_state_entry(self):
        log = parse_stdout("[STATE:model_call_1:iteration_count=0]")
        assert len(log.state_entries) == 1
        e = log.state_entries[0]
        assert e.scope == "model_call_1"
        assert e.key == "iteration_count"
        assert e.value == "0"

    def test_nested_scope(self):
        log = parse_stdout("[STATE:before_agent:repl_did_expand=True]")
        e = log.state_entries[0]
        assert e.scope == "before_agent"
        assert e.key == "repl_did_expand"
        assert e.value == "True"

    def test_scopeless_state_entry(self):
        log = parse_stdout("[STATE:iteration_count=5]")
        e = log.state_entries[0]
        assert e.scope == ""
        assert e.key == "iteration_count"
        assert e.value == "5"

    def test_complex_scope_with_colons(self):
        log = parse_stdout("[STATE:pre_tool:obs:rewrite_count=3]")
        e = log.state_entries[0]
        # rsplit(":", 1) on "pre_tool:obs:rewrite_count" => ("pre_tool:obs", "rewrite_count")
        assert e.scope == "pre_tool:obs"
        assert e.key == "rewrite_count"


class TestParseTimingEntries:
    """[TIMING:label=ms] parsing."""

    def test_valid_timing(self):
        log = parse_stdout("[TIMING:model_call_1_ms=12.4]")
        assert len(log.timing_entries) == 1
        assert log.timing_entries[0].label == "model_call_1_ms"
        assert log.timing_entries[0].value_ms == 12.4

    def test_invalid_timing_value(self):
        log = parse_stdout("[TIMING:broken_ms=not_a_number]")
        assert log.timing_entries[0].value_ms == -1.0
        assert log.timing_entries[0].raw == "not_a_number"

    def test_negative_timing(self):
        log = parse_stdout("[TIMING:agent_ms=-1]")
        assert log.timing_entries[0].value_ms == -1.0


class TestParseDynInstr:
    """[DYN_INSTR:key=value] parsing."""

    def test_basic_dyn_instr(self):
        log = parse_stdout("[DYN_INSTR:repo_url=resolved=True]")
        assert log.dyn_instr["repo_url"] == "resolved=True"

    def test_multiple_dyn_instr(self):
        stdout = (
            "[DYN_INSTR:repo_url=resolved=True]\n"
            "[DYN_INSTR:user_ctx_keys=['a.txt', 'b.txt']]"
        )
        log = parse_stdout(stdout)
        assert len(log.dyn_instr) == 2


class TestParseReplTrace:
    """[REPL_TRACE:key=value] parsing."""

    def test_basic_repl_trace(self):
        log = parse_stdout("[REPL_TRACE:execution_mode=thread_bridge]")
        assert len(log.repl_trace_entries) == 1
        assert log.repl_trace_entries[0].key == "execution_mode"
        assert log.repl_trace_entries[0].value == "thread_bridge"

    def test_numeric_repl_trace(self):
        log = parse_stdout("[REPL_TRACE:wall_time_ms=45.7]")
        assert log.repl_trace_entries[0].value == "45.7"


class TestMalformedLines:
    """Malformed line detection."""

    def test_no_malformed_on_clean_input(self):
        log = parse_stdout("[TEST_SKILL:key=val]")
        assert log.malformed_lines == []

    def test_malformed_detected(self):
        # Has known prefix [TEST_SKILL: but doesn't match the regex pattern
        log = parse_stdout("[TEST_SKILL:]")
        assert len(log.malformed_lines) == 1

    def test_unknown_prefix_ignored(self):
        log = parse_stdout("[UNKNOWN_TAG:foo=bar]")
        assert log.malformed_lines == []


class TestEmptyAndMixedInput:
    """Edge cases: empty input, non-tagged lines, mixed content."""

    def test_empty_string(self):
        log = parse_stdout("")
        assert log.test_skill == {}
        assert log.plugin_entries == []
        assert log.malformed_lines == []

    def test_non_tagged_lines_ignored(self):
        log = parse_stdout("just some text\nanother line\n")
        assert log.test_skill == {}
        assert log.plugin_entries == []

    def test_mixed_tagged_and_plain(self):
        stdout = "init\n[TEST_SKILL:depth=0]\nmore text\n[TIMING:ms=1.0]"
        log = parse_stdout(stdout)
        assert log.test_skill["depth"] == "0"
        assert log.timing_entries[0].value_ms == 1.0

    def test_raw_stdout_preserved(self):
        raw = "some output\n[TEST_SKILL:x=1]"
        log = parse_stdout(raw)
        assert log.raw_stdout == raw


class TestParsedLogAccessors:
    """ParsedLog convenience methods."""

    def _make_log(self) -> ParsedLog:
        return parse_stdout(
            "[PLUGIN:before_agent:reasoning_agent:depth=0]\n"
            "[PLUGIN:before_model:reasoning_agent:call_num=1]\n"
            "[PLUGIN:before_agent:rlm_orchestrator:depth=0]\n"
            "[STATE:model_call_1:iteration_count=0]\n"
            "[STATE:model_call_1:should_stop=False]\n"
            "[STATE:pre_tool:iteration_count=1]\n"
            "[TIMING:agent_reasoning_agent_ms=50.0]\n"
            "[TIMING:model_call_1_ms=12.0]\n"
            "[REPL_TRACE:execution_mode=thread_bridge]\n"
            "[REPL_TRACE:wall_time_ms=100.5]\n"
            "[TEST_SKILL:depth=0]\n"
            "[TEST_SKILL:thread_bridge_latency_ms=45.2]\n"
            "[TEST_SKILL:COMPLETE=True]\n"
        )

    def test_plugin_hooks(self):
        log = self._make_log()
        hooks = log.plugin_hooks("before_agent")
        assert len(hooks) == 2

    def test_plugin_for_agent(self):
        log = self._make_log()
        entries = log.plugin_for_agent("before_agent", "reasoning_agent")
        assert len(entries) == 1
        assert entries[0].key == "depth"

    def test_state_at_scope(self):
        log = self._make_log()
        scope = log.state_at_scope("model_call_1")
        assert scope["iteration_count"] == "0"
        assert scope["should_stop"] == "False"

    def test_state_at_scope_empty(self):
        log = self._make_log()
        assert log.state_at_scope("nonexistent") == {}

    def test_timing_for(self):
        log = self._make_log()
        assert log.timing_for("agent_reasoning_agent_ms") == 50.0
        assert log.timing_for("nonexistent") is None

    def test_agent_names_seen(self):
        log = self._make_log()
        names = log.agent_names_seen()
        assert "reasoning_agent" in names
        assert "rlm_orchestrator" in names

    def test_repl_trace(self):
        log = self._make_log()
        trace = log.repl_trace()
        assert trace["execution_mode"] == "thread_bridge"
        assert trace["wall_time_ms"] == "100.5"

    def test_repl_trace_float(self):
        log = self._make_log()
        assert log.repl_trace_float("wall_time_ms") == 100.5
        assert log.repl_trace_float("nonexistent") is None

    def test_test_skill_float(self):
        log = self._make_log()
        assert log.test_skill_float("thread_bridge_latency_ms") == 45.2
        assert log.test_skill_float("depth") == 0.0
        assert log.test_skill_float("nonexistent") is None

    def test_test_skill_bool(self):
        log = self._make_log()
        assert log.test_skill_bool("COMPLETE") is True
        assert log.test_skill_bool("nonexistent") is None

    def test_test_skill_bool_false(self):
        log = parse_stdout("[TEST_SKILL:flag=false]")
        assert log.test_skill_bool("flag") is False


class TestRealisticStdout:
    """Parse a realistic multi-line stdout from an instrumented run."""

    REALISTIC = (
        "[PLUGIN:before_agent:rlm_orchestrator:depth=0]\n"
        "[PLUGIN:before_agent:rlm_orchestrator:fanout_idx=0]\n"
        "[PLUGIN:before_agent:rlm_orchestrator:agent_type=RLMOrchestratorAgent]\n"
        "[PLUGIN:before_model:reasoning_agent:call_num=1]\n"
        "[PLUGIN:before_model:reasoning_agent:model=gemini-fake]\n"
        "[STATE:model_call_1:iteration_count=0]\n"
        "[STATE:model_call_1:should_stop=False]\n"
        "[STATE:model_call_1:repl_did_expand=False]\n"
        "[PLUGIN:before_tool:reasoning_agent:tool_name=execute_code]\n"
        "[TEST_SKILL:depth=0]\n"
        "[TEST_SKILL:execution_mode=thread_bridge]\n"
        "[TEST_SKILL:COMPLETE=True]\n"
        "[DYN_INSTR:repo_url=resolved=True]\n"
        "[DYN_INSTR:user_ctx_keys=['arch_context.txt', 'test_metadata.json']]\n"
        "[PLUGIN:after_tool:reasoning_agent:tool_name=execute_code]\n"
        "[STATE:post_tool:repl_did_expand=True]\n"
        "[TIMING:tool_execute_code_ms=67.1]\n"
        "[PLUGIN:after_agent:rlm_orchestrator:elapsed_ms=312.7]\n"
        "[TIMING:agent_rlm_orchestrator_ms=312.7]\n"
        "[REPL_TRACE:execution_mode=thread_bridge]\n"
        "[REPL_TRACE:wall_time_ms=50.3]\n"
    )

    def test_all_families_parsed(self):
        log = parse_stdout(self.REALISTIC)
        assert len(log.test_skill) >= 3
        assert len(log.plugin_entries) >= 5
        assert len(log.state_entries) >= 4
        assert len(log.timing_entries) >= 2
        assert len(log.dyn_instr) >= 2
        assert len(log.repl_trace_entries) >= 2
        assert log.malformed_lines == []

    def test_state_transition_captured(self):
        log = parse_stdout(self.REALISTIC)
        pre = log.state_at_scope("model_call_1")
        post = log.state_at_scope("post_tool")
        assert pre.get("repl_did_expand") == "False"
        assert post.get("repl_did_expand") == "True"

    def test_test_skill_values(self):
        log = parse_stdout(self.REALISTIC)
        assert log.test_skill["depth"] == "0"
        assert log.test_skill["execution_mode"] == "thread_bridge"
        assert log.test_skill["COMPLETE"] == "True"

    def test_dyn_instr_parsed(self):
        log = parse_stdout(self.REALISTIC)
        assert log.dyn_instr["repo_url"] == "resolved=True"
        assert "arch_context.txt" in log.dyn_instr["user_ctx_keys"]
