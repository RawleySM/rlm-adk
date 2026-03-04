# Comprehensive Request Body Verification (G1-G9)

*2026-03-04T13:55:28Z by Showboat 0.6.0*
<!-- showboat-id: 0783f319-db71-4ae8-a64a-5db26b98bbd3 -->

This demo verifies that ALL data flowing through the RLM pipeline actually lands in the LLM request bodies — closing 9 gaps (G1-G9) identified in a data flow audit.

**Gaps closed:**
- G1: Dict-typed state key in dynamic instruction
- G2: Variable persistence across REPL iterations
- G3: Prior worker result chaining into next worker prompt
- G4: Multiple data sources combined in single worker prompt
- G5: Data loaded from REPL globals (not hardcoded inline)
- G6: functionResponse variables dict fidelity (nested dict, list)
- G7: Worker systemInstruction content
- G8: Worker generationConfig (temperature)
- G9: Dynamic instruction re-injection across all reasoning iterations

**Fixture:** 5-call flow (reasoning1 → worker1 → reasoning2 → worker2 → reasoning3)
**Runtime change:** contract_runner.py supports initial_repl_globals injection

## 1. Fixture Config — Dict State Key + REPL Globals

The fixture injects a nested dict as test_context (G1) and two REPL globals (G5):

```bash
grep -n "initial_state\|initial_repl_globals\|DICT_STATE\|_repo_xml_data\|_test_metadata\|experiment_id\|parameters\|tags\|METADATA" tests_rlm_adk/fixtures/provider_fake/request_body_comprehensive.json | head -15
```

```output
10:    "initial_state": {
12:        "\u00abDICT_STATE_START\u00bb": true,
13:        "experiment_id": "exp-42",
14:        "parameters": {"learning_rate": 0.001, "epochs": 10, "batch_size": 32},
15:        "tags": ["test", "roundtrip", "comprehensive"],
16:        "\u00abDICT_STATE_END\u00bb": true
19:    "initial_repl_globals": {
20:      "_repo_xml_data": "\u00abREPO_XML_START\u00bb <repository name=\"test-repo\"><file path=\"main.py\">print('hello world')</file><file path=\"utils.py\">def add(a,b): return a+b</file></repository> \u00abREPO_XML_END\u00bb",
21:      "_test_metadata": {
22:        "\u00abMETADATA_START\u00bb": true,
25:        "\u00abMETADATA_END\u00bb": true
33:      "note": "Reasoning iter 1: reads _repo_xml_data (REPL global string, simulating pack_repo output), reads _test_metadata (REPL global dict), combines both into llm_query prompt. Tests G4 (combined sources) and G5 (REPL globals injection).",
45:                      "code": "repo_xml = _repo_xml_data\nmetadata = _test_metadata\ncombined_prompt = \"\u00abCOMBINED_PROMPT_START\u00bb Analyze this repository:\\n\" + repo_xml + \"\\n\\nWith metadata: \" + str(metadata) + \" \u00abCOMBINED_PROMPT_END\u00bb\"\nresult = llm_query(combined_prompt)\nprint(result)\nprint(\"\u00abSTDOUT_SENTINEL_START\u00bb stdout from iteration 1 \u00abSTDOUT_SENTINEL_END\u00bb\")"
```

## 2. Runtime Change — contract_runner initial_repl_globals Support

The _make_repl helper injects REPL globals from fixture config, supporting both plain values and mock functions:

```bash
grep -n "def _make_repl\|initial_repl_globals\|mock_return\|repl.globals\[key\]\|LocalREPL" tests_rlm_adk/provider_fake/contract_runner.py
```

```output
36:from rlm_adk.repl.local_repl import LocalREPL
92:def _make_repl(router: ScenarioRouter) -> LocalREPL | None:
93:    """Create a LocalREPL pre-loaded with initial_repl_globals from fixture config.
96:    the ``$mock_return`` sentinel::
98:        "initial_repl_globals": {
99:            "pack_repo": {"$mock_return": "known XML string"},
103:    Returns None if no initial_repl_globals are configured.
105:    repl_globals_spec = router.config.get("initial_repl_globals")
109:    repl = LocalREPL(depth=1)
111:        if isinstance(value, dict) and "$mock_return" in value:
112:            return_value = value["$mock_return"]
113:            repl.globals[key] = lambda *args, _rv=return_value, **kwargs: _rv
115:            repl.globals[key] = value
```

