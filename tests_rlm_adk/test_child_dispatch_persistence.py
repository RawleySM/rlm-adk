"""Focused tests for child dispatch persistence observability."""

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rlm_adk.dispatch import DispatchConfig, create_dispatch_closures
from rlm_adk.repl.trace import REPLTrace
from rlm_adk.state import (
    REASONING_FINISH_REASON,
    REASONING_PARSED_OUTPUT,
    REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS,
    REASONING_VISIBLE_OUTPUT_TEXT,
)


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.invocation_id = "inv-test"
    ctx.session.state = {}
    return ctx


def _make_child_with_obs(
    answer: str,
    *,
    depth: int = 1,
    output_key: str | None = None,
) -> MagicMock:
    child = MagicMock()
    child.persistent = False
    child.repl = None

    reasoning = MagicMock()
    reasoning.output_key = output_key or f"reasoning_output@d{depth}"
    child.reasoning_agent = reasoning

    async def mock_run_async(ctx):
        ctx.session.state[reasoning.output_key] = answer
        ctx.session.state[f"reasoning_input_tokens@d{depth}"] = 17
        ctx.session.state[f"reasoning_output_tokens@d{depth}"] = 9
        ctx.session.state[f"{REASONING_THOUGHT_TOKENS}@d{depth}"] = 4
        ctx.session.state[f"{REASONING_FINISH_REASON}@d{depth}"] = "STOP"
        ctx.session.state[f"{REASONING_VISIBLE_OUTPUT_TEXT}@d{depth}"] = answer
        ctx.session.state[f"{REASONING_THOUGHT_TEXT}@d{depth}"] = "hidden chain"
        ctx.session.state[f"{REASONING_PARSED_OUTPUT}@d{depth}"] = {
            "final_answer": answer,
            "reasoning_summary": "done",
        }
        return
        yield

    child.run_async = mock_run_async
    return child


class TestDispatchChildMetadata:
    @pytest.mark.asyncio
    async def test_llm_query_populates_child_metadata_and_call_log(self):
        ctx = _make_ctx()
        config = DispatchConfig(default_model="gemini-test")
        call_log_sink: list = []
        trace = REPLTrace()
        trace_holder = [trace]
        child = _make_child_with_obs("child answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config,
                ctx,
                call_log_sink=call_log_sink,
                trace_sink=trace_holder,
                depth=0,
                max_depth=3,
            )
            result = await llm_query("solve this")

        assert result.input_tokens == 17
        assert result.output_tokens == 9
        assert result.finish_reason == "STOP"
        assert result.parsed == {"final_answer": "child answer", "reasoning_summary": "done"}
        assert getattr(result, "thoughts_tokens", None) == 4
        assert getattr(result, "visible_text", None) == "child answer"
        assert getattr(result, "thought_text", None) == "hidden chain"

        assert len(call_log_sink) == 1
        call = call_log_sink[0]
        assert call.prompt == "solve this"
        assert call.response == "child answer"
        usage = call.usage_summary.model_usage_summaries["gemini-test"]
        assert usage.total_input_tokens == 17
        assert usage.total_output_tokens == 9

        assert len(trace.llm_calls) == 1
        trace_entry = trace.llm_calls[0]
        assert trace_entry["input_tokens"] == 17
        assert trace_entry["output_tokens"] == 9
        assert trace_entry["finish_reason"] == "STOP"
        assert trace_entry["thoughts_tokens"] == 4

    @pytest.mark.asyncio
    async def test_failed_child_dispatch_is_added_to_call_log(self):
        ctx = _make_ctx()
        config = DispatchConfig(default_model="gemini-test")
        call_log_sink: list = []
        trace = REPLTrace()
        trace_holder = [trace]

        async def _failing_run_child(*args, **kwargs):
            raise RuntimeError("child boom")
            yield

        child = MagicMock()
        child.persistent = False
        child.repl = None
        reasoning = MagicMock()
        reasoning.output_key = "reasoning_output@d1"
        child.reasoning_agent = reasoning
        child.run_async = _failing_run_child

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config,
                ctx,
                call_log_sink=call_log_sink,
                trace_sink=trace_holder,
                depth=0,
                max_depth=3,
            )
            result = await llm_query("solve this")

        assert result.error is True
        assert len(call_log_sink) == 1
        call = call_log_sink[0]
        assert call.prompt == "solve this"
        assert call.root_model == "gemini-test"
        assert call.response == "Error: child boom"
        usage = call.usage_summary.model_usage_summaries["gemini-test"]
        assert usage.total_input_tokens == 0
        assert usage.total_output_tokens == 0

    @pytest.mark.asyncio
    async def test_depth_limit_failure_is_added_to_call_log(self):
        ctx = _make_ctx()
        config = DispatchConfig(default_model="gemini-test")
        call_log_sink: list = []

        llm_query, _, _ = create_dispatch_closures(
            config,
            ctx,
            call_log_sink=call_log_sink,
            depth=2,
            max_depth=3,
        )
        result = await llm_query("too deep")

        assert result.error is True
        assert result.error_category == "DEPTH_LIMIT"
        assert len(call_log_sink) == 1
        call = call_log_sink[0]
        assert call.prompt == "too deep"
        assert call.root_model == "gemini-test"
        assert "[DEPTH_LIMIT]" in call.response
        usage = call.usage_summary.model_usage_summaries["gemini-test"]
        assert usage.total_input_tokens == 0
        assert usage.total_output_tokens == 0


