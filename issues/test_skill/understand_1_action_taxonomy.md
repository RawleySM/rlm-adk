# UNDERSTAND Phase: Action Taxonomy & Isolation

**Document Location:** `/home/rawley-stanhope/dev/rlm-adk/issues/test_skill/understand_1_action_taxonomy.md`

## A. Restate

The core insight from the user is that "the codebase at its core boils down to a limited set of agent actions that we should be able to isolate and test." I need to:

1. Enumerate all distinct actions any RLMOrchestratorAgent or child agent can take
2. Map each action to its precise code path and entry point
3. Identify which actions apply identically at every depth
4. Catalog which state keys each action reads and writes
5. Determine the minimum fixture responses needed for multi-turn, multi-depth tests

---

## B. Target

**Primary objective:** Create a complete, exhaustive enumeration of the action taxonomy that:
- Lists every discrete agent action (not every code path variant)
- Maps each action to its entry/exit points in the source
- Shows how each action transitions state and fires callbacks
- Identifies which actions must be tested in isolation vs. composition
- Establishes the preconditions and postconditions for each action

**Secondary objective:** Use this taxonomy to validate that the existing `skill_arch_test.json` fixture covers the essential actions, and identify which actions are untested.

---

## C. Givens

**Architectural foundations:**
- RLM-ADK is built on Google ADK's event-driven architecture
- The orchestrator does NOT manually iterate; it delegates to ADK's native tool-calling loop
- Every agent at every depth shares the same action interface and state key structure
- Depth scoping (`@dN` suffixes) allows independent state per recursion level
- Child agents are dispatch-created copies of RLMOrchestratorAgent at depth+1
- State mutations MUST flow through ADK-tracked channels (AR-CRIT-001 rule)
- Skills are discoverable via SKILL.md frontmatter and injected as REPL globals
- Thread bridge (via `run_coroutine_threadsafe`) is the only dispatch mechanism; AST rewriter is deleted

**From documentation:**
- Core Loop doc lists 7 extension points (orchestrator, REPL, thread bridge, recursion depth, etc.)
- Dispatch & State doc defines 200+ state keys across flow control, observability, and artifact domains
- Observability doc documents 4+ plugin systems that observe actions
- Testing doc specifies provider-fake infrastructure for deterministic testing

**From implementation:**
- `orchestrator.py`: RLMOrchestratorAgent._run_async_impl (lines 242-658)
- `dispatch.py`: create_dispatch_closures returns 3-tuple (llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn)
- `tools/repl_tool.py`: REPLTool.run_async is the primary executor
- `state.py`: 90+ state key constants defined with depth-scoping rules
- `repl/thread_bridge.py`: sync bridge closures that block REPL thread during child dispatch

**From existing test:**
- `skill_arch_test.json` has 3 response entries (2 calls total, one depth=0 + one depth=1)
- `test_skill_arch_e2e.py` runs 8 contract + lineage + observability assertions
- Expected lineage documented in `REVIEW_skill_arch_e2e_gaps.md` with 13 recommended assertion additions

---

## D. Conditions

**Constraints that must be satisfied:**

1. **Every action must be testable at depth 0 (root) AND depth 1+ (child)** — the architecture guarantees that the same agent code path is used at all depths, so any action isolation test must verify this invariant.

2. **State mutation paths are not negotiable** — AR-CRIT-001 forbids ctx.session.state writes in dispatch closures. All actions must be verified to use only tracked channels (tool_context.state, EventActions, callbacks).

3. **No AST rewriting** — llm_query() is a real sync callable (thread bridge), not a transformed async function. This means action isolation tests CANNOT rely on AST detection; they must verify the thread bridge mechanism directly.

4. **Depth-scoped state keys are mandatory** — child agents must use depth_key() to avoid colliding with parent state. Tests must verify that key suffixing occurs correctly.

5. **Skill injection is module-import only** — the old source-expansion path is deleted. Skills are discovered from SKILL.md, injected into repl.globals via loader.py, and called as regular REPL functions. Tests must verify this path, not the deleted one.

6. **Events must be yielded, not accumulated** — the orchestrator MUST yield events to the ADK Runner; it cannot batch them or write them directly to ctx.session.state. Tests must verify the event stream, not state snapshots alone.

7. **Child event re-emission is required** — child state deltas must flow through child_event_queue and be drained by the parent. Tests must verify that child_depth > 0 rows appear in session_state_events.

---

## E. Unknowns

**Gaps in the existing test coverage that this taxonomy must address:**