## 3. Test Execution — 28 Tests, All GREEN

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_request_body_comprehensive.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
28 passed
```

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_request_body_verification.py tests_rlm_adk/test_request_body_comprehensive.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
51 passed
```

## 4. Evidence — Captured Request Bodies

5 captured requests from the comprehensive fixture (reasoning1 + worker1 + reasoning2 + worker2 + reasoning3):

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
print(f'Captured requests: {len(reqs)}')
for i, r in enumerate(reqs):
    keys = sorted(r.keys())
    caller = 'reasoning' if 'tools' in r else 'worker'
    print(f'  Call {i} ({caller}): {keys}')
"
```

```output
Captured requests: 5
  Call 0 (reasoning): ['contents', 'generationConfig', 'systemInstruction', 'tools']
  Call 1 (worker): ['contents', 'generationConfig', 'systemInstruction']
  Call 2 (reasoning): ['contents', 'generationConfig', 'systemInstruction', 'tools']
  Call 3 (worker): ['contents', 'generationConfig', 'systemInstruction']
  Call 4 (reasoning): ['contents', 'generationConfig', 'systemInstruction', 'tools']
```

### G1: Dict-typed state key lands in systemInstruction

The dict test_context (with nested parameters, tags list) is serialized via str() into the dynamic instruction and appended to systemInstruction:

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
si = json.dumps(reqs[0]['systemInstruction'], ensure_ascii=False)
for marker in ['DICT_STATE_START', 'DICT_STATE_END', 'exp-42', 'learning_rate', 'comprehensive']:
    print(f'  {marker}: {chr(70)+chr(79)+chr(85)+chr(78)+chr(68) if marker in si else chr(77)+chr(73)+chr(83)+chr(83)+chr(73)+chr(78)+chr(71)}')
"
```

```output
  DICT_STATE_START: FOUND
  DICT_STATE_END: FOUND
  exp-42: FOUND
  learning_rate: FOUND
  comprehensive: FOUND
```

### G5: REPL Globals in Worker Prompt + G4: Combined Sources

Worker 1 receives a combined prompt containing BOTH the repo XML (from _repo_xml_data global) AND the metadata dict (from _test_metadata global):

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
w1 = json.dumps(reqs[1], ensure_ascii=False)
for marker in ['COMBINED_PROMPT_START', 'COMBINED_PROMPT_END', 'REPO_XML_START', 'REPO_XML_END', 'METADATA_START', 'METADATA_END', 'test-repo', 'main.py', 'unit_test']:
    found = 'FOUND' if marker in w1 else 'MISSING'
    print(f'  Worker1 {marker}: {found}')
"
```

```output
  Worker1 COMBINED_PROMPT_START: FOUND
  Worker1 COMBINED_PROMPT_END: FOUND
  Worker1 REPO_XML_START: FOUND
  Worker1 REPO_XML_END: FOUND
  Worker1 METADATA_START: FOUND
  Worker1 METADATA_END: FOUND
  Worker1 test-repo: FOUND
  Worker1 main.py: FOUND
  Worker1 unit_test: FOUND
```

### G2+G3: Variable Persistence + Worker Result Chaining

Worker 2 receives a chained prompt containing the PRIOR worker result (from iter 1) plus persisted repo_xml and metadata (variable persistence across REPL iterations):

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
w2 = json.dumps(reqs[3], ensure_ascii=False)
for marker in ['CHAINED_PROMPT_START', 'CHAINED_PROMPT_END', 'WORKER_RESPONSE_1_START', 'arithmetic operations', 'REPO_XML_START', 'METADATA_START']:
    found = 'FOUND' if marker in w2 else 'MISSING'
    print(f'  Worker2 {marker}: {found}')
"
```

```output
  Worker2 CHAINED_PROMPT_START: FOUND
  Worker2 CHAINED_PROMPT_END: FOUND
  Worker2 WORKER_RESPONSE_1_START: FOUND
  Worker2 arithmetic operations: FOUND
  Worker2 REPO_XML_START: FOUND
  Worker2 METADATA_START: FOUND
```

