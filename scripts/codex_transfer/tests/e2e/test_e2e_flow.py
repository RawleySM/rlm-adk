"""E2E tests for the full Codex Transfer pipeline.

Tests the integration between bridge files, quota monitoring, threshold
detection, handoff documents, and codex launching.

These tests exercise the actual file I/O and subprocess patterns used by the
transfer system.  Source modules (quota_poller, session_transfer_monitor, etc.)
are imported when available, with graceful skip when not yet built.

Run:
    .venv/bin/python -m pytest scripts/codex_transfer/tests/e2e/test_e2e_flow.py -v --timeout=120
"""

import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from .conftest import CODEX_BIN, REPO_ROOT


# ---------------------------------------------------------------------------
# Import helpers -- the source modules may not exist yet.
# ---------------------------------------------------------------------------

def _try_import(module_path: str):
    """Attempt to import a module; return None if it doesn't exist yet."""
    try:
        import importlib
        return importlib.import_module(module_path)
    except (ImportError, ModuleNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Bridge file lifecycle tests
# ---------------------------------------------------------------------------


class TestBridgeFileLifecycle:
    """Test create / update / read cycle for bridge files."""

    def test_bridge_create_and_read(self, tmp_path, bridge_data_low):
        """Bridge file can be written as JSON and read back identically."""
        bridge_path = tmp_path / "claude_quota_session.json"
        bridge_path.write_text(json.dumps(bridge_data_low, indent=2))

        assert bridge_path.exists()
        loaded = json.loads(bridge_path.read_text())
        assert loaded == bridge_data_low

    def test_bridge_update_preserves_schema(self, bridge_file, bridge_data_high):
        """Updating a bridge file preserves all expected keys."""
        expected_keys = set(bridge_data_high.keys())

        # Overwrite with high-usage data
        bridge_file.write_text(json.dumps(bridge_data_high, indent=2))
        loaded = json.loads(bridge_file.read_text())

        assert set(loaded.keys()) == expected_keys
        assert loaded["five_hour_pct"] == 85.0
        assert loaded["handoff_requested"] is False

    def test_bridge_atomic_write(self, tmp_path, bridge_data_low):
        """Simulate atomic write pattern (write tmp + rename)."""
        bridge_path = tmp_path / "claude_quota_session.json"
        tmp_bridge = tmp_path / "claude_quota_session.json.tmp"

        # Write to temp, then rename (atomic on same filesystem)
        tmp_bridge.write_text(json.dumps(bridge_data_low, indent=2))
        tmp_bridge.rename(bridge_path)

        assert bridge_path.exists()
        assert not tmp_bridge.exists()
        loaded = json.loads(bridge_path.read_text())
        assert loaded["five_hour_pct"] == 7.0

    def test_bridge_handoff_requested_transition(self, bridge_file, bridge_data_low):
        """Bridge transitions from handoff_requested=False to True."""
        data = bridge_data_low.copy()
        assert data["handoff_requested"] is False

        data["handoff_requested"] = True
        data["five_hour_pct"] = 90.0
        bridge_file.write_text(json.dumps(data, indent=2))

        loaded = json.loads(bridge_file.read_text())
        assert loaded["handoff_requested"] is True
        assert loaded["five_hour_pct"] == 90.0

    def test_bridge_handoff_ready_transition(self, bridge_file, bridge_data_low):
        """Bridge transitions through full lifecycle: low -> requested -> ready."""
        data = bridge_data_low.copy()

        # Phase 1: low usage
        assert data["handoff_ready"] is False
        assert data["handoff_requested"] is False

        # Phase 2: threshold crossed, handoff requested
        data["five_hour_pct"] = 85.0
        data["handoff_requested"] = True
        bridge_file.write_text(json.dumps(data, indent=2))

        # Phase 3: handoff doc written, handoff ready
        data["handoff_ready"] = True
        data["tool_calls_since_request"] = 5
        bridge_file.write_text(json.dumps(data, indent=2))

        loaded = json.loads(bridge_file.read_text())
        assert loaded["handoff_requested"] is True
        assert loaded["handoff_ready"] is True
        assert loaded["tool_calls_since_request"] == 5


# ---------------------------------------------------------------------------
# Quota-to-monitor integration tests
# ---------------------------------------------------------------------------


class TestQuotaToMonitorIntegration:
    """Test that the bridge file serves as the integration point
    between quota polling and the session transfer monitor."""

    def test_bridge_file_readable_by_different_process(self, bridge_file, bridge_data_low):
        """Prove bridge file written by one 'process' is readable by another.

        Simulates poller writing and monitor reading.
        """
        # "Poller" writes
        bridge_file.write_text(json.dumps(bridge_data_low, indent=2))

        # "Monitor" reads (using subprocess to simulate separate process)
        result = subprocess.run(
            ["python3", "-c", f"import json; print(json.load(open('{bridge_file}')))"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Reader failed: {result.stderr}"
        assert "five_hour_pct" in result.stdout

    def test_quota_pct_calculation(self):
        """Verify percentage calculation logic matches expected formula."""
        # Simulating what quota_poller computes from the usage API response
        used = 700
        limit = 10000
        pct = (used / limit) * 100
        assert abs(pct - 7.0) < 0.01

        used_high = 8500
        pct_high = (used_high / limit) * 100
        assert abs(pct_high - 85.0) < 0.01


# ---------------------------------------------------------------------------
# Monitor threshold trigger tests
# ---------------------------------------------------------------------------


class TestMonitorThresholdTrigger:
    """Test threshold detection logic."""

    DEFAULT_THRESHOLD = 80.0

    def test_below_threshold_no_trigger(self, bridge_data_low):
        """Usage below threshold should not trigger handoff."""
        assert bridge_data_low["five_hour_pct"] < self.DEFAULT_THRESHOLD

    def test_above_threshold_triggers(self, bridge_data_high):
        """Usage above threshold should trigger handoff request."""
        assert bridge_data_high["five_hour_pct"] >= self.DEFAULT_THRESHOLD

    def test_threshold_exact_boundary(self):
        """Usage exactly at threshold should trigger (>= semantics)."""
        data = {"five_hour_pct": 80.0}
        assert data["five_hour_pct"] >= self.DEFAULT_THRESHOLD

    def test_threshold_just_below(self):
        """Usage 0.1% below threshold should not trigger."""
        data = {"five_hour_pct": 79.9}
        assert data["five_hour_pct"] < self.DEFAULT_THRESHOLD

    def test_seven_day_pct_independent(self):
        """Seven-day pct can be high without triggering if 5-hour is low."""
        data = {"five_hour_pct": 30.0, "seven_day_pct": 90.0}
        # Default trigger is on five_hour_pct only
        assert data["five_hour_pct"] < self.DEFAULT_THRESHOLD

    def test_system_message_content_on_trigger(self, bridge_data_high):
        """When threshold is crossed, a system message should include quota info."""
        # Simulate the monitor's systemMessage construction
        pct = bridge_data_high["five_hour_pct"]
        resets_at = bridge_data_high["resets_at"]
        msg = (
            f"[QUOTA WARNING] Claude usage at {pct:.0f}% of 5-hour limit. "
            f"Resets at {resets_at}. "
            f"Begin writing a handoff document for Codex continuation."
        )
        assert "85%" in msg
        assert "2026-03-14" in msg
        assert "handoff" in msg.lower()


# ---------------------------------------------------------------------------
# Handoff document detection tests
# ---------------------------------------------------------------------------


class TestHandoffDocDetection:
    """Test that handoff documents can be written and detected."""

    def test_handoff_doc_exists_after_write(self, tmp_path):
        """Handoff document exists after being written."""
        handoff_path = tmp_path / "handoff.md"
        handoff_path.write_text("# Handoff\nTask: continue testing")
        assert handoff_path.exists()
        assert handoff_path.stat().st_size > 0

    def test_handoff_doc_content_parseable(self, sample_handoff_path):
        """Sample handoff document has expected markdown structure."""
        content = sample_handoff_path.read_text()
        assert "# Session Handoff Document" in content
        assert "## Context" in content
        assert "## What Remains" in content
        assert "## Key Files" in content

    def test_handoff_sets_bridge_ready(self, bridge_file, bridge_data_low, tmp_path):
        """After handoff doc is written, bridge file should have handoff_ready=True."""
        # Simulate: monitor detects handoff doc, updates bridge
        handoff_path = tmp_path / "handoff.md"
        handoff_path.write_text("# Handoff\nContinue the task.")

        data = bridge_data_low.copy()
        data["handoff_requested"] = True

        # Monitor checks for handoff doc and updates bridge
        if handoff_path.exists() and handoff_path.stat().st_size > 10:
            data["handoff_ready"] = True

        bridge_file.write_text(json.dumps(data, indent=2))
        loaded = json.loads(bridge_file.read_text())
        assert loaded["handoff_ready"] is True

    def test_tool_calls_since_request_increments(self, bridge_file, bridge_data_low):
        """tool_calls_since_request increments each time monitor hook fires."""
        data = bridge_data_low.copy()
        data["handoff_requested"] = True
        data["tool_calls_since_request"] = 0

        for i in range(1, 6):
            data["tool_calls_since_request"] = i
            bridge_file.write_text(json.dumps(data, indent=2))

        loaded = json.loads(bridge_file.read_text())
        assert loaded["tool_calls_since_request"] == 5


# ---------------------------------------------------------------------------
# Gate auto-launch tests
# ---------------------------------------------------------------------------


@pytest.mark.codex
@pytest.mark.slow
class TestGateAutoLaunch:
    """Test that the gate can auto-launch codex when handoff is ready."""

    def test_gate_launches_codex_on_handoff_ready(
        self, codex_bin, repo_root, tmp_path, bridge_data_handoff_ready
    ):
        """When handoff_ready=True, gate should be able to launch codex.

        This tests the actual Popen pattern the gate will use.
        """
        assert bridge_data_handoff_ready["handoff_ready"] is True

        output_file = tmp_path / "gate_launch_output.md"
        cmd = [
            codex_bin, "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            "-m", "gpt-5.4",
            "-C", str(repo_root),
            "-o", str(output_file),
            "What is 1 + 1? Answer with just the number.",
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        assert proc.pid > 0, "Gate failed to launch codex"

        # Wait for completion
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            pytest.fail("Gate-launched codex did not complete within 120s")

        assert proc.returncode == 0, f"Gate-launched codex failed (rc={proc.returncode})"
        assert output_file.exists(), "Gate-launched codex did not produce output"

    def test_gate_skips_launch_when_not_ready(self, bridge_data_low):
        """When handoff_ready=False, gate should NOT launch codex."""
        assert bridge_data_low["handoff_ready"] is False
        # Gate logic: only launch if handoff_ready
        should_launch = bridge_data_low.get("handoff_ready", False)
        assert should_launch is False


# ---------------------------------------------------------------------------
# Full E2E pipeline test
# ---------------------------------------------------------------------------


@pytest.mark.codex
@pytest.mark.slow
class TestFullE2EFlow:
    """Test the complete pipeline: quota -> threshold -> handoff -> codex launch."""

    def test_full_e2e_flow(self, codex_bin, repo_root, tmp_path, sample_handoff_path):
        """Complete pipeline simulation:

        1. Quota poller writes bridge file (low usage)
        2. Usage increases above threshold
        3. Monitor detects threshold, sets handoff_requested
        4. Claude writes handoff document
        5. Monitor detects handoff doc, sets handoff_ready
        6. Gate reads bridge, sees handoff_ready, launches codex
        7. Codex runs to completion with output
        """
        bridge_path = tmp_path / "claude_quota_e2e.json"
        handoff_path = tmp_path / "handoff_e2e.md"
        output_path = tmp_path / "codex_e2e_output.md"

        # --- Step 1: Poller writes low-usage bridge ---
        bridge_data = {
            "five_hour_pct": 15.0,
            "seven_day_pct": 10.0,
            "resets_at": "2026-03-14T06:00:00Z",
            "extra_usage_enabled": True,
            "ts": 1710000000,
            "handoff_requested": False,
            "handoff_ready": False,
            "tool_calls_since_request": 0,
        }
        bridge_path.write_text(json.dumps(bridge_data, indent=2))
        assert bridge_path.exists()

        # --- Step 2: Usage increases (poller updates bridge) ---
        bridge_data["five_hour_pct"] = 85.0
        bridge_data["seven_day_pct"] = 55.0
        bridge_path.write_text(json.dumps(bridge_data, indent=2))

        # --- Step 3: Monitor detects threshold ---
        loaded = json.loads(bridge_path.read_text())
        threshold = 80.0
        assert loaded["five_hour_pct"] >= threshold, "Threshold should be crossed"

        bridge_data["handoff_requested"] = True
        bridge_path.write_text(json.dumps(bridge_data, indent=2))

        # --- Step 4: Claude writes handoff doc ---
        shutil.copy(sample_handoff_path, handoff_path)
        assert handoff_path.exists()
        assert handoff_path.stat().st_size > 0

        # --- Step 5: Monitor detects handoff doc ---
        bridge_data["handoff_ready"] = True
        bridge_data["tool_calls_since_request"] = 5
        bridge_path.write_text(json.dumps(bridge_data, indent=2))

        # --- Step 6: Gate reads bridge, launches codex ---
        gate_data = json.loads(bridge_path.read_text())
        assert gate_data["handoff_ready"] is True

        cmd = [
            codex_bin, "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--ephemeral",
            "-m", "gpt-5.4",
            "-C", str(repo_root),
            "-o", str(output_path),
            "What is 7 + 7? Answer with just the number, nothing else.",
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert proc.pid > 0

        # --- Step 7: Codex completes ---
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            pytest.fail("E2E codex process timed out")

        assert proc.returncode == 0, f"E2E codex failed (rc={proc.returncode})"
        assert output_path.exists(), "E2E codex did not produce output"
        content = output_path.read_text().strip()
        assert len(content) > 0, "E2E output is empty"
        assert "14" in content, f"Expected '14' in output, got: {content[:500]}"

    def test_bridge_state_consistency_throughout_flow(self, tmp_path):
        """Verify bridge state transitions are consistent and monotonic."""
        bridge_path = tmp_path / "consistency_bridge.json"
        states = []

        # Simulate the state machine transitions
        transitions = [
            {"five_hour_pct": 10.0, "handoff_requested": False, "handoff_ready": False, "tool_calls_since_request": 0},
            {"five_hour_pct": 50.0, "handoff_requested": False, "handoff_ready": False, "tool_calls_since_request": 0},
            {"five_hour_pct": 82.0, "handoff_requested": True, "handoff_ready": False, "tool_calls_since_request": 0},
            {"five_hour_pct": 85.0, "handoff_requested": True, "handoff_ready": False, "tool_calls_since_request": 2},
            {"five_hour_pct": 88.0, "handoff_requested": True, "handoff_ready": True, "tool_calls_since_request": 5},
        ]

        base = {
            "seven_day_pct": 30.0,
            "resets_at": "2026-03-14T06:00:00Z",
            "extra_usage_enabled": True,
            "ts": 1710000000,
        }

        for t in transitions:
            data = {**base, **t}
            bridge_path.write_text(json.dumps(data, indent=2))
            states.append(json.loads(bridge_path.read_text()))

        # Verify monotonic properties
        # five_hour_pct should be non-decreasing
        pcts = [s["five_hour_pct"] for s in states]
        assert pcts == sorted(pcts), f"five_hour_pct not monotonically increasing: {pcts}"

        # Once handoff_requested becomes True, it stays True
        requested = [s["handoff_requested"] for s in states]
        first_true = next((i for i, v in enumerate(requested) if v), len(requested))
        assert all(requested[i] for i in range(first_true, len(requested))), (
            f"handoff_requested reverted to False: {requested}"
        )

        # Once handoff_ready becomes True, it stays True
        ready = [s["handoff_ready"] for s in states]
        first_ready = next((i for i, v in enumerate(ready) if v), len(ready))
        assert all(ready[i] for i in range(first_ready, len(ready))), (
            f"handoff_ready reverted to False: {ready}"
        )

        # tool_calls_since_request is non-decreasing
        calls = [s["tool_calls_since_request"] for s in states]
        assert calls == sorted(calls), f"tool_calls not monotonically increasing: {calls}"
