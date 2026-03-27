"""Tests for _rlm_state read-only state snapshot injection into REPL.

Verifies that REPLTool injects a snapshot of allowlisted session state keys
into the REPL namespace as ``_rlm_state`` before each code execution.

RED phase: these tests are written before implementation and should all fail.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import (
    APP_MAX_DEPTH,
    APP_MAX_ITERATIONS,
    CURRENT_DEPTH,
    EXPOSED_STATE_KEYS,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    depth_key,
)
from rlm_adk.tools.repl_tool import REPLTool

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake_contract]

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_fake"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Build a mock ToolContext with a dict-backed .state property."""
    ctx = MagicMock()
    ctx.state = dict(state or {})
    ctx.actions = MagicMock()
    return ctx


# ===========================================================================
# Unit tests
# ===========================================================================


class TestSnapshotInjectedIntoRepl:
    """Verify _rlm_state is injected into the REPL namespace during execution."""

    async def test_snapshot_injected_into_repl(self):
        """REPLTool injects _rlm_state into repl.globals before code runs."""
        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)

        tc = _make_tool_context(
            {
                ITERATION_COUNT: 1,
                CURRENT_DEPTH: 0,
                APP_MAX_ITERATIONS: 30,
            }
        )

        result = await tool.run_async(
            args={"code": "snapshot = dict(_rlm_state)\nprint(f'got={list(snapshot.keys())}')"},
            tool_context=tc,
        )

        assert "got=" in result["stdout"], (
            f"Expected _rlm_state to be accessible in REPL, got stderr={result['stderr']!r}"
        )
        repl.cleanup()

    async def test_snapshot_contains_expected_keys(self):
        """The snapshot dict contains only allowlisted keys that have values."""
        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)

        tc = _make_tool_context(
            {
                CURRENT_DEPTH: 0,
                APP_MAX_ITERATIONS: 30,
                APP_MAX_DEPTH: 5,
                # Not in EXPOSED_STATE_KEYS -- should be excluded:
                "obs:total_input_tokens": 1000,
                "some_random_key": "should_not_appear",
            }
        )

        result = await tool.run_async(
            args={
                "code": "import json\n"
                "print(json.dumps(dict(_rlm_state)))"
            },
            tool_context=tc,
        )

        import json

        snapshot = json.loads(result["stdout"].strip())

        # iteration_count is written by REPLTool as _call_count (1 on first call)
        assert snapshot[ITERATION_COUNT] == 1
        assert snapshot[CURRENT_DEPTH] == 0
        assert snapshot[APP_MAX_ITERATIONS] == 30
        assert snapshot[APP_MAX_DEPTH] == 5

        # Non-allowlisted keys should NOT be present
        assert "obs:total_input_tokens" not in snapshot
        assert "some_random_key" not in snapshot

        # Every key in snapshot must be in EXPOSED_STATE_KEYS or be a
        # runtime lineage key injected by REPLTool for non-circular test
        # verification (see repl_tool.py lineage metadata injection).
        _LINEAGE_KEYS = {"_rlm_depth", "_rlm_fanout_idx", "_rlm_agent_name"}
        for key in snapshot:
            assert key in EXPOSED_STATE_KEYS or key in _LINEAGE_KEYS, (
                f"Unexpected key {key!r} in snapshot"
            )

        repl.cleanup()

    async def test_snapshot_is_read_only_safe(self):
        """Mutating the snapshot dict does not affect session state (AR-CRIT-001)."""
        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)

        tc = _make_tool_context(
            {
                ITERATION_COUNT: 1,
                CURRENT_DEPTH: 0,
            }
        )

        # Attempt to mutate the snapshot from REPL code
        result = await tool.run_async(
            args={"code": "_rlm_state['iteration_count'] = 999\nprint('mutated')"},
            tool_context=tc,
        )

        assert "mutated" in result["stdout"]
        # Original state must NOT be affected
        # REPLTool increments iteration_count to 1 (call_count=1)
        assert tc.state[ITERATION_COUNT] == 1, (
            f"Session state was corrupted by REPL mutation: {tc.state[ITERATION_COUNT]}"
        )
        repl.cleanup()

    async def test_snapshot_depth_scoping(self):
        """Depth-scoped keys use the correct depth suffix for lookup."""
        repl = LocalREPL(depth=1)
        depth = 2
        tool = REPLTool(repl, max_calls=10, depth=depth)

        # Pre-seed a depth-scoped key (LAST_REPL_RESULT) with @d2f0 suffix.
        # LAST_REPL_RESULT is in DEPTH_SCOPED_KEYS and is NOT overwritten
        # by REPLTool before code execution (only after), so the snapshot
        # will see this pre-seeded value.
        scoped_key = depth_key(LAST_REPL_RESULT, depth)
        fake_repl_result = {"has_output": True, "stdout": "previous run"}
        tc = _make_tool_context(
            {
                scoped_key: fake_repl_result,
                depth_key(CURRENT_DEPTH, depth): depth,  # depth-scoped
                APP_MAX_ITERATIONS: 30,
            }
        )

        result = await tool.run_async(
            args={"code": "import json\nprint(json.dumps(dict(_rlm_state), default=str))"},
            tool_context=tc,
        )

        import json

        snapshot = json.loads(result["stdout"].strip())

        # The snapshot should use the UNSCOPED key name for clean API
        assert snapshot.get(LAST_REPL_RESULT) == fake_repl_result, (
            f"Expected last_repl_result from depth-scoped lookup, got {snapshot}"
        )
        # CURRENT_DEPTH IS depth-scoped (in DEPTH_SCOPED_KEYS)
        assert snapshot.get(CURRENT_DEPTH) == depth
        # iteration_count is depth-scoped and was written by REPLTool as 1
        assert snapshot.get(ITERATION_COUNT) == 1

        repl.cleanup()

    async def test_snapshot_refreshed_each_call(self):
        """Two consecutive run_async calls show different iteration_count values."""
        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)

        tc = _make_tool_context(
            {
                CURRENT_DEPTH: 0,
                APP_MAX_ITERATIONS: 30,
            }
        )

        # First call -- iteration_count written by REPLTool as 1
        result1 = await tool.run_async(
            args={"code": "print(f\"iter={_rlm_state.get('iteration_count', 'MISSING')}\")"},
            tool_context=tc,
        )

        # Second call -- iteration_count written by REPLTool as 2
        result2 = await tool.run_async(
            args={"code": "print(f\"iter={_rlm_state.get('iteration_count', 'MISSING')}\")"},
            tool_context=tc,
        )

        assert "iter=1" in result1["stdout"], f"First call stdout: {result1['stdout']!r}"
        assert "iter=2" in result2["stdout"], f"Second call stdout: {result2['stdout']!r}"

        repl.cleanup()

    async def test_snapshot_omits_none_values(self):
        """Keys with None values in state are excluded from the snapshot."""
        repl = LocalREPL(depth=1)
        tool = REPLTool(repl, max_calls=10, depth=0)

        tc = _make_tool_context(
            {
                CURRENT_DEPTH: 0,
                # LAST_REPL_RESULT is None initially
            }
        )

        result = await tool.run_async(
            args={"code": "import json\nprint(json.dumps(dict(_rlm_state)))"},
            tool_context=tc,
        )

        import json

        snapshot = json.loads(result["stdout"].strip())

        # LAST_REPL_RESULT was not set, so should not appear
        assert LAST_REPL_RESULT not in snapshot

        repl.cleanup()


