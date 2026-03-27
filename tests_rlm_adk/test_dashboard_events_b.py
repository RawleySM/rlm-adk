"""Tests for DashboardEventPlugin (Agent B).

TDD cycles for the plugin that captures model + tool events into
an append-only JSONL file with explicit lineage.

1. Model event emitted after model callback
2. Tool event carries model_event_id
3. execute_code sets invocation context attrs
4. GAP-06 finalizer emits when after_tool skipped
5. Finalizer composition calls both plugins
6. _last_model_event_id cleaned on set_model_response
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_inv_ctx(
    *,
    invocation_id="inv_001",
    agent_name="reasoning_agent",
    depth=0,
    fanout_idx=None,
    parent_invocation_id=None,
    parent_tool_call_id=None,
    dispatch_call_index=0,
    branch=None,
    session_id="sess_001",
):
    """Build a minimal mock InvocationContext + agent."""
    agent = MagicMock()
    agent.name = agent_name
    agent._rlm_depth = depth
    agent._rlm_fanout_idx = fanout_idx
    agent._rlm_parent_invocation_id = parent_invocation_id
    agent._rlm_parent_tool_call_id = parent_tool_call_id
    agent._rlm_dispatch_call_index = dispatch_call_index

    session = MagicMock()
    session.id = session_id

    inv_ctx = MagicMock()
    inv_ctx.invocation_id = invocation_id
    inv_ctx.agent = agent
    inv_ctx.branch = branch
    inv_ctx.session = session

    return inv_ctx


def _make_callback_context(inv_ctx):
    """Build a minimal mock CallbackContext wrapping an InvocationContext."""
    cb = MagicMock()
    cb._invocation_context = inv_ctx
    return cb


def _make_tool_context(inv_ctx):
    """Build a minimal mock ToolContext wrapping an InvocationContext."""
    tc = MagicMock()
    tc._invocation_context = inv_ctx
    return tc


def _make_llm_request(*, model="gemini-2.0-flash"):
    """Build a minimal mock LlmRequest."""
    req = MagicMock()
    req.model = model
    return req


def _make_llm_response(
    *, input_tokens=100, output_tokens=50, thought_tokens=10, error_code=None, error_message=None
):
    """Build a minimal mock LlmResponse with usage_metadata."""
    resp = MagicMock()
    usage = MagicMock()
    usage.prompt_token_count = input_tokens
    usage.candidates_token_count = output_tokens
    usage.thoughts_token_count = thought_tokens
    resp.usage_metadata = usage
    resp.error_code = error_code
    resp.error_message = error_message
    return resp


def _make_tool(*, name="execute_code"):
    """Build a minimal mock tool."""
    tool = MagicMock()
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# Cycle 1 -- Model event emitted after model callback
# ---------------------------------------------------------------------------


class TestModelEventEmitted:
    """after_model_callback decomposes request + tokens -> JSONL line with phase=model."""

    @pytest.mark.asyncio
    async def test_model_event_emitted_after_model_callback(self, tmp_path):
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_m1")
        cb_ctx = _make_callback_context(inv_ctx)
        llm_req = _make_llm_request(model="gemini-2.0-flash")
        llm_resp = _make_llm_response(input_tokens=100, output_tokens=50, thought_tokens=10)

        # before + after model
        await plugin.before_model_callback(
            callback_context=cb_ctx,
            llm_request=llm_req,
        )
        await plugin.after_model_callback(
            callback_context=cb_ctx,
            llm_response=llm_resp,
        )

        # Read JSONL
        lines = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines) == 1, f"Expected 1 JSONL line, got {len(lines)}"
        event = json.loads(lines[0])

        assert event["phase"] == "model"
        assert event["event_id"]  # non-empty
        assert event["invocation_id"] == "inv_m1"
        assert event["input_tokens"] == 100
        assert event["output_tokens"] == 50
        assert event["thought_tokens"] == 10
        assert event["model"] == "gemini-2.0-flash"
        assert event["error"] is False

        plugin.close()


# ---------------------------------------------------------------------------
# Cycle 2 -- Tool event carries model_event_id
# ---------------------------------------------------------------------------


class TestToolEventCarriesModelEventId:
    """after_tool_callback emits phase=tool with model_event_id pointing to preceding model event."""

    @pytest.mark.asyncio
    async def test_tool_event_carries_model_event_id(self, tmp_path):
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_mt1")
        cb_ctx = _make_callback_context(inv_ctx)
        tc = _make_tool_context(inv_ctx)
        llm_req = _make_llm_request()
        llm_resp = _make_llm_response()
        tool = _make_tool(name="some_tool")

        # Model callback pair
        await plugin.before_model_callback(callback_context=cb_ctx, llm_request=llm_req)
        await plugin.after_model_callback(callback_context=cb_ctx, llm_response=llm_resp)

        # Tool callback pair
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"key": "val"},
            tool_context=tc,
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"key": "val"},
            tool_context=tc,
            result={"status": "ok"},
        )

        lines = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines) == 2, f"Expected 2 JSONL lines, got {len(lines)}"

        model_event = json.loads(lines[0])
        tool_event = json.loads(lines[1])

        assert model_event["phase"] == "model"
        assert tool_event["phase"] == "tool"
        assert tool_event["model_event_id"] == model_event["event_id"]
        assert tool_event["tool_name"] == "some_tool"
        assert tool_event["duration_ms"] >= 0

        plugin.close()


# ---------------------------------------------------------------------------
# Cycle 3 -- execute_code sets invocation context attrs
# ---------------------------------------------------------------------------


class TestExecuteCodeSetsInvCtxAttrs:
    """before_tool_callback for execute_code sets _dashboard_execute_code_event_id
    and resets _dispatch_call_counter."""

    @pytest.mark.asyncio
    async def test_execute_code_sets_invocation_context_attrs(self, tmp_path):
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_ec1")
        tc = _make_tool_context(inv_ctx)
        tool = _make_tool(name="execute_code")

        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('hi')"},
            tool_context=tc,
        )

        # Check that _dashboard_execute_code_event_id was set on AGENT
        # (plugin sets on agent, not InvocationContext, because ADK gives
        # tool callbacks a different InvocationContext instance than dispatch)
        agent = inv_ctx.agent
        assert hasattr(agent, "_dashboard_execute_code_event_id"), (
            "Expected _dashboard_execute_code_event_id to be set on agent"
        )
        event_id = agent._dashboard_execute_code_event_id
        assert event_id and isinstance(event_id, str), (
            f"Expected non-empty string event_id, got: {event_id!r}"
        )

        # Check that _dashboard_dispatch_call_counter was reset
        assert agent._dashboard_dispatch_call_counter == 0, (
            f"Expected _dashboard_dispatch_call_counter=0, got: {agent._dashboard_dispatch_call_counter}"
        )

        plugin.close()


# ---------------------------------------------------------------------------
# Cycle 4 -- GAP-06 finalizer emits when after_tool skipped
# ---------------------------------------------------------------------------


class TestGap06FinalizerEmits:
    """make_telemetry_finalizer closure emits tool event synchronously."""

    @pytest.mark.asyncio
    async def test_gap06_finalizer_emits_when_after_tool_skipped(self, tmp_path):
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_gap06")
        cb_ctx = _make_callback_context(inv_ctx)
        tc = _make_tool_context(inv_ctx)
        tool = _make_tool(name="execute_code")

        # Model pair first (so there's a model_event_id to link)
        llm_req = _make_llm_request()
        llm_resp = _make_llm_response()
        await plugin.before_model_callback(callback_context=cb_ctx, llm_request=llm_req)
        await plugin.after_model_callback(callback_context=cb_ctx, llm_response=llm_resp)

        # before_tool_callback runs, but after_tool_callback does NOT
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "x = 1"},
            tool_context=tc,
        )

        # Get the finalizer and call it directly (simulating REPLTool's GAP-06 path)
        finalizer = plugin.make_telemetry_finalizer()
        tool_context_id = id(tc)
        finalizer(tool_context_id, {"stdout": "ok", "stderr": "", "llm_calls_made": False, "total_llm_calls": 0})

        lines = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines) == 2, f"Expected 2 JSONL lines (model + tool), got {len(lines)}"

        tool_event = json.loads(lines[1])
        assert tool_event["phase"] == "tool"
        assert tool_event["tool_name"] == "execute_code"
        assert tool_event["stdout"] == "ok"
        assert tool_event["invocation_id"] == "inv_gap06"

        # Verify finalizer is idempotent -- calling again should NOT emit
        finalizer(tool_context_id, {"stdout": "again"})
        lines_after = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines_after) == 2, "Finalizer should be idempotent (no duplicate emit)"

        plugin.close()


# ---------------------------------------------------------------------------
# Cycle 5 -- Finalizer composition calls both
# ---------------------------------------------------------------------------


class TestFinalizerComposition:
    """Combined finalizer calls both sqlite and dashboard finalizers."""

    def test_finalizer_composition_calls_both(self):
        """Compose two finalizers and verify both are called."""
        call_log: list[str] = []

        def fin_a(tid, r):
            call_log.append(f"a:{tid}")

        def fin_b(tid, r):
            call_log.append(f"b:{tid}")

        finalizers = [fin_a, fin_b]
        # Same composition pattern used in orchestrator.py
        composed = (lambda fns: lambda tid, r: [f(tid, r) for f in fns])(finalizers)

        composed(42, {"result": "ok"})

        assert "a:42" in call_log
        assert "b:42" in call_log
        assert len(call_log) == 2


# ---------------------------------------------------------------------------
# Cycle 6 -- _last_model_event_id cleaned on set_model_response
# ---------------------------------------------------------------------------


class TestLastModelEventIdCleanedOnSetModelResponse:
    """_last_model_event_id entry removed after set_model_response tool event."""

    @pytest.mark.asyncio
    async def test_last_model_event_id_cleaned_on_set_model_response(self, tmp_path):
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_smr1")
        cb_ctx = _make_callback_context(inv_ctx)
        tc = _make_tool_context(inv_ctx)
        llm_req = _make_llm_request()
        llm_resp = _make_llm_response()

        # Model pair
        await plugin.before_model_callback(callback_context=cb_ctx, llm_request=llm_req)
        await plugin.after_model_callback(callback_context=cb_ctx, llm_response=llm_resp)

        # Confirm _last_model_event_id is set (keyed by id(inv_ctx))
        ctx_key = id(inv_ctx)
        assert ctx_key in plugin._last_model_event_id

        # set_model_response tool pair
        smr_tool = _make_tool(name="set_model_response")
        await plugin.before_tool_callback(
            tool=smr_tool,
            tool_args={"final_answer": "done"},
            tool_context=tc,
        )
        await plugin.after_tool_callback(
            tool=smr_tool,
            tool_args={"final_answer": "done"},
            tool_context=tc,
            result={"status": "ok"},
        )

        # _last_model_event_id should be cleaned for this invocation
        assert ctx_key not in plugin._last_model_event_id, (
            f"Expected ctx_key to be removed from _last_model_event_id, "
            f"but found: {plugin._last_model_event_id}"
        )

        plugin.close()


# ---------------------------------------------------------------------------
# Cycle 7 -- llm_query_detected/llm_query_count read correct keys
# ---------------------------------------------------------------------------


class TestLlmQueryKeysMatchREPLTool:
    """after_tool_callback reads llm_calls_made and total_llm_calls from REPLTool result."""

    @pytest.mark.asyncio
    async def test_after_tool_reads_llm_calls_made_true(self, tmp_path):
        """llm_query_detected is True when result has llm_calls_made=True."""
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_llm1")
        cb_ctx = _make_callback_context(inv_ctx)
        tc = _make_tool_context(inv_ctx)
        tool = _make_tool(name="execute_code")

        # Model pair
        llm_req = _make_llm_request()
        llm_resp = _make_llm_response()
        await plugin.before_model_callback(callback_context=cb_ctx, llm_request=llm_req)
        await plugin.after_model_callback(callback_context=cb_ctx, llm_response=llm_resp)

        # Tool pair with llm_calls_made=True and total_llm_calls=3
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "llm_query('x')"},
            tool_context=tc,
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "llm_query('x')"},
            tool_context=tc,
            result={
                "stdout": "ok",
                "stderr": "",
                "llm_calls_made": True,
                "total_llm_calls": 3,
                "call_number": 1,
            },
        )

        lines = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines) == 2
        tool_event = json.loads(lines[1])

        assert tool_event["llm_query_detected"] is True, (
            f"Expected llm_query_detected=True, got {tool_event['llm_query_detected']}"
        )
        assert tool_event["llm_query_count"] == 3, (
            f"Expected llm_query_count=3, got {tool_event['llm_query_count']}"
        )

        plugin.close()

    @pytest.mark.asyncio
    async def test_after_tool_reads_llm_calls_made_false(self, tmp_path):
        """llm_query_detected is False when result has llm_calls_made=False."""
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        inv_ctx = _make_inv_ctx(invocation_id="inv_llm2")
        cb_ctx = _make_callback_context(inv_ctx)
        tc = _make_tool_context(inv_ctx)
        tool = _make_tool(name="execute_code")

        # Model pair
        llm_req = _make_llm_request()
        llm_resp = _make_llm_response()
        await plugin.before_model_callback(callback_context=cb_ctx, llm_request=llm_req)
        await plugin.after_model_callback(callback_context=cb_ctx, llm_response=llm_resp)

        # Tool pair with llm_calls_made=False and total_llm_calls=0
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "x = 1"},
            tool_context=tc,
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "x = 1"},
            tool_context=tc,
            result={
                "stdout": "1",
                "stderr": "",
                "llm_calls_made": False,
                "total_llm_calls": 0,
                "call_number": 1,
            },
        )

        lines = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines) == 2
        tool_event = json.loads(lines[1])

        assert tool_event["llm_query_detected"] is False, (
            f"Expected llm_query_detected=False, got {tool_event['llm_query_detected']}"
        )
        assert tool_event["llm_query_count"] == 0, (
            f"Expected llm_query_count=0, got {tool_event['llm_query_count']}"
        )

        plugin.close()

    def test_finalizer_reads_llm_calls_made_true(self, tmp_path):
        """GAP-06 finalizer reads llm_calls_made and total_llm_calls correctly."""
        from rlm_adk.plugins.dashboard_events import DashboardEventPlugin

        jsonl_path = str(tmp_path / "events.jsonl")
        plugin = DashboardEventPlugin(output_path=jsonl_path)

        # Manually insert a pending_tool entry (simulating before_tool_callback)
        fake_entry = {
            "event_id": "evt_fin_llm",
            "start_time": 1000.0,
            "tool_name": "execute_code",
            "tool_args": {"code": "llm_query('y')"},
            "invocation_id": "inv_fin_llm",
            "ctx_key": 999,
            "agent_name": "reasoning_agent",
            "depth": 0,
            "fanout_idx": None,
            "parent_invocation_id": None,
            "parent_tool_call_id": None,
            "dispatch_call_index": 0,
            "branch": None,
            "session_id": "sess_fin",
        }
        tc_id = 12345
        plugin._pending_tool[tc_id] = fake_entry

        finalizer = plugin.make_telemetry_finalizer()
        finalizer(tc_id, {
            "stdout": "child result",
            "stderr": "",
            "llm_calls_made": True,
            "total_llm_calls": 2,
            "call_number": 1,
        })

        lines = Path(jsonl_path).read_text().strip().splitlines()
        assert len(lines) == 1
        tool_event = json.loads(lines[0])

        assert tool_event["llm_query_detected"] is True, (
            f"Expected llm_query_detected=True, got {tool_event['llm_query_detected']}"
        )
        assert tool_event["llm_query_count"] == 2, (
            f"Expected llm_query_count=2, got {tool_event['llm_query_count']}"
        )

        plugin.close()
