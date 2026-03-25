# Understand Phase 2: Depth Topology & Event Flow

**Document**: `/home/rawley-stanhope/dev/rlm-adk/issues/test_skill/understand_2_depth_topology.md`

**Date**: 2026-03-25  
**Analyst**: UNDERSTAND Agent 2  
**Scope**: Depth topology, event flow, child dispatch mechanics, and provider-fake fixture design

---

## A. Restate

The core requirement is to validate that RLM-ADK can successfully call recursive child agents to depth 2 or deeper, with child agents also calling `llm_query()` to spawn their own children. The existing `skill_arch_test.json` fixture demonstrates depth=1 (root agent spawning one child), but there is no fixture yet that exercises depth=2 (root calls child, child calls grandchild). The task is to understand the complete depth topology, map the event flow for nested dispatch, and specify how many provider-fake responses are needed to construct a depth=2 test.

---

## B. Target

Produce a complete technical specification for depth-2 fixture design, including:

1. **Exact call tree**: Every model invocation (call_index), caller identity (reasoning vs worker), depth, and action (tool call name)
2. **Provider-fake response count**: The complete number of responses needed in the fixture JSON
3. **State key evolution**: What state keys exist at d0, d1, d2, and how they are prefixed/scoped
4. **Event flow diagram**: How events bubble up from child to parent, timing of child event re-emission
5. **Depth-scoped key mapping**: Exact keys and their depth prefixes at each level

---

## C. Givens

From code inspection, tests, and fixtures:

1. **Root orchestrator always at depth=0** with `reasoning_agent` (LlmAgent) wired with `REPLTool` and `SetModelResponseTool`
2. **Child creation**: Each `llm_query()` call spawns a new `RLMOrchestratorAgent` at `depth = parent_depth + 1`
3. **Current fixture**: `skill_arch_test.json` has 3 model calls (call_index 0, 1, 2):
   - call_index=0: depth=0 reasoning agent calls `execute_code`
   - call_index=1: depth=1 child reasoning agent (triggered by llm_query inside REPL) calls `set_model_response`
   - call_index=2: depth=0 reasoning agent calls `set_model_response`
4. **Thread bridge dispatch**: llm_query() is a real sync callable that uses `run_coroutine_threadsafe()` to dispatch async child orchestrators
5. **State scoping**: Keys in `DEPTH_SCOPED_KEYS` are suffixed with `@dN` at depth N > 0
6. **Child event re-emission**: Child state-delta events are filtered and pushed onto `child_event_queue` by dispatch.py `_run_child()`, then drained by orchestrator after each reasoning event
7. **Max depth default**: `RLM_MAX_DEPTH` env var defaults to 5, checked before child creation

---

## D. Conditions

Constraints that bound the solution:

1. **Provider-fake mock responses must match actual pipeline semantics**: Each response body must include `functionCall` with correct tool name and args
2. **No reward-hacking**: Initial state seeds only configuration (user_provided_ctx, repo_url, etc.), not results
3. **Depth limit**: The fixture can go to at most depth=5 (current default RLM_MAX_DEPTH) but depth=2 is sufficient to prove recursion
4. **State mutation must use event channels**: All state writes through `EventActions(state_delta={...})`, never raw `ctx.session.state[key] = value`
5. **Async boundaries**: llm_query() calls block the REPL worker thread and return `LLMResult` objects that must be stringifiable
6. **Skill injection timing**: Skills are injected into REPL globals at orchestrator init time, before any code execution, so child REPL has them too

---

## E. Unknowns

What the design must resolve:

1. **Exact number of provider-fake responses for depth=2**: Is it 4? 5? 6? Depends on how many code executions vs set_model_response calls happen
2. **Whether children always call set_model_response or sometimes execute_code first**: Can a child at depth=1 call execute_code? Or does it only call set_model_response?
3. **How child event re-emission affects the event stream order**: Do child events appear interleaved with parent events, or queued?
4. **What observable state keys differentiate d0, d1, d2 in the final SQLite traces**: Which depth-scoped keys must be present?
5. **Whether batched llm_query_batched() requires more fixture responses**: A single `llm_query_batched([p1, p2, p3])` spawns 3 concurrent children — is that 3 responses or 1?

---

## F. Definitions

Key terms clarified:

