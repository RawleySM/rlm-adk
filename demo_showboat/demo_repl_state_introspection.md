# REPL State Introspection: _rlm_state Read-Only Snapshot

*2026-03-17T17:40:48Z by Showboat 0.6.0*
<!-- showboat-id: 922b9e06-35f0-4292-9809-a5f2b1e9c581 -->

## Feature Summary

This feature injects a read-only snapshot of allowlisted session state keys into the REPL namespace as `_rlm_state`, enabling REPL code to introspect session state without violating AR-CRIT-001 (no direct state writes from REPL).

**Production code changes:** 2 files (`rlm_adk/state.py`, `rlm_adk/tools/repl_tool.py`)
**New test file:** `tests_rlm_adk/test_repl_state_snapshot.py` (6 unit + 2 e2e)
**New fixture:** `tests_rlm_adk/fixtures/provider_fake/repl_state_introspection.json`

## Step 1: New Constants in state.py

`REPL_STATE_SNAPSHOT` and `EXPOSED_STATE_KEYS` define the injection target name and the allowlist of keys.

```bash
sed -n "151,174p" rlm_adk/state.py
```

```output
# REPL State Introspection
REPL_STATE_SNAPSHOT = "_rlm_state"

EXPOSED_STATE_KEYS: frozenset[str] = frozenset(
    {
        ITERATION_COUNT,
        CURRENT_DEPTH,
        APP_MAX_ITERATIONS,
        APP_MAX_DEPTH,
        OBS_CHILD_DISPATCH_COUNT,
        OBS_CHILD_ERROR_COUNTS,
        OBS_CHILD_DISPATCH_LATENCY_MS,
        OBS_CHILD_TOTAL_BATCH_DISPATCHES,
        OBS_TOTAL_INPUT_TOKENS,
        OBS_TOTAL_OUTPUT_TOKENS,
        REASONING_INPUT_TOKENS,
        REASONING_OUTPUT_TOKENS,
        OBS_STRUCTURED_OUTPUT_FAILURES,
        OBS_REWRITE_COUNT,
        OBS_REWRITE_FAILURE_COUNT,
        LAST_REPL_RESULT,
        REPL_SUBMITTED_CODE_CHARS,
    }
)
```

## Step 2: Snapshot Injection in REPLTool.run_async()

Before code execution, REPLTool builds a dict from allowlisted state keys (using depth-scoped lookups where applicable) and injects it as `_rlm_state` in the REPL namespace.

```bash
grep -n "_state_snapshot" rlm_adk/tools/repl_tool.py
```

```output
186:        _state_snapshot: dict[str, Any] = {}
191:                _state_snapshot[key] = val  # Use unscoped key name for clean API
192:        self.repl.globals[REPL_STATE_SNAPSHOT] = _state_snapshot
```

```bash
sed -n "185,193p" rlm_adk/tools/repl_tool.py
```

```output
        # Build read-only state snapshot for REPL introspection
        _state_snapshot: dict[str, Any] = {}
        for key in EXPOSED_STATE_KEYS:
            scoped = depth_key(key, self._depth) if key in DEPTH_SCOPED_KEYS else key
            val = tool_context.state.get(scoped)
            if val is not None:
                _state_snapshot[key] = val  # Use unscoped key name for clean API
        self.repl.globals[REPL_STATE_SNAPSHOT] = _state_snapshot

```

## Step 3: Provider-Fake Fixture

The `repl_state_introspection.json` fixture scripts a model that emits `execute_code` printing `_rlm_state['iteration_count']` and `_rlm_state['current_depth']`, then finalizes.

```bash
python3 -c "import json; d=json.load(open(\"tests_rlm_adk/fixtures/provider_fake/repl_state_introspection.json\")); print(json.dumps({\"scenario_id\":d[\"scenario_id\"],\"code_in_iter1\":d[\"responses\"][0][\"body\"][\"candidates\"][0][\"content\"][\"parts\"][0][\"functionCall\"][\"args\"][\"code\"],\"expected_final_answer\":d[\"expected\"][\"final_answer\"],\"expected_stdout_contains\":d[\"expected_contract\"][\"tool_results\"][\"stdout_contains\"]}, indent=2))"
```

```output
{
  "scenario_id": "repl_state_introspection",
  "code_in_iter1": "print(f\"iter={_rlm_state['iteration_count']}\")\nprint(f\"depth={_rlm_state['current_depth']}\")",
  "expected_final_answer": "State introspection succeeded: iter=1, depth=0",
  "expected_stdout_contains": [
    "iter=1",
    "depth=0"
  ]
}
```

## Step 4: Test Results

Running the new test file (6 unit tests + 2 e2e tests):

```bash
/home/rawley-stanhope/dev/rlm-adk/.venv/bin/python -m pytest tests_rlm_adk/test_repl_state_snapshot.py -v --no-header --tb=no 2>&1 | grep -E "PASSED|FAILED|passed|failed"
```

```output
tests_rlm_adk/test_repl_state_snapshot.py::TestSnapshotInjectedIntoRepl::test_snapshot_injected_into_repl PASSED [ 12%]
tests_rlm_adk/test_repl_state_snapshot.py::TestSnapshotInjectedIntoRepl::test_snapshot_contains_expected_keys PASSED [ 25%]
tests_rlm_adk/test_repl_state_snapshot.py::TestSnapshotInjectedIntoRepl::test_snapshot_is_read_only_safe PASSED [ 37%]
tests_rlm_adk/test_repl_state_snapshot.py::TestSnapshotInjectedIntoRepl::test_snapshot_depth_scoping PASSED [ 50%]
tests_rlm_adk/test_repl_state_snapshot.py::TestSnapshotInjectedIntoRepl::test_snapshot_refreshed_each_call PASSED [ 62%]
tests_rlm_adk/test_repl_state_snapshot.py::TestSnapshotInjectedIntoRepl::test_snapshot_omits_none_values PASSED [ 75%]
tests_rlm_adk/test_repl_state_snapshot.py::TestReplStateIntrospectionE2E::test_fixture_contract PASSED [ 87%]
tests_rlm_adk/test_repl_state_snapshot.py::TestReplStateIntrospectionE2E::test_stdout_contains_state_values PASSED [100%]
======================== 8 passed, 6 warnings in 1.08s =========================
```

## Step 5: Regression and Lint Check

Default suite passes with zero regressions. Lint and format checks pass on all changed files.

```bash
/home/rawley-stanhope/dev/rlm-adk/.venv/bin/ruff check rlm_adk/state.py rlm_adk/tools/repl_tool.py tests_rlm_adk/test_repl_state_snapshot.py 2>&1 && /home/rawley-stanhope/dev/rlm-adk/.venv/bin/ruff format --check rlm_adk/state.py rlm_adk/tools/repl_tool.py tests_rlm_adk/test_repl_state_snapshot.py 2>&1
```

```output
All checks passed!
3 files already formatted
```

```bash
/home/rawley-stanhope/dev/rlm-adk/.venv/bin/python -m pytest tests_rlm_adk/ -q --no-header --tb=no 2>&1 | grep -oP "\d+ passed" | head -1
```

```output
38 passed
```
