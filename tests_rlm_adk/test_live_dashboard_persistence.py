import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin


@pytest.fixture
def plugin_and_db(tmp_path):
    db_path = str(tmp_path / "live.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    return plugin, db_path


def _invocation_context():
    ctx = MagicMock()
    ctx.session.id = "sess_live"
    ctx.session.user_id = "user"
    ctx.app_name = "rlm_adk"
    ctx.session.state = {}
    return ctx


@pytest.mark.asyncio
async def test_reasoning_and_child_payload_keys_persist_to_sse(plugin_and_db):
    plugin, db_path = plugin_and_db
    inv_ctx = _invocation_context()
    await plugin.before_run_callback(invocation_context=inv_ctx)

    event = MagicMock()
    event.author = "reasoning_agent"
    event.actions.state_delta = {
        "reasoning_visible_output_text@d1": "full visible child output",
        "reasoning_thought_text@d1": "full child thought trace",
        "reasoning_raw_output@d1": {"final_answer": "ok"},
        "reasoning_parsed_output@d1": {"final_answer": "ok"},
        "skill_instruction": "Use shard summarization.",
        "obs:child_summary@d2f1": {
            "depth": 2,
            "fanout_idx": 1,
            "parent_depth": 1,
            "parent_fanout_idx": 0,
            "prompt": "Read shard B",
            "visible_output_text": "Shard B answer",
            "thought_text": "Shard B reasoning",
            "raw_output": {"answer": "Shard B answer"},
        },
    }
    event.actions.artifact_delta = {}

    await plugin.on_event_callback(invocation_context=inv_ctx, event=event)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT state_key, key_depth, key_fanout, value_text, value_json
        FROM session_state_events
        ORDER BY seq
        """
    ).fetchall()
    conn.close()

    by_key = {(row["state_key"], row["key_depth"], row["key_fanout"]): row for row in rows}
    assert ("reasoning_visible_output_text", 1, None) in by_key
    assert by_key[("reasoning_visible_output_text", 1, None)]["value_text"] == "full visible child output"
    assert ("skill_instruction", 0, None) in by_key
    child_payload = json.loads(by_key[("obs:child_summary", 2, 1)]["value_json"])
    assert child_payload["prompt"] == "Read shard B"
    assert child_payload["raw_output"]["answer"] == "Shard B answer"


@pytest.mark.asyncio
async def test_tool_telemetry_captures_full_repl_payload(plugin_and_db):
    plugin, db_path = plugin_and_db
    inv_ctx = _invocation_context()
    await plugin.before_run_callback(invocation_context=inv_ctx)

    callback_context = MagicMock()
    callback_context.state = {}
    agent = MagicMock()
    agent.name = "reasoning_agent"
    await plugin.before_agent_callback(agent=agent, callback_context=callback_context)

    tool = MagicMock()
    tool.name = "execute_code"
    tool._depth = 1
    tool_context = MagicMock()
    tool_context.state = {
        "iteration_count@d1": 3,
        "last_repl_result@d1": {
            "stdout": "full stdout",
            "stderr": "full stderr",
            "has_errors": True,
            "has_output": True,
            "total_llm_calls": 2,
        },
    }

    await plugin.before_tool_callback(
        tool=tool,
        tool_args={"code": "print('hi')"},
        tool_context=tool_context,
    )
    await plugin.after_tool_callback(
        tool=tool,
        tool_args={"code": "print('hi')"},
        tool_context=tool_context,
        result={
            "stdout": "full stdout",
            "stderr": "full stderr",
            "call_number": 3,
        },
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT tool_name, depth, iteration, call_number, result_payload,
               repl_stdout, repl_stderr, repl_stdout_len, repl_stderr_len
        FROM telemetry
        WHERE event_type = 'tool_call'
        """
    ).fetchone()
    conn.close()

    assert row["tool_name"] == "execute_code"
    assert row["depth"] == 1
    assert row["iteration"] == 3
    assert row["call_number"] == 3
    payload = json.loads(row["result_payload"])
    assert payload["stdout"] == "full stdout"
    assert row["repl_stdout"] == "full stdout"
    assert row["repl_stderr"] == "full stderr"
    assert row["repl_stdout_len"] == len("full stdout")
    assert row["repl_stderr_len"] == len("full stderr")

