"""E2E test: Architecture introspection skill via thread bridge.

Exercises: skill loading (module-import) + thread-bridge child dispatch at depth=2 +
llm_query_batched fanout + dynamic instruction resolution + full observability pipeline.

Expanded fixture: 15 model calls, 4 tools x 3 depths (list_skills, load_skill,
execute_code, set_model_response at d0/d1/d2), llm_query_batched with 2 prompts.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from rlm_adk.state import depth_key
from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.expected_lineage import (
    build_skill_arch_test_lineage,
    run_all_assertions,
)
from tests_rlm_adk.provider_fake.instrumented_runner import (
    run_fixture_contract_instrumented,
)
from tests_rlm_adk.provider_fake.stdout_parser import parse_stdout

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "skill_arch_test.json"


def _combined_output(run_result) -> str:
    return run_result.repl_stdout + "\n" + run_result.instrumentation_log


def _state_json(run_result, key: str) -> dict[str, object]:
    raw = run_result.final_state.get(key)
    assert raw is not None, f"{key} missing from final_state"
    if isinstance(raw, str):
        return json.loads(raw)
    assert isinstance(raw, dict), f"{key} is not a dict/JSON string: {type(raw)!r}"
    return raw


@pytest.fixture(scope="module")
async def run_result(tmp_path_factory):
    """Run the fixture once, reuse across all tests in this module."""
    tmp_path = tmp_path_factory.mktemp("skill_arch")
    return await run_fixture_contract_instrumented(
        FIXTURE_PATH,
        traces_db_path=str(tmp_path / "traces.db"),
        tmpdir=str(tmp_path),
    )


class TestContractPasses:
    async def test_contract_passes(self, run_result):
        assert run_result.contract.passed, run_result.contract.diagnostics()


class TestArchitectureLineage:
    async def test_full_lineage(self, run_result):
        combined = _combined_output(run_result)
        log = parse_stdout(combined)
        lineage = build_skill_arch_test_lineage()
        report = run_all_assertions(log, lineage)
        if not report.passed:
            extra = ""
            if hasattr(run_result, "repl_stderr") and run_result.repl_stderr:
                extra = f"\n\n--- REPL stderr (Verbose xmode) ---\n{run_result.repl_stderr}"
            pytest.fail(report.format_report() + extra)


class TestDynamicInstruction:
    async def test_no_unresolved_placeholders(self, run_result):
        si = run_result.final_state.get("_captured_system_instruction_0", "")
        assert si, "No system instruction captured by dyn_instr_capture_hook"
        for placeholder in [
            "{repo_url?}",
            "{root_prompt?}",
            "{test_context?}",
            "{skill_instruction?}",
            "{user_ctx_manifest?}",
        ]:
            assert placeholder not in si, f"Unresolved placeholder: {placeholder}"

    async def test_resolved_values_present(self, run_result):
        """Verify resolved placeholder values appear in DYN_INSTR tags."""
        combined = _combined_output(run_result)
        # DYN_INSTR tags confirm dynamic instruction resolution occurred
        assert "DYN_INSTR:repo_url=resolved=True" in combined, "repo_url not resolved"
        assert "DYN_INSTR:user_ctx_manifest=resolved=True" in combined, "user_ctx_manifest not resolved"
        assert "DYN_INSTR:skill_instruction=resolved=True" in combined, "skill_instruction not resolved"
        # Verify the actual repo URL value appeared in preview
        assert "test.example.com/depth2-batched" in combined, "repo_url preview value not found"


class TestSqliteTelemetry:
    async def test_traces_completed(self, run_result):
        """Verify traces.status = 'completed' and total_calls >= 15."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute("SELECT status, total_calls FROM traces LIMIT 1").fetchone()
            assert row and row[0] == "completed", f"traces.status = {row}"
            assert row[1] >= 15, f"total_calls = {row[1]}, expected >= 15"
        finally:
            conn.close()

    async def test_execute_code_telemetry(self, run_result):
        """Verify execute_code tool telemetry rows exist with repl_llm_calls >= 1."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT repl_llm_calls FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='execute_code' LIMIT 1"
            ).fetchone()
            assert row and row[0] >= 1, f"repl_llm_calls = {row}"
        finally:
            conn.close()

    async def test_max_depth_reached(self, run_result):
        """Verify max_depth_reached >= 2 in traces table (proves grandchild at d2 ran)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT max_depth_reached FROM traces LIMIT 1"
            ).fetchone()
            if row and row[0] is not None:
                val = row[0]
                if isinstance(val, str):
                    val = int(val)
                assert val >= 2, f"max_depth_reached = {val}, expected >= 2"
            else:
                pytest.skip("max_depth_reached column not present in traces table")
        finally:
            conn.close()

    async def test_tool_invocation_summary(self, run_result):
        """Verify tool_invocation_summary contains execute_code and set_model_response."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT tool_invocation_summary FROM traces LIMIT 1"
            ).fetchone()
            if row and row[0] is not None:
                summary = row[0]
                if isinstance(summary, str):
                    summary = json.loads(summary)
                assert "execute_code" in summary, f"execute_code not in tool_invocation_summary: {summary}"
                assert "set_model_response" in summary, f"set_model_response not in tool_invocation_summary: {summary}"
            else:
                pytest.skip("tool_invocation_summary column not present in traces table")
        finally:
            conn.close()


class TestSetModelResponseDepth:
    """BUG-014: Verify set_model_response tool_call rows in SQLite have correct depth values.

    The fixture has set_model_response calls at depth=0 (root, call_index=14),
    depth=1 (child at call_index=10, batch children at call_index=12,13),
    and depth=2 (grandchild at call_index=9).
    """

    async def test_smr_depth_nonzero_exists(self, run_result):
        """At least one set_model_response tool_call row must have depth > 0."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT depth FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='set_model_response'"
            ).fetchall()
            depths = [r[0] for r in rows]
            assert len(depths) >= 4, (
                f"Expected >= 4 set_model_response rows, got {len(depths)}: {depths}"
            )
            nonzero = [d for d in depths if d and int(d) > 0]
            assert len(nonzero) >= 1, (
                f"BUG-014: All set_model_response tool_call depths are 0. "
                f"Depths: {depths}. Child/grandchild SMR calls should have depth > 0."
            )
        finally:
            conn.close()

    async def test_smr_depth2_exists(self, run_result):
        """The grandchild set_model_response at depth=2 must be recorded with depth=2."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT depth, agent_name FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='set_model_response'"
            ).fetchall()
            depth_set = {int(r[0]) for r in rows if r[0] is not None}
            assert 2 in depth_set, (
                f"BUG-014: depth=2 not found in set_model_response tool_call rows. "
                f"Rows: {[(r[0], r[1]) for r in rows]}"
            )
        finally:
            conn.close()

    async def test_smr_depth_distribution(self, run_result):
        """Verify set_model_response depths include 0, 1, and 2."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT depth FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='set_model_response'"
            ).fetchall()
            depth_set = {int(r[0]) for r in rows if r[0] is not None}
            assert depth_set >= {0, 1, 2}, (
                f"BUG-014: Expected depths {{0, 1, 2}} in set_model_response rows, "
                f"got {depth_set}"
            )
        finally:
            conn.close()


