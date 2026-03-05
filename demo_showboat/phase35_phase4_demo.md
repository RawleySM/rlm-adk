# Phase 3.5 + Phase 4: E2E Fixture Migration & Observability

*2026-03-04T21:05:08Z by Showboat 0.6.0*
<!-- showboat-id: 10b5f1a2-7af4-495e-bb99-394242b5710a -->

## Phase 3.5: E2E Fixture Migration

Verify that FMEA e2e tests, provider-fake e2e tests, and request body comprehensive tests all pass. Confirm old worker test files were deleted and remaining worker tests are clean.

### FMEA E2E Tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py --tb=no -q 2>&1 | grep -E "passed|failed" | sed "s/ in [0-9.]*s.*//"
```

```output
107 passed, 502 warnings
```

### Provider-Fake E2E Tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py --tb=no -q 2>&1 | grep -E "passed|failed" | sed "s/ in [0-9.]*s.*//"
```

```output
35 passed, 157 warnings
```

### Request Body Comprehensive Tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_request_body_comprehensive.py --tb=no -q 2>&1 | grep -E "passed|failed" | sed "s/ in [0-9.]*s.*//"
```

```output
27 passed, 7 warnings
```

### Old Worker Test Files Deleted

```bash
for f in test_adk_dispatch_worker_pool.py test_bug006_pool_growth.py test_fix_dispatch_events.py test_request_body_verification.py; do [ -f "tests_rlm_adk/$f" ] && echo "FAIL: $f exists" || echo "OK: $f deleted"; done
```

```output
OK: test_adk_dispatch_worker_pool.py deleted
OK: test_bug006_pool_growth.py deleted
OK: test_fix_dispatch_events.py deleted
OK: test_request_body_verification.py deleted
```

### Remaining Worker Tests Clean

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_adk_worker_retry.py tests_rlm_adk/test_source_fixes_fmea.py --tb=no -q 2>&1 | grep -E "passed|failed" | sed "s/ in [0-9.]*s.*//"
```

```output
30 passed, 15 warnings
```

## Phase 4: Observability + Cleanup

Verify depth tagging, context window snapshots, child dispatch logging, and orchestrator cleanup.

### Phase 4 Observability Tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_phase4_observability.py --tb=no -q 2>&1 | grep -E "passed|failed" | sed "s/ in [0-9.]*s.*//"
```

```output
7 passed, 1 warning
```

### Source: _rlm_depth tag set on reasoning_agent (orchestrator.py:180)

```bash
grep -n '_rlm_depth' rlm_adk/orchestrator.py
```

```output
180:        object.__setattr__(self.reasoning_agent, '_rlm_depth', self.depth)
```

### Source: CONTEXT_WINDOW_SNAPSHOT includes depth (reasoning.py:128-132)

```bash
grep -n -A5 '_rlm_depth' rlm_adk/callbacks/reasoning.py
```

```output
128:    _depth = getattr(agent_obj, '_rlm_depth', 0)
129-
130-    callback_context.state[CONTEXT_WINDOW_SNAPSHOT] = {
131-        "agent_type": "reasoning",
132-        "depth": _depth,
133-        "content_count": content_count,
```

### Source: Observability plugin logs child dispatch counts (observability.py:325-344)

```bash
grep -n 'child_dispatch' rlm_adk/plugins/observability.py
```

```output
325:            child_dispatches = state.get(OBS_CHILD_DISPATCH_COUNT, 0)
342:            if child_dispatches > 0:
343:                log_msg += ", child_dispatches=%d"
344:                log_args.append(child_dispatches)
```

### Source: Orchestrator finally block cleans up tool wiring (orchestrator.py:348-353)

```bash
grep -n -A5 'finally:' rlm_adk/orchestrator.py
```

```output
348:        finally:
349-            # Clean up reasoning_agent wiring
350-            object.__setattr__(self.reasoning_agent, 'tools', [])
351-            object.__setattr__(self.reasoning_agent, 'after_tool_callback', None)
352-            object.__setattr__(self.reasoning_agent, 'on_tool_error_callback', None)
353-            if not self.persistent:
```

## Full Regression

Run the complete test suite to confirm no regressions.

```bash
.venv/bin/python -m pytest tests_rlm_adk/ --tb=no -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s.*//"
```

```output
6 failed, 765 passed, 1 skipped, 930 warnings, 1 error
```

All 6 failures and 1 error are pre-existing (confirmed identical on clean main). 765 tests passed, 1 skipped. No regressions from Phase 3.5 or Phase 4.