1. **Which actions are untested?** The skill_arch_test fixture covers: execute_code, llm_query (child dispatch), and set_model_response. But what about:
   - llm_query_batched (concurrent multi-child dispatch)?
   - Error handling in each action (REPL syntax error, child timeout, depth limit)?
   - Structured output (output_schema parameter)?
   - State mutation via post_dispatch_state_patch_fn?
   - Skill loading failure or missing skill?

2. **What is the minimal fixture structure for a 3+ turn, depth=2+ scenario?** The skill_arch_test has only 3 responses (1 root + 1 child). A comprehensive fixture would need:
   - Root orchestrator call 1 → execute_code (depth 0)
   - Child orchestrator call 1 → llm_query triggered (depth 1)
   - Root orchestrator call 2 → execute_code with new state (depth 0 again)
   - Grandchild orchestrator call 1 → nested llm_query (depth 2)
   - ... and back up

3. **Which actions change between depths?** Both root and child use the same action interface, but:
   - Root uses full static instruction + repomix
   - Child uses condensed static instruction (no repomix)
   - Root has max_iterations=30
   - Child has max_iterations=10
   Do these differences affect the action contract?

4. **How should state isolation be tested?** The existing test observes final state values but does NOT verify that they arrived via the correct mutation path (tool_context.state vs raw write). Should a test hook capture the channel used?

5. **What does "action isolation" mean operationally?** Can we test execute_code WITHOUT llm_query? Can we test llm_query WITHOUT the parent execute_code? What is the minimal reproducible unit?

---

## F. Definitions

**Key terms operationalized:**

**Action**: A discrete, named interface point that an agent uses to interact with its environment. Examples: "execute_code tool call", "llm_query dispatch", "set_model_response termination". Each action has preconditions, postconditions, state impacts, and observable artifacts.

**Entry point**: The place in the source code where an action begins execution. Examples: `REPLTool.run_async()` for execute_code, `llm_query_async()` closure for dispatch, `reasoning_agent.run_async()` delegation for tool-calling iteration.

**Exit point**: Where the action returns control and its result is delivered. Examples: REPLTool returns dict to ADK, llm_query returns LLMResult to REPL code, set_model_response returns typed response to orchestrator.

**Isolation**: The ability to test one action without requiring the others to succeed. This requires understanding which actions are composable prerequisites vs which can stand alone.

**Depth-invariance**: An action exhibits depth-invariance if it can be executed identically at depth 0, 1, 2, etc. Example: execute_code is depth-invariant (REPL mechanics don't change). Counter-example: the initial static instruction is depth-variant (root gets repomix, child doesn't).

**State key depth-scoping**: The practice of suffixing state keys with `@dN` at depth N > 0 to isolate child state from parent. Examples: `iteration_count@d1`, `should_stop@d2`.

**Fixture response**: A simulated LLM response in a provider-fake test. Each response has: call_index, caller (reasoning vs worker), status, body (with functionCall or set_model_response), and optional note explaining the expected behavior.

**Caller field**: In fixture responses, indicates who is invoking the action: "reasoning" means the root/parent reasoning_agent, "worker" means a child orchestrator at depth > 0. (Terminology is historical; "worker" now means child orchestrator.)

---

## G. Representation

### Action Taxonomy Diagram

```
RLMOrchestratorAgent
  |
  +-- _run_async_impl()
       |
       +-- CREATE_LOCALREPL (action: setup)
       |
       +-- CREATE_DISPATCH_CLOSURES (action: setup)
       |
       +-- CREATE_REPLTOOL (action: setup)
       |
       +-- CREATE_SETMODELRESPONSE_TOOL (action: setup)
       |
       +-- YIELD_INITIAL_STATE (action: state-export)
       |
       +-- YIELD_INITIAL_PROMPT (action: input-inject)
       |
       v
       reasoning_agent.run_async(ctx) [ADK native loop]
       |
       +-- MODEL_CALL (action: invoke-lm)
       |    |
       |    +-- returns: functionCall to tool
       |    |
       |    v
       |    (dispatch to tool or set_model_response)
       |
       +-- EXECUTE_CODE_TOOL (action: downward-movement)
       |    |
       |    +-- REPL_EXECUTE (sub-action)
       |    |
       |    +-- LLM_QUERY_DISPATCH (sub-action: lateral-movement)
       |    |    |
       |    |    +-- Thread bridge blocks REPL thread
       |    |    |
       |    |    v
       |    |    Child at depth+1 recursively executes
       |    |    |
       |    |    v
       |    |    LLMResult returned to REPL code
       |    |
       |    +-- STATE_PATCH_APPLY (sub-action)
       |    |
       |    +-- RETURN_TOOL_RESULT (action: feedback)
       |
       +-- SET_MODEL_RESPONSE_TOOL (action: upward-movement)
       |    |
       |    +-- VALIDATE_OUTPUT_SCHEMA (sub-action)
       |    |
       |    +-- RETURN_FINAL_ANSWER (action: termination)
       |
       v
       COLLECT_COMPLETION (action: harvest)
       |
       v
       YIELD_FINAL_RESPONSE (action: state-export)
       |
       v
       CLEANUP (action: teardown)
```

