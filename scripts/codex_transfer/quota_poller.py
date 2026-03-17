"""Quota poller: reads OAuth token, fetches usage, caches, writes bridge file.

Stdlib-only — no pip dependencies required.
"""

import json
import time
import urllib.request
from pathlib import Path

# Cache time-to-live in seconds.
CACHE_TTL_SECONDS = 60

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"


def read_oauth_token(credentials_path: Path | None = None) -> str:
    """Read the OAuth access token from the Claude credentials file.

    Args:
        credentials_path: Path to .credentials.json.
            Defaults to ``~/.claude/.credentials.json``.

    Returns:
        The access token string.

    Raises:
        FileNotFoundError: If the credentials file does not exist.
        KeyError: If the expected keys are missing.
    """
    if credentials_path is None:
        credentials_path = Path.home() / ".claude" / ".credentials.json"
    credentials_path = Path(credentials_path)

    if not credentials_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

    with open(credentials_path) as f:
        creds = json.load(f)

    return creds["claudeAiOauth"]["accessToken"]


def fetch_usage(token: str) -> dict:
    """Fetch usage data from the Anthropic OAuth usage endpoint.

    Args:
        token: OAuth access token.

    Returns:
        Parsed JSON response as dict.

    Raises:
        urllib.error.HTTPError: On non-200 responses.
    """
    req = urllib.request.Request(
        USAGE_API_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Anthropic-beta": "oauth-2025-04-20",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_cached_usage(cache_path: Path | None = None) -> dict | None:
    """Return cached usage data if within TTL, else None.

    Args:
        cache_path: Path to the cache file.
            Defaults to ``~/.claude/usage_cache.json``.

    Returns:
        Parsed usage data dict, or None if cache is missing/expired/invalid.
    """
    if cache_path is None:
        cache_path = Path.home() / ".claude" / "usage_cache.json"
    cache_path = Path(cache_path)

    if not cache_path.exists():
        return None

    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    ts = cache.get("ts", 0)
    if time.time() - ts > CACHE_TTL_SECONDS:
        return None

    return cache.get("data")


def _write_cache(cache_path: Path, data: dict) -> None:
    """Write usage data to cache with current timestamp."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump({"ts": time.time(), "data": data}, f)


def parse_usage(raw: dict) -> dict:
    """Parse raw API usage response into percentage-based metrics.

    Args:
        raw: Raw JSON from the usage API.

    Returns:
        Dict with five_hour_pct, seven_day_pct, resets_at, extra_usage_enabled.
    """
    five_hour = raw.get("five_hour", {})
    seven_day = raw.get("seven_day", {})
    extra_usage = raw.get("extra_usage", {})

    five_limit = five_hour.get("limit", 0)
    seven_limit = seven_day.get("limit", 0)

    five_pct = (five_hour.get("used", 0) / five_limit * 100.0) if five_limit > 0 else 0.0
    seven_pct = (seven_day.get("used", 0) / seven_limit * 100.0) if seven_limit > 0 else 0.0

    return {
        "five_hour_pct": round(five_pct, 1),
        "seven_day_pct": round(seven_pct, 1),
        "resets_at": five_hour.get("resets_at", ""),
        "extra_usage_enabled": extra_usage.get("enabled", False),
    }


def write_bridge_file(bridge_path: Path, data: dict) -> None:
    """Write bridge file as JSON.

    Args:
        bridge_path: Path to the bridge file.
        data: Complete bridge data dict.
    """
    bridge_path = Path(bridge_path)
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    with open(bridge_path, "w") as f:
        json.dump(data, f, indent=2)


def _read_existing_bridge(bridge_path: Path) -> dict | None:
    """Read existing bridge file if present, returning handoff state."""
    bridge_path = Path(bridge_path)
    if not bridge_path.exists():
        return None
    try:
        with open(bridge_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def poll_quota(
    session_id: str,
    claude_dir: Path | None = None,
    bridge_dir: Path | None = None,
) -> dict:
    """Top-level quota poll: read token, fetch/cache usage, write bridge file.

    Args:
        session_id: Session identifier for the bridge file name.
        claude_dir: Path to .claude directory. Defaults to ``~/.claude``.
        bridge_dir: Directory for bridge files. Defaults to ``/tmp``.

    Returns:
        Parsed usage data dict (bridge file content).
    """
    if claude_dir is None:
        claude_dir = Path.home() / ".claude"
    if bridge_dir is None:
        bridge_dir = Path("/tmp")

    claude_dir = Path(claude_dir)
    bridge_dir = Path(bridge_dir)

    cache_path = claude_dir / "usage_cache.json"
    credentials_path = claude_dir / ".credentials.json"
    bridge_path = bridge_dir / f"claude_quota_{session_id}.json"

    # Try cache first
    usage_raw = get_cached_usage(cache_path=cache_path)

    if usage_raw is None:
        # Cache miss — fetch from API
        token = read_oauth_token(credentials_path=credentials_path)
        usage_raw = fetch_usage(token)
        _write_cache(cache_path, usage_raw)

    # Parse to percentages
    parsed = parse_usage(usage_raw)

    # Read existing bridge to preserve handoff state
    existing = _read_existing_bridge(bridge_path)

    bridge_data = {
        "five_hour_pct": parsed["five_hour_pct"],
        "seven_day_pct": parsed["seven_day_pct"],
        "resets_at": parsed["resets_at"],
        "extra_usage_enabled": parsed["extra_usage_enabled"],
        "ts": int(time.time()),
        "handoff_requested": existing.get("handoff_requested", False) if existing else False,
        "handoff_ready": existing.get("handoff_ready", False) if existing else False,
        "tool_calls_since_request": existing.get("tool_calls_since_request", 0) if existing else 0,
    }

    write_bridge_file(bridge_path, bridge_data)
    return bridge_data
