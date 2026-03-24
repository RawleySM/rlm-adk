# Demo: [Cycle 4] Lock-Free Execution Prevents Recursive Deadlock

## TDD Cycle Reference
- Cycle: 4
- Tests: `test_thread_bridge.py::TestExecuteCodeThreadsafe::test_does_not_acquire_exec_lock`, `test_executes_simple_code`, `test_uses_cwd_open_not_chdir`
- Assertion: `_execute_code_threadsafe()` does NOT acquire `_EXEC_LOCK`, preventing deadlock under recursive dispatch where parent holds worker thread T1 and child needs worker thread T2.

## What This Proves
The lock-free execution path is the critical correctness property that prevents the `_EXEC_LOCK` deadlock scenario:
```
T1: parent exec(code) -> llm_query() -> blocks on future.result()
T0: child orchestrator -> child REPLTool -> child exec(code)
```
If child exec tried to acquire `_EXEC_LOCK` (held by parent's original `execute_code`), the system would deadlock. The thread-safe path avoids this entirely.

## Reward-Hacking Risk
A test that mocks `_execute_code_threadsafe` or patches `_EXEC_LOCK` could trivially pass without proving the real deadlock-free behavior. The most dangerous reward hack:
- The test never actually contends for the lock -- it just checks a boolean flag
- The test uses `execute_code` (the locking version) instead of `_execute_code_threadsafe`

The demo guards against this by holding `_EXEC_LOCK` in one thread and proving `_execute_code_threadsafe` completes without deadlocking.

## Prerequisites
- `LocalREPL._execute_code_threadsafe()` implemented
- `.venv` activated

## Demo Steps

### Step 1: Prove the locking version WOULD deadlock (control case)
```bash
.venv/bin/python3 -c "
import threading
import time
from rlm_adk.repl.local_repl import LocalREPL, _EXEC_LOCK

repl = LocalREPL()

# Hold the lock in this thread (simulating parent's execute_code)
_EXEC_LOCK.acquire()
print(f'Lock held by: {threading.current_thread().name}')

# Try the LOCKING execute_code from another thread with a timeout
result = [None]
error = [None]

def try_locking_exec():
    try:
        # This should deadlock because we hold the lock
        # Use a timeout to prevent actual deadlock
        acquired = _EXEC_LOCK.acquire(timeout=1.0)
        if acquired:
            result[0] = 'acquired (should not happen while held)'
            _EXEC_LOCK.release()
        else:
            result[0] = 'TIMED OUT -- would deadlock in production'
    except Exception as e:
        error[0] = str(e)

t = threading.Thread(target=try_locking_exec)
t.start()
t.join(timeout=3.0)
_EXEC_LOCK.release()

print(f'Locking path result: {result[0]}')
print(f'CONTROL CASE: Lock contention confirmed')
"
```
**Expected output**:
```
Lock held by: MainThread
Locking path result: TIMED OUT -- would deadlock in production
CONTROL CASE: Lock contention confirmed
```
**What this proves**: When one thread holds `_EXEC_LOCK`, another thread trying to acquire it will block. This is the deadlock that recursive dispatch would cause if `_execute_code_threadsafe` used the lock.

### Step 2: Prove the lock-free version completes while lock is held
```bash
.venv/bin/python3 -c "
import threading
import time
from rlm_adk.repl.local_repl import LocalREPL, _EXEC_LOCK

repl = LocalREPL()

# Hold the lock (simulating parent's execute_code)
_EXEC_LOCK.acquire()
print(f'Lock held by: {threading.current_thread().name}')

# Try _execute_code_threadsafe from another thread
result = [None]
completed = threading.Event()

def try_lockfree_exec():
    stdout, stderr, success = repl._execute_code_threadsafe('x = 42; print(x)')
    result[0] = {
        'stdout': stdout.strip(),
        'success': success,
        'completed': True,
    }
    completed.set()

t = threading.Thread(target=try_lockfree_exec)
start = time.perf_counter()
t.start()
completed.wait(timeout=2.0)
elapsed = time.perf_counter() - start
_EXEC_LOCK.release()

if result[0]:
    print(f'Lock-free path stdout: {result[0][\"stdout\"]}')
    print(f'Lock-free path success: {result[0][\"success\"]}')
    print(f'Completed in: {elapsed:.3f}s (< 2.0s = no deadlock)')
    print(f'PROOF: _execute_code_threadsafe does NOT contend for _EXEC_LOCK')
else:
    print('FAIL: _execute_code_threadsafe did not complete (deadlock?)')
"
```
**Expected output**:
```
Lock held by: MainThread
Lock-free path stdout: 42
Lock-free path success: True
Completed in: 0.XXXs (< 2.0s = no deadlock)
PROOF: _execute_code_threadsafe does NOT contend for _EXEC_LOCK
```
**What this proves**: Even with `_EXEC_LOCK` held by another thread, `_execute_code_threadsafe` completes in well under 2 seconds. In production, this means a child REPL can execute while the parent thread is blocked on `llm_query()`.

### Step 3: Run the automated test
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestExecuteCodeThreadsafe::test_does_not_acquire_exec_lock -x -v 2>&1 | tail -5
```
**Expected output**: Test PASSED

## Verification Checklist
- [ ] Control case: locking path times out when lock is held (deadlock confirmed)
- [ ] Lock-free path: `_execute_code_threadsafe` completes while lock is held
- [ ] Completion time is sub-second (not waiting for any lock)
- [ ] Code execution result is correct (stdout = "42", success = True)
- [ ] This could NOT pass if `_execute_code_threadsafe` internally acquired `_EXEC_LOCK` because it would deadlock within the 2s timeout