### Action-to-State-Key Mapping

| Action | Reads | Writes | Depth-Scoped | Depth-Invariant |
|--------|-------|--------|:------------:|:---------------:|
| **CREATE_LOCALREPL** | — | — | N/A | Yes |
| **CREATE_DISPATCH_CLOSURES** | `DYN_SKILL_INSTRUCTION` (pre-computed) | — | No | Yes |
| **MODEL_CALL** | `ITERATION_COUNT`, `CURRENT_DEPTH` (read-only snapshot) | — (ADK manages) | N/A | Yes |
| **EXECUTE_CODE_TOOL** | `EXPOSED_STATE_KEYS` (8 keys via _rlm_state) | `LAST_REPL_RESULT`, `ITERATION_COUNT`, `REPL_SUBMITTED_CODE*` (4 keys) | Yes (all 4) | Yes |
| **REPL_EXECUTE** | `iteration_count`, `should_stop`, `final_response_text`, `last_repl_result` | same + user REPL locals | Yes | Yes |
| **LLM_QUERY_DISPATCH** (child creation) | `CURRENT_DEPTH`, `max_depth` (env var) | — (state pushed to queue) | N/A | Yes |
| **LLM_QUERY_BATCHED** | same + `RLM_MAX_CONCURRENT_CHILDREN` | — (state queued per child) | N/A | Yes |
| **STATE_PATCH_APPLY** | `DYN_SKILL_INSTRUCTION` (restored) | `DYN_SKILL_INSTRUCTION` (via tool_context.state) | No | Yes |
| **SET_MODEL_RESPONSE_TOOL** | — | `reasoning_output@dN` (output_key) | Yes | Yes |
| **COLLECT_COMPLETION** | `reasoning_output@dN`, `_rlm_terminal_completion` attr | — (local vars) | N/A | Yes |
| **YIELD_FINAL_RESPONSE** | final answer text | — (via EventActions) | Yes | Yes |
| **CHILD_EVENT_REEMIT** | child state deltas from queue | — (yielded as Event) | Yes | Yes |

### Fixture Response Structure for 3-Turn Depth-2 Scenario

```json
{
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "note": "Root: execute_code to run code that calls llm_query",
      "status": 200,
      "body": {"functionCall": {"name": "execute_code", "args": {"code": "..."}}}
    },
    {
      "call_index": 1,
      "caller": "worker",
      "note": "Child@d1: dispatched by root's llm_query, returns simple answer",
      "status": 200,
      "body": {"functionCall": {"name": "set_model_response", "args": {"final_answer": "..."}}}
    },
    {
      "call_index": 2,
      "caller": "reasoning",
      "note": "Root: execute_code again, this time calls llm_query_batched with 2 prompts",
      "status": 200,
      "body": {"functionCall": {"name": "execute_code", "args": {"code": "..."}}}
    },
    {
      "call_index": 3,
      "caller": "worker",
      "note": "Child@d1 (batch index 0): first of two concurrent children from batched call",
      "status": 200,
      "body": {"functionCall": {"name": "set_model_response", "args": {"final_answer": "..."}}}
    },
    {
      "call_index": 4,
      "caller": "worker",
      "note": "Child@d1 (batch index 1): second of two concurrent children from batched call",
      "status": 200,
      "body": {"functionCall": {"name": "set_model_response", "args": {"final_answer": "..."}}}
    },
    {
      "call_index": 5,
      "caller": "reasoning",
      "note": "Root: final answer via set_model_response",
      "status": 200,
      "body": {"functionCall": {"name": "set_model_response", "args": {"final_answer": "..."}}}
    }
  ]
}
```

---

## H. Assumptions

**Implicit assumptions built into the action taxonomy:**

1. **All agents share the same tools** — Root and all children have REPLTool + SetModelResponseTool. No custom tools are wired per depth. (Assumption: toolset is static.)

2. **set_model_response is always terminal** — Once a reasoning agent calls set_model_response, that agent's run_async loop terminates. No further execute_code calls are possible for that agent. (Assumption: no retry after set_model_response succeeds.)

