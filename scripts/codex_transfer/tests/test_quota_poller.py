"""Tests for quota_poller module — RED phase first."""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from http.client import HTTPResponse
from io import BytesIO

import pytest

# Module under test
from scripts.codex_transfer.quota_poller import (
    read_oauth_token,
    fetch_usage,
    get_cached_usage,
    parse_usage,
    write_bridge_file,
    poll_quota,
    CACHE_TTL_SECONDS,
)


class TestReadOAuthToken:
    """Test reading OAuth token from credentials file."""

    def test_reads_access_token(self, fake_credentials, tmp_home):
        """Should extract accessToken from claudeAiOauth."""
        token = read_oauth_token(credentials_path=fake_credentials)
        assert token == "test-access-token-abc123"

    def test_raises_on_missing_file(self, tmp_path):
        """Should raise FileNotFoundError when credentials file missing."""
        missing = tmp_path / ".claude" / ".credentials.json"
        with pytest.raises(FileNotFoundError):
            read_oauth_token(credentials_path=missing)

    def test_raises_on_missing_oauth_key(self, tmp_home):
        """Should raise KeyError when claudeAiOauth missing."""
        creds_path = tmp_home / ".claude" / ".credentials.json"
        creds_path.write_text(json.dumps({"other": {}}))
        with pytest.raises(KeyError):
            read_oauth_token(credentials_path=creds_path)

    def test_raises_on_missing_access_token(self, tmp_home):
        """Should raise KeyError when accessToken missing."""
        creds_path = tmp_home / ".claude" / ".credentials.json"
        creds_path.write_text(json.dumps({"claudeAiOauth": {"refreshToken": "x"}}))
        with pytest.raises(KeyError):
            read_oauth_token(credentials_path=creds_path)


class TestFetchUsage:
    """Test HTTP fetch of usage data."""

    def test_calls_api_with_correct_headers(self, sample_usage_response):
        """Should call GET with Bearer token and beta header."""
        response_body = json.dumps(sample_usage_response).encode()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = fetch_usage("test-token-123")

            # Verify the request was made
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.get_header("Authorization") == "Bearer test-token-123"
            assert request.get_header("Anthropic-beta") == "oauth-2025-04-20"
            assert "usage" in request.full_url

    def test_returns_parsed_json(self, sample_usage_response):
        """Should return parsed JSON dict."""
        response_body = json.dumps(sample_usage_response).encode()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = fetch_usage("test-token")
            assert result == sample_usage_response

    def test_raises_on_http_error(self):
        """Should raise on non-200 response."""
        from urllib.error import HTTPError

        with patch(
            "urllib.request.urlopen",
            side_effect=HTTPError(
                url="https://api.anthropic.com/api/oauth/usage",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=BytesIO(b""),
            ),
        ):
            with pytest.raises(HTTPError):
                fetch_usage("bad-token")


class TestGetCachedUsage:
    """Test caching behavior."""

    def test_returns_none_when_no_cache(self, tmp_path):
        """Should return None when cache file doesn't exist."""
        cache_path = tmp_path / "usage_cache.json"
        result = get_cached_usage(cache_path=cache_path)
        assert result is None

    def test_returns_cached_data_within_ttl(self, tmp_path, sample_usage_response):
        """Should return cached data if within TTL."""
        cache_path = tmp_path / "usage_cache.json"
        cache_data = {
            "ts": time.time(),  # Just now
            "data": sample_usage_response,
        }
        cache_path.write_text(json.dumps(cache_data))
        result = get_cached_usage(cache_path=cache_path)
        assert result == sample_usage_response

    def test_returns_none_when_cache_expired(self, tmp_path, sample_usage_response):
        """Should return None when cache is older than TTL."""
        cache_path = tmp_path / "usage_cache.json"
        cache_data = {
            "ts": time.time() - CACHE_TTL_SECONDS - 10,  # Expired
            "data": sample_usage_response,
        }
        cache_path.write_text(json.dumps(cache_data))
        result = get_cached_usage(cache_path=cache_path)
        assert result is None

    def test_returns_none_on_corrupt_cache(self, tmp_path):
        """Should return None on invalid JSON cache."""
        cache_path = tmp_path / "usage_cache.json"
        cache_path.write_text("not json")
        result = get_cached_usage(cache_path=cache_path)
        assert result is None