class TestREPLTracingPluginDepthKeys:
    @pytest.mark.asyncio
    async def test_depth_scoped_last_repl_result_is_persisted(self):
        from rlm_adk.plugins.repl_tracing import REPLTracingPlugin

        plugin = REPLTracingPlugin()
        event = MagicMock()
        event.author = "child_orchestrator_d2"
        event.actions.state_delta = {
            "iteration_count@d2": 7,
            "last_repl_result@d2": {
                "trace_summary": {"llm_call_count": 2, "wall_time_ms": 12.5}
            },
        }
        invocation_context = MagicMock()
        invocation_context.app_name = "rlm_adk"
        invocation_context.session.id = "sess-1"
        invocation_context.session.user_id = "user-1"
        invocation_context.artifact_service = MagicMock()
        invocation_context.artifact_service.save_artifact = AsyncMock()

        await plugin.on_event_callback(
            invocation_context=invocation_context,
            event=event,
        )
        await plugin.after_run_callback(invocation_context=invocation_context)

        save_call = invocation_context.artifact_service.save_artifact.await_args
        payload = json.loads(save_call.kwargs["artifact"].inline_data.data.decode("utf-8"))
        assert payload["d2:i7"]["depth"] == 2
        assert payload["d2:i7"]["iteration"] == 7
        assert payload["d2:i7"]["trace_summary"]["llm_call_count"] == 2


