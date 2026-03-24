# test_skill.py Design — Architecture E2E Introspection Skill

**Author**: Skill-Proposer Agent
**Date**: 2026-03-24 (reworked for post-thread-bridge target state)
**Status**: Design Plan — targets codebase AFTER all TDD cycles complete

---

## Overview

`test_skill.py` is a source-expandable REPL skill whose sole purpose is to exercise and validate the entire rlm_adk architecture during provider-fake e2e testing. It is NOT a diagnostic utility for operators — it is a purpose-built test artifact that prints tagged diagnostic lines to stdout, makes a real `llm_query()` call to exercise child dispatch, captures introspection state, and returns a typed `TestSkillResult` dataclass.

**Important**: This test_skill and its fixture NEVER run on the pre-thread-bridge codebase. They exist as the final e2e validation harness for the full thread-bridge TDD implementation plan (Cycles 1–27 in `thread_bridge_plan_B_TDD.md`). The constraints below reflect the codebase AFTER all cycles are complete.

---

## 1. Architectural Constraints That Shape This Design

Each constraint below states what was assumed in the pre-thread-bridge design, what changed, and what the new design does.

### Constraint 1 (CHANGED): Skill globals are populated by the loader, not by side-effect registration

**Pre-thread-bridge assumption**: `SkillRegistry._exports` is populated via side-effect imports. The test module must `import rlm_adk.skills.test_skill` before running the fixture so that `register_skill_export()` populates the registry. The REPL code uses `from rlm_repl_skills.test_skill import run_test_skill` — a synthetic import that `expand_skill_imports()` expands inline.

**What changed**: After Phase 2 (Cycles 10–14), the PRIMARY mechanism for skill availability in the REPL is `collect_skill_repl_globals()` in `rlm_adk/skills/loader.py`. This function:
1. Discovers skill directories containing `SKILL.md`
2. Imports the Python module at `rlm_adk.skills.<skill_name>`
3. Reads `SKILL_EXPORTS` from `__init__.py`
4. Wraps functions that have `llm_query_fn` parameter with an auto-injection wrapper
5. Injects the resulting dict into `repl.globals` at orchestrator startup (Cycle 14)

The source-expansion mechanism (`SkillRegistry`, `expand_skill_imports()`, `rlm_repl_skills.*` synthetic imports) is retained for backward compatibility and may still be used by the test_skill design.

**New design decision**: `test_skill` uses the **source-expansion path** (synthetic `from rlm_repl_skills.test_skill import run_test_skill`) rather than the module-import path, for a specific reason: it validates a different code path than `run_recursive_ping` (which tests the module-import + `llm_query_fn` parameter path). Using both paths in the test suite means both execution paths are exercised. The source-expansion registration via side-effect import (`import rlm_adk.skills.test_skill`) is still required in test setup.

**For phase-appropriate testing**: The capstone e2e tests in `test_skill_thread_bridge_e2e.py` (Cycles 21–26) use the module-import path via `run_recursive_ping`. `test_skill_arch_e2e.py` uses the source-expansion path via `run_test_skill`. Both are needed.

### Constraint 2 (CHANGED): Default execution is thread-bridge, not AST-rewriter

**Pre-thread-bridge assumption**: `has_llm_calls(exec_code)` detects `llm_query(...)` in expanded source. `rewrite_for_async(exec_code)` transforms it to `await llm_query_async(...)`. `execute_code_async()` runs the async wrapper. The presence of `_repl_exec` in globals signals the async-rewrite path.

**What changed**: After Phase 1 (Cycles 1–9):
- The DEFAULT execution path is `repl.execute_code_threaded()` (thread bridge)
- `llm_query()` in REPL globals is a REAL sync callable created by `make_sync_llm_query()` from `rlm_adk/repl/thread_bridge.py`
- `llm_query_batched()` is similarly real via `make_sync_llm_query_batched()`
- `_execute_code_threadsafe` does NOT use `_EXEC_LOCK` or `os.chdir()`
- The AST-rewriter path is the FALLBACK, controlled by `RLM_REPL_THREAD_BRIDGE=0`
- `_repl_exec` is NOT present in REPL globals under the default thread-bridge path
- `REPLTool` has `use_thread_bridge=True` by default; env var `RLM_REPL_THREAD_BRIDGE` gates it
- `LAST_REPL_RESULT["execution_mode"]` is `"thread_bridge"` in the default path (Cycle 8)

