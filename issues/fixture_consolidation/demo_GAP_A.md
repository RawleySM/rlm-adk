# GAP-A: Child Orchestrators Now Receive `enabled_skills`

## Gap Description

Children spawned via `llm_query()` / `llm_query_batched()` never received
`enabled_skills`, so they could never get a `SkillToolset` (the ADK toolset
that exposes `list_skills` / `load_skill` to the reasoning agent).  The root
cause was that `create_child_orchestrator()` did not accept an
`enabled_skills` parameter, and the two functions above it in the call chain
did not propagate it.

## Before (Broken)

The propagation chain had no `enabled_skills` plumbing:

```
orchestrator._run_async_impl
  -> create_dispatch_closures(... NO enabled_skills ...)
    -> _run_child(...)
      -> create_child_orchestrator(... NO enabled_skills ...)
        => child.enabled_skills == ()   # always empty
        => SkillToolset never added to child tools
```

### Old Signatures

```python
# rlm_adk/agent.py
def create_child_orchestrator(
    model, depth, prompt, worker_pool=None, thinking_budget=512,
    output_schema=None, fanout_idx=0, parent_fanout_idx=None,
    instruction_router=None,
    # enabled_skills NOT accepted
) -> RLMOrchestratorAgent:

# rlm_adk/dispatch.py
def create_dispatch_closures(
    dispatch_config, ctx, call_log_sink=None, trace_sink=None,
    depth=0, max_depth=10, instruction_router=None, fanout_idx=0,
    child_event_queue=None,
    # enabled_skills NOT accepted
) -> tuple[Any, Any, Any]:

# rlm_adk/orchestrator.py  (_run_async_impl call site)
create_dispatch_closures(
    self.worker_pool, ctx,
    call_log_sink=..., trace_sink=..., depth=self.depth,
    instruction_router=self.instruction_router,
    fanout_idx=self.fanout_idx,
    child_event_queue=...,
    # enabled_skills NOT passed
)
```

## After (Fixed)

All three functions now accept and propagate `enabled_skills`:

```
orchestrator._run_async_impl
  -> create_dispatch_closures(..., enabled_skills=self.enabled_skills)
    -> _run_child(...)
      -> create_child_orchestrator(..., enabled_skills=enabled_skills)
        => child.enabled_skills == ("recursive_ping",)  # propagated
        => SkillToolset added when enabled_skills is non-empty
```

### New Signatures

```python
# rlm_adk/agent.py  (line 329)
def create_child_orchestrator(
    model, depth, prompt, worker_pool=None, thinking_budget=512,
    output_schema=None, fanout_idx=0, parent_fanout_idx=None,
    instruction_router=None,
    enabled_skills: tuple[str, ...] = (),          # NEW
) -> RLMOrchestratorAgent:

# rlm_adk/dispatch.py  (line 109)
def create_dispatch_closures(
    dispatch_config, ctx, call_log_sink=None, trace_sink=None,
    depth=0, max_depth=10, instruction_router=None, fanout_idx=0,
    child_event_queue=None,
    enabled_skills: tuple[str, ...] = (),          # NEW
) -> tuple[Any, Any, Any]:

# rlm_adk/orchestrator.py  (line 293, call site)
create_dispatch_closures(
    self.worker_pool, ctx,
    ...,
    enabled_skills=self.enabled_skills,            # NEW
)
```

## Propagation Chain (4 hops)

| Hop | File | Function / Call Site | Line |
|-----|------|----------------------|------|
| 1 | `orchestrator.py` | `_run_async_impl` passes `self.enabled_skills` | 302 |
| 2 | `dispatch.py` | `create_dispatch_closures` captures `enabled_skills` in closure | 119 |
| 3 | `dispatch.py` | `_run_child` passes `enabled_skills` to `create_child_orchestrator` | 309 |
| 4 | `agent.py` | `create_child_orchestrator` sets `enabled_skills=` on child | 384 |

## Test Coverage

**4 new tests** in `tests_rlm_adk/test_child_feature_parity.py`:

| Test | What It Proves |
|------|----------------|
| `test_create_child_orchestrator_accepts_enabled_skills` | Hop 4: field is set on returned orchestrator |
| `test_create_child_orchestrator_default_enabled_skills_empty` | Default is `()` (backward-compatible) |
| `test_dispatch_propagates_enabled_skills` | Hops 2-3: closure forwards to `create_child_orchestrator` |
| `test_orchestrator_passes_enabled_skills_to_dispatch` | Hop 1: orchestrator passes to `create_dispatch_closures` |

**3 new tests** in `tests_rlm_adk/test_skill_toolset_integration.py` (class `TestChildSkillPropagation`):

| Test | What It Proves |
|------|----------------|
| `test_children_get_repl_globals_unconditionally` | Skill functions in REPL even without `enabled_skills` |
| `test_children_without_enabled_skills_do_not_get_skilltoolset` | No `SkillToolset` when `enabled_skills=()` |
| `test_children_with_enabled_skills_get_skilltoolset` | `SkillToolset` present when `enabled_skills=("recursive_ping",)` |

## Verification Commands

```bash
# Run the 4 child-feature-parity tests (GAP-A core)
.venv/bin/python -m pytest tests_rlm_adk/test_child_feature_parity.py -x -q

# Run the 3 child-propagation tests in skill_toolset_integration
.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestChildSkillPropagation -x -q

# Run all 7 GAP-A tests together
.venv/bin/python -m pytest tests_rlm_adk/test_child_feature_parity.py tests_rlm_adk/test_skill_toolset_integration.py::TestChildSkillPropagation -x -q
```

## Verification Checklist

- [ ] `create_child_orchestrator` accepts `enabled_skills` kwarg (agent.py:339)
- [ ] `create_dispatch_closures` accepts `enabled_skills` kwarg (dispatch.py:119)
- [ ] `_run_child` passes `enabled_skills` to `create_child_orchestrator` (dispatch.py:309)
- [ ] `_run_async_impl` passes `self.enabled_skills` to `create_dispatch_closures` (orchestrator.py:302)
- [ ] Default value is `()` everywhere (backward-compatible, no breakage)
- [ ] `test_child_feature_parity.py` -- 4 tests pass
- [ ] `TestChildSkillPropagation` -- 3 tests pass
- [ ] Children with `enabled_skills` get `SkillToolset` in their tools list
- [ ] Children without `enabled_skills` do NOT get `SkillToolset`
