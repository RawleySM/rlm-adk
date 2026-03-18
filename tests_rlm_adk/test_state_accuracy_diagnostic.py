"""Diagnostic: verify state variable accuracy at each REPL turn.

Runs multi-iteration and fanout fixtures, inspects events for state_delta
at each step, and confirms iteration_count, obs:child_dispatch_count, and
other key state variables are accurate and monotonically correct.

NOT a permanent test — diagnostic script for state accuracy audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.contract_runner import (
    run_fixture_contract_with_plugins,
)

FIXTURE_DIR = Path("tests_rlm_adk/fixtures/provider_fake")

# State keys we want to track across events
TRACKED_KEYS = {
    "iteration_count",
    "obs:child_dispatch_count",
    "obs:child_error_counts",
    "obs:child_total_batch_dispatches",
    "obs:child_dispatch_count_total",
    "obs:child_batch_dispatches_total",
    "obs:child_error_counts_total",
    "obs:structured_output_failures_total",
    "obs:total_input_tokens",
    "obs:total_output_tokens",
    "obs:total_calls",
    "obs:per_iteration_token_breakdown",
    "obs:tool_invocation_summary",
    "obs:finish_max_tokens_count",
    "obs:rewrite_count",
    "last_repl_result",
    "reasoning_input_tokens",
    "reasoning_output_tokens",
}


def _extract_state_timeline(events: list) -> list[dict]:
    """Extract per-event state_delta timeline for tracked keys."""
    timeline = []
    for i, event in enumerate(events):
        sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        if not sd:
            continue
        tracked = {}
        for k, v in sd.items():
            # Match exact keys or keys that start with tracked prefixes
            for tk in TRACKED_KEYS:
                if k == tk or k.startswith(tk):
                    tracked[k] = v
                    break
            # Also capture any key containing "iteration" or "dispatch"
            if "iteration" in k or "dispatch" in k or "child_summary" in k:
                tracked[k] = v

        if tracked:
            # Get event metadata
            author = getattr(event, "author", "?")
            has_fc = bool(event.get_function_calls()) if hasattr(event, "get_function_calls") else False
            has_fr = bool(event.get_function_responses()) if hasattr(event, "get_function_responses") else False
            content_text = ""
            if event.content and event.content.parts:
                for p in event.content.parts:
                    if hasattr(p, "text") and p.text:
                        content_text = p.text[:80]
                        break
            timeline.append({
                "event_idx": i,
                "author": author,
                "has_function_call": has_fc,
                "has_function_response": has_fr,
                "content_preview": content_text,
                "state_delta": tracked,
            })
    return timeline


def _build_cumulative_state(events: list, keys: set[str] | None = None) -> dict:
    """Replay all state_deltas to build cumulative state (like session service does)."""
    state: dict = {}
    for event in events:
        sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        for k, v in sd.items():
            if keys is None or any(k == tk or k.startswith(tk) for tk in keys):
                state[k] = v
    return state


def _print_timeline(fixture_name: str, timeline: list[dict], final_state: dict):
    """Pretty-print the state timeline for a fixture."""
    print(f"\n{'='*80}")
    print(f"FIXTURE: {fixture_name}")
    print(f"{'='*80}")

    for entry in timeline:
        print(f"\n  Event #{entry['event_idx']} | author={entry['author']} "
              f"| FC={entry['has_function_call']} FR={entry['has_function_response']}")
        if entry["content_preview"]:
            print(f"    content: {entry['content_preview']!r}")
        for k, v in sorted(entry["state_delta"].items()):
            # Truncate long values
            vs = repr(v)
            if len(vs) > 120:
                vs = vs[:117] + "..."
            print(f"    {k} = {vs}")

    print(f"\n  --- FINAL STATE (tracked keys) ---")
    for k in sorted(final_state):
        for tk in TRACKED_KEYS:
            if k == tk or k.startswith(tk):
                v = final_state[k]
                vs = repr(v)
                if len(vs) > 120:
                    vs = vs[:117] + "..."
                print(f"    {k} = {vs}")
                break
        if "child_summary" in k:
            v = final_state[k]
            vs = repr(v)
            if len(vs) > 120:
                vs = vs[:117] + "..."
            print(f"    {k} = {vs}")


# Fixtures to audit: multi-iteration and fanout scenarios
AUDIT_FIXTURES = [
    "fake_recursive_ping",          # 2 iterations, recursive
    "max_iterations_exceeded",       # 3 iterations, hits limit
    "instruction_router_fanout",    # fanout with batched
    "repl_error_then_retry",        # 2 iterations, error recovery
    "worker_500_retry_exhausted",   # fault injection, 1 iter
    "worker_max_tokens_truncated",  # MAX_TOKENS finish, 1 iter
]


@pytest.mark.provider_fake_contract
@pytest.mark.parametrize("fixture_name", AUDIT_FIXTURES)
async def test_state_accuracy_audit(fixture_name: str, tmp_path: Path):
    """Run fixture, dump per-event state timeline, verify iteration_count accuracy."""
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")

    # Load fixture to get expected values
    with open(fixture_path) as f:
        fixture = json.load(f)
    expected_iterations = fixture.get("expected", {}).get("total_iterations", 0)
    expected_calls = fixture.get("expected", {}).get("total_model_calls", 0)

    result = await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
        tmpdir=str(tmp_path),
    )

    timeline = _extract_state_timeline(result.events)
    _print_timeline(fixture_name, timeline, result.final_state)

    # === ACCURACY CHECKS ===

    # 1. iteration_count must be monotonically non-decreasing across events
    iter_values = []
    for entry in timeline:
        for k, v in entry["state_delta"].items():
            if k == "iteration_count" or k.startswith("iteration_count"):
                iter_values.append((entry["event_idx"], k, v))

    print(f"\n  --- ITERATION_COUNT TRACE ---")
    for idx, key, val in iter_values:
        print(f"    event #{idx}: {key} = {val}")

    if iter_values:
        # Group by key (depth-scoped keys may differ)
        by_key: dict[str, list[tuple[int, int]]] = {}
        for idx, key, val in iter_values:
            by_key.setdefault(key, []).append((idx, val))

        for key, vals in by_key.items():
            values_only = [v for _, v in vals]
            print(f"\n    {key} progression: {values_only}")
            # Must be monotonically non-decreasing
            for i in range(1, len(values_only)):
                assert values_only[i] >= values_only[i - 1], (
                    f"iteration_count DECREASED at event: "
                    f"{values_only[i-1]} -> {values_only[i]} "
                    f"(key={key}, events={vals[i-1][0]}->{vals[i][0]})"
                )

    # 2. Final iteration_count should match expected_iterations
    final_iter = result.final_state.get("iteration_count", 0)
    print(f"\n  final iteration_count = {final_iter}, expected = {expected_iterations}")
    if expected_iterations > 0:
        assert final_iter == expected_iterations, (
            f"Final iteration_count={final_iter} != expected={expected_iterations}"
        )

    # 3. obs:child_dispatch_count: track what it looks like per event
    dispatch_values = []
    for entry in timeline:
        for k, v in entry["state_delta"].items():
            if k == "obs:child_dispatch_count":
                dispatch_values.append((entry["event_idx"], v))

    if dispatch_values:
        print(f"\n  --- OBS:CHILD_DISPATCH_COUNT TRACE ---")
        for idx, val in dispatch_values:
            print(f"    event #{idx}: obs:child_dispatch_count = {val}")

    # 3b. obs:child_dispatch_count_total must be monotonically non-decreasing
    cum_dispatch_values = []
    for entry in timeline:
        for k, v in entry["state_delta"].items():
            if k == "obs:child_dispatch_count_total":
                cum_dispatch_values.append((entry["event_idx"], v))

    if cum_dispatch_values:
        print("\n  --- OBS:CHILD_DISPATCH_COUNT_TOTAL TRACE ---")
        for idx, val in cum_dispatch_values:
            print(f"    event #{idx}: obs:child_dispatch_count_total = {val}")

        values_only = [v for _, v in cum_dispatch_values]
        print(f"    progression: {values_only}")
        for i in range(1, len(values_only)):
            assert values_only[i] >= values_only[i - 1], (
                f"obs:child_dispatch_count_total DECREASED: "
                f"{values_only[i-1]} -> {values_only[i]} "
                f"(events {cum_dispatch_values[i-1][0]} -> {cum_dispatch_values[i][0]})"
            )
        print("    monotonicity check: PASS")

    # 4. obs:total_calls should match expected total_model_calls
    final_total_calls = result.final_state.get("obs:total_calls", 0)
    print(f"\n  final obs:total_calls = {final_total_calls}, expected = {expected_calls}")

    # 5. obs:per_iteration_token_breakdown length should match iterations
    breakdown = result.final_state.get("obs:per_iteration_token_breakdown", [])
    print(f"  obs:per_iteration_token_breakdown length = {len(breakdown)}")

    # 6. Cross-check: last_repl_result should exist
    last_repl = result.final_state.get("last_repl_result")
    print(f"  last_repl_result exists = {last_repl is not None}")
    if last_repl:
        print(f"  last_repl_result.has_output = {last_repl.get('has_output')}")
        print(f"  last_repl_result.total_llm_calls = {last_repl.get('total_llm_calls')}")
        stdout_preview = last_repl.get("stdout_preview", "")
        print(f"  last_repl_result.stdout_preview = {stdout_preview[:80]!r}")

    # Contract should pass
    assert result.contract.passed, (
        f"Contract FAILED for {fixture_name}:\n{result.contract.diagnostics()}"
    )

    print(f"\n  PASS ✓")
