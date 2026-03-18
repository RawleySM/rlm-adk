"""Tests for dashboard UI polish and status/presence fixes (GAP-10 through GAP-14).

Step 6: UI-Polish (GAP-10, GAP-11, GAP-12)
Step 7: Status-Signal (GAP-14)
Step 8: Presence-Fix (GAP-13)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rlm_adk.dashboard.live_loader import LiveDashboardLoader
from rlm_adk.dashboard.live_models import (
    LiveContextBannerItem,
    LiveInvocation,
    LiveInvocationNode,
    LiveRequestChunk,
    LiveStateItem,
    LiveToolEvent,
)
from rlm_adk.state import REASONING_VISIBLE_OUTPUT_TEXT

pytestmark = [pytest.mark.unit_nondefault]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_invocation(
    *,
    depth: int = 0,
    state_items: list[LiveStateItem] | None = None,
    tool_events: list[LiveToolEvent] | None = None,
    request_chunks: list[LiveRequestChunk] | None = None,
    reasoning_visible_text: str = "",
    repl_submission: str = "",
) -> LiveInvocation:
    """Build a minimal LiveInvocation for testing."""
    return LiveInvocation(
        invocation_id="inv-1",
        pane_id="d0:root",
        depth=depth,
        fanout_idx=None,
        agent_name="reasoning_agent",
        model="gemini-test",
        model_version=None,
        status="running",
        iteration=1,
        input_tokens=100,
        output_tokens=50,
        thought_tokens=0,
        elapsed_ms=500.0,
        request_chunks=request_chunks or [],
        state_items=state_items or [],
        child_summaries=[],
        repl_submission=repl_submission,
        repl_expanded_code="",
        repl_stdout="",
        repl_stderr="",
        reasoning_visible_text=reasoning_visible_text,
        reasoning_thought_text="",
        structured_output=None,
        raw_payload={},
        model_events=[],
        tool_events=tool_events or [],
    )


def _make_tool_event() -> LiveToolEvent:
    """Build a minimal LiveToolEvent."""
    return LiveToolEvent(
        telemetry_id="tel-1",
        agent_name="reasoning_agent",
        depth=0,
        fanout_idx=None,
        tool_name="execute_code",
        start_time=1.0,
        end_time=2.0,
        duration_ms=1000.0,
        result_preview="OK",
        repl_has_errors=False,
        repl_has_output=True,
        repl_llm_calls=0,
        repl_stdout_len=10,
        repl_stderr_len=0,
    )


def _make_state_item(key: str, value: str, *, depth: int = 0) -> LiveStateItem:
    """Build a minimal LiveStateItem."""
    return LiveStateItem(
        raw_key=key,
        base_key=key,
        depth=depth,
        fanout_idx=None,
        value=value,
        value_type="str",
        event_time=1.0,
        seq=1,
    )


def _make_node(
    *,
    parent_code_text: str = "",
    parent_stdout_text: str = "",
    parent_stderr_text: str = "",
    invocation: LiveInvocation | None = None,
    context_items: list[LiveContextBannerItem] | None = None,
) -> LiveInvocationNode:
    """Build a minimal LiveInvocationNode."""
    inv = invocation or _make_invocation()
    return LiveInvocationNode(
        pane_id="d0:root",
        invocation=inv,
        available_invocations=[inv],
        context_items=context_items or [],
        child_nodes=[],
        lineage=[inv],
        parent_code_text=parent_code_text,
        parent_stdout_text=parent_stdout_text,
        parent_stderr_text=parent_stderr_text,
        invocation_context_tokens=100,
    )


# ===========================================================================
# Step 6: GAP-10 — tool call placeholder for empty reasoning_visible_output_text
# ===========================================================================


class TestGap10ToolCallPlaceholder:
    """build_banner_items sets display_value_preview for tool-call-only turns."""

    def test_tool_call_placeholder_when_empty_text_and_tool_events(self):
        """When reasoning_visible_output_text is empty and tool_events is non-empty,
        display_value_preview should be '(tool call -- no text output)'."""
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REASONING_VISIBLE_OUTPUT_TEXT, ""),
            ],
            tool_events=[_make_tool_event()],
        )
        items = loader.build_banner_items(invocation)

        vis_items = [i for i in items if i.raw_key == REASONING_VISIBLE_OUTPUT_TEXT]
        assert len(vis_items) == 1
        assert vis_items[0].display_value_preview == "(tool call \u2014 no text output)"

    def test_no_placeholder_when_text_present(self):
        """When reasoning_visible_output_text has content, preview should show that content."""
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REASONING_VISIBLE_OUTPUT_TEXT, "Hello world"),
            ],
            tool_events=[_make_tool_event()],
        )
        items = loader.build_banner_items(invocation)

        vis_items = [i for i in items if i.raw_key == REASONING_VISIBLE_OUTPUT_TEXT]
        assert len(vis_items) == 1
        assert vis_items[0].display_value_preview == "Hello world"

    def test_no_placeholder_when_no_tool_events(self):
        """When reasoning_visible_output_text is empty but no tool_events,
        display_value_preview should remain empty."""
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REASONING_VISIBLE_OUTPUT_TEXT, ""),
            ],
            tool_events=[],
        )
        items = loader.build_banner_items(invocation)

        vis_items = [i for i in items if i.raw_key == REASONING_VISIBLE_OUTPUT_TEXT]
        assert len(vis_items) == 1
        assert vis_items[0].display_value_preview == ""


# ===========================================================================
# Step 6: GAP-11 — always render code chip in REPL panel
# ===========================================================================


class TestGap11AlwaysRenderCodeChip:
    """_repl_panel always renders a code action chip even when parent_code_text is empty."""

    def test_code_chip_rendered_when_code_empty(self):
        """_repl_panel should render the 'code' chip even when parent_code_text is empty."""
        # Import the function
        from rlm_adk.dashboard.components.live_invocation_tree import _repl_panel

        node = _make_node(parent_code_text="")

        # We can't easily render NiceGUI components in tests, so we patch ui
        # and check the structure. Use a recording approach.
        calls = []

        def recording_on_open_repl_output(inv_id, text, label):
            calls.append({"inv_id": inv_id, "text": text, "label": label})

        # Patch NiceGUI ui to capture what gets rendered
        with patch("rlm_adk.dashboard.components.live_invocation_tree.ui") as mock_ui:
            # Set up the mock chain
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label

            _repl_panel(node, on_open_repl_output=recording_on_open_repl_output)

            # Find all label calls — should include "code", "stdout", "stderr", "REPL"
            label_texts = [call.args[0] for call in mock_ui.label.call_args_list]
            assert "code" in label_texts, f"Expected 'code' chip but got labels: {label_texts}"

    def test_code_chip_click_shows_placeholder_for_empty(self):
        """Clicking empty code chip should show 'No code captured yet' text."""
        from rlm_adk.dashboard.components.live_invocation_tree import _repl_panel

        node = _make_node(parent_code_text="")
        captured = []

        def recording_on_open_repl_output(inv_id, text, label):
            captured.append({"text": text, "label": label})

        with patch("rlm_adk.dashboard.components.live_invocation_tree.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label

            _repl_panel(node, on_open_repl_output=recording_on_open_repl_output)

            # Find the on("click.stop", ...) call for the code chip
            # _action_chip creates a div.on("click.stop", lambda: on_click())
            # We need to invoke the lambda to see what text it sends
            # Collect all on("click.stop") lambdas from mock_element.on calls
            click_lambdas = []
            for call in mock_element.on.call_args_list:
                if call.args and call.args[0] == "click.stop":
                    click_lambdas.append(call.args[1])

            # Invoke first click lambda (code chip is first after REPL label)
            # The order: REPL label, then code chip, stdout chip, stderr chip
            # _action_chip wraps on_click in a lambda _e: on_click()
            # so we need to call it with a dummy event
            assert len(click_lambdas) >= 1
            click_lambdas[0](None)  # invoke the code chip click

            assert len(captured) == 1
            assert captured[0]["text"] == "No code captured yet"


# ===========================================================================
# Step 6: GAP-12 — display "n/a" for empty state keys
# ===========================================================================


class TestGap12NaForEmptyStateKeys:
    """_context_chip renders 'n/a' when token_count==0 and display_value_preview is empty."""

    def test_na_for_zero_tokens_empty_preview(self):
        """When token_count==0 and display_value_preview is empty, chip text should say 'n/a'."""
        from rlm_adk.dashboard.components.live_invocation_tree import _context_chip

        item = LiveContextBannerItem(
            label="some_key",
            raw_key="some_key",
            scope="state_key",
            present=False,
            token_count=0,
            token_count_is_exact=False,
            source_kind="state_key",
            display_value_preview="",
        )
        invocation = _make_invocation()

        with patch("rlm_adk.dashboard.components.live_invocation_tree.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label
            mock_label.tooltip.return_value = mock_label

            _context_chip(invocation, [invocation], item, on_open_context=lambda *a: None)

            # The label should contain "n/a"
            label_text = mock_ui.label.call_args_list[0].args[0]
            assert "n/a" in label_text, f"Expected 'n/a' in '{label_text}'"
            assert "~0 tok" not in label_text, f"Should not contain '~0 tok' in '{label_text}'"

    def test_exact_tokens_for_non_zero(self):
        """When token_count > 0 and exact, show 'N tok'."""
        from rlm_adk.dashboard.components.live_invocation_tree import _context_chip

        item = LiveContextBannerItem(
            label="some_key",
            raw_key="some_key",
            scope="state_key",
            present=True,
            token_count=42,
            token_count_is_exact=True,
            source_kind="state_key",
            display_value_preview="hello",
        )
        invocation = _make_invocation()

        with patch("rlm_adk.dashboard.components.live_invocation_tree.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label
            mock_label.tooltip.return_value = mock_label

            _context_chip(invocation, [invocation], item, on_open_context=lambda *a: None)

            label_text = mock_ui.label.call_args_list[0].args[0]
            assert "42 tok" in label_text
            assert "~" not in label_text

    def test_approximate_tokens_for_non_zero_non_exact(self):
        """When token_count > 0 and not exact, show '~N tok'."""
        from rlm_adk.dashboard.components.live_invocation_tree import _context_chip

        item = LiveContextBannerItem(
            label="some_key",
            raw_key="some_key",
            scope="state_key",
            present=False,
            token_count=10,
            token_count_is_exact=False,
            source_kind="state_key",
            display_value_preview="abc",
        )
        invocation = _make_invocation()

        with patch("rlm_adk.dashboard.components.live_invocation_tree.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label
            mock_label.tooltip.return_value = mock_label

            _context_chip(invocation, [invocation], item, on_open_context=lambda *a: None)

            label_text = mock_ui.label.call_args_list[0].args[0]
            assert "~10 tok" in label_text

    def test_na_when_zero_tokens_zero_preview_exact(self):
        """Even if token_count_is_exact, 0 tokens + empty preview => n/a."""
        from rlm_adk.dashboard.components.live_invocation_tree import _context_chip

        item = LiveContextBannerItem(
            label="some_key",
            raw_key="some_key",
            scope="state_key",
            present=False,
            token_count=0,
            token_count_is_exact=True,
            source_kind="state_key",
            display_value_preview="",
        )
        invocation = _make_invocation()

        with patch("rlm_adk.dashboard.components.live_invocation_tree.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label
            mock_label.tooltip.return_value = mock_label

            _context_chip(invocation, [invocation], item, on_open_context=lambda *a: None)

            label_text = mock_ui.label.call_args_list[0].args[0]
            assert "n/a" in label_text


# ===========================================================================
# Step 7: GAP-14 — fix status badge accuracy
# ===========================================================================


class TestGap14NormalizeStatus:
    """_normalize_status falls back to telemetry_model_count when total_calls=0."""

    def test_running_with_telemetry_fallback(self):
        """When total_calls=0 but telemetry_model_count > 0, status should be 'running'."""
        result = LiveDashboardLoader._normalize_status(
            "running", total_calls=0, telemetry_model_count=5
        )
        assert result == "running"

    def test_idle_when_no_calls_and_no_telemetry(self):
        """When total_calls=0 and telemetry_model_count=0, status should be 'idle'."""
        result = LiveDashboardLoader._normalize_status(
            "running", total_calls=0, telemetry_model_count=0
        )
        assert result == "idle"

    def test_running_when_total_calls_positive(self):
        """When total_calls > 0, status should be 'running' regardless of telemetry."""
        result = LiveDashboardLoader._normalize_status(
            "running", total_calls=3, telemetry_model_count=0
        )
        assert result == "running"

    def test_completed_always_returns_completed(self):
        """Completed status is never overridden."""
        result = LiveDashboardLoader._normalize_status(
            "completed", total_calls=0, telemetry_model_count=0
        )
        assert result == "completed"

    def test_error_always_returns_error(self):
        """Error status is never overridden."""
        result = LiveDashboardLoader._normalize_status(
            "error", total_calls=0, telemetry_model_count=5
        )
        assert result == "error"

    def test_backward_compat_no_telemetry_arg(self):
        """Default telemetry_model_count=0 preserves backward compatibility."""
        result = LiveDashboardLoader._normalize_status("running", total_calls=5)
        assert result == "running"


# ===========================================================================
# Step 8: GAP-13 — simplify state key presence detection
# ===========================================================================


class TestGap13PresenceDetection:
    """present flag uses simple bool(display_text) instead of substring match."""

    def test_present_true_when_display_text_nonempty(self):
        """State key with non-empty display_text should have present=True."""
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        # Create an invocation with a state item that has content but
        # whose preview[:80] would NOT match in request_text (breaking old logic).
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REASONING_VISIBLE_OUTPUT_TEXT, "some unique content xyz"),
            ],
            request_chunks=[],
        )
        items = loader.build_banner_items(invocation)

        vis_items = [i for i in items if i.raw_key == REASONING_VISIBLE_OUTPUT_TEXT]
        assert len(vis_items) == 1
        assert vis_items[0].present is True, (
            "State key with non-empty display_text should be present=True"
        )

    def test_present_false_when_display_text_empty(self):
        """State key with empty display_text should have present=False."""
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REASONING_VISIBLE_OUTPUT_TEXT, ""),
            ],
        )
        items = loader.build_banner_items(invocation)

        vis_items = [i for i in items if i.raw_key == REASONING_VISIBLE_OUTPUT_TEXT]
        assert len(vis_items) == 1
        assert vis_items[0].present is False

    def test_present_true_without_substring_match(self):
        """present should be True even when display_text is NOT in request_text."""
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        # The old substring logic would fail here because the state value
        # is NOT in the request text.
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REASONING_VISIBLE_OUTPUT_TEXT, "value not in request"),
            ],
            request_chunks=[
                LiveRequestChunk(
                    chunk_id="chunk-1",
                    category="system",
                    title="System",
                    text="completely different text",
                    char_count=24,
                    token_count=6,
                ),
            ],
        )
        items = loader.build_banner_items(invocation)

        vis_items = [i for i in items if i.raw_key == REASONING_VISIBLE_OUTPUT_TEXT]
        assert len(vis_items) == 1
        assert vis_items[0].present is True, (
            "present should be True for non-empty display_text regardless of substring match"
        )

    def test_no_repl_special_case(self):
        """REPL keys should also use simple bool(display_text) logic."""
        from rlm_adk.state import REPL_SUBMITTED_CODE

        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        invocation = _make_invocation(
            state_items=[
                _make_state_item(REPL_SUBMITTED_CODE, "print('hi')"),
            ],
            repl_submission="print('hi')",
        )
        items = loader.build_banner_items(invocation)

        repl_items = [i for i in items if i.raw_key == REPL_SUBMITTED_CODE]
        assert len(repl_items) == 1
        # With the new logic, present is bool("print('hi')") = True
        assert repl_items[0].present is True
