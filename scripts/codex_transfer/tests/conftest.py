"""Shared fixtures for codex_transfer tests."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_home(tmp_path):
    """Provide a temporary home directory with .claude structure."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "handoffs").mkdir()
    return tmp_path


@pytest.fixture
def fake_credentials(tmp_home):
    """Write a fake credentials file and return the path."""
    creds = {
        "claudeAiOauth": {
            "accessToken": "test-access-token-abc123",
            "refreshToken": "test-refresh-token",
            "expiresAt": "2099-01-01T00:00:00Z",
            "scopes": ["user:inference"],
            "subscriptionType": "max_5",
            "rateLimitTier": "standard",
        }
    }
    creds_path = tmp_home / ".claude" / ".credentials.json"
    creds_path.write_text(json.dumps(creds))
    return creds_path


@pytest.fixture
def session_id():
    """Return a fixed session ID for testing."""
    return "test-session-1234"


@pytest.fixture
def bridge_path(tmp_path, session_id):
    """Return bridge file path using tmp_path."""
    return tmp_path / f"claude_quota_{session_id}.json"


@pytest.fixture
def sample_bridge_data():
    """Return sample bridge file data at low usage."""
    return {
        "five_hour_pct": 7.0,
        "seven_day_pct": 6.0,
        "resets_at": "2026-03-14T06:00:00Z",
        "extra_usage_enabled": True,
        "ts": 1710000000,
        "handoff_requested": False,
        "handoff_ready": False,
        "tool_calls_since_request": 0,
    }


@pytest.fixture
def high_usage_bridge_data():
    """Return bridge data above the default 80% threshold."""
    return {
        "five_hour_pct": 85.0,
        "seven_day_pct": 60.0,
        "resets_at": "2026-03-14T06:00:00Z",
        "extra_usage_enabled": True,
        "ts": 1710000000,
        "handoff_requested": False,
        "handoff_ready": False,
        "tool_calls_since_request": 0,
    }


@pytest.fixture
def sample_usage_response():
    """Return sample API usage response."""
    return {
        "five_hour": {
            "used": 700,
            "limit": 10000,
            "resets_at": "2026-03-14T06:00:00Z",
        },
        "seven_day": {
            "used": 6000,
            "limit": 100000,
            "resets_at": "2026-03-20T00:00:00Z",
        },
        "extra_usage": {
            "enabled": True,
        },
    }


@pytest.fixture
def usage_cache_path(tmp_home):
    """Return path for cached usage data."""
    return tmp_home / ".claude" / "usage_cache.json"
