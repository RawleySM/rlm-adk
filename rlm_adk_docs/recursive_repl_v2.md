# Recursive Worker Orchestrator v2 (Direct Cutover Spec)

## 1) Validated Constraints and Design Drivers
Validated against current code:
- Worker execution is leaf-`LlmAgent`-specific and callback-carrier-driven (`rlm_adk/dispatch.py:103-146`, `rlm_adk/dispatch.py:368-497`, `rlm_adk/callbacks/worker.py:52-181`).
- Child worker runs currently share parent invocation context (`rlm_adk/dispatch.py:386-413`).
- Fixed `reasoning_output` and flat state keys are collision-prone under nested workers (`rlm_adk/agent.py:219`, `rlm_adk/orchestrator.py:255-275`, `rlm_adk/tools/repl_tool.py:81-84`, `rlm_adk/tools/repl_tool.py:130-185`).
- Observability/tracing is currently flat and prefix-scan based in places (`rlm_adk/plugins/observability.py:106-127`, `rlm_adk/plugins/observability.py:152-233`, `rlm_adk/plugins/repl_tracing.py:31-45`).
- Sync REPL timeout and teardown behavior has known thread/cancel risk (`rlm_adk/repl/local_repl.py:77-81`, `rlm_adk/repl/local_repl.py:324-339`, `rlm_adk/dispatch.py:386-430`, `rlm_adk/dispatch.py:592-612`).

Required outcomes in this spec:
- Explicit child invocation-context isolation and write discipline.
- Explicit model-routing behavior for `model=` override in `llm_query*`.
- Explicit structured-output behavior decision for the initial cutover phase and follow-up phase.
- Expanded scoped-key matrix including reasoning callback accounting keys.
- Hard concurrency, cancel-drain, and quarantine requirements.
- Child summary event envelope and rollup invariants for observability/tracing.
- Concrete RED/GREEN phases with acceptance criteria.

## 2) Updated Architecture Plan (Worker=Orchestrator; REPL Optional)
Cutover decision:
- `WorkerPool` creates child `RLMOrchestratorAgent` runtimes for subcalls.
- Leaf callback-carrier path is removed from the primary subcall path.

Execution model per subcall:
1. Parent allocates child scope (`depth`, `lineage_id`, `worker_call_id`).
2. Parent instantiates child orchestrator with scoped output key.
3. Child runs as full orchestrator and may or may not call `execute_code`.
4. Parent maps child terminal output to `LLMResult` and merges child telemetry.

Model routing rule:
- `llm_query*(..., model=...)` must route that model into child orchestrator reasoning agent creation (no silent fallback to parent model).

Primary runtime interface in dispatch:
- `start(prompt, child_context, scope)`
- `await completion`
- `result() -> LLMResult`
- `teardown(status)`

Relevant files:
- `rlm_adk/dispatch.py`
- `rlm_adk/orchestrator.py`
- `rlm_adk/agent.py`
- `rlm_adk/tools/repl_tool.py`

## 3) State Authority Model + Scoped Key Matrix
Scope identity:
- `scope_id = d{depth}#{lineage_id}`
- `scoped_key(base, scope_id) = "{base}@{scope_id}"`

Authority model:
- Scoped keys are authoritative for child reads/writes.
- Unsuffixed keys are root-only aliases and never authoritative for child scope.
- Child unsuffixed writes to guarded keys are invalid and must fail.

Root-immutable keys:
- `request_id` (set once; child overwrite is forbidden)
- invocation-level start timestamps

Scoped-key matrix (mandatory in child scope):
- Core loop keys:
  - `iteration_count`
  - `last_repl_result`
  - `final_answer`
  - `should_stop`
  - `reasoning_output`
  - `message_history`
- Worker output artifacts:
  - keys currently derived from `worker_<n>_output`
- Worker dispatch counters:
  - `worker_dispatch_count`
  - `obs:worker_dispatch_latency_ms`
  - `obs:worker_total_dispatches`
  - `obs:worker_total_batch_dispatches`
  - `obs:worker_timeout_count`
  - `obs:worker_rate_limit_count`
  - `obs:worker_error_counts`
  - `obs:worker_pool_exhaustion_count`
  - `obs:structured_output_failures`
