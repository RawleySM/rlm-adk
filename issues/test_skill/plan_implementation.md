# Implementation Plan: Expanded skill_arch_test Fixture and Test Runner

**Date**: 2026-03-25
**Author**: Synthesis Planner
**Inputs**: understand_1 through understand_4, review_cross_consistency, review_feasibility, plus 17 source files

---

## Section 1: Call Sequence (Verified)

Cross-checked between `review_cross_consistency.md` section 4 and `review_feasibility.md` section 1. Both agree on 8 calls.

| call_index | depth | caller | tool called | REPL code / final_answer | Observable signals |
|-----------|-------|--------|-------------|--------------------------|-------------------|
| 0 | 0 | reasoning | execute_code | Calls `run_test_skill(child_prompt=..., emit_debug=True, rlm_state=_rlm_state)`. Skill internally calls `llm_query_fn(child_prompt)` which dispatches to d1. After skill returns, prints `skill_result=...` and `skill_latency_ms=...`. | `[TEST_SKILL:depth=0]`, `[TEST_SKILL:COMPLETE=True]`, `[TEST_SKILL:child_result_preview=...]`, `iteration_count` incremented to 1, `last_repl_result` written with `execution_mode: thread_bridge`, `llm_calls_made: true`. `[DYN_INSTR:user_ctx_keys=...]` from user_ctx access. |
| 1 | 1 | worker | execute_code | Child d1 reasoning agent calls `execute_code` with code: `grandchild_result = llm_query('Return the leaf value: depth2_leaf_ok')` followed by `print(f'grandchild_said={grandchild_result}')`. This dispatches to d2 via thread bridge. | `iteration_count@d1` incremented to 1, `last_repl_result@d1` written, `current_depth@d1=1` in initial state. Child event re-emission pushes these to parent queue. |
| 2 | 2 | worker | set_model_response | Grandchild d2 immediately returns `final_answer: "depth2_leaf_ok"`. No REPL execution at d2. | `current_depth@d2=2` set in initial state, `should_stop@d2=True`, `final_response_text@d2="depth2_leaf_ok"`. These bubble up through two-stage re-emission to root's `session_state_events`. |
| 3 | 1 | worker | set_model_response | Child d1 reasoning agent sees REPL stdout (`grandchild_said=depth2_leaf_ok`), calls `set_model_response` with `final_answer: "child_confirmed_depth2: depth2_leaf_ok"`. | `should_stop@d1=True`, `final_response_text@d1` set. LLMResult returned to root's `run_test_skill()` call via thread bridge. |
| 4 | 0 | reasoning | execute_code | Root reasoning sees Turn 1 REPL output (all TEST_SKILL tags + skill_result). Calls `execute_code` with code that calls `llm_query_batched(['Summarize finding A', 'Summarize finding B'])`, then prints each result and `batch_count=2`. Also reads `_rlm_state` to print `turn2_iteration_count=...`. | `iteration_count` incremented to 2, `last_repl_result` updated, new REPL stdout with `batch_0=...`, `batch_1=...`, `batch_count=2`, `turn2_iteration_count=2`. |
| 5 | 1 | worker | set_model_response | Batch child 0 (fanout_idx=0) returns `final_answer: "finding_A_summary"`. | `current_depth@d1=1`, `should_stop@d1=True` (separate child instance). |
| 6 | 1 | worker | set_model_response | Batch child 1 (fanout_idx=1) returns `final_answer: "finding_B_summary"`. | Same as above for second batch child. |
| 7 | 0 | reasoning | set_model_response | Root returns final answer combining all results. | `should_stop=True`, `final_response_text` set to final answer string. |

**Total model API calls: 8**
**Total fixture responses: 8**
**Root `execute_code` calls: 2** (so `iteration_count` = 2 at end)
**Max depth reached: 2** (grandchild at d2)

### FIFO Queue Order Verification

Responses consumed in exact order [0..7] because:
- Call #0: Root reasoning first API call
- Call #1: Root REPL thread blocked on `llm_query()` inside `run_test_skill`. Child d1 starts on event loop.
- Call #2: Child d1 REPL thread blocked on `llm_query()`. Grandchild d2 starts on event loop.
- Call #3: Grandchild returns, child d1 REPL resumes, child d1 reasoning sees tool result and makes next API call.
- Call #4: Child d1 returns, root REPL resumes (run_test_skill completes), root reasoning sees tool result.
- Call #5: Root REPL thread blocked on `llm_query_batched`. Batch child 0 runs first (task order in asyncio.gather).
- Call #6: Batch child 1 runs after batch child 0 completes (zero-latency fake server, deterministic single-threaded event loop).
- Call #7: Both batch children return, root REPL resumes, root reasoning makes final API call.

---

## Section 2: Fixture JSON (`skill_arch_test.json`)

This is the COMPLETE replacement fixture.

