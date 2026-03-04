# Phase 3: Recursive Child Dispatch

*2026-03-04T18:53:32Z by Showboat 0.6.0*
<!-- showboat-id: d026b8d9-f8c5-4778-b9e0-dd1e8da3d8de -->

Phase 3 replaces leaf LlmAgent workers with child RLMOrchestratorAgent instances. WorkerPool is replaced by DispatchConfig (a simple model config holder). Each sub-query now spawns a full child orchestrator with its own REPL + SetModelResponseTool, enabling recursive code-execution at every nesting level.

```bash
grep -n "class DispatchConfig" -A 8 rlm_adk/dispatch.py
```

```output
48:class DispatchConfig:
49-    """Holds model configuration for child dispatch (replaces WorkerPool)."""
50-
51-    def __init__(
52-        self,
53-        default_model: str,
54-        other_model: str | None = None,
55-        pool_size: int = 5,
56-    ):
```

```bash
grep -n "async def _run_child" -A 6 rlm_adk/dispatch.py
```

```output
107:    async def _run_child(
108-        prompt: str,
109-        model: str | None,
110-        output_schema: type[BaseModel] | None,
111-        fanout_idx: int,
112-    ) -> LLMResult:
113-        """Spawn a child orchestrator for a single sub-query."""
```

Depth limit enforcement prevents infinite recursion. An asyncio.Semaphore (configurable via RLM_MAX_CONCURRENT_CHILDREN, default 3) throttles concurrent child orchestrators. When depth + 1 >= max_depth, dispatch returns a DEPTH_LIMIT error instead of spawning.

```bash
grep -n "depth + 1 >= max_depth" -B 1 -A 5 rlm_adk/dispatch.py
```

```output
113-        """Spawn a child orchestrator for a single sub-query."""
114:        if depth + 1 >= max_depth:
115-            return LLMResult(
116-                f"[DEPTH_LIMIT] Cannot dispatch at depth {depth + 1} (max_depth={max_depth})",
117-                error=True,
118-                error_category="DEPTH_LIMIT",
119-            )
```

```bash
grep -n "OBS_CHILD" rlm_adk/state.py
```

```output
90:OBS_CHILD_DISPATCH_COUNT = "obs:child_dispatch_count"
91:OBS_CHILD_SUMMARY_PREFIX = "obs:child_summary@"
92:OBS_CHILD_ERROR_COUNTS = "obs:child_error_counts"
93:OBS_CHILD_DISPATCH_LATENCY_MS = "obs:child_dispatch_latency_ms"
94:OBS_CHILD_TOTAL_BATCH_DISPATCHES = "obs:child_total_batch_dispatches"
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_phase3_recursive_dispatch.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
18 passed
```

All 18 Phase 3 tests pass. Recursive dispatch is working: child orchestrators spawn with REPL + SetModelResponseTool, depth limits are enforced, semaphore concurrency control is active, and new obs keys track child dispatch metrics. Old worker-pool tests are expected to fail and will be addressed in Phase 3.5 (fixture migration).