**New design**: The skill source uses bare `llm_query()` (calling it as a real sync callable). The execution mode detection is inverted: `_repl_exec` ABSENT means thread bridge (the correct default path). The expected `execution_mode` tag in stdout is `"thread_bridge"`.

### Constraint 3 (STILL CORRECT, minor update): `_rlm_state` is the primary introspection surface

`REPLTool.run_async()` injects `_rlm_state` into `repl.globals` before every execution. It contains keys from `EXPOSED_STATE_KEYS`:
- `iteration_count`, `current_depth`, `app:max_iterations`, `app:max_depth`
- `last_repl_result`, `step:mode_enabled`, `should_stop`, `final_response_text`
- `_rlm_depth` (from REPLTool constructor — independent provenance from state pipeline)
- `_rlm_fanout_idx`
- `_rlm_agent_name`

After Phase 4 (Cycle 14 adds `REPL_SKILL_GLOBALS_INJECTED`), this key may appear in `_rlm_state` if it is added to `EXPOSED_STATE_KEYS`. The skill reads whatever is present and captures it.

**No change to the skill's introspection logic**: it reads all `_rlm_state` keys generically. If the key set grows, the captured snapshot automatically includes the new keys.

### Constraint 4 (UNCHANGED): Child worker response must use set_model_response

`create_child_orchestrator()` in `dispatch.py` wires `SetModelResponseTool(ReasoningOutput)`. The child worker model must emit a `functionCall: set_model_response` with `{final_answer: ..., reasoning_summary: ...}`. Plain-text responses will not be correctly parsed as `LLMResult`. No change post-thread-bridge.

### Constraint 5 (PARTIALLY CHANGED): Skill source is still inlined via expansion for this skill

**Pre-thread-bridge assumption**: When source is expanded, it is concatenated into the submitted code string and executed as a single block. Cannot `import rlm_adk.*` — must be self-contained Python.

**What changed**: After Phase 2, module-imported skill functions (like `run_recursive_ping`) ARE regular Python modules that CAN `import rlm_adk.*`. This constraint applied only to the source-expansion mechanism.

**New design decision**: `test_skill` still uses source expansion, so this constraint still applies. The expanded source must be self-contained. The key implication for the new design is that `run_test_skill` calls bare `llm_query()` — now a REAL sync callable, not a RuntimeError stub — without needing AST rewriting. The source-expansion mechanism remains intact (the `SkillRegistry` is still wired in `repl_tool.py` for backward compatibility) but after thread-bridge, the `llm_query()` call in the expanded source resolves directly as a real callable in REPL globals, not through async rewriting.

---

## 2. Complete `test_skill.py` Module

**File location**: `rlm_adk/skills/test_skill.py`

This module follows the same pattern as `obsolete/repl_skills/ping.py`: it defines source strings for each skill export and registers them at import time via `register_skill_export()`.

