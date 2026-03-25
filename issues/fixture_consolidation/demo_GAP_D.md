# GAP-D: Child `repo_url` Propagation + Child Static Instruction Skill Tools

## Gap Description

Two related sub-issues prevented children from having full feature parity:

1. **`repo_url` not propagated**: Children spawned via `llm_query()` /
   `llm_query_batched()` never received `repo_url`, so the ADK dynamic
   instruction template `{repo_url?}` resolved to empty for all children.
   The root cause was that `create_child_orchestrator()` did not accept a
   `repo_url` parameter, and the two functions above it in the call chain
   did not propagate it.

2. **`RLM_CHILD_STATIC_INSTRUCTION` missing skill tools**: The condensed
   child static instruction did not mention `list_skills` or `load_skill`,
   so even when children received a `SkillToolset` (via GAP-A), the model
   had no guidance on how to use those discovery tools.

## Sub-Issue 1: `repo_url` Propagation

### Before (Broken)

```
orchestrator._run_async_impl
  -> create_dispatch_closures(... NO repo_url ...)
    -> _run_child(...)
      -> create_child_orchestrator(... NO repo_url ...)
        => child.repo_url == None   # always None
        => {repo_url?} resolves to empty in child dynamic instruction
```

#### Old Signatures

```python
# rlm_adk/agent.py
def create_child_orchestrator(
    model, depth, prompt, worker_pool=None, thinking_budget=512,
    output_schema=None, fanout_idx=0, parent_fanout_idx=None,
    instruction_router=None, enabled_skills=(),
    # repo_url NOT accepted
) -> RLMOrchestratorAgent:

# rlm_adk/dispatch.py
def create_dispatch_closures(
    dispatch_config, ctx, call_log_sink=None, trace_sink=None,
    depth=0, max_depth=10, instruction_router=None, fanout_idx=0,
    child_event_queue=None, enabled_skills=(),
    # repo_url NOT accepted
) -> tuple[Any, Any, Any]:

# rlm_adk/orchestrator.py  (_run_async_impl call site)
create_dispatch_closures(
    self.worker_pool, ctx,
    ...,
    enabled_skills=self.enabled_skills,
    # repo_url NOT passed
)
```

### After (Fixed)

```
orchestrator._run_async_impl
  -> create_dispatch_closures(..., repo_url=self.repo_url)
    -> _run_child(...)
      -> create_child_orchestrator(..., repo_url=repo_url)
        => child.repo_url == "https://github.com/..."  # propagated
        => {repo_url?} resolves correctly in child dynamic instruction
```

#### New Signatures

```python
# rlm_adk/agent.py  (line 329)
def create_child_orchestrator(
    model, depth, prompt, worker_pool=None, thinking_budget=512,
    output_schema=None, fanout_idx=0, parent_fanout_idx=None,
    instruction_router=None, enabled_skills=(),
    repo_url: str | None = None,              # NEW
) -> RLMOrchestratorAgent:

# rlm_adk/dispatch.py  (line 109)
def create_dispatch_closures(
    dispatch_config, ctx, call_log_sink=None, trace_sink=None,
    depth=0, max_depth=10, instruction_router=None, fanout_idx=0,
    child_event_queue=None, enabled_skills=(),
    repo_url: str | None = None,              # NEW
) -> tuple[Any, Any, Any]:

# rlm_adk/orchestrator.py  (line 293, call site)
create_dispatch_closures(
    self.worker_pool, ctx,
    ...,
    enabled_skills=self.enabled_skills,
    repo_url=self.repo_url,                   # NEW
)
```

### Propagation Chain (4 hops)

| Hop | File | Function / Call Site | Line |
|-----|------|----------------------|------|
| 1 | `orchestrator.py` | `_run_async_impl` passes `self.repo_url` | 303 |
| 2 | `dispatch.py` | `create_dispatch_closures` captures `repo_url` in closure | 120 |
| 3 | `dispatch.py` | `_run_child` passes `repo_url` to `create_child_orchestrator` | 311 |
| 4 | `agent.py` | `create_child_orchestrator` sets `repo_url=` on child | 387 |

## Sub-Issue 2: Child Static Instruction Mentions Skill Tools

### Before (Broken)

`RLM_CHILD_STATIC_INSTRUCTION` listed only `execute_code` and
`set_model_response`. No mention of `list_skills` or `load_skill`, so the
child model had no awareness of skill discovery tools even when they were
available.

### After (Fixed)

`RLM_CHILD_STATIC_INSTRUCTION` now includes a "Skill Tools" section
(lines 140-147 of `rlm_adk/utils/prompts.py`):

