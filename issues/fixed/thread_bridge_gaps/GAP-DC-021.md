# GAP-DC-021: collect_skill_repl_globals passes None repl_globals in orchestrator edge case
**Severity**: LOW
**Category**: unwired
**Files**: `rlm_adk/orchestrator.py` (line 270-273), `rlm_adk/skills/loader.py` (line 128-146)

## Problem

In `orchestrator.py`, `collect_skill_repl_globals()` is called with `repl_globals=repl.globals`:

```python
_skill_globals = collect_skill_repl_globals(
    enabled_skills=self.enabled_skills or None,
    repl_globals=repl.globals,
)
repl.globals.update(_skill_globals)
```

This is correctly wired. The `_wrap_with_llm_query_injection` wrapper reads `llm_query` from `repl_globals` lazily, and since `repl_globals` IS `repl.globals` (same dict object), the lazy read will find `llm_query` after `repl.set_llm_query_fns()` is called later.

However, `collect_skill_repl_globals()` also accepts `repl_globals=None` as a default, in which case it creates a fresh dict that is never connected to any REPL. If a future caller forgets to pass `repl_globals`, wrapped functions will always raise `RuntimeError("llm_query not available")` at call time.

## Evidence

```python
# loader.py:128-147
def collect_skill_repl_globals(
    enabled_skills=None,
    repl_globals=None,
) -> dict[str, Any]:
    if repl_globals is None:
        repl_globals = {}  # Creates orphan dict
```

The `repl_globals=None` default is used in tests (`test_skill_loader.py:185` calls `loader.collect_skill_repl_globals()` without args). This is fine for testing discovery logic but would fail at call time if the wrapped functions tried to use `llm_query_fn`.

## Suggested Fix

No action needed for correctness (the orchestrator passes the right dict). Consider adding a log warning when `repl_globals is None` to help future debugging:

```python
if repl_globals is None:
    repl_globals = {}
    log.debug("collect_skill_repl_globals called without repl_globals; "
              "wrapped functions will fail unless llm_query is manually injected")
```
