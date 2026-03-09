# Bug: failed REPL runs can produce negative `trace_summary.wall_time_ms`

## Summary
A failed REPL iteration can emit a negative `wall_time_ms` in `last_repl_result.trace_summary` and in the `repl_traces.json` artifact. Wall time should never be negative.

## Location
- [trace.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py#L103)
- [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L227)
- [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L252)

## Expected
For any REPL execution path, including exceptions and cancellations:
- `trace_summary.wall_time_ms >= 0`
- failed runs should still have a valid non-negative duration, or `0` if timing was not recorded

## Actual
On a failed REPL iteration, `trace_summary.wall_time_ms` can be negative.

## Evidence
Reproduced while inspecting [repl_runtime_error_partial_state.json](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/repl_runtime_error_partial_state.json) through the plugin-enabled provider-fake contract path with `repl_trace_level=2`.

Observed behavior:
- the run produced `repl_traces.json`
- artifact/state contained entries for `d0:i1` and `d0:i2`
- the failed REPL iteration at `d0:i1` had a negative `trace_summary.wall_time_ms`

This is inconsistent with the successful iteration in the same run, which had a normal non-negative wall-time value.

## Likely Root Cause
`REPLTrace.summary()` computes wall time as:
```python
round((self.end_time - self.start_time) * 1000, 2) if self.start_time else 0
```
See [trace.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py#L103).

On failure paths, `REPLTool` still writes `LAST_REPL_RESULT` using the current trace object:
- cancellation path: [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L227)
- exception path: [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L252)

That suggests one of these is happening on error:
- `end_time` is unset or stale while `start_time` is set
- timing fields are written in the wrong order on a failure path
- trace injection / cleanup is bypassed during failure and the summary is computed from inconsistent state

## Impact
Negative wall time makes trace data unreliable for:
- REPL performance analysis
- stuck/looping-code detection
- regression comparison across runs
- any downstream metrics that assume duration is non-negative

It also reduces confidence in trace summaries during the exact class of runs where observability matters most: failures.

## Reproduction
1. Run [repl_runtime_error_partial_state.json](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/repl_runtime_error_partial_state.json) through `run_fixture_contract_with_plugins(..., repl_trace_level=2)`.
2. Load `repl_traces.json` or inspect `last_repl_result.trace_summary` for the failed iteration.
3. Observe negative `wall_time_ms` on the failed REPL step.

## Proposed Fix
Harden trace finalization for error paths so `REPLTrace.summary()` cannot emit negative durations.

Options:
- ensure `end_time` is always set before building `LAST_REPL_RESULT` on failure paths
- clamp negative durations to `0`
- add a defensive invariant in `REPLTrace.summary()` if `end_time < start_time`

The best fix is to correct the failure-path timing lifecycle first, then keep a defensive clamp in `summary()` as a safeguard.
