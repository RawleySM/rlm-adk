# OG-01 through OG-04: Observability Gap Closures

*2026-03-06T19:42:39Z by Showboat 0.6.0*
<!-- showboat-id: fda55a5d-3fc3-4853-9ea7-d506fa251548 -->

This demo proves that all 4 CRITICAL observability gaps (OG-01 through OG-04) have been closed with passing tests and validated gap registry.

## OG-01: stdout persisted under REPL state key
REPLTool now writes stdout_preview (first 500 chars) into LAST_REPL_RESULT on all 3 paths: success, CancelledError, and Exception.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_og01_stdout_preview.py -v --tb=no 2>&1 | grep -E "PASSED|FAILED|passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_og01_stdout_preview.py::TestStdoutPreview::test_stdout_preview_present_on_success PASSED [ 25%]
tests_rlm_adk/test_og01_stdout_preview.py::TestStdoutPreview::test_stdout_preview_bounded_at_500_chars PASSED [ 50%]
tests_rlm_adk/test_og01_stdout_preview.py::TestStdoutPreview::test_stdout_preview_empty_on_exception PASSED [ 75%]
tests_rlm_adk/test_og01_stdout_preview.py::TestStdoutPreview::test_no_stdout_preview_on_call_limit PASSED [100%]
========================= 4 passed, 1 warning =========================
```

## OG-02: REPL trace summary now lands in tool telemetry
SqliteTracingPlugin reads trace_summary from LAST_REPL_RESULT in after_tool_callback and serializes it into the repl_trace_summary column.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_og02_trace_summary_telemetry.py -v --tb=no 2>&1 | grep -E "PASSED|FAILED|passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_og02_trace_summary_telemetry.py::TestTraceSummaryInTelemetry::test_repl_trace_summary_written_to_telemetry PASSED [ 50%]
tests_rlm_adk/test_og02_trace_summary_telemetry.py::TestTraceSummaryInTelemetry::test_repl_trace_summary_null_when_no_trace PASSED [100%]
========================= 2 passed, 1 warning =========================
```

## OG-03: REPL submitted code captured in session state events
Added repl_submitted_code prefix to SqliteTracingPlugin curated capture set and categorize function.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_og03_submitted_code_sse.py -v --tb=no 2>&1 | grep -E "PASSED|FAILED|passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCapture::test_should_capture_repl_submitted_code PASSED [ 11%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCapture::test_should_capture_repl_submitted_code_preview PASSED [ 22%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCapture::test_should_capture_repl_submitted_code_hash PASSED [ 33%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCapture::test_should_capture_repl_submitted_code_chars PASSED [ 44%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCategory::test_categorize_repl_submitted_code PASSED [ 55%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCategory::test_categorize_repl_submitted_code_preview PASSED [ 66%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCategory::test_categorize_repl_submitted_code_hash PASSED [ 77%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeCategory::test_categorize_repl_submitted_code_chars PASSED [ 88%]
tests_rlm_adk/test_og03_submitted_code_sse.py::TestSubmittedCodeSSEPersistence::test_submitted_code_keys_appear_in_sse PASSED [100%]
========================= 9 passed, 1 warning =========================
```

## OG-04: Negative REPL wall time fixed on failed runs
REPLTrace.summary() and to_dict() now clamp wall_time_ms via max(0, ...) and require both start_time and end_time. REPLTool error paths set trace.end_time before building LAST_REPL_RESULT.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_og04_negative_wall_time.py -v --tb=no 2>&1 | grep -E "PASSED|FAILED|passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_og04_negative_wall_time.py::TestREPLTraceWallTime::test_summary_non_negative_when_end_time_zero PASSED [ 16%]
tests_rlm_adk/test_og04_negative_wall_time.py::TestREPLTraceWallTime::test_to_dict_non_negative_when_end_time_zero PASSED [ 33%]
tests_rlm_adk/test_og04_negative_wall_time.py::TestREPLTraceWallTime::test_summary_non_negative_when_end_before_start PASSED [ 50%]
tests_rlm_adk/test_og04_negative_wall_time.py::TestREPLTraceWallTime::test_summary_zero_when_no_start_time PASSED [ 66%]
tests_rlm_adk/test_og04_negative_wall_time.py::TestREPLToolErrorPathTiming::test_exception_path_has_non_negative_wall_time PASSED [ 83%]
tests_rlm_adk/test_og04_negative_wall_time.py::TestREPLToolErrorPathTiming::test_successful_run_has_positive_wall_time PASSED [100%]
========================= 6 passed, 1 warning =========================
```

## Gap Registry Validation
All 32 gaps resolved: 4 closed, 28 deferred. Registry validates at 100%.

```bash
.venv/bin/python .claude/skills/gap-audit/scripts/gap_guard.py --check-only 2>&1
```

```output
=== GAP REGISTRY: 0 of 32 gaps still pending ===
Mode: report | Phase: greenfield development | Progress: 100% (32/32 resolved)

Resolve via: /gap-audit close|dismiss|defer <gap-id>
```