- Reasoning callback accounting:
  - `REASONING_PROMPT_CHARS`
  - `REASONING_SYSTEM_CHARS`
  - `REASONING_CONTENT_COUNT`
  - `REASONING_HISTORY_MSG_COUNT`
  - `REASONING_INPUT_TOKENS`
  - `REASONING_OUTPUT_TOKENS`
  - `CONTEXT_WINDOW_SNAPSHOT`
- Observability per-call breakdown:
  - `OBS_PER_ITERATION_TOKEN_BREAKDOWN`

Required `state.py` additions:
- `ORCHESTRATOR_DEPTH`
- `ORCHESTRATOR_LINEAGE_ID`
- `ORCHESTRATOR_RUN_ID`
- `ORCHESTRATOR_PARENT_RUN_ID`
- `ACTIVE_SCOPE_ID`
- `ROOT_REQUEST_ID`
- `scope_id(depth, lineage_id)`
- `scoped_key(base, scope_id)`
- child raw-key write guard utility

## 4) Context/Write Discipline for Child Invocation Execution
Child context strategy:
- Child runs with a scoped state overlay, not direct shared writes into parent flat state.
- Parent provides immutable root identity and child scope metadata.
- Child writes only scoped keys during execution.
- Parent merges back only approved outputs:
  - terminal answer payload
  - scoped telemetry payload
  - scoped trace summary payload

Write guard rules:
1. Guarded raw key writes in child scope throw runtime error.
2. Child cannot mutate root-only keys (`request_id`).
3. Parent merge rejects unknown child keys outside approved scoped namespaces.

`output_key` discipline:
- Child reasoning agent receives scoped `output_key`.
- Orchestrator terminal extraction reads scoped key only.

## 5) Structured-Output Behavior Decision for v1 + Follow-Up
Current reality:
- Worker `output_schema` behavior in leaf mode depends on `SetModelResponseTool` + retry callbacks (`rlm_adk/dispatch.py:373-380`, `rlm_adk/callbacks/worker_retry.py:40-158`).

v1 cutover decision:
- `llm_query*(..., output_schema=...)` is explicitly rejected in orchestrator-worker path.
- Dispatch returns a clear unsupported error category for this argument path.

v2 follow-up phase:
- Reintroduce structured output through child-orchestrator-native contract:
  - schema attached to child reasoning model config
  - scoped structured-result capture
  - scoped retry accounting

## 6) Timing/Threading/Cancellation Hard Requirements
Hard requirements:
1. Global recursive concurrency budget:
   - max in-flight child runtimes per invocation (strict semaphore).
2. Depth and fanout budgets:
   - max recursion depth
   - max children per batch
   - max child calls per parent iteration
3. Timeout handling:
   - timeout -> cancel -> bounded drain wait -> teardown
   - if drain fails, runtime is quarantined and dropped
4. Reuse policy:
   - any timeout/cancel-error runtime is non-reusable
5. Event-loop safety:
   - recursive mode cannot block event loop on sync REPL path
   - blocking sync tool work must run via thread-offloaded await
6. REPL mutable state safety:
   - per-REPL async critical section lock around mutable globals/stdout path
7. Accumulator isolation:
   - dispatch accumulators tracked per-lineage, not closure-shared global buckets

Code hotspots:
- `rlm_adk/repl/local_repl.py`
- `rlm_adk/tools/repl_tool.py`
- `rlm_adk/dispatch.py`

## 7) Observability + Tracing Migration Sequence
Required lineage fields on child telemetry:
- `obs:lineage_id`
- `obs:depth`
- `obs:worker_call_id`
- `obs:parent_request_id`
- `obs:agent_role` (`root_orchestrator`, `recursive_worker`)

Child summary event envelope (v1):
- `type: "sub_agent_event"`
- `lineage_id`
- `depth`
- `worker_call_id`
- `phase` (`start`, `complete`, `timeout`, `error`)
- `payload` (bounded summary fields)

Rollup invariants:
1. Aggregate totals = root-local totals + sum(child lineage totals).
2. Rollup is computed exactly once from lineage buckets.
3. No prefix-based blind rescan allowed for child attribution.

