"""E2E test: Architecture introspection skill via thread bridge.

Exercises: skill loading (module-import) + thread-bridge child dispatch at depth=2 +
llm_query_batched fanout + dynamic instruction resolution + full observability pipeline.

Expanded fixture: 8 model calls, 3 reasoning turns, depth=2 via llm_query chain,
llm_query_batched with 2 prompts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.diagnostic_dump import write_diagnostic_dump
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


@pytest.fixture
async def run_result(tmp_path: Path):
    """Run the fixture once, reuse across all tests in this module."""
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
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
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
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        # DYN_INSTR tags confirm dynamic instruction resolution occurred
        assert "DYN_INSTR:repo_url=resolved=True" in combined, "repo_url not resolved"
        assert "DYN_INSTR:user_ctx_manifest=resolved=True" in combined, "user_ctx_manifest not resolved"
        assert "DYN_INSTR:skill_instruction=resolved=True" in combined, "skill_instruction not resolved"
        # Verify the actual repo URL value appeared in preview
        assert "test.example.com/depth2-batched" in combined, "repo_url preview value not found"


class TestSqliteTelemetry:
    async def test_traces_completed(self, run_result):
        """Verify traces.status = 'completed' and total_calls >= 8."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute("SELECT status, total_calls FROM traces LIMIT 1").fetchone()
            assert row and row[0] == "completed", f"traces.status = {row}"
            assert row[1] >= 8, f"total_calls = {row[1]}, expected >= 8"
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

    The fixture has set_model_response calls at depth=0 (root, call_index=7),
    depth=1 (child at call_index=3, batch children at call_index=5,6),
    and depth=2 (grandchild at call_index=2).
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
        """Verify iteration_count=2 at depth=0 (two execute_code calls)."""
        assert run_result.final_state.get("iteration_count") == 2, (
            f"iteration_count = {run_result.final_state.get('iteration_count')}, expected 2"
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
        """Verify grandchild's final_response_text='depth2_leaf_ok' bubbled up."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT value_text FROM session_state_events "
                "WHERE state_key = 'final_response_text' AND key_depth = 2"
            ).fetchall()
            assert len(rows) > 0, "No final_response_text at key_depth=2"
            assert rows[0][0] == "depth2_leaf_ok", (
                f"Grandchild final_response_text = {rows[0][0]!r}, expected 'depth2_leaf_ok'"
            )
        finally:
            conn.close()


class TestBatchedDispatch:
    """Verify llm_query_batched produced correct results observable in stdout."""

    async def test_batch_count_in_stdout(self, run_result):
        """Verify 'batch_count=2' appears in REPL stdout."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "batch_count=2" in combined, (
            "batch_count=2 not found in stdout. "
            "llm_query_batched may not have returned 2 results."
        )

    async def test_batch_results_in_stdout(self, run_result):
        """Verify individual batch results appear in stdout."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "batch_0=" in combined, "batch_0 result not found in stdout"
        assert "batch_1=" in combined, "batch_1 result not found in stdout"
        assert "finding_A_summary" in combined, "finding_A_summary not found in stdout"
        assert "finding_B_summary" in combined, "finding_B_summary not found in stdout"

    async def test_turn2_iteration_count(self, run_result):
        """Verify turn2 code read iteration_count=2 from _rlm_state."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "turn2_iteration_count=2" in combined, (
            "turn2_iteration_count=2 not found in stdout. "
            "Either _rlm_state snapshot was wrong or second execute_code didn't increment."
        )

    async def test_turn1_variable_persisted(self, run_result):
        """Verify that the 'result' variable from Turn 1 persists into Turn 2 REPL namespace."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "turn1_skill_result_persisted=True" in combined, (
            "turn1_skill_result_persisted=True not found in stdout. "
            "REPL namespace may not persist across execute_code calls."
        )

    async def test_depth2_proof_in_stdout(self, run_result):
        """Verify depth2_leaf_ok flows through the depth=2 chain into root stdout."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "depth2_leaf_ok" in combined, (
            "depth2_leaf_ok not found in stdout. "
            "The depth=2 chain (root -> d1 execute_code -> d2 set_model_response -> d1 -> root) may be broken."
        )


class TestDiagnosticDump:
    """Data capture test: writes a comprehensive JSON diagnostic dump of the fixture run."""

    async def test_write_diagnostic_dump(self, run_result):
        """Write diagnostic dump to issues/dashboard/fixture_runtime_output.json.

        This test always passes -- it exists solely to capture runtime data.
        """
        output_path = write_diagnostic_dump(
            run_result,
            output_path="./issues/dashboard/fixture_runtime_output.json",
        )
        assert output_path.exists(), f"Diagnostic dump was not written to {output_path}"
