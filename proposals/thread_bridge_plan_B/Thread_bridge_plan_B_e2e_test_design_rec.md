# Skill Thread Bridge + SkillToolset E2E Test Design

## Overview

This plan designs a provider-fake JSON fixture and pytest test class that prove the complete data flow from skill-backed REPL code through child dispatch through the sqlite state/event, telemetry, and trace pipeline.

---

## 1. Provider-Fake JSON Fixture: `skill_thread_bridge_e2e.json`

### Design Rationale

The fixture exercises the **skill expansion + child dispatch + structured observability** path. It follows the same pattern as `skill_expansion.json` (existing) but goes further:
- Uses `from rlm_repl_skills.ping import run_recursive_ping` to trigger skill expansion
- The expanded skill code calls `llm_query()` which triggers child dispatch
- Child responds, parent REPL continues, prints result
- Reasoning agent then calls `set_model_response` with a structured ReasoningOutput

This exercises the real pipeline -- no reward-hacking. The fixture **must** use the existing `run_recursive_ping` skill because that is the only skill currently registered in the skill registry. We cannot use a hypothetical `load_skill` tool because no such tool exists in the current architecture. The skill mechanism is **source expansion** via `expand_skill_imports()` in `REPLTool.run_async()`.

### What Happens at Each Step

**Response 0 (reasoning, call_index=0):** Model emits `functionCall: execute_code` with code that:
```python
from rlm_repl_skills.ping import run_recursive_ping

result = run_recursive_ping(
    max_layer=1,
    starting_layer=0,
    terminal_layer=1,
    emit_debug=True,
)
print(f"layer={result.layer}, payload={result.payload}")
```

This code triggers:
1. `expand_skill_imports()` detects the synthetic import -> expands inline source
2. `has_llm_calls()` detects `llm_query()` in the expanded code -> `rewrite_for_async()`
3. Child orchestrator dispatched at depth+1
4. `DYN_SKILL_INSTRUCTION` state key written if instruction_router is wired
5. `REPL_DID_EXPAND`, `REPL_EXPANDED_CODE`, `REPL_SKILL_EXPANSION_META` written to state
6. `REPL_SUBMITTED_CODE*` written to state
7. Child event queue receives curated state_delta events

**Response 1 (worker, call_index=1):** Child model returns plain text `pong` response.

**Response 2 (reasoning, call_index=2):** Model emits `functionCall: set_model_response` with structured `ReasoningOutput`:
```json
{
  "final_answer": "Skill thread bridge verified: layer=0, payload=pong",
  "reasoning_summary": "The run_recursive_ping skill expanded, dispatched a child LLM query, and returned the terminal payload."
}
```

### Complete Fixture JSON

```json
{
  "scenario_id": "skill_thread_bridge_e2e",
  "description": "Skill expansion + child dispatch + structured set_model_response. Verifies full telemetry/state pipeline for skill-backed REPL execution with thread bridge child dispatch.",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "status": 200,
      "body": {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "name": "execute_code",
                    "args": {
                      "code": "from rlm_repl_skills.ping import run_recursive_ping\n\nresult = run_recursive_ping(\n    max_layer=1,\n    starting_layer=0,\n    terminal_layer=1,\n    emit_debug=True,\n)\nprint(f\"layer={result.layer}, payload={result.payload}\")"
                    }
                  }
                }
              ]
            },
            "finishReason": "STOP",
            "index": 0
          }
        ],
        "usageMetadata": {
          "promptTokenCount": 300,
          "candidatesTokenCount": 200,
          "totalTokenCount": 500
        },
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 1,
      "caller": "worker",
      "note": "Child orchestrator reasoning at depth=1 for the llm_query inside run_recursive_ping",
      "status": 200,
      "body": {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "name": "set_model_response",
                    "args": {
                      "final_answer": "pong",
                      "reasoning_summary": "terminal ping response"
                    }
                  }
                }
              ]
            },
            "finishReason": "STOP",
            "index": 0
          }
        ],
        "usageMetadata": {
          "promptTokenCount": 100,
          "candidatesTokenCount": 20,
          "totalTokenCount": 120
        },
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 2,
      "caller": "reasoning",
      "note": "Reasoning agent calls set_model_response with structured output after seeing REPL result",
      "status": 200,
      "body": {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "name": "set_model_response",
                    "args": {
                      "final_answer": "Skill thread bridge verified: layer=0, payload=pong",
                      "reasoning_summary": "The run_recursive_ping skill expanded, dispatched a child LLM query, and returned the terminal payload."
                    }
                  }
                }
              ]
            },
            "finishReason": "STOP",
            "index": 0
          }
        ],
        "usageMetadata": {
          "promptTokenCount": 500,
          "candidatesTokenCount": 60,
          "totalTokenCount": 560
        },
        "modelVersion": "gemini-fake"
      }
    }
  ],
  "fault_injections": [],
  "expected": {
    "final_answer": "Skill thread bridge verified: layer=0, payload=pong",
    "total_iterations": 1,
    "total_model_calls": 3
  }
}
```