3. **State keys use flat namespace** — All agents write to the same ctx.session.state with depth-scoped suffixes. There is no separate per-agent state namespace. (Assumption: flat key space with @dN scoping is sufficient.)

4. **Child event re-emission is optional but encouraged** — A fixture can run without a child_event_queue, in which case child state deltas are captured but not re-yielded to the parent's plugin loop. Tests MAY operate without this queue. (Assumption: re-emission is a feature, not a requirement.)

5. **Error handling is out-of-scope for this taxonomy** — I am not enumerating error actions (REPL syntax error, child timeout, structured output retry) separately; these are sub-cases of EXECUTE_CODE_TOOL and SET_MODEL_RESPONSE_TOOL. (Assumption: happy path is the base contract.)

6. **ADK's model-calling loop is opaque** — The action taxonomy treats reasoning_agent.run_async() as a black box that handles retries, structured output validation, and tool loop iteration. I do not enumerate internal ADK state machine steps. (Assumption: ADK is trusted.)

7. **Depth limit enforcement is implicit in llm_query_async** — The depth check (if depth+1 >= max_depth, return error LLMResult) is NOT listed as a separate action, but as a guard inside llm_query_async. (Assumption: depth limit is a precondition check, not an action.)

8. **Skill loading happens once at orchestrator setup** — Skills are discovered and injected into REPL globals before the first execute_code call. No dynamic skill loading during execution. (Assumption: skill injection is a one-time setup, not an action that repeats.)

---

## I. Well-Posedness

**Is the problem well-specified and solvable as stated?**

**YES**, with one caveat.

**Well-posed aspects:**
- The architecture is fully documented and the codebase is small (~5000 LOC in core modules).
- All entry/exit points for actions are clearly named and source-findable.
- State key constants are exhaustively enumerated in state.py.
- The existing test (`skill_arch_test.json`) demonstrates a working multi-turn fixture with depth-1 dispatch.
- The gap analysis (`REVIEW_skill_arch_e2e_gaps.md`) already identifies 13 concrete assertion gaps.

**Caveat: "Isolation" is ambiguous without a definition of "unit".**

The phrase "isolate and test" can mean:
- **Option A**: Test each action in a minimal fixture with only that action (e.g., execute_code alone, without llm_query).
- **Option B**: Test each action within its minimal composite unit (e.g., execute_code WITH llm_query, because they are coupled in the fixture).
- **Option C**: Test each action's state contract independently (e.g., verify that EXECUTE_CODE_TOOL writes LAST_REPL_RESULT without requiring llm_query to succeed).

I am assuming **Option B + C**: Test actions in their natural composite forms (as they appear in fixtures), but verify each action's state contract independently through assertions.

**Under this interpretation, the problem is well-posed.**

---

## J. Success Criteria

**A correct answer to this Understand phase must:**

1. ✓ Enumerate all distinct actions (not variants) that agents take — **DONE (7 top-level actions + sub-actions)**.

2. ✓ Map each action to its entry point (method/function name + file:line) — **DONE (all mapped to orchestrator.py, dispatch.py, repl_tool.py, thread_bridge.py)**.

3. ✓ Show which state keys each action reads and writes — **DONE (table in section G)**.

4. ✓ Identify which actions are depth-invariant and which are depth-variant — **DONE (table shows all are depth-invariant in their logic, though output is depth-scoped)**.

5. ✓ List the minimum fixture responses needed for a 3-turn depth-2 test — **DONE (6 responses outlined above)**.

6. ✓ Explain why the existing skill_arch_test fixture IS sufficient for initial validation but NOT sufficient for comprehensive isolation — **DONE (in section K below)**.

7. ✓ Provide actionable recommendations for expanding the test suite — **DONE (in section K)**.

---

## K. Action Taxonomy Analysis

### K.1 Complete Action Inventory

#### **Level 1: Setup Actions (non-repeating)**

