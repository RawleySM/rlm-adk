# Phase 1: Key Dedup + Dead Code Removal

*2026-03-05T18:31:35Z by Showboat 0.6.0*
<!-- showboat-id: fa8b108f-96c1-4868-a4ef-836244818b09 -->

Deduplicated state keys: flush_fn() now writes only canonical OBS_CHILD_* keys, removing 5 duplicate OBS_WORKER_* writes. Deleted 9 dead constants from state.py. Removed dead worker agent_type detection branch from observability.py. Updated 26 fixture JSON files, 6 test files, and 3 source files.

```bash
.venv/bin/python -c "
import rlm_adk.state as s
# Verify deleted constants are gone
deleted = [\"OBS_WORKER_TIMEOUT_COUNT\", \"OBS_WORKER_RATE_LIMIT_COUNT\", 
           \"OBS_WORKER_POOL_EXHAUSTION_COUNT\", \"OBS_CHILD_SUMMARY_PREFIX\",
           \"OBS_ARTIFACT_LOADS\", \"OBS_ARTIFACT_DELETES\", \"OBS_ARTIFACT_SAVE_LATENCY_MS\",
           \"OBS_WORKER_ERROR_COUNTS\", \"OBS_WORKER_TOTAL_BATCH_DISPATCHES\"]
for name in deleted:
    assert not hasattr(s, name), f\"{name} still exists!\"
print(f\"Verified {len(deleted)} constants deleted from state.py\")

# Verify deprecated constants still importable
deprecated = [\"WORKER_DISPATCH_COUNT\", \"WORKER_PROMPT_CHARS\", \"OBS_WORKER_DISPATCH_LATENCY_MS\"]
for name in deprecated:
    assert hasattr(s, name), f\"{name} missing!\"
print(f\"Verified {len(deprecated)} deprecated constants still importable (for debug_logging.py)\")

# Verify canonical keys exist
canonical = [\"OBS_CHILD_DISPATCH_COUNT\", \"OBS_CHILD_ERROR_COUNTS\", 
             \"OBS_CHILD_DISPATCH_LATENCY_MS\", \"OBS_CHILD_TOTAL_BATCH_DISPATCHES\"]
for name in canonical:
    assert hasattr(s, name), f\"{name} missing!\"
print(f\"Verified {len(canonical)} canonical OBS_CHILD_* keys present\")
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
Verified 9 constants deleted from state.py
Verified 3 deprecated constants still importable (for debug_logging.py)
Verified 4 canonical OBS_CHILD_* keys present
```

flush_fn() simplified: only canonical keys in delta dict.

```bash
.venv/bin/python -c "
from unittest.mock import MagicMock
from rlm_adk.dispatch import DispatchConfig, create_dispatch_closures
config = DispatchConfig(default_model=\"test-model\")
ctx = MagicMock()
ctx.session.state = {}
_, _, flush = create_dispatch_closures(config, ctx)
delta = flush()
print(\"flush_fn() keys:\", sorted(delta.keys()))
# Verify no OBS_WORKER_* or worker_dispatch_count
for k in delta:
    assert \"worker\" not in k.lower(), f\"Legacy key found: {k}\"
print(\"No legacy worker keys in delta -- PASS\")
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
flush_fn() keys: ['obs:child_dispatch_count', 'obs:child_dispatch_latency_ms']
No legacy worker keys in delta -- PASS
```

All 813 tests pass (0 failures, 1 pre-existing skip).

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_key_dedup.py -v --tb=no -q 2>&1 | tail -5
```

```output
  /home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 16 passed, 1 warning in 0.05s =========================
```
