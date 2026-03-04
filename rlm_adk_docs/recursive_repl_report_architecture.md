# Recursive REPL Worker Report: Architecture

## Current Flow
- Root orchestration is centralized in `RLMOrchestratorAgent._run_async_impl` and always initializes `LocalREPL(depth=1)` when no external REPL is injected (`rlm_adk/orchestrator.py:99-115`).
- Orchestrator wires dispatch closures into that REPL and mounts `REPLTool` on a single `reasoning_agent` (`rlm_adk/orchestrator.py:127-170`).
- Subcalls from REPL code route into `WorkerPool` closures; workers are currently `LlmAgent` leaf workers, not orchestrators (`rlm_adk/dispatch.py:55-150`, `rlm_adk/dispatch.py:222-305`).
- Worker execution is consumed internally and suppressed from upstream event stream (`rlm_adk/dispatch.py:216-219`, `rlm_adk/dispatch.py:386-413`).

## Gaps for Orchestrator-as-Worker
- Hardcoded depth initialization prevents recursive depth awareness at runtime (`rlm_adk/orchestrator.py:114`, `rlm_adk/orchestrator.py:175`).
- Final answer extraction is fixed to global key `reasoning_output`; nested orchestrators would contend on the same key (`rlm_adk/agent.py:219`, `rlm_adk/orchestrator.py:255-275`).
- Dispatch contracts assume worker objects expose LlmAgent-specific mutable carriers (`_pending_prompt`, `_result_ready`, `_call_record`) and can be reconfigured with `output_schema/tools` for structured output (`rlm_adk/dispatch.py:368-380`, `rlm_adk/dispatch.py:433-497`).
- `create_dispatch_closures(...)` currently executes workers in the same `InvocationContext` (`rlm_adk/dispatch.py:222-227`, `rlm_adk/dispatch.py:387`, `rlm_adk/dispatch.py:412`), so recursive workers would mutate shared state unless isolated.
- Worker cleanup logic assumes `parent_agent` semantics of `ParallelAgent` and LlmAgent reuse behavior (`rlm_adk/dispatch.py:607-612`).

## Minimal Viable Design
1. Add a recursion feature gate and depth guard.
- Introduce `RLM_RECURSIVE_WORKERS` (off by default) and `RLM_RECURSIVE_MAX_DEPTH`.
- Enforce guard before child-worker dispatch and before nested orchestrator startup.

2. Make orchestrator depth-aware and output-key aware.
- Parameterize `create_reasoning_agent(..., output_key=...)` instead of fixed `reasoning_output` (`rlm_adk/agent.py:208-226`).
- Compute a scoped output key per child lineage and depth.
- Stop reading hardcoded `ctx.session.state["reasoning_output"]`; read the scoped output key.

3. Introduce a worker runtime abstraction.
- Keep existing LlmAgent worker path for non-recursive mode.
- Add a recursive worker adapter that owns an `RLMOrchestratorAgent` instance and exposes dispatcher-compatible lifecycle methods.
- Keep existing dispatch API (`llm_query_async`, `llm_query_batched_async`) stable for REPL code.

4. Isolate child execution context.
- Child workers must run with scoped state (overlay/fork) rather than writing directly into parent keyspace.
- Merge back only normalized `LLMResult` + selected metrics.

## High-Risk Changes
- Changing worker type in `WorkerPool._create_worker` from `LlmAgent` to orchestrator affects structured output wiring path (`rlm_adk/dispatch.py:373-380`) and cleanup assumptions (`rlm_adk/dispatch.py:592-612`).
- Modifying reasoning output key semantics can regress collapsed orchestrator behavior validated in `tests_rlm_adk/test_orchestrator_collapsed.py:58-70`.
- Event propagation behavior may change; current design intentionally consumes worker events (`rlm_adk/dispatch.py:216-219`).
- Recursive fan-out can amplify resource pressure and pool exhaustion pathways already tracked in tests (`tests_rlm_adk/test_adk_dispatch_worker_pool.py:211-313`, `tests_rlm_adk/test_fmea_e2e.py:1938-2023`).

## Backward Compatibility
- Default behavior must remain current leaf-worker dispatch when recursion gate is disabled.
- Keep legacy keys (`final_answer`, `iteration_count`, `last_repl_result`) emitted for root orchestrator while adding scoped variants for nested flows.
- Preserve existing `LLMResult` return semantics in REPL helper contracts.
- Preserve existing error category mappings and dispatch timeout semantics.

## Recommended Migration Steps
1. Add recursion config + depth guard + scoped output key plumbing (no behavior change when gate is off).
2. Introduce dispatcher worker runtime abstraction and keep LlmAgent runtime as default.
3. Implement recursive runtime behind gate with child-state isolation.
4. Add event/metric lineage propagation.
5. Run full regression, then enable gate in targeted integration fixtures before default rollout.