- **Depth**: Integer N where root orchestrator is d0, its direct children are d1, their children are d2, etc.
- **Depth-scoped key**: A state key suffixed `@dN` (e.g., `iteration_count@d1`) visible only at depth N via the depth_key() function
- **Call index**: The ordinal position of a model invocation in the fixture's `responses` array (0-indexed)
- **Caller**: Either `"reasoning"` (reasoning_agent making a model call) or `"worker"` (created by dispatch.py for child orchestrator)
- **set_model_response**: ADK tool that terminates an agent run with a typed response; used by all agents (root + children)
- **execute_code**: REPLTool wrapped and wired as a BaseTool; used only by reasoning agents when they choose to write code
- **Thread bridge**: The `make_sync_llm_query()` and `make_sync_llm_query_batched()` closures that wrap async dispatch in sync callables via `run_coroutine_threadsafe()`
- **Child event re-emission**: The mechanism by which a child orchestrator's state deltas are captured during `_run_child()` and pushed onto `child_event_queue` for the parent to re-emit to the ADK Runner

---

## G. Representation

### Call Tree Diagram for depth=2 Fixture

```
                        ┌─────────────────────────┐
                        │ Runner.run_async()      │
                        │ (event loop)            │
                        └────────────┬────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │ RLMOrchestratorAgent    │
                        │ depth=0 (root)          │
                        │ (call_index 0,2)        │
                        └────────────┬────────────┘
                                     │
                    ┌────────────────┴──────────────────┐
                    │ reasoning_agent.run_async()       │
                    │ (ADK native tool loop)            │
                    │ (call_index 0)                    │
                    └────────────┬───────────────────────┘
                                 │
              ┌──────────────────────┬────────────────────┐
              │ REPLTool             │ SetModelResponse   │
        (call_index 0)          (call_index 2)
              │                     │
              ▼                     │
    execute_code("...")            │
    REPL worker thread             │
         │                         │
         ├─ llm_query("q1")◄────────── thread bridge
         │      │                  │
         │      │                  │
         │      └─► asyncio.run_coroutine_threadsafe()
         │          to event loop
         │          ┌────────────────────────────────┐
         │          │ llm_query_async("q1")          │
         │          │ (dispatch.py)                  │
         │          └────────┬─────────────────────────┘
         │                   │
         │      ┌────────────▼──────────────┐
         │      │ RLMOrchestratorAgent      │
         │      │ depth=1 (child_0)         │
         │      │ (call_index 1, 3)         │
         │      └────────────┬──────────────┘
         │                   │
         │      ┌────────────▼──────────────────┐
         │      │ reasoning_agent.run_async()   │
         │      │ depth=1                       │
         │      │ (call_index 1)                │
         │      └────────────┬──────────────────┘
         │                   │
         │    ┌──────────────┴──────────────┐
         │    │ REPLTool                    │ SetModelResponse
         │ (call_index 1)            (call_index 3)
         │    │                           │
         │    ▼                           │
         │ execute_code("...")           │
         │ (child REPL worker thread)   │
         │    │                         │
         │    ├─ llm_query("q2")◄───────── thread bridge
         │    │      │                  │
         │    │      │                  │
         │    │      └─► asyncio.run_coroutine_threadsafe()
         │    │          to event loop
         │    │          ┌────────────────────────────────┐
         │    │          │ llm_query_async("q2")          │
         │    │          │ (dispatch.py)                  │
         │    │          └────────┬─────────────────────────┘
         │    │                   │
         │    │      ┌────────────▼──────────────┐
         │    │      │ RLMOrchestratorAgent      │
         │    │      │ depth=2 (grandchild)      │
         │    │      │ (call_index 4)            │
         │    │      └────────────┬──────────────┘
         │    │                   │
         │    │      ┌────────────▼──────────────────┐
         │    │      │ reasoning_agent.run_async()   │
         │    │      │ depth=2                       │
         │    │      │ (call_index 4)                │
         │    │      └────────────┬──────────────────┘
         │    │                   │
         │    │                   │ SetModelResponse
         │    │                   │ (call_index 4)
         │    │                   │
         │    │      ┌────────────▼──────────────┐
         │    │      │ Orchestrator terminates   │
         │    │      │ → LLMResult returned      │
         │    │      └───────────────────────────┘
         │    │
         │    │ [LLMResult from grandchild]
         │    │ ┌─────────────────────────┐
         │    └─► REPL continues          │
         │        Print result            │
         │        Set variables           │
         │        ┌────────────────────────┘
         │
         └─► [final_answer from child REPL]
             Return to parent llm_query() call
             (thread bridge unblocks REPL)
             ┌─────────────────────────────┐
             │ Parent REPL continues       │
             │ (receives LLMResult)        │
             │ Prints [TEST_SKILL:...]     │
             │ Returns TestSkillResult     │
             └─────────────────────────────┘
                          │
                          │
             ┌────────────▼──────────────┐
             │ reasoning_agent sees REPL │
             │ output with result        │
             │ (call_index 2)            │
             │ calls set_model_response  │
             └───────────────────────────┘
```

