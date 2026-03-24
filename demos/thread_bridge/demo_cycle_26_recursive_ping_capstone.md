# Demo: [Cycle 26] Capstone -- Module-Imported Skill Calls `llm_query()` via Thread Bridge

## TDD Cycle Reference
- Cycle: 26
- Tests: `test_skill_thread_bridge_e2e.py::TestRecursivePingE2E::test_skill_function_calls_llm_query_via_thread_bridge`, `test_child_dispatch_at_depth_1`, `test_result_propagates_to_parent_repl`
- Assertion: The `run_recursive_ping` skill function is imported as a Python module, calls `llm_query()` internally via the thread bridge, dispatches a child at depth+1, and the parent REPL receives the result.

## What This Proves
This is the capstone that validates the entire Thread Bridge Plan B. It demonstrates the previously impossible scenario:
1. A Python function lives in `rlm_adk/skills/recursive_ping/ping.py` as regular Python code
2. It is imported into the REPL via `collect_skill_repl_globals()` + `_wrap_with_llm_query_injection()`
3. The model calls `execute_code` with code that calls `run_recursive_ping()`
4. Inside the function body (opaque bytecode), `llm_query_fn()` calls the sync bridge
5. The sync bridge dispatches to the event loop via `run_coroutine_threadsafe()`
6. A child orchestrator runs at depth+1
7. The child returns a result
8. The parent REPL continues execution below the `llm_query_fn()` call
9. The REPL prints the result, the model sees it, and calls `set_model_response`

Every link in this chain must work. If any one is broken, the test fails.

## Reward-Hacking Risk
This is the highest-risk test because it exercises the most links in the chain. Reward-hacking approaches:
- **Inline code instead of import**: If the fixture used `llm_query()` directly in submitted code (not inside an imported function), the AST rewriter could handle it -- no thread bridge needed
- **Mock llm_query_fn in the wrapper**: The injection wrapper could pass a hardcoded mock that returns "pong" without dispatching
- **Pre-set REPL variables**: The REPL could have `result` already set before the skill function runs
- **Single-depth assertion**: Checking only the final answer without verifying child dispatch at depth+1

The demo guards against this with a multi-step verification that proves each link:
1. The code uses a module import (not inline `llm_query()`)
2. A child worker response is consumed (proving dispatch happened)
3. The telemetry table shows rows at depth > 0
4. Disabling the thread bridge breaks the test

## Prerequisites
- ALL cycles 1-25 implemented
- `rlm_adk/skills/recursive_ping/` directory with `ping.py`, `__init__.py`, `SKILL.md`
- Provider-fake fixture that scripts the skill execution + child dispatch
- `.venv` activated

## Demo Steps

### Step 1: Verify the skill function is real Python (not a mock)
```bash
.venv/bin/python3 -c "
import inspect
from rlm_adk.skills.recursive_ping.ping import run_recursive_ping

source = inspect.getsource(run_recursive_ping)
print('=== run_recursive_ping source ===')
print(source[:500])
print()

# Verify it has the llm_query_fn parameter
sig = inspect.signature(run_recursive_ping)
print(f'Parameters: {list(sig.parameters.keys())}')
print(f'Has llm_query_fn: {\"llm_query_fn\" in sig.parameters}')

# Verify the function body contains llm_query_fn() call
print(f'Body calls llm_query_fn: {\"llm_query_fn(\" in source}')
"
```
**Expected output**: Shows the actual Python source of `run_recursive_ping`, confirms `llm_query_fn` parameter exists, confirms the body calls `llm_query_fn(...)`.
**What this proves**: This is real Python code with a real `llm_query_fn()` call in the body. The AST rewriter cannot see inside this function when it is imported as a module.

### Step 2: Prove the skill function is in REPL globals via the loader
```bash
.venv/bin/python3 -c "
from rlm_adk.skills.loader import collect_skill_repl_globals

# Simulate what the orchestrator does
repl_globals = {'llm_query': lambda p: 'MOCK_RESPONSE'}
exports = collect_skill_repl_globals(repl_globals=repl_globals)

print(f'Exported names: {list(exports.keys())}')
print(f'run_recursive_ping callable: {callable(exports.get(\"run_recursive_ping\"))}')
print(f'RecursivePingResult type: {exports.get(\"RecursivePingResult\")}')
"
```
**Expected output**:
```
Exported names: ['run_recursive_ping', 'RecursivePingResult']
run_recursive_ping callable: True
RecursivePingResult type: <class 'rlm_adk.skills.recursive_ping.ping.RecursivePingResult'>
```
**What this proves**: The skill loader discovers the recursive_ping skill, imports it, and exports the function + type for REPL globals injection.

### Step 3: Run the capstone e2e test
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestRecursivePingE2E -x -v 2>&1 | tail -10
```
**Expected output**: All `TestRecursivePingE2E` tests PASSED

### Step 4: Prove it fails without thread bridge
```bash
RLM_REPL_THREAD_BRIDGE=0 .venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestRecursivePingE2E::test_skill_function_calls_llm_query_via_thread_bridge -x -v 2>&1 | tail -15
```
**Expected output**: Test FAILS -- the imported skill function cannot call `llm_query()` via the AST rewriter path because the function body is opaque bytecode.
**What this proves**: The test genuinely requires the thread bridge. This is not a reward-hacked assertion.

### Step 5: Verify child dispatch at depth+1 in telemetry
```bash
.venv/bin/python3 -c "
import sqlite3, glob, os

db_files = glob.glob('/tmp/**/traces.db', recursive=True)
if db_files:
    db = max(db_files, key=os.path.getmtime)
    conn = sqlite3.connect(db)

    print('=== DEPTH VERIFICATION ===')
    rows = conn.execute('''
        SELECT key, key_depth, substr(value, 1, 60)
        FROM session_state_events
        WHERE key_depth > 0
        ORDER BY id
        LIMIT 5
    ''').fetchall()

    if rows:
        for key, depth, val in rows:
            print(f'  depth={depth} key={key} value={val}')
        print(f'CAPSTONE PROOF: Child orchestrator ran at depth > 0')
    else:
        print('No child events found -- run the capstone test first')

    conn.close()
else:
    print('No traces.db found')
"
```
**Expected output**: Shows child state events with `key_depth > 0`.
**What this proves**: The `llm_query_fn()` call inside the skill function actually dispatched a child orchestrator at depth+1. This is not simulated.

## Verification Checklist
- [ ] Skill function source code contains `llm_query_fn(...)` call in body
- [ ] Skill loader exports the function for REPL globals injection
- [ ] Capstone e2e test passes with thread bridge enabled
- [ ] Capstone e2e test FAILS with `RLM_REPL_THREAD_BRIDGE=0`
- [ ] Telemetry shows child state events at depth > 0
- [ ] This is the previously impossible scenario: module-imported function calling `llm_query()` as a real sync callable
- [ ] This could NOT pass without the complete chain: loader -> wrapper -> REPL globals -> thread bridge -> event loop -> child orchestrator -> return