class TestParseUsage:
    """Test parsing raw API response to percentages."""

    def test_calculates_five_hour_pct(self, sample_usage_response):
        """Should compute five_hour utilization as percentage."""
        result = parse_usage(sample_usage_response)
        # 700 / 10000 = 7.0%
        assert result["five_hour_pct"] == 7.0

    def test_calculates_seven_day_pct(self, sample_usage_response):
        """Should compute seven_day utilization as percentage."""
        result = parse_usage(sample_usage_response)
        # 6000 / 100000 = 6.0%
        assert result["seven_day_pct"] == 6.0

    def test_includes_resets_at(self, sample_usage_response):
        """Should include five_hour resets_at timestamp."""
        result = parse_usage(sample_usage_response)
        assert result["resets_at"] == "2026-03-14T06:00:00Z"

    def test_includes_extra_usage_enabled(self, sample_usage_response):
        """Should include extra_usage enabled flag."""
        result = parse_usage(sample_usage_response)
        assert result["extra_usage_enabled"] is True

    def test_handles_zero_limit(self):
        """Should handle zero limit gracefully."""
        data = {
            "five_hour": {"used": 0, "limit": 0, "resets_at": "2026-03-14T06:00:00Z"},
            "seven_day": {"used": 0, "limit": 0, "resets_at": "2026-03-20T00:00:00Z"},
            "extra_usage": {"enabled": False},
        }
        result = parse_usage(data)
        assert result["five_hour_pct"] == 0.0
        assert result["seven_day_pct"] == 0.0

    def test_returns_all_required_keys(self, sample_usage_response):
        """Should return dict with all required bridge keys."""
        result = parse_usage(sample_usage_response)
        required_keys = {"five_hour_pct", "seven_day_pct", "resets_at", "extra_usage_enabled"}
        assert required_keys.issubset(result.keys())


class TestWriteBridgeFile:
    """Test bridge file writing."""

    def test_writes_json_file(self, bridge_path, sample_bridge_data):
        """Should write valid JSON to bridge path."""
        write_bridge_file(bridge_path, sample_bridge_data)
        assert bridge_path.exists()
        data = json.loads(bridge_path.read_text())
        assert data["five_hour_pct"] == 7.0

    def test_includes_all_required_fields(self, bridge_path, sample_bridge_data):
        """Should include all required bridge fields."""
        write_bridge_file(bridge_path, sample_bridge_data)
        data = json.loads(bridge_path.read_text())
        required = {
            "five_hour_pct",
            "seven_day_pct",
            "resets_at",
            "extra_usage_enabled",
            "ts",
            "handoff_requested",
            "handoff_ready",
            "tool_calls_since_request",
        }
        assert required.issubset(data.keys())

    def test_preserves_handoff_state(self, bridge_path):
        """Should preserve handoff_requested/ready flags."""
        data = {
            "five_hour_pct": 85.0,
            "seven_day_pct": 60.0,
            "resets_at": "2026-03-14T06:00:00Z",
            "extra_usage_enabled": True,
            "ts": 1710000000,
            "handoff_requested": True,
            "handoff_ready": False,
            "tool_calls_since_request": 3,
        }
        write_bridge_file(bridge_path, data)
        result = json.loads(bridge_path.read_text())
        assert result["handoff_requested"] is True
        assert result["tool_calls_since_request"] == 3

    def test_overwrites_existing_file(self, bridge_path, sample_bridge_data):
        """Should overwrite existing bridge file."""
        bridge_path.write_text('{"old": true}')
        write_bridge_file(bridge_path, sample_bridge_data)
        data = json.loads(bridge_path.read_text())
        assert "old" not in data
        assert data["five_hour_pct"] == 7.0


