# Lineage/Completion/State Planes — 3-Depth E2E Verification

*2026-03-19T18:27:39Z by Showboat 0.6.1*
<!-- showboat-id: 83b8907c-5387-46c5-b112-8fac6b1c304d -->

## Fixture Design

The `lineage_completion_planes` fixture is a 9-call scenario exercising all three observability planes simultaneously:

- **State plane**: Minimal working state (iteration_count, should_stop, final_response_text)
- **Lineage plane**: Per-model/tool-call provenance via LineageEnvelope + SQLite telemetry
- **Completion plane**: In-memory CompletionEnvelope on agents (not session state)

Coverage matrix: 3 depths (0→1→2), 2 fanout indices, 2 parent iterations, both `execute_code` and `set_model_response` decision modes, custom schema (ChildResult) and default (ReasoningOutput).

```bash
python3 -c "
import json
f = json.load(open('tests_rlm_adk/fixtures/provider_fake/agent_challenge/lineage_completion_planes.json'))
print(f'scenario_id: {f[\"scenario_id\"]}')
print(f'responses: {len(f[\"responses\"])} model calls')
print(f'depths: 0, 1, 2')
print(f'expected total_model_calls: {f[\"expected\"][\"total_model_calls\"]}')
print(f'expected total_iterations: {f[\"expected\"][\"total_iterations\"]}')
"
```

```output
scenario_id: lineage_completion_planes
responses: 9 model calls
depths: 0, 1, 2
expected total_model_calls: 9
expected total_iterations: 2
```

## Response Sequence (9 calls, deterministic with RLM_MAX_CONCURRENT_CHILDREN=1)

Each call maps to a specific depth, fanout, and decision mode:

```bash
python3 -c "
import json
f = json.load(open('tests_rlm_adk/fixtures/provider_fake/agent_challenge/lineage_completion_planes.json'))
for r in f['responses']:
    idx = r['call_index']
    caller = r['caller']
    part = r['body']['candidates'][0]['content']['parts'][0]
    if 'functionCall' in part:
        tool = part['functionCall']['name']
    else:
        tool = 'text'
    print(f'  call {idx}: {caller:10s} -> {tool}')
"
```

```output
  call 0: reasoning  -> execute_code
  call 1: worker     -> execute_code
  call 2: worker     -> set_model_response
  call 3: worker     -> set_model_response
  call 4: worker     -> execute_code
  call 5: worker     -> set_model_response
  call 6: reasoning  -> execute_code
  call 7: worker     -> set_model_response
  call 8: reasoning  -> set_model_response
```

## Depth-0 REPL Code (Call 0)

The parent reasoning agent defines ChildResult, dispatches `llm_query_batched(K=2)` with schema, and prints diagnostic state:

```bash
python3 -c "
import json
f = json.load(open('tests_rlm_adk/fixtures/provider_fake/agent_challenge/lineage_completion_planes.json'))
code = f['responses'][0]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
print(code)
"
```

```output
from pydantic import BaseModel
class ChildResult(BaseModel):
    answer: str
    confidence: float

state = _rlm_state
print(f"[D0_T0] iteration_count={state.get('iteration_count')}")
print(f"[D0_T0] current_depth={state.get('current_depth')}")
print(f"[D0_T0] should_stop={state.get('should_stop')}")

prompts = ["Analyze item A in depth", "Analyze item B briefly"]
results = llm_query_batched(prompts, output_schema=ChildResult)
print(f"[D0_T0] DISPATCH num_results={len(results)}")
for i, r in enumerate(results):
    print(f"[D0_T0] CHILD_{i} error={r.error} parsed={r.parsed}")
```

## GROUP H Tests — All 6 Pass

Six test functions covering all three planes:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k 'lineage' -m 'agent_challenge' -q --no-header 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
6 passed, 60 deselected
```

## Proof A: State Plane

Session state values after the 9-call run completes:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k 'lineage_state_plane' -m 'agent_challenge' -s --no-header 2>&1 | grep -E 'final_answer=|iteration_count=|should_stop='
```

```output
  final_answer='Multi-depth analysis complete: items A and B analyzed across 3 depth levels with'
  iteration_count=2
  should_stop=True
```

## Proof B: Lineage Plane (SQLite Telemetry)

The SqliteTracingPlugin captures model_call and tool_call rows at every depth. Row counts prove all 9 model calls and both tool types are tracked across 3 depths:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k 'lineage_sqlite_telemetry' -m 'agent_challenge' -s --no-header 2>&1 | grep -E 'model_call rows:|tool_call rows:|max_depth_reached='
```

```output
  model_call rows: d0=3 d1=5 d2=1 total=9
  tool_call rows: execute_code=4 set_model_response=5
  max_depth_reached=2
```

## Proof C: Lineage Plane (Plugin Model Events)

The LineageAssertionPlugin captures before/after_model callbacks at every depth. This proves child orchestrators inherit the plugin_manager and lineage attrs are correctly propagated:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k 'lineage_plugin_model_events' -m 'agent_challenge' -s --no-header 2>&1 | grep -E 'model events:|d0 schemas:|d1 events'
```

```output
  model events: d0=3 d1=5 d2=1
  d0 schemas: {'ReasoningOutput'}
  d1 events with parent_depth: 5
```

## Proof D: Tool Decision Modes

Both `execute_code` (4 calls at depths 0, 1) and `set_model_response` (5 calls at depths 0, 1, 2) are captured by the plugin. This proves both decision paths work across the full depth tree:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k 'lineage_plugin_tool_events' -m 'agent_challenge' -s --no-header 2>&1 | grep -E 'execute_code:|set_model_response:|exec depths:|smr depths:'
```

```output
  execute_code: 4 before, 4 after
  set_model_response: 5 before
  exec depths: [0, 1]
  smr depths: [0, 1, 2]
```

## Proof E: Completion Plane

Terminal CompletionEnvelopes captured via after_agent_callback across all 3 depth levels. Each shows terminal=True, mode=structured, and the correct output schema (ChildResult for d1 batch children, ReasoningOutput for d0 parent and d2 grandchild):

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k 'lineage_completion_plane' -m 'agent_challenge' -s --no-header 2>&1 | grep -E 'total completions:|d=|completion depths:'
```

```output
  total completions: 10
    d=2 f=0 agent=child_reasoning_d2 terminal=True mode=structured schema=ReasoningOutput
    d=None f=None agent=child_orchestrator_d2 terminal=True mode=structured schema=ReasoningOutput
    d=1 f=0 agent=child_reasoning_d1 terminal=True mode=structured schema=ChildResult
    d=None f=None agent=child_orchestrator_d1 terminal=True mode=structured schema=ChildResult
    d=1 f=1 agent=child_reasoning_d1 terminal=True mode=structured schema=ChildResult
    d=None f=None agent=child_orchestrator_d1 terminal=True mode=structured schema=ChildResult
    d=1 f=0 agent=child_reasoning_d1 terminal=True mode=structured schema=ReasoningOutput
    d=None f=None agent=child_orchestrator_d1 terminal=True mode=structured schema=ReasoningOutput
    d=0 f=0 agent=reasoning_agent terminal=True mode=structured schema=ReasoningOutput
    d=None f=None agent=rlm_orchestrator terminal=True mode=structured schema=ReasoningOutput
  completion depths: [0, 1, 2]
```

## No Regressions

The default test suite (279 contract tests) still passes with the new fixture and plugin additions:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/ -q --no-header 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//' | sed 's/ (.*)//' | head -1
```

```output
279 passed, 92 deselected
```
