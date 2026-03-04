# Recursive Worker REPL: State-Key Collisions and Isolation

## Existing State Model
Current runtime state is a flat session dictionary with mostly unsuffixed keys.

- Depth-scoping primitives exist but are not wired into the main runtime path: `DEPTH_SCOPED_KEYS` and `depth_key()` (`rlm_adk/state.py:117-134`).
- Orchestrator startup writes unsuffixed `current_depth`, `iteration_count`, and `request_id` (`rlm_adk/orchestrator.py:174-178`).
- REPL tool increments unsuffixed `iteration_count` and writes unsuffixed `last_repl_result` on success/error/cancel (`rlm_adk/tools/repl_tool.py:83`, `rlm_adk/tools/repl_tool.py:130`, `rlm_adk/tools/repl_tool.py:154`, `rlm_adk/tools/repl_tool.py:185`).
- Worker dispatch metrics are flushed as unsuffixed keys (`worker_dispatch_count`, `obs:*worker*`) (`rlm_adk/dispatch.py:633-652`) and copied directly into tool state (`rlm_adk/tools/repl_tool.py:171-174`).
- Worker agent outputs are persisted by `output_key` in callback state (`rlm_adk/callbacks/worker.py:134-137`), where key names come from `worker_<n>_output` (`rlm_adk/dispatch.py:113-125`).
- Reasoning callback writes prompt/context accounting in unsuffixed keys used later by observability (`rlm_adk/callbacks/reasoning.py:81`, `rlm_adk/callbacks/reasoning.py:112-117`).
- Observability plugin accumulates totals in unsuffixed global counters and uses unsuffixed `iteration_count` for per-call breakdown entries (`rlm_adk/plugins/observability.py:163-176`, `rlm_adk/plugins/observability.py:203-233`).
- Architecture docs and compressed repomix flow confirm this single-namespace behavior (`rlm_adk_docs/architecture_summary.md:71-75`, `repomix-architecture-flow-compressed.xml:570`, `repomix-architecture-flow-compressed.xml:717`).

## Collision Surfaces
### 1) `REQUEST_ID`
- `request_id` is rewritten by orchestrator start (`rlm_adk/orchestrator.py:177`) even though observability uses it as the run correlation token in multiple callbacks (`rlm_adk/plugins/observability.py:70`, `rlm_adk/plugins/observability.py:130`, `rlm_adk/plugins/observability.py:235`, `rlm_adk/plugins/observability.py:307`).
- Under nested orchestrators, child writes can sever parent log correlation and overwrite parent identity mid-run.

### 2) `ITERATION_COUNT`
- Seeded to `0` by orchestrator (`rlm_adk/orchestrator.py:176`) and then overwritten by REPL tool call count (`rlm_adk/tools/repl_tool.py:81-84`).
- Observability reads this value as if it were the current iteration context (`rlm_adk/plugins/observability.py:203-208`).
- Nested or sibling recursive workers can race/overwrite iteration values, producing incorrect per-iteration attribution.

### 3) `LAST_REPL_RESULT`
- Always written to a single unsuffixed key (`rlm_adk/tools/repl_tool.py:130`, `rlm_adk/tools/repl_tool.py:154`, `rlm_adk/tools/repl_tool.py:185`).
- Trace consumers read this key together with `iteration_count` from event deltas (`repomix-architecture-flow-compressed.xml:86`, `repomix-architecture-flow-compressed.xml:90`).
- Child runs can replace parent trace summary before plugins consume it.

### 4) Worker output keys (`worker_<n>_output`)
- Worker names are local to each `WorkerPool` (`worker_1`, `worker_2`, ...) (`rlm_adk/dispatch.py:113-114`), and output keys are derived directly (`rlm_adk/dispatch.py:124`).
- Callback writes these keys into shared state (`rlm_adk/callbacks/worker.py:134-137`).
- A new nested pool restarts naming at `worker_1`, causing output-key collisions (`worker_1_output`) across orchestrator frames.

### 5) Observability counters under nested orchestrators
- Dispatch flush emits per-REPL-call counters to global keys (`rlm_adk/dispatch.py:625-652`).
- Observability plugin keeps run totals in global keys and appends per-iteration breakdown entries keyed only by unsuffixed iteration (`rlm_adk/plugins/observability.py:163-176`, `rlm_adk/plugins/observability.py:203-233`).
- `after_agent_callback` also re-publishes dynamic `obs:*` keys by scanning entire session state (`rlm_adk/plugins/observability.py:120-127`), which amplifies scope bleed across nested frames.