```python
"""Source-expandable REPL skill: architecture introspection test.

Registers a source-expandable ReplSkillExport so that:
    from rlm_repl_skills.test_skill import run_test_skill

expands into inline source in the REPL. The skill:
1. Reads _rlm_state globals to capture the current depth/iteration/agent context
2. Makes a real llm_query() call to exercise child dispatch via thread bridge
3. Detects execution mode (thread_bridge vs async_rewrite vs unknown)
4. Prints tagged diagnostic lines for test assertion
5. Returns a TestSkillResult dataclass with all captured data

Import this module in test setup to trigger registration:
    import rlm_adk.skills.test_skill  # noqa: F401

Post-thread-bridge behavior:
- llm_query() in REPL globals is a real sync callable (make_sync_llm_query)
- execution_mode will be "thread_bridge" (default path)
- _repl_exec will NOT be in globals (no async wrapper injected)
- The bare llm_query() call works without AST rewriting
"""

from __future__ import annotations

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ---------------------------------------------------------------------------
# Source block: TestSkillResult dataclass (no import needed — plain class)
# ---------------------------------------------------------------------------

_TEST_SKILL_RESULT_SRC = '''\
class TestSkillResult:
    """Typed result from run_test_skill(). All fields are JSON-serializable."""

    def __init__(
        self,
        state_snapshot: dict,
        repl_globals_keys: list,
        execution_mode: str,
        thread_bridge_latency_ms: float,
        child_result: str,
        timestamps: dict,
    ):
        self.state_snapshot = state_snapshot
        self.repl_globals_keys = repl_globals_keys
        self.execution_mode = execution_mode
        self.thread_bridge_latency_ms = thread_bridge_latency_ms
        self.child_result = child_result
        self.timestamps = timestamps

    def __repr__(self):
        return (
            f"TestSkillResult("
            f"depth={self.state_snapshot.get('_rlm_depth')}, "
            f"iter={self.state_snapshot.get('iteration_count')}, "
            f"mode={self.execution_mode!r}, "
            f"latency_ms={self.thread_bridge_latency_ms:.1f}, "
            f"child={self.child_result[:60]!r})"
        )
'''

# ---------------------------------------------------------------------------
# Source block: run_test_skill function
# ---------------------------------------------------------------------------

_RUN_TEST_SKILL_SRC = '''\
def run_test_skill(
    child_prompt: str = "Reply with exactly: arch_test_ok",
    *,
    emit_debug: bool = True,
) -> TestSkillResult:
    """Exercise the full rlm_adk architecture pipeline and return diagnostic data.

    This function is designed for provider-fake e2e testing. It:
    1. Reads _rlm_state for depth/iteration/agent introspection
    2. Enumerates what is available in REPL globals
    3. Detects whether llm_query is thread_bridge (real callable) or unknown
    4. Makes a real llm_query() call and measures latency
    5. Prints tagged diagnostic lines parseable by test assertions

    Post-thread-bridge: bare llm_query() is a real sync callable in REPL globals.
    The call does NOT go through AST rewriting. Expected execution_mode is
    "thread_bridge".

    Args:
        child_prompt: Prompt to send to the child orchestrator.
        emit_debug: Whether to print [TEST_SKILL:...] tagged lines.

    Returns:
        TestSkillResult with all captured diagnostic data.
    """
    import time as _time

    def _tag(key, value):
        if emit_debug:
            print(f"[TEST_SKILL:{key}={value}]")

    timestamps = {}

    # ------------------------------------------------------------------
    # Step 1: Capture _rlm_state (injected by REPLTool before execution)
    # ------------------------------------------------------------------
    timestamps["t0_start"] = _time.perf_counter()

    state_snapshot = {}
    _state = globals().get("_rlm_state") or {}
    for k, v in _state.items():
        try:
            import json as _json
            _json.dumps(v)
            state_snapshot[k] = v
        except (TypeError, ValueError):
            state_snapshot[k] = repr(v)

    _tag("depth", state_snapshot.get("_rlm_depth", "?"))
    _tag("rlm_agent_name", state_snapshot.get("_rlm_agent_name", "?"))
    _tag("iteration_count", state_snapshot.get("iteration_count", "?"))
    _tag("current_depth", state_snapshot.get("current_depth", "?"))
    _tag("should_stop", state_snapshot.get("should_stop", "?"))
    _tag("state_keys_count", len(state_snapshot))
    _tag("state_keys", sorted(state_snapshot.keys()))

    # ------------------------------------------------------------------
    # Step 2: Enumerate REPL globals to surface what is available
    # ------------------------------------------------------------------
    _globs = list(globals().keys())
    # Filter out builtins and private internals for clean listing
    repl_globals_keys = [k for k in _globs if not k.startswith("__")]

    _tag("repl_globals_count", len(repl_globals_keys))

    # Check if llm_query is a real callable (thread-bridge) vs missing/unknown
    _lq = globals().get("llm_query")
    _lq_type = type(_lq).__name__ if _lq is not None else "missing"
    _tag("llm_query_type", _lq_type)

    # ------------------------------------------------------------------
    # Detect execution mode (post-thread-bridge version)
    #
    # INVERTED logic from the pre-thread-bridge design:
    #
    # Pre-bridge: presence of _repl_exec in globals == async_rewrite path (DEFAULT)
    # Post-bridge: ABSENCE of _repl_exec == thread_bridge path (DEFAULT)
    #
    # Under thread-bridge (default):
    #   - _repl_exec is NOT in globals (no async wrapper function injected)
    #   - llm_query is a plain sync function created by make_sync_llm_query()
    #   => execution_mode = "thread_bridge"
    #
    # Under AST-rewriter fallback (RLM_REPL_THREAD_BRIDGE=0):
    #   - _repl_exec IS in globals (async wrapper was injected)
    #   - llm_query is still a function (llm_query_async shim)
    #   => execution_mode = "async_rewrite"
    # ------------------------------------------------------------------
    _has_repl_exec = "_repl_exec" in globals()
    if not _has_repl_exec and _lq_type == "function":
        execution_mode = "thread_bridge"
    elif _has_repl_exec:
        execution_mode = "async_rewrite"
    else:
        execution_mode = "unknown"

    _tag("execution_mode", execution_mode)
    _tag("has_repl_exec_in_globals", _has_repl_exec)

    # ------------------------------------------------------------------
    # Step 3: Exercise child dispatch via llm_query()
    # Post-bridge: llm_query() is a real sync callable — no async rewriting.
    # It blocks the worker thread via asyncio.run_coroutine_threadsafe()
    # + future.result() while the event loop runs the child orchestrator.
    # ------------------------------------------------------------------
    timestamps["t1_before_llm_query"] = _time.perf_counter()
    _tag("calling_llm_query", True)

    child_result = llm_query(child_prompt)

    timestamps["t2_after_llm_query"] = _time.perf_counter()

    latency_ms = (
        timestamps["t2_after_llm_query"] - timestamps["t1_before_llm_query"]
    ) * 1000.0

    _tag("child_result_preview", str(child_result)[:120])
    _tag("thread_bridge_latency_ms", round(latency_ms, 2))

    # ------------------------------------------------------------------
    # Step 4: Final summary line for test assertions
    # ------------------------------------------------------------------
    timestamps["t3_end"] = _time.perf_counter()

    _tag("COMPLETE", True)
    _tag("summary", (
        f"depth={state_snapshot.get('_rlm_depth', '?')} "
        f"mode={execution_mode} "
        f"latency_ms={latency_ms:.1f} "
        f"child_ok={bool(child_result)}"
    ))

    return TestSkillResult(
        state_snapshot=state_snapshot,
        repl_globals_keys=repl_globals_keys,
        execution_mode=execution_mode,
        thread_bridge_latency_ms=latency_ms,
        child_result=str(child_result),
        timestamps={k: round(v, 6) for k, v in timestamps.items()},
    )
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.test_skill",
        name="TestSkillResult",
        source=_TEST_SKILL_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.test_skill",
        name="run_test_skill",
        source=_RUN_TEST_SKILL_SRC,
        requires=["TestSkillResult"],
        kind="function",
    )
)
```

