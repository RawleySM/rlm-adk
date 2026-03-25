# Issues/Test_Skill/Understand_3_AntihackProof.md

## A. Restatement

**Core Task:** Design a non-reward-hacking test that validates the skill architecture e2e (depth=0 → depth=1 → depth=2), where every assertion can ONLY pass if the real pipeline actually executed. Currently, the test observes many outputs but asserts on few, and several assertions check default dict values rather than pipeline-produced values.

**User's Goal:** "ALL proven to work with real key and variable reads via callbacks, REPL print(), and clearly visible in stdout" — every passing assertion must be traceable to a real execution artifact that cannot be spoofed by pre-seeding or default values.

---

## B. Target

Design the expanded skill_arch_test fixture and assertion strategy such that:

1. **Every assertion maps to a non-fakeable output signal** that can only exist if the pipeline executed correctly
2. **A proof chain** links depth=0 → depth=1 → depth=2 execution, where each depth's output feeds into the next depth's input
3. **Reward-hacking vulnerabilities are cataloged** and eliminated (e.g., dict.get() defaults masquerading as state values)
4. **Observable signals are exhaustive**, covering: REPL stdout/print(), callback state reads, SQLite telemetry, and fixture response progression
5. **Fixture design prevents pre-seeding tricks**, using nonces and state transforms that cannot be pre-computed

---

## C. Givens

### From CLAUDE.md and Architecture Docs

1. **Three Directional Flows:**
   - **Downward:** Reasoning Agent → execute_code → REPL code
   - **Lateral:** REPL code → llm_query() (thread bridge) → child orchestrator → result
   - **Upward:** Reasoning Agent → set_model_response → typed response

2. **Thread Bridge (Replaced AST Rewriter):**
   - `llm_query()` is a real sync callable via `run_coroutine_threadsafe()`
   - No AST transformation; closures are injected at runtime
   - Sync REPL code calls async child orchestrators transparently

3. **Depth Scoping (depth_key):**
   - `depth_key("iteration_count", 0)` → `"iteration_count"`
   - `depth_key("iteration_count", 1)` → `"iteration_count@d1"`
   - Child state isolated via `@dN` suffix

4. **State Mutation Discipline (AR-CRIT-001):**
   - Only ADK-tracked channels: `tool_context.state`, `EventActions(state_delta={})`, callback context
   - `ctx.session.state` writes in dispatch closures = silent loss (never persisted)

5. **Observability Pipeline:**
   - **SqliteTracingPlugin:** traces (1 row), telemetry (per call), session_state_events (per key change)
   - **REPLCapturePlugin:** submitted code, REPL globals, stdout/stderr per tool call
   - **InstrumentationPlugin** (in test harness): [PLUGIN:hook:agent:key=value] tags, [TIMING:...] tags
   - **Child Event Re-Emission:** Child state changes pushed to `child_event_queue`, drained by parent, re-emitted with `rlm_child_event=True` metadata

### From REVIEW Gap Analysis

1. **Current Test Gaps:**
   - Gap A1: `set_model_response` tool calls not asserted (only `execute_code` checked)
   - Gap B1: `execution_mode` assertion uses `oneof ["async_rewrite", "thread_bridge"]` — accepts deleted AST rewriter
   - Gap B2: Thread bridge not validated via runtime behavior (hardcoded in skill source)
   - Gap B3: Child event re-emission unasserted (session_state_events has `key_depth > 0` rows but not checked)
   - Gap C3: Depth-scoped keys observed but not asserted
   - Gap D1: `repl_did_expand` never observed as `True` (dead signal)
   - Gap D2: `should_stop` at model_call_1 checks dict.get() default, not a pipeline value
   - Gap E1: Child dispatch count unasserted
   - Gap F1-F3: REPL trace, skill expansion, token accounting unasserted

2. **Fixture Pre-Seeding:**
   - `user_provided_ctx`, `repo_url`, `root_prompt`, `test_context`, `skill_instruction` pre-seeded
   - These are **input configuration**, not output values (acceptable)
   - But test never validates they flow through the pipeline (PATH B context injection)

### From Test Skill Code (skill.py)