class TestPollQuota:
    """Test the top-level poll_quota orchestrator."""

    def test_uses_cache_when_available(self, tmp_home, session_id, sample_usage_response):
        """Should use cached data and skip HTTP fetch."""
        cache_path = tmp_home / ".claude" / "usage_cache.json"
        cache_data = {"ts": time.time(), "data": sample_usage_response}
        cache_path.write_text(json.dumps(cache_data))

        with patch(
            "scripts.codex_transfer.quota_poller.read_oauth_token", return_value="token"
        ):
            with patch("scripts.codex_transfer.quota_poller.fetch_usage") as mock_fetch:
                result = poll_quota(
                    session_id=session_id,
                    claude_dir=tmp_home / ".claude",
                    bridge_dir=tmp_home,
                )
                mock_fetch.assert_not_called()
                assert result["five_hour_pct"] == 7.0

    def test_fetches_when_cache_expired(self, tmp_home, session_id, sample_usage_response):
        """Should fetch from API when cache expired."""
        with patch(
            "scripts.codex_transfer.quota_poller.read_oauth_token", return_value="token"
        ):
            with patch(
                "scripts.codex_transfer.quota_poller.fetch_usage",
                return_value=sample_usage_response,
            ):
                result = poll_quota(
                    session_id=session_id,
                    claude_dir=tmp_home / ".claude",
                    bridge_dir=tmp_home,
                )
                assert result["five_hour_pct"] == 7.0

    def test_writes_bridge_file(self, tmp_home, session_id, sample_usage_response):
        """Should write bridge file with parsed data."""
        with patch(
            "scripts.codex_transfer.quota_poller.read_oauth_token", return_value="token"
        ):
            with patch(
                "scripts.codex_transfer.quota_poller.fetch_usage",
                return_value=sample_usage_response,
            ):
                poll_quota(
                    session_id=session_id,
                    claude_dir=tmp_home / ".claude",
                    bridge_dir=tmp_home,
                )
                bridge_file = tmp_home / f"claude_quota_{session_id}.json"
                assert bridge_file.exists()
                data = json.loads(bridge_file.read_text())
                assert data["handoff_requested"] is False
                assert data["handoff_ready"] is False

    def test_preserves_existing_handoff_state(
        self, tmp_home, session_id, sample_usage_response
    ):
        """Should preserve handoff flags from existing bridge file."""
        bridge_file = tmp_home / f"claude_quota_{session_id}.json"
        existing = {
            "five_hour_pct": 50.0,
            "seven_day_pct": 30.0,
            "resets_at": "2026-03-14T06:00:00Z",
            "extra_usage_enabled": True,
            "ts": 1710000000,
            "handoff_requested": True,
            "handoff_ready": False,
            "tool_calls_since_request": 3,
        }
        bridge_file.write_text(json.dumps(existing))

        with patch(
            "scripts.codex_transfer.quota_poller.read_oauth_token", return_value="token"
        ):
            with patch(
                "scripts.codex_transfer.quota_poller.fetch_usage",
                return_value=sample_usage_response,
            ):
                poll_quota(
                    session_id=session_id,
                    claude_dir=tmp_home / ".claude",
                    bridge_dir=tmp_home,
                )
                data = json.loads(bridge_file.read_text())
                assert data["handoff_requested"] is True
                assert data["tool_calls_since_request"] == 3

    def test_writes_cache_after_fetch(self, tmp_home, session_id, sample_usage_response):
        """Should update cache file after fresh fetch."""
        with patch(
            "scripts.codex_transfer.quota_poller.read_oauth_token", return_value="token"
        ):
            with patch(
                "scripts.codex_transfer.quota_poller.fetch_usage",
                return_value=sample_usage_response,
            ):
                poll_quota(
                    session_id=session_id,
                    claude_dir=tmp_home / ".claude",
                    bridge_dir=tmp_home,
                )
                cache_path = tmp_home / ".claude" / "usage_cache.json"
                assert cache_path.exists()
                cache = json.loads(cache_path.read_text())
                assert "ts" in cache
                assert cache["data"] == sample_usage_response