---

## 3. `TestSkillResult` Schema Summary

| Field | Type | Content |
|-------|------|---------|
| `state_snapshot` | `dict[str, Any]` | All JSON-serializable keys from `_rlm_state` at call time |
| `repl_globals_keys` | `list[str]` | All non-private names in `globals()` at call time |
| `execution_mode` | `str` | `"thread_bridge"` \| `"async_rewrite"` \| `"unknown"` |
| `thread_bridge_latency_ms` | `float` | Elapsed ms for the `llm_query()` round-trip |
| `child_result` | `str` | The raw string value returned by `llm_query()` |
| `timestamps` | `dict[str, float]` | `t0_start`, `t1_before_llm_query`, `t2_after_llm_query`, `t3_end` as perf_counter values |

### Detecting execution mode from `TestSkillResult`

| `_repl_exec` in globals | `llm_query` type | `execution_mode` | Meaning |
|------------------------|-----------------|------------------|---------|
| No | `function` | `"thread_bridge"` | Default path post-thread-bridge |
| Yes | any | `"async_rewrite"` | Fallback path (`RLM_REPL_THREAD_BRIDGE=0`) |
| No | not `function` | `"unknown"` | Unexpected state |

- `thread_bridge_latency_ms`: measures the blocking `future.result()` wait time when the event loop processes the child orchestrator. Meaningful for both paths.

---

## 4. Tagged Stdout Lines (Parseable by Test Assertions)

Every print call uses the prefix `[TEST_SKILL:<key>=<value>]`. Tests parse these lines to assert specific values without depending on the full stdout string.

Example stdout from a provider-fake run at depth=0, iteration=1 (post-thread-bridge):

```
[TEST_SKILL:depth=0]
[TEST_SKILL:rlm_agent_name=reasoning_agent]
[TEST_SKILL:iteration_count=1]
[TEST_SKILL:current_depth=0]
[TEST_SKILL:should_stop=False]
[TEST_SKILL:state_keys_count=7]
[TEST_SKILL:state_keys=['_rlm_agent_name', '_rlm_depth', '_rlm_fanout_idx', 'app:max_depth', 'app:max_iterations', 'current_depth', 'iteration_count']]
[TEST_SKILL:repl_globals_count=12]
[TEST_SKILL:llm_query_type=function]
[TEST_SKILL:execution_mode=thread_bridge]
[TEST_SKILL:has_repl_exec_in_globals=False]
[TEST_SKILL:calling_llm_query=True]
[TEST_SKILL:child_result_preview=arch_test_ok]
[TEST_SKILL:thread_bridge_latency_ms=45.23]
[TEST_SKILL:COMPLETE=True]
[TEST_SKILL:summary=depth=0 mode=thread_bridge latency_ms=45.2 child_ok=True]
```

