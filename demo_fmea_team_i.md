# FMEA Team I: AST Rewriter & REPL Execution Edge Cases

*2026-03-01 by Showboat 0.6.0*

## FM-06: AST Rewriter Alias Blindness (RPN=18, Pathway: P3/P5)

**Failure Mode:** When REPL code aliases `llm_query` to another name (e.g.,
`q = llm_query; q("prompt")`), the AST detection function `has_llm_calls()`
fails to recognize the aliased callable as an LLM call. The code is routed to
the synchronous `execute_code()` path, where `llm_query` is the sync stub that
raises `RuntimeError` because no event loop is available for the underlying
async dispatch.

**Risk:** RPN=18 (S=3, O=2, D=3). Residual risk is low because the
`RuntimeError` is caught by the sync `execute_code()` exception handler and
surfaced to the model in `stderr`. However, the error message may be confusing
to the model -- it does not explain that the alias bypassed async routing.

**Source Code Inspection:**

The detection gate is `has_llm_calls()` in `rlm_adk/repl/ast_rewriter.py` lines 15-36:

```python
# rlm_adk/repl/ast_rewriter.py lines 15-36
def has_llm_calls(code: str) -> bool:
    """Check if code contains llm_query or llm_query_batched calls.

    Uses AST parsing to detect calls accurately (not just string matching,
    which could match comments or string literals).

    Returns False if code has syntax errors (will be caught during execution).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in (
                "llm_query",
                "llm_query_batched",
            ):
                return True
    return False
```

The routing decision in `REPLTool.run_async()` at `rlm_adk/tools/repl_tool.py` lines 107-119:

```python
# rlm_adk/tools/repl_tool.py lines 107-119
        try:
            if has_llm_calls(code):
                llm_calls_made = True
                tree = rewrite_for_async(code)
                compiled = compile(tree, "<repl>", "exec")
                # Merge globals and locals so _repl_exec sees variables from
                # previous executions (imports, user-defined vars, etc.)
                ns = {**self.repl.globals, **self.repl.locals}
                exec(compiled, ns)
                repl_exec_fn = ns["_repl_exec"]
                result = await self.repl.execute_code_async(code, repl_exec_fn, trace=trace)
            else:
                result = self.repl.execute_code(code, trace=trace)
```

The `LlmCallRewriter.visit_Call()` at `rlm_adk/repl/ast_rewriter.py` lines 55-67 has the same limitation -- it only rewrites `ast.Name` nodes:

```python
# rlm_adk/repl/ast_rewriter.py lines 55-67
    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Transform sync LM calls to async await expressions."""
        # Transform children first (handles nested calls like
        # llm_query(llm_query("inner")))
        self.generic_visit(node)

        if isinstance(node.func, ast.Name) and node.func.id in self._SYNC_TO_ASYNC:
            # Replace function name with async variant
            node.func.id = self._SYNC_TO_ASYNC[node.func.id]
            # Wrap in Await node
            return ast.Await(value=node)

        return node
```

**How the code handles FM-06:**

1. **Detection miss:** `has_llm_calls()` walks the AST and looks for `ast.Call`
   nodes where `node.func` is an `ast.Name` with `id` in `("llm_query",
   "llm_query_batched")`. The code `q = llm_query; q("prompt")` produces an
   `ast.Call` where `node.func` is `ast.Name(id="q")`, which does not match.
   The function returns `False`.

2. **Sync routing:** Because `has_llm_calls()` returns `False`, `REPLTool.run_async()`
   takes the `else` branch at line 119 and calls `self.repl.execute_code(code)`,
   the synchronous path.

3. **Sync stub failure:** In the sync execution namespace, `llm_query` is the
   sync stub function. When REPL code executes `q = llm_query` it captures a
   reference to this stub. Calling `q("prompt")` invokes the sync stub, which
   attempts to call the async dispatch closure without an event loop context,
   raising `RuntimeError`.

4. **Error recovery:** The `except Exception as e` handler at line 301 of
   `local_repl.py` catches the `RuntimeError` and populates `stderr`. The model
   receives the error and can retry with direct `llm_query("prompt")` syntax.

**Testability Assessment:** Unit test. This failure mode does not require a
full provider-fake e2e test. A direct unit test can call `has_llm_calls()` with
alias patterns and verify the return value. A second unit test can verify that
`LlmCallRewriter` does not transform aliased calls.