### G6: functionResponse Variables Dict Fidelity

Call 2 (reasoning iter 2) functionResponse contains the variables dict with repo_xml (string), metadata (nested dict with markers), and result (worker 1 response):

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
r2 = json.dumps(reqs[2], ensure_ascii=False)
for marker in ['repo_xml', 'REPO_XML_START', 'METADATA_START', 'unit_test', '1.0.0']:
    found = 'FOUND' if marker in r2 else 'MISSING'
    print(f'  Call2 {marker}: {found}')
"
```

```output
  Call2 repo_xml: FOUND
  Call2 REPO_XML_START: FOUND
  Call2 METADATA_START: FOUND
  Call2 unit_test: FOUND
  Call2 1.0.0: FOUND
```

### G7+G8: Worker systemInstruction + generationConfig

Workers have their instruction text and temperature=0.0 in the request body:

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
for idx in [1, 3]:
    si = json.dumps(reqs[idx].get('systemInstruction', {}), ensure_ascii=False)
    gc = reqs[idx].get('generationConfig', {})
    temp = gc.get('temperature', 'N/A')
    has_answer = 'Answer' in si
    print(f'  Worker call {idx}: systemInstruction has Answer={has_answer}, temperature={temp}')
"
```

```output
  Worker call 1: systemInstruction has Answer=True, temperature=0.0
  Worker call 3: systemInstruction has Answer=True, temperature=0.0
```

### G9: Dynamic Instruction Re-injection Across All Iterations

The dict-typed test_context is re-injected into systemInstruction on every reasoning call (not just the first):

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/provider_fake/build_docs/captured_requests_comprehensive.json') as f:
    reqs = json.load(f)
for idx in [0, 2, 4]:
    si = json.dumps(reqs[idx].get('systemInstruction', {}), ensure_ascii=False)
    has_dict = 'DICT_STATE_START' in si and 'exp-42' in si
    print(f'  Reasoning call {idx}: dict_state_in_sysInstruction={has_dict}')
"
```

```output
  Reasoning call 0: dict_state_in_sysInstruction=True
  Reasoning call 2: dict_state_in_sysInstruction=True
  Reasoning call 4: dict_state_in_sysInstruction=True
```

## 5. Gap Coverage Matrix

| Gap | Description | Tests | Evidence |
|-----|-------------|-------|----------|
| G1 | Dict state key in dynamic instruction | test_g1_dict_state_in_system_instruction, test_g1_dict_state_nested_structure_preserved | DICT_STATE markers + exp-42 + learning_rate + comprehensive in systemInstruction |
| G2 | Variable persistence across iterations | test_g2_persisted_repo_xml_in_worker2, test_g2_persisted_metadata_in_worker2 | REPO_XML + METADATA markers in worker 2 prompt (persisted from iter 1) |
| G3 | Worker result chaining | test_g3_chained_prompt_markers, test_g3_prior_worker_result_in_chained_prompt, test_g3_chained_prompt_has_both_old_and_new_data | WORKER_RESPONSE_1 + REPO_XML in worker 2 chained prompt |
| G4 | Combined sources in single prompt | test_g4_combined_prompt_markers, test_g4_both_sources_in_combined_prompt | COMBINED_PROMPT wraps REPO_XML + METADATA in worker 1 |
| G5 | REPL globals injection | test_g5_repo_xml_in_worker1_prompt, test_g5_repo_xml_content_not_truncated, test_g5_metadata_dict_in_worker1_prompt | _repo_xml_data + _test_metadata globals reach worker prompt |
| G6 | functionResponse variables dict | test_g6_function_response_has_variables, test_g6_variables_contain_repo_xml, test_g6_variables_contain_metadata_dict | repo_xml, METADATA markers, unit_test, 1.0.0 in call 2 functionResponse |
| G7 | Worker systemInstruction | test_g7_worker_has_system_instruction | Answer in worker systemInstruction |
| G8 | Worker generationConfig | test_g8_worker_generation_config | temperature=0.0 confirmed |
| G9 | Dynamic instruction re-injection | test_g9_dynamic_instruction_in_reasoning_iter1/iter2/iter3 | DICT_STATE + exp-42 in all 3 reasoning calls |

Total: 28 tests (+ 23 from original suite = 51 request body verification tests)