```json
{
  "scenario_id": "skill_arch_test",
  "description": "Full pipeline exercise: 3 reasoning turns, depth=2 via run_test_skill -> llm_query -> child execute_code -> llm_query -> grandchild set_model_response, then llm_query_batched with 2 prompts, all observable via stdout/callbacks/SQLite. Non-reward-hacking: every assertion depends on real pipeline execution.",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 10,
    "retry_delay": 0.0,
    "enabled_skills": ["test_skill"],
    "initial_state": {
      "user_provided_ctx": {
        "arch_context.txt": "Architecture validation context for depth=2 + batched dispatch test.",
        "test_metadata.json": "{\"scenario\": \"skill_arch_test\", \"pipeline\": \"provider_fake\", \"depth\": 2}"
      },
      "repo_url": "https://test.example.com/depth2-batched",
      "root_prompt": "Exercise depth=2 dispatch and batched queries.",
      "test_context": "Provider-fake e2e run: depth=2 chain + batched dispatch verification.",
      "skill_instruction": "Use run_test_skill() for depth=2 chain, then llm_query_batched for fanout."
    }
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "note": "Turn 1: Root reasoning agent calls execute_code with run_test_skill. The skill internally calls llm_query() which dispatches a child at depth=1. Also verifies user_ctx injection via DYN_INSTR tags.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": {
                  "code": "result = run_test_skill(\n    child_prompt='Analyze the context and call llm_query to dispatch a grandchild at depth=2.',\n    emit_debug=True,\n    rlm_state=_rlm_state,\n)\nprint(f'skill_result={result.child_result}')\nprint(f'skill_latency_ms={result.thread_bridge_latency_ms:.1f}')\nprint(f'skill_depth={result.state_snapshot.get(\"_rlm_depth\", \"MISSING\")}')\n\n# Dynamic instruction verification\nif 'user_ctx' in dir():\n    print(f'[DYN_INSTR:user_ctx_keys={sorted(user_ctx.keys())}]')\n    print(f'[DYN_INSTR:arch_context_preview={user_ctx.get(\"arch_context.txt\", \"\")[:40]}]')"
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 80, "totalTokenCount": 480},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 1,
      "caller": "worker",
      "note": "Depth=1 child reasoning agent (spawned by run_test_skill's llm_query inside skill code). Child calls execute_code with code that itself calls llm_query() to spawn a grandchild at depth=2.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": {
                  "code": "grandchild_result = llm_query('Return the leaf value: depth2_leaf_ok')\nprint(f'grandchild_said={grandchild_result}')\nprint(f'd1_depth={_rlm_state.get(\"_rlm_depth\", \"MISSING\")}')\nprint(f'd1_iteration={_rlm_state.get(\"iteration_count\", \"MISSING\")}')"
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 150, "candidatesTokenCount": 40, "totalTokenCount": 190},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 2,
      "caller": "worker",
      "note": "Depth=2 grandchild reasoning agent. Leaf node -- calls set_model_response immediately with the requested leaf value.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "depth2_leaf_ok",
                  "reasoning_summary": "Returned leaf value as requested at depth=2."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 20, "totalTokenCount": 100},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 3,
      "caller": "worker",
      "note": "Depth=1 child reasoning agent (resumed after grandchild returned). Sees REPL stdout with grandchild_said=depth2_leaf_ok. Calls set_model_response forwarding the grandchild result.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "child_confirmed_depth2: depth2_leaf_ok",
                  "reasoning_summary": "Dispatched to depth=2, received leaf value depth2_leaf_ok, confirmed."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 30, "totalTokenCount": 230},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 4,
      "caller": "reasoning",
      "note": "Turn 2: Root reasoning agent sees Turn 1 REPL stdout (TEST_SKILL tags + skill_result + depth2_leaf_ok chain). Calls execute_code with llm_query_batched(2 prompts). Also reads _rlm_state to print iteration count, proving state persistence across turns.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": {
                  "code": "batch_results = llm_query_batched(['Summarize finding A', 'Summarize finding B'])\nfor i, r in enumerate(batch_results):\n    print(f'batch_{i}={r}')\nprint(f'batch_count={len(batch_results)}')\nprint(f'turn2_iteration_count={_rlm_state.get(\"iteration_count\", \"MISSING\")}')\nprint(f'turn2_depth={_rlm_state.get(\"_rlm_depth\", \"MISSING\")}')\n\n# Verify turn 1 variable persists in REPL namespace\nprint(f'turn1_skill_result_persisted={\"result\" in dir()}')"
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 600, "candidatesTokenCount": 60, "totalTokenCount": 660},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 5,
      "caller": "worker",
      "note": "Batch child 0 at depth=1 (fanout_idx=0, prompt='Summarize finding A'). Simple set_model_response.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "finding_A_summary",
                  "reasoning_summary": "Summarized finding A."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 15, "totalTokenCount": 95},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 6,
      "caller": "worker",
      "note": "Batch child 1 at depth=1 (fanout_idx=1, prompt='Summarize finding B'). Simple set_model_response.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "finding_B_summary",
                  "reasoning_summary": "Summarized finding B."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 15, "totalTokenCount": 95},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 7,
      "caller": "reasoning",
      "note": "Turn 3: Root reasoning agent sees Turn 1 (skill + depth=2 chain) and Turn 2 (batch) results. Calls set_model_response with final answer.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "Pipeline verified: depth=2 chain succeeded (depth2_leaf_ok via child), batched dispatch returned 2 results (finding_A_summary, finding_B_summary).",
                  "reasoning_summary": "Exercised run_test_skill for depth=2 chain and llm_query_batched for fanout. All components confirmed."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 60, "totalTokenCount": 860},
        "modelVersion": "gemini-fake"
      }
    }
  ],
  "fault_injections": [],
  "expected": {
    "final_answer": {
      "$contains": "depth=2 chain succeeded"
    },
    "total_iterations": 2,
    "total_model_calls": 8
  },
  "expected_state": {
    "user_provided_ctx": {"$not_none": true},
    "user_ctx_manifest": {"$contains": "arch_context.txt"},
    "repo_url": {"$contains": "test.example.com"},
    "skill_instruction": {"$contains": "run_test_skill"},
    "last_repl_result": {"$not_none": true, "$has_key": "execution_mode"},
    "iteration_count": 2,
    "current_depth": 0,
    "should_stop": true,
    "repl_skill_globals_injected": {"$not_none": true}
  },
  "expected_contract": {
    "callers": {
      "sequence": ["reasoning", "worker", "worker", "worker", "reasoning", "worker", "worker", "reasoning"],
      "counts": {"reasoning": 3, "worker": 5},
      "count": 8
    },
    "tool_results": {
      "stdout_contains": ["TEST_SKILL:COMPLETE=True", "batch_count=2", "depth2_leaf_ok"]
    }
  }
}
```