Note the two key differences from pre-thread-bridge expected output:
- `execution_mode=thread_bridge` (was `async_rewrite`)
- `has_repl_exec_in_globals=False` (was `True`)

### Key assertions for test code

```python
def _parse_test_skill_tags(stdout: str) -> dict[str, str]:
    """Parse [TEST_SKILL:key=value] lines from stdout into a dict."""
    import re
    result = {}
    for m in re.finditer(r"\[TEST_SKILL:([^=\]]+)=([^\]]*)\]", stdout):
        result[m.group(1)] = m.group(2)
    return result

# In test assertions (post-thread-bridge):
tags = _parse_test_skill_tags(repl_stdout)
assert tags["depth"] == "0"
assert tags["COMPLETE"] == "True"
assert tags["execution_mode"] == "thread_bridge"   # NOT "async_rewrite"
assert tags["has_repl_exec_in_globals"] == "False" # NOT "True"
assert tags["llm_query_type"] == "function"
assert float(tags["thread_bridge_latency_ms"]) > 0
assert "arch_test_ok" in tags["child_result_preview"]

# To also accept fallback mode in CI (when RLM_REPL_THREAD_BRIDGE=0):
assert tags["execution_mode"] in ("thread_bridge", "async_rewrite")
```

---

## 5. Proposed Source Modifications for Broader State Exposure

The current `EXPOSED_STATE_KEYS` in `state.py` only exposes 8 keys into `_rlm_state`. After Phase 4 (Cycles 17 and 14), `REPL_SKILL_GLOBALS_INJECTED` may be added.

### Existing exposure (8 keys):

```python
EXPOSED_STATE_KEYS: frozenset[str] = frozenset({
    ITERATION_COUNT,
    CURRENT_DEPTH,
    APP_MAX_ITERATIONS,
    APP_MAX_DEPTH,
    LAST_REPL_RESULT,
    STEP_MODE_ENABLED,
    SHOULD_STOP,
    FINAL_RESPONSE_TEXT,
})
```

### Optional extension (low priority):

```python
# After Phase 4 Cycle 14 (wire skill globals in orchestrator):
# DYN_SKILL_INSTRUCTION,     # "skill_instruction" — injected skill instructions
# REPL_SKILL_GLOBALS_INJECTED, # "repl_skill_globals_injected" — bool, from Cycle 14
# REPL_DID_EXPAND,            # "repl_did_expand" — whether skill expansion occurred
```

**Note**: `REPL_SUBMITTED_CODE` and `REPL_EXPANDED_CODE` remain excluded from `_rlm_state` — they are large strings that would bloat every REPL globals injection. Tests assert on them via SQLite or event stream after the run.

The `test_skill` captures `_rlm_state` generically, so new keys automatically appear in `state_snapshot` if `EXPOSED_STATE_KEYS` is extended. No skill source changes needed.

---

## 6. Complete Fixture JSON

**File**: `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json`

The fixture is unchanged from the pre-thread-bridge design for the orchestration shape (3 responses: reasoning execute_code, worker set_model_response, reasoning set_model_response). However, after the thread-bridge implementation the test assertions against this fixture must check for `execution_mode=thread_bridge` in the REPL result state.

