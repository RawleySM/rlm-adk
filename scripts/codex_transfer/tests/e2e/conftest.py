"""Shared fixtures and configuration for codex_transfer e2e tests."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path("/home/rawley-stanhope/dev/rlm-adk")
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CODEX_BIN = shutil.which("codex") or os.path.expanduser("~/.npm-global/bin/codex")

# ---------------------------------------------------------------------------
# Marks registration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "codex: tests requiring the codex CLI binary")
    config.addinivalue_line("markers", "slow: tests that take >30s (model inference)")


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------


def _codex_available() -> bool:
    """Return True if the codex CLI is installed and runnable."""
    try:
        result = subprocess.run(
            [CODEX_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# Cache the check so we only shell out once per session.
_CODEX_OK = _codex_available()


@pytest.fixture(autouse=True)
def _skip_if_no_codex(request):
    """Auto-skip tests marked @pytest.mark.codex when the CLI is absent."""
    if request.node.get_closest_marker("codex") and not _CODEX_OK:
        pytest.skip("codex CLI not installed or not runnable")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def codex_bin():
    """Return the resolved path to the codex binary."""
    return CODEX_BIN


@pytest.fixture
def repo_root():
    """Return the project repository root as a Path."""
    return REPO_ROOT


@pytest.fixture
def output_file(tmp_path):
    """Provide a temporary output file path, cleaned up automatically."""
    return tmp_path / "codex_output.md"


@pytest.fixture
def events_file(tmp_path):
    """Provide a temporary JSONL events file path."""
    return tmp_path / "codex_events.jsonl"


@pytest.fixture
def stderr_file(tmp_path):
    """Provide a temporary stderr capture file path."""
    return tmp_path / "codex_stderr.log"


@pytest.fixture
def prompt_file(tmp_path):
    """Write a simple prompt to a temp file and return its path."""
    p = tmp_path / "prompt.txt"
    p.write_text("What is 2 + 2? Answer with just the number.")
    return p


@pytest.fixture
def sample_handoff_path():
    """Return the path to the sample handoff fixture."""
    return FIXTURES_DIR / "sample_handoff.md"


@pytest.fixture
def sample_bridge_path():
    """Return the path to the sample bridge fixture."""
    return FIXTURES_DIR / "sample_bridge.json"


@pytest.fixture
def bridge_data_low():
    """Return low-usage bridge data dict."""
    with open(FIXTURES_DIR / "sample_bridge.json") as f:
        return json.load(f)["low_usage"]


@pytest.fixture
def bridge_data_high():
    """Return high-usage bridge data dict."""
    with open(FIXTURES_DIR / "sample_bridge.json") as f:
        return json.load(f)["high_usage"]


@pytest.fixture
def bridge_data_handoff_ready():
    """Return handoff-ready bridge data dict."""
    with open(FIXTURES_DIR / "sample_bridge.json") as f:
        return json.load(f)["handoff_ready"]


@pytest.fixture
def bridge_file(tmp_path, bridge_data_low):
    """Write low-usage bridge data to a temp file and return the path."""
    p = tmp_path / "claude_quota_test.json"
    p.write_text(json.dumps(bridge_data_low))
    return p


@pytest.fixture
def handoff_doc(tmp_path, sample_handoff_path):
    """Copy the sample handoff to tmp_path and return the path."""
    dest = tmp_path / "handoff.md"
    shutil.copy(sample_handoff_path, dest)
    return dest