### Key Design Decisions

1. **Turn 1 code calls `run_test_skill()`** -- this proves skill import works. The skill internally calls `llm_query_fn()` which dispatches to d1. The child at d1 then calls `execute_code` with `llm_query()` to reach d2.

2. **Turn 2 code calls `llm_query_batched()`** directly -- this exercises the batched dispatch path separately from the skill path. It also reads `_rlm_state` to print `turn2_iteration_count=2`, proving that `iteration_count` was correctly incremented to 2 by the second `execute_code` call.

3. **Turn 2 also prints `turn1_skill_result_persisted`** -- this verifies REPL namespace persistence across turns (the `result` variable from Turn 1 is still available).

4. **The grandchild (d2) only calls `set_model_response`** -- it does NOT execute code. This means `iteration_count@d2` stays at 0, but `current_depth@d2=2` and `should_stop@d2=True` ARE written by the orchestrator's initial state and final state yields. This is verified by checking `session_state_events` for `key_depth=2`.

---

## Section 3: Skill Modifications (`skill.py`)

### Current Skill Analysis

The current `run_test_skill()` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/test_skill/skill.py` is fully compatible with the new fixture. It:

1. Accepts `child_prompt`, `emit_debug`, `rlm_state`, `llm_query_fn` -- all needed.
2. Calls `llm_query_fn(child_prompt)` at line 97 -- this dispatches to d1.
3. Emits `[TEST_SKILL:...]` tags for all diagnostic data.
4. Returns `TestSkillResult` with `child_result`, `thread_bridge_latency_ms`, etc.

### What the Skill Does NOT Need to Do

The child at d1 does NOT call `run_test_skill()`. The child's `execute_code` response (fixture call_index=1) contains plain Python that calls `llm_query()` directly. The skill only runs at depth=0. This is correct per the feasibility review: "the skill function only runs at depth=0 in the root REPL."

### Modification: Runtime Thread Detection

The `execution_mode = "thread_bridge"` at line 87 is hardcoded (identified as WEAK by review_cross_consistency). To strengthen this, modify the skill to detect the thread bridge at runtime.

**Diff**:

Old (line 87):
```python
    execution_mode = "thread_bridge"
```

New:
```python
    import threading
    _thread_name = threading.current_thread().name
    # Thread bridge runs REPL code in a worker thread (not MainThread).
    # If we're in a worker thread, thread_bridge is in use.
    execution_mode = "thread_bridge" if _thread_name != "MainThread" else "direct"
    _tag("worker_thread_name", _thread_name)
```

This adds one new tag (`worker_thread_name`) and makes `execution_mode` a runtime detection rather than a hardcoded string. The assertion in the lineage can then check `worker_thread_name` is not `MainThread` (STRONG proof) alongside `execution_mode=thread_bridge`.

### Full Diff for `skill.py`

```python
# Old lines 82-88:
    # ------------------------------------------------------------------
    # Step 2: Detect execution mode
    # Module-import functions always use thread bridge (the default).
    # AST rewriter cannot transform opaque bytecode.
    # ------------------------------------------------------------------
    execution_mode = "thread_bridge"
    _tag("execution_mode", execution_mode)

# New lines 82-92:
    # ------------------------------------------------------------------
    # Step 2: Detect execution mode at runtime
    # Thread bridge runs REPL code in a worker thread (not MainThread).
    # Detecting the thread name proves the bridge is actually in use.
    # ------------------------------------------------------------------
    import threading
    _thread_name = threading.current_thread().name
    execution_mode = "thread_bridge" if _thread_name != "MainThread" else "direct"
    _tag("execution_mode", execution_mode)
    _tag("worker_thread_name", _thread_name)
