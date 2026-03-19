"""Diagnostic: verify _rlm_state snapshot accuracy at each REPL turn.

The _rlm_state dict is built BEFORE code execution in REPLTool.run_async.
This means obs keys from flush_fn reflect the PREVIOUS iteration's values.
This test dumps the actual _rlm_state dict seen by REPL code at each turn.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.contract_runner import (
    run_fixture_contract_with_plugins,
)

FIXTURE_DIR = Path("tests_rlm_adk/fixtures/provider_fake")


def _extract_tool_results(events: list) -> list[dict]:
    """Extract function_response tool results from events."""
    results = []
    for i, event in enumerate(events):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fr = getattr(part, "function_response", None)
            if fr and fr.name == "execute_code":
                response_data = dict(fr.response) if fr.response else {}
                results.append({
                    "event_idx": i,
                    "author": getattr(event, "author", "?"),
                    "call_number": response_data.get("call_number", "?"),
                    "stdout": response_data.get("stdout", ""),
                    "stderr": response_data.get("stderr", ""),
                    "llm_calls_made": response_data.get("llm_calls_made", False),
                    "variables": response_data.get("variables", {}),
                })
    return results


def _parse_rlm_state_from_stdout(stdout: str) -> dict | None:
    """Try to parse _rlm_state dict from stdout line."""
    # Look for _rlm_state={...} pattern
    match = re.search(r"_rlm_state=(\{.*\})", stdout)
    if not match:
        return None
    try:
        # Python dict repr uses single quotes; try ast.literal_eval
        import ast
        return ast.literal_eval(match.group(1))
    except Exception:
        return None


# Multi-iteration fixtures that print _rlm_state
AUDIT_FIXTURES = [
    "fake_recursive_ping",      # prints _rlm_state at layer 0 turn 1, layer 1, layer 2, turn 2
]


@pytest.mark.provider_fake_contract
@pytest.mark.parametrize("fixture_name", AUDIT_FIXTURES)
async def test_rlm_state_snapshot_accuracy(fixture_name: str, tmp_path: Path):
    """Verify _rlm_state snapshot values at each REPL turn."""
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"

    result = await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
        tmpdir=str(tmp_path),
    )

    tool_results = _extract_tool_results(result.events)

    print(f"\n{'='*80}")
    print(f"_rlm_state SNAPSHOT AUDIT: {fixture_name}")
    print(f"{'='*80}")

    for tr in tool_results:
        print(f"\n  REPL Turn (event #{tr['event_idx']}) | call_number={tr['call_number']} "
              f"| llm_calls={tr['llm_calls_made']}")
        print(f"  author: {tr['author']}")

        # Full stdout
        stdout = tr["stdout"]
        if stdout:
            for line in stdout.split("\n"):
                if line.strip():
                    print(f"    stdout: {line}")

        if tr["stderr"]:
            print(f"    stderr: {tr['stderr'][:200]}")

        # Parse _rlm_state if present
        rlm_state = _parse_rlm_state_from_stdout(stdout)
        if rlm_state:
            print(f"\n    === _rlm_state dict ===")
            for k in sorted(rlm_state.keys()):
                v = rlm_state[k]
                vs = repr(v)
                if len(vs) > 100:
                    vs = vs[:97] + "..."
                print(f"      {k} = {vs}")

            # Check iteration_count
            ic = rlm_state.get("iteration_count")
            print(f"\n    iteration_count = {ic}")

            # Check obs:child_dispatch_count
            cdc = rlm_state.get("obs:child_dispatch_count")
            print(f"    obs:child_dispatch_count = {cdc}")

    # Also dump the final state for comparison
    print(f"\n  --- FINAL SESSION STATE (key subset) ---")
    state_keys = [
        "iteration_count", "obs:child_dispatch_count",
        "obs:total_calls", "obs:total_input_tokens",
        "obs:total_output_tokens", "obs:rewrite_count",
    ]
    for k in state_keys:
        v = result.final_state.get(k)
        print(f"    {k} = {v}")

    assert result.contract.passed, result.contract.diagnostics()
    print(f"\n  Contract PASS")


@pytest.mark.provider_fake_contract
async def test_rlm_state_dispatch_count_timing(tmp_path: Path):
    """Specific test: does _rlm_state.obs:child_dispatch_count show stale values?

    For fake_recursive_ping:
    - Turn 1 code dispatches a child (llm_query call)
    - Turn 2 code does NOT dispatch (just prints _rlm_state)

    In _rlm_state snapshot:
    - Turn 1: obs:child_dispatch_count should be ABSENT or 0 (snapshot taken BEFORE execution)
    - Turn 2: obs:child_dispatch_count should be 1 (reads the flush from turn 1)

    In final state:
    - obs:child_dispatch_count should be 0 (turn 2 flushed with 0 dispatches)
    """
    fixture_path = FIXTURE_DIR / "fake_recursive_ping.json"

    result = await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
        tmpdir=str(tmp_path),
    )

    tool_results = _extract_tool_results(result.events)

    # Find root-level REPL turns (author=reasoning_agent)
    root_turns = [tr for tr in tool_results if tr["author"] == "reasoning_agent"]

    print(f"\n  Root REPL turns: {len(root_turns)}")
    assert len(root_turns) == 2, f"Expected 2 root turns, got {len(root_turns)}"

    # Turn 1: dispatches a child
    turn1 = root_turns[0]
    turn1_state = _parse_rlm_state_from_stdout(turn1["stdout"])
    print(f"\n  Turn 1 _rlm_state:")
    if turn1_state:
        print(f"    iteration_count = {turn1_state.get('iteration_count')}")
        print(f"    obs:child_dispatch_count = {turn1_state.get('obs:child_dispatch_count', 'ABSENT')}")
        print(f"    obs:child_dispatch_count_total = {turn1_state.get('obs:child_dispatch_count_total', 'ABSENT')}")
        print(f"    last_repl_result = {'PRESENT' if 'last_repl_result' in turn1_state else 'ABSENT'}")
    else:
        print(f"    (could not parse _rlm_state)")

    # Turn 2: no dispatch, just reads _rlm_state
    turn2 = root_turns[1]
    turn2_state = _parse_rlm_state_from_stdout(turn2["stdout"])
    print(f"\n  Turn 2 _rlm_state:")
    if turn2_state:
        print(f"    iteration_count = {turn2_state.get('iteration_count')}")
        print(f"    obs:child_dispatch_count = {turn2_state.get('obs:child_dispatch_count', 'ABSENT')}")
        print(f"    obs:child_dispatch_count_total = {turn2_state.get('obs:child_dispatch_count_total', 'ABSENT')}")
        print(f"    obs:rewrite_count = {turn2_state.get('obs:rewrite_count', 'ABSENT')}")
        print(f"    last_repl_result = {'PRESENT' if 'last_repl_result' in turn2_state else 'ABSENT'}")
    else:
        print(f"    (could not parse _rlm_state)")

    # Final state
    final_dispatch = result.final_state.get("obs:child_dispatch_count")
    final_dispatch_total = result.final_state.get("obs:child_dispatch_count_total")
    final_iter = result.final_state.get("iteration_count")
    print(f"\n  Final state:")
    print(f"    iteration_count = {final_iter}")
    print(f"    obs:child_dispatch_count = {final_dispatch}")
    print(f"    obs:child_dispatch_count_total = {final_dispatch_total}")

    # ASSERTIONS
    # iteration_count should be correct at each turn
    if turn1_state:
        assert turn1_state.get("iteration_count") == 1, (
            f"Turn 1 iteration_count should be 1, got {turn1_state.get('iteration_count')}"
        )
    if turn2_state:
        assert turn2_state.get("iteration_count") == 2, (
            f"Turn 2 iteration_count should be 2, got {turn2_state.get('iteration_count')}"
        )

    # obs:child_dispatch_count TIMING CHECK
    # Turn 1 snapshot is built BEFORE execution, so dispatch_count is stale (from init=0 or absent)
    if turn1_state:
        turn1_dispatch = turn1_state.get("obs:child_dispatch_count")
        print(f"\n  TIMING CHECK: Turn 1 obs:child_dispatch_count = {turn1_dispatch}")
        print(f"    (Expected: ABSENT or 0, because snapshot is BEFORE this turn's dispatch)")

    # Turn 2 snapshot reads the flush from turn 1
    if turn2_state:
        turn2_dispatch = turn2_state.get("obs:child_dispatch_count")
        print(f"  TIMING CHECK: Turn 2 obs:child_dispatch_count = {turn2_dispatch}")
        print(f"    (Expected: 1, because it reads turn 1's flushed value)")

    # Final state: turn 2 flushed with 0 dispatches
    print(f"  TIMING CHECK: Final obs:child_dispatch_count = {final_dispatch}")
    print(f"    (Expected: 0, because turn 2 had no dispatches)")

    # === CUMULATIVE DISPATCH COUNT ASSERTIONS ===

    # Turn 1: obs:child_dispatch_count_total should be present (seeded in initial_state), value 0
    if turn1_state:
        turn1_total = turn1_state.get("obs:child_dispatch_count_total")
        assert turn1_total is not None, "obs:child_dispatch_count_total should be present on turn 1 (seeded in initial_state)"
        assert turn1_total == 0, f"Turn 1 obs:child_dispatch_count_total should be 0, got {turn1_total}"
        print(f"\n  CUMULATIVE CHECK: Turn 1 obs:child_dispatch_count_total = {turn1_total} (PASS: present and 0)")

    # Turn 2: cumulative dispatch count should be 1 (turn 1 dispatched one child)
    if turn2_state:
        turn2_total = turn2_state.get("obs:child_dispatch_count_total")
        assert turn2_total == 1, f"Turn 2 obs:child_dispatch_count_total should be 1, got {turn2_total}"
        print(f"  CUMULATIVE CHECK: Turn 2 obs:child_dispatch_count_total = {turn2_total} (PASS: cumulative=1)")

    # Final state: cumulative count equals total dispatches across all iterations
    final_total = result.final_state.get("obs:child_dispatch_count_total")
    assert final_total == 1, f"Final obs:child_dispatch_count_total should be 1, got {final_total}"
    print(f"  CUMULATIVE CHECK: Final obs:child_dispatch_count_total = {final_total} (PASS: total=1)")

    assert result.contract.passed, result.contract.diagnostics()
    print(f"\n  Contract PASS")