1. **What the Test Skill Emits:**
   - `_rlm_state` inspection (depth, agent name, iteration_count, should_stop, current_depth, state_keys_count)
   - `execution_mode = "thread_bridge"` (hardcoded, not detected)
   - `calling_llm_query = True` (before dispatch)
   - `child_result_preview` (returned value from child)
   - `thread_bridge_latency_ms` (time.perf_counter() delta)
   - `COMPLETE = True` (if no exception)

2. **What It Does NOT Emit:**
   - Runtime detection of thread bridge (would require threading.current_thread().name)
   - Verification that skill globals were injected (no self-introspection of REPL namespace)
   - Confirmation that llm_query_fn is the real thread-bridge closure (just checks type)

---

## D. Conditions

**Constraints:**

1. **Real-only outputs:** No pre-seeded default values
2. **Depth-linked proof chain:** d0 output → d1 input → d1 output → d2 input → d2 output
3. **Observable in stdout/SQLite:** Every assertion must map to a captured output
4. **Fixture responses locked:** Cannot modify; must work with provider-fake 3-response pattern
5. **No state mutation violations:** All assertions flow through tracked channels only
6. **Skill loading must be proven:** Not just assumed from imports

**Success Conditions:**

- Fixture + assertion strategy collectively prove:
  - `execute_code` was called (downward flow)
  - `llm_query()` thread bridge was invoked (lateral flow)
  - Child orchestrator ran at depth=1 (depth scoped state)
  - Child's `set_model_response` was executed (upward flow, child level)
  - Parent received child's result and called `set_model_response` (upward flow, root level)
  - All mutations were via ADK-tracked channels
  - Skill loading injected the correct globals
  - No reward-hackable assertions

---

## E. Unknowns

1. **Can execution mode be detected at runtime** without modifying the skill source?
   - Answer: Yes, via `threading.current_thread().name` emitted inside skill
   - Or: Via custom decorator injected by loader that wraps the function with runtime detection

2. **Should child depth-scoped keys be in fixture response(s)?**
   - Answer: No — child state is produced by dispatch pipeline, not pre-seeded
   - These are observed via session_state_events (re-emitted by child event queue)

3. **How to prove skill loading without reading REPL globals directly?**
   - Answer: Via REPL stdout — skill code that calls injected functions will only work if they were loaded

4. **What makes a valid depth=2 nonce to prove three-depth execution?**
   - Answer: A value generated at d0, transformed at d1, transformed again at d2, returned to parent for final assertion
   - Cannot be pre-computed because transformations happen inside child orchestrators

---

## F. Definitions

**Key Terms (Clarified):**

| Term | Definition | Contextual Use |
|------|-----------|-----------------|
| **Reward-hacking** | An assertion that passes when the pipeline is broken (e.g., checks a dict.get() default instead of a real state value) | Gap D2: `should_stop` checks default `False`, not a pipeline-written value |
| **Observable Signal** | A value that ONLY appears in stdout, state_delta, or SQLite if the pipeline executed that step | child_result_preview can only exist if child orchestrator ran and returned a value |
| **Proof Chain** | Linked outputs where d0 → d1 → d2, with d1 depending on d0's output and d2 depending on d1's output | Nonce generation, transformation, and re-assertion forms the chain |
| **Pre-seeded vs Pipeline-Produced** | Pre-seeded: provided in fixture initial_state; Pipeline-produced: created by orchestrator/tool/callback execution | `repo_url` is pre-seeded; `iteration_count` is pipeline-produced (incremented by REPLTool) |
| **Tracked Channel** | ADK event stream: tool_context.state, EventActions(state_delta), callback context; prevents silent loss | All assertions must source from tracked channels per AR-CRIT-001 |
| **Depth-Scoped Key** | State key with `@dN` suffix at depth N > 0 to isolate child state from parent | `current_depth@d1=1` vs `current_depth=0` proves distinct execution contexts |

---

## G. Representation

### Proof Chain Diagram (Depth 0 → 1 → 2)