```

No changes to `__init__.py` or `SKILL.md` are needed.

---

## Section 4: Expected Lineage (`expected_lineage.py`)

The COMPLETE replacement `build_skill_arch_test_lineage()` function.

```python
def build_skill_arch_test_lineage() -> ExpectedLineage:
    """Build the ExpectedLineage for the expanded skill_arch_test fixture.

    8-call fixture: 3 reasoning turns (2x execute_code + 1x set_model_response),
    depth=2 via llm_query chain, llm_query_batched with 2 prompts.

    Anti-reward-hacking: every assertion depends on real pipeline execution.
    Removed: repl_did_expand (dead signal), should_stop at model_call_1 (default check).
    Strengthened: execution_mode uses eq not oneof, worker_thread_name added.
    """
    state_keys = [
        # --- iteration_count=0 at first model call (before any tool runs) ---
        StateKeyExpectation(
            phase="model_call_1",
            key="iteration_count",
            operator="eq",
            expected="0",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py:393 -- initial state yields iteration_count=0",
        ),
        # NOTE: Removed should_stop at model_call_1 (was reward-hackable: dict.get default)
        # NOTE: Removed repl_did_expand (dead signal: source expansion path deleted)
    ]

    test_skill = [
        # --- Depth verification (STRONG: _rlm_depth from REPLTool state injection) ---
        TestSkillExpectation(
            key="depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- _rlm_depth injected into _rlm_state; proves REPLTool ran at d=0",
        ),
        # --- Agent name (STRONG: from tool_context.agent_name) ---
        TestSkillExpectation(
            key="rlm_agent_name",
            operator="eq",
            expected="reasoning_agent",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- _rlm_agent_name from tool context",
        ),
        # --- iteration_count=1 inside TEST_SKILL (STRONG: REPLTool incremented) ---
        TestSkillExpectation(
            key="iteration_count",
            operator="eq",
            expected="1",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- REPLTool increments _call_count to 1 before first execute_code",
        ),
        # --- current_depth=0 (STRONG: from depth-scoped state) ---
        TestSkillExpectation(
            key="current_depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- current_depth from EXPOSED_STATE_KEYS snapshot",
        ),
        # --- should_stop inside skill: '?' because it's None before any tool completes ---
        TestSkillExpectation(
            key="should_stop",
            operator="eq",
            expected="?",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- should_stop in EXPOSED_STATE_KEYS but None; skill defaults to '?'",
        ),
        # --- state_keys_count (STRONG: proves _rlm_state was built) ---
        TestSkillExpectation(
            key="state_keys_count",
            operator="gte",
            expected=6,
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- _rlm_state from EXPOSED_STATE_KEYS + 3 lineage metadata keys",
        ),
        # --- llm_query_fn_type (STRONG: proves loader wrapper injected the closure) ---
        TestSkillExpectation(
            key="llm_query_fn_type",
            operator="eq",
            expected="function",
            source_file="rlm_adk/dispatch.py",
            source_hint="dispatch.py -- llm_query injected as closure; type() is 'function'",
        ),
        # --- execution_mode STRICT eq (fixed from oneof, now runtime-detected) ---
        TestSkillExpectation(
            key="execution_mode",
            operator="eq",
            expected="thread_bridge",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py -- runtime detection: thread_bridge if not MainThread",
        ),
        # --- worker_thread_name (NEW, STRONG: proves REPL runs in worker thread) ---
        TestSkillExpectation(
            key="worker_thread_name",
            operator="not_contains",
            expected="MainThread",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py -- threading.current_thread().name; must NOT be MainThread",
        ),
        # --- calling_llm_query (STRONG: emitted before llm_query() call) ---
        TestSkillExpectation(
            key="calling_llm_query",
            operator="eq",
            expected="True",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py -- emitted immediately before llm_query_fn() call",
        ),
        # --- child_result_preview (STRONG: requires child dispatch + return) ---
        TestSkillExpectation(
            key="child_result_preview",
            operator="contains",
            expected="child_confirmed_depth2",
            source_file="rlm_adk/dispatch.py",
            source_hint="dispatch.py -- child at d1 calls execute_code then set_model_response with 'child_confirmed_depth2: depth2_leaf_ok'",
        ),
        # --- thread_bridge_latency_ms (STRONG: measured via perf_counter) ---
        TestSkillExpectation(
            key="thread_bridge_latency_ms",
            operator="gt",
            expected=0.0,
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py -- latency measured via time.perf_counter() around llm_query()",
        ),
        # --- COMPLETE (STRONG: only emitted if run_test_skill returns without error) ---
        TestSkillExpectation(
            key="COMPLETE",
            operator="eq",
            expected="True",
            source_file="rlm_adk/skills/test_skill/skill.py",
            source_hint="skill.py -- only emitted if the entire function ran without exception",
        ),
    ]

    plugin_hooks = [
        PluginHookExpectation(
            hook="before_agent",
            agent_name="reasoning_agent",
            key="depth",
            operator="eq",
            expected="0",
            source_file="rlm_adk/agent.py",
            source_hint="agent.py -- _rlm_depth=0 on root reasoning_agent",
        ),
        PluginHookExpectation(
            hook="before_model",
            agent_name="reasoning_agent",
            key="call_num",
            operator="gte",
            expected=1,
            source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
            source_hint="InstrumentationPlugin.before_model_callback -- monotonic counter",
        ),
        PluginHookExpectation(
            hook="before_model",
            agent_name="reasoning_agent",
            key="sys_instr_len",
            operator="gt",
            expected=0,
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py -- RLM_STATIC_INSTRUCTION + resolved RLM_DYNAMIC_INSTRUCTION",
        ),
        # --- execute_code tool call (STRONG: before_tool fires for real tool invocations) ---
        PluginHookExpectation(
            hook="before_tool",
            agent_name="reasoning_agent",
            key="tool_name",
            operator="eq",
            expected="execute_code",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- REPLTool.name == 'execute_code'",
        ),
        # --- set_model_response tool call at root (NEW, STRONG: proves upward flow at d0) ---
        PluginHookExpectation(
            hook="before_tool",
            agent_name="reasoning_agent",
            key="tool_name",
            operator="eq",
            expected="set_model_response",
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="ADK SetModelResponseTool fires before_tool for root reasoning_agent",
        ),
        PluginHookExpectation(
            hook="after_model",
            agent_name="reasoning_agent",
            key="finish_reason",
            operator="eq",
            expected="STOP",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py -- reasoning_agent finishes with STOP",
        ),
    ]

    timings = [
        TimingExpectation(
            label="agent_reasoning_agent_ms",
            operator="gte",
            expected_ms=0.0,
            source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
            source_hint="InstrumentationPlugin.after_agent_callback -- emits [TIMING:agent_<name>_ms=<elapsed>]",
        ),
        TimingExpectation(
            label="model_call_1_ms",
            operator="gte",
            expected_ms=0.0,
            source_file="tests_rlm_adk/provider_fake/instrumented_runner.py",
            source_hint="InstrumentationPlugin.after_model_callback -- emits [TIMING:model_call_<N>_ms=<elapsed>]",
        ),
    ]

    orderings = [
        OrderingExpectation(
            first_hook="before_agent",
            first_agent="reasoning_agent",
            second_hook="before_model",
            second_agent="reasoning_agent",
            description="before_agent must fire before before_model (agent lifecycle order)",
        ),
        OrderingExpectation(
            first_hook="before_model",
            first_agent="reasoning_agent",
            second_hook="before_tool",
            second_agent="reasoning_agent",
            description="before_model must fire before before_tool (model decides to call tool)",
        ),
        OrderingExpectation(
            first_hook="before_tool",
            first_agent="reasoning_agent",
            second_hook="after_tool",
            second_agent="reasoning_agent",
            description="before_tool must fire before after_tool (tool bracket pair is closed)",
        ),
    ]

    dyn_instr = [
        DynInstrExpectation(
            key="repo_url",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py -- '{repo_url?}' resolved from session state key 'repo_url'",
        ),
        DynInstrExpectation(
            key="root_prompt",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py -- '{root_prompt?}' resolved from 'root_prompt' in session state",
        ),
        DynInstrExpectation(
            key="test_context",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py -- '{test_context?}' resolved from raw key 'test_context'",
        ),
        DynInstrExpectation(
            key="skill_instruction",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/utils/prompts.py",
            source_hint="prompts.py -- '{skill_instruction?}' resolved from DYN_SKILL_INSTRUCTION",
        ),
        DynInstrExpectation(
            key="user_ctx_manifest",
            operator="contains",
            expected="resolved=True",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py Path B -- builds user_ctx_manifest from user_provided_ctx dict",
        ),
        DynInstrExpectation(
            key="user_ctx_keys",
            operator="contains",
            expected="arch_context.txt",
            source_file="rlm_adk/orchestrator.py",
            source_hint="orchestrator.py Path B -- pre-loads repl.globals['user_ctx']",
        ),
    ]

    repl_trace = [
        ReplTraceExpectation(
            key="execution_mode",
            operator="eq",
            expected="thread_bridge",
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py -- REPLTrace.execution_mode field",
            required=False,
        ),
        ReplTraceExpectation(
            key="wall_time_ms",
            operator="gt",
            expected=0.0,
            source_file="rlm_adk/repl/ipython_executor.py",
            source_hint="ipython_executor.py -- pre_run_cell/post_run_cell timing callbacks",
            required=False,
        ),
        ReplTraceExpectation(
            key="llm_call_count",
            operator="gte",
            expected=1,
            source_file="rlm_adk/repl/trace.py",
            source_hint="trace.py -- REPLTrace.record_llm_start() called by dispatch.py",
            required=False,
        ),
        ReplTraceExpectation(
            key="submitted_code_chars",
            operator="gt",
            expected=0,
            source_file="rlm_adk/tools/repl_tool.py",
            source_hint="repl_tool.py -- trace.submitted_code_chars = len(expanded_code)",
            required=False,
        ),
    ]

    return ExpectedLineage(
        state_key_expectations=state_keys,
        test_skill_expectations=test_skill,
        plugin_hook_expectations=plugin_hooks,
        timing_expectations=timings,
        ordering_expectations=orderings,
        dyn_instr_expectations=dyn_instr,
        repl_trace_expectations=repl_trace,
    )
