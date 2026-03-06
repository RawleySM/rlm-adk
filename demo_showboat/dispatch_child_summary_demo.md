# Dispatch Child Summary Observability

## What was implemented

Per-child observability summaries in `dispatch.py` `_run_child()` finally block. Each child orchestrator dispatch now writes a structured summary dict keyed by `child_obs_key(depth, fanout_idx)` into `_acc_child_summaries`. The summary includes:

- `model` -- target model name
- `elapsed_ms` -- wall-clock latency
- `error` / `error_category` -- success/failure classification
- `prompt_preview` -- first 500 chars of the prompt sent to the child
- `result_preview` -- first 500 chars of the child's result string
- `error_message` -- exception message on failure, None on success

`flush_fn()` merges these summaries into the returned delta dict and resets the accumulator. BUG-13 suppress_count also flows through flush_fn when non-zero.

## Key files

- `rlm_adk/dispatch.py` -- `_run_child()` finally block (lines 175-185), `flush_fn()` (lines 313-339)
- `rlm_adk/state.py` -- `child_obs_key()` function (line 86-88)
- `tests_rlm_adk/test_child_obs_summary.py` -- 13 tests covering all behaviors

## Proof: all 13 tests pass

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_child_obs_summary.py -v
```

Expected output:

```
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_single_dispatch_summary_key_present PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_single_dispatch_summary_has_required_fields PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_single_dispatch_summary_values_correct PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_error_dispatch_summary_has_error_true PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_batch_dispatch_all_fanout_keys_present PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_flush_resets_child_summaries PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_single_dispatch_summary_has_prompt_preview PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_single_dispatch_summary_has_result_preview PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_short_prompt_not_truncated PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_error_dispatch_has_error_detail_in_summary PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_success_dispatch_has_no_error_message PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_batch_dispatch_summaries_have_previews PASSED
tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_depth_limit_does_not_write_summary PASSED
======================== 13 passed in 0.06s =========================
```

## Test coverage breakdown

### (a) prompt_preview -- first 500 chars captured

`test_single_dispatch_summary_has_prompt_preview` sends a 700-char prompt and asserts the summary contains exactly the first 500 characters. `test_short_prompt_not_truncated` verifies short prompts are preserved in full.

```python
# dispatch.py _run_child() finally block, line 182:
"prompt_preview": prompt[:500],
```

### (b) result_preview captured

`test_single_dispatch_summary_has_result_preview` uses a 700-char answer and confirms truncation to 500 chars. `test_batch_dispatch_summaries_have_previews` checks each fanout child gets its own result_preview.

```python
# dispatch.py _run_child() finally block, line 183:
"result_preview": str(_child_result)[:500] if _child_result is not None else None,
```

### (c) error_message on failures

`test_error_dispatch_has_error_detail_in_summary` verifies that when a child raises `RuntimeError("simulated child failure")`, the summary's `error_message` contains that string. `test_success_dispatch_has_no_error_message` confirms `error_message` is None on success.

```python
# dispatch.py _run_child() except block sets _error_message = str(e)
# finally block writes:
"error_message": _error_message,
```

### (d) flush_fn returns and resets accumulators

`test_flush_resets_child_summaries` calls flush_fn twice: first flush contains child_summary keys, second flush has none.

```python
# dispatch.py flush_fn(), lines 331-337:
delta.update(_acc_child_summaries)
# Reset:
_acc_child_summaries.clear()
```

### (e) BUG-13 suppress_count flows through flush_fn

```python
# dispatch.py flush_fn(), lines 327-329:
bug13_count = _bug13_stats.get("suppress_count", 0)
if bug13_count > 0:
    delta["obs:bug13_suppress_count"] = bug13_count
```

This reads the global `_bug13_stats` dict from `worker_retry.py` and includes the suppress count in the delta when non-zero.

## Verify child_obs_key format

```bash
.venv/bin/python -c "from rlm_adk.state import child_obs_key; print(child_obs_key(1, 0)); print(child_obs_key(2, 3))"
```

Expected:

```
obs:child_summary@d1f0
obs:child_summary@d2f3
```

## Verify flush_fn delta structure (interactive)

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_child_obs_summary.py::TestChildObsSummary::test_single_dispatch_summary_has_required_fields -v -s
```

## Run full test suite to confirm no regressions

```bash
.venv/bin/python -m pytest tests_rlm_adk/ -v --tb=short -q 2>&1 | tail -5
```