```
┌─────────────────────────────────────────────────────────────────┐
│ DEPTH 0: Root Orchestrator + Skill                              │
├─────────────────────────────────────────────────────────────────┤
│ 1. REPLTool increments iteration_count: 0 → 1                   │
│ 2. Injects _rlm_state (depth=0, iteration_count=1)              │
│ 3. Test Skill emits [TEST_SKILL:depth=0]                        │
│ 4. Test Skill generates NONCE_0 = sha256(uuid4())               │
│ 5. Test Skill calls llm_query(child_prompt + NONCE_0)           │
│    └─> Thread bridge dispatches to child                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (thread bridge)
┌─────────────────────────────────────────────────────────────────┐
│ DEPTH 1: Child Orchestrator + Child Skill                       │
├─────────────────────────────────────────────────────────────────┤
│ 1. REPLTool increments iteration_count@d1: 0 → 1                │
│ 2. Injects _rlm_state (depth=1, iteration_count=1)              │
│ 3. Child Skill receives NONCE_0 in prompt, extracts it          │
│ 4. Child Skill generates NONCE_1 = transform(NONCE_0)           │
│ 5. Child Skill calls llm_query(child2_prompt + NONCE_1)         │
│    └─> Thread bridge dispatches to grandchild                   │
│ 6. Child Skill emits [TEST_SKILL:depth=1]                       │
│ 7. Child Skill returns ChildSkillResult with NONCE_1 embedded   │
│ 8. Child's set_model_response called with result                │
│    └─> final_answer contains NONCE_1                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (llm_query returns)
┌─────────────────────────────────────────────────────────────────┐
│ DEPTH 2: Grandchild Orchestrator                                │
├─────────────────────────────────────────────────────────────────┤
│ 1. REPLTool increments iteration_count@d2: 0 → 1                │
│ 2. Injects _rlm_state (depth=2, iteration_count=1)              │
│ 3. Grandchild Skill receives NONCE_1 in prompt, extracts it     │
│ 4. Grandchild Skill generates NONCE_2 = transform(NONCE_1)      │
│ 5. Grandchild Skill emits [TEST_SKILL:depth=2]                  │
│ 6. Grandchild Skill returns GrandchildSkillResult with NONCE_2  │
│ 7. Grandchild's set_model_response called with result           │
│    └─> final_answer contains NONCE_2                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (llm_query returns)
┌─────────────────────────────────────────────────────────────────┐
│ DEPTH 1: RESUMPTION (after child returns)                       │
├─────────────────────────────────────────────────────────────────┤
│ 1. Child Skill receives NONCE_2 from grandchild                 │
│ 2. Child Skill calls llm_query(final_check + NONCE_2)           │
│    └─> Should hit depth limit (d2 + 1 >= max_depth=3)           │
│    └─> Returns error LLMResult instead of spawning d3           │
│ 3. Child Skill detects depth limit error                        │
│ 4. Child Skill re-calls set_model_response with NONCE_2 hash    │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (returns to d0)
┌─────────────────────────────────────────────────────────────────┐
│ DEPTH 0: RESUMPTION (after child returns)                       │
├─────────────────────────────────────────────────────────────────┤
│ 1. Test Skill receives child_result (contains NONCE_1)          │
│ 2. Test Skill validates NONCE_1 (should be transform(NONCE_0))  │
│ 3. Test Skill generates NONCE_1_HASH = sha256(NONCE_1)          │
│ 4. Test Skill calls llm_query(audit_prompt + NONCE_1_HASH)      │
│ 5. Test Skill emits [TEST_SKILL:child_nonce_hash_match=<bool>]  │
│ 6. Test Skill calls set_model_response with final_result        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘

ASSERTIONS ON PROOF CHAIN:
✓ depth=0 state key exists (iteration_count=1)
✓ depth=1 state key exists (iteration_count@d1=1)
✓ depth=2 state key exists (iteration_count@d2=1)
✓ NONCE_0 generated at d0
✓ NONCE_1 generated at d1, derived from NONCE_0
✓ NONCE_2 generated at d2, derived from NONCE_1
✓ NONCE_2 returned from child (in child_result)
✓ NONCE_1 hash returned from parent (in final_answer)
✓ Depth limit error detected at d1 when attempting d3
```

---

## I. Well-Posedness

**The problem as stated is well-posed:**