```json
{
  "scenario_id": "skill_arch_test",
  "description": "Architecture introspection skill e2e (post-thread-bridge): Reasoning agent imports and runs run_test_skill via source expansion, which reads _rlm_state, calls llm_query() as a real sync callable through the thread bridge, and returns a TestSkillResult. Validates: skill expansion + state injection + thread-bridge child dispatch + set_model_response. Expected execution_mode: thread_bridge.",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "note": "Reasoning agent calls execute_code to import and run run_test_skill via source expansion.",
      "status": 200,
      "body": {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "name": "execute_code",
                    "args": {
                      "code": "from rlm_repl_skills.test_skill import run_test_skill\n\nresult = run_test_skill(\n    child_prompt='Reply with exactly: arch_test_ok',\n    emit_debug=True,\n)\nprint(f'result={result!r}')"
                    }
                  }
                }
              ]
            },
            "finishReason": "STOP",
            "index": 0
          }
        ],
        "usageMetadata": {
          "promptTokenCount": 300,
          "candidatesTokenCount": 80,
          "totalTokenCount": 380
        },
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 1,
      "caller": "worker",
      "note": "Child orchestrator at depth=1, responding to llm_query('Reply with exactly: arch_test_ok'). Dispatched via thread bridge (run_coroutine_threadsafe + future.result()). Must use set_model_response since child orchestrator wires SetModelResponseTool.",
      "status": 200,
      "body": {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "name": "set_model_response",
                    "args": {
                      "final_answer": "arch_test_ok",
                      "reasoning_summary": "Replied as instructed."
                    }
                  }
                }
              ]
            },
            "finishReason": "STOP",
            "index": 0
          }
        ],
        "usageMetadata": {
          "promptTokenCount": 80,
          "candidatesTokenCount": 20,
          "totalTokenCount": 100
        },
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 2,
      "caller": "reasoning",
      "note": "Reasoning agent sees REPL stdout with [TEST_SKILL:...] tags (including execution_mode=thread_bridge) and calls set_model_response.",
      "status": 200,
      "body": {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "name": "set_model_response",
                    "args": {
                      "final_answer": "Architecture test complete. Skill expanded, child dispatch succeeded via thread bridge, arch_test_ok received.",
                      "reasoning_summary": "run_test_skill expanded from rlm_repl_skills.test_skill, executed with _rlm_state introspection, called llm_query() as real sync callable through thread bridge which returned arch_test_ok, execution_mode=thread_bridge confirmed."
                    }
                  }
                }
              ]
            },
            "finishReason": "STOP",
            "index": 0
          }
        ],
        "usageMetadata": {
          "promptTokenCount": 500,
          "candidatesTokenCount": 60,
          "totalTokenCount": 560
        },
        "modelVersion": "gemini-fake"
      }
    }
  ],
  "fault_injections": [],
  "expected": {
    "final_answer": "Architecture test complete. Skill expanded, child dispatch succeeded via thread bridge, arch_test_ok received.",
    "total_iterations": 1,
    "total_model_calls": 3
  }
}
```

---

## 7. Skill Registration Integration

### How test_skill wires into the skill registry

The registry is populated by side-effect imports. `test_skill.py` calls `register_skill_export()` at module import time — the same pattern as the old `ping.py`. This is the source-expansion path, which still works post-thread-bridge.

**Test setup requirement** (in the pytest test module or conftest):

```python
# Must be imported BEFORE running the fixture so the registry is populated.
# The import is a side effect — it calls register_skill_export().
import rlm_adk.skills.test_skill  # noqa: F401
```

**Why not the module-import (loader) path**: The `test_skill` deliberately uses source expansion to validate the `SkillRegistry.expand()` code path. The module-import path (Phase 2 loader, `SKILL_EXPORTS`, `llm_query_fn` parameter) is validated by the `run_recursive_ping` capstone tests (Cycles 13 and 26). Both paths must be tested; this fixture tests source expansion.

**Why the source-expansion path still works post-thread-bridge**: The `SkillRegistry.expand()` call in `REPLTool.run_async()` is preserved for backward compatibility. After expansion, the inlined `llm_query()` call in the expanded source is resolved from REPL globals at execution time. Since `llm_query` is now a real sync callable (not a RuntimeError stub), it works without AST rewriting.

### Synthetic import path

```python
from rlm_repl_skills.test_skill import run_test_skill
```

This matches the `module="rlm_repl_skills.test_skill"` in the `ReplSkillExport` registration. `SkillRegistry.expand()` detects `rlm_repl_skills.*` prefixed imports and expands them inline.

### Expansion result

After expansion, the submitted code becomes (conceptually):

```python
# --- skill: rlm_repl_skills.test_skill.TestSkillResult ---
class TestSkillResult:
    ...  # (full source block)

# --- skill: rlm_repl_skills.test_skill.run_test_skill ---
def run_test_skill(...):
    ...  # (full source block)
    # Inside: bare llm_query(child_prompt) -- real sync callable, no AST rewrite

result = run_test_skill(
    child_prompt='Reply with exactly: arch_test_ok',
    emit_debug=True,
)
print(f'result={result!r}')
```

