"""Tests for statusline_quota module — RED phase first."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.codex_transfer.statusline_quota import (
    read_cached_usage,
    format_quota_display,
    get_ansi_color,
    COLOR_GREEN,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_RESET,
)


@pytest.fixture
def usage_cache(tmp_path):
    """Create a valid usage cache file."""
    cache_path = tmp_path / "usage_cache.json"
    cache_data = {
        "ts": time.time(),
        "data": {
            "five_hour": {
                "used": 3000,
                "limit": 10000,
                "resets_at": "2026-03-14T06:00:00Z",
            },
            "seven_day": {
                "used": 20000,
                "limit": 100000,
                "resets_at": "2026-03-20T00:00:00Z",
            },
            "extra_usage": {"enabled": True},
        },
    }
    cache_path.write_text(json.dumps(cache_data))
    return cache_path


class TestReadCachedUsage:
    """Test reading cached usage data."""

    def test_reads_valid_cache(self, usage_cache):
        """Should read and return cached data."""
        result = read_cached_usage(usage_cache)
        assert result is not None
        assert "five_hour" in result

    def test_returns_none_on_missing(self, tmp_path):
        """Should return None when cache file missing."""
        result = read_cached_usage(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_on_corrupt(self, tmp_path):
        """Should return None on invalid JSON."""
        path = tmp_path / "usage_cache.json"
        path.write_text("bad json")
        result = read_cached_usage(path)
        assert result is None

    def test_returns_data_regardless_of_age(self, tmp_path):
        """Status line should show data even if stale (no TTL filtering)."""
        cache_path = tmp_path / "usage_cache.json"
        cache_data = {
            "ts": time.time() - 3600,  # 1 hour old
            "data": {
                "five_hour": {"used": 100, "limit": 10000, "resets_at": "x"},
                "seven_day": {"used": 1000, "limit": 100000, "resets_at": "x"},
                "extra_usage": {"enabled": False},
            },
        }
        cache_path.write_text(json.dumps(cache_data))
        result = read_cached_usage(cache_path)
        assert result is not None


class TestGetAnsiColor:
    """Test ANSI color selection based on percentage."""

    def test_green_below_50(self):
        """Should return green for <50%."""
        assert get_ansi_color(0.0) == COLOR_GREEN
        assert get_ansi_color(25.0) == COLOR_GREEN
        assert get_ansi_color(49.9) == COLOR_GREEN

    def test_yellow_50_to_79(self):
        """Should return yellow for 50-79%."""
        assert get_ansi_color(50.0) == COLOR_YELLOW
        assert get_ansi_color(65.0) == COLOR_YELLOW
        assert get_ansi_color(79.9) == COLOR_YELLOW

    def test_red_80_and_above(self):
        """Should return red for >=80%."""
        assert get_ansi_color(80.0) == COLOR_RED
        assert get_ansi_color(95.0) == COLOR_RED
        assert get_ansi_color(100.0) == COLOR_RED


class TestFormatQuotaDisplay:
    """Test the output format for the status line."""

    def test_format_with_low_usage(self):
        """Should format as [quota: N%] with green color."""
        data = {
            "five_hour": {"used": 700, "limit": 10000, "resets_at": "x"},
            "seven_day": {"used": 6000, "limit": 100000, "resets_at": "x"},
            "extra_usage": {"enabled": True},
        }
        result = format_quota_display(data)
        assert "7%" in result
        assert "quota" in result.lower()
        assert COLOR_GREEN in result
        assert COLOR_RESET in result

    def test_format_with_medium_usage(self):
        """Should use yellow color for 50-79%."""
        data = {
            "five_hour": {"used": 6000, "limit": 10000, "resets_at": "x"},
            "seven_day": {"used": 6000, "limit": 100000, "resets_at": "x"},
            "extra_usage": {"enabled": True},
        }
        result = format_quota_display(data)
        assert "60%" in result
        assert COLOR_YELLOW in result

    def test_format_with_high_usage(self):
        """Should use red color for >=80%."""
        data = {
            "five_hour": {"used": 9000, "limit": 10000, "resets_at": "x"},
            "seven_day": {"used": 6000, "limit": 100000, "resets_at": "x"},
            "extra_usage": {"enabled": True},
        }
        result = format_quota_display(data)
        assert "90%" in result
        assert COLOR_RED in result

    def test_format_with_zero_limit(self):
        """Should handle zero limit without error."""
        data = {
            "five_hour": {"used": 0, "limit": 0, "resets_at": "x"},
            "seven_day": {"used": 0, "limit": 0, "resets_at": "x"},
            "extra_usage": {"enabled": False},
        }
        result = format_quota_display(data)
        assert "0%" in result

    def test_returns_empty_on_none(self):
        """Should return empty string when data is None."""
        result = format_quota_display(None)
        assert result == ""

    def test_format_is_bracket_wrapped(self):
        """Output should be wrapped in square brackets."""
        data = {
            "five_hour": {"used": 5000, "limit": 10000, "resets_at": "x"},
            "seven_day": {"used": 6000, "limit": 100000, "resets_at": "x"},
            "extra_usage": {"enabled": True},
        }
        result = format_quota_display(data)
        # Strip ANSI codes to check bracket structure
        stripped = result.replace(COLOR_GREEN, "").replace(COLOR_YELLOW, "").replace(
            COLOR_RED, ""
        ).replace(COLOR_RESET, "")
        assert stripped.startswith("[")
        assert stripped.endswith("]")
