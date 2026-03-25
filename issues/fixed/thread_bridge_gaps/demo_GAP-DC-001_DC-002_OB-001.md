# Demo: GAP-DC-001 + GAP-DC-002 + GAP-OB-001 -- Dead AST rewrite observability constants

## What was fixed

The AST rewriter was deleted in Phase 0A (thread bridge migration), but four observability constants and their string-literal references survived across production code and test files. All vestiges have been removed.

| Gap | Scope | What was dead |
|-----|-------|---------------|
| GAP-DC-001 | `rlm_adk/state.py` | 4 constant definitions (`OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`, `OBS_REWRITE_FAILURE_COUNT`, `OBS_REWRITE_FAILURE_CATEGORIES`) |
| GAP-DC-002 | `rlm_adk/dashboard/live_loader.py` | 3 entries in `_KNOWN_OBS_KEYS` list (`obs:rewrite_count`, `obs:rewrite_total_ms`, `obs:rewrite_failure_count`) |
| GAP-OB-001 | Both files above | Observability keys defined + monitored but never written (no writer exists post-rewriter deletion) |

## Dead code that was removed

### From `rlm_adk/state.py` (4 constants + comment)

```python
# AST Rewrite Instrumentation (written by REPLTool)
OBS_REWRITE_COUNT = "obs:rewrite_count"
OBS_REWRITE_TOTAL_MS = "obs:rewrite_total_ms"
OBS_REWRITE_FAILURE_COUNT = "obs:rewrite_failure_count"
OBS_REWRITE_FAILURE_CATEGORIES = "obs:rewrite_failure_categories"
```

### From `rlm_adk/dashboard/live_loader.py` (3 list entries)

```python
    "obs:rewrite_count",
    "obs:rewrite_total_ms",
    "obs:rewrite_failure_count",
```

### From 5 test files (stale `obs:rewrite` references)

| File | What was removed/replaced |
|------|--------------------------|
| `tests_rlm_adk/provider_fake/instrumented_runner.py` | Removed `obs:rewrite_count` and `obs:rewrite_total_ms` references |
| `tests_rlm_adk/test_instrumented_runner_unit.py` | Replaced `obs:rewrite_count` test example with a live key |
| `tests_rlm_adk/test_stdout_parser.py` | Replaced `obs:rewrite_count` test example with a live key |
| `tests_rlm_adk/test_rlm_state_snapshot_audit.py` | Removed from diagnostic list |
| `tests_rlm_adk/test_state_accuracy_diagnostic.py` | Removed from `TRACKED_KEYS` |

## Verification commands

### 1. Zero `OBS_REWRITE` references in production code

```bash
grep -r "OBS_REWRITE" rlm_adk/
```

Expected: no output (exit code 1).

### 2. Zero `obs:rewrite` references in test code

```bash
grep -r "obs:rewrite" tests_rlm_adk/
```

Expected: no output (exit code 1).

### 3. Zero references anywhere in the repo (excluding gap documentation)

```bash
grep -r "OBS_REWRITE\|obs:rewrite" rlm_adk/ tests_rlm_adk/
```

Expected: no output (exit code 1).

## Verification Checklist

- [ ] `grep -r "OBS_REWRITE" rlm_adk/` returns zero matches
- [ ] `grep -r "obs:rewrite" tests_rlm_adk/` returns zero matches
- [ ] `state.py` no longer defines any `OBS_REWRITE_*` constants
- [ ] `live_loader.py` `_KNOWN_OBS_KEYS` contains no `obs:rewrite_*` entries
- [ ] All 5 test files compile without `obs:rewrite` references
