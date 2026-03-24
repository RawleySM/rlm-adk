# Demo: [Cycles 22-24] E2E Three-Plane Verification -- State, Telemetry, Trace

## TDD Cycle Reference
- Cycle: 22 -- State/event plane (`TestSkillThreadBridgeStateEvents`)
- Cycle: 23 -- Telemetry plane (`TestSkillThreadBridgeTelemetry`)
- Cycle: 24 -- Trace plane (`TestSkillThreadBridgeTracePlane`)
- Tests: `test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeStateEvents::*`, `TestSkillThreadBridgeTelemetry::*`, `TestSkillThreadBridgeTracePlane::*`
- Assertion: All three observability planes capture correct data through the thread bridge execution path.

## What This Proves
The thread bridge changes the execution path inside `REPLTool.run_async()`. If any part of the telemetry/state/trace pipeline assumes the old async rewriter path, it could silently produce empty or incorrect rows. These tests verify that:
1. **State plane**: `session_state_events` has skill expansion metadata, REPL results, child events
2. **Telemetry plane**: `telemetry` table has model call rows, tool call rows with correct `decision_mode`
3. **Trace plane**: `final_state` has `execution_mode: "thread_bridge"` and `llm_calls >= 1`

## Reward-Hacking Risk
These tests query SQLite tables after a provider-fake run. The risk is:
- Pre-populated database rows that exist regardless of whether the pipeline ran
- Assertions that check row COUNT instead of row CONTENT (count could match by accident)
- Assertions against the `traces` table summary row (which is written on run completion) without verifying the individual `telemetry` rows that feed it

The demo guards against this by:
1. Running the SAME fixture as Cycle 21 (same `_run()` helper, single pipeline execution)
2. Querying specific column values (not just counts)
3. Cross-referencing across planes (e.g., `execution_mode` in trace plane matches what telemetry captured)

## Prerequisites
- ALL Phase 1-5 cycles implemented
- Provider-fake e2e fixture passing (Cycle 21)
- `.venv` activated

## Demo Steps

### Step 1: Run ALL three-plane tests and capture results
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py -k "StateEvents or Telemetry or TracePlane" -x -v 2>&1 | tail -25
```
**Expected output**: All state, telemetry, and trace plane tests PASSED

### Step 2: Inspect the state plane -- skill expansion metadata
```bash
.venv/bin/python3 -c "
import sqlite3, glob, os

db_files = glob.glob('/tmp/**/traces.db', recursive=True)
if db_files:
    db = max(db_files, key=os.path.getmtime)
    conn = sqlite3.connect(db)

    print('=== STATE PLANE: Skill Expansion Events ===')
    rows = conn.execute('''
        SELECT key, substr(value, 1, 80) as val_preview
        FROM session_state_events
        WHERE key LIKE '%repl_did_expand%'
           OR key LIKE '%repl_skill_expansion_meta%'
           OR key LIKE '%repl_submitted_code%'
        ORDER BY id
    ''').fetchall()
    for key, val in rows:
        print(f'  {key}: {val}')

    print()
    print('=== STATE PLANE: Child Events (depth > 0) ===')
    rows = conn.execute('''
        SELECT key, key_depth, substr(value, 1, 60) as val_preview
        FROM session_state_events
        WHERE key_depth > 0
        LIMIT 5
    ''').fetchall()
    for key, depth, val in rows:
        print(f'  depth={depth} {key}: {val}')

    conn.close()
else:
    print('Run Cycle 21 e2e test first to generate traces.db')
"
```
**Expected output**: Shows `repl_did_expand`, `repl_skill_expansion_meta`, `repl_submitted_code` rows, plus child events at depth > 0.
**What this proves**: The state/event plane captured skill expansion metadata AND child state events through the thread bridge.

### Step 3: Inspect the telemetry plane -- tool calls and model calls
```bash
.venv/bin/python3 -c "
import sqlite3, glob, os