**Recommended Test Scenario:**

```python
def test_has_llm_calls_misses_alias():
    """FM-06: Alias blindness -- has_llm_calls returns False for aliased calls."""
    code = 'q = llm_query\nresult = q("prompt")'
    assert has_llm_calls(code) is False  # Documents the known gap

def test_has_llm_calls_direct_call():
    """Control: has_llm_calls detects direct calls."""
    code = 'result = llm_query("prompt")'
    assert has_llm_calls(code) is True
```

**Gaps:**
- No unit test documents this known detection limitation.
- No fixture exercises the alias pattern end-to-end.
- If a future fix adds alias tracking (e.g., data-flow analysis of assignment
  targets), there is no regression test to verify it works.

---

## FM-07: AST Rewriter -- List Comprehension with llm_query (RPN=16, Pathway: P5)

**Failure Mode:** REPL code uses `[llm_query(p) for p in prompts]` -- a list
comprehension containing an LLM call. The AST rewriter transforms this to
`[await llm_query_async(p) for p in prompts]` inside `async def _repl_exec()`.
On Python 3.11+, this is valid because comprehensions inside async functions
inherit the async context. On Python < 3.11, async comprehensions had
restrictions that could cause `SyntaxError`.

**Risk:** RPN=16 (S=2, O=2, D=4). The current codebase targets Python 3.11+
(see `pyproject.toml`), so this works correctly in the supported environment.
The residual risk is a latent compatibility issue if the codebase were ever
backported to Python 3.10 or earlier.

**Source Code Inspection:**

The `rewrite_for_async()` function at `rlm_adk/repl/ast_rewriter.py` lines 161-228 wraps all rewritten code in `async def _repl_exec()`:

```python
# rlm_adk/repl/ast_rewriter.py lines 178-228
    # Parse original code
    tree = ast.parse(code)

    # Transform LM calls to async awaits
    rewriter = LlmCallRewriter()
    tree = rewriter.visit(tree)

    # Promote any sync functions that now contain await to async def,
    # and wrap their call sites with await (transitively).
    _promote_functions_to_async(tree)

    # Take all statements from the module body
    body_stmts = tree.body

    # Add 'return locals()' at the end so the caller can extract
    # variables created during execution
    return_locals = ast.Return(
        value=ast.Call(
            func=ast.Name(id="locals", ctx=ast.Load()),
            args=[],
            keywords=[],
        )
    )
    body_stmts.append(return_locals)

    # Create async def _repl_exec(): <body>
    async_func = ast.AsyncFunctionDef(
        name="_repl_exec",
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        ),
        body=body_stmts,
        decorator_list=[],
        returns=None,
        type_comment=None,
        type_params=[],
    )

    # Create new module with just the async function definition
    new_module = ast.Module(body=[async_func], type_ignores=[])

    # Fix missing line numbers (required for compile())
    ast.fix_missing_locations(new_module)

    return new_module
```

The `LlmCallRewriter.visit_Call()` at lines 55-67 transforms `llm_query(p)` to
`await llm_query_async(p)` without special handling for comprehension contexts:

```python
# rlm_adk/repl/ast_rewriter.py lines 55-67
    def visit_Call(self, node: ast.Call) -> ast.AST:
        """Transform sync LM calls to async await expressions."""
        self.generic_visit(node)

        if isinstance(node.func, ast.Name) and node.func.id in self._SYNC_TO_ASYNC:
            node.func.id = self._SYNC_TO_ASYNC[node.func.id]
            return ast.Await(value=node)

        return node
```

**How the code handles FM-07:**

1. **Detection:** `has_llm_calls()` correctly detects `llm_query(p)` inside the
   list comprehension because `ast.walk()` descends into all child nodes of the
   module, including the `ast.ListComp` generator body. The `ast.Call` node with
   `ast.Name(id="llm_query")` is found.

2. **Rewriting:** `LlmCallRewriter.visit_Call()` transforms the call to
   `await llm_query_async(p)`. The `ast.NodeTransformer` visits the `ast.Call`
   inside the comprehension via `generic_visit()`. There is no special-case
   logic for comprehensions -- the rewriter treats all `ast.Call` nodes
   uniformly regardless of their syntactic context.