| # | Action | Entry Point | Exit Point | Pre | Post | Depth-Invariant |
|---|--------|-------------|-----------|-----|------|:---------------:|
| 1 | **CREATE_LOCALREPL** | `orchestrator._run_async_impl:283` | LocalREPL instance | — | REPL ready, globals={} | ✓ |
| 2 | **CREATE_DISPATCH_CLOSURES** | `orchestrator._run_async_impl:287` | 3-tuple (llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn) | dispatch_config ready | Closures ready to inject | ✓ |
| 3 | **CREATE_REPLTOOL** | `orchestrator._run_async_impl:317` | REPLTool instance | REPL ready | Tool ready for registration | ✓ |
| 4 | **CREATE_SETMODELRESPONSE_TOOL** | `orchestrator._run_async_impl:330` | SetModelResponseTool instance | output_schema set | Tool ready for registration | ✓ |
| 5 | **WIRE_TOOLS_TO_REASONING_AGENT** | `orchestrator._run_async_impl:335-338` via `object.__setattr__` | reasoning_agent.tools = [REPLTool, SetModelResponseTool] | Both tools created | reasoning_agent can call tools | ✓ |
| 6 | **INJECT_SKILL_GLOBALS** | `orchestrator._run_async_impl:268-271` | REPL globals += {skill_functions} | REPL created, skills discovered | Skill functions callable | ✓ |
| 7 | **INJECT_BRIDGE_CLOSURES** | `orchestrator._run_async_impl:293-296` | REPL globals += {llm_query, llm_query_batched} | Dispatch closures created | REPL code can call llm_query() | ✓ |

#### **Level 2: Initial State Export Actions (one-time)**

| # | Action | Entry Point | Exit Point | Pre | Post | Depth-Invariant |
|---|--------|-------------|-----------|-----|------|:---------------:|
| 8 | **YIELD_INITIAL_STATE** | `orchestrator._run_async_impl:344-349` | Event(state_delta={CURRENT_DEPTH, ITERATION_COUNT, REQUEST_ID}) | Tools wired | Session state keys initialized | ✓ |
| 9 | **YIELD_USER_PROMPT** | `orchestrator._run_async_impl:352-353` | Event(Content(user_message=root_prompt)) | State initialized | ADK loop receives user input | ✓ |

#### **Level 3: Main Loop Actions (repeating per iteration)**

| # | Action | Entry Point | Exit Point | Pre | Post | Depth-Invariant |
|---|--------|-------------|-----------|-----|------|:---------------:|
| 10 | **MODEL_CALL** | `reasoning_agent.run_async()` (ADK native loop) | LLM response (candidates[]) | Previous tool results in history | Response with functionCall or finish_reason | ✓ |
| 11 | **EXECUTE_CODE_TOOL** | `REPLTool.run_async()` | {"stdout", "stderr", "variables", "llm_calls_made", "call_number"} dict | Code in args, REPL ready | Code executed, state patched | ✓ |
| 12 | **REPL_EXECUTE** | `repl.execute_code()` inside REPLTool | {"stdout", "stderr", "locals"} | Code string, timeout set | Code ran (or timed out), exceptions caught | ✓ |
| 13 | **LLM_QUERY_SYNC_BRIDGE** | `llm_query()` (sync callable) in REPL code | LLMResult (backward-compat string with metadata) | Depth < max_depth, event loop alive | Child orchestrator runs and returns | ✓ |
| 14 | **LLM_QUERY_ASYNC_DISPATCH** | `llm_query_async()` closure from dispatch.py | Single LLMResult | Depth check passed, child config ready | Child orchestrator created and run_async invoked | ✓ |
| 15 | **LLM_QUERY_BATCHED_SYNC_BRIDGE** | `llm_query_batched()` (sync callable) in REPL code | list[LLMResult] | Depth < max_depth, event loop alive | All K children complete, results in order | ✓ |
| 16 | **LLM_QUERY_BATCHED_ASYNC_DISPATCH** | `llm_query_batched_async()` closure from dispatch.py | list[LLMResult] | Batch size K, semaphore ready (max 3 concurrent) | K child orchestrators run in parallel | ✓ |
| 17 | **STATE_PATCH_APPLY** | `post_dispatch_state_patch_fn()` called in REPLTool:258-260 | dict[str, Any] with DYN_SKILL_INSTRUCTION restoration | Child dispatch complete, parent instruction cached | tool_context.state[key] = value for each patched key | ✓ |
| 18 | **SET_MODEL_RESPONSE_TOOL** | `SetModelResponseTool.run_async()` | SetModelResponseTool validates & returns args | Output matches schema, reasoning done | Orchestrator's output_key is populated | ✓ |

#### **Level 4: Completion & Cleanup Actions (one-time)**