db_files = glob.glob('/tmp/**/traces.db', recursive=True)
if db_files:
    db = max(db_files, key=os.path.getmtime)
    conn = sqlite3.connect(db)

    print('=== TELEMETRY PLANE: Tool Invocations ===')
    rows = conn.execute('''
        SELECT tool_name, decision_mode, repl_llm_calls, repl_wall_time_ms
        FROM telemetry
        WHERE event_type = 'tool_call'
        ORDER BY id
    ''').fetchall()
    for name, mode, llm_calls, wall_ms in rows:
        print(f'  tool={name} decision_mode={mode} llm_calls={llm_calls} wall_ms={wall_ms}')

    print()
    print('=== TELEMETRY PLANE: Model Calls ===')
    rows = conn.execute('''
        SELECT agent_name, prompt_tokens, completion_tokens
        FROM telemetry
        WHERE event_type = 'model_call'
        ORDER BY id
    ''').fetchall()
    for agent, pt, ct in rows:
        print(f'  agent={agent} prompt_tokens={pt} completion_tokens={ct}')

    conn.close()
else:
    print('Run Cycle 21 e2e test first')
"
```
**Expected output**: Shows `execute_code` tool call with `repl_llm_calls >= 1` (proving child dispatch happened through REPLTool) and model calls for both reasoning and worker agents.
**What this proves**: Telemetry correctly attributed the tool call to `execute_code` with `decision_mode` set, and captured the child LLM call count.

### Step 4: Inspect the trace plane -- execution_mode in final state
```bash
.venv/bin/python3 -c "
import sqlite3, glob, os, json

db_files = glob.glob('/tmp/**/traces.db', recursive=True)
if db_files:
    db = max(db_files, key=os.path.getmtime)
    conn = sqlite3.connect(db)

    print('=== TRACE PLANE: Run Status ===')
    rows = conn.execute('''
        SELECT status, total_model_calls, total_tool_calls
        FROM traces
        LIMIT 1
    ''').fetchall()
    for status, mc, tc in rows:
        print(f'  status={status} model_calls={mc} tool_calls={tc}')

    print()
    print('=== TRACE PLANE: Execution Mode in LAST_REPL_RESULT ===')
    rows = conn.execute('''
        SELECT key, value
        FROM session_state_events
        WHERE key LIKE '%last_repl_result%'
        ORDER BY id DESC
        LIMIT 1
    ''').fetchall()
    for key, val in rows:
        try:
            parsed = json.loads(val) if isinstance(val, str) else val
            exec_mode = parsed.get('execution_mode', 'NOT FOUND')
            llm_calls = parsed.get('llm_calls_made', 'NOT FOUND')
            print(f'  execution_mode: {exec_mode}')
            print(f'  llm_calls_made: {llm_calls}')
        except (json.JSONDecodeError, AttributeError):
            print(f'  raw value: {str(val)[:100]}')

    conn.close()
else:
    print('Run Cycle 21 e2e test first')
"
```
**Expected output**: Shows `execution_mode: thread_bridge` and `llm_calls_made: True` in the LAST_REPL_RESULT state key.
**What this proves**: The trace plane correctly records that the thread bridge execution path was used, not the AST rewriter.

## Verification Checklist
- [ ] State plane: `repl_did_expand`, `repl_skill_expansion_meta` rows exist
- [ ] State plane: child state events at depth > 0 exist
- [ ] Telemetry plane: `execute_code` tool call has `repl_llm_calls >= 1`
- [ ] Telemetry plane: model calls for both reasoning and worker agents
- [ ] Trace plane: `execution_mode` is `"thread_bridge"` (not `"sync"` or `"async_rewrite"`)
- [ ] Trace plane: run status is `"completed"`
- [ ] This could NOT pass if the thread bridge were broken because the skill function would crash on `llm_query()`, the REPL would capture a RuntimeError in stderr, the child worker response would never be consumed, and telemetry would show 0 llm_calls
