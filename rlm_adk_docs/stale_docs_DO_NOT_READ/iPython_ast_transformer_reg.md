<!-- validated: 2026-03-15 -->

# IPython Feature 4: AST Transformer Registration

## Executive Summary

This document analyzes the feasibility and risks of registering the custom
`LlmCallRewriter` AST transformer into IPython's built-in `ast_transformers`
pipeline instead of invoking it manually in `REPLTool.run_async()`. The
proposal would let IPython handle parse-transform-compile-execute as a single
`run_cell()` call, potentially eliminating the dual sync/async execution paths
and the manual `async def _repl_exec(): ... return locals()` wrapper.

**Verdict: HIGH RISK, LOW REWARD.** The current manual pipeline is well-tested
and gives the codebase precise control over namespace propagation, async
wrapping, transitive function promotion, trace injection, and concurrency
isolation. IPython's `ast_transformers` pipeline was designed for interactive
notebook use and does not provide the control surfaces needed here. The
migration would introduce at least five breaking risks (detailed below) for
marginal code reduction. **Recommendation: do not pursue this migration.**

---

## Current Architecture

```
REPLTool.run_async()
  |
  |-- expand_skill_imports(code)      # synthetic import expansion
  |
  |-- has_llm_calls(exec_code)?       # AST scan for llm_query / llm_query_batched
  |     |
  |     |-- YES (async path):
  |     |     rewrite_for_async(exec_code)
  |     |       1. ast.parse(code)
  |     |       2. LlmCallRewriter.visit(tree)     # llm_query -> await llm_query_async
  |     |       3. _promote_functions_to_async()    # transitive closure
  |     |       4. Wrap in: async def _repl_exec(): <body>; return locals()
  |     |     compile(tree, "<repl>", "exec")
  |     |     LocalREPL.execute_code_async(compiled=...)
  |     |       IPythonDebugExecutor.execute_async(compiled, ns)
  |     |         exec(compiled, namespace)         # installs _repl_exec
  |     |         new_locals = await _repl_exec()   # runs the async wrapper
  |     |       Merge new_locals into self.locals
  |     |
  |     |-- NO (sync path):
  |           LocalREPL.execute_code(exec_code, trace)
  |             _execute_code_inner() under _EXEC_LOCK
  |               IPythonDebugExecutor.execute_sync(instrumented, combined)
  |                 shell.run_cell(code)  OR  exec(code, ns, ns)
  |               Merge combined back into self.locals
  |
  |-- flush_fn()  # dispatch accumulator -> tool_context.state
  |-- Write LAST_REPL_RESULT
```

### Key design decisions in current architecture:

1. **Explicit async wrapping**: `rewrite_for_async()` wraps code in
   `async def _repl_exec(): ... return locals()`. This guarantees `await`
   expressions are inside a coroutine. The caller then does
   `await _repl_exec()` to get the locals dict back.

2. **Transitive function promotion**: `_promote_functions_to_async()` handles
   the case where a user-defined function calls `llm_query()` -- that function
   must become `async def` and its call sites must be `await`-ed. This runs in
   a fixpoint loop until stable.

3. **Dual execution paths**: sync code (no `llm_query`) runs through
   `execute_code()` with `_EXEC_LOCK` and thread-pool timeout. Async code runs
   through `execute_code_async()` without the lock.

4. **Namespace propagation via `return locals()`**: The async wrapper returns
   `locals()` so that variables created during async execution flow back to the
   REPL's persistent namespace.

5. **Trace injection**: sync path prepends/appends trace header/footer as raw
   strings before execution. Async path sets `trace.start_time` directly in
   Python, not via code injection.

---

## Proposed Architecture (IPython AST Transformer Registration)

```
IPythonDebugExecutor.__init__()
  shell = InteractiveShell.instance()
  shell.ast_transformers.append(LlmCallRewriter())

REPLTool.run_async()
  |-- expand_skill_imports(code)
  |-- shell.run_cell(exec_code)        # IPython does:
  |     1. transform_cell(raw_cell)    # string transforms (magics, etc.)
  |     2. ast_parse(cell)             # parse to AST
  |     3. transform_ast(code_ast)     # <-- LlmCallRewriter runs here
  |     4. should_run_async(cell)      # detect await in compiled code
  |     5. run_ast_nodes()             # compile + exec/eval per node
  |        If async: await eval(code_obj, user_global_ns, user_ns)
  |        If sync:  exec(code_obj, user_global_ns, user_ns)
  |-- Read results from shell.user_ns
```