3. **Wrapping:** `rewrite_for_async()` wraps the entire module body in
   `async def _repl_exec()`. The list comprehension
   `[await llm_query_async(p) for p in prompts]` ends up inside this async
   function body.

4. **Python 3.11+ validity:** In Python 3.11+, `await` expressions inside list
   comprehensions are valid when the comprehension is inside an `async def`
   function. The compiled code executes correctly.

5. **Sequential execution:** Note that
   `[await llm_query_async(p) for p in prompts]` executes each query
   **sequentially** (each `await` completes before the next iteration). This is
   functionally correct but suboptimal -- `llm_query_batched(prompts)` would
   dispatch all queries in parallel via `ParallelAgent`.

**Testability Assessment:** Unit test. The AST rewriting can be verified by
calling `rewrite_for_async()` on comprehension code and inspecting the resulting
AST. An integration test can compile and execute the rewritten code in an async
context to confirm it produces valid Python.

**Recommended Test Scenario:**

```python
import ast, sys

def test_list_comprehension_rewrite_produces_valid_ast():
    """FM-07: List comprehension with llm_query rewrites to valid async code."""
    code = 'results = [llm_query(p) for p in prompts]'
    tree = rewrite_for_async(code)
    compiled = compile(tree, "<test>", "exec")
    # Should not raise SyntaxError on Python 3.11+
    assert compiled is not None

def test_list_comprehension_detected_by_has_llm_calls():
    """FM-07: has_llm_calls detects llm_query inside list comprehension."""
    code = 'results = [llm_query(p) for p in prompts]'
    assert has_llm_calls(code) is True
```

**Gaps:**
- No unit test verifies that the rewritten comprehension compiles successfully.
- No test verifies that the rewritten code executes correctly in an async
  context (i.e., the `await` inside the comprehension actually resolves).
- No fixture exercises the list comprehension pattern end-to-end via
  provider-fake.
- The sequential-vs-parallel performance difference is undocumented -- a model
  using `[llm_query(p) for p in prompts]` instead of
  `llm_query_batched(prompts)` loses parallelism silently.

---

## FM-22: RecursionError from REPL Variable Serialization (RPN=25, Pathway: P8)

**Failure Mode:** REPL code creates a self-referential data structure (e.g.,
`d = {}; d['self'] = d`). When `REPLTool.run_async()` attempts to serialize
REPL variables for the tool response, `json.dumps(v)` raises `RecursionError`.
`RecursionError` is a subclass of `BaseException` (via `RecursionError` ->
`RuntimeError` -> `Exception`). However, the `except` clause only catches
`(TypeError, ValueError, OverflowError)`, so the `RecursionError` propagates
uncaught out of the variable serialization loop.

**Risk:** RPN=25 (S=5, O=1, D=5). The severity is moderate because the
uncaught exception propagates into ADK's tool dispatch machinery. Occurrence is
low because LLM-generated code rarely creates self-referential structures.
Detection is moderate -- the error traceback points to `json.dumps` but the
root cause (circular reference in REPL locals) may not be obvious.

**Source Code Inspection:**

The variable serialization code in `rlm_adk/tools/repl_tool.py` lines 148-159:

```python
# rlm_adk/tools/repl_tool.py lines 148-159
        # Extract JSON-serializable variables from REPL locals.
        # We attempt json.dumps to catch nested non-serializable objects
        # (e.g., a dict containing module references) that would cause ADK's
        # deepcopy to fail with TypeError.
        variables: dict[str, Any] = {}
        for k, v in result.locals.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                try:
                    json.dumps(v)
                    variables[k] = v
                except (TypeError, ValueError, OverflowError):
                    pass  # Skip non-serializable values
```

The `isinstance` check at line 154 passes `dict` and `list` types through to
`json.dumps()`. A self-referential dict like `d = {}; d['self'] = d` passes the
`isinstance(v, dict)` check, but `json.dumps(d)` hits Python's recursion limit.

**How the code handles FM-22:**

1. **Type gate passes:** The `isinstance(v, (int, float, str, bool, list, dict))`
   check at line 154 allows the self-referential dict through because it is
   indeed a `dict`.

2. **json.dumps raises RecursionError:** `json.dumps(v)` attempts to serialize
   the circular structure. The JSON encoder follows `d['self']` -> `d` ->
   `d['self']` -> ... until hitting Python's recursion limit (default 1000
   frames), then raises `RecursionError`.