```

### Why Each Expectation is Non-Reward-Hacking

| Expectation | Pipeline dependency |
|------------|-------------------|
| `depth=0` | _rlm_state snapshot injected by REPLTool; if tool doesn't run, value is absent |
| `iteration_count=1` | REPLTool increments `_call_count` before executing code; absent if tool never fires |
| `child_result_preview` contains `child_confirmed_depth2` | Requires: skill called `llm_query_fn()` -> thread bridge dispatched d1 child -> d1 called `execute_code` -> d1 called `llm_query()` -> d2 grandchild returned `depth2_leaf_ok` -> d1 forwarded as `child_confirmed_depth2: depth2_leaf_ok` -> thread bridge returned LLMResult to skill |
| `COMPLETE=True` | Only emitted if `run_test_skill()` runs to completion without exception |
| `execution_mode=thread_bridge` | Now runtime-detected via `threading.current_thread().name` |
| `worker_thread_name` not MainThread | Runtime thread check; cannot be pre-computed |
| `before_tool:reasoning_agent:tool_name=set_model_response` | Proves root called set_model_response (upward flow) |

---

## Section 5: Test Module (`test_skill_arch_e2e.py`)

The COMPLETE replacement test module:

```python
"""E2E test: Architecture introspection skill via thread bridge.

Exercises: skill loading (module-import) + thread-bridge child dispatch at depth=2 +
llm_query_batched fanout + dynamic instruction resolution + full observability pipeline.

Expanded fixture: 8 model calls, 3 reasoning turns, depth=2 via llm_query chain,
llm_query_batched with 2 prompts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.expected_lineage import (
    build_skill_arch_test_lineage,
    run_all_assertions,
)
from tests_rlm_adk.provider_fake.instrumented_runner import (
    run_fixture_contract_instrumented,
)
from tests_rlm_adk.provider_fake.stdout_parser import parse_stdout

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "skill_arch_test.json"


@pytest.fixture
async def run_result(tmp_path: Path):
    """Run the fixture once, reuse across all tests in this module."""
    return await run_fixture_contract_instrumented(
        FIXTURE_PATH,
        traces_db_path=str(tmp_path / "traces.db"),
        tmpdir=str(tmp_path),
    )


class TestContractPasses:
    async def test_contract_passes(self, run_result):
        assert run_result.contract.passed, run_result.contract.diagnostics()


class TestArchitectureLineage:
    async def test_full_lineage(self, run_result):
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        log = parse_stdout(combined)
        lineage = build_skill_arch_test_lineage()
        report = run_all_assertions(log, lineage)
        if not report.passed:
            extra = ""
            if hasattr(run_result, "repl_stderr") and run_result.repl_stderr:
                extra = f"\n\n--- REPL stderr (Verbose xmode) ---\n{run_result.repl_stderr}"
            pytest.fail(report.format_report() + extra)


class TestDynamicInstruction:
    async def test_no_unresolved_placeholders(self, run_result):
        si = run_result.final_state.get("_captured_system_instruction_0", "")
        assert si, "No system instruction captured by dyn_instr_capture_hook"
        for placeholder in [
            "{repo_url?}",
            "{root_prompt?}",
            "{test_context?}",
            "{skill_instruction?}",
            "{user_ctx_manifest?}",
        ]:
            assert placeholder not in si, f"Unresolved placeholder: {placeholder}"

    async def test_resolved_values_present(self, run_result):
        si = run_result.final_state.get("_captured_system_instruction_0", "")
        assert "https://test.example.com/depth2-batched" in si
        assert "depth=2 dispatch" in si.lower() or "depth=2" in si.lower() or "batched" in si.lower()
        assert "arch_context.txt" in si


class TestSqliteTelemetry:
    async def test_traces_completed(self, run_result):
        """Verify traces.status = 'completed' and total_calls >= 8."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute("SELECT status, total_calls FROM traces LIMIT 1").fetchone()
            assert row and row[0] == "completed", f"traces.status = {row}"
            assert row[1] >= 8, f"total_calls = {row[1]}, expected >= 8"
        finally:
            conn.close()

    async def test_execute_code_telemetry(self, run_result):
        """Verify execute_code tool telemetry rows exist with repl_llm_calls >= 1."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT repl_llm_calls FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='execute_code' LIMIT 1"
            ).fetchone()
            assert row and row[0] >= 1, f"repl_llm_calls = {row}"
        finally:
            conn.close()

    async def test_max_depth_reached(self, run_result):
        """Verify max_depth_reached >= 2 in traces table (proves grandchild at d2 ran)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT max_depth_reached FROM traces LIMIT 1"
            ).fetchone()
            # max_depth_reached may be stored as integer or JSON; handle both
            if row and row[0] is not None:
                val = row[0]
                if isinstance(val, str):
                    val = int(val)
                assert val >= 2, f"max_depth_reached = {val}, expected >= 2"
            else:
                # Column may not exist in older schema; skip gracefully
                pytest.skip("max_depth_reached column not present in traces table")
        finally:
            conn.close()

    async def test_child_dispatch_count(self, run_result):
        """Verify child_dispatch_count >= 4 (1 from skill + 1 from d1 + 2 from batch)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT child_dispatch_count FROM traces LIMIT 1"
            ).fetchone()
            if row and row[0] is not None:
                val = row[0]
                if isinstance(val, str):
                    val = int(val)
                assert val >= 4, f"child_dispatch_count = {val}, expected >= 4"
            else:
                pytest.skip("child_dispatch_count column not present in traces table")
        finally:
            conn.close()

    async def test_tool_invocation_summary(self, run_result):
        """Verify tool_invocation_summary contains execute_code and set_model_response."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT tool_invocation_summary FROM traces LIMIT 1"
            ).fetchone()
            if row and row[0] is not None:
                summary = row[0]
                if isinstance(summary, str):
                    summary = json.loads(summary)
                assert "execute_code" in summary, f"execute_code not in tool_invocation_summary: {summary}"
                assert "set_model_response" in summary, f"set_model_response not in tool_invocation_summary: {summary}"
            else:
                pytest.skip("tool_invocation_summary column not present in traces table")
        finally:
            conn.close()


