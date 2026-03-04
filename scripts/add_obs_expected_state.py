#!/usr/bin/env python3
"""Add newly-persistent obs keys to fixture expected_state blocks.

Round 2: Now that ObservabilityPlugin.after_agent_callback persists
ephemeral keys, add declarative assertions for them.
"""

import json
from pathlib import Path

FIXTURE_DIR = Path("tests_rlm_adk/fixtures/provider_fake")

# Base obs keys every fixture should assert
BASE_OBS = {
    "obs:total_calls": {"$gt": 0},
    "obs:total_input_tokens": {"$gt": 0},
    "obs:total_output_tokens": {"$gt": 0},
    "obs:per_iteration_token_breakdown": {"$type": "list", "$not_empty": True},
}

# Fixtures that have safety finish reasons
SAFETY_FIXTURES = {
    "worker_safety_finish",
    "worker_empty_response",
    "worker_empty_response_finish_reason",
    "empty_reasoning_output_safety",
    "reasoning_safety_finish",
}

# Fixtures that have max_tokens finish reasons
MAX_TOKENS_FIXTURES = {
    "worker_max_tokens_truncated",
    "worker_max_tokens_naive",
}

# Special case: reasoning_safety_finish has 0 output tokens (safety-blocked first turn)
ZERO_OUTPUT_TOKEN_FIXTURES = {
    "reasoning_safety_finish",
}


def main():
    updated = 0
    skipped = 0

    for fixture_path in sorted(FIXTURE_DIR.glob("*.json")):
        if fixture_path.name == "index.json":
            continue

        stem = fixture_path.stem

        with open(fixture_path) as f:
            data = json.load(f)

        if "expected_state" not in data:
            print(f"  SKIP: {stem} (no expected_state block)")
            skipped += 1
            continue

        es = data["expected_state"]

        # Check if already has obs keys (idempotent)
        if "obs:total_calls" in es:
            print(f"  SKIP: {stem} (already has obs keys)")
            skipped += 1
            continue

        # Add base obs keys
        es.update(BASE_OBS)

        # Override output tokens for zero-output fixtures
        if stem in ZERO_OUTPUT_TOKEN_FIXTURES:
            es["obs:total_output_tokens"] = {"$gte": 0}

        # Add finish reason keys
        if stem in SAFETY_FIXTURES:
            es["obs:finish_safety_count"] = {"$gt": 0}
        if stem in MAX_TOKENS_FIXTURES:
            es["obs:finish_max_tokens_count"] = {"$gt": 0}

        data["expected_state"] = es

        with open(fixture_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        extras = []
        if stem in SAFETY_FIXTURES:
            extras.append("safety")
        if stem in MAX_TOKENS_FIXTURES:
            extras.append("max_tokens")
        if stem in ZERO_OUTPUT_TOKEN_FIXTURES:
            extras.append("zero_output_override")
        extra_str = f" (+{', '.join(extras)})" if extras else ""
        print(f"  ADD:  {stem}{extra_str}")
        updated += 1

    print(f"\nDone: {updated} updated, {skipped} skipped")


if __name__ == "__main__":
    main()