### Provider-Fake Response Structure for depth=2

```
responses: [
  {
    call_index: 0,
    caller: "reasoning",  # depth=0 reasoning_agent
    body: {
      functionCall: { name: "execute_code", args: {...} }
    }
  },
  {
    call_index: 1,
    caller: "worker",     # depth=1 reasoning_agent (dispatched by llm_query)
    body: {
      functionCall: { name: "execute_code", args: {...} }
    }
  },
  {
    call_index: 2,
    caller: "worker",     # depth=2 reasoning_agent (dispatched by child's llm_query)
    body: {
      functionCall: { name: "set_model_response", args: {...} }
    }
  },
  {
    call_index: 3,
    caller: "worker",     # depth=1 reasoning_agent (continues after child returns)
    body: {
      functionCall: { name: "set_model_response", args: {...} }
    }
  },
  {
    call_index: 4,
    caller: "reasoning",  # depth=0 reasoning_agent (continues after child returns)
    body: {
      functionCall: { name: "set_model_response", args: {...} }
    }
  }
]
```

**Total responses needed: 5** (call_index 0 through 4)

---

## H. Assumptions

Hidden premises that must be validated:

1. **ADK's native tool-calling loop is re-entrant within the same session**: When a child orchestrator runs inside `_run_child()`, ADK's reasoning_agent.run_async() is called recursively, but all invocation contexts are separate. This works because each child gets its own `ctx` parameter and its own temporary state tracking.

2. **The thread bridge correctly suspends and resumes the REPL worker thread**: `asyncio.run_coroutine_threadsafe()` blocks on `future.result(timeout)` without deadlock, allowing child dispatch to complete on the main event loop while the worker thread waits.

3. **State keys at different depths do not collide**: A key like `iteration_count` at depth=0 is stored as `iteration_count` (no suffix), while at depth=1 it is `iteration_count@d1`. The `depth_key()` function ensures this mapping is consistent.

4. **Provider-fake mock responses trigger the correct conditional paths in real code**: The `set_model_response` response at call_index=2 will be recognized by ADK as a tool call and executed, not treated as text.

5. **Child event re-emission is optional for core functionality**: If `child_event_queue` is not passed to `create_dispatch_closures()`, child state deltas are lost; but the child still completes and returns a value. For observability (SQLite telemetry, state audit), re-emission is critical.

6. **Fanout indexing doesn't affect depth-scoped keys**: `fanout_idx` is used only for batched dispatch (llm_query_batched), not for single llm_query(). It does not appear in state key suffixes.

---

## I. Well-Posedness

**Assessment: WELL-POSED**

The problem is complete and internally consistent:

- **Sufficient data**: The source code (orchestrator.py, dispatch.py, thread_bridge.py, repl_tool.py) fully specifies depth creation and event flow
- **Solvable**: The fixture design is a straightforward application of the existing patterns (skill_arch_test.json as template)
- **Deterministic**: Provider-fake mocking provides deterministic control — no randomness or network indeterminacy
- **No contradictions**: The architectural requirements (AR-CRIT-001 state mutation, depth scoping, skill injection) are consistent with the code

Potential ambiguity resolved:
- **Whether children execute code or only set_model_response**: Both are possible. A depth=1 child can execute REPL code (if the model requests it), which can then call llm_query() spawning depth=2. Or it can immediately call set_model_response. The fixture design chooses when each happens by controlling provider-fake responses.

---

## J. Success Criteria

A correct solution must satisfy:

1. **Call tree accuracy**: The fixture's `responses` array matches the actual call sequence with no gaps or extra calls
2. **Depth correctness**: Each response identifies the correct depth (0, 1, or 2) and caller type (reasoning or worker)
3. **State key presence**: SQLite traces and session state must show depth-scoped keys (iteration_count@d1, current_depth@d2, etc.) appearing at the correct depths
4. **Child event re-emission**: session_state_events table must contain rows with `key_depth > 0`, proving child state was captured
5. **Execution mode**: LAST_REPL_RESULT["execution_mode"] == "thread_bridge" for all code execution
6. **No depth-limit violation**: max_depth default (5) is not exceeded; depth=2 completes without DEPTH_LIMIT errors
7. **Backward compatibility**: depth=1 fixtures (existing skill_arch_test.json) continue to pass without modification

---

## K. Depth Topology Analysis

### K.1 Complete Call Tree with Depths

```
MODEL_CALL SEQUENCE (5 total for depth=2 fixture):

Call 0: reasoning_agent at depth=0
  ├─ Agent name: reasoning_agent
  ├─ Depth: 0
  ├─ Parent: RLMOrchestratorAgent(depth=0)
  ├─ Model input tokens: ~300
  ├─ Tool call: execute_code("code to call llm_query('q1')")
  ├─ State at start: iteration_count=1, current_depth=0
  └─ Outcome: Code executes, llm_query('q1') dispatches to depth=1

Call 1: reasoning_agent at depth=1
  ├─ Agent name: reasoning_agent_d1 (or child_reasoning_d1)
  ├─ Depth: 1
  ├─ Parent: RLMOrchestratorAgent(depth=1), created by dispatch.py _run_child()
  ├─ Parent orchestrator's depth: 0
  ├─ Lineage: parent_depth=0, parent_fanout_idx=0
  ├─ Model input tokens: ~100 (reduced from root context)
  ├─ Tool call: execute_code("code to call llm_query('q2')")
  ├─ State at start: iteration_count@d1=1, current_depth@d1=1
  └─ Outcome: Code executes, llm_query('q2') dispatches to depth=2

Call 2: reasoning_agent at depth=2
  ├─ Agent name: reasoning_agent_d2 (or grandchild_reasoning_d2)
  ├─ Depth: 2
  ├─ Parent: RLMOrchestratorAgent(depth=2), created by dispatch.py _run_child()
  ├─ Parent orchestrator's depth: 1
  ├─ Lineage: parent_depth=1, parent_fanout_idx=0
  ├─ Model input tokens: ~80 (further reduced)
  ├─ Tool call: set_model_response(final_answer="...")
  ├─ State at start: iteration_count@d2=0, current_depth@d2=2
  ├─ Outcome: Agent terminates, returns CompletionEnvelope with final_answer
  └─ Result: LLMResult returned to depth=1's llm_query() call

Call 3: reasoning_agent at depth=1 (resumed)
  ├─ Agent name: reasoning_agent_d1
  ├─ Depth: 1
  ├─ Model input tokens: updated with child result from stdout
  ├─ Tool call: set_model_response(final_answer="child result was: ...")
  ├─ State at step: iteration_count@d1=1, current_depth@d1=1
  ├─ Outcome: Agent terminates, returns CompletionEnvelope
  └─ Result: LLMResult returned to depth=0's llm_query() call

Call 4: reasoning_agent at depth=0 (resumed)
  ├─ Agent name: reasoning_agent
  ├─ Depth: 0
  ├─ Model input tokens: updated with grandchild result chain from REPL stdout
  ├─ Tool call: set_model_response(final_answer="...")
  ├─ State at step: iteration_count=1, current_depth=0
  ├─ Outcome: Agent terminates, returns CompletionEnvelope
  └─ Result: Final answer returned to RLMOrchestratorAgent(depth=0)
```

### K.2 State Key Evolution by Depth

#### At Depth=0 (Root)

Initialized before any code execution:

```
current_depth: 0
iteration_count: 1
should_stop: false
final_response_text: (none)
last_repl_result: (none)
request_id: (generated UUID)
user_provided_ctx: {...}
repo_url: "..."
root_prompt: "..."
artifact_save_count: 0
```

After Call 0 (execute_code):

```
[same as above, plus]
last_repl_result: {
  "stdout": "[TEST_SKILL:depth=0]...[TEST_SKILL:llm_query_fn_type=function]...",
  "stderr": "",
  "variables": {result: TestSkillResult(...)},
  "llm_calls_made": true,
  "execution_mode": "thread_bridge"
}
repl_submitted_code: "result = llm_query('q1'); print(...)"
repl_submitted_code_chars: 45
artifact_save_count: 1
```

After Call 4 (set_model_response from depth=0):

