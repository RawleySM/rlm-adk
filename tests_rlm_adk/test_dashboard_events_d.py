"""Agent D: Split-panel notebook UI component tests.

TDD cycles for rlm_adk/dashboard/components/notebook_panel.py and
controller/app wiring.

1. notebook_panel module imports without error
2. Model event provides correct data for banner rendering
3. children_of_tool_event returns children when execute_code has llm_query
4. Multiple children sorted by dispatch_call_index (batch selector order)
5. Controller load_event_tree + root_invocation_id
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
BASIC = FIXTURES / "dashboard_events_basic.jsonl"
BATCH = FIXTURES / "dashboard_events_batch.jsonl"


# ---------------------------------------------------------------------------
# Cycle 1 -- notebook_panel module imports without error
# ---------------------------------------------------------------------------


class TestNotebookPanelImports:
    """notebook_panel module is importable and exposes render_notebook_panel."""

    def test_notebook_panel_module_imports(self):
        """notebook_panel module imports without error."""
        from rlm_adk.dashboard.components.notebook_panel import render_notebook_panel

        assert callable(render_notebook_panel)

    def test_escape_html_function_exists(self):
        """_escape_html utility is available and works."""
        from rlm_adk.dashboard.components.notebook_panel import _escape_html

        assert _escape_html("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
        assert _escape_html("normal") == "normal"
        assert _escape_html("a & b") == "a &amp; b"


# ---------------------------------------------------------------------------
# Cycle 2 -- Model event provides correct data for banner rendering
# ---------------------------------------------------------------------------


class TestModelBannerDataExtraction:
    """Model event provides correct fields for banner rendering."""

    def test_model_event_fields_for_banner(self):
        """StepEvent with phase='model' has agent_name, depth, tokens, model."""
        from rlm_adk.dashboard.event_reader import build_tree, read_events

        events = read_events(BASIC)
        tree = build_tree(events)

        # First model event in inv0
        steps = tree.steps["reasoning_agent"]
        model_event, tool_event = steps[0]

        assert model_event.phase == "model"
        assert model_event.agent_name == "reasoning_agent"
        assert model_event.depth == 0
        assert model_event.input_tokens == 100
        assert model_event.output_tokens == 50
        assert model_event.thought_tokens == 10
        assert model_event.model == "gemini-2.5-flash"

    def test_child_model_event_fields(self):
        """Child invocation model events have correct depth and parent lineage."""
        from rlm_adk.dashboard.event_reader import build_tree, read_events

        events = read_events(BASIC)
        tree = build_tree(events)

        # First model event in inv1 (child)
        steps = tree.steps["child_reasoning_d1f0"]
        model_event, tool_event = steps[0]

        assert model_event.phase == "model"
        assert model_event.agent_name == "child_reasoning_d1f0"
        assert model_event.depth == 1
        assert model_event.parent_invocation_id == "inv0"  # still inv0 in fixture (invocation_id, not agent_name)
        assert model_event.parent_tool_call_id == "t1"


# ---------------------------------------------------------------------------
# Cycle 3 -- child_panel activates on llm_query
# ---------------------------------------------------------------------------


class TestChildPanelActivatesOnLlmQuery:
    """children_of_tool_event returns children when execute_code has llm_query_detected."""

    def test_execute_code_with_llm_query_has_children(self):
        """execute_code tool event with llm_query_detected=True spawns children."""
        from rlm_adk.dashboard.event_reader import (
            build_tree,
            children_of_tool_event,
            read_events,
        )

        events = read_events(BASIC)
        tree = build_tree(events)

        # t1 is execute_code with llm_query_detected=True
        # Verify the tool event itself reports llm_query_detected
        inv0_steps = tree.steps["reasoning_agent"]
        _m1, t1 = inv0_steps[1]
        assert t1 is not None
        assert t1.tool_name == "execute_code"
        assert t1.llm_query_detected is True
        assert t1.llm_query_count == 1

        # Verify children exist
        children = children_of_tool_event(tree, "t1")
        assert children == ["child_reasoning_d1f0"]

    def test_execute_code_without_llm_query_has_no_children(self):
        """execute_code without llm_query_detected has no children."""
        from rlm_adk.dashboard.event_reader import (
            build_tree,
            children_of_tool_event,
            read_events,
        )

        events = read_events(BASIC)
        tree = build_tree(events)

        # t2 is execute_code in inv1 (child), no llm_query
        inv1_steps = tree.steps["child_reasoning_d1f0"]
        _m2, t2 = inv1_steps[0]
        assert t2 is not None
        assert t2.tool_name == "execute_code"
        assert t2.llm_query_detected is False

        # No children spawned
        children = children_of_tool_event(tree, "t2")
        assert children == []


# ---------------------------------------------------------------------------
# Cycle 4 -- batch selector tabs in dispatch order
# ---------------------------------------------------------------------------


class TestBatchSelectorTabsInDispatchOrder:
    """Multiple children sorted by dispatch_call_index for tab ordering."""

    def test_batch_children_dispatch_order(self):
        """Batch fixture children are in dispatch_call_index order, not completion order."""
        from rlm_adk.dashboard.event_reader import (
            build_tree,
            children_of_tool_event,
            read_events,
        )

        events = read_events(BATCH)
        tree = build_tree(events)

        # t0 spawned 3 children that completed out of order
        children = children_of_tool_event(tree, "t0")
        assert children == ["child_d1f0", "child_d1f1", "child_d1f2"]

    def test_batch_child_count_matches_llm_query_count(self):
        """Number of batch children matches llm_query_count on the parent tool event."""
        from rlm_adk.dashboard.event_reader import (
            build_tree,
            children_of_tool_event,
            read_events,
        )

        events = read_events(BATCH)
        tree = build_tree(events)

        # Verify the parent tool event's llm_query_count
        inv0_steps = tree.steps["reasoning_agent"]
        _m0, t0 = inv0_steps[0]
        assert t0 is not None
        assert t0.llm_query_count == 3

        children = children_of_tool_event(tree, "t0")
        assert len(children) == t0.llm_query_count


# ---------------------------------------------------------------------------
# Cycle 5 -- Controller load_event_tree + root_invocation_id
# ---------------------------------------------------------------------------


class TestControllerLoadEventTree:
    """Controller loads JSONL and builds tree, finds root invocation."""

    def test_load_event_tree_returns_tree(self, tmp_path):
        """load_event_tree reads JSONL and returns InvocationTree."""
        from rlm_adk.dashboard.event_reader import InvocationTree
        from rlm_adk.dashboard.live_controller import LiveDashboardController

        # Copy basic fixture to tmp_path
        jsonl_path = tmp_path / "dashboard_events.jsonl"
        jsonl_path.write_text(BASIC.read_text())

        # Create controller with mock loader
        from unittest.mock import MagicMock

        mock_loader = MagicMock()
        controller = LiveDashboardController(mock_loader)

        tree = controller.load_event_tree(str(jsonl_path))

        assert tree is not None
        assert isinstance(tree, InvocationTree)
        assert "reasoning_agent" in tree.by_inv
        assert "child_reasoning_d1f0" in tree.by_inv

    def test_load_event_tree_returns_none_for_missing_file(self):
        """load_event_tree returns None when file doesn't exist."""
        from unittest.mock import MagicMock

        from rlm_adk.dashboard.live_controller import LiveDashboardController

        mock_loader = MagicMock()
        controller = LiveDashboardController(mock_loader)

        result = controller.load_event_tree("/nonexistent/path.jsonl")
        assert result is None

    def test_root_invocation_id_finds_root(self, tmp_path):
        """root_invocation_id returns the invocation with no parent."""
        from unittest.mock import MagicMock

        from rlm_adk.dashboard.live_controller import LiveDashboardController

        jsonl_path = tmp_path / "dashboard_events.jsonl"
        jsonl_path.write_text(BASIC.read_text())

        mock_loader = MagicMock()
        controller = LiveDashboardController(mock_loader)

        tree = controller.load_event_tree(str(jsonl_path))
        assert tree is not None

        root_id = controller.root_invocation_id(tree)
        assert root_id == "reasoning_agent"

    def test_root_invocation_id_batch_fixture(self, tmp_path):
        """root_invocation_id works with batch fixture."""
        from unittest.mock import MagicMock

        from rlm_adk.dashboard.live_controller import LiveDashboardController

        jsonl_path = tmp_path / "dashboard_events.jsonl"
        jsonl_path.write_text(BATCH.read_text())

        mock_loader = MagicMock()
        controller = LiveDashboardController(mock_loader)

        tree = controller.load_event_tree(str(jsonl_path))
        assert tree is not None

        root_id = controller.root_invocation_id(tree)
        assert root_id == "reasoning_agent"

    def test_load_event_tree_empty_file(self, tmp_path):
        """load_event_tree returns None for empty file."""
        from unittest.mock import MagicMock

        from rlm_adk.dashboard.live_controller import LiveDashboardController

        jsonl_path = tmp_path / "dashboard_events.jsonl"
        jsonl_path.write_text("")

        mock_loader = MagicMock()
        controller = LiveDashboardController(mock_loader)

        result = controller.load_event_tree(str(jsonl_path))
        assert result is None