---

## Detailed Risk Analysis

### RISK-1: Namespace Propagation Mismatch (CRITICAL)

**Current behavior**: `rewrite_for_async()` appends `return locals()` to the
wrapped function body. The caller receives a dict of all variables created
during execution and merges them into `self.locals`.

**IPython behavior**: `run_code()` does `exec(code_obj, self.user_global_ns,
self.user_ns)` or `await eval(code_obj, ...)`. Variables created during
execution are written directly into `user_ns`. There is no `return locals()`
mechanism.

**Problem**: The current architecture uses a *separate* namespace
(`{**self.globals, **self.locals}`) per execution, then selectively merges
results back (filtering underscored names). IPython's `run_cell` modifies
`user_ns` in place. To use IPython's pipeline, we would need to:
- Set `shell.user_ns` to our combined namespace before each `run_cell`
- After execution, diff the namespace to find new variables
- Handle the case where IPython adds its own internal variables (`_`, `__`,
  `___`, `_i`, `_ii`, `_oh`, `_dh`, `In`, `Out`, etc.)

The current `_execute_via_ipython()` already does a namespace swap
(lines 168-181 of `ipython_executor.py`), but this only works for the sync
path. The async path bypasses `run_cell` entirely.

**Severity**: If the async path goes through `run_cell`, namespace propagation
semantics change. The `return locals()` pattern gives an explicit snapshot;
IPython's in-place mutation gives no such snapshot and introduces IPython's own
internal state variables into the REPL namespace.

### RISK-2: Transitive Function Promotion Not Supported (CRITICAL)

**Current behavior**: `_promote_functions_to_async()` detects when a
user-defined function contains `await` (because `LlmCallRewriter` transformed
`llm_query()` calls inside it) and promotes:
- `def foo(): ... await llm_query_async(...)` -> `async def foo(): ...`
- Call sites: `foo()` -> `await foo()`

This runs as a fixpoint loop, handling transitive chains (e.g., `bar()` calls
`foo()` which calls `llm_query()`).

**IPython behavior**: `transform_ast()` simply calls `transformer.visit(node)`
for each registered transformer. It does not run any fixpoint loop. The
`LlmCallRewriter.visit()` only transforms `llm_query()` -> `await
llm_query_async()` -- it does *not* promote containing functions to async.

**Problem**: If we register only `LlmCallRewriter` as an AST transformer, the
transitive promotion step is lost. We would need to either:
1. Create a *compound* transformer that does both LlmCallRewriter + promotion
   in a single `visit()` call, OR
2. Register a second transformer for promotion

Option 1 is viable but means we still maintain essentially the same code --
just invoked via a different entry point. No simplification.

**Severity**: Without transitive promotion, any user code like
`def helper(): return llm_query("x")` followed by `result = helper()` would
produce `SyntaxError: 'await' outside function` or `TypeError: object
coroutine can't be used in 'await' expression` depending on context.

### RISK-3: IPython's `should_run_async()` Detection Mismatch (HIGH)

**Current behavior**: `has_llm_calls()` uses AST walking to detect
`llm_query`/`llm_query_batched` calls. If found, the entire code block is
wrapped in `async def _repl_exec()` and executed asynchronously.

**IPython behavior**: `should_run_async()` calls `_should_be_async()` which
compiles the code with `PyCF_ALLOW_TOP_LEVEL_AWAIT` and checks the
`CO_COROUTINE` flag. This detects `await`, `async for`, `async with` in the
*compiled* code.

**Problem**: The AST transformer runs *after* `should_run_async()` is called.
Looking at the `run_cell()` flow:

```python
# interactiveshell.py:3214
elif self.should_run_async(raw_cell, ...):  # <-- checks ORIGINAL code
    runner = self.loop_runner                # <-- async runner
else:
    runner = _pseudo_sync_runner             # <-- sync runner
```

But `transform_ast()` runs inside `run_cell_async()` at line 3433, *after*
the runner decision. So `should_run_async()` examines the *original* code
(before AST transformation), which does NOT contain `await` expressions yet.
The runner decision will always pick `_pseudo_sync_runner` for code containing
`llm_query()` but no explicit `await`.

