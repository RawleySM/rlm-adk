# Demo: [Cycle 11] `llm_query_fn` Auto-Injection from REPL Globals

## TDD Cycle Reference
- Cycle: 11
- Tests: `test_skill_loader.py::TestLlmQueryFnInjection::test_wrapper_injects_from_globals`, `test_wrapper_respects_explicit_llm_query_fn`, `test_wrapper_raises_when_no_llm_query_available`
- Assertion: The `_wrap_with_llm_query_injection` wrapper reads `llm_query` from REPL globals at call time and injects it as `llm_query_fn`. Explicit `llm_query_fn` is respected. Missing `llm_query` raises `RuntimeError`.

## What This Proves
Skill functions declare `llm_query_fn` as a parameter. The wrapper auto-injects it from REPL globals so the skill function can call LLM dispatch without knowing about the thread bridge plumbing. This is the mechanism that makes skills both REPL-callable and unit-testable.

## Reward-Hacking Risk
A test could:
- Set `llm_query_fn` directly in the kwargs (testing explicit injection, not auto-injection)
- Use a wrapper that always injects regardless of parameter inspection
- Mock `repl_globals` with `llm_query` already set at wrap time rather than call time (missing lazy binding)

The demo guards against this by:
1. Proving lazy binding: `llm_query` is NOT in globals at wrap time, only at call time
2. Proving parameter inspection: a function WITHOUT `llm_query_fn` is NOT wrapped
3. Proving explicit override: passing `llm_query_fn` directly skips globals lookup

## Prerequisites
- `rlm_adk/skills/loader.py` with `_wrap_with_llm_query_injection` implemented
- `.venv` activated

## Demo Steps

### Step 1: Prove lazy binding -- globals can be empty at wrap time
```bash
.venv/bin/python3 -c "
from rlm_adk.skills.loader import _wrap_with_llm_query_injection, _has_llm_query_fn_param

# Define a skill function
def my_skill(x, *, llm_query_fn=None):
    return llm_query_fn(f'process {x}')

# Create empty REPL globals (llm_query not wired yet)
repl_globals = {}

# Wrap the function -- this should NOT fail even though llm_query is missing
wrapped = _wrap_with_llm_query_injection(my_skill, repl_globals)
print(f'Wrapped successfully: {wrapped.__name__}')

# Now wire llm_query into globals (simulating orchestrator wiring AFTER wrap)
repl_globals['llm_query'] = lambda prompt: f'RESULT: {prompt}'

# Call the wrapped function -- it should pick up llm_query from globals NOW
result = wrapped('hello')
print(f'Result: {result}')
print(f'LAZY BINDING PROOF: llm_query was not in globals at wrap time, only at call time')
"
```
**Expected output**:
```
Wrapped successfully: my_skill
Result: RESULT: process hello
LAZY BINDING PROOF: llm_query was not in globals at wrap time, only at call time
```
**What this proves**: The wrapper captures a reference to the `repl_globals` dict (not its contents). At call time, it reads `llm_query` from the dict. This is critical because in production, the orchestrator wires skill globals BEFORE wiring `llm_query` -- lazy binding makes the order not matter.

### Step 2: Prove explicit `llm_query_fn` overrides globals
```bash
.venv/bin/python3 -c "
from rlm_adk.skills.loader import _wrap_with_llm_query_injection

def my_skill(x, *, llm_query_fn=None):
    return llm_query_fn(f'process {x}')

repl_globals = {'llm_query': lambda p: 'FROM_GLOBALS'}
wrapped = _wrap_with_llm_query_injection(my_skill, repl_globals)

# Call with explicit llm_query_fn -- should use THIS, not globals
result = wrapped('test', llm_query_fn=lambda p: 'FROM_EXPLICIT')
print(f'Result: {result}')
print(f'OVERRIDE PROOF: explicit llm_query_fn took precedence over globals')
"
```
**Expected output**:
```
Result: FROM_EXPLICIT
OVERRIDE PROOF: explicit llm_query_fn took precedence over globals
```
**What this proves**: In unit tests, you can pass a mock `llm_query_fn` directly. The wrapper does not override it.

### Step 3: Prove missing `llm_query` raises helpful error
```bash
.venv/bin/python3 -c "
from rlm_adk.skills.loader import _wrap_with_llm_query_injection

def my_skill(x, *, llm_query_fn=None):
    return llm_query_fn(f'process {x}')

repl_globals = {}  # Never wired
wrapped = _wrap_with_llm_query_injection(my_skill, repl_globals)

try:
    wrapped('test')
    print('FAIL: should have raised')
except RuntimeError as e:
    print(f'Correct error: {e}')
    print(f'SAFETY PROOF: missing llm_query raises clear error, not silent None')
"
```
**Expected output**:
```
Correct error: llm_query not available in REPL globals when calling my_skill(). Ensure dispatch closures are wired.
SAFETY PROOF: missing llm_query raises clear error, not silent None
```

### Step 4: Run the automated tests
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestLlmQueryFnInjection -x -v 2>&1 | tail -10
```
**Expected output**: All `TestLlmQueryFnInjection` tests PASSED

## Verification Checklist
- [ ] Lazy binding: wrapper works when globals are empty at wrap time
- [ ] Lazy binding: wrapper picks up `llm_query` at call time
- [ ] Override: explicit `llm_query_fn` parameter takes precedence
- [ ] Safety: missing `llm_query` raises `RuntimeError` with function name
- [ ] This could NOT pass if the wrapper captured `llm_query` eagerly at wrap time (it would be None/missing)
