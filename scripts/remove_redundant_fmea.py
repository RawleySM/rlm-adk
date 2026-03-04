#!/usr/bin/env python3
"""Remove FMEA test methods subsumed by declarative expected_state.

Only removes pure single-state-key assertion methods that now have
declarative equivalents in fixture JSON expected_state blocks.
"""

import re
from pathlib import Path

FMEA_PATH = Path("tests_rlm_adk/test_fmea_e2e.py")

# Methods to remove: (class_name, method_name)
# Each is a pure single-state-key assertion now covered by expected_state
METHODS_TO_REMOVE = [
    # TestWorker429MidBatch
    ("TestWorker429MidBatch", "test_worker_dispatch_count"),
    ("TestWorker429MidBatch", "test_obs_batch_dispatch_count"),
    ("TestWorker429MidBatch", "test_obs_error_counts_rate_limit"),
    # TestReplErrorThenRetry
    ("TestReplErrorThenRetry", "test_worker_dispatch_count_both_iterations"),
    # TestStructuredOutputBatchedK3
    ("TestStructuredOutputBatchedK3", "test_obs_batch_dispatch_count"),
    # TestWorkerEmptyResponse
    ("TestWorkerEmptyResponse", "test_worker_dispatch_count"),
    ("TestWorkerEmptyResponse", "test_obs_finish_safety_tracked"),
    # TestWorker500ThenSuccess
    ("TestWorker500ThenSuccess", "test_worker_dispatch_count"),
    # TestAllWorkersFail
    ("TestAllWorkersFail", "test_worker_dispatch_count"),
    # TestEmptyReasoningOutput
    ("TestEmptyReasoningOutput", "test_should_stop_is_true"),
    # TestWorkerSafetyFinish
    ("TestWorkerSafetyFinish", "test_worker_dispatch_counted"),
    ("TestWorkerSafetyFinish", "test_obs_finish_safety_tracked"),
    # TestStructuredOutputBatchedK3WithRetry
    ("TestStructuredOutputBatchedK3WithRetry", "test_dispatch_count_equals_3"),
    ("TestStructuredOutputBatchedK3WithRetry", "test_obs_batch_dispatch_count"),
    # TestReplCancelledDuringAsync
    ("TestReplCancelledDuringAsync", "test_worker_dispatch_count"),
    # TestReplExceptionThenRetry
    ("TestReplExceptionThenRetry", "test_worker_dispatch_count_no_drift"),
    # TestWorker500RetryExhausted
    ("TestWorker500RetryExhausted", "test_worker_dispatch_count"),
    ("TestWorker500RetryExhausted", "test_obs_error_counts_server"),
    # TestWorkerMaxTokensTruncated
    ("TestWorkerMaxTokensTruncated", "test_worker_dispatch_count"),
    # TestWorkerMalformedJson
    ("TestWorkerMalformedJson", "test_worker_dispatch_count"),
    ("TestWorkerMalformedJson", "test_obs_error_counts_malformed"),
    # TestStructuredOutputRetryExhaustion
    ("TestStructuredOutputRetryExhaustion", "test_worker_dispatch_count"),
    # TestWorker500RetryExhaustedNaive
    ("TestWorker500RetryExhaustedNaive", "test_obs_error_counts_present"),
    # TestWorkerAuthError401
    ("TestWorkerAuthError401", "test_worker_dispatch_count"),
    ("TestWorkerAuthError401", "test_obs_error_counts_tracked"),
    # TestWorkerEmptyResponseFinishReason
    ("TestWorkerEmptyResponseFinishReason", "test_obs_error_counts_safety"),
    # TestStructuredOutputRetryExhaustionPureValidation
    ("TestStructuredOutputRetryExhaustionPureValidation", "test_worker_dispatch_count"),
    # TestStructuredOutputBatchedK3MultiRetry
    ("TestStructuredOutputBatchedK3MultiRetry", "test_dispatch_count_equals_3"),
    ("TestStructuredOutputBatchedK3MultiRetry", "test_obs_batch_dispatches"),
    # TestStructuredOutputBatchedK3MixedExhaust
    ("TestStructuredOutputBatchedK3MixedExhaust", "test_dispatch_count_equals_3"),
]


def remove_methods(source: str, methods: list[tuple[str, str]]) -> str:
    """Remove specified methods from source, preserving class structure."""
    lines = source.split("\n")
    result_lines = []
    skip_until_next_method = False
    current_class = None
    methods_set = set(methods)
    removed = set()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track current class
        class_match = re.match(r"^class (\w+)", line)
        if class_match:
            current_class = class_match.group(1)
            skip_until_next_method = False

        # Check if this is a method def we should remove
        method_match = re.match(r"^    async def (test_\w+)\(", line)
        if not method_match:
            method_match = re.match(r"^    def (test_\w+)\(", line)

        if method_match and current_class:
            method_name = method_match.group(1)
            if (current_class, method_name) in methods_set:
                # Skip this method: consume lines until next method/class/section
                removed.add((current_class, method_name))
                # Remove any preceding blank lines that were method separator
                while result_lines and result_lines[-1].strip() == "":
                    result_lines.pop()
                skip_until_next_method = True
                i += 1
                continue

        if skip_until_next_method:
            # Check if this line starts a new method, class, or section
            if (stripped.startswith("async def test_") or
                stripped.startswith("def test_") or
                stripped.startswith("class ") or
                stripped.startswith("# ===") or
                (stripped == "" and i + 1 < len(lines) and
                 (lines[i + 1].strip().startswith("async def test_") or
                  lines[i + 1].strip().startswith("def test_") or
                  lines[i + 1].strip().startswith("class ") or
                  lines[i + 1].strip().startswith("# ===")))):
                skip_until_next_method = False
                # Add blank line separator before next method
                result_lines.append("")
                result_lines.append(line)
                i += 1
                continue
            else:
                i += 1
                continue

        result_lines.append(line)
        i += 1

    # Report
    not_found = methods_set - removed
    if not_found:
        print(f"WARNING: {len(not_found)} methods not found:")
        for cls, meth in sorted(not_found):
            print(f"  {cls}.{meth}")

    print(f"Removed {len(removed)} methods")
    return "\n".join(result_lines)


def main():
    source = FMEA_PATH.read_text()
    original_lines = len(source.split("\n"))

    result = remove_methods(source, METHODS_TO_REMOVE)

    new_lines = len(result.split("\n"))
    print(f"Lines: {original_lines} -> {new_lines} (removed {original_lines - new_lines})")

    FMEA_PATH.write_text(result)
    print(f"Written to {FMEA_PATH}")


if __name__ == "__main__":
    main()