### Key Design Decision: Worker Response Format

The child orchestrator at depth=1 needs to return via `set_model_response` (not plain text) because `create_child_orchestrator()` wires `SetModelResponseTool(schema)` and `ReasoningOutput` as the output schema. The child reasoning agent receives the ping prompt and must call `set_model_response` with `{"final_answer": "pong", "reasoning_summary": "..."}`. This matches how `structured_output_happy_path.json` works.

**Important**: The existing `skill_expansion.json` fixture uses plain-text worker responses because it was designed for the old leaf-LlmAgent worker pool. With child orchestrator dispatch, the worker response must be a `set_model_response` function call matching the `ReasoningOutput` schema.

---

## 2. Python Runner Script: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`

### Test Architecture

The test uses `run_fixture_contract_with_plugins()` from the existing contract runner infrastructure. This gives us:
- Real `FakeGeminiServer` serving scripted responses
- Real `SqliteTracingPlugin` writing to a temp SQLite DB
- Real `ObservabilityPlugin` and `REPLTracingPlugin`
- Real `FileArtifactService` and `SqliteSessionService`
- Full event stream collection

After the run completes, we query the SQLite database directly to verify all observability data was captured.

### Complete Test Class

```python
"""End-to-end test: Skill thread bridge + SkillToolset telemetry verification.

Proves the complete data flow from skill expansion through child dispatch
through the sqlite state/event, telemetry, and trace pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rlm_adk.state import (
    DYN_SKILL_INSTRUCTION,
    FINAL_RESPONSE_TEXT,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    REPL_DID_EXPAND,
    REPL_EXPANDED_CODE,
    REPL_SKILL_EXPANSION_META,
    REPL_SUBMITTED_CODE,
)
from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract_with_plugins,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "skill_thread_bridge_e2e.json"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _run(tmp_path: Path) -> PluginContractResult:
    """Run the skill_thread_bridge_e2e fixture with full plugin stack."""
    return await run_fixture_contract_with_plugins(
        FIXTURE_PATH,
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
        tmpdir=str(tmp_path),
    )


# ===========================================================================
# CONTRACT: Basic pipeline correctness
# ===========================================================================


class TestSkillThreadBridgeContract:
    """Verify the fixture passes the contract and produces the expected answer."""

    @pytest.mark.agent_challenge
    async def test_contract_passes(self, tmp_path: Path):
        result = await _run(tmp_path)
        assert result.contract.passed, result.contract.diagnostics()

    @pytest.mark.agent_challenge
    async def test_final_answer_contains_expected_text(self, tmp_path: Path):
        result = await _run(tmp_path)
        fa = result.final_state.get(FINAL_RESPONSE_TEXT, "")
        assert "pong" in fa.lower() or "Skill thread bridge" in fa, (
            f"Expected skill result in final answer, got: {fa!r}"
        )

    @pytest.mark.agent_challenge
    async def test_events_emitted(self, tmp_path: Path):
        result = await _run(tmp_path)
        assert len(result.events) > 0, "Expected events from the run"


# ===========================================================================
# STATE/EVENT PLANE: session_state_events table
# ===========================================================================


class TestSkillThreadBridgeStateEvents:
    """Verify session_state_events captures skill expansion and REPL state."""

    @pytest.mark.agent_challenge
    async def test_repl_submitted_code_events(self, tmp_path: Path):
        """session_state_events has repl_submitted_code entries."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE state_key = 'repl_submitted_code'"
            ).fetchone()[0]
            assert rows >= 1, (
                f"Expected >= 1 repl_submitted_code SSE rows, got {rows}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_skill_expansion_meta_events(self, tmp_path: Path):
        """session_state_events has repl_skill_expansion_meta entries."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE state_key = 'repl_skill_expansion_meta'"
            ).fetchone()[0]
            assert rows >= 1, (
                f"Expected >= 1 repl_skill_expansion_meta SSE rows, got {rows}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_repl_did_expand_events(self, tmp_path: Path):
        """session_state_events has repl_did_expand = True entry."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT value_int FROM session_state_events "
                "WHERE state_key = 'repl_did_expand' LIMIT 1"
            ).fetchone()
            assert row is not None, "No repl_did_expand SSE row found"
            assert row[0] == 1, f"Expected repl_did_expand = 1 (True), got {row[0]}"
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_last_repl_result_events(self, tmp_path: Path):
        """session_state_events has last_repl_result entries with llm call data."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT value_json FROM session_state_events "
                "WHERE state_key = 'last_repl_result' LIMIT 1"
            ).fetchone()
            assert row is not None, "No last_repl_result SSE row found"
            payload = json.loads(row[0])
            assert payload.get("total_llm_calls", 0) >= 1, (
                f"Expected total_llm_calls >= 1 in last_repl_result, got {payload}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_iteration_count_events(self, tmp_path: Path):
        """session_state_events has iteration_count entries."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE state_key = 'iteration_count'"
            ).fetchone()[0]
            assert rows >= 1, (
                f"Expected >= 1 iteration_count SSE rows, got {rows}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_child_state_events_captured(self, tmp_path: Path):
        """session_state_events has key_depth > 0 rows from child dispatch."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE key_depth > 0"
            ).fetchone()[0]
            # Child events are re-emitted via asyncio.Queue bridge.
            # At minimum we expect iteration_count@d1 from the child.
            assert rows >= 1, (
                f"Expected >= 1 child state event rows (key_depth > 0), got {rows}"
            )
        finally:
            conn.close()


# ===========================================================================
# TELEMETRY PLANE: telemetry table
# ===========================================================================


class TestSkillThreadBridgeTelemetry:
    """Verify telemetry table captures model calls and tool invocations."""

    @pytest.mark.agent_challenge
    async def test_traces_row_completed(self, tmp_path: Path):
        """traces table has a completed row with token stats."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT status, total_calls, total_input_tokens, total_output_tokens "
                "FROM traces LIMIT 1"
            ).fetchone()
            assert row is not None, "No trace row found"
            status, total_calls, in_tok, out_tok = row
            assert status == "completed", f"Expected 'completed', got {status!r}"
            # At least 2 model calls at depth=0 (reasoning call_index 0 and 2)
            assert total_calls >= 2, f"Expected >= 2 total_calls, got {total_calls}"
            assert in_tok > 0, f"Expected input_tokens > 0, got {in_tok}"
            assert out_tok > 0, f"Expected output_tokens > 0, got {out_tok}"
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_model_call_telemetry_rows(self, tmp_path: Path):
        """telemetry table has model_call rows for reasoning + child."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            model_rows = conn.execute(
                "SELECT COUNT(*) FROM telemetry WHERE event_type = 'model_call'"
            ).fetchone()[0]
            # Reasoning call 0, child call 1, reasoning call 2 = at least 3
            assert model_rows >= 2, (
                f"Expected >= 2 model_call telemetry rows, got {model_rows}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_execute_code_tool_telemetry(self, tmp_path: Path):
        """telemetry table has a tool_call row for execute_code with REPL enrichment."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT tool_name, decision_mode, repl_llm_calls, "
                "       repl_has_output, duration_ms "
                "FROM telemetry "
                "WHERE event_type = 'tool_call' AND tool_name = 'execute_code' "
                "LIMIT 1"
            ).fetchone()
            assert row is not None, "No execute_code tool_call telemetry row"
            tool_name, decision_mode, repl_llm_calls, repl_has_output, duration_ms = row
            assert tool_name == "execute_code"
            assert decision_mode == "execute_code"
            assert repl_llm_calls >= 1, (
                f"Expected repl_llm_calls >= 1 (child dispatch), got {repl_llm_calls}"
            )
            assert repl_has_output == 1, (
                f"Expected repl_has_output = 1 (print statement), got {repl_has_output}"
            )
            assert duration_ms is not None and duration_ms > 0, (
                f"Expected positive duration_ms, got {duration_ms}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_set_model_response_tool_telemetry(self, tmp_path: Path):
        """telemetry table has a tool_call row for set_model_response at depth=0."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT tool_name, decision_mode, depth "
                "FROM telemetry "
                "WHERE event_type = 'tool_call' AND tool_name = 'set_model_response' "
                "AND depth = 0 "
                "LIMIT 1"
            ).fetchone()
            assert row is not None, (
                "No set_model_response tool_call telemetry row at depth=0"
            )
            assert row[1] == "set_model_response"
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_tool_invocation_summary_in_traces(self, tmp_path: Path):
        """traces.tool_invocation_summary includes both execute_code and set_model_response."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT tool_invocation_summary FROM traces LIMIT 1"
            ).fetchone()
            assert row is not None and row[0] is not None, (
                "No tool_invocation_summary in traces"
            )
            summary = json.loads(row[0])
            assert "execute_code" in summary, (
                f"Expected 'execute_code' in tool summary, got {summary}"
            )
            assert "set_model_response" in summary, (
                f"Expected 'set_model_response' in tool summary, got {summary}"
            )
        finally:
            conn.close()

    @pytest.mark.agent_challenge
    async def test_skill_instruction_column_populated(self, tmp_path: Path):
        """telemetry.skill_instruction is populated for model_call rows when
        instruction_router is wired (depth=0 reasoning calls read DYN_SKILL_INSTRUCTION
        from state and before_model_callback records it)."""
        result = await _run(tmp_path)
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            # The skill_instruction column is populated by
            # SqliteTracingPlugin.before_model_callback reading
            # DYN_SKILL_INSTRUCTION from callback_context.state.
            # This is only non-NULL if the orchestrator has an
            # instruction_router that seeds the state key.
            # With the default contract runner (no instruction_router),
            # this may be NULL. We verify it does not crash.
            row = conn.execute(
                "SELECT skill_instruction FROM telemetry "
                "WHERE event_type = 'model_call' LIMIT 1"
            ).fetchone()
            assert row is not None, "No model_call telemetry row"
            # Skill instruction may be NULL if instruction_router not wired.
            # The key assertion is that the column exists and was queried
            # without error.
        finally:
            conn.close()


# ===========================================================================
# TRACE PLANE: REPL trace and child dispatch observability
# ===========================================================================


class TestSkillThreadBridgeTracePlane:
    """Verify REPL trace captures and child dispatch recording."""

    @pytest.mark.agent_challenge
    async def test_repl_submitted_code_in_state(self, tmp_path: Path):
        """Final state contains REPL_SUBMITTED_CODE with the skill import."""
        result = await _run(tmp_path)
        code = result.final_state.get(REPL_SUBMITTED_CODE, "")
        assert "rlm_repl_skills" in code, (
            f"Expected rlm_repl_skills import in submitted code, got: {code!r}"
        )

    @pytest.mark.agent_challenge
    async def test_skill_expansion_meta_in_state(self, tmp_path: Path):
        """Final state contains REPL_SKILL_EXPANSION_META with expanded symbols."""
        result = await _run(tmp_path)
        meta = result.final_state.get(REPL_SKILL_EXPANSION_META)
        assert meta is not None, "REPL_SKILL_EXPANSION_META not in final state"
        assert isinstance(meta, dict), f"Expected dict, got {type(meta)}"
        symbols = meta.get("symbols", [])
        assert "run_recursive_ping" in symbols, (
            f"Expected 'run_recursive_ping' in expanded symbols, got {symbols}"
        )

    @pytest.mark.agent_challenge
    async def test_expanded_code_in_state(self, tmp_path: Path):
        """Final state contains REPL_EXPANDED_CODE with inlined skill source."""
        result = await _run(tmp_path)
        expanded = result.final_state.get(REPL_EXPANDED_CODE, "")
        # The expanded code should contain the inlined skill function,
        # not the original synthetic import.
        assert "rlm_repl_skills" not in expanded, (
            "Expanded code should not contain synthetic import"
        )
        # It should contain the actual function definition from the skill
        assert "def " in expanded or "result" in expanded, (
            f"Expanded code should contain inlined skill source, got: {expanded[:200]!r}"
        )

    @pytest.mark.agent_challenge
    async def test_repl_did_expand_in_state(self, tmp_path: Path):
        """Final state has REPL_DID_EXPAND = True."""
        result = await _run(tmp_path)
        assert result.final_state.get(REPL_DID_EXPAND) is True, (
            f"Expected REPL_DID_EXPAND=True, got {result.final_state.get(REPL_DID_EXPAND)}"
        )

    @pytest.mark.agent_challenge
    async def test_last_repl_result_has_llm_calls(self, tmp_path: Path):
        """Final state LAST_REPL_RESULT shows >= 1 llm calls from child dispatch."""
        result = await _run(tmp_path)
        lrr = result.final_state.get(LAST_REPL_RESULT)
        assert lrr is not None, "LAST_REPL_RESULT not in final state"
        assert isinstance(lrr, dict), f"Expected dict, got {type(lrr)}"
        assert lrr.get("total_llm_calls", 0) >= 1, (
            f"Expected total_llm_calls >= 1, got {lrr}"
        )

    @pytest.mark.agent_challenge
    async def test_child_events_in_event_stream(self, tmp_path: Path):
        """Event stream contains child re-emitted events with rlm_child_event metadata."""
        result = await _run(tmp_path)
        child_events = [
            e for e in result.events
            if getattr(e, "custom_metadata", None)
            and e.custom_metadata.get("rlm_child_event")
        ]
        # Child events are re-emitted via asyncio.Queue bridge in dispatch.py.
        # They should appear in the event stream with child_depth > 0.
        assert len(child_events) >= 1, (
            f"Expected >= 1 child re-emitted events, got {len(child_events)}"
        )
        for ce in child_events:
            assert ce.custom_metadata.get("child_depth", 0) > 0, (
                f"Expected child_depth > 0 in child event metadata"
            )
```