# ===========================================================================
# E2E provider-fake fixture test
# ===========================================================================


class TestReplStateIntrospectionE2E:
    """E2E test using a provider-fake fixture that exercises _rlm_state."""

    async def test_fixture_contract(self):
        """The repl_state_introspection fixture passes its contract."""
        from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract

        fixture_path = FIXTURE_DIR / "repl_state_introspection.json"
        result = await run_fixture_contract(fixture_path)
        if not result.passed:
            print(result.diagnostics())
        assert result.passed, f"Fixture contract failed:\n{result.diagnostics()}"

    async def test_stdout_contains_state_values(self):
        """Fixture code prints _rlm_state values visible in tool results."""
        from tests_rlm_adk.provider_fake.contract_runner import (
            run_fixture_contract_with_plugins,
        )

        fixture_path = FIXTURE_DIR / "repl_state_introspection.json"
        result = await run_fixture_contract_with_plugins(fixture_path)

        # Extract tool results from events
        tool_results = []
        for event in result.events:
            content = getattr(event, "content", None)
            if content is None:
                continue
            for part in getattr(content, "parts", []):
                fr = getattr(part, "function_response", None)
                if fr is not None and getattr(fr, "name", "") == "execute_code":
                    response_data = getattr(fr, "response", None)
                    if isinstance(response_data, dict):
                        tool_results.append(response_data)

        assert len(tool_results) >= 1, "Expected at least one execute_code tool response"

        # The first tool result should contain iter=1 and depth=0
        first_stdout = tool_results[0].get("stdout", "")
        assert "iter=1" in first_stdout, (
            f"Expected 'iter=1' in first tool stdout, got: {first_stdout!r}"
        )
        assert "depth=0" in first_stdout, (
            f"Expected 'depth=0' in first tool stdout, got: {first_stdout!r}"
        )