## Depth/Worker Scoping Strategy
Use a two-dimensional scope: depth + orchestrator-frame id.

1. Keep `REQUEST_ID` as immutable root correlation id.
2. Add a per-orchestrator frame id (`orchestrator:run_id`) and parent linkage (`orchestrator:parent_run_id`).
3. Scope all loop-local keys by both depth and run id.
4. Scope worker output keys by run id and worker identity.
5. Store per-scope observability metrics separately; keep optional root rollups for compatibility.

Exact keying format:

- `scope_id := d{depth}:r{run_id}`
- `scoped(base_key, scope_id) := {base_key}@{scope_id}`
- `worker_output(scope_id, worker_name, call_idx) := worker_output@{scope_id}:w={worker_name}:c={call_idx}`

Apply to collision-prone keys:

- `iteration_count@d{depth}:r{run_id}`
- `last_repl_result@d{depth}:r{run_id}`
- `final_answer@d{depth}:r{run_id}`
- `should_stop@d{depth}:r{run_id}`
- `worker_output@d{depth}:r{run_id}:w={worker_name}:c={call_idx}`

Guardrails:

- `REQUEST_ID` write-once rule: set only if absent.
- No direct writes to keys in `DEPTH_SCOPED_KEYS`; all writes go through a resolver helper.
- Observability writes must include `scope_id` (either in key or payload) before aggregation.
- Root-level aliases (`iteration_count`, `last_repl_result`) may mirror only the active top-level frame for backward compatibility.

## Required New Keys
Add these explicit top-level keys in `rlm_adk/state.py`:

- `ORCHESTRATOR_RUN_ID = "orchestrator:run_id"`
- `ORCHESTRATOR_PARENT_RUN_ID = "orchestrator:parent_run_id"`
- `ORCHESTRATOR_SCOPE_STACK = "orchestrator:scope_stack"`  (list of `{depth, run_id}` frames)
- `ROOT_REQUEST_ID = "root_request_id"`  (stable copy of first request id)
- `ACTIVE_SCOPE_ID = "active_scope_id"`  (`d{depth}:r{run_id}`)
- `OBS_SCOPE_METRICS = "obs:scope_metrics"`  (dict keyed by `scope_id`)
- `OBS_SCOPE_BREAKDOWN = "obs:scope_breakdown"`  (per-scope token/call breakdown arrays)

Also add helpers:

- `scope_id(depth: int, run_id: str) -> str`
- `scoped_key(base_key: str, depth: int, run_id: str) -> str`
- `worker_output_key(depth: int, run_id: str, worker_name: str, call_idx: int) -> str`

## Migration/Compatibility Notes
1. Phase 1 (dual-write): write both scoped keys and legacy unsuffixed keys for root/top frame.
2. Phase 2 (reader migration): move observability and trace consumers to scoped reads first, fallback to legacy keys.
3. Phase 3 (strict mode): block unsuffixed writes for keys in `DEPTH_SCOPED_KEYS` except explicit root aliasing.
4. Keep global rollup counters (`obs:total_*`) but derive them from `OBS_SCOPE_METRICS` to avoid double counting.
5. Worker output legacy keys (`worker_<n>_output`) should become optional debug aliases only; primary persistence should be scoped output keys.

## Test Cases
1. Nested request-id integrity.
- Start parent orchestrator, spawn child orchestrator, assert `request_id` remains parent/root while child has distinct `orchestrator:run_id`.

2. Iteration isolation across parent/child.
- Parent reaches iteration 3, child runs 2 steps, assert:
  - `iteration_count@d_parent:r_parent == 3`
  - `iteration_count@d_child:r_child == 2`
  - no overwrite of parent key.

3. Parallel sibling workers at same depth.
- Spawn two child orchestrators concurrently at identical depth; assert unique run ids and no collisions in scoped iteration/repl keys.

4. `LAST_REPL_RESULT` isolation + trace fidelity.
- Parent and child both write traces in same wall-clock window; assert both scoped `last_repl_result@...` entries persist and plugin extraction maps correctly.

5. Worker output key collision prevention.
- Use separate pools where both create `worker_1`; assert persisted state keys differ because scoped key includes run id/depth.

6. Observability scoped accounting.
- Verify `OBS_SCOPE_METRICS[scope_id]` is deterministic per frame and global `obs:total_*` equals sum across scope metrics.

7. Backward compatibility alias behavior.
- During dual-write, assert legacy `iteration_count` and `last_repl_result` reflect active top-level frame only and do not include child frame values.

8. Guardrail enforcement.
- Unit-test direct write attempts to depth-scoped keys without resolver fail fast (exception or lint/test failure).