This means the code would be transformed to contain `await` expressions but
then executed with the pseudo-sync runner, which would fail with:
`RuntimeError: ... needs a real async loop`.

**Workaround**: Override `should_run_async()` to also check for `llm_query`
calls. But this adds complexity rather than removing it.

### RISK-4: Singleton InteractiveShell and Concurrency (HIGH)

**Current behavior**: `InteractiveShell.instance()` returns a process-global
singleton. The current code uses `_EXEC_LOCK` for sync execution and
task-local `ContextVar` streams for async execution. The async path bypasses
`shell.run_cell()` entirely (it uses raw `exec()` + `await`).

**Problem**: If we route async execution through `shell.run_cell()`, the
singleton shell's `ast_transformers` list is shared across all concurrent
executions. The transformers themselves are stateless (`LlmCallRewriter` has no
instance state), so this is safe for the transformer. But `shell.user_ns` is
mutable shared state. The current namespace-swap pattern
(`_execute_via_ipython`) is not concurrency-safe -- two concurrent `run_cell`
calls would race on `shell.user_ns`.

**Severity**: In production, concurrent REPLs (e.g., depth > 1 with child
dispatch) would corrupt each other's namespaces.

### RISK-5: Trace Injection Incompatibility (MEDIUM)

**Current behavior**: sync path prepends `TRACE_HEADER` / `TRACE_HEADER_MEMORY`
and appends `TRACE_FOOTER` / `TRACE_FOOTER_MEMORY` as raw source strings before
passing to `execute_sync()`. The trace code injects `_rlm_trace.start_time`,
`tracemalloc.start()`, etc.

**Problem**: If execution goes through `run_cell()`, the trace header/footer
must be injected *before* `run_cell` is called (as part of the raw cell text).
This means trace injection happens before AST transformation, which is the
current behavior for sync. But for async code that goes through the AST
transformer, the trace header/footer would also be transformed -- the
`LlmCallRewriter` would walk the trace code looking for `llm_query` calls
(harmless, but unnecessary work). More importantly, if the entire cell is
wrapped in an async function by IPython's async detection, the trace
header/footer would execute inside that wrapper, which may change scoping.

**Workaround**: Inject trace as a separate AST transformer that wraps the
body with try/finally. Adds complexity.

### RISK-6: Error Auto-Unregistration (MEDIUM)

**IPython behavior**: If an AST transformer throws an exception during
`transform_ast()`, IPython catches it, warns, and *removes the transformer*
from the list (line 3582):

```python
except Exception as e:
    warn("AST transformer %r threw an error. It will be unregistered. %s" % ...)
    self.ast_transformers.remove(transformer)
```

**Problem**: If `LlmCallRewriter` ever throws (e.g., on malformed AST from a
syntax edge case), IPython silently removes it. Subsequent code blocks would
execute without the async transformation, causing `llm_query()` to be called
synchronously -- which would deadlock (the sync `llm_query` function is not
wired, only `llm_query_async` is).

The current code catches rewrite exceptions in `REPLTool.run_async()` and
reports them as structured errors without losing the transformer.

### RISK-7: `async def _repl_exec()` Wrapper Elimination (LOW)

**IPython behavior**: When `should_run_async()` returns True, IPython uses
`PyCF_ALLOW_TOP_LEVEL_AWAIT` to compile code and then does `await eval(code_obj,
...)`. This is IPython's equivalent of the `async def _repl_exec()` wrapper --
it allows top-level `await` without an explicit async function.

**Opportunity**: This is the one area where IPython's pipeline could simplify
things. If the async detection worked correctly (see RISK-3), we could
eliminate the `async def _repl_exec(): ... return locals()` wrapper.

**But**: We lose the `return locals()` namespace propagation (RISK-1) and
transitive function promotion (RISK-2).

---

## File-by-File Impact Inventory

### Files that would change

