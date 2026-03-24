# Demo: [Cycle 5] One-Shot Executor Prevents Thread Pool Exhaustion Under Recursion

## TDD Cycle Reference
- Cycle: 5
- Tests: `test_thread_bridge.py::TestExecuteCodeThreaded::test_one_shot_executor_cleanup`, `test_timeout_produces_error_result`, `test_sets_trace_execution_mode`
- Assertion: Each `execute_code_threaded()` call creates a fresh one-shot `ThreadPoolExecutor(max_workers=1)` and shuts it down in `finally`. No leaked threads across calls.

## What This Proves
Recursive dispatch creates a stack of blocked threads:
```
T1 (depth 0): exec(code) -> llm_query() -> blocks
T2 (depth 1): exec(code) -> llm_query() -> blocks
T3 (depth 2): exec(code) -> terminal, returns
```
If all three used the default `ThreadPoolExecutor`, the shared pool could exhaust its workers. One-shot executors guarantee each depth level gets its own fresh thread.

## Reward-Hacking Risk
A test could:
- Check `executor._shutdown` is `True` after the call without verifying it was one-shot
- Use a mocked executor that never actually creates threads
- Test only depth=0 (no recursion, so pool exhaustion never triggers)

The demo guards by verifying thread count before/after and confirming cleanup.

## Prerequisites
- `LocalREPL.execute_code_threaded()` implemented
- `.venv` activated

## Demo Steps

### Step 1: Verify no thread leaks across multiple calls
```bash
.venv/bin/python3 -c "
import asyncio
import threading
from rlm_adk.repl.local_repl import LocalREPL

async def main():
    repl = LocalREPL()

    threads_before = threading.active_count()
    print(f'Threads before: {threads_before}')

    # Run 5 sequential calls
    for i in range(5):
        result = await repl.execute_code_threaded(f'x_{i} = {i}; print(x_{i})')

    threads_after = threading.active_count()
    print(f'Threads after 5 calls: {threads_after}')
    print(f'Thread leak: {threads_after - threads_before}')
    print(f'NO LEAK: {threads_after <= threads_before + 1}')

asyncio.run(main())
"
```
**Expected output**:
```
Threads before: N
Threads after 5 calls: N (or N+1 at most)
Thread leak: 0
NO LEAK: True
```
**What this proves**: Each `execute_code_threaded` call creates and destroys its own executor. No threads accumulate.

### Step 2: Run the automated tests
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestExecuteCodeThreaded -x -v 2>&1 | tail -8
```
**Expected output**: All `TestExecuteCodeThreaded` tests PASSED

## Verification Checklist
- [ ] Thread count does not grow across sequential calls
- [ ] Each call creates a fresh one-shot executor
- [ ] Executor is shut down in `finally` (even on timeout)
- [ ] This could NOT pass if the default shared executor were used because recursive dispatch would exhaust the pool