Execution flow under thread bridge:
1. `REPLTool.run_async()` sees `use_thread_bridge=True` (default)
2. `has_llm_calls(exec_code)` detects `llm_query(` in expanded source (observability only — no rewriting)
3. `repl.execute_code_threaded(exec_code)` runs the code in a worker thread via `run_in_executor`
4. Worker thread executes `run_test_skill()`, reaches `llm_query(child_prompt)`
5. `llm_query` (a `make_sync_llm_query` closure) calls `asyncio.run_coroutine_threadsafe(llm_query_async(...), loop)` and blocks on `future.result()`
6. Event loop (free, since REPL is in worker thread) runs the child orchestrator coroutine
7. Child returns `LLMResult("arch_test_ok")`
8. Worker thread unblocks, `child_result = "arch_test_ok"`
9. `run_test_skill` prints `[TEST_SKILL:COMPLETE=True]` and returns `TestSkillResult`

State keys written by REPLTool after successful expansion:
- `repl_did_expand` → `True`
- `repl_expanded_code` → full expanded source
- `repl_expanded_code_hash` → sha256 of expanded code
- `repl_skill_expansion_meta` → `{"symbols": ["TestSkillResult", "run_test_skill"], "modules": ["rlm_repl_skills.test_skill"]}`

---

## 8. What This Tests End-to-End

| Component | What is tested |
|-----------|---------------|
| `SkillRegistry.expand()` | Synthetic import detection, dependency resolution, topo-sort, code assembly |
| `REPL_DID_EXPAND` / `REPL_EXPANDED_CODE` state keys | Written by REPLTool after expansion |
| `REPL_SKILL_EXPANSION_META` | Symbol list correctly captured |
| `_rlm_state` global injection | Depth, iteration count, agent name visible inside skill code |
| Thread bridge execution path | `repl.execute_code_threaded()` (not AST rewriter) runs the expanded code |
| `make_sync_llm_query()` callable | `llm_query()` in expanded source is real sync callable, not RuntimeError stub |
| `asyncio.run_coroutine_threadsafe` + `future.result()` | Blocking worker thread, event loop handles child dispatch |
| `create_dispatch_closures()` | Child orchestrator spawned at depth+1 |
| `SetModelResponseTool` + `ReasoningOutput` | Child responds via structured set_model_response |
| `LLMResult` extraction | `_read_child_completion()` returns the `final_answer` text |
| `LAST_REPL_RESULT` state key | Written by REPLTool with stdout preview, llm_calls count, `execution_mode="thread_bridge"` |
| Child event re-emission | `CURATED_STATE_KEYS` keys at depth>0 appear in session_state_events |
| SQLite tracing | `repl_did_expand=True`, `skill_instruction` column, depth-scoped keys captured |
| `set_model_response` (root) | Reasoning agent terminates with `ReasoningOutput.final_answer` |
| Tagged stdout | `[TEST_SKILL:key=value]` lines parseable for test assertions including `execution_mode=thread_bridge` |

**What this does NOT test** (delegated to Cycles 21–26 in `test_skill_thread_bridge_e2e.py`):
- Module-imported function calling `llm_query()` through thread bridge (the `run_recursive_ping` capstone)
- `llm_query_fn` parameter injection wrapper
- `SKILL_EXPORTS` / `collect_skill_repl_globals()` loader path
- SkillToolset L1/L2 discovery (`list_skills`, `load_skill`)

---

## 9. Key Design Decisions

### Decision 1: Bare `llm_query()` not `llm_query_fn` parameter (source-expansion path)

The `llm_query_fn` parameter pattern (Cycle 11, Phase 2B) applies to module-imported skill functions. For source-expanded skills, the function body is inlined into the same REPL namespace where `llm_query` is already a REPL global. Using `llm_query_fn` as a parameter would require the loader to inject it, which is the module-import path. Using bare `llm_query()` is correct for source-expanded skills and works post-thread-bridge because the REPL global is now a real callable.

**Post-thread-bridge**: bare `llm_query()` in source-expanded code resolves to the real sync callable from `make_sync_llm_query()`. No AST rewriting needed. No RuntimeError raised.

### Decision 2: Inverted `execution_mode` detection logic

The detection logic is inverted from the pre-thread-bridge design:

- **Pre-bridge**: `_repl_exec` PRESENT = async_rewrite (the DEFAULT at that time)
- **Post-bridge**: `_repl_exec` ABSENT = thread_bridge (the DEFAULT now)

The logic now reads: if `_repl_exec` is NOT in globals and `llm_query` is a function, we are in the default thread-bridge path. This is a natural inversion — no code change was needed because the signal (`_repl_exec` presence) was already correct; only the interpretation flips as the default execution path changes.