| File | Lines | Change Description |
|------|-------|--------------------|
| `rlm_adk/repl/ast_rewriter.py` | 1-230 (entire file) | `rewrite_for_async()` (L161-228) would be partially obsoleted -- the `async def _repl_exec()` wrapper could be removed if IPython handles async execution. `has_llm_calls()` (L15-36) would still be needed for RISK-3 workaround. `_promote_functions_to_async()` (L82-119) must be preserved and integrated into the transformer. `LlmCallRewriter` (L39-67) would become a compound transformer that also calls `_promote_functions_to_async()`. |
| `rlm_adk/tools/repl_tool.py` | L107-273 (`run_async`) | The `has_llm_calls` / `rewrite_for_async` / `compile` block (L184-212) would be replaced by a single `run_cell()` call. The dual path (sync vs async) would merge. But flush_fn, trace, and error handling would remain. Net savings: ~30 lines. |
| `rlm_adk/repl/local_repl.py` | L281-316 (`_execute_code_inner`), L374-470 (`execute_code_async`) | `execute_code_async()` would be eliminated or heavily refactored -- the `compiled` parameter and `_repl_exec` extraction are no longer needed. `execute_code()` sync path could remain for the no-llm-calls case, or everything could go through `run_cell()`. Namespace merge logic (L306-310, L438-441) would change to a user_ns diff. |
| `rlm_adk/repl/ipython_executor.py` | L72-262 (entire class) | `execute_async()` (L183-237) would be obsoleted -- IPython handles async internally. `execute_sync()` might be replaced by `run_cell()` delegation. `_execute_via_ipython()` (L160-181) would need concurrency protection. The class could potentially be simplified to just `run_cell()` + namespace swap. |
| `rlm_adk/repl/trace.py` | L157-201 (header/footer strings) | Trace injection would need to change from string concatenation to AST-level injection (new transformer or pre-processing). The `TRACE_HEADER`/`TRACE_FOOTER` constants might be replaced by an AST transformer. |

### Files that would NOT change

| File | Reason |
|------|--------|
| `rlm_adk/repl/skill_registry.py` | Skill expansion happens before AST transformation |
| `rlm_adk/dispatch.py` | Dispatch closures are unaffected |
| `rlm_adk/orchestrator.py` | Delegates to reasoning_agent, no direct REPL interaction |
| `rlm_adk/state.py` | State keys unchanged |
| `rlm_adk/plugins/*` | Observability plugins consume state, don't touch AST |

---

## Test Impact Inventory

| Test File | Tests Affected | Impact |
|-----------|---------------|--------|
| `tests_rlm_adk/test_adk_ast_rewriter.py` (417 lines) | All 20+ tests | Tests for `has_llm_calls`, `LlmCallRewriter`, `rewrite_for_async`, transitive promotion. Most tests would need to change if `rewrite_for_async` is modified. Tests for `has_llm_calls` and `LlmCallRewriter` would remain valid. |
| `tests_rlm_adk/test_rewrite_instrumentation.py` (292 lines) | All 6 tests | Patch targets `rlm_adk.tools.repl_tool.has_llm_calls` and `rlm_adk.tools.repl_tool.rewrite_for_async`. If rewrite is done via IPython pipeline, these patches would target different code paths. |
| `tests_rlm_adk/test_repl_tool.py` (325 lines) | Tests using async llm_query | The `has_llm_calls` trigger and async execution path would change. |
| `tests_rlm_adk/test_adk_repl_local.py` (453 lines) | `test_async_*` tests | Tests that call `rewrite_for_async` + `execute_code_async(compiled=...)` would need rewriting. |
| `tests_rlm_adk/test_skill_expander_ast.py` (157 lines) | All 12 tests | Tests `has_llm_calls` + `rewrite_for_async` on expanded skill code. Would need adaptation. |
| `tests_rlm_adk/test_skill_expander_e2e.py` (221 lines) | E2E skill expansion tests | Exercises the full pipeline including AST rewriting. |
| `tests_rlm_adk/test_fmea_e2e.py` (2299 lines) | `test_*has_llm_calls` tests | Provider-fake e2e tests that verify `llm_calls_made` in tool results. |
| `tests_rlm_adk/test_adk_imports.py` | `test_import_ast_rewriter` | Import test would need updating if public API changes. |

**Total test files affected**: 8
**Estimated tests requiring changes**: 40+

---

## Recommended Implementation Sequence

**Given the HIGH RISK, LOW REWARD verdict, the recommendation is to NOT
implement this migration.** However, if the decision is made to proceed
despite the risks, the following sequence minimizes blast radius:

### Phase 0: Prerequisite Research (1 day)
- Confirm IPython version pinned in `pyproject.toml`
- Verify `PyCF_ALLOW_TOP_LEVEL_AWAIT` behavior with transitive async promotion
- Prototype: register `LlmCallRewriter` on a fresh shell, run code with
  `llm_query()`, verify `should_run_async()` behavior (expect: fails per RISK-3)