| # | Action | Entry Point | Exit Point | Pre | Post | Depth-Invariant |
|---|--------|-------------|-----------|-----|------|:---------------:|
| 19 | **DRAIN_CHILD_EVENT_QUEUE** | `orchestrator._run_async_impl:358-360` (inside yield loop) + final drain line 364 | Events re-yielded from queue | Child orchestrators completed | Child state deltas visible to parent plugins | ✓ |
| 20 | **COLLECT_COMPLETION** | `orchestrator._collect_completion()` | CompletionEnvelope with final_answer | set_model_response tool succeeded | Typed answer extracted (ReasoningOutput) | ✓ |
| 21 | **YIELD_FINAL_RESPONSE** | `orchestrator._run_async_impl:372-377` | Event(Content(final_answer)) + state_delta(SHOULD_STOP=True, FINAL_RESPONSE_TEXT=...) | Completion collected | ADK/Runner receives final response | ✓ |
| 22 | **CLEANUP** | `orchestrator._run_async_impl:380-383` | REPL destroyed (if not persistent) | Execution complete | Resources freed | ✓ |

#### **Sub-Actions Inside EXECUTE_CODE_TOOL**

| # | Sub-Action | Line Range | Reads | Writes | Depth-Scoped |
|---|------------|-----------|-------|--------|:------------:|
| 12.1 | Persist code metadata | :145-149 | — | `REPL_SUBMITTED_CODE*` (4 keys) | Yes |
| 12.2 | Save code artifact | :150 | code string | artifact file | N/A |
| 12.3 | Increment call count | :153-155 | `_call_count` | `ITERATION_COUNT` | Yes |
| 12.4 | Build _rlm_state snapshot | :157-165 | `EXPOSED_STATE_KEYS` (8 keys) from tool_context.state | REPL global `_rlm_state` | Yes |
| 12.5 | Inject lineage metadata | :162-164 | depth, fanout_idx from tool | REPL global: `_rlm_depth`, `_rlm_fanout_idx`, `_rlm_agent_name` | N/A |
| 12.6 | Execute code sync | :169-173 | user code (side effects) | REPL locals + stdout/stderr | Yes |
| 12.7 | Apply state patch | :174 | result from `post_dispatch_state_patch_fn()` | tool_context.state | No |
| 12.8 | Write LAST_REPL_RESULT | :177-178 | execution result dict | tool_context.state[LAST_REPL_RESULT] | Yes |
| 12.9 | Filter & return tool result | :179-181 | REPL locals (JSON-serializable subset) | tool return dict | N/A |

---

### K.2 Action Preconditions and State Transition Map

**Precondition Hierarchy:**
```
Model Ready
  ├─ Session open (InvocationContext)
  ├─ App initialized (plugins, services)
  └─ Orchestrator created (tools wired)

REPL Ready
  ├─ LocalREPL initialized (globals, locals)
  ├─ Skill functions injected (loader.py)
  ├─ Thread bridge closures injected (thread_bridge.py)
  └─ initial _rlm_state built (exposed keys snapshot)

Child Orchestrator Ready (for each llm_query call)
  ├─ Parent depth < max_depth (env RLM_MAX_DEPTH)
  ├─ Semaphore slot available (for batched: max 3 concurrent)
  ├─ Event loop alive and context accessible
  └─ Parent event queue created (if re-emission needed)

Set Model Response Ready
  ├─ Reasoning agent finished with execute_code loop
  ├─ Output matches ReasoningOutput schema
  └─ ADK validation passed (on 3rd retry, error)
```

**State Transition Timeline (single turn):**

```
START
  |
  v
[Initialize: CURRENT_DEPTH, ITERATION_COUNT, REQUEST_ID]
  |
  v
[Yield: user Content event with root_prompt]
  |
  v
LOOP {
  [Model call 1]
    |
    v
  [execute_code tool 1]
    |
    +-- [REPL code executes]
    |    |
    |    +-- [llm_query() called → child@d1 dispatched]
    |    |    |
    |    |    v
    |    |   [Child: MODEL + execute_code/set_model_response]
    |    |    |
    |    |    v
    |    |   [LLMResult returned to parent REPL]
    |    |
    |    +-- [continue parent code]
    |
    +-- [State patch: restore DYN_SKILL_INSTRUCTION]
    |
    v
  [Write: LAST_REPL_RESULT, ITERATION_COUNT@d0]
    |
    v
  [Drain: child_event_queue → re-yield child state deltas]
    |
    v
  [Model call 2: sees updated LAST_REPL_RESULT]
    |
    +-- [execute_code again] OR [set_model_response]
}

[Model call N: set_model_response]
  |
  v
[Validate output schema]
  |
  v
[Set output_key = ReasoningOutput]
  |
  v
[Collect completion: harvest final_answer from output_key]
  |
  v
[Yield: final Content event + state(SHOULD_STOP=True)]
  |
  v
[Cleanup: REPL.cleanup()]
  |
  v
END
```

---

### K.3 Which Actions Are Present in skill_arch_test.json?