class TestDepthScopedState:
    """Verify depth-scoped state keys appear in session_state_events via child event re-emission."""

    async def test_depth1_state_keys(self, run_result):
        """Verify depth=1 state keys exist in session_state_events."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT state_key FROM session_state_events WHERE key_depth = 1"
            ).fetchall()
            keys = [r[0] for r in rows]
            assert len(keys) > 0, (
                "No depth=1 state keys found in session_state_events. "
                "Child event re-emission may not be working."
            )
            assert "current_depth" in keys, (
                f"current_depth at key_depth=1 not found. Keys at d1: {keys}"
            )
        finally:
            conn.close()

    async def test_depth2_state_keys(self, run_result):
        """Verify depth=2 state keys exist (proves grandchild events bubbled up)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT state_key FROM session_state_events WHERE key_depth = 2"
            ).fetchall()
            keys = [r[0] for r in rows]
            assert len(keys) > 0, (
                "No depth=2 state keys found in session_state_events. "
                "Two-stage child event re-emission (d2 -> d1 -> d0) may not be working."
            )
        finally:
            conn.close()

    async def test_iteration_count_at_root(self, run_result):
        """Verify iteration_count=3 at depth=0 (three execute_code calls)."""
        assert run_result.final_state.get("iteration_count") == 3, (
            f"iteration_count = {run_result.final_state.get('iteration_count')}, expected 3"
        )