### Phase 1: Compound Transformer (2 days)
- Create `LlmCallCompoundTransformer(ast.NodeTransformer)` that:
  1. Runs `LlmCallRewriter.visit(tree)`
  2. Runs `_promote_functions_to_async(tree)`
  3. Returns modified tree (WITHOUT `async def _repl_exec` wrapper)
- Unit test the compound transformer independently
- Do NOT register it in IPython yet

### Phase 2: `should_run_async` Override (1 day)
- Subclass `InteractiveShell` or monkey-patch `should_run_async` to also
  detect `llm_query` calls (via `has_llm_calls`)
- Verify that the async runner is selected correctly

### Phase 3: Namespace Propagation (2 days)
- Replace `return locals()` with post-execution namespace diffing
- Filter out IPython internal variables (`_`, `__`, `In`, `Out`, etc.)
- Verify variable persistence across multiple `run_cell` calls
- Handle the `user_ns` vs `user_global_ns` distinction

### Phase 4: Concurrency Isolation (2 days)
- Address singleton `InteractiveShell` sharing
- Options: per-execution namespace swap with locking, or multiple shell instances
- Verify with concurrent dispatch tests

### Phase 5: Trace Migration (1 day)
- Convert trace header/footer from string injection to AST transformer or
  pre-cell injection
- Verify trace levels 0, 1, 2 all work

### Phase 6: Test Migration (3 days)
- Update all 40+ affected tests
- Run full FMEA suite
- Run provider-fake e2e suite

**Total estimated effort: 12 days** (vs. current working state requiring 0 days)

---

## Open Questions / Unknowns

1. **IPython version stability**: Does the `ast_transformers` API have any
   deprecation warnings or planned changes? The codebase uses IPython as an
   execution backend, not interactively -- are there undocumented assumptions?

2. **`PyCF_ALLOW_TOP_LEVEL_AWAIT` and function promotion**: If IPython compiles
   with `PyCF_ALLOW_TOP_LEVEL_AWAIT`, does `await` inside a sync `def` still
   raise `SyntaxError`? (Expected: yes, the flag only allows top-level await.)
   This means transitive promotion is still required even with IPython's async
   support.

3. **IPython's `run_cell` inside an existing event loop**: The RLM-ADK
   orchestrator runs inside an asyncio event loop (ADK's runner). IPython's
   `_asyncio_runner` calls `loop.run_until_complete(coro)` -- this will raise
   `RuntimeError: This event loop is already running` if called from inside an
   existing loop. The current code avoids this by using raw `await` in
   `execute_async()`. Using `run_cell()` from within an async context would
   hit this problem.

4. **`nest_asyncio` compatibility**: Would `nest_asyncio.apply()` be needed?
   This adds another dependency and has its own edge cases.

5. **Safe builtins**: The current REPL uses `_SAFE_BUILTINS` (blocks
   `eval`/`input`/`compile`/`globals`). IPython's `run_cell` uses its own
   `__builtin__` module. How would safe builtins be enforced through
   `run_cell()`? The current `_execute_via_ipython` swaps `user_ns` which
   includes `__builtins__`, but IPython may override this.

6. **Error handling contract**: `REPLTool.run_async()` currently catches
   `SyntaxError` from `rewrite_for_async()` and returns structured error
   responses with rewrite failure instrumentation (`OBS_REWRITE_FAILURE_COUNT`,
   `OBS_REWRITE_FAILURE_CATEGORIES`). If IPython handles the AST transform,
   errors would surface as `InputRejected` or be silently swallowed (RISK-6).
   The observability instrumentation would need a new hook.

---

## Conclusion

The current manual AST rewriting pipeline in `repl_tool.py` ->
`ast_rewriter.py` -> `local_repl.py` is well-designed for the specific
requirements of RLM-ADK:

- **Precise namespace control** via `return locals()`
- **Transitive function promotion** via fixpoint loop
- **Concurrency safety** via separate namespace copies
- **Observability** via structured error categorization
- **Trace injection** via string concatenation

IPython's `ast_transformers` pipeline was designed for a different use case
(interactive notebook cells) and does not provide equivalents for these
capabilities. Adopting it would require extensive workarounds that negate any
simplification benefit.

**The manual pipeline should be retained.**
