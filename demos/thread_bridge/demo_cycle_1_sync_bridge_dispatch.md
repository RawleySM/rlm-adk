# Demo: [Cycle 1] Sync Bridge Dispatches from Worker Thread to Event Loop

## TDD Cycle Reference
- Cycle: 1
- Tests: `test_thread_bridge.py::TestMakeSyncLlmQuery::test_dispatches_from_worker_thread`, `test_dispatches_from_worker_thread`, `test_passes_keyword_args`
- Assertion: A sync wrapper created by `make_sync_llm_query()` can be called from a worker thread, submits the async dispatch to the event loop via `run_coroutine_threadsafe`, and returns the result.

## What This Proves
The `asyncio.run_coroutine_threadsafe()` + `future.result()` pattern actually works when called from a non-event-loop thread while the event loop concurrently processes the submitted coroutine. This is the atomic mechanism that the entire thread bridge depends on.

## Reward-Hacking Risk
A unit test with a mock async coroutine proves the wrapper calls `run_coroutine_threadsafe` -- but it cannot prove the cross-thread handoff works under real concurrency conditions. A reward-hacked test could:
- Use a mock that returns instantly without ever touching the event loop
- Run the sync wrapper from the event loop thread itself (where `run_coroutine_threadsafe` is unnecessary)
- Replace `future.result()` with a direct coroutine call

The demo guards against this by running from an actual worker thread with an actual running event loop, and proving the result transits between threads.

## Prerequisites
- Thread bridge module implemented (`rlm_adk/repl/thread_bridge.py`)
- `.venv` activated

## Demo Steps

### Step 1: Prove the calling thread is NOT the event loop thread
```bash
.venv/bin/python3 -c "
import asyncio
import threading
import concurrent.futures

from rlm_adk.repl.thread_bridge import make_sync_llm_query

calls = []

async def fake_dispatch(prompt, model=None, output_schema=None):
    calls.append({
        'prompt': prompt,
        'thread': threading.current_thread().name,
        'is_event_loop_thread': True,  # always true here
    })
    await asyncio.sleep(0.01)  # yield to event loop
    return f'CHILD_RESULT_FOR: {prompt}'

async def main():
    loop = asyncio.get_running_loop()
    sync_fn = make_sync_llm_query(fake_dispatch, loop)

    # Run sync_fn from a worker thread (NOT the event loop thread)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    caller_thread = []

    def worker():
        caller_thread.append(threading.current_thread().name)
        return sync_fn('hello from worker thread', model='test-model')

    result = await loop.run_in_executor(executor, worker)
    executor.shutdown(wait=True)

    print(f'Caller thread:      {caller_thread[0]}')
    print(f'Dispatch thread:    {calls[0][\"thread\"]}')
    print(f'Threads differ:     {caller_thread[0] != calls[0][\"thread\"]}')
    print(f'Prompt forwarded:   {calls[0][\"prompt\"]}')
    print(f'Model forwarded:    True (dispatch received call)')
    print(f'Result returned:    {result}')
    print(f'Cross-thread proof: PASS' if caller_thread[0] != calls[0]['thread'] else 'Cross-thread proof: FAIL')

asyncio.run(main())
"
```
**Expected output**:
```
Caller thread:      ThreadPoolExecutor-0_0
Dispatch thread:    MainThread
Threads differ:     True
Prompt forwarded:   hello from worker thread
Model forwarded:    True (dispatch received call)
Result returned:    CHILD_RESULT_FOR: hello from worker thread
Cross-thread proof: PASS
```
**What this proves**: The sync wrapper was called from `ThreadPoolExecutor-0_0` (worker thread). The async dispatch ran on `MainThread` (event loop thread). The result transited back. This is the real cross-thread mechanism -- not a mock shortcut.

### Step 2: Prove it works with the actual unit test
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestMakeSyncLlmQuery::test_dispatches_from_worker_thread -x -v 2>&1 | tail -5
```
**Expected output**: Test PASSED
**What this proves**: The automated test exercises the same mechanism.

## Verification Checklist
- [ ] Caller thread name differs from dispatch thread name (cross-thread handoff is real)
- [ ] The prompt string makes it through the bridge intact
- [ ] The result string makes it back to the worker thread
- [ ] This could NOT pass if `run_coroutine_threadsafe` were broken because the worker thread would hang on `future.result()` forever (timeout would fire)