### Decision 3: Source-expansion registration, not auto-discovery, for test_skill

Skills registered by the loader (`collect_skill_repl_globals`) require a `SKILL.md` file and a proper skill directory structure. `test_skill.py` deliberately avoids this structure to stay as a minimal test-only artifact. Auto-discovery would scan `rlm_adk/skills/` and import all skills at agent startup, coupling test-only code to production. The explicit side-effect import in test setup keeps test_skill isolated from production.

### Decision 4: `json.dumps` guard inside skill source

The skill source uses `import json as _json` and `_json.dumps(v)` to guard state snapshot values. This ensures `TestSkillResult` is JSON-serializable for the `variables` return dict. Unchanged from pre-thread-bridge design.

### Decision 5: No `dataclass` — plain class with `__init__`

The expanded source executes as a plain Python block. `@dataclass` requires `from dataclasses import dataclass` inside the source block. Using a plain class with explicit `__init__` is simpler, has no import dependency, and is fully equivalent for this diagnostic purpose. Unchanged from pre-thread-bridge design.

### Decision 6: This fixture tests source-expansion; Cycles 21–26 test module-import

The test suite must cover both code paths. Designating `test_skill_arch_e2e.py` / `skill_arch_test.json` for the source-expansion path and `test_skill_thread_bridge_e2e.py` / `skill_thread_bridge.json` for the module-import + `llm_query_fn` path ensures both mechanisms are exercised without overlap.

---

## 10. Required Source Modifications

**None required** for the core skill to work post-thread-bridge. The skill uses:
- Existing `_rlm_state` injection (already in `repl_tool.py`)
- Existing `expand_skill_imports()` call (preserved for backward compatibility)
- Existing child dispatch machinery
- `llm_query()` — now a real sync callable, not a stub (provided by Cycle 7)

**Optional enhancement** (low priority): Extend `EXPOSED_STATE_KEYS` in `state.py` to include `REPL_SKILL_GLOBALS_INJECTED` if tests need to assert on skill injection status from within REPL code. Currently assertable from SQLite DB and session state after the run.

---

## 11. Files to Create

| File | Action |
|------|--------|
| `rlm_adk/skills/test_skill.py` | **Create** — the skill registration module |
| `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` | **Create** — provider-fake fixture |
| `tests_rlm_adk/test_skill_arch_e2e.py` | **Create** — pytest test module (separate agent designs this per Task #2) |

The test module for Task #2 should:
1. `import rlm_adk.skills.test_skill` to populate the registry
2. Run the fixture via `run_fixture_contract_with_plugins()`
3. Parse `[TEST_SKILL:...]` tags from REPL stdout (from `LAST_REPL_RESULT` state key or SQLite)
4. Assert on `repl_did_expand=True`, skill expansion meta symbols, child dispatch completion, and `final_answer`
5. Assert `tags["execution_mode"] == "thread_bridge"` (not `"async_rewrite"`)
6. Assert `tags["has_repl_exec_in_globals"] == "False"`
7. Assert `LAST_REPL_RESULT["execution_mode"] == "thread_bridge"` in final state

---

## 12. Summary of Changes from Pre-Thread-Bridge Design

| Section | Pre-thread-bridge | Post-thread-bridge |
|---------|-------------------|-------------------|
| **Constraint 1** (Registry) | Side-effect import required; no loader | Loader is PRIMARY for module-import skills; source-expansion still works via side-effect import |
| **Constraint 2** (Execution path) | AST-rewriter is DEFAULT; `_repl_exec` present = default | Thread-bridge is DEFAULT; `_repl_exec` absent = default |
| **Constraint 3** (`_rlm_state`) | 8 fixed keys | Same 8 keys + possible `repl_skill_globals_injected` from Cycle 14 |
| **Constraint 4** (set_model_response) | Unchanged | Unchanged |
| **Constraint 5** (Source inlining) | All skills must be source-expanded | Module-import skills (loader path) CAN import `rlm_adk.*`; source-expanded skills still cannot |
| **Expected `execution_mode` tag** | `"async_rewrite"` | `"thread_bridge"` |
| **`has_repl_exec_in_globals` tag** | `True` | `False` |
| **`llm_query()` call site** | Goes through AST rewriter | Direct real sync callable call |
| **Fixture description** | No thread-bridge mention | Explicitly describes thread-bridge dispatch |
| **Test assertions** | `execution_mode in ("async_rewrite", "thread_bridge")` | `execution_mode == "thread_bridge"` |
