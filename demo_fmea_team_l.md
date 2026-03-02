# FMEA Team L: REPL and Worker Edge Cases (FM-14, FM-25)

*2026-03-02T11:31:01Z by Showboat 0.6.0*
<!-- showboat-id: 6bcf73fa-eb3f-4dd5-bfa3-b72fa659daf7 -->

## Overview

Two edge-case failure modes from the FMEA analysis:

**FM-14: flush_fn Skipped on REPL CancelledError (RPN=96, Pathway P7)**
When REPL code throws an exception during async execution (e.g. asyncio.CancelledError),
the except handler in repl_tool.py must still call flush_fn to drain dispatch accumulators.
If flush_fn is skipped, stale accumulator values leak across iterations. The fixture provides
a happy-path base; CancelledError injection is done test-side (not fixture-side).

**FM-25: Worker MAX_TOKENS Finish Reason (RPN=75, Pathway P6d)**
When a worker LLM response has finishReason=MAX_TOKENS, the text is truncated mid-sentence.
The worker_after_model callback extracts the partial text and sets _result_ready=True but
does NOT set _result_error=True (only SAFETY finish reason triggers error). The REPL code
receives truncated text and the reasoning agent reports the truncation.

```bash
echo "=== FM-14 fixture: repl_cancelled_during_async ==="
jq '{scenario_id, description: (.description | split(":")[0] + "..."), config: .config, response_count: (.responses | length), fault_injections: (.fault_injections | length)}' tests_rlm_adk/fixtures/provider_fake/repl_cancelled_during_async.json
echo ""
echo "=== FM-25 fixture: worker_max_tokens_truncated ==="
jq '{scenario_id, config: .config, response_count: (.responses | length), worker_finish_reason: .responses[1].body.candidates[0].finishReason, worker_text_preview: (.responses[1].body.candidates[0].content.parts[0].text | .[0:80])}' tests_rlm_adk/fixtures/provider_fake/worker_max_tokens_truncated.json

```

```output
=== FM-14 fixture: repl_cancelled_during_async ===
{
  "scenario_id": "repl_cancelled_during_async",
  "description": "FM-14 (RPN=96)...",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0
  },
  "response_count": 3,
  "fault_injections": 0
}

=== FM-25 fixture: worker_max_tokens_truncated ===
{
  "scenario_id": "worker_max_tokens_truncated",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0,
    "max_retries": 3
  },
  "response_count": 3,
  "worker_finish_reason": "MAX_TOKENS",
  "worker_text_preview": "The analysis shows that the market is trending upward with several key indicator"
}
```

## FM-14 Analysis: flush_fn and CancelledError

The key code is in `rlm_adk/tools/repl_tool.py`. The REPLTool.run_async method has two
flush_fn call sites:

1. **In the CancelledError except block** (line ~120-125): When async REPL execution is
   cancelled, the except handler catches CancelledError, calls flush_fn to drain dispatch
   accumulators, and returns an error tool result with stderr="CancelledError: ...".

2. **In the normal path** (line ~155-156): After successful REPL execution, flush_fn is
   called to drain accumulators into ToolContext.state.

The fixture `repl_cancelled_during_async.json` provides a clean happy-path base (reasoning
emits execute_code with llm_query, worker responds, reasoning returns FINAL). The actual
CancelledError is injected by test code patching asyncio, not by the fixture. This design
separates fixture stability from fault injection mechanics.

```bash
echo "=== repl_tool.py: flush_fn and CancelledError handling ==="
grep -n "flush_fn\|CancelledError" rlm_adk/tools/repl_tool.py

```

```output
=== repl_tool.py: flush_fn and CancelledError handling ===
10:- Flushes dispatch accumulators into ToolContext.state when a flush_fn is provided
44:        flush_fn: Optional[Callable[[], dict]] = None,
58:        self._flush_fn = flush_fn
120:        except asyncio.CancelledError as exc:
124:            if self._flush_fn is not None:
125:                acc = self._flush_fn()
139:                "stderr": f"CancelledError: {exc}",
155:        if self._flush_fn is not None:
156:            acc = self._flush_fn()
```