class TestChildEventReemission:
    """Verify child events reached parent session via re-emission queue."""

    async def test_child_events_have_correct_authors(self, run_result):
        """Verify child state events have distinct event_author values."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT event_author FROM session_state_events "
                "WHERE key_depth > 0"
            ).fetchall()
            authors = [r[0] for r in rows if r[0]]
            assert len(authors) > 0, (
                "No child event authors found in session_state_events with key_depth > 0"
            )
        finally:
            conn.close()

    async def test_depth2_final_response_text(self, run_result):
        """Verify the grandchild's final response text bubbled into state/events/stdout."""
        assert run_result.traces_db_path
        d2_text = run_result.final_state.get("final_response_text@d2f0")
        assert isinstance(d2_text, str) and d2_text, "final_response_text@d2f0 missing"
        d2_reasoning = _state_json(run_result, "reasoning_output@d2f0")
        assert d2_reasoning.get("final_answer") == d2_text, (
            f"Grandchild reasoning_output final_answer {d2_reasoning!r} "
            f"did not match final_response_text@d2f0={d2_text!r}"
        )
        d1_stdout = run_result.final_state.get("last_repl_result@d1f0", {}).get("stdout", "")
        assert f"grandchild_said={d2_text}" in d1_stdout, (
            "Depth-1 REPL stdout did not echo the depth-2 response text. "
            f"d1 stdout: {d1_stdout!r}"
        )
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT value_text FROM session_state_events "
                "WHERE state_key = 'final_response_text' AND key_depth = 2"
            ).fetchall()
            assert len(rows) > 0, "No final_response_text at key_depth=2"
            assert any(row[0] == d2_text for row in rows), (
                "Depth-2 final_response_text event rows did not contain the depth-2 "
                f"state value {d2_text!r}. Rows: {rows!r}"
            )
        finally:
            conn.close()


class TestBatchedDispatch:
    """Verify llm_query_batched produced correct results observable in stdout."""

    async def test_batch_count_in_stdout(self, run_result):
        """Verify 'batch_count=2' appears in REPL stdout."""
        combined = _combined_output(run_result)
        assert "batch_count=2" in combined, (
            "batch_count=2 not found in stdout. "
            "llm_query_batched may not have returned 2 results."
        )

    async def test_batch_results_in_stdout(self, run_result):
        """Verify both batch results surfaced as structured payloads in REPL stdout."""
        combined = _combined_output(run_result)
        assert "batch_0=" in combined, "batch_0 result not found in stdout"
        assert "batch_1=" in combined, "batch_1 result not found in stdout"
        assert '"summary"' in combined, "summary field not found in batch stdout"
        assert '"confidence"' in combined, "confidence field not found in batch stdout"

    async def test_turn2_iteration_count(self, run_result):
        """Verify turn2 code read iteration_count=2 from _rlm_state."""
        combined = _combined_output(run_result)
        assert "turn2_iteration_count=2" in combined, (
            "turn2_iteration_count=2 not found in stdout. "
            "Either _rlm_state snapshot was wrong or second execute_code didn't increment."
        )

    async def test_turn1_variable_persisted(self, run_result):
        """Verify that the 'result' variable from Turn 1 persists into Turn 2 REPL namespace."""
        combined = _combined_output(run_result)
        assert "turn1_skill_result_persisted=True" in combined, (
            "turn1_skill_result_persisted=True not found in stdout. "
            "REPL namespace may not persist across execute_code calls."
        )

    async def test_depth2_result_propagates_into_child_stdout(self, run_result):
        """Verify the actual depth-2 final answer propagated into the depth-1 REPL output."""
        combined = _combined_output(run_result)
        d2_text = run_result.final_state.get("final_response_text@d2f0")
        assert isinstance(d2_text, str) and d2_text, "final_response_text@d2f0 missing"
        assert f"grandchild_said={d2_text}" in combined, (
            "The depth-1 REPL stdout did not include the depth-2 final answer. "
            "The thread-bridge return path may be broken."
        )


