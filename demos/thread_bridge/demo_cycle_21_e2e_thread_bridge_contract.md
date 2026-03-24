# Demo: [Cycle 21] E2E Provider-Fake Contract -- Skill Function Calls `llm_query()` via Thread Bridge

## TDD Cycle Reference
- Cycle: 21
- Tests: `test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeContract::test_contract_passes`, `test_final_answer_contains_expected_text`, `test_events_emitted`
- Assertion: The full pipeline works: model calls `execute_code` with skill function code -> skill function calls `llm_query()` via thread bridge -> child orchestrator dispatches -> child returns -> parent REPL continues -> model calls `set_model_response`.

## What This Proves
This is the PREVIOUSLY IMPOSSIBLE test. Before the thread bridge, a module-imported function calling `llm_query()` would crash with `RuntimeError` because:
1. The AST rewriter only transforms the submitted code string
2. Imported function bodies are opaque bytecode
3. The sync `llm_query` stub intentionally raises `RuntimeError`

With the thread bridge, `llm_query()` is a real sync callable that bridges to the event loop. The skill function's opaque bytecode can call it directly.

## Reward-Hacking Risk
This is the highest reward-hacking risk in the plan because:
- A fixture could script the "correct" output without the skill function actually executing
- A fixture could use inline `llm_query()` in the submitted code (which the AST rewriter can handle) instead of a module-imported function call
- A test could mock `llm_query` at the REPL globals level with a fake that returns the expected value without dispatching a child

The fixture design guards against this because:
1. The submitted code uses `from rlm_adk.skills.recursive_ping import run_recursive_ping` -- a real module import
2. The skill function body contains `llm_query_fn(...)` -- opaque bytecode the AST rewriter CANNOT see
3. The fixture scripts a child worker response at `call_index=1` -- if no child dispatches, the fixture exhausts responses and crashes
4. If `llm_query` is the old RuntimeError stub, the REPL catches `RuntimeError` and the final answer will NOT contain the expected text

## Prerequisites
- ALL Phase 1-4 cycles implemented
- Provider-fake fixture `skill_thread_bridge.json` created
- `FakeGeminiServer` + `ScenarioRouter` infrastructure available
- `.venv` activated

## Demo Steps

### Step 1: Inspect the fixture to see what the model "does"
```bash
.venv/bin/python3 -c "
import json

with open('tests_rlm_adk/fixtures/provider_fake/skill_thread_bridge.json') as f:
    fixture = json.load(f)

print(f'Scenario: {fixture[\"scenario_id\"]}')
print(f'Responses: {len(fixture[\"responses\"])}')
print()

for resp in fixture['responses']:
    idx = resp['call_index']
    caller = resp.get('caller', 'unknown')
    parts = resp['body']['candidates'][0]['content']['parts']
    for part in parts:
        fc = part.get('functionCall')
        if fc:
            print(f'[call_index={idx}, caller={caller}] functionCall: {fc[\"name\"]}')
            if fc['name'] == 'execute_code':
                print(f'  Code (first 3 lines):')
                for line in fc['args']['code'].split(chr(10))[:3]:
                    print(f'    {line}')
            elif fc['name'] == 'set_model_response':
                fa = fc['args'].get('final_answer', '')[:80]
                print(f'  final_answer: {fa}...')
        else:
            text = part.get('text', '')[:80]
            if text:
                print(f'[call_index={idx}, caller={caller}] text: {text}')
"
```
**Expected output** (approximate):
```
Scenario: skill_thread_bridge_e2e
Responses: 3

[call_index=0, caller=reasoning] functionCall: execute_code
  Code (first 3 lines):
    from rlm_repl_skills.ping import run_recursive_ping
    ...
[call_index=1, caller=worker] functionCall: set_model_response
  final_answer: pong...
[call_index=2, caller=reasoning] functionCall: set_model_response
  final_answer: Skill thread bridge verified...
```
**What this proves**: The fixture scripts exactly 3 model calls. Call 0 imports a real module and calls the skill function. Call 1 is the child worker's response. Call 2 is the final answer. If the skill function never dispatches a child, call 1's response is never consumed and the pipeline crashes.

### Step 2: Run the contract test
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeContract -x -v 2>&1 | tail -10
```
**Expected output**: All `TestSkillThreadBridgeContract` tests PASSED
**What this proves**: The full pipeline ran: skill imported, `llm_query()` dispatched via thread bridge, child responded, parent REPL continued, final answer returned.

### Step 3: Prove this CANNOT work without the thread bridge
```bash
RLM_REPL_THREAD_BRIDGE=0 .venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeContract::test_contract_passes -x -v 2>&1 | tail -15
```
**Expected output**: Test FAILS (the AST rewriter path cannot transform the opaque bytecode of the imported skill function, so `llm_query()` inside the function either raises `RuntimeError` or is not rewritten)
**What this proves**: The test is NOT reward-hacked. It genuinely requires the thread bridge to pass. Disabling the bridge breaks it.

### Step 4: Inspect the traces.db for evidence of child dispatch
```bash
.venv/bin/python3 -c "
import sqlite3
import glob
import os

# Find the most recent traces.db from the test run
db_files = glob.glob('/tmp/**/traces.db', recursive=True)
if not db_files:
    # Check test output directories
    db_files = glob.glob('tests_rlm_adk/**/traces.db', recursive=True)

if db_files:
    db = max(db_files, key=os.path.getmtime)
    conn = sqlite3.connect(db)
    rows = conn.execute('''
        SELECT key, value, key_depth
        FROM session_state_events
        WHERE key_depth > 0
        ORDER BY id
        LIMIT 5
    ''').fetchall()
    conn.close()

    if rows:
        print(f'Child state events in {db}:')
        for key, value, depth in rows:
            v = str(value)[:60]
            print(f'  depth={depth} key={key} value={v}')
        print(f'PROOF: Child dispatch happened at depth > 0')
    else:
        print('No child state events found (run the e2e test first)')
else:
    print('No traces.db found (run the e2e test first)')
"
```
**Expected output**: Shows `key_depth > 0` rows proving child orchestrator ran

## Verification Checklist
- [ ] Fixture scripts exactly 3 responses (reasoning, worker, reasoning)
- [ ] Contract test passes with thread bridge enabled
- [ ] Contract test FAILS with `RLM_REPL_THREAD_BRIDGE=0` (proving it requires the bridge)
- [ ] traces.db shows child state events at depth > 0
- [ ] This could NOT pass if the skill function's `llm_query()` call were not bridged because the function body is opaque bytecode that the AST rewriter cannot transform