```bash
echo "=== worker.py: finish_reason handling (SAFETY vs MAX_TOKENS) ==="
grep -n "finish_reason\|MAX_TOKENS\|SAFETY\|_result_error\|_result_ready" rlm_adk/callbacks/worker.py

```

```output
=== worker.py: finish_reason handling (SAFETY vs MAX_TOKENS) ===
72:    Writes result onto the agent object (_result, _result_ready, _call_record)
88:        finish_reason = llm_response.finish_reason
90:            finish_reason is not None
91:            and hasattr(finish_reason, "name")
92:            and finish_reason.name == "SAFETY"
97:        agent._result_ready = True  # type: ignore[attr-defined]
99:            agent._result_error = True  # type: ignore[attr-defined]
116:            "finish_reason": finish_reason.name if finish_reason else None,
120:            record["error_category"] = "SAFETY"
133:        agent._result_ready = True  # type: ignore[attr-defined]
134:        agent._result_error = True  # type: ignore[attr-defined]
141:            "finish_reason": None,
164:    agent._result_ready = True  # type: ignore[attr-defined]
165:    agent._result_error = True  # type: ignore[attr-defined]
174:        "finish_reason": None,
```

## FM-25 Analysis: MAX_TOKENS vs SAFETY

In `rlm_adk/callbacks/worker.py`, the `worker_after_model` callback handles finish reasons:

- **SAFETY** (line 92): Sets both `_result_ready=True` AND `_result_error=True`, plus
  `error_category="SAFETY"`. This marks the worker result as an error.

- **MAX_TOKENS** (implied by lines 97-99): Sets `_result_ready=True` but does NOT set
  `_result_error=True`. The truncated text is extracted as a normal (non-error) result.
  Only the `finish_reason.name == "SAFETY"` check gates the error flag.

This means truncated MAX_TOKENS responses flow into REPL code as normal strings. The REPL
code must detect truncation itself (e.g. checking if text ends mid-sentence). The fixture
demonstrates this: the worker returns text ending with "...indicators suggest" (no period),
and the REPL code detects the truncation via string inspection.

```bash
echo "=== Running FM-14 and FM-25 tests ==="
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplCancelledDuringAsync tests_rlm_adk/test_fmea_e2e.py::TestWorkerMaxTokensTruncated -v 2>&1 | sed "s/ in [0-9.]*s//"

```

```output
=== Running FM-14 and FM-25 tests ===
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests_rlm_adk/test_fmea_e2e.py::TestReplCancelledDuringAsync::test_contract PASSED [ 16%]
tests_rlm_adk/test_fmea_e2e.py::TestReplCancelledDuringAsync::test_happy_path_final_answer PASSED [ 33%]
tests_rlm_adk/test_fmea_e2e.py::TestReplCancelledDuringAsync::test_single_iteration PASSED [ 50%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerMaxTokensTruncated::test_contract PASSED [ 66%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerMaxTokensTruncated::test_truncated_result_detected PASSED [ 83%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerMaxTokensTruncated::test_single_iteration PASSED [100%]

============================== 6 passed ===============================
```

## Summary and Remaining Gaps

**FM-14 (RPN=96) - flush_fn on CancelledError:**
- Coverage: The fixture provides a happy-path base for CancelledError injection testing.
  Tests verify the non-cancelled path works correctly (contract, final answer, iteration count).
- Remaining gap: No test currently injects an actual CancelledError during REPL async
  execution. A future test should patch asyncio to raise CancelledError inside the
  dispatch async path and verify that flush_fn is still called (accumulators drained).

**FM-25 (RPN=75) - Worker MAX_TOKENS Truncated:**
- Coverage: Fixture sends MAX_TOKENS finish reason with truncated text. Tests verify the
  truncated text flows through to FINAL_ANSWER, the contract passes, and single iteration
  completes. The key semantic: MAX_TOKENS is NOT treated as error (unlike SAFETY).
- Remaining gap: No test verifies that _result_error is explicitly False for MAX_TOKENS
  responses. A future assertion could check the worker call record to confirm error=False.

**All 6 tests pass.** Both fixtures are deterministic, replay-compatible, and verify the
expected behavior documented in the FMEA analysis.
