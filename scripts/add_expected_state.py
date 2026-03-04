#!/usr/bin/env python3
"""Add expected_state blocks to provider-fake fixture JSON files.

Values are derived from FMEA test assertions (test_fmea_e2e.py) which
document the correct expected values for each fixture.
"""

import json
from pathlib import Path

FIXTURE_DIR = Path("tests_rlm_adk/fixtures/provider_fake")

# Mapping: fixture_stem -> expected_state dict
# Values cross-referenced from test_fmea_e2e.py assertions
EXPECTED_STATE: dict[str, dict] = {
    # --- Worker batch fixtures (K=3) ---
    "worker_429_mid_batch": {
        "worker_dispatch_count": 3,
        "obs:worker_total_batch_dispatches": 1,
        "obs:worker_dispatch_latency_ms": {"$type": "list", "$not_empty": True},
        "obs:worker_error_counts": {"$not_none": True, "$not_empty": True},
        "last_repl_result": {"$not_none": True},
    },
    "all_workers_fail_batch": {
        "worker_dispatch_count": 3,
        "obs:worker_total_batch_dispatches": 1,
        "obs:worker_error_counts": {"$not_none": True, "$not_empty": True},
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_batched_k3": {
        "worker_dispatch_count": 3,
        "obs:worker_total_batch_dispatches": 1,
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_batched_k3_with_retry": {
        "worker_dispatch_count": 3,
        "obs:worker_total_batch_dispatches": 1,
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_batched_k3_multi_retry": {
        "worker_dispatch_count": 3,
        "obs:worker_total_batch_dispatches": 1,
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_batched_k3_mixed_exhaust": {
        "worker_dispatch_count": 3,
        "obs:worker_total_batch_dispatches": 1,
        "last_repl_result": {"$not_none": True},
    },

    # --- Worker batch fixtures (K=2) ---
    "worker_empty_response": {
        "worker_dispatch_count": 2,
        "obs:worker_error_counts": {"$not_none": True, "$has_key": "SAFETY"},
        "last_repl_result": {"$not_none": True},
    },
    "worker_empty_response_finish_reason": {
        "worker_dispatch_count": 2,
        "obs:worker_error_counts": {"$not_none": True, "$has_key": "SAFETY"},
        "last_repl_result": {"$not_none": True},
    },

    # --- Single worker dispatch (K=1) with error tracking ---
    "worker_500_then_success": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "worker_500_retry_exhausted": {
        "worker_dispatch_count": 1,
        "obs:worker_error_counts": {"$not_none": True, "$not_empty": True},
        "last_repl_result": {"$not_none": True},
    },
    "worker_500_retry_exhausted_naive": {
        "worker_dispatch_count": 1,
        "obs:worker_error_counts": {"$not_none": True, "$not_empty": True},
        "last_repl_result": {"$not_none": True},
    },
    "worker_auth_error_401": {
        "worker_dispatch_count": 1,
        "obs:worker_error_counts": {"$not_none": True, "$not_empty": True},
        "last_repl_result": {"$not_none": True},
    },
    "worker_safety_finish": {
        "worker_dispatch_count": {"$gte": 1},
        "obs:worker_error_counts": {"$not_none": True, "$has_key": "SAFETY"},
        "last_repl_result": {"$not_none": True},
    },
    "worker_malformed_json": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },

    # --- Single worker dispatch (K=1) without error tracking ---
    "worker_max_tokens_truncated": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "worker_max_tokens_naive": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },

    # --- Structured output (K=1) ---
    "structured_output_retry_exhaustion": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_retry_exhaustion_pure_validation": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_retry_empty": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "structured_output_retry_validation": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },

    # --- REPL with worker dispatch (multi-iteration, last iter delta) ---
    "repl_error_then_retry": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "repl_exception_then_retry": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },
    "repl_cancelled_during_async": {
        "worker_dispatch_count": 1,
        "last_repl_result": {"$not_none": True},
    },

    # --- REPL error without workers ---
    "repl_syntax_error": {
        "last_repl_result": {"$not_none": True},
    },
    "repl_runtime_error": {
        "last_repl_result": {"$not_none": True},
    },
    "repl_runtime_error_partial_state": {
        "last_repl_result": {"$not_none": True},
    },

    # --- Max iterations ---
    "max_iterations_exceeded": {
        "last_repl_result": {"$not_none": True},
    },
    "max_iterations_exceeded_persistent": {
        "last_repl_result": {"$not_none": True},
    },

    # --- Empty/safety reasoning output ---
    "empty_reasoning_output": {
        "should_stop": True,
    },
    "empty_reasoning_output_safety": {
        "should_stop": True,
    },
    "reasoning_safety_finish": {
        "should_stop": True,
    },

    # --- No-REPL / reasoning-only ---
    "fault_429_then_success": {
        "reasoning_input_tokens": {"$gt": 0},
    },
}


def main():
    updated = 0
    skipped = 0
    for fixture_path in sorted(FIXTURE_DIR.glob("*.json")):
        if fixture_path.name == "index.json":
            continue

        stem = fixture_path.stem
        if stem not in EXPECTED_STATE:
            print(f"  SKIP: {stem} (no expected_state mapping)")
            skipped += 1
            continue

        with open(fixture_path) as f:
            data = json.load(f)

        if "expected_state" in data:
            print(f"  SKIP: {stem} (already has expected_state)")
            skipped += 1
            continue

        data["expected_state"] = EXPECTED_STATE[stem]

        with open(fixture_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        n_keys = len(EXPECTED_STATE[stem])
        print(f"  ADD:  {stem} ({n_keys} keys)")
        updated += 1

    print(f"\nDone: {updated} updated, {skipped} skipped")


if __name__ == "__main__":
    main()