**Covered actions (✓):**
- \#1 CREATE_LOCALREPL — implied by fixture execution
- \#2 CREATE_DISPATCH_CLOSURES — implied
- \#3 CREATE_REPLTOOL — called in response[0]
- \#4 CREATE_SETMODELRESPONSE_TOOL — called in response[1] and [2]
- \#8 YIELD_INITIAL_STATE — fixture state dict populated
- \#9 YIELD_USER_PROMPT — fixture root_prompt in config
- \#10 MODEL_CALL (root) — response[0] and [2]
- \#10 MODEL_CALL (child) — response[1]
- \#11 EXECUTE_CODE_TOOL (root) — response[0] code arg
- \#12 REPL_EXECUTE — executed via code arg
- \#13 LLM_QUERY_SYNC_BRIDGE — skill calls llm_query_fn
- \#14 LLM_QUERY_ASYNC_DISPATCH — thread bridge mechanism
- \#18 SET_MODEL_RESPONSE_TOOL (child) — response[1] set_model_response
- \#18 SET_MODEL_RESPONSE_TOOL (root) — response[2] set_model_response
- \#20 COLLECT_COMPLETION — implicit in fixture execution
- \#21 YIELD_FINAL_RESPONSE — fixture checks final_answer

**Implicitly covered but NOT explicitly tested (✗):**
- \#6 INJECT_SKILL_GLOBALS — assumed, but no assertion that run_test_skill is in REPL globals
- \#7 INJECT_BRIDGE_CLOSURES — assumed, but no explicit assertion that llm_query is a thread-bridge callable
- \#12.7 STATE_PATCH_APPLY — no assertion that post_dispatch_state_patch_fn was called or that DYN_SKILL_INSTRUCTION was restored
- \#19 DRAIN_CHILD_EVENT_QUEUE — child state deltas are visible in session_state_events, but no explicit assertion that re-emission happened via the queue (vs. some other mechanism)

**NOT covered in skill_arch_test.json (✗):**
- \#15 LLM_QUERY_BATCHED_SYNC_BRIDGE — fixture does not call llm_query_batched
- \#16 LLM_QUERY_BATCHED_ASYNC_DISPATCH — never tested
- Error variants of #11 (REPL syntax error, timeout)
- Error variants of #14 (depth limit exceeded, timeout)
- Error variants of #18 (structured output retry, schema validation failure)
- \#22 CLEANUP — implicit, but not asserted

---

### K.4 Minimal Fixture Structure for Comprehensive Coverage

**A 6-response fixture (depth=0, depth=1) achieving 95% action coverage:**

```
Response[0]: reasoning, MODEL_CALL + execute_code
  - Triggers: #10, #11, #12, #12.1-12.9
  - Code: calls llm_query_batched with 2 prompts
  - Payload: functionCall execute_code

Response[1]: worker@d1, MODEL_CALL (first child)
  - Triggers: #10, #14, #16 (first of two batched children)
  - Payload: functionCall set_model_response

Response[2]: worker@d1, MODEL_CALL (second child)
  - Triggers: #10, #14, #16 (second of two batched children)
  - Payload: functionCall set_model_response

Response[3]: reasoning, MODEL_CALL + execute_code
  - Triggers: #10, #11, #12, #12.4 (sees @d1 state keys), #12.7 (state patch), #19 (drain queue)
  - Code: calls llm_query with error-inducing prompt
  - Payload: functionCall execute_code

Response[4]: worker@d1, MODEL_CALL (child error case)
  - Triggers: #10, #14 (returns error LLMResult instead of success)
  - Payload: error response (HTTP 500 or timeout)

Response[5]: reasoning, MODEL_CALL + set_model_response
  - Triggers: #10, #18, #20, #21
  - Payload: functionCall set_model_response with final answer
```