3. **Exception escapes:** The `except (TypeError, ValueError, OverflowError)`
   clause at line 158 does **not** catch `RecursionError`. Although
   `RecursionError` is a subclass of `RuntimeError` which is a subclass of
   `Exception`, it is not listed in the except tuple. The `RecursionError`
   propagates up through `run_async()`.

4. **Outer catch:** The `except (Exception, asyncio.CancelledError)` at line
   120 of `repl_tool.py` **does** catch `RecursionError` (since it is an
   `Exception` subclass), so the tool returns a `stderr` error dict rather than
   crashing ADK. However, this means the entire tool response is an error --
   both `stdout` and `variables` are lost even though code execution itself
   succeeded.

**Correction to FMEA assessment:** The FMEA catalog states "propagates to ADK"
but the outer `except (Exception, asyncio.CancelledError)` at line 120 actually
catches it. The real impact is that a successful REPL execution's stdout and
variable state are discarded because the serialization step failed. The model
sees only an error, losing the execution results.

**Testability Assessment:** Unit test. This can be tested by creating a
`LocalREPL`, executing code that creates a circular reference, then calling the
serialization logic and verifying the behavior.

**Recommended Test Scenario:**

```python
import json
import pytest

def test_recursion_error_from_circular_dict():
    """FM-22: json.dumps on self-referential dict raises RecursionError,
    which is not caught by the (TypeError, ValueError, OverflowError) except."""
    d = {}
    d['self'] = d
    with pytest.raises(RecursionError):
        json.dumps(d)

def test_variable_serialization_should_skip_circular():
    """FM-22: Variable serialization should catch RecursionError and skip
    the circular variable instead of discarding the entire result."""
    # This test documents the gap: currently RecursionError is NOT caught
    # by the per-variable except clause.
    d = {}
    d['self'] = d
    variables = {}
    try:
        json.dumps(d)
        variables['d'] = d
    except (TypeError, ValueError, OverflowError):
        pass  # Current code -- RecursionError escapes
    except RecursionError:
        pass  # Proposed fix -- catch and skip
    # With current code, RecursionError would have propagated
```

**Gaps:**
- The `except` clause at line 158 is missing `RecursionError`. Adding it to the
  tuple (`except (TypeError, ValueError, OverflowError, RecursionError)`) would
  make the serialization skip the problematic variable instead of crashing the
  entire tool response.
- No unit test exercises circular data structures in REPL locals.
- No fixture creates self-referential structures in REPL code.
- The broader `except Exception` pattern would also work but is intentionally
  avoided to keep the exception handling precise.

---

## FM-26: Sync REPL Under _EXEC_LOCK with Infinite Loop (RPN=24, Pathway: P4a)

**Failure Mode:** The model generates REPL code containing an infinite loop
(e.g., `while True: pass`). The sync `execute_code()` method holds the
module-level `_EXEC_LOCK` (a `threading.Lock`) for the entire duration of
`exec()`. Because the loop never terminates, the lock is never released. All
subsequent sync REPL calls (from any REPL instance in the same process) block
indefinitely on `_EXEC_LOCK` acquisition, causing a complete system deadlock.

**Risk:** RPN=24 (S=8, O=1, D=3). Severity is high because the entire process
hangs and must be killed. Occurrence is low because models rarely generate
infinite loops. Detection is moderate -- the process becomes unresponsive and
the lock contention is diagnosable via thread dumps.

**Source Code Inspection:**

The `_EXEC_LOCK` definition at `rlm_adk/repl/local_repl.py` lines 76-79:

```python
# rlm_adk/repl/local_repl.py lines 76-79
# Module-level lock protecting process-global state (os.chdir, sys.stdout/stderr)
# during synchronous execute_code. Ensures concurrent REPLs running in threads
# do not race on CWD or output capture.
_EXEC_LOCK = threading.Lock()
```

The `execute_code()` method at `rlm_adk/repl/local_repl.py` lines 267-313:

```python
# rlm_adk/repl/local_repl.py lines 267-313
    def execute_code(self, code: str, trace: REPLTrace | None = None) -> REPLResult:
        """Execute code synchronously in the sandboxed namespace.

        Uses _EXEC_LOCK to serialize access to process-global state
        (os.chdir, sys.stdout/stderr) so that concurrent REPLs in
        threads do not race.
        """
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()
        trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))

        with _EXEC_LOCK, self._capture_output() as (stdout_buf, stderr_buf), self._temp_cwd():
            try:
                combined = {**self.globals, **self.locals}
                # ... trace instrumentation ...
                exec(instrumented, combined, combined)  # <-- line 291: blocks here forever

                # Update locals with new variables
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value

                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue()
                self._last_exec_error = None
            except Exception as e:
                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
                self._last_exec_error = f"{type(e).__name__}: {e}"

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )
```

The critical path is line 278: the `with _EXEC_LOCK` statement acquires the
lock, then line 291 calls `exec(instrumented, combined, combined)`. If the
code contains `while True: pass`, `exec()` never returns, and the `with` block
never exits, so `_EXEC_LOCK` is never released.

**How the code handles FM-26:**

1. **Lock acquisition:** The `with _EXEC_LOCK` at line 278 acquires the
   module-level `threading.Lock()`. This is a non-reentrant lock shared across
   all `LocalREPL` instances in the process.

2. **Unbounded exec():** The `exec()` call at line 291 executes the model's
   code in the combined namespace. There is no timeout mechanism -- `exec()`
   runs until the code completes or raises an exception. An infinite loop
   (`while True: pass`) will run forever.

3. **Lock held indefinitely:** Because `exec()` never returns, the `with` block
   never exits. The `_EXEC_LOCK.__exit__()` method (which calls `release()`) is
   never invoked. The lock remains acquired.

4. **Cascading deadlock:** Any subsequent call to `execute_code()` from any
   `LocalREPL` instance in the same process will block at `with _EXEC_LOCK`
   forever, because the lock is already held by the stuck thread.

5. **No external interruption:** Python's `threading.Lock` cannot be interrupted
   from another thread. `asyncio.wait_for()` cannot cancel a thread-based
   `exec()`. The only recovery is process termination (SIGKILL).

6. **Async path is immune:** `execute_code_async()` (lines 315-382) does not
   acquire `_EXEC_LOCK`. An infinite loop in async code would block the event
   loop but not hold the lock, and `asyncio.wait_for()` could cancel the
   coroutine (though this has its own complications per FM-13).

**Testability Assessment:** Not testable via provider-fake. The provider-fake
framework controls model responses but cannot inject execution timeouts into
the REPL. A targeted unit test could demonstrate the lock acquisition behavior
but would need careful handling to avoid actually hanging the test runner.

**Recommended Test Scenario:**

```python
import threading
import time

def test_exec_lock_held_during_long_execution():
    """FM-26: Demonstrate that _EXEC_LOCK is held for the entire duration
    of execute_code(), including during exec()."""
    from rlm_adk.repl.local_repl import LocalREPL, _EXEC_LOCK

    repl = LocalREPL()
    # Use a bounded sleep instead of infinite loop to keep test finite
    lock_acquired_during_exec = threading.Event()

    def probe_lock():
        """Try to acquire the lock -- if blocked, the exec is holding it."""
        acquired = _EXEC_LOCK.acquire(timeout=0.5)
        if not acquired:
            lock_acquired_during_exec.set()
        else:
            _EXEC_LOCK.release()

    # Start a thread that probes the lock while execute_code runs
    probe = threading.Thread(target=probe_lock)
    probe.start()
    repl.execute_code("import time; time.sleep(1)")  # Holds lock for 1s
    probe.join()

    assert lock_acquired_during_exec.is_set(), (
        "Lock should be held during exec() -- an infinite loop would hold it forever"
    )
    repl.cleanup()
```

**Gaps:**
- No execution timeout for `exec()` in the sync path. A `signal.alarm()` (Unix)
  or `concurrent.futures.ThreadPoolExecutor` with timeout could provide a kill
  mechanism, but neither is implemented.
- No test verifies the deadlock scenario (for obvious reasons -- it would hang).
- The async path (`execute_code_async`) avoids this specific failure mode but
  has its own issue (FM-13: `CancelledError` swallowed).
- The `_EXEC_LOCK` is a module-level singleton, so a single stuck execution
  affects all REPL instances in the process, not just the one running the
  infinite loop.

---

## FM-27: execute_code_async CWD Race Condition (RPN=32, Pathway: P4b)