class TestSkillToolsetDiscovery:
    """Verify SkillToolset list_skills/load_skill telemetry rows exist at multiple depths.

    Proves GAP-A fix: children (d1, d2) receive SkillToolset and can call
    list_skills and load_skill, not just the root reasoning agent.
    """

    async def test_list_skills_telemetry_exists(self, run_result):
        """At least one telemetry row with tool_name='list_skills' exists."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='list_skills'"
            ).fetchone()
            assert rows and rows[0] >= 1, (
                f"No list_skills tool_call rows found in telemetry. "
                f"SkillToolset may not be wired or telemetry not recording list_skills calls."
            )
        finally:
            conn.close()

    async def test_load_skill_telemetry_exists(self, run_result):
        """At least one telemetry row with tool_name='load_skill' exists."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='load_skill'"
            ).fetchone()
            assert rows and rows[0] >= 1, (
                f"No load_skill tool_call rows found in telemetry. "
                f"SkillToolset may not be wired or telemetry not recording load_skill calls."
            )
        finally:
            conn.close()

    async def test_list_skills_at_multiple_depths(self, run_result):
        """list_skills telemetry rows exist at depth=0 AND at depth > 0 (proves GAP-A fix)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT depth FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='list_skills'"
            ).fetchall()
            depths = {int(r[0]) for r in rows if r[0] is not None}
            assert 0 in depths, (
                f"list_skills not recorded at depth=0. Depths found: {depths}"
            )
            assert 2 in depths, (
                f"GAP-A: list_skills not recorded at depth=2. "
                f"Grandchild may not have SkillToolset. Depths: {depths}"
            )
        finally:
            conn.close()

    async def test_load_skill_at_multiple_depths(self, run_result):
        """load_skill telemetry rows exist at depth=0 AND at depth=2."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT depth FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='load_skill'"
            ).fetchall()
            depths = {int(r[0]) for r in rows if r[0] is not None}
            assert 0 in depths, (
                f"load_skill not recorded at depth=0. Depths found: {depths}"
            )
            assert 2 in depths, (
                f"GAP-A: load_skill not recorded at depth=2. "
                f"Grandchild may not have SkillToolset. Depths: {depths}"
            )
        finally:
            conn.close()


