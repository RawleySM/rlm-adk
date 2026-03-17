# Understand Bench Trial: Session-State User Context Wiring

*2026-03-16 by Showboat*

## Summary

Wired the understand_bench benchmark to run against the real RLM agent by closing a gap in the orchestrator's user-context injection. Previously, context data could only enter `repl.globals["user_ctx"]` via the `RLM_USER_CTX_DIR` environment variable (Path A). When a replay fixture or benchmark runner pre-seeds `user_provided_ctx` in session state, that data landed in `ctx.session.state` but never reached the REPL globals -- the LLM's code had no way to access it.

The fix adds a Path B fallback: after the env-var check, the orchestrator reads `user_provided_ctx` from `ctx.session.state`, builds a manifest, and injects it into `repl.globals["user_ctx"]` and `initial_state`.

## What Was Built

### 1. Orchestrator Fallback (Path B)

In `rlm_adk/orchestrator.py`, after the `RLM_USER_CTX_DIR` env-var block, an `elif` clause reads pre-seeded `user_provided_ctx` from session state:

```python
# --- Path B: pre-seeded user_provided_ctx in session state ---
elif ctx.session.state.get(USER_PROVIDED_CTX):
    _pre_seeded = ctx.session.state[USER_PROVIDED_CTX]
    initial_state[USER_PROVIDED_CTX] = _pre_seeded
    # Build manifest from the pre-seeded dict
    _filenames = sorted(k for k in _pre_seeded if not k.startswith("_"))
    # ... builds manifest_lines, sets DYN_USER_CTX_MANIFEST ...
    repl.globals["user_ctx"] = _pre_seeded
```

Key design decisions:
- Reads from `ctx.session.state` (not writing to it -- AR-CRIT-001 compliant)
- Writes to `initial_state` dict, which gets yielded as `EventActions(state_delta=initial_state)`
- Internal keys (prefixed with `_`) are excluded from the manifest
- Path A (env var) takes priority when both are present

### 2. Replay Fixture

Created `tests_rlm_adk/replay/bench_case_efile_auth.json` with:
- Pre-seeded `user_provided_ctx` containing the case's full `provided_context_dict` (taxpayer intake, W-2, prior-year summary)
- Pre-seeded `user_ctx_manifest` with file inventory
- `app:max_iterations` = 20 (enough for the 4-phase polya-understand loop)
- `app:max_depth` = 2 (children need depth for child dispatches)
- Query steering the agent to run `polya-understand` against `user_ctx`

### 3. Bridge agent_fn

Added to `rlm_adk/eval/understand_bench/runner.py`:
- `_run_rlm_agent_async()` -- async function that builds pre-seeded state, creates a Runner via `create_rlm_runner()`, executes the agent, and extracts `retrieval_order` + `halted` from REPL output
- `make_rlm_agent_fn()` -- factory returning a sync callable matching the `BenchmarkRunner.run_case()` signature

Usage:
```python
from rlm_adk.eval.understand_bench.runner import BenchmarkRunner, make_rlm_agent_fn

runner = BenchmarkRunner(difficulty_filter="easy")
agent_fn = make_rlm_agent_fn(model="gemini-2.5-flash", max_iterations=20)
result = runner.run_case("case_efile_auth", agent_fn)
print(f"Score: {result.total_score} / 100")
```

### 4. State Key Constants

Added to `rlm_adk/state.py`:
```python
USER_PROVIDED_CTX = "user_provided_ctx"
USER_PROVIDED_CTX_EXCEEDED = "user_provided_ctx_exceeded"
USR_PROVIDED_FILES_SERIALIZED = "usr_provided_files_serialized"
USR_PROVIDED_FILES_UNSERIALIZED = "usr_provided_files_unserialized"
DYN_USER_CTX_MANIFEST = "user_ctx_manifest"
```

## Test Results

20 tests, all passing:

```
$ .venv/bin/python -m pytest tests_rlm_adk/test_orchestrator_user_ctx.py -x -q -o "addopts="
....................
20 passed in 0.10s
```

Test coverage by area:

| # | Test | What it verifies |
|---|------|------------------|
| 1 | `test_env_var_not_set_no_context_loaded` | No context keys when neither path active |
| 2 | `test_env_var_set_loads_context` | Path A: env var loads files into ctx dict |
| 3 | `test_env_var_set_invalid_dir_skipped` | Path A: invalid dir is safe no-op |
| 4 | `test_context_populates_all_state_keys` | Path A: all 5 state keys populated |
| 5 | `test_context_injected_into_repl_globals` | Path A: repl.globals["user_ctx"] set |
| 6 | `test_max_chars_env_var_respected` | Path A: budget eviction works |
| 7 | `test_orchestrator_has_user_context_wiring` | Source inspection: Path A keywords |
| 8 | `test_orchestrator_imports_state_constants` | All 5 constants imported |
| 9 | `test_pre_seeded_ctx_injects_repl_globals` | Path B: repl globals injection |
| 10 | `test_pre_seeded_ctx_populates_all_state_keys` | Path B: all 5 keys |
| 11 | `test_pre_seeded_manifest_generation` | Path B: manifest well-formed |
| 12 | `test_pre_seeded_serialized_files_list` | Path B: sorted filenames, no internals |
| 13 | `test_env_var_takes_priority_over_pre_seeded` | Path A priority over Path B |
| 14 | `test_orchestrator_has_path_b_wiring` | Source inspection: Path B keywords |
| 15 | `test_case_efile_auth_loads_as_benchmark_case` | Case loads as BenchmarkCase |
| 16 | `test_scoring_perfect_agent_output` | Perfect score = 100 |
| 17 | `test_scoring_empty_agent_output` | Empty output scores 0 with penalties |
| 18 | `test_scoring_partial_category_match` | Category match = 50% recall credit |
| 19 | `test_replay_fixture_bench_case_efile_auth_valid` | Fixture has required fields |
| 20 | `test_fixture_pre_seeded_manifest` | Fixture's pre-seeded dict -> valid manifest |

Default regression suite unaffected: 34 passed, 2 skipped.

## How to Run the Benchmark Trial

### Dry-run (no LLM calls)

```bash
.venv/bin/python -m rlm_adk.eval.understand_bench.runner --difficulty easy
```

### With replay fixture

```bash
.venv/bin/adk run --replay tests_rlm_adk/replay/bench_case_efile_auth.json rlm_adk
```

### Programmatic with real agent

```python
from rlm_adk.eval.understand_bench.runner import BenchmarkRunner, make_rlm_agent_fn

runner = BenchmarkRunner(difficulty_filter="easy")
agent_fn = make_rlm_agent_fn(model="gemini-2.5-flash")
result = runner.run_case("case_efile_auth", agent_fn)
print(f"Score: {result.total_score:.1f} / 100")
print(f"Recall: {result.recall:.2f}, Precision: {result.precision:.2f}")
print(f"Halted: {result.halt_score:.0f}, Order: {result.order_score:.2f}")
```

## Files Changed

| File | Change |
|------|--------|
| `rlm_adk/state.py` | Added 5 user-context state key constants |
| `rlm_adk/orchestrator.py` | Added Path A (env var) + Path B (session state) user context wiring |
| `rlm_adk/eval/understand_bench/runner.py` | Added `_run_rlm_agent_async()` + `make_rlm_agent_fn()` bridge |
| `tests_rlm_adk/test_orchestrator_user_ctx.py` | 20 tests covering Path A, Path B, scoring, and fixture validation |
| `tests_rlm_adk/replay/bench_case_efile_auth.json` | Replay fixture with pre-seeded case_efile_auth context |