**Failure Mode:** Two `LocalREPL` instances call `execute_code_async()`
concurrently on the same event loop. Both call `os.chdir(self.temp_dir)` to
set their working directory, then later `os.chdir(old_cwd)` to restore it.
Because `os.chdir()` modifies process-global state and the async path has no
lock, the interleaving can cause one REPL's file operations to execute in the
wrong directory.

**Risk:** RPN=32 (S=4, O=1, D=8). Severity is moderate because file operations
could read/write wrong files. Occurrence is very low because the current
architecture uses one REPL per orchestrator and orchestrators do not share REPL
instances. Detection is very difficult because the race is timing-dependent and
the symptoms (wrong file contents) may not be immediately attributable to CWD.

**Source Code Inspection:**

The sync path at `rlm_adk/repl/local_repl.py` lines 257-265 uses `_temp_cwd()`
inside `_EXEC_LOCK`:

```python
# rlm_adk/repl/local_repl.py lines 257-265
    @contextmanager
    def _temp_cwd(self):
        """Temporarily change to temp directory for execution."""
        old_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            yield
        finally:
            os.chdir(old_cwd)
```

And the sync `execute_code()` acquires `_EXEC_LOCK` before entering `_temp_cwd()`:

```python
# rlm_adk/repl/local_repl.py line 278
        with _EXEC_LOCK, self._capture_output() as (stdout_buf, stderr_buf), self._temp_cwd():
```

The async path at `rlm_adk/repl/local_repl.py` lines 315-382 performs the same
`os.chdir()` calls but **without any lock**:

```python
# rlm_adk/repl/local_repl.py lines 335-371
        old_cwd = os.getcwd()
        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf
            os.chdir(self.temp_dir)           # <-- line 338: unprotected chdir

            # ... async execution ...

            # Run the async _repl_exec function
            new_locals = await repl_exec_fn()  # <-- line 347: yields to event loop

            # ... result collection ...
        except Exception as e:
            # ... error handling ...
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            _capture_stdout.reset(tok_out)
            _capture_stderr.reset(tok_err)
            os.chdir(old_cwd)                  # <-- line 371: unprotected restore
```

The race condition window is between line 338 (`os.chdir(self.temp_dir)`) and
line 371 (`os.chdir(old_cwd)`). The `await repl_exec_fn()` at line 347 is an
async yield point -- the event loop may switch to another coroutine that also
calls `os.chdir()`.

**How the code handles FM-27:**

1. **Sync path is protected:** `execute_code()` acquires `_EXEC_LOCK` at line
   278 before calling `_temp_cwd()`. This serializes all sync REPL executions,
   ensuring no CWD race between concurrent sync calls.

2. **Async path is unprotected:** `execute_code_async()` calls
   `os.chdir(self.temp_dir)` at line 338 without acquiring any lock. The
   `_EXEC_LOCK` is a `threading.Lock` and cannot be used in async code (it
   would block the event loop). An `asyncio.Lock` would be needed instead.

3. **Yield point exposes race:** The `await repl_exec_fn()` at line 347 is a
   coroutine yield point. If another `execute_code_async()` coroutine is
   scheduled by the event loop during this `await`, it will call
   `os.chdir()` to its own `temp_dir`, overwriting the first coroutine's CWD.
   When the first coroutine resumes, `os.getcwd()` returns the second
   coroutine's temp directory.

4. **Architectural mitigation:** The current architecture creates exactly one
   `LocalREPL` per `RLMOrchestratorAgent`, and each orchestrator processes one
   request at a time. There is no codepath where two `execute_code_async()`
   calls run concurrently on the same event loop. This makes the race condition
   a latent rather than active vulnerability.

5. **ContextVar for stdout/stderr:** Note that the async path correctly uses
   `contextvars.ContextVar` for stdout/stderr capture (lines 329-330), which
   is task-local and does not race. The CWD is the only process-global
   resource that lacks async-safe protection.

**Testability Assessment:** Architectural analysis. This failure mode is not
exercisable via provider-fake (which uses a single REPL) or standard unit tests
(which would need to run two orchestrators concurrently). A targeted concurrency
test could demonstrate the race by running two `execute_code_async()` calls
with `asyncio.gather()`.

**Recommended Test Scenario:**