class TestDepth2StateVerification:
    """Verify the d2 execute_code (idx 8) printed state verification markers.

    The grandchild at depth=2 reads _rlm_state and prints [D2_STATE:key=value]
    markers. These are captured in final_state['last_repl_result@d2f0']['stdout']
    because child event re-emission writes depth-scoped state keys.
    """

    @staticmethod
    def _d2_stdout(run_result) -> str:
        """Extract d2 REPL stdout from depth-scoped last_repl_result@d2f0."""
        lrr = run_result.final_state.get("last_repl_result@d2f0")
        if isinstance(lrr, dict):
            return lrr.get("stdout", "")
        return ""

    async def test_d2_repl_result_exists(self, run_result):
        """last_repl_result@d2f0 must exist in final_state (proves child event re-emission)."""
        lrr = run_result.final_state.get("last_repl_result@d2f0")
        assert lrr is not None, (
            "last_repl_result@d2f0 not in final_state — "
            "child event re-emission (d2 -> d1 -> d0) may be broken."
        )

    async def test_d2_state_markers_in_stdout(self, run_result):
        """At least one [D2_STATE: prefixed line exists in d2 REPL stdout."""
        d2_out = self._d2_stdout(run_result)
        assert "[D2_STATE:" in d2_out, (
            "[D2_STATE: markers not found in last_repl_result@d2f0 stdout. "
            "The grandchild execute_code at idx 8 may not have run or its output was lost. "
            f"last_repl_result@d2f0 = {run_result.final_state.get('last_repl_result@d2f0')!r}"
        )

    async def test_d2_depth_correct(self, run_result):
        """[D2_STATE:depth=2] proves _rlm_depth=2 was in _rlm_state at d2."""
        d2_out = self._d2_stdout(run_result)
        assert "[D2_STATE:depth=2]" in d2_out, (
            "[D2_STATE:depth=2] not found in last_repl_result@d2f0 stdout. "
            "Either _rlm_depth was not propagated to depth=2 or the grandchild REPL "
            f"did not execute idx 8 code. d2 stdout: {d2_out[:200]!r}"
        )

    async def test_d2_has_current_depth(self, run_result):
        """[D2_STATE:current_depth= in d2 stdout. Value may be MISSING (not depth-scoped to children)."""
        d2_out = self._d2_stdout(run_result)
        assert "[D2_STATE:current_depth=" in d2_out, (
            "[D2_STATE:current_depth= not found in last_repl_result@d2f0 stdout. "
            f"d2 stdout: {d2_out[:200]!r}"
        )

    async def test_d2_runtime_state_shape(self, run_result):
        """Depth-2 stdout should report runtime-derived state shape, not a canned proof string."""
        d2_out = self._d2_stdout(run_result)
        key_count_match = re.search(r"\[D2_STATE:key_count=(\d+)\]", d2_out)
        assert key_count_match, (
            "Depth-2 stdout did not report state key count. "
            f"d2 stdout: {d2_out[:200]!r}"
        )
        assert int(key_count_match.group(1)) >= 5, (
            f"Depth-2 state key count too small: {key_count_match.group(1)}. "
            f"d2 stdout: {d2_out[:200]!r}"
        )
        assert "[D2_STATE:has_skill_instruction=True]" in d2_out, (
            "Depth-2 state did not report skill_instruction in _rlm_state. "
            f"d2 stdout: {d2_out[:200]!r}"
        )
        assert "[D2_STATE:has_user_ctx_manifest=True]" in d2_out, (
            "Depth-2 state did not report user_ctx_manifest in _rlm_state. "
            f"d2 stdout: {d2_out[:200]!r}"
        )
        assert "[D2_STATE:resolved_dyn_keys=['skill_instruction']]" in d2_out, (
            "Depth-2 stdout did not report the resolved dynamic-instruction keys. "
            f"d2 stdout: {d2_out[:200]!r}"
        )

    async def test_d2_dyn_instr_skill_instruction_resolved(self, run_result):
        """D2_STATE:dyn_instr_skill_instruction=resolved=True proves skill_instruction propagates to d2."""
        d2_out = self._d2_stdout(run_result)
        assert "D2_STATE:dyn_instr_skill_instruction=resolved=True" in d2_out, (
            "D2_STATE:dyn_instr_skill_instruction=resolved=True not found in d2 stdout. "
            "The skill_instruction state key may not propagate to depth=2. "
            f"d2 stdout: {d2_out[:200]!r}"
        )