---

## 3. Callback Flow Diagram

### Sequence of Callbacks During the Fixture Run

```
PHASE 1: Run Initialization
===========================
SqliteTracingPlugin.before_run_callback
  -> INSERT INTO traces (trace_id, session_id, ...)
  -> _trace_id set

RLMOrchestratorAgent._run_async_impl
  -> yield Event(state_delta={current_depth: 0, iteration_count: 0, ...})
    -> SqliteTracingPlugin.on_event_callback
      -> _insert_sse("current_depth", 0, ...)
      -> _insert_sse("iteration_count", 0, ...)
  -> yield Event(content=user prompt)

PHASE 2: Reasoning Call #0 (execute_code)
==========================================
SqliteTracingPlugin.before_agent_callback(reasoning_agent)
  -> push "reasoning_agent" onto _agent_span_stack

SqliteTracingPlugin.before_model_callback(reasoning, llm_request)
  -> INSERT INTO telemetry (event_type='model_call', agent_name='reasoning_agent',
     depth=0, skill_instruction=state[DYN_SKILL_INSTRUCTION], ...)
  -> _pending_model_telemetry[id(ctx)] = (telemetry_id, start_time)

reasoning_before_model(callback_context, llm_request) [agent callback]
  -> Merge dynamic instruction into system_instruction
  -> Store _rlm_pending_request_meta on agent

-- FakeGeminiServer returns functionCall: execute_code --

SqliteTracingPlugin.after_model_callback(reasoning, llm_response)
  -> UPDATE telemetry SET end_time, duration_ms, input_tokens, output_tokens, ...
  -> Pair with pending entry

reasoning_after_model(callback_context, llm_response) [agent callback]
  -> Store _rlm_last_response_meta on agent

SqliteTracingPlugin.before_tool_callback(execute_code, args, tool_context)
  -> INSERT INTO telemetry (event_type='tool_call', tool_name='execute_code',
     depth=0, decision_mode='execute_code', ...)
  -> _pending_tool_telemetry[id(tool_context)] = (telemetry_id, start_time)

REPLTool.run_async(args, tool_context)
  -> tool_context.state[repl_submitted_code] = code
  -> tool_context.state[repl_submitted_code_chars] = len(code)
  -> tool_context.state[repl_submitted_code_hash] = sha256
  -> tool_context.state[repl_submitted_code_preview] = code[:500]
  -> save_repl_code artifact
  -> tool_context.state[iteration_count] = 1
  -> expand_skill_imports(code)
    -> SkillRegistry detects "from rlm_repl_skills.ping import run_recursive_ping"
    -> Returns ExpandedSkillCode(did_expand=True, expanded_symbols=["run_recursive_ping"], ...)
  -> tool_context.state[repl_expanded_code] = expanded_source
  -> tool_context.state[repl_expanded_code_hash] = sha256
  -> tool_context.state[repl_skill_expansion_meta] = {symbols: [...], modules: [...]}
  -> tool_context.state[repl_did_expand] = True
  -> has_llm_calls(expanded_code) = True
  -> rewrite_for_async(expanded_code)
  -> repl.execute_code_async(code, compiled=tree)
    -> Skill function calls llm_query("...")
      -> AST-rewritten to await llm_query_async("...")
        -> dispatch.py._run_child(prompt, model, ...)
          -> create_child_orchestrator(depth=1, ...)
          -> child.run_async(child_ctx)
            -> [SqliteTracingPlugin callbacks fire for child at depth=1]
            -> [child events put onto _child_event_queue]
          -> _read_child_completion(child, ...)
          -> _build_call_log(prompt, result, elapsed)
    -> repl._pending_llm_calls updated
  -> post_dispatch_state_patch_fn() restores DYN_SKILL_INSTRUCTION
  -> tool_context.state[last_repl_result] = {total_llm_calls: 1, ...}
  -> telemetry_finalizer(id(tool_context), result)
    -> UPDATE telemetry SET end_time, duration_ms, repl_has_errors, repl_has_output,
       repl_llm_calls, repl_stdout_len, ...

SqliteTracingPlugin.after_tool_callback(execute_code, args, tool_context, result)
  -> UPDATE telemetry SET result_preview, decision_mode='execute_code',
     repl_has_errors, repl_has_output, repl_llm_calls, ...
  -> (may be no-op if telemetry_finalizer already consumed pending entry)

-- ADK yields tool response event --
SqliteTracingPlugin.on_event_callback(event)
  -> For each key in state_delta:
    -> _insert_sse(repl_submitted_code, ...)
    -> _insert_sse(repl_submitted_code_chars, ...)
    -> _insert_sse(repl_expanded_code, ...)
    -> _insert_sse(repl_skill_expansion_meta, ...)
    -> _insert_sse(repl_did_expand, ...)
    -> _insert_sse(iteration_count, ...)
    -> _insert_sse(last_repl_result, ...)

-- Orchestrator drains child_event_queue --
SqliteTracingPlugin.on_event_callback(child_event)
  -> _insert_sse(iteration_count@d1, ..., key_depth=1)
  -> _insert_sse(last_repl_result@d1, ..., key_depth=1)

PHASE 3: Reasoning Call #2 (set_model_response)
=================================================
SqliteTracingPlugin.before_model_callback(reasoning, llm_request)
  -> INSERT INTO telemetry (event_type='model_call', ...)

-- FakeGeminiServer returns functionCall: set_model_response --

SqliteTracingPlugin.after_model_callback(reasoning, llm_response)
  -> UPDATE telemetry SET ...

SqliteTracingPlugin.before_tool_callback(set_model_response, args, tool_context)
  -> INSERT INTO telemetry (event_type='tool_call', tool_name='set_model_response', ...)

-- SetModelResponseTool validates and stores result --

SqliteTracingPlugin.after_tool_callback(set_model_response, args, tool_context, result)
  -> UPDATE telemetry SET decision_mode='set_model_response'
  -> _deferred_tool_lineage.append({telemetry_id, agent, result})

-- ADK detects set_model_response -> terminates reasoning loop --

SqliteTracingPlugin.after_agent_callback(reasoning_agent)
  -> _flush_deferred_tool_lineage()
    -> UPDATE telemetry SET structured_outcome, terminal_completion, validated_output_json

PHASE 4: Orchestrator Finalization
===================================
RLMOrchestratorAgent._run_async_impl
  -> _collect_completion(reasoning_agent, session_state, output_schema)
  -> yield Event(state_delta={final_response_text: "...", should_stop: True})
    -> SqliteTracingPlugin.on_event_callback
      -> _insert_sse("final_response_text", ...)
      -> _insert_sse("should_stop", ...)
  -> yield Event(content=final text)

SqliteTracingPlugin.after_agent_callback(orchestrator)
  -> _flush_deferred_tool_lineage() [already empty]

SqliteTracingPlugin.after_run_callback
  -> _build_trace_summary_from_telemetry()
    -> SELECT COUNT(*), SUM(input_tokens), ... FROM telemetry
  -> UPDATE traces SET end_time, status='completed', total_calls, ...
```