```python
import asyncio
import os

async def test_cwd_race_between_two_repls():
    """FM-27: Demonstrate CWD race condition in execute_code_async.
    Two REPLs executing concurrently may observe each other's temp_dir."""
    from rlm_adk.repl.local_repl import LocalREPL

    repl_a = LocalREPL()
    repl_b = LocalREPL()

    observed_cwds_a = []
    observed_cwds_b = []

    # Create trivial async functions that record CWD and yield
    async def exec_a():
        observed_cwds_a.append(os.getcwd())
        await asyncio.sleep(0)  # Yield to event loop
        observed_cwds_a.append(os.getcwd())
        return {}

    async def exec_b():
        observed_cwds_b.append(os.getcwd())
        await asyncio.sleep(0)  # Yield to event loop
        observed_cwds_b.append(os.getcwd())
        return {}

    await asyncio.gather(
        repl_a.execute_code_async("pass", exec_a),
        repl_b.execute_code_async("pass", exec_b),
    )

    # If race occurs, one REPL may observe the other's temp_dir
    # This test documents the race window -- it may or may not trigger
    # depending on event loop scheduling
    repl_a.cleanup()
    repl_b.cleanup()
```

**Gaps:**
- No `asyncio.Lock` protects `os.chdir()` in the async path.
- No concurrency test exists for `execute_code_async()`.
- The architectural mitigation (one REPL per orchestrator) is implicit and
  undocumented -- a future change adding REPL sharing or concurrent orchestration
  would expose this latent race.
- `os.chdir()` is inherently process-global. A more robust fix would avoid
  `os.chdir()` entirely and instead pass the working directory to subprocess
  calls or use `os.open()`/`os.fstat()` with directory file descriptors.

---

## Summary

| FM | Name | RPN | Testability | Current Coverage | Key Finding |
|----|------|-----|-------------|-----------------|-------------|
| FM-06 | AST Rewriter Alias Blindness | 18 | Unit test | Gap | `has_llm_calls()` and `LlmCallRewriter` only check `ast.Name` nodes; aliased callables (`q = llm_query; q()`) are invisible to detection and rewriting |
| FM-07 | AST Rewriter List Comprehension | 16 | Unit test | Gap | Rewrite produces valid `await` inside comprehension on Python 3.11+; sequential execution is correct but loses parallelism vs `llm_query_batched` |
| FM-22 | RecursionError Variable Serialization | 25 | Unit test | Gap | `except (TypeError, ValueError, OverflowError)` at `repl_tool.py:158` misses `RecursionError` from circular dicts; outer `except Exception` at line 120 catches it but discards all execution results |
| FM-26 | Sync REPL Infinite Loop Under Lock | 24 | Architectural | Gap | `exec()` at `local_repl.py:291` runs under `_EXEC_LOCK` with no timeout; infinite loop holds lock forever, deadlocking all sync REPL calls process-wide |
| FM-27 | execute_code_async CWD Race | 32 | Architectural | Gap | `os.chdir()` at `local_repl.py:338` is unprotected in async path; `await` at line 347 is a yield point where another coroutine can overwrite CWD; mitigated by one-REPL-per-orchestrator architecture |

**Key architectural insights:**

1. **Detection vs. rewriting symmetry.** FM-06 shows that `has_llm_calls()` and
   `LlmCallRewriter.visit_Call()` share the same `isinstance(func, ast.Name)`
   check. Any fix must update both functions consistently, or a detection miss
   will route code to the sync path while a rewriting miss will leave the async
   call un-transformed.

2. **Exception hierarchy matters.** FM-22 demonstrates that Python's exception
   hierarchy creates subtle gaps. `RecursionError` is a `RuntimeError`
   subclass, which is an `Exception` subclass. The per-variable `except` at
   `repl_tool.py:158` names three specific types but misses `RecursionError`.
   The simplest fix is adding `RecursionError` to the tuple. Using bare
   `except Exception` would also work but catches too broadly for a
   serialization probe.

3. **Sync vs. async protection asymmetry.** FM-26 and FM-27 show that the sync
   and async REPL paths have complementary weaknesses. The sync path has lock
   protection (preventing CWD races) but no execution timeout (enabling
   deadlock). The async path has no lock protection (enabling CWD races) but
   `asyncio.wait_for()` could theoretically cancel a stuck coroutine (though
   FM-13 shows that cancellation is swallowed). Neither path is fully hardened.