class TestStructuredOutputCoverage:
    """Verify structured output via output_schema=BatchResult on llm_query_batched.

    Subsumes structured_output_happy_path fixture: exercises output_schema on
    llm_query_batched at idx 11, with BatchResult schema validated by children
    at idx 12 and idx 13.
    """

    async def test_structured_output_marker_in_stdout(self, run_result):
        """Verify [STRUCTURED_OUTPUT: markers appear in combined stdout."""
        combined = _combined_output(run_result)
        assert "[STRUCTURED_OUTPUT:" in combined, (
            "[STRUCTURED_OUTPUT: marker not found in stdout. "
            "The llm_query_batched(output_schema=BatchResult) code at idx 11 "
            "may not have executed or the parsed results were None."
        )

    async def test_structured_output_parsed_results(self, run_result):
        """Verify both batch results have parsed=True and accessible fields."""
        combined = _combined_output(run_result)
        assert "[STRUCTURED_OUTPUT:batch_0_parsed=True]" in combined, (
            "batch_0_parsed=True not found — child 0 structured output not parsed"
        )
        assert "[STRUCTURED_OUTPUT:batch_1_parsed=True]" in combined, (
            "batch_1_parsed=True not found — child 1 structured output not parsed"
        )

    async def test_structured_output_runtime_shape(self, run_result):
        """Verify parsed structured outputs have the expected runtime shape and value ranges.

        Turn 2 produced BatchResult(summary, confidence) at @d1f0/@d1f1.
        Turn 3's combo dispatch overwrites those keys:
          - llm_query_batched(3) writes NumberClassification to @d1f0, @d1f1, @d1f2
          - llm_query(1) (delegates to batched k=1) overwrites @d1f0 with AggregateReport
        Final state: @d1f0=AggregateReport, @d1f1=NumberClassification, @d1f2=NumberClassification.
        Turn 2 stdout markers still verify the BatchResult parsing worked.
        """
        combined = _combined_output(run_result)
        # Turn 2 stdout markers (not overwritten by state changes)
        assert "[STRUCTURED_OUTPUT:parsed_count=2]" in combined, (
            "parsed_count=2 not found — batched structured outputs were not both parsed"
        )
        assert "[STRUCTURED_OUTPUT:unique_summary_count=2]" in combined, (
            "unique_summary_count=2 not found — sibling structured outputs may have clobbered"
        )
        assert "[STRUCTURED_OUTPUT:all_confidences_in_range=True]" in combined, (
            "Confidence range marker not found — parsed confidence values were not usable"
        )

        # Turn 3 combo dispatch overwrote @d1f0 with AggregateReport (single llm_query)
        agg = _state_json(run_result, "reasoning_output@d1f0")
        assert set(agg) == {"total_numbers", "even_count", "positive_count", "value_sum", "verdict"}, (
            f"@d1f0 should be AggregateReport from combo single dispatch, got: {agg!r}"
        )
        assert agg["total_numbers"] == 3
        assert isinstance(agg["verdict"], str) and agg["verdict"]

        # Turn 3 batch children wrote NumberClassification to @d1f1, @d1f2
        for key in ("reasoning_output@d1f1", "reasoning_output@d1f2"):
            nc = _state_json(run_result, key)
            assert set(nc) == {"even_number", "value", "positive"}, (
                f"{key} should be NumberClassification, got: {nc!r}"
            )
            assert isinstance(nc["value"], int), f"value not int: {nc!r}"
            assert isinstance(nc["even_number"], bool), f"even_number not bool: {nc!r}"
            assert isinstance(nc["positive"], bool), f"positive not bool: {nc!r}"


