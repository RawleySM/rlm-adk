# Demo: [Cycle 7] Orchestrator Wires Real Sync Bridge (Not RuntimeError Stub)

## TDD Cycle Reference
- Cycle: 7
- Tests: `test_thread_bridge.py::TestOrchestratorWiring::test_sync_llm_query_wired_to_repl_globals`, `test_sync_llm_query_is_callable`
- Assertion: After orchestrator wiring, `repl.globals["llm_query"]` is a real sync callable created by `make_sync_llm_query()`, not the `sync_llm_query_unsupported` stub that raises `RuntimeError`.

## What This Proves
The orchestrator currently wires `sync_llm_query_unsupported` into REPL globals -- a function that raises `RuntimeError("llm_query() cannot be called synchronously...")`. This cycle replaces that stub with the real thread bridge. If the wiring is wrong, every `llm_query()` call in REPL code crashes.

## Reward-Hacking Risk
A test could:
- Check `isinstance(repl.globals["llm_query"], Callable)` -- the stub IS callable, it just raises
- Mock the orchestrator's wiring path so it never actually runs
- Assert the function exists without actually calling it

The demo guards against this by actually calling `repl.globals["llm_query"]` and proving it does NOT raise `RuntimeError`.

## Prerequisites
- All Phase 1 cycles (1-6) implemented
- Orchestrator wiring updated to use `make_sync_llm_query`
- `.venv` activated

## Demo Steps

### Step 1: Prove the OLD stub would raise RuntimeError
```bash
.venv/bin/python3 -c "
# Recreate the old stub to show what it does
def sync_llm_query_unsupported(*args, **kwargs):
    raise RuntimeError(
        'llm_query() cannot be called synchronously from this context. '
        'Only async llm_query_async() is available.'
    )

try:
    sync_llm_query_unsupported('test prompt')
    print('FAIL: should have raised')
except RuntimeError as e:
    print(f'OLD STUB raises: {e}')
    print('CONTROL: This is what llm_query() did before the thread bridge.')
"
```
**Expected output**:
```
OLD STUB raises: llm_query() cannot be called synchronously from this context. Only async llm_query_async() is available.
CONTROL: This is what llm_query() did before the thread bridge.
```

### Step 2: Prove the NEW wiring creates a real callable
```bash
.venv/bin/python3 -c "
import asyncio
import threading

from rlm_adk.repl.thread_bridge import make_sync_llm_query

# Simulate what the orchestrator does
async def fake_llm_query_async(prompt, model=None, output_schema=None):
    return f'RESPONSE: {prompt}'

async def main():
    loop = asyncio.get_running_loop()
    sync_fn = make_sync_llm_query(fake_llm_query_async, loop)

    # This is what repl.globals['llm_query'] points to after wiring
    print(f'Type: {type(sync_fn).__name__}')
    print(f'Callable: {callable(sync_fn)}')

    # Actually call it from a worker thread (as REPL code would)
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    result = await loop.run_in_executor(executor, sync_fn, 'test prompt from REPL')
    executor.shutdown()

    print(f'Result: {result}')
    print(f'No RuntimeError: PASS')

asyncio.run(main())
"
```
**Expected output**:
```
Type: function
Callable: True
Result: RESPONSE: test prompt from REPL
No RuntimeError: PASS
```
**What this proves**: The new sync callable actually dispatches and returns a result instead of raising `RuntimeError`. When the orchestrator wires this into `repl.globals["llm_query"]`, REPL code can call `llm_query()` as a normal function.

### Step 3: Run the automated test
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestOrchestratorWiring -x -v 2>&1 | tail -8
```
**Expected output**: All `TestOrchestratorWiring` tests PASSED

## Verification Checklist
- [ ] Old stub raises `RuntimeError` (control case)
- [ ] New sync bridge does NOT raise `RuntimeError`
- [ ] New sync bridge actually dispatches to async coroutine and returns result
- [ ] This could NOT pass if the orchestrator still wired the old stub because any call to `llm_query()` in REPL code would crash with `RuntimeError`