- **Sufficient information:** Fixture structure, REVIEW analysis, and skill code are fully available
- **Unique solution:** Proof chain design with nonces is unambiguous and unfakeable
- **Consistent constraints:** No contradictions between "real-only outputs" and "observable in stdout/SQLite"
- **Solvable in scope:** Can be implemented without breaking provider-fake design or ADK contract

---

## J. Success Criteria

**Test passes if and only if:**

1. Contract test passes (fixture responses + skill execution correct)
2. **All three depths observed:**
   - `[TEST_SKILL:depth=0]` in d0 REPL stdout
   - `[TEST_SKILL:depth=1]` in d1 session_state_events (child event re-emission)
   - `[TEST_SKILL:depth=2]` in session_state_events or SQLite telemetry
3. **Proof chain validated:**
   - NONCE_0 generated, printed at d0
   - NONCE_1 (transform of NONCE_0) generated at d1, returned to d0
   - NONCE_2 (transform of NONCE_1) generated at d2, returned to d1, returned to d0
   - Hash(NONCE_1) matches Hash(child_result from d1)
4. **State keys depth-scoped:**
   - `iteration_count=1` at d0
   - `iteration_count@d1=1` at d1
   - `iteration_count@d2=1` at d2
5. **All mutations tracked:**
   - No state writes bypass `tool_context.state` or `EventActions(state_delta={})`
   - SQLite session_state_events has rows with correct `event_author` values
6. **Zero reward-hackable assertions:**
   - No checks on dict.get() defaults
   - No pre-seeded value comparisons
   - All assertions source from pipeline-produced outputs

---

## K. Anti-Reward-Hacking Analysis

### K.1 Assertion Strength Classification

**Table: Every Assertion → Proof Strength → Unfakeable Properties**

| Assertion | Current Strength | Proof Type | What Makes It Unfakeable | Can Be Faked? | Recommendation |
|-----------|------------------|-----------|--------------------------|---------------|-----------------|
| `depth=0` in TEST_SKILL | MEDIUM | Introspection | Must come from _rlm_state, which is injected fresh at each tool call | No* | Strengthen: Require hash of depth+uuid to match response |
| `iteration_count=1` at d0 | MEDIUM | State read | REPLTool increments counter, not pre-seeded | Unlikely | Strengthen: Assert incremental progression (0→1) |
| `execution_mode="thread_bridge"` | **WEAK** | Hardcoded string | Skill source has literal `execution_mode = "thread_bridge"` at line 87 | **YES** | **Fix: Detect at runtime via threading.current_thread().name** |
| `calling_llm_query=True` | STRONG | Execution flow | Printed immediately before llm_query() call; if not printed, skill error | No | Keep as-is |
| `child_result_preview` contains text | STRONG | Dispatch proof | Can only appear if child orchestrator executed and returned a value | No | Keep as-is |
| `thread_bridge_latency_ms > 0` | STRONG | Timing proof | Measured via time.perf_counter() delta; cannot be pre-computed | No | Keep as-is |
| `repl_did_expand=False` at model_call_1 | **FAKE** | Default value | Reads from dict.get("repl_did_expand", False); default is used, not pipeline value | **YES** | **Remove or fix: Skill should set this to True after expansion** |
| `should_stop=False` at model_call_1 | **FAKE** | Default value | Reads from dict.get("should_stop", False); no value written by pipeline yet | **YES** | **Remove: Assertion checks default parameter, not pipeline output** |
| `iteration_count@d1=1` (child scoped) | STRONG | Depth isolation | Can only exist if child orchestrator ran at depth=1 and REPLTool incremented | No | Add to assertions (currently missing) |
| `current_depth@d1=1` (child scoped) | STRONG | Depth isolation | Proves child state had correct depth value injected | No | Add to assertions (currently missing) |
| `set_model_response` tool call for child | STRONG | Upward flow | Proves child returned typed response, not string fallback | No | Add to assertions (currently missing) |
| `max_depth_reached=1` in SQLite traces | STRONG | Depth reached | Computed from telemetry rows; cannot be pre-seeded | No | Add to assertions (currently missing) |
| `artifact_saves >= 1` in SQLite traces | MEDIUM | Artifact tracking | Should be 1 (code artifact), but depends on plugin firing | Maybe | Add to assertions, but mark as observability-dependent |
| `tool_invocation_summary` in SQLite | STRONG | Tool count | Tally of execute_code and set_model_response counts; must match execution | No | Add to assertions (currently missing) |