class TestFanoutScoping:
    """Verify fanout scoping: batch children at the same depth get independent state keys.

    The two batch children at depth=1 (idx 12, 13) produce distinct
    fanout-scoped state keys (e.g. iteration_count@d1f0 vs @d1f1).
    The root's execute_code at idx 11 also prints depth_key() output
    to prove the function is accessible in REPL globals.
    """

    async def test_depth_key_used_for_runtime_fanout_scoping(self, run_result):
        """Verify depth_key() ran in REPL code and its computed keys line up with sibling state.

        Note: repl_submitted_code stores only the latest code (Turn 3 combo dispatch).
        depth_key() was used in Turn 2, so we verify via cumulative stdout markers.
        """
        combined = _combined_output(run_result)
        last_repl = run_result.final_state.get("last_repl_result", {})
        assert isinstance(last_repl, dict) and last_repl.get("has_errors") is False, (
            f"Root last_repl_result indicates REPL failure: {last_repl!r}"
        )
        expected_keys = [depth_key("iteration_count", 1, i) for i in range(2)]
        # Turn 2 stdout markers prove depth_key() was invoked
        assert "[FANOUT_SCOPE:key_count=2]" in combined, (
            "REPL code did not report fanout key generation across both batch results"
        )
        assert "[FANOUT_SCOPE:unique_keys=True]" in combined, (
            "Computed fanout keys were not unique"
        )
        assert "[FANOUT_SCOPE:all_depth_scoped=True]" in combined, (
            "Computed fanout keys were not depth-scoped"
        )
        for key in expected_keys:
            assert key in run_result.final_state, f"{key} missing from final_state"
            assert key in combined, f"{key} missing from REPL fanout-scope output"

    async def test_batch_children_write_distinct_state_keys(self, run_result):
        """Batch child 0 writes @d1f0 keys, child 1 writes @d1f1 — no clobbering."""
        state = run_result.final_state
        # Both batch children's orchestrators emit initial state with
        # iteration_count@d1fN via EventActions(state_delta=...), which is
        # re-emitted through the child_event_queue and applied to session state.
        f0_key = "iteration_count@d1f0"
        f1_key = "iteration_count@d1f1"
        assert f0_key in state, (
            f"{f0_key} not in final_state — batch child 0 (fanout_idx=0) "
            "did not write its fanout-scoped initial state, or child event "
            f"re-emission dropped the key. Keys with '@d1': "
            f"{[k for k in state if '@d1' in str(k)]}"
        )
        assert f1_key in state, (
            f"{f1_key} not in final_state — batch child 1 (fanout_idx=1) "
            "did not write its fanout-scoped initial state, or child event "
            f"re-emission dropped the key. Keys with '@d1': "
            f"{[k for k in state if '@d1' in str(k)]}"
        )

    async def test_batch_children_state_keys_independent(self, run_result):
        """Sibling state keys coexist — both should_stop@d1f0 and @d1f1 are present."""
        state = run_result.final_state
        for base_key in ("should_stop", "final_response_text"):
            f0 = f"{base_key}@d1f0"
            f1 = f"{base_key}@d1f1"
            assert f0 in state, f"{f0} missing from final_state"
            assert f1 in state, f"{f1} missing from final_state"

    async def test_old_depth_format_absent(self, run_result):
        """Regression guard: old @dN format (without fM suffix) must NOT exist in final_state.

        The system now always generates @dNfM format (e.g. iteration_count@d1f0).
        A regression that wrote both old and new formats would pass all positive
        assertions silently. This test ensures the old format is absent.
        """
        state = run_result.final_state
        old_format_keys = [
            "iteration_count",
            "current_depth",
            "should_stop",
            "final_response_text",
            "last_repl_result",
        ]
        for base_key in old_format_keys:
            old_key = f"{base_key}@d1"
            new_f0 = depth_key(base_key, 1, 0)
            assert old_key not in state, (
                f"Regression: old format key '{old_key}' found in final_state. "
                f"The system should only write new format keys like '{new_f0}'. "
                f"Keys matching '@d1' in state: "
                f"{[k for k in state if '@d1' in str(k)]}"
            )
