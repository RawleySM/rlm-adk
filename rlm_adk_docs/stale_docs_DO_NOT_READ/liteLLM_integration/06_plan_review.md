<!-- reviewed: 2026-03-09 -->
<!-- reviewer: Claude Code (claude-sonnet-4-6) -->
<!-- sources verified: agent.py, dispatch.py, orchestrator.py, callbacks/worker.py,
     .venv/.../google/adk/models/lite_llm.py, .venv/.../google/adk/models/base_llm.py -->

# Plan Review: LiteLLM Integration (05_implementation_plan.md)

## Verdict: APPROVED WITH CHANGES

The plan is architecturally sound. The `llm_client` injection strategy is confirmed correct
against the actual ADK source. All Critical and Medium issues must be resolved before implementation.

---

## Critical Issues

### CRIT-1: `_resolve_model` will double-wrap `LiteLlm` on recursive dispatch
**Phases 2, 4** | In Phase 4, `dispatch_config.other_model` is already a `LiteLlm` object. `_run_child` passes it to `create_child_orchestrator` → `create_reasoning_agent` → `_resolve_model`, which calls `create_litellm_model(LiteLlm_object)` → `LiteLlm(model=LiteLlm_object)`. ADK expects `model: str`.

**Fix:** Add `isinstance` guard:
```python
def _resolve_model(model_str, tier=None):
    if not _is_litellm_active(): return model_str
    if not isinstance(model_str, str): return model_str  # Already LiteLlm
    ...
```

### CRIT-2: Singleton `_get_or_create_client` not concurrency-safe under `asyncio.gather`
**Phase 1** | Multiple `_run_child` coroutines can simultaneously see `_cached_client is None` and create duplicate Router instances with split cooldown/usage state.

**Fix:** Use `threading.Lock` with double-checked locking.

### CRIT-3: `RLM_LITELLM_*` env vars advertised but never consumed
**Phases 1, 4** | `RLM_LITELLM_WORKER_TIER`, `RLM_LITELLM_ROUTING_STRATEGY`, `RLM_LITELLM_COOLDOWN_TIME`, `RLM_LITELLM_NUM_RETRIES`, `RLM_LITELLM_TIMEOUT` are in the env var table but nowhere in the code.

**Fix:** Read env vars in `_get_or_create_client` and Phase 4 worker wiring.

### CRIT-4: Empty model list produces silent fail-on-first-call
**Phase 1** | `litellm.Router(model_list=[])` succeeds at construction but fails cryptically at first `acompletion()`.

**Fix:** Guard in `_get_or_create_client`: `if not model_list: raise RuntimeError(...)`.

---

## Medium Issues

### MED-1: litellm exception constructor signatures must be verified
**Phase 3** | LiteLLM exception constructors change between versions. Tests may fail at construction.

**Fix:** Inspect installed version before writing tests, or use `MagicMock(spec=..., status_code=429)`.

### MED-2: Cost tracking plugin covers only root reasoning agent
**Phase 5** | Plugin callbacks don't fire for child orchestrators (isolated invocation contexts). `obs:litellm_total_cost` tracks ~10% of actual costs.

**Fix:** Document limitation. Consider Router-level `litellm.success_callback` for global tracking.

### MED-3: `obs:child_dispatch_count` assertion will fail in live test
**Phase 6** | `flush_fn` resets `_acc_child_dispatches` per REPL iteration. Final state reflects last iteration only.

**Fix:** Assert on `obs:child_dispatch_latency_ms` list length, or ensure single REPL iteration.

### MED-4: Phase 2 factory tests instantiate a real litellm.Router
**Phase 2** | Unit tests should not have litellm side-effects. Singleton cache causes test-ordering dependencies.

**Fix:** `monkeypatch.setattr("rlm_adk.agent.create_litellm_model", lambda *a, **kw: MagicMock())`.

---

## Minor Issues

### MIN-1: `llm_client` injection description technically inaccurate
Pydantic assigns via standard field assignment, not a pop. The pop at line 1835 removes it from `_additional_args`. No code change needed.

### MIN-2: Add `ADK_SUPPRESS_GEMINI_LITELLM_WARNINGS` to env var table and demo

### MIN-3: Consider `litellm` as optional extras dependency
```toml
[project.optional-dependencies]
litellm = ["litellm>=1.50.0"]
```

### MIN-4: Timeout unit mismatch
`RLM_REASONING_HTTP_TIMEOUT` (milliseconds) vs `RLM_LITELLM_TIMEOUT` (seconds). Document clearly.

### MIN-5: `RLM_TEST_LITELLM_MODEL` default value is invalid for Router architecture
Remove or fix. Live tests should use `RLM_ADK_LITELLM=1` + `create_rlm_runner(model="reasoning")`.

---

## Positive Findings (confirmed correct)

1. **`llm_client` injection works.** `generate_content_async` calls `self.llm_client.acompletion()`. All streaming, tool call conversion, and usage metadata conversion is reused.
2. **AR-CRIT-001 compliance maintained.** All state writes use valid contexts.
3. **Line number references are accurate.** All verified against source.
4. **Error handling phases correctly ordered.** Phase 3 before Phase 4 in dependency graph.
5. **Feature flag is truly zero-impact when off.** No new branches in hot paths.
6. **Provider-fake tests correctly scoped to Gemini only.**

---

## Required Changes Summary

| ID | Phase | Severity | Change |
|----|-------|----------|--------|
| CRIT-1 | 2, 4 | Critical | `isinstance(model_str, str)` guard in `_resolve_model` |
| CRIT-2 | 1 | Critical | `threading.Lock` double-checked locking for singleton |
| CRIT-3 | 1, 4 | Critical | Read `RLM_LITELLM_*` env vars in code |
| CRIT-4 | 1 | Critical | Raise on empty model list |
| MED-1 | 3 | Medium | Verify litellm exception constructors |
| MED-2 | 5 | Medium | Document cost tracking gap |
| MED-3 | 6 | Medium | Fix dispatch count assertion |
| MED-4 | 2 | Medium | Mock `create_litellm_model` in factory tests |