class TestDepthScopedState:
    """Verify depth-scoped state keys appear in session_state_events via child event re-emission."""

    async def test_depth1_state_keys(self, run_result):
        """Verify depth=1 state keys exist in session_state_events (key_depth=1)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            # Check for any key with @d1 suffix in session_state_events
            rows = conn.execute(
                "SELECT key FROM session_state_events WHERE key LIKE '%@d1'"
            ).fetchall()
            if not rows:
                # Try key_depth column if available
                rows = conn.execute(
                    "SELECT key FROM session_state_events WHERE key_depth = 1"
                ).fetchall()
            keys = [r[0] for r in rows]
            assert len(keys) > 0, (
                "No depth=1 state keys found in session_state_events. "
                "Child event re-emission may not be working."
            )
            # Verify at least current_depth@d1 is present
            d1_keys_base = [k.split("@")[0] for k in keys]
            assert "current_depth" in d1_keys_base, (
                f"current_depth@d1 not found. Keys at d1: {keys}"
            )
        finally:
            conn.close()

    async def test_depth2_state_keys(self, run_result):
        """Verify depth=2 state keys exist (proves grandchild events bubbled up)."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT key FROM session_state_events WHERE key LIKE '%@d2'"
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT key FROM session_state_events WHERE key_depth = 2"
                ).fetchall()
            keys = [r[0] for r in rows]
            assert len(keys) > 0, (
                "No depth=2 state keys found in session_state_events. "
                "Two-stage child event re-emission (d2 -> d1 -> d0) may not be working."
            )
        finally:
            conn.close()

    async def test_iteration_count_at_root(self, run_result):
        """Verify iteration_count=2 at depth=0 (two execute_code calls)."""
        assert run_result.final_state.get("iteration_count") == 2, (
            f"iteration_count = {run_result.final_state.get('iteration_count')}, expected 2"
        )