Migration sequence:
1. `observability.py`: lineage buckets + deterministic rollup pass.
2. `observability.py`: remove dynamic-prefix cross-scope bleed path in `after_agent_callback`.
3. `repl_tracing.py`: ingest scoped `last_repl_result` and index by `{lineage}:{iteration}`.
4. `dispatch.py`: emit `sub_agent_event` summary envelopes with lineage metadata.

## 8) Red/Green TDD Plan with Concrete Tests and Acceptance Criteria
### Phase A (RED): Runtime Cutover Contracts
Add failing tests:
- `tests_rlm_adk/test_recursive_worker_is_orchestrator.py`
- `tests_rlm_adk/test_recursive_worker_repl_optional.py`
- `tests_rlm_adk/test_recursive_worker_model_routing.py`
- `tests_rlm_adk/test_recursive_worker_schema_rejected_v1.py`

Acceptance criteria:
- Worker runtime is orchestrator-based.
- Child completes both with and without REPL call.
- `model=` override is honored.
- `output_schema` path is explicitly rejected in v1.

### Phase B (GREEN): Core Runtime Implementation
Implement:
- orchestrator-worker runtime in `dispatch.py`
- scoped child output key in `agent.py` + `orchestrator.py`
- child context overlay + merge boundary

Acceptance criteria:
- normalized `LLMResult` parity
- no leaf-carrier dependency in primary path

### Phase C (RED): State Authority and Guards
Add failing tests:
- `tests_rlm_adk/test_recursive_state_scoping.py`
- `tests_rlm_adk/test_recursive_request_id_immutable.py`
- `tests_rlm_adk/test_recursive_raw_key_write_guard.py`
- `tests_rlm_adk/test_recursive_reasoning_key_scoping.py`

Acceptance criteria:
- no parent/child key collisions
- child unsuffixed guarded writes fail deterministically

### Phase D (GREEN): State Guard Implementation
Implement:
- scoped key API in `state.py`
- child write guards
- REPL tool and callbacks route through scope resolver

Acceptance criteria:
- scoped keys are authoritative for child reads/writes

### Phase E (RED): Timing/Cancellation Hardening
Add failing tests:
- `tests_rlm_adk/test_recursive_timeout_quarantine.py`
- `tests_rlm_adk/test_recursive_cancel_drain.py`
- `tests_rlm_adk/test_recursive_no_stale_write_after_timeout.py`
- `tests_rlm_adk/test_recursive_fanout_budget_limits.py`
- `tests_rlm_adk/test_recursive_event_loop_non_blocking.py`

Acceptance criteria:
- runtime quarantine and drain policy enforced
- concurrency budget hard-capped

### Phase F (GREEN): Timing/Cancellation Implementation
Implement:
- semaphore budgets
- cancel-drain-teardown path
- quarantine-on-failure
- non-blocking sync execution offload

Acceptance criteria:
- no stale runtime reuse after timeout/cancel

### Phase G (RED): Observability/Tracing
Add failing tests:
- `tests_rlm_adk/test_recursive_observability_lineage.py`
- `tests_rlm_adk/test_recursive_rollup_consistency.py`
- `tests_rlm_adk/test_recursive_trace_scope_retention.py`
- `tests_rlm_adk/test_recursive_sub_agent_event_envelope.py`
- `tests_rlm_adk/test_recursive_after_agent_no_prefix_bleed.py`

Acceptance criteria:
- lineage metrics isolated
- aggregate rollup invariant holds
- scoped trace retention works

### Phase H (GREEN): Observability/Tracing Implementation
Implement lineage buckets, rollup pass, scoped trace indexing, and summary envelope emission.

Acceptance criteria:
- deterministic lineage observability and trace indexing under nested fanout.

## 9) Implementation Phases with Clear Done Criteria
### Phase 1: Worker Runtime Cutover
Done when:
- dispatch primary path runs child orchestrators only
- REPL optional behavior validated by tests

### Phase 2: State Authority + Context Isolation
Done when:
- scoped key matrix enforced
- root `request_id` immutability enforced
- child raw-key write guards active