```
should_stop: true
final_response_text: "Recursion complete. Depth=2 reached and returned."
reasoning_output: {
  "final_answer": "Recursion complete...",
  "reasoning_summary": "..."
}
```

#### At Depth=1 (Child)

Initialized when child orchestrator is created:

```
current_depth@d1: 1
iteration_count@d1: 0 (starts fresh per child)
should_stop@d1: false
final_response_text@d1: (none)
last_repl_result@d1: (none)
_rlm_depth: 1 (runtime lineage metadata in _rlm_state snapshot)
_rlm_agent_name: "reasoning_agent_d1"
_rlm_fanout_idx: 0
```

After Call 1 (execute_code at d1):

```
iteration_count@d1: 1
last_repl_result@d1: {
  "stdout": "[TEST_SKILL:depth=1]...",
  "stderr": "",
  "variables": {...},
  "llm_calls_made": true
}
repl_submitted_code@d1: "..."
artifact_save_count@d1: 1
```

After Call 3 (set_model_response from depth=1):

```
should_stop@d1: true
final_response_text@d1: "grandchild returned: ..."
reasoning_output@d1: {
  "final_answer": "grandchild returned: ...",
  "reasoning_summary": "..."
}
```

#### At Depth=2 (Grandchild)

Initialized when grandchild orchestrator is created:

```
current_depth@d2: 2
iteration_count@d2: 0
should_stop@d2: false
final_response_text@d2: (none)
_rlm_depth: 2
_rlm_agent_name: "reasoning_agent_d2"
_rlm_fanout_idx: 0
```

After Call 2 (set_model_response immediately at d2):

```
should_stop@d2: true
final_response_text@d2: "leaf node response"
reasoning_output@d2: {
  "final_answer": "leaf node response",
  "reasoning_summary": "..."
}
```

### K.3 Depth-Scoped Key Prefixing

The `depth_key(key, depth)` function implements this logic:

```python
def depth_key(key: str, depth: int = 0) -> str:
    if depth == 0:
        return key  # No suffix
    return f"{key}@d{depth}"
```

Applied to keys in `DEPTH_SCOPED_KEYS`:

| Key Name | d=0 Storage | d=1 Storage | d=2 Storage |
|----------|------------|------------|------------|
| `current_depth` | `current_depth` | `current_depth@d1` | `current_depth@d2` |
| `iteration_count` | `iteration_count` | `iteration_count@d1` | `iteration_count@d2` |
| `final_response_text` | `final_response_text` | `final_response_text@d1` | `final_response_text@d2` |
| `should_stop` | `should_stop` | `should_stop@d1` | `should_stop@d2` |
| `last_repl_result` | `last_repl_result` | `last_repl_result@d1` | `last_repl_result@d2` |
| `repl_submitted_code` | `repl_submitted_code` | `repl_submitted_code@d1` | `repl_submitted_code@d2` |

**Key insight**: Each depth has its own independent namespace. A child at d=1 increments `iteration_count@d1`, not `iteration_count`. The parent's `iteration_count` remains 1. This prevents collision and allows independent REPL execution tracking per depth.

### K.4 Child Event Re-Emission Path

Sequence of events in `_run_child()` (dispatch.py):

```
1. Child orchestrator created: RLMOrchestratorAgent(depth=1, ...)
2. Child's _run_async_impl() starts → yields events
3. Each event has state_delta containing child-scoped keys
4. Orchestrator consumes event: async for event in child.run_async(ctx)
5. For each event:
   - Extract state_delta
   - For each key in state_delta:
     - Parse key to determine depth: parse_depth_key(key) → (base_key, key_depth)
     - Check if should_capture_state_key(base_key)
     - If yes: create new Event with custom_metadata.rlm_child_event=True
     - Put event onto child_event_queue via put_nowait()

6. Orchestrator's _run_async_impl() drains queue after reasoning_agent.run_async():
   while not queue.empty():
     child_event = queue.get_nowait()
     yield child_event  # To ADK Runner

7. Final drain after reasoning loop completes to catch edge cases
```

**Result in SQLite session_state_events table**:

```sql
SELECT * FROM session_state_events WHERE key_depth > 0;

-- Depth=1 events
│ ... │ key='current_depth@d1' │ value='1'   │ key_depth=1 │ custom_metadata.rlm_child_event=true │
│ ... │ key='should_stop@d1'   │ value='true'│ key_depth=1 │ custom_metadata.rlm_child_event=true │
│ ... │ key='final_response_text@d1' │ ... │ key_depth=1 │ ... │

-- Depth=2 events (if re-emission is working correctly)
│ ... │ key='current_depth@d2' │ value='2'   │ key_depth=2 │ custom_metadata.rlm_child_event=true │
│ ... │ key='should_stop@d2'   │ value='true'│ key_depth=2 │ ... │
```

### K.5 llm_query_batched() Behavior

If fixture calls `llm_query_batched([p1, p2, p3])` instead of three separate `llm_query()`:

```
Single call in REPL:
results = llm_query_batched(["q1", "q2", "q3"])

Dispatch behavior (dispatch.py llm_query_batched_async):
1. Create 3 tasks: _run_child(p1, fanout_idx=0), _run_child(p2, fanout_idx=1), _run_child(p3, fanout_idx=2)
2. await asyncio.gather(*tasks) with semaphore(max_concurrent=3)
3. Each task is independent child orchestrator at depth+1
4. All three execute "concurrently" (subject to semaphore)
5. Collect results into list[LLMResult]
6. Return to REPL code

Provider-fake fixture response structure:
responses: [
  { call_index: 0, caller: "reasoning", body: { functionCall: {name: "execute_code", args: {...llm_query_batched...}} } },
  { call_index: 1, caller: "worker", body: { functionCall: {name: "set_model_response", ...} } },  # child[0]
  { call_index: 2, caller: "worker", body: { functionCall: {name: "set_model_response", ...} } },  # child[1]
  { call_index: 3, caller: "worker", body: { functionCall: {name: "set_model_response", ...} } },  # child[2]
  { call_index: 4, caller: "reasoning", body: { functionCall: {name: "set_model_response", ...} } },
]

Total: 5 responses (1 root execute + 3 children set_model + 1 root set_model)
Difference from single llm_query: Same total, but all children are siblings (fanout_idx 0, 1, 2)
```

**Key insight**: `llm_query_batched()` doesn't increase depth; it spawns sibling children (all at depth d+1) with distinct fanout_idx values. A true depth=2 call requires one child to call llm_query() after its code execution.

### K.6 Number of Provider-Fake Responses for Each Scenario

| Scenario | Description | Responses | Call Indices |
|----------|-------------|-----------|--------------|
| **Depth=0 only** | Root calls set_model_response immediately | 1 | 0 |
| **Depth=0 execute, then set** | Root executes code, then calls set | 2 | 0, 1 |
| **Depth=1 via llm_query** | Root calls code with llm_query, child calls set | 3 | 0, 1, 2 |
| **Depth=2 (single path)** | Root code → llm_query → child code → llm_query → grandchild set → child set → root set | 5 | 0, 1, 2, 3, 4 |
| **Depth=2 (batched)** | Root code with llm_query_batched([3 prompts]) → 3 children → root set | 5 | 0, 1, 2, 3, 4 |
| **Depth=3** | Root → child → grandchild → great-grandchild | 7 | 0-6 |

**Formula for linear depth chain** (each level executes code then dispatches one child):
```
total_responses = 2 * depth + 1

Examples:
- depth=0: 2*0 + 1 = 1
- depth=1: 2*1 + 1 = 3
- depth=2: 2*2 + 1 = 5 ✓
- depth=3: 2*3 + 1 = 7
```

---

## Summary

The depth topology is fully determined by:

1. **Recursion entry point**: llm_query() in REPL code creates child at depth+1
2. **Child orchestrator creation**: each call to `_run_child(depth, ...)` instantiates a new RLMOrchestratorAgent with depth incremented
3. **State isolation**: Each depth has its own namespace via depth-scoped key suffixes (@dN)
4. **Event threading**: Child events are captured and re-emitted via child_event_queue to maintain observability
5. **Provider-fake count**: For a depth=2 linear call chain: 5 responses (formula: 2*depth + 1)

A complete depth=2 fixture requires:
- **5 provider-fake responses** with correct `functionCall` names and arguments
- **State assertions** validating current_depth@d1, current_depth@d2, should_stop@d1, should_stop@d2
- **Event re-emission checks** in session_state_events for key_depth=1 and key_depth=2 rows
- **SQLite telemetry** showing max_depth_reached=2 in traces table
- **Lineage metadata** confirming parent_depth and parent_fanout_idx on child orchestrators

---

**End of Understand Phase 2 Document**
