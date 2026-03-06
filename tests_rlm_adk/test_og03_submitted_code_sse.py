"""Tests for OG-03: repl_submitted_code* in session_state_events."""
import sqlite3
from unittest.mock import MagicMock

import pytest

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin, _should_capture, _categorize_key


@pytest.fixture
def plugin_and_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    return plugin, db_path


def _make_invocation_context():
    ctx = MagicMock()
    ctx.session.id = "sess_1"
    ctx.session.user_id = "user_1"
    ctx.app_name = "test"
    ctx.session.state = {}
    return ctx


class TestSubmittedCodeCapture:
    def test_should_capture_repl_submitted_code(self):
        assert _should_capture("repl_submitted_code") is True

    def test_should_capture_repl_submitted_code_preview(self):
        assert _should_capture("repl_submitted_code_preview") is True

    def test_should_capture_repl_submitted_code_hash(self):
        assert _should_capture("repl_submitted_code_hash") is True

    def test_should_capture_repl_submitted_code_chars(self):
        assert _should_capture("repl_submitted_code_chars") is True


class TestSubmittedCodeCategory:
    def test_categorize_repl_submitted_code(self):
        assert _categorize_key("repl_submitted_code") == "repl"

    def test_categorize_repl_submitted_code_preview(self):
        assert _categorize_key("repl_submitted_code_preview") == "repl"

    def test_categorize_repl_submitted_code_hash(self):
        assert _categorize_key("repl_submitted_code_hash") == "repl"

    def test_categorize_repl_submitted_code_chars(self):
        assert _categorize_key("repl_submitted_code_chars") == "repl"


class TestSubmittedCodeSSEPersistence:
    @pytest.mark.asyncio
    async def test_submitted_code_keys_appear_in_sse(self, plugin_and_db):
        plugin, db_path = plugin_and_db
        inv_ctx = _make_invocation_context()
        await plugin.before_run_callback(invocation_context=inv_ctx)

        # Simulate an event with repl_submitted_code state_delta
        event = MagicMock()
        event.author = "reasoning_agent"
        event.actions.state_delta = {
            "repl_submitted_code": "print('hello')",
            "repl_submitted_code_preview": "print('hello')",
            "repl_submitted_code_hash": "abc123def456",
            "repl_submitted_code_chars": 14,
        }
        event.actions.artifact_delta = {}

        await plugin.on_event_callback(invocation_context=inv_ctx, event=event)

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT state_key, key_category FROM session_state_events ORDER BY seq"
        ).fetchall()
        conn.close()

        keys_found = {row[0] for row in rows}
        assert "repl_submitted_code" in keys_found
        assert "repl_submitted_code_preview" in keys_found
        assert "repl_submitted_code_hash" in keys_found
        assert "repl_submitted_code_chars" in keys_found

        # All should be categorized as 'repl'
        for row in rows:
            assert row[1] == "repl", f"Expected 'repl' category for {row[0]}, got {row[1]}"
