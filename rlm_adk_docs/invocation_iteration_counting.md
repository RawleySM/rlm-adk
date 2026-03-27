# Invocation Iteration Counting

How RLM-ADK tracks the iteration (turn) number within each agent invocation,
and how the dashboard derives iteration labels for display.

## Source of Truth: REPLTool._call_count

Each `RLMOrchestratorAgent` creates a `REPLTool` instance scoped to its
`(depth, fanout_idx)` pair.  The tool maintains a local `_call_count`
starting at 0:

```python
# rlm_adk/tools/repl_tool.py:78,130-132
self._call_count = 0

# On each execute_code invocation:
self._call_count += 1
tool_context.state[depth_key(ITERATION_COUNT, self._depth, self._fanout_idx)] = self._call_count
```

This means:
- **Increment trigger**: every `execute_code` tool call
- **Does NOT increment on**: `set_model_response` (different tool, same model turn)
- **Scope**: per `(depth, fanout_idx)` — fully independent per agent instance

## State Key Format

`iteration_count` is a **depth-scoped key** (`rlm_adk/state.py:133`).
The `depth_key()` function suffixes it with `@d{depth}f{fanout_idx}`:

```
depth_key("iteration_count", 0)     -> "iteration_count"        # root
depth_key("iteration_count", 1, 0)  -> "iteration_count@d1f0"   # child depth=1, fanout=0
depth_key("iteration_count", 2, 3)  -> "iteration_count@d2f3"   # grandchild
```

## Reset Boundaries

Each child orchestrator creates a **new** `REPLTool` with `_call_count = 0`:

```python
# rlm_adk/orchestrator.py:414-415  (inside _run_async_impl)
initial_state = {
    depth_key(ITERATION_COUNT, self.depth, self.fanout_idx): 0,
    ...
}
```

This means:
- Root orchestrator (d0): resets per user message (new invocation)
- Child orchestrator (d1f0): resets each time it is spawned by a parent `execute_code`
- The same `d#f#` spawned from different parent iterations gets a **fresh** counter each time

## Parent-Child Iteration Independence

Parent and child iterations are fully isolated:

```
Parent (d0):
  iter 1: execute_code  →  (spawns child d1f0)
    Child d1f0: iter 1, iter 2, iter 3 → set_model_response
  iter 2: execute_code  →  (spawns child d1f0 again)
    Child d1f0: iter 1, iter 2 → set_model_response     ← resets to 1
  iter 3: execute_code  →  (spawns d1f0 + d1f1 via llm_query_batched)
    Child d1f0: iter 1 → set_model_response
    Child d1f1: iter 1, iter 2 → set_model_response
  iter 4: set_model_response                             ← no increment
```

The iteration count for each child is **idempotent** when qualified by the
full lineage path: `d0iter2/d1f0iter1` uniquely identifies a specific model
turn across the entire execution tree.

## Iteration in the ADK Agent Loop

Google ADK's `BaseLlmFlow.run_async()` runs a while-loop where each iteration
calls `_run_one_step_async()` — one LLM call plus optional tool execution.
ADK tracks total LLM calls via `InvocationContext._invocation_cost_manager`
(`_number_of_llm_calls`) but does not expose a per-agent iteration counter.
RLM-ADK's `REPLTool._call_count` fills this gap.

Each ADK "step" maps to one `(model_event, tool_event)` pair in the dashboard
event stream.  The loop terminates when:
1. The model emits `set_model_response` (successful completion)
2. `_call_count` exceeds `max_iterations` (safety limit)
3. `end_invocation` is set by a callback

## Dashboard Event Stream Mapping

The `DashboardEventPlugin` emits JSONL events with explicit lineage fields:

| Field                  | Source                              | Purpose                       |
|------------------------|-------------------------------------|-------------------------------|
| `depth`                | `agent._rlm_depth`                  | Nesting level                 |
| `fanout_idx`           | `agent._rlm_fanout_idx`             | Batch position                |
| `dispatch_call_index`  | `agent._rlm_dispatch_call_index`    | Ordering within batch         |
| `parent_tool_call_id`  | `agent._rlm_parent_tool_call_id`    | Links child to parent tool    |
| `agent_name`           | `agent.name`                        | Unique per (depth, fanout)    |

**Iteration is NOT emitted as a JSONL field.** Instead, the dashboard derives
it from step ordering within the invocation tree.

## Dashboard Derivation of Iteration Number

`event_reader.build_tree()` groups events by `agent_name` and pairs them
into `(model_event, tool_event | None)` tuples stored in `steps[agent_name]`.
These pairs are in execution order (JSONL line order within each agent).

The **1-based index** of each step pair IS the iteration number:

```python
steps = tree.steps.get(agent_name, [])
# steps[0] = iteration 1 (first model call + tool response)
# steps[1] = iteration 2 (second model call + tool response)
# ...
# steps[N-1] = iteration N (may be set_model_response, no increment in source)
```

This directly corresponds to `REPLTool._call_count` for steps where the tool
is `execute_code`, with the caveat that the final step (usually
`set_model_response`) has no matching `_call_count` increment — it is still
a distinct model turn and gets the next iteration number in the display.

## Display Format

The model banner replaces the redundant depth label with the iteration:

```
Before:  child_reasoning_d1f0  d1   in:120 out:10  gemini-fake
After:   child_reasoning_d1f0  i1   in:120 out:10  gemini-fake
```

The depth is already encoded in the agent name (`d1f0`), making a separate
`d1` label redundant.  The iteration number `iN` shows which turn of the
reasoning loop this model call represents.