class TestSqliteTracingChildPersistence:
    @pytest.mark.asyncio
    async def test_after_run_persists_child_total_batch_dispatches(self, tmp_path):
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        db_path = tmp_path / "traces.db"
        plugin = SqliteTracingPlugin(db_path=str(db_path))
        invocation_context = MagicMock()
        invocation_context.session.id = "sess-1"
        invocation_context.session.user_id = "user-1"
        invocation_context.app_name = "rlm_adk"
        invocation_context.session.state = {
            "obs:child_total_batch_dispatches": 3,
        }

        await plugin.before_run_callback(invocation_context=invocation_context)
        await plugin.after_run_callback(invocation_context=invocation_context)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT child_total_batch_dispatches FROM traces"
        ).fetchone()
        conn.close()

        assert row["child_total_batch_dispatches"] == 3

    @pytest.mark.asyncio
    async def test_after_tool_uses_last_repl_result_state_for_repl_metrics(self, tmp_path):
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        db_path = tmp_path / "traces.db"
        plugin = SqliteTracingPlugin(db_path=str(db_path))
        invocation_context = MagicMock()
        invocation_context.session.id = "sess-1"
        invocation_context.session.user_id = "user-1"
        invocation_context.app_name = "rlm_adk"
        invocation_context.session.state = {}
        await plugin.before_run_callback(invocation_context=invocation_context)

        tool = MagicMock()
        tool.name = "execute_code"
        tool_context = MagicMock()
        tool_context.state = {
            "last_repl_result@d2": {
                "has_errors": False,
                "has_output": True,
                "total_llm_calls": 5,
                "trace_summary": {"llm_call_count": 5, "wall_time_ms": 4.2},
            }
        }

        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('hello')"},
            tool_context=tool_context,
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "print('hello')"},
            tool_context=tool_context,
            result={"stdout": "hello\n", "stderr": "", "llm_calls_made": True},
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT repl_has_errors, repl_has_output, repl_llm_calls,
                   repl_stdout_len, repl_stderr_len, repl_trace_summary
            FROM telemetry
            """
        ).fetchone()
        conn.close()

        assert row["repl_has_errors"] == 0
        assert row["repl_has_output"] == 1
        assert row["repl_llm_calls"] == 5
        assert row["repl_stdout_len"] == 6
        assert row["repl_stderr_len"] == 0
        assert json.loads(row["repl_trace_summary"])["llm_call_count"] == 5

    @pytest.mark.asyncio
    async def test_after_tool_prefers_matching_depth_last_repl_result(self, tmp_path):
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        db_path = tmp_path / "traces.db"
        plugin = SqliteTracingPlugin(db_path=str(db_path))
        invocation_context = MagicMock()
        invocation_context.session.id = "sess-1"
        invocation_context.session.user_id = "user-1"
        invocation_context.app_name = "rlm_adk"
        invocation_context.session.state = {}
        await plugin.before_run_callback(invocation_context=invocation_context)

        tool = MagicMock()
        tool.name = "execute_code"
        tool._depth = 1
        tool_context = MagicMock()
        tool_context.state = {
            "last_repl_result@d1": {
                "has_errors": False,
                "has_output": True,
                "total_llm_calls": 1,
            },
            "last_repl_result@d2": {
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": 9,
            },
        }

        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('hello')"},
            tool_context=tool_context,
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "print('hello')"},
            tool_context=tool_context,
            result={"stdout": "hello\n", "stderr": "", "llm_calls_made": True},
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT repl_has_errors, repl_has_output, repl_llm_calls
            FROM telemetry
            """
        ).fetchone()
        conn.close()

        assert row["repl_has_errors"] == 0
        assert row["repl_has_output"] == 1
        assert row["repl_llm_calls"] == 1

    @pytest.mark.asyncio
    async def test_after_model_persists_thought_tokens(self, tmp_path):
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        db_path = tmp_path / "traces.db"
        plugin = SqliteTracingPlugin(db_path=str(db_path))
        invocation_context = MagicMock()
        invocation_context.session.id = "sess-1"
        invocation_context.session.user_id = "user-1"
        invocation_context.app_name = "rlm_adk"
        invocation_context.session.state = {}
        await plugin.before_run_callback(invocation_context=invocation_context)

        callback_context = MagicMock()
        callback_context.state = {}
        callback_context._invocation_context = MagicMock()
        llm_request = MagicMock()
        llm_request.model = "gemini-test"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=llm_request,
        )

        llm_response = MagicMock()
        llm_response.model_version = "gemini-test"
        llm_response.usage_metadata = MagicMock()
        llm_response.usage_metadata.prompt_token_count = 11
        llm_response.usage_metadata.candidates_token_count = 7
        llm_response.usage_metadata.thoughts_token_count = 3
        llm_response.finish_reason = MagicMock()
        llm_response.finish_reason.name = "STOP"
        llm_response.error_code = None

        await plugin.after_model_callback(
            callback_context=callback_context,
            llm_response=llm_response,
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT input_tokens, output_tokens, thought_tokens FROM telemetry"
        ).fetchone()
        conn.close()

        assert row["input_tokens"] == 11
        assert row["output_tokens"] == 7
        assert row["thought_tokens"] == 3