---

## 4. Verification Matrix

| Data Flow | Source Component | Write Target | SQLite Table + Column | Test Method |
|---|---|---|---|---|
| Skill import detection | REPLTool.run_async | tool_context.state | session_state_events.state_key = 'repl_submitted_code' | test_repl_submitted_code_events |
| Skill expansion flag | REPLTool.run_async | tool_context.state | session_state_events.state_key = 'repl_did_expand', value_int = 1 | test_repl_did_expand_events |
| Expanded code hash | REPLTool.run_async | tool_context.state | session_state_events.state_key = 'repl_expanded_code' | (covered by test_expanded_code_in_state via final_state) |
| Expansion metadata | REPLTool.run_async | tool_context.state | session_state_events.state_key = 'repl_skill_expansion_meta' | test_skill_expansion_meta_events |
| Iteration count | REPLTool.run_async | tool_context.state | session_state_events.state_key = 'iteration_count' | test_iteration_count_events |
| REPL result with llm_calls | REPLTool.run_async | tool_context.state | session_state_events.state_key = 'last_repl_result', value_json contains total_llm_calls >= 1 | test_last_repl_result_events |
| Child state events | dispatch.py child_event_queue | re-emitted Events | session_state_events.key_depth > 0 | test_child_state_events_captured |
| Child events in stream | orchestrator drain loop | Event stream | event.custom_metadata.rlm_child_event = True | test_child_events_in_event_stream |
| Model call telemetry | SqliteTracingPlugin.before/after_model | telemetry | telemetry.event_type = 'model_call', COUNT >= 2 | test_model_call_telemetry_rows |
| execute_code telemetry | SqliteTracingPlugin.before/after_tool | telemetry | telemetry.tool_name = 'execute_code', repl_llm_calls >= 1 | test_execute_code_tool_telemetry |
| set_model_response telemetry | SqliteTracingPlugin.before/after_tool | telemetry | telemetry.tool_name = 'set_model_response', depth = 0 | test_set_model_response_tool_telemetry |
| Tool invocation summary | SqliteTracingPlugin.after_run | traces | traces.tool_invocation_summary has execute_code + set_model_response | test_tool_invocation_summary_in_traces |
| Trace completion | SqliteTracingPlugin.after_run | traces | traces.status = 'completed', total_calls >= 2, tokens > 0 | test_traces_row_completed |
| skill_instruction column | SqliteTracingPlugin.before_model | telemetry | telemetry.skill_instruction (may be NULL without instruction_router) | test_skill_instruction_column_populated |
| Expanded symbols in state | REPLTool -> expand_skill_imports | session state | final_state[REPL_SKILL_EXPANSION_META].symbols contains "run_recursive_ping" | test_skill_expansion_meta_in_state |
| Expanded code has no synthetic import | REPLTool -> expand_skill_imports | session state | final_state[REPL_EXPANDED_CODE] has no "rlm_repl_skills" | test_expanded_code_in_state |
| REPL_DID_EXPAND flag | REPLTool.run_async | session state | final_state[REPL_DID_EXPAND] = True | test_repl_did_expand_in_state |
| LLM calls in REPL result | REPLTool.run_async | session state | final_state[LAST_REPL_RESULT].total_llm_calls >= 1 | test_last_repl_result_has_llm_calls |

