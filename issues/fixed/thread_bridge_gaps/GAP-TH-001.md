# GAP-TH-001: IPython singleton shell shared across concurrent worker threads without synchronization

**Severity**: HIGH
**Category**: threading
**Files**: `rlm_adk/repl/ipython_executor.py`, `rlm_adk/repl/local_repl.py`

## Problem

`IPythonDebugExecutor.__init__` calls `InteractiveShell.instance()` (line 97), which returns a process-wide singleton. When recursive `llm_query()` dispatch creates a child orchestrator that creates its own `LocalREPL` with its own `IPythonDebugExecutor`, both parent and child share the **same** `InteractiveShell` singleton.

Inside `execute_sync` (line 146-162), the executor temporarily replaces `shell.showtraceback` with a capture function, swaps `shell.user_ns` in `_execute_via_ipython` (line 235), and restores both in `finally` blocks. If two threads execute through the same shell concurrently (which happens when a parent thread is blocked on `future.result()` in `llm_query()` and a child thread starts executing via its own `_execute_code_threadsafe`), the `user_ns` swap and `showtraceback` monkey-patch race against each other.

Concrete scenario:
1. Parent REPL thread T1 enters `_execute_via_ipython`, sets `shell.user_ns = namespace_A` (line 235)
2. Parent code calls `llm_query()`, which dispatches to the event loop
3. Child orchestrator runs `execute_code_threaded` on thread T2
4. T2 enters `_execute_via_ipython`, sets `shell.user_ns = namespace_B` (line 235)
5. T1's code is still mid-execution inside `run_cell` -- but `user_ns` is now `namespace_B`
6. Variable resolution breaks, or worse, T1's code mutates T2's namespace

## Evidence

```python
# ipython_executor.py line 97
self._shell = shell_cls.instance()  # Process-wide singleton

# ipython_executor.py lines 222-250
def _execute_via_ipython(self, code, namespace):
    shell = self._shell
    old_ns = shell.user_ns
    shell.user_ns = namespace      # <-- Unsynchronized write to shared singleton
    try:
        result = shell.run_cell(code, silent=False, store_history=False)
    finally:
        shell.user_ns = old_ns     # <-- Restore races with concurrent set
```

The `_execute_code_threadsafe` path (used by the thread bridge) does NOT acquire `_EXEC_LOCK` by design. So there is no serialization of IPython shell access across threads.

## Suggested Fix

Two options:

**Option A (Recommended)**: Add a dedicated lock for IPython shell access in `IPythonDebugExecutor`. The `_EXEC_LOCK` was intentionally excluded from `_execute_code_threadsafe` to avoid deadlocks, but a separate per-executor lock (or a class-level shell lock) that protects only the IPython singleton would serialize `run_cell` calls without the CWD/stdout deadlock risk:

```python
_IPYTHON_LOCK = threading.Lock()

def execute_sync(self, code, namespace):
    ...
    if self._use_ipython and self._shell is not None:
        with _IPYTHON_LOCK:
            # shell.user_ns swap + run_cell + restore
```

The tradeoff: this serializes all IPython execution across all threads in the process. Under recursive dispatch this means a child REPL cannot execute while the parent's REPL thread holds the lock -- but since the parent thread is blocked on `future.result()`, it is NOT holding this lock (it left `execute_sync` and is waiting on the child). So the lock only prevents true concurrent execution, not the parent-blocks-on-child case.

**However**: there is a subtle issue. If parent thread T1 calls `execute_sync` -> enters `_execute_via_ipython` -> `run_cell` runs user code -> user code calls `llm_query()` which blocks on `future.result()`. At this point T1 is STILL inside `_execute_via_ipython`, still holding `_IPYTHON_LOCK`. The child's thread T2 would then deadlock waiting for the lock. So a simple lock would create a deadlock.

**Option B (Better)**: Use `backend="exec"` for child orchestrators or for the `_execute_code_threadsafe` path. Raw `exec()` does not use the IPython singleton. Since child orchestrators use condensed instructions and don't need rich tracebacks, this is a clean separation. Alternatively, create a fresh non-singleton `InteractiveShell` per executor (IPython supports this via `InteractiveShell()`  without `.instance()`).

**Option C**: Since parent code that calls `llm_query()` is paused mid-`run_cell` and the IPython shell's `user_ns` was already set for that call, the child's `user_ns` swap would corrupt the parent. Create a per-REPL IPython instance (not the singleton) by using `InteractiveShell()` directly instead of `InteractiveShell.instance()`.