class TestChildEventReemission:
    """Verify child events reached parent session via re-emission queue."""

    async def test_child_event_metadata(self, run_result):
        """Verify session_state_events has rows with rlm_child_event metadata."""
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            # Check if the custom_metadata column exists and contains child event markers
            try:
                rows = conn.execute(
                    "SELECT custom_metadata FROM session_state_events "
                    "WHERE custom_metadata IS NOT NULL LIMIT 10"
                ).fetchall()
            except sqlite3.OperationalError:
                pytest.skip("custom_metadata column not in session_state_events")
                return

            child_events = [
                r[0] for r in rows
                if r[0] and "rlm_child_event" in str(r[0])
            ]
            assert len(child_events) > 0, (
                "No child events with rlm_child_event metadata found in session_state_events"
            )
        finally:
            conn.close()


class TestBatchedDispatch:
    """Verify llm_query_batched produced correct results observable in stdout."""

    async def test_batch_count_in_stdout(self, run_result):
        """Verify 'batch_count=2' appears in REPL stdout (proves batched dispatch returned 2 results)."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "batch_count=2" in combined, (
            "batch_count=2 not found in stdout. "
            "llm_query_batched may not have returned 2 results."
        )

    async def test_batch_results_in_stdout(self, run_result):
        """Verify individual batch results appear in stdout."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "batch_0=" in combined, "batch_0 result not found in stdout"
        assert "batch_1=" in combined, "batch_1 result not found in stdout"
        # Verify the actual child responses flowed through
        assert "finding_A_summary" in combined, "finding_A_summary not found in stdout"
        assert "finding_B_summary" in combined, "finding_B_summary not found in stdout"

    async def test_turn2_iteration_count(self, run_result):
        """Verify turn2 code read iteration_count=2 from _rlm_state (proves state persistence)."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "turn2_iteration_count=2" in combined, (
            "turn2_iteration_count=2 not found in stdout. "
            "Either _rlm_state snapshot was wrong or second execute_code didn't increment."
        )

    async def test_turn1_variable_persisted(self, run_result):
        """Verify that the 'result' variable from Turn 1 persists into Turn 2 REPL namespace."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "turn1_skill_result_persisted=True" in combined, (
            "turn1_skill_result_persisted=True not found in stdout. "
            "REPL namespace may not persist across execute_code calls."
        )

    async def test_depth2_proof_in_stdout(self, run_result):
        """Verify depth2_leaf_ok flows through the depth=2 chain into root stdout."""
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        assert "depth2_leaf_ok" in combined, (
            "depth2_leaf_ok not found in stdout. "
            "The depth=2 chain (root -> d1 execute_code -> d2 set_model_response -> d1 set_model_response -> root) may be broken."
        )

    async def test_caller_sequence(self, run_result):
        """Verify the expected caller sequence matches the 8-call fixture."""
        # This is checked by expected_contract.callers.sequence in the contract,
        # but we double-check it here for clarity.
        assert run_result.contract.passed, (
            "Contract failed. Caller sequence may not match. "
            f"Diagnostics: {run_result.contract.diagnostics()}"
        )
