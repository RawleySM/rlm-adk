import json
import sqlite3

import pytest

from rlm_adk.dashboard.live_controller import LiveDashboardController
from rlm_adk.dashboard.live_loader import LiveDashboardLoader
from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin


@pytest.fixture
def live_sources(tmp_path):
    db_path = tmp_path / "traces.db"
    snapshots_path = tmp_path / "context_snapshots.jsonl"
    outputs_path = tmp_path / "model_outputs.jsonl"
    SqliteTracingPlugin(db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO traces (trace_id, session_id, app_name, start_time, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("trace_live", "sess_live", "rlm_adk", 1.0, "running"),
    )
    conn.execute(
        """
        INSERT INTO telemetry (
            telemetry_id, trace_id, event_type, agent_name, iteration, depth,
            start_time, end_time, duration_ms, model, input_tokens, output_tokens,
            thought_tokens, prompt_chars, system_chars, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tel_root",
            "trace_live",
            "model_call",
            "reasoning_agent",
            0,
            0,
            10.0,
            11.0,
            1000.0,
            "gemini-root",
            120,
            40,
            15,
            320,
            180,
            "ok",
        ),
    )
    conn.execute(
        """
        INSERT INTO telemetry (
            telemetry_id, trace_id, event_type, agent_name, iteration, depth,
            start_time, end_time, duration_ms, model, input_tokens, output_tokens,
            thought_tokens, prompt_chars, system_chars, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tel_child",
            "trace_live",
            "model_call",
            "child_reasoning_d1",
            0,
            1,
            12.0,
            13.0,
            900.0,
            "gemini-child",
            60,
            25,
            8,
            150,
            0,
            "ok",
        ),
    )
    conn.execute(
        """
        INSERT INTO telemetry (
            telemetry_id, trace_id, event_type, agent_name, iteration, depth,
            call_number, start_time, end_time, duration_ms, tool_name,
            result_preview, repl_stdout_len, repl_stderr_len,
            repl_stdout, repl_stderr, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tool_root",
            "trace_live",
            "tool_call",
            "reasoning_agent",
            1,
            0,
            1,
            11.5,
            11.8,
            300.0,
            "execute_code",
            "{}",
            12,
            0,
            "hello world\n",
            "",
            "ok",
        ),
    )

    sse_rows = [
        (
            "sse_1",
            "trace_live",
            0,
            "reasoning_agent",
            10.0,
            "reasoning_visible_output_text",
            "obs_reasoning",
            0,
            None,
            "str",
            None,
            None,
            "Root visible output",
            None,
        ),
        (
            "sse_2",
            "trace_live",
            1,
            "reasoning_agent",
            10.0,
            "reasoning_thought_text",
            "obs_reasoning",
            0,
            None,
            "str",
            None,
            None,
            "Root thought output",
            None,
        ),
        (
            "sse_3",
            "trace_live",
            2,
            "reasoning_agent",
            11.0,
            "repl_submitted_code",
            "repl",
            0,
            None,
            "str",
            None,
            None,
            "print('hello world')",
            None,
        ),
        (
            "sse_4",
            "trace_live",
            3,
            "reasoning_agent",
            11.0,
            "last_repl_result",
            "repl",
            0,
            None,
            "dict",
            None,
            None,
            None,
            json.dumps({"stdout": "hello world\n", "stderr": "", "has_output": True}),
        ),
        (
            "sse_5",
            "trace_live",
            4,
            "reasoning_agent",
            10.0,
            "skill_instruction",
            "request_meta",
            0,
            None,
            "str",
            None,
            None,
            "Use recursive search.",
            None,
        ),
        (
            "sse_6",
            "trace_live",
            5,
            "reasoning_agent",
            10.0,
            "obs:child_summary",
            "obs_dispatch",
            1,
            0,
            "dict",
            None,
            None,
            None,
            json.dumps(
                {
                    "depth": 1,
                    "fanout_idx": 0,
                    "parent_depth": 0,
                    "parent_fanout_idx": None,
                    "model": "gemini-child",
                    "prompt": "Inspect shard A",
                    "visible_output_text": "Child answer",
                    "thought_text": "Child reasoning",
                    "raw_output": {"final_answer": "Child answer"},
                    "input_tokens": 60,
                    "output_tokens": 25,
                    "thought_tokens": 8,
                    "elapsed_ms": 900.0,
                    "final_answer": "Child answer",
                    "structured_output": {"outcome": "validated"},
                }
            ),
        ),
    ]
    conn.executemany(
        """
        INSERT INTO session_state_events (
            event_id, trace_id, seq, event_author, event_time, state_key,
            key_category, key_depth, key_fanout, value_type, value_int,
            value_float, value_text, value_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        sse_rows,
    )
    conn.commit()
    conn.close()

    snapshots = [
        {
            "session_id": "sess_live",
            "iteration": 0,
            "agent_type": "reasoning",
            "agent_name": "reasoning_agent",
            "input_tokens": 120,
            "chunks": [
                {
                    "category": "dynamic_instruction",
                    "title": "Dynamic Context (repo_url, root_prompt)",
                    "text": "Repository URL: https://example.com/repo\nOriginal query: Build the live page\nSkill instruction: Use recursive search.",
                    "char_count": 112,
                }
            ],
        },
        {
            "session_id": "sess_live",
            "iteration": 0,
            "agent_type": "worker",
            "agent_name": "child_reasoning_d1",
            "input_tokens": 60,
            "chunks": [
                {
                    "category": "worker_prompt",
                    "title": "Worker Prompt",
                    "text": "Inspect shard A",
                    "char_count": 15,
                }
            ],
        },
    ]
    with snapshots_path.open("w", encoding="utf-8") as handle:
        for entry in snapshots:
            handle.write(json.dumps(entry) + "\n")

    with outputs_path.open("w", encoding="utf-8") as handle:
        for entry in [
            {
                "session_id": "sess_live",
                "iteration": 0,
                "agent_name": "reasoning_agent",
                "output_text": "Root visible output",
            },
            {
                "session_id": "sess_live",
                "iteration": 0,
                "agent_name": "child_reasoning_d1",
                "output_text": "Child answer",
            },
        ]:
            handle.write(json.dumps(entry) + "\n")

    return db_path, snapshots_path, outputs_path


@pytest.fixture
def live_sources_subtree_iterations(tmp_path):
    db_path = tmp_path / "traces_tree.db"
    snapshots_path = tmp_path / "context_snapshots_tree.jsonl"
    outputs_path = tmp_path / "model_outputs_tree.jsonl"
    SqliteTracingPlugin(db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO traces (trace_id, session_id, app_name, start_time, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("trace_tree", "sess_tree", "rlm_adk", 1.0, "running"),
    )
    conn.commit()
    conn.close()

    snapshots = [
        {
            "session_id": "sess_tree",
            "iteration": 1,
            "timestamp": 10.0,
            "agent_type": "reasoning",
            "agent_name": "reasoning_agent",
            "input_tokens": 50,
            "chunks": [
                {
                    "category": "dynamic_instruction",
                    "title": "Dynamic Context",
                    "text": "Original query: Root iteration\nRepository URL: https://example.com/repo",
                    "char_count": 72,
                }
            ],
        },
        {
            "session_id": "sess_tree",
            "iteration": 1,
            "timestamp": 12.0,
            "agent_type": "worker",
            "agent_name": "child_reasoning_d1",
            "input_tokens": 30,
            "chunks": [
                {
                    "category": "worker_prompt",
                    "title": "Worker Prompt",
                    "text": "Child iteration one",
                    "char_count": 19,
                }
            ],
        },
        {
            "session_id": "sess_tree",
            "iteration": 1,
            "timestamp": 12.5,
            "agent_type": "worker",
            "agent_name": "child_reasoning_d2",
            "input_tokens": 15,
            "chunks": [
                {
                    "category": "worker_prompt",
                    "title": "Worker Prompt",
                    "text": "Grandchild from child iteration one",
                    "char_count": 35,
                }
            ],
        },
        {
            "session_id": "sess_tree",
            "iteration": 2,
            "timestamp": 14.0,
            "agent_type": "worker",
            "agent_name": "child_reasoning_d1",
            "input_tokens": 32,
            "chunks": [
                {
                    "category": "worker_prompt",
                    "title": "Worker Prompt",
                    "text": "Child iteration two",
                    "char_count": 19,
                }
            ],
        },
        {
            "session_id": "sess_tree",
            "iteration": 2,
            "timestamp": 14.5,
            "agent_type": "worker",
            "agent_name": "child_reasoning_d2",
            "input_tokens": 16,
            "chunks": [
                {
                    "category": "worker_prompt",
                    "title": "Worker Prompt",
                    "text": "Grandchild from child iteration two",
                    "char_count": 35,
                }
            ],
        },
    ]
    with snapshots_path.open("w", encoding="utf-8") as handle:
        for entry in snapshots:
            handle.write(json.dumps(entry) + "\n")

    outputs_path.write_text("", encoding="utf-8")
    return db_path, snapshots_path, outputs_path


def test_live_loader_builds_root_and_child_panes(live_sources):
    db_path, snapshots_path, outputs_path = live_sources
    loader = LiveDashboardLoader(
        traces_db_path=str(db_path),
        snapshots_path=str(snapshots_path),
        outputs_path=str(outputs_path),
    )

    snapshot = loader.load_session("sess_live")

    pane_ids = {pane.pane_id for pane in snapshot.panes}
    assert "d0:root" in pane_ids
    assert "d1:f0" in pane_ids
    assert snapshot.active_candidate_pane_id == "d1:f0"

    root_pane = next(pane for pane in snapshot.panes if pane.pane_id == "d0:root")
    child_pane = next(pane for pane in snapshot.panes if pane.pane_id == "d1:f0")
    banner_items = loader.build_banner_items(root_pane.invocations[-1], lineage=[root_pane.invocations[-1]])

    assert root_pane.repl_stdout == "hello world\n"
    assert any(item.raw_key == "repo_url" and item.present for item in banner_items)
    assert any(item.raw_key == "skill_instruction" and item.present for item in banner_items)
    assert child_pane.reasoning_visible_text == "Child answer"
    assert child_pane.request_chunks[0].text == "Inspect shard A"


@pytest.mark.asyncio
async def test_live_controller_manual_focus_disables_auto_follow(live_sources):
    db_path, snapshots_path, outputs_path = live_sources
    loader = LiveDashboardLoader(
        traces_db_path=str(db_path),
        snapshots_path=str(snapshots_path),
        outputs_path=str(outputs_path),
    )
    controller = LiveDashboardController(loader)

    await controller.select_session("sess_live")
    controller.set_active_pane("d0:root", manual=True)

    assert controller.state.auto_follow is False
    assert controller.state.run_state is not None
    assert controller.state.run_state.active_pane_id == "d0:root"


@pytest.mark.asyncio
async def test_live_controller_reuses_single_context_viewer(live_sources):
    db_path, snapshots_path, outputs_path = live_sources
    loader = LiveDashboardLoader(
        traces_db_path=str(db_path),
        snapshots_path=str(snapshots_path),
        outputs_path=str(outputs_path),
    )
    controller = LiveDashboardController(loader)

    await controller.select_session("sess_live")
    controller.set_active_pane("d0:root", manual=True)

    assert controller.state.run_state is not None
    root_node = controller.state.run_state.invocation_nodes[0]
    submitted = next(
        item
        for item in root_node.context_items
        if item.raw_key == "repl_submitted_code"
    )
    repl_result = next(
        item
        for item in root_node.context_items
        if item.raw_key == "last_repl_result"
    )

    controller.open_invocation_context_viewer(root_node.invocation, submitted, root_node.lineage)

    assert controller.state.context_selection is not None
    assert controller.state.context_selection.raw_key == "repl_submitted_code"
    assert "hello world" in controller.state.context_selection.text

    controller.open_invocation_context_viewer(root_node.invocation, repl_result, root_node.lineage)

    assert controller.state.context_selection is not None
    assert controller.state.context_selection.raw_key == "last_repl_result"
    assert '"stdout": "hello world\\n"' in controller.state.context_selection.text
    assert "print('hello world')" not in controller.state.context_selection.text

    controller.close_context_viewer()

    assert controller.state.context_selection is None


@pytest.mark.asyncio
async def test_live_controller_context_viewer_supports_dynamic_and_request_items(live_sources):
    db_path, snapshots_path, outputs_path = live_sources
    loader = LiveDashboardLoader(
        traces_db_path=str(db_path),
        snapshots_path=str(snapshots_path),
        outputs_path=str(outputs_path),
    )
    controller = LiveDashboardController(loader)

    await controller.select_session("sess_live")

    assert controller.state.run_state is not None
    child_node = controller.state.run_state.invocation_nodes[0].child_nodes[0]
    root_prompt = next(
        item
        for item in child_node.context_items
        if item.raw_key == "root_prompt"
    )
    request_chunk = next(
        item
        for item in child_node.context_items
        if item.scope == "request_chunk"
    )

    controller.open_invocation_context_viewer(child_node.invocation, root_prompt, child_node.lineage)

    assert controller.state.context_selection is not None
    assert controller.state.context_selection.raw_key == "root_prompt"
    assert controller.state.context_selection.text == "Build the live page"

    controller.open_invocation_context_viewer(child_node.invocation, request_chunk, child_node.lineage)

    assert controller.state.context_selection is not None
    assert controller.state.context_selection.raw_key == request_chunk.raw_key
    assert controller.state.context_selection.text == "Inspect shard A"


@pytest.mark.asyncio
async def test_live_controller_select_iteration_updates_only_subtree(
    live_sources_subtree_iterations,
):
    db_path, snapshots_path, outputs_path = live_sources_subtree_iterations
    loader = LiveDashboardLoader(
        traces_db_path=str(db_path),
        snapshots_path=str(snapshots_path),
        outputs_path=str(outputs_path),
    )
    controller = LiveDashboardController(loader)

    await controller.select_session("sess_tree")

    assert controller.state.run_state is not None
    root_node = controller.state.run_state.invocation_nodes[0]
    child_node = root_node.child_nodes[0]
    grandchild_node = child_node.child_nodes[0]

    assert [inv.iteration for inv in child_node.available_invocations] == [1, 2]
    assert child_node.invocation.iteration == 2
    assert grandchild_node.invocation.iteration == 2
    assert grandchild_node.invocation.request_chunks[0].text == "Grandchild from child iteration two"

    controller.select_iteration(
        child_node.pane_id,
        child_node.available_invocations[0].invocation_id,
    )

    assert controller.state.run_state is not None
    root_node = controller.state.run_state.invocation_nodes[0]
    child_node = root_node.child_nodes[0]
    grandchild_node = child_node.child_nodes[0]

    assert child_node.invocation.iteration == 1
    assert grandchild_node.invocation.iteration == 1
    assert grandchild_node.invocation.request_chunks[0].text == "Grandchild from child iteration one"