**Legend:**
- **STRONG:** Cannot pass without real pipeline execution
- **MEDIUM:** Probably real, but indirect (depends on intermediate layer)
- **WEAK:** Checks code constant, not behavior
- **FAKE:** Checks default value or pre-seeded config, not pipeline output

---

### K.2 Current Reward-Hacking Vulnerabilities

**Gap D2 (CRITICAL):** The assertion `should_stop=False` at phase `model_call_1` checks:
```python
callback_context.state.get("should_stop", False)
```
The `False` comes from the `get()` default parameter, NOT from a pipeline-written value. At model_call_1 (before any tool runs), the key `"should_stop"` has never been written. This assertion would pass even if the entire state mutation pipeline failed, because the default argument masks the failure.

**Remediation:** Remove this assertion or replace with a post-REPL check when `should_stop` has actually been set by the orchestrator (after first iteration).

**Gap D1 (CRITICAL):** The `repl_did_expand` key is never observed as `True` in the showboat demo. The consolidated plan claims "Skill source expansion" is validated by `repl_did_expand == True`, but this key appears to:
- Only be set by source-expansion codepath (deleted)
- Never be set by module-import loader (current architecture)

**Remediation:** Either (a) remove the assertion, or (b) add explicit skill code that sets this key when expansion would have occurred (for semantic continuity).

**Gap B1 (HIGH):** The `execution_mode` assertion uses:
```python
operator="oneof", expected=["async_rewrite", "thread_bridge"]
```
This accepts the deleted AST rewriter path. Since `execution_mode` is hardcoded in skill source as the literal string `"thread_bridge"`, the assertion would pass even if:
- The thread bridge is completely broken
- The skill code compiles and runs
- No actual async dispatch occurs

**Remediation:** Change to `operator="eq", expected="thread_bridge"` (strict). Better: Modify skill to detect thread bridge at runtime (see below).

**Gap A1 (MEDIUM):** No assertion for `set_model_response` tool calls (only `execute_code` checked). The upward flow is validated via observing the final_answer in contract test, but there's no explicit lineage assertion that the tool was called.

**Remediation:** Add `PluginHookExpectation` for `before_tool:reasoning_agent:tool_name=set_model_response` and `before_tool:child_reasoning_d1:tool_name=set_model_response`.

---

### K.3 Observable Proof Signals by Depth

**Depth 0 (Root):**

| Signal | Source | Observation Method | Proof Value | Can Be Faked? |
|--------|--------|-------------------|------------|---------------|
| iteration_count=1 injected | REPLTool._call_count | [TEST_SKILL:iteration_count=1] | Proves REPLTool.run_async executed | No (requires tool run) |
| depth=0 in _rlm_state | REPLTool._rlm_depth field | [TEST_SKILL:depth=0] | Proves REPL got state injection | No |
| child_result returned | llm_query_fn() | [TEST_SKILL:child_result_preview=...] | Proves child executed and returned | No (fake provider does it, but result must match response) |
| REPL stdout emitted | print() in skill | Captured in run_result.repl_stdout | Proves code ran to completion | No |
| artifact saved | orchestrator → save_artifact | SQLite traces.status="completed" | Proves artifact pipeline ran | No (plugin fires at end) |
| final_answer set | set_model_response tool | run_result.contract.final_answer | Proves upward flow | No (contract verifies this) |

**Depth 1 (Child):**

| Signal | Source | Observation Method | Proof Value | Can Be Faked? |
|--------|--------|-------------------|------------|---------------|
| Child agent executed | dispatch._run_child() | [PLUGIN:before_agent:child_orchestrator_d1:...] | Proves child orch created | No (dispatch runs it) |
| iteration_count@d1=1 in state | Child REPLTool._call_count | session_state_events key_depth=1 | Proves child REPL ran | No (re-emitted by queue) |
| current_depth@d1=1 in state | Child REPLTool._rlm_depth | session_state_events key_depth=1 | Proves depth scoping worked | No |
| Child REPL stdout | print() in child skill code | Embedded in child's final_answer | Proves child code executed | No (fake provider returns it in response[1]) |
| Child's set_model_response | Child reasoning agent | [PLUGIN:before_tool:child_reasoning_d1:...] | Proves upward flow at d1 | No |