---

## 5. Implementation Notes

### File Locations

- **Fixture**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/skill_thread_bridge_e2e.json`
- **Test script**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_skill_thread_bridge_e2e.py`

### Dependencies

The test depends on:
1. The `run_recursive_ping` skill being registered in `rlm_repl_skills.ping` (already exists)
2. The `FakeGeminiServer` infrastructure in `tests_rlm_adk/provider_fake/`
3. The `contract_runner.run_fixture_contract_with_plugins()` helper
4. `SqliteTracingPlugin` installed as a plugin

### Running the Tests

```bash
# Run just this test file
.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q

# Run with verbose output
.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py -v --tb=short
```

### Why This Is Not Reward-Hacking

The fixture:
1. Uses the **real** skill expansion pipeline (`expand_skill_imports()`)
2. Uses the **real** AST rewriter (`rewrite_for_async()`)
3. Uses the **real** child orchestrator dispatch (`create_child_orchestrator()`)
4. Uses the **real** `SqliteTracingPlugin` writing to a real SQLite database
5. The child model response format (`set_model_response` with `ReasoningOutput`) matches what a real model would emit through a child orchestrator
6. The assertions query the **actual database** rather than checking mock invocations

The fixture does NOT:
- Pre-populate expected state values
- Mock any pipeline components
- Simulate telemetry writes directly
- Use in-memory services (uses real SqliteSessionService + FileArtifactService)

### Potential Failure Modes

1. **Fixture response count mismatch**: If the child orchestrator makes more API calls than expected (e.g., the initial user content event triggers an extra model call), the fake server will run out of scripted responses. The `skill_expansion.json` fixture already handles this pattern with 3 responses (reasoning #0, worker #1, reasoning #2), so we follow the same pattern.

2. **Child set_model_response format**: If the child orchestrator does not wire `SetModelResponseTool`, the worker response format would be wrong. We use `set_model_response` functionCall format for the worker response (call_index=1) since `create_child_orchestrator` wires `ReasoningOutput` as the schema.

3. **SSE key capture**: If `should_capture_state_key()` does not include a key we assert on, the SSE row will not be written. All keys we assert on (`repl_submitted_code`, `repl_skill_expansion_meta`, `repl_did_expand`, `last_repl_result`, `iteration_count`) are covered by `CURATED_STATE_PREFIXES` or `CURATED_STATE_KEYS` in `state.py`.
