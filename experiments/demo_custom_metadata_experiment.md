# custom_metadata Dispatch Simplification — Proof of Collision-Free Fan-Out

*2026-03-19T10:36:36Z by Showboat 0.6.0*
<!-- showboat-id: 75646bfd-f2b2-4f7d-b910-fdbf00ebebb5 -->

Proves that `LlmResponse.custom_metadata` and depth-scoped state keys carry **correct, distinct values** for K=2 fan-out child dispatch. Full plugin stack (ObservabilityPlugin + SqliteTracingPlugin) enabled. Zero vacuous assertions — every test prints actual values then asserts against fixture-defined token counts.

**Architectural finding (H5):** custom_metadata only fires for the root reasoning agent. Children use production callbacks, so child data flows via depth-scoped state keys + SQLite telemetry. This is documented honestly, not hidden.

## H1: Root custom_metadata carries CORRECT token values from fixture

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest experiments/test_custom_metadata_e2e.py::test_h1_custom_metadata_correct_values -s --tb=no -q 2>&1 | grep -E "^  (Event [0-9]|PROOF|PASSED)" | head -10
```

```output
  Event 0: depth=0, input_tokens=250, output_tokens=120, thoughts_tokens=30, finish_reason=STOP, visible_text='I will analyze the two reviews using batched dispatch.'
  Event 1: depth=0, input_tokens=400, output_tokens=60, thoughts_tokens=15, finish_reason=STOP, visible_text=''
  PROOF: seen input_tokens across root events = [250, 400]
  PROOF: expected root input_tokens = [250, 400]
  PROOF: matched = [250, 400]
  PASSED: custom_metadata carries correct token VALUES
```

## H2: Depth-scoped state_delta keys with exact values per depth layer

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest experiments/test_custom_metadata_e2e.py::test_h2_state_delta_depth_scoped_values -s --tb=no -q 2>&1 | grep -E "^    reasoning_|^  PROOF" | head -20
```

```output
    reasoning_finish_reason = 'STOP'
    reasoning_input_tokens = 250
    reasoning_output_tokens = 120
    reasoning_prompt_chars = 167
    reasoning_system_chars = 27800
    reasoning_thought_text = ''
    reasoning_thought_tokens = 30
    reasoning_visible_output_text = 'I will analyze the two reviews using batched dispatch.'
    reasoning_finish_reason@d1 = 'STOP'
    reasoning_input_tokens@d1 = 220
    reasoning_output_tokens@d1 = 40
    reasoning_thought_text@d1 = ''
    reasoning_visible_output_text@d1 = ''
    reasoning_finish_reason = 'STOP'
    reasoning_input_tokens = 400
    reasoning_output_tokens = 60
    reasoning_prompt_chars = 221
    reasoning_system_chars = 27852
    reasoning_thought_text = ''
    reasoning_thought_tokens = 15
```

Depth-0 keys (`reasoning_input_tokens=250`, `=400`) coexist with depth-1 keys (`reasoning_input_tokens@d1=220`) — no collision. The `@d1` suffix scopes child state independently.

## H3: SQLite telemetry shows DISTINCT token counts per child — 6 model calls, zero collisions

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest experiments/test_custom_metadata_e2e.py::test_h3_fanout_no_collision_with_values -s --tb=no -q 2>&1 | grep -E "^    (agent=|Child [01] final)|^  PROOF" | head -15
```

```output
  PROOF: Both children have distinct summary keys -- no collision
    Child 0 final_answer: 'Review A is positive'
    Child 1 final_answer: 'Review B is negative'
    agent=reasoning_agent, depth=0, input=250, output=120, thoughts=30, finish=STOP
    agent=child_reasoning_d1, depth=1, input=100, output=50, thoughts=20, finish=STOP
    agent=child_reasoning_d1, depth=1, input=120, output=30, thoughts=0, finish=STOP
    agent=child_reasoning_d1, depth=1, input=200, output=75, thoughts=35, finish=STOP
    agent=child_reasoning_d1, depth=1, input=220, output=40, thoughts=0, finish=STOP
    agent=reasoning_agent, depth=0, input=400, output=60, thoughts=15, finish=STOP
  PROOF: Child model call input_tokens = [100, 120, 200, 220]
  PROOF: Child 0 fixture values {120, 100}: FOUND
  PROOF: Child 1 fixture values {200, 220}: FOUND
  PROOF: DISTINCT token counts prove collision-free dispatch
```

Six telemetry rows: 2 root (`reasoning_agent`, depth=0) + 4 child (`child_reasoning_d1`, depth=1). Child 0 has input tokens {100, 120}, child 1 has {200, 220} — matching fixture values exactly. `obs:child_summary@d1f0` and `@d1f1` carry distinct final answers.

## H5: Honest architectural finding — custom_metadata does NOT reach children

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest experiments/test_custom_metadata_e2e.py::test_h5_child_completion_via_state -s --tb=no -q 2>&1 | grep -E "^  (FINDING|REASON|  +depth|PROOF)" | head -15
```

```output
  FINDING: No child events have custom_metadata.
  REASON: Children use production callbacks, not experimental.
      depth=0 (reasoning_visible_output_text): ''
      depth=1 (reasoning_visible_output_text@d1): ''
      depth=0 (reasoning_thought_text): ''
      depth=1 (reasoning_thought_text@d1): ''
      depth=0 (reasoning_finish_reason): 'STOP'
      depth=1 (reasoning_finish_reason@d1): 'STOP'
      depth=0 (reasoning_input_tokens): 400
      depth=1 (reasoning_input_tokens@d1): 220
      depth=0 (reasoning_output_tokens): 60
      depth=1 (reasoning_output_tokens@d1): 40
      depth=0 (reasoning_thought_tokens): 15
      depth=1 (reasoning_thought_tokens@d1): None
  PROOF: depth-0 input_tokens = 400
```

Children spawned via `create_child_orchestrator` get their own `reasoning_agent` with the production `reasoning_after_model` callback — NOT the experimental one. So `custom_metadata` only works for root events. Child data is accessible via depth-scoped state keys (depth=0 vs depth=1 shown above). Migration Phase 1 must wire `custom_metadata` writing in the production callback to cover children too.

## All 7 tests pass

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest experiments/test_custom_metadata_e2e.py -v --tb=no 2>&1 | grep -E "^(experiments/|=)" | sed "s/ in [0-9.]*s//"
```

```output
============================= test session starts ==============================
experiments/test_custom_metadata_e2e.py::test_h1_custom_metadata_correct_values PASSED [ 14%]
experiments/test_custom_metadata_e2e.py::test_h2_state_delta_depth_scoped_values PASSED [ 28%]
experiments/test_custom_metadata_e2e.py::test_h3_fanout_no_collision_with_values PASSED [ 42%]
experiments/test_custom_metadata_e2e.py::test_h4_custom_metadata_field_completeness PASSED [ 57%]
experiments/test_custom_metadata_e2e.py::test_h5_child_completion_via_state PASSED [ 71%]
experiments/test_custom_metadata_e2e.py::test_h6_sqlite_telemetry_completeness PASSED [ 85%]
experiments/test_custom_metadata_e2e.py::test_h7_session_state_final_verification PASSED [100%]
============================== 7 passed ===============================
```

## No production regressions

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/ -q --tb=no 2>&1 | grep -E "^[0-9]+ passed" | sed "s/ in [0-9.]*s.*//"
```

```output
279 passed, 86 deselected
```