### Phase 3: Structured Output v1 Finalization
Done when:
- `output_schema` rejection behavior is explicit and tested for worker path

### Phase 4: Timing/Cancellation Hardening
Done when:
- semaphore budgets active
- timeout/cancel drain and quarantine path verified
- no event-loop blocking in recursive mode

### Phase 5: Observability/Tracing Migration
Done when:
- lineage buckets and rollup invariants are test-verified
- scoped trace persistence and envelope emission are test-verified

### Phase 6: End-to-End Validation
Done when:
- full recursive suite passes
- nested fanout run demonstrates deterministic state, telemetry, and teardown behavior
- cutover acceptance criteria from all previous phases are green together.

## 10) P0/P1 Risk Register and Release Gates

| Risk | Priority (P0/P1) | Failure Mode | Gate Type (Pass/Fail) | Required Test File(s) | Gate Rule |
| --- | --- | --- | --- | --- | --- |
| State collisions across scopes | P0 | Child overwrites parent `iteration_count`, `reasoning_output`, `last_repl_result`, or `request_id` lineage semantics | Pass/Fail | `tests_rlm_adk/test_recursive_state_scoping.py`, `tests_rlm_adk/test_recursive_request_id_immutable.py`, `tests_rlm_adk/test_recursive_reasoning_key_scoping.py` | PASS only if all tests pass and no unsuffixed guarded-key write from child scope succeeds. Any overwrite is FAIL. |
| Recursion/fanout runaway | P0 | Unbounded nested dispatch exceeds configured depth/fanout/in-flight budgets | Pass/Fail | `tests_rlm_adk/test_recursive_depth_budget_limits.py`, `tests_rlm_adk/test_recursive_fanout_budget_limits.py`, `tests_rlm_adk/test_recursive_inflight_budget_limits.py` | PASS only if all three controls are independently enforced: depth cap, per-batch fanout cap, and in-flight semaphore cap, each with deterministic failure when exceeded. |
| Timeout/cancel stale runtime reuse | P0 | Timed-out child runtime is released and reused; stale writes appear after timeout/cancel | Pass/Fail | `tests_rlm_adk/test_recursive_timeout_quarantine.py`, `tests_rlm_adk/test_recursive_cancel_drain.py`, `tests_rlm_adk/test_recursive_no_stale_write_after_timeout.py` | PASS only if timeout/cancel path quarantines runtime and no post-timeout write mutates active scope. |
| Structured output behavior regression | P1 | `output_schema` path silently degrades or behaves inconsistently in orchestrator-worker v1 | Pass/Fail | `tests_rlm_adk/test_recursive_worker_schema_rejected_v1.py` | PASS only if `output_schema` is rejected with explicit unsupported error category in worker path. Any silent accept/fallback is FAIL. |
| Observability lineage corruption / double counting | P0 | Child metrics bleed across lineages or aggregate rollup is inconsistent | Pass/Fail | `tests_rlm_adk/test_recursive_observability_lineage.py`, `tests_rlm_adk/test_recursive_rollup_consistency.py`, `tests_rlm_adk/test_recursive_after_agent_no_prefix_bleed.py` | PASS only if lineage buckets are isolated and aggregate totals equal deterministic rollup from lineage buckets. |
| Model routing drift | P0 | `model=` override ignored or silently routed to parent/default model | Pass/Fail | `tests_rlm_adk/test_recursive_worker_model_routing.py` | PASS only if explicit `model=` override is honored for child reasoning model selection on every subcall path. |
| Event loop blocking | P0 | Recursive mode blocks loop via sync REPL path and degrades concurrent dispatch | Pass/Fail | `tests_rlm_adk/test_recursive_event_loop_non_blocking.py` | PASS only if recursive subcall execution keeps loop responsive under concurrent load test. |

### Release Decision Rule

- P0 rule: any P0 gate failure is an absolute release blocker. No exceptions.
- P1 rule: all in-scope P1 gates must pass before production release.
- P1 waiver rule (non-production only): waiver record must include owner, approver, expiry date, mitigation plan, rollback trigger, and storage path in `rlm_adk_docs/waivers/`.
- Scope rule: security-hardening gates are explicitly out of scope for this phase and are not included in current release gating.