```
## Skill Tools

When skills are available, you have additional tools for discovery:
- `list_skills()`: List available skills and their descriptions.
- `load_skill(name)`: Load a skill's detailed instructions and usage.

After discovering a skill, call its functions via `execute_code`. Skill
functions are pre-loaded as REPL globals -- use them directly in code.
```

This matches the same section in `RLM_STATIC_INSTRUCTION` (the root
instruction), ensuring children and root agents have consistent guidance.

## Test Coverage

**6 new tests** in `tests_rlm_adk/test_child_feature_parity.py`:

| Test Class | Test | What It Proves |
|------------|------|----------------|
| `TestCreateChildOrchestratorRepoUrl` | `test_create_child_orchestrator_propagates_repo_url` | Hop 4: `repo_url` is set on returned orchestrator |
| `TestCreateChildOrchestratorRepoUrl` | `test_create_child_orchestrator_default_repo_url_none` | Default is `None` (backward-compatible) |
| `TestDispatchPropagatesRepoUrl` | `test_dispatch_propagates_repo_url` | Hops 2-3: closure forwards `repo_url` to `create_child_orchestrator` |
| `TestOrchestratorPassesRepoUrlToDispatch` | `test_orchestrator_passes_repo_url_to_dispatch` | Hop 1: orchestrator passes `repo_url` to `create_dispatch_closures` |
| `TestChildStaticInstructionMentionsSkillTools` | `test_child_static_instruction_mentions_skill_tools` | `list_skills` and `load_skill` appear in `RLM_CHILD_STATIC_INSTRUCTION` |
| `TestDepth2InductionEnabledSkills` | `test_depth1_child_forwards_enabled_skills_to_dispatch` | Depth-2 induction: child at depth=1 re-passes skills to its own dispatch |

## Verification Commands

```bash
# Note: these tests are not marked provider_fake_contract, so override
# the default addopts filter with --override-ini="addopts=".

# Run the repo_url propagation tests (Cycles 9-11)
.venv/bin/python -m pytest tests_rlm_adk/test_child_feature_parity.py::TestCreateChildOrchestratorRepoUrl tests_rlm_adk/test_child_feature_parity.py::TestDispatchPropagatesRepoUrl tests_rlm_adk/test_child_feature_parity.py::TestOrchestratorPassesRepoUrlToDispatch -x -q --override-ini="addopts="

# Run the child static instruction test (Cycle 12)
.venv/bin/python -m pytest tests_rlm_adk/test_child_feature_parity.py::TestChildStaticInstructionMentionsSkillTools -x -q --override-ini="addopts="

# Run all GAP-D tests together
.venv/bin/python -m pytest tests_rlm_adk/test_child_feature_parity.py::TestCreateChildOrchestratorRepoUrl tests_rlm_adk/test_child_feature_parity.py::TestDispatchPropagatesRepoUrl tests_rlm_adk/test_child_feature_parity.py::TestOrchestratorPassesRepoUrlToDispatch tests_rlm_adk/test_child_feature_parity.py::TestChildStaticInstructionMentionsSkillTools -x -q --override-ini="addopts="

# Quick smoke test: verify the string literals exist
.venv/bin/python -c "from rlm_adk.utils.prompts import RLM_CHILD_STATIC_INSTRUCTION; assert 'list_skills' in RLM_CHILD_STATIC_INSTRUCTION and 'load_skill' in RLM_CHILD_STATIC_INSTRUCTION; print('OK: child instruction mentions skill tools')"
```

## Verification Checklist

- [ ] `create_child_orchestrator` accepts `repo_url` kwarg (agent.py:340)
- [ ] `create_dispatch_closures` accepts `repo_url` kwarg (dispatch.py:120)
- [ ] `_run_child` passes `repo_url` to `create_child_orchestrator` (dispatch.py:311)
- [ ] `_run_async_impl` passes `self.repo_url` to `create_dispatch_closures` (orchestrator.py:303)
- [ ] Default value for `repo_url` is `None` everywhere (backward-compatible)
- [ ] `RLM_CHILD_STATIC_INSTRUCTION` contains `list_skills` (prompts.py:143)
- [ ] `RLM_CHILD_STATIC_INSTRUCTION` contains `load_skill` (prompts.py:144)
- [ ] Child skill tools section matches root instruction's skill tools section
- [ ] `test_child_feature_parity.py` -- all GAP-D tests pass
- [ ] Smoke test: `RLM_CHILD_STATIC_INSTRUCTION` string check passes