**Depth 2 (Grandchild):**

| Signal | Source | Observation Method | Proof Value | Can Be Faked? |
|--------|--------|-------------------|------------|---------------|
| iteration_count@d2 in state | Grandchild REPLTool | SQLite telemetry event_type=tool_call depth=2 | Proves d2 REPL executed | No (would need 4th response) |
| current_depth@d2=2 | Grandchild state injection | SQLite session_state_events key_depth=2 | Proves d2 depth scoped correctly | No |
| max_depth_reached=2 in traces | Plugin post-run | SQLite traces.max_depth_reached | Proves d2 was deepest depth | No (computed from telemetry) |

---

### K.4 Proposed Proof Chain (Nonce Pattern)

**Goal:** Create a chain where d0 → d1 → d2 → d1 → d0, with each hop transforming and validating a nonce that cannot be pre-computed.

**Fixture Modification (responses only):**

1. **Response[0]** (d0 model call): No change needed
2. **Response[1]** (d1 model call): Add `nonce_at_d1` to child skill output (generated at d1 from d0's nonce)
3. **Response[2]** (d0 model call again, after child returns): No change (just set_model_response)
4. **(Optional) Response[3]** (d2 model call): If we want d2 execution, add 4th response with d2 skill generating nonce_at_d2

**Skill Code Modifications:**

**At Depth 0:**
```python
# Generate unique nonce that child must receive and transform
nonce_d0 = hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]
_tag("nonce_d0", nonce_d0)

# Include in child prompt
child_prompt = f"...Execute skill with nonce={nonce_d0}..."
child_result = llm_query_fn(child_prompt)

# Validate d1 nonce is derived from d0 nonce
if "nonce_at_d1=" in str(child_result):
    nonce_d1_from_child = extract_nonce(str(child_result))
    expected_d1_nonce = sha256(nonce_d0 + "d1_transform").hexdigest()[:16]
    _tag("nonce_chain_valid", nonce_d1_from_child == expected_d1_nonce)
```

**At Depth 1 (Child Skill):**
```python
# Extract d0 nonce from prompt
nonce_d0 = extract_from_prompt(prompt, "nonce=")
_tag("received_nonce_d0", nonce_d0)

# Transform it (this proves we received and processed d0's value)
nonce_d1 = sha256(nonce_d0 + "d1_transform").hexdigest()[:16]
_tag("nonce_at_d1", nonce_d1)

# Optionally dispatch to d2 with d1 nonce
child_d2_result = llm_query_fn(f"...nonce={nonce_d1}...")

# Return d1 nonce in result so d0 can verify chain
return ChildSkillResult(nonce=nonce_d1, ...)
```

**At Depth 2 (Optional, Grandchild Skill):**
```python
# Same pattern
nonce_d1_received = extract_from_prompt(prompt, "nonce=")
nonce_d2 = sha256(nonce_d1_received + "d2_transform").hexdigest()[:16]
_tag("nonce_at_d2", nonce_d2)
return GrandchildSkillResult(nonce=nonce_d2, ...)
```

**Assertions on Proof Chain:**
```python
# These would be StateKeyExpectation or TestSkillExpectation entries
- [TEST_SKILL:nonce_d0] present (d0)
- [TEST_SKILL:received_nonce_d0] matches nonce_d0 (d1 received d0's value)
- [TEST_SKILL:nonce_at_d1] matches transform(nonce_d0) (d1 transformed correctly)
- [TEST_SKILL:child_result_nonce] in final answer matches nonce_at_d1 (chain closed)
- [TEST_SKILL:nonce_chain_valid=True] (d0 validated the chain)
```

**Why Unfakeable:**
- Nonces are random UUIDs (generated at runtime, not pre-seeded)
- Transformations are deterministic hash operations (cannot be guessed)
- Each depth must receive previous depth's nonce and transform it (requires actual execution)
- Final d0 validation checks the chain end-to-end (requires all three depths to execute)
- If any depth is skipped, the nonce mismatches and assertion fails

---

### K.5 Catalog of All Observable Signals

**A. STDOUT-Based Signals (Printed by Skill Code)**

| Signal | Format | Emitted By | Depth | Observable Via | Proof Strength |
|--------|--------|-----------|-------|----------------|---|
| `[TEST_SKILL:depth=...]` | Tag | skill.py:_tag() | 0, 1, 2 | run_result.repl_stdout | STRONG |
| `[TEST_SKILL:iteration_count=...]` | Tag | skill.py:_tag() | 0, 1, 2 | run_result.repl_stdout | STRONG |
| `[TEST_SKILL:execution_mode=...]` | Tag | skill.py line 87 | 0, 1, 2 | run_result.repl_stdout | WEAK (hardcoded) |
| `[TEST_SKILL:calling_llm_query=True]` | Tag | skill.py line 95 | 0, 1, 2 | run_result.repl_stdout | STRONG |
| `[TEST_SKILL:child_result_preview=...]` | Tag | skill.py line 103 | 0 | run_result.repl_stdout | STRONG |
| `[TEST_SKILL:thread_bridge_latency_ms=...]` | Tag | skill.py line 104 | 0, 1 | run_result.repl_stdout | STRONG |
| `[TEST_SKILL:COMPLETE=True]` | Tag | skill.py line 111 | 0, 1, 2 | run_result.repl_stdout | STRONG |
| `[DYN_INSTR:user_ctx_keys=...]` | Tag | orchestrator code | 0 | run_result.repl_stdout | STRONG |
| Child skill stdout (d1) | Plain text | skill.py print() in d1 | 1 | Child's final_answer (in response[1]) | STRONG |

**B. State-Based Signals (Session State Keys, Tracked Channels)**

| Signal | Key Name | Depth | Written By | Observable Via | Proof Strength |
|--------|----------|-------|-----------|-----------------|---|
| Iteration count | `iteration_count` | 0 | REPLTool.run_async | run_result.final_state or session_state_events | STRONG |
| Iteration count (child) | `iteration_count@d1` | 1 | Child REPLTool | session_state_events (re-emitted) | STRONG |
| Current depth | `current_depth` | 0 | Orchestrator init | session_state_events | STRONG |
| Current depth (child) | `current_depth@d1` | 1 | Child orchestrator | session_state_events (re-emitted) | STRONG |
| Skill globals injected | `repl_skill_globals_injected` | 0 | Loader callback | run_result.final_state | MEDIUM |
| Final response text | `final_response_text` | 0 | Orchestrator final | run_result.final_state | STRONG |
| Final response (child) | `final_response_text@d1` | 1 | Child orchestrator | session_state_events (re-emitted) | STRONG |
| LAST_REPL_RESULT | `last_repl_result` | 0 | REPLTool line 258 | run_result.final_state | STRONG |
| REPL submitted code | `repl_submitted_code` | 0 | REPLTool line 170 | run_result.final_state | STRONG |

**C. Plugin/Callback-Based Signals (Instrumentation)**

| Signal | Tag Format | Fired By | Depth | Observable Via | Proof Strength |
|--------|-----------|----------|-------|-----------------|---|
| before_agent | `[PLUGIN:before_agent:reasoning_agent:depth=0]` | InstrumentationPlugin | 0 | instrumentation_log | STRONG |
| before_agent (child) | `[PLUGIN:before_agent:child_orchestrator_d1:...]` | InstrumentationPlugin | 1 | instrumentation_log | STRONG |
| before_model | `[PLUGIN:before_model:reasoning_agent:call_num=1]` | InstrumentationPlugin | 0 | instrumentation_log | STRONG |
| before_tool | `[PLUGIN:before_tool:reasoning_agent:tool_name=execute_code]` | InstrumentationPlugin | 0 | instrumentation_log | STRONG |
| before_tool (set_model_response) | `[PLUGIN:before_tool:reasoning_agent:tool_name=set_model_response]` | InstrumentationPlugin | 0 | instrumentation_log | STRONG |
| after_model | `[PLUGIN:after_model:reasoning_agent:finish_reason=STOP]` | InstrumentationPlugin | 0 | instrumentation_log | STRONG |
| after_model (child) | `[PLUGIN:after_model:child_reasoning_d1:finish_reason=STOP]` | InstrumentationPlugin | 1 | instrumentation_log | STRONG |
| Model tokens | `[PLUGIN:after_model:reasoning_agent:input_tokens=300]` | ObservabilityPlugin | 0 | (not tagged) but in run_result.contract | STRONG |

**D. SQLite Telemetry-Based Signals (Persistent, Auditable)**

| Signal | Table | Query | Depth | Proof Strength |
|--------|-------|-------|-------|---|
| Status completed | `traces.status` | `SELECT status FROM traces` | N/A | STRONG |
| Total calls count | `traces.total_calls` | `SELECT total_calls FROM traces` | N/A | STRONG |
| Max depth reached | `traces.max_depth_reached` | `SELECT max_depth_reached FROM traces` | N/A | STRONG |
| Tool invocation count | `traces.tool_invocation_summary` | JSON extract | N/A | STRONG |
| Model call (d0) | `telemetry.event_type` | `WHERE depth=0` | 0 | STRONG |
| Model call (d1) | `telemetry.event_type` | `WHERE depth=1` | 1 | STRONG |
| Tool call (execute_code d0) | `telemetry.tool_name` | `WHERE depth=0 AND tool_name=execute_code` | 0 | STRONG |
| Tool call (set_model_response d0) | `telemetry.tool_name` | `WHERE depth=0 AND tool_name=set_model_response` | 0 | STRONG |
| Tool call (set_model_response d1) | `telemetry.tool_name` | `WHERE depth=1 AND tool_name=set_model_response` | 1 | STRONG |
| REPL trace data | `telemetry.repl_trace_summary` | JSON extract | 0 | MEDIUM (depends on RLM_REPL_TRACE) |
| Child state events | `session_state_events.key_depth` | `WHERE key_depth=1` | 1 | STRONG |
| Event author (child) | `session_state_events.event_author` | `WHERE event_author LIKE 'child_%'` | 1 | STRONG |

**E. Response-Based Signals (Fixture Design)**

| Signal | Response | Index | Proof Value | Can Be Faked? |
|--------|----------|-------|------------|---|
| Reasoning agent calls execute_code | 0 | functionCall.name | Downward flow proven | No (provider-fake mock) |
| Child orchestrator responds (response[1]) | 1 | candidatesTokenCount>0 | Child executed | No (must be in responses) |
| Child's set_model_response called | 1 | functionCall.name | Upward flow at d1 | No (must be in responses) |
| Parent gets child result | 1 | final_answer="arch_test_ok" | Child return value | No (must be in responses) |
| Parent calls set_model_response | 2 | functionCall.name | Upward flow at d0 | No (must be in responses) |

---

## Summary

**The anti-reward-hacking design strategy:**

1. **Eliminate fake assertions:** Remove checks on dict.get() defaults; require actual pipeline-produced values only

2. **Implement proof chain:** Generate nonce at d0, transform at d1, transform at d2, return and validate all the way back (d0 → d1 → d2 → d1 → d0)

3. **Exhaust observable signals:** Assertions should cover STDOUT tags, state keys (both root and depth-scoped), plugin hooks (all three flows), and SQLite telemetry (traces, telemetry, session_state_events)

4. **Strict operator enforcement:** Change `execution_mode` from `oneof ["async_rewrite", "thread_bridge"]` to `eq "thread_bridge"` (or better: detect at runtime)

5. **Add missing assertions:** 
   - `before_tool:reasoning_agent:tool_name=set_model_response` (upward flow at root)
   - `before_tool:child_reasoning_d1:tool_name=set_model_response` (upward flow at child)
   - `current_depth@d1=1` and `iteration_count@d1=1` (depth-scoped state)
   - `max_depth_reached >= 1` in SQLite traces (depth reached)

6. **Skill introspection:** Modify skill to emit runtime-detected thread bridge signal (e.g., threading.current_thread().name) instead of hardcoded string

7. **Design fixture for three depths:** Add optional 4th response for d2 model call (grandchild depth) to complete the full d0 → d1 → d2 cycle

This transforms the test from a "does it run?" smoke test to a complete architecture validation where every passing assertion is backed by a non-fakeable execution artifact.
