# BUG-014: Fix child set_model_response depth=0 telemetry

*2026-03-25T13:18:47Z by Showboat 0.6.1*
<!-- showboat-id: bfdb625b-e07e-4d9a-ab9a-daa5d9cd1934 -->

BUG-014: SqliteTracingPlugin.before_tool_callback resolved depth from tool._depth, which is only set on REPLTool instances. For ADK-internal tools like set_model_response (SetModelResponseTool), getattr(tool, "_depth", 0) always returns 0. Fix: resolve depth from agent._rlm_depth via invocation context (same pattern as before_model_callback), falling back to tool._depth for REPLTool backward compat. Same fix applied to InstrumentationPlugin.

```bash
grep -n "BUG-014" rlm_adk/plugins/sqlite_tracing.py
```

```output
1214:            # Resolve agent first (moved above depth resolution for BUG-014)
1218:            # BUG-014 fix: resolve depth from agent._rlm_depth (set by
```

```bash
grep -n "BUG-014" tests_rlm_adk/provider_fake/instrumented_runner.py
```

```output
287:            # BUG-014 fix: resolve depth from agent._rlm_depth (matches
```

The fix moves agent resolution (inv_ctx/agent getattr chain) above the depth computation, then reads agent._rlm_depth first. The _rlm_depth attribute is stamped on every child reasoning agent by its parent orchestrator at construction time, so it is always accurate. Falls back to tool._depth (set only on REPLTool) for backward compat.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py::TestSetModelResponseDepth -q -m provider_fake 2>/dev/null | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
3 passed
```

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py -q -m provider_fake 2>/dev/null | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
21 passed
```