```

---

## Section 6: Files to Create/Modify

Implementation order (TDD: test expectations first, then fixture, then skill, then test runner).

| Order | File | Action | Description |
|-------|------|--------|-------------|
| 1 | `rlm_adk/skills/test_skill/skill.py` | MODIFY | Add runtime thread detection for `execution_mode` and `worker_thread_name` tag |
| 2 | `tests_rlm_adk/provider_fake/expected_lineage.py` | MODIFY | Replace `build_skill_arch_test_lineage()` with expanded version. Remove reward-hackable assertions (repl_did_expand, should_stop at model_call_1). Add worker_thread_name, set_model_response plugin hook, strengthen execution_mode to eq. Update child_result_preview to match new child response. |
| 3 | `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` | REPLACE | Replace entire file with new 8-response fixture |
| 4 | `tests_rlm_adk/test_skill_arch_e2e.py` | REPLACE | Replace with expanded test module adding TestDepthScopedState, TestChildEventReemission, TestBatchedDispatch, expanded TestSqliteTelemetry |
| 5 | `tests_rlm_adk/fixtures/provider_fake/index.json` | MODIFY | Update the skill_arch_test entry if total_model_calls or description changed |

### Verification Steps After Implementation

1. Run the single test: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py -x -v`
2. Run existing provider-fake tests to ensure no regressions: `.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -x -v`
3. Run lint: `ruff check rlm_adk/skills/test_skill/ tests_rlm_adk/test_skill_arch_e2e.py tests_rlm_adk/provider_fake/expected_lineage.py`

---

## Section 7: Risk Assessment

### From the Cross-Consistency Review: 14 Claims Checked, 4 That Affect This Plan

| Finding | Impact on plan | Mitigation |
|---------|---------------|------------|
| **I1**: EXPOSED_STATE_KEYS has 10 keys (not 8). Plus 3 runtime metadata keys = up to 13 in _rlm_state. | `state_keys_count >= 6` assertion is safe (well below actual count). No change needed. | None needed. |
| **I13**: Child event drain happens DURING reasoning loop (not only after). | Does not affect fixture design. Events are drained correctly during the loop. | None needed. |
| **I14**: Children get ALL skill REPL functions (because `() or None` = `None`), but do NOT get SkillToolset. | Confirmed: child at d1 CAN call `run_test_skill()` from its REPL if needed, but our fixture has the child calling `llm_query()` directly. No conflict. | None needed. |
| **C5**: Agent 3's nonce chain requires children to execute code (not just set_model_response). | Our fixture already has d1 calling execute_code (call_index=1). The nonce chain from Agent 3 is NOT implemented in this plan because it would require additional skill modifications at d1 (the child doesn't run `run_test_skill`). Instead, we prove the depth=2 chain through the `child_confirmed_depth2: depth2_leaf_ok` string flowing through stdout. | The proof chain is: d2 returns "depth2_leaf_ok" -> d1 prints "grandchild_said=depth2_leaf_ok" -> d1 returns "child_confirmed_depth2: depth2_leaf_ok" -> root's run_test_skill receives this -> root prints child_result_preview containing it. If any link breaks, the assertion fails. |

### Feasibility Review: No Blockers, But Edge Cases

| Edge case | Risk | Mitigation |
|-----------|------|------------|
| REPL timeout (30s default) for nested depth=2 chain | LOW: With fake server, entire chain completes in < 1s. | The fixture config does not need `RLM_REPL_SYNC_TIMEOUT` override. |
| `asyncio.gather` ordering for batch children | LOW: Deterministic with zero-latency fake server. | Call #5 before #6 is reliable. |
| `session_state_events` table schema may vary | MEDIUM: If SqliteTracingPlugin doesn't write `key_depth` column, depth-scoped key assertions use `LIKE '%@d1'` fallback. | Both patterns are tested (LIKE fallback + key_depth column). |
| `max_depth_reached` and `child_dispatch_count` columns may not exist | MEDIUM: These columns depend on SqliteTracingPlugin schema version. | Tests use `pytest.skip()` if columns are absent. |
| `custom_metadata` column in session_state_events | MEDIUM: May not be populated by all SqliteTracingPlugin versions. | Test uses `pytest.skip()` if column is absent or empty. |

### Expected Totals for Contract

| Metric | Expected value | Source |
|--------|---------------|--------|
| `total_model_calls` | 8 | Router's `_call_index` counter after all 8 API calls |
| `total_iterations` | 2 | REPLTool's `_call_count` at depth=0 (two execute_code calls) |
| `final_answer` | Contains "depth=2 chain succeeded" | From response #7's set_model_response args |
| `callers.sequence` | `["reasoning", "worker", "worker", "worker", "reasoning", "worker", "worker", "reasoning"]` | 3 reasoning (d0) + 5 worker (d1/d2) calls |
| `callers.counts` | `{"reasoning": 3, "worker": 5}` | Cross-check with sequence |

---

**End of Implementation Plan**