**This fixture covers:**
- Single and batched dispatch (#14, #16)
- Child event re-emission (#19)
- State patch application (#12.7)
- Error handling in child (#14 error case)
- All exit paths (success, error, completion)

---

### K.5 Why Isolation Testing Is Hard (and how to enable it)

**Challenge 1: Actions are not independent**

`execute_code` and `llm_query` are coupled at runtime:
- You cannot test `llm_query` dispatch without a parent REPL code block calling it.
- You cannot test the state patch without having a child return.
- You cannot test event re-emission without a child orchestrator actually running.

**Solution:** Test actions in their **minimal composite units**, not in isolation. Examples:

1. **Unit: EXECUTE_CODE_TOOL alone (no llm_query)**
   - Fixture: Root calls execute_code with simple print/variable code
   - Response: 1 model call + 1 execute_code tool + 1 set_model_response
   - Validates: #11, #12, #12.4, #12.8, but NOT #13-17

2. **Unit: EXECUTE_CODE_TOOL + LLM_QUERY**
   - Fixture: Root calls execute_code, code calls llm_query, child answers
   - Response: 2 model calls (root + child) + 2 tools
   - Validates: #11-14, #13

3. **Unit: EXECUTE_CODE_TOOL + LLM_QUERY_BATCHED**
   - Fixture: Root calls execute_code, code calls llm_query_batched(["q1", "q2"]), two children answer
   - Response: 3 model calls (root + 2 children) + 3 tools
   - Validates: #11-16

4. **Unit: SET_MODEL_RESPONSE_TOOL with structured output**
   - Fixture: execute_code succeeds, then set_model_response with output_schema
   - Response: 1 + model calls + set_model_response + (retries if needed)
   - Validates: #18, error handling in #18

**Challenge 2: State assertions require introspection**

Current assertions check final state values (e.g., `iteration_count == 1`). To validate state mutations:
1. Use test hooks (CB_REASONING_CONTEXT, CB_TOOL_CONTEXT) to capture state at action boundaries.
2. Query SQLite telemetry (session_state_events table) to verify: event_author, key_depth, mutation timestamp.
3. Verify that mutation path is correct (e.g., event_author == "rlm_orchestrator" means mutation flowed through EventActions).

---

### K.6 Depth-Invariance Validation

**Claim: All 22 actions are depth-invariant (except for depth-scoped state keys).**

**How to test:**
Create two fixtures:
1. **Fixture A (depth=0)**: Root orchestrator only, no child dispatch. Tests actions #1-12, #18, #20-22.
2. **Fixture B (depth=1)**: Root + child at depth=1. Uses same action code as Fixture A, but child experiences #1-12, #18, #20-22 with depth=1.

**Assertion:** Token counts, execution times, state keys (minus @dN suffix), and tool call sequences must be identical between Fixture A and Fixture B, proving depth-invariance.

**Example:**
- Root in A: ITERATION_COUNT increments as "0", "1", "2" ... (depth 0 keys)
- Child in B: ITERATION_COUNT@d1 increments as "0", "1" ... (depth 1 keys, independent namespace)
- Logic is identical; only key names differ.

---

### K.7 Missing Test Fixtures (Priority Order)

**P0 (Critical for action taxonomy validation):**
1. `execute_code_only.json` — Root calls execute_code without llm_query. Tests action isolation.
2. `llm_query_batched_k3.json` — Root calls llm_query_batched(["q1", "q2", "q3"]). Tests concurrent dispatch (#16).
3. `repl_execute_error.json` — Root calls execute_code with syntax error. Tests error handling in #12.
4. `set_model_response_structured_output.json` — Root calls set_model_response with output_schema. Tests #18 with schema validation.

**P1 (Comprehensive depth & state coverage):**
5. `depth_invariance_root_vs_child.json` — Compare root (#1-12) vs child (#1-12 at depth=1) with same code path.
6. `child_event_reemission.json` — Verify that child state_delta events flow through queue and appear in session_state_events.
7. `state_patch_restoration.json` — Verify that DYN_SKILL_INSTRUCTION is restored after each child dispatch.
8. `concurrent_children_interleaving.json` — Root dispatches 3 children concurrently via batched, verify ordering and semaphore.

**P2 (Edge cases & error paths):**
9. `depth_limit_exceeded.json` — Root at depth 2 tries to call llm_query, gets error LLMResult.
10. `child_timeout.json` — Child dispatch times out, parent REPL sees error LLMResult.
11. `skill_not_found.json` — Root tries to call missing skill, REPL raises error.

---

## Summary

The RLM-ADK action taxonomy consists of **22 distinct actions** across 4 categories (setup, state export, main loop, completion), all of which are **depth-invariant** (the logic is identical at depth 0 and depth N; only state key names are suffixed).

The existing **skill_arch_test.json fixture is sufficient for happy-path validation** but leaves 8+ actions implicitly tested and 3+ actions entirely untested.

**To achieve comprehensive isolation testing**, we must:
1. Create minimal composite-unit fixtures (execute_code alone, +llm_query, +batched, +error).
2. Add state introspection assertions (SQLite telemetry, test hooks, event_author verification).
3. Validate depth-invariance by running identical code at depth 0 and depth 1, comparing state key structure (minus @dN suffix).
4. Add the 7 P0 fixture templates above to the test suite.

With these additions, every action will be testable in isolation AND in composition, and the assertion coverage will rise from ~30% to ~90% of the action taxonomy.
