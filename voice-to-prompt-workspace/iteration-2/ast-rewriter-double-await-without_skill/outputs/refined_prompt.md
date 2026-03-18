<!-- generated: 2026-03-17 -->
<!-- source: voice transcription, refined without skill -->
# Fix AST Rewriter: Double-Await on Nested Async Functions

## Context

The AST rewriter (`rlm_adk/repl/ast_rewriter.py`, 230 lines) transforms sync `llm_query()` calls into `await llm_query_async()` and promotes containing `FunctionDef` nodes to `AsyncFunctionDef`. Two bugs cause double-await or missing-await when the LM generates code with nested async functions:

1. **Double-await on pre-awaited calls.** `LlmCallRewriter.visit_Call` (line 55) unconditionally wraps every `llm_query`/`llm_query_batched` call in `ast.Await`. When the LM writes `await llm_query("x")`, the AST is `Await(value=Call(func=Name("llm_query")))`. The `NodeTransformer` descends into `Await` via `generic_visit`, reaches the `Call`, and `visit_Call` wraps it in a second `Await` -- producing `Await(Await(Call(...)))`, i.e., `await await llm_query_async("x")`.

2. **Missing await for user-written `async def`.** `_promote_functions_to_async` (line 82) only scans `isinstance(node, ast.FunctionDef)` in its promotion loop (line 102). If the LM writes `async def helper(): return llm_query("x")` followed by `result = helper()`, the rewriter transforms the inner call correctly but never adds `helper` to the `promoted` set. The call site `helper()` at module level never gets `await`, producing a coroutine object at runtime instead of the expected result.

Both bugs were observed in production on 2026-03-16.

## Original Transcription

> the ast rewriter is breaking on nested async functions. like if the LM generates code that defines an async helper inside the repl block and then calls llm query from inside that helper, the rewriter promotes it wrong and you get a double await. I saw it happen in production yesterday. Can you fix the node transformer so it tracks scope properly and doesn't re-promote functions that are already async.

## Refined Instructions

### Step 1: Prevent double-await in `LlmCallRewriter`

**File:** `rlm_adk/repl/ast_rewriter.py`, class `LlmCallRewriter` (line 39)

**Problem:** The class only defines `visit_Call` (line 55). Python's `ast.NodeTransformer.generic_visit` descends into `Await` nodes, so when the source is `await llm_query("x")`, the traversal visits the child `Call` and `visit_Call` wraps it in `ast.Await`, producing `Await(Await(Call(...)))`.

**Fix:** Add a `visit_Await` method to `LlmCallRewriter`:

- If `node.value` is an `ast.Call` whose `func` is an `ast.Name` with `id` in `_SYNC_TO_ASYNC`: rename the function (e.g., `llm_query` to `llm_query_async`) but return the *original* `Await` node with the renamed call as its `.value`. Do NOT wrap in a second `Await`.
- Otherwise: call `self.generic_visit(node)` and return the result, so that nested calls inside non-target awaits are still processed.

This ensures `await llm_query("x")` becomes `await llm_query_async("x")` (single await), while `llm_query("x")` (no existing await) still becomes `await llm_query_async("x")` through the existing `visit_Call` path.

### Step 2: Make `_promote_functions_to_async` aware of user-written `AsyncFunctionDef`

**File:** `rlm_adk/repl/ast_rewriter.py`, function `_promote_functions_to_async` (line 82)

**Problem:** The promotion loop (line 101-107) only scans `ast.FunctionDef`. User-written `AsyncFunctionDef` nodes are invisible. Their call sites never get `await` added.

**Fix:** After the `while True` promotion loop exits (line 106-107, the `if not newly_promoted: break` path), add a second pass:

1. Walk the tree for `ast.AsyncFunctionDef` nodes whose `name` is NOT already in `promoted`.
2. Collect these names into a set (e.g., `user_async_names`).
3. If non-empty, run `_PromotedCallAwaiter(user_async_names).visit(tree)` to wrap their call sites with `await`.
4. Call `ast.fix_missing_locations(tree)`.
5. Add `user_async_names` to `promoted` before returning.

The existing `_PromotedCallAwaiter.visit_Await` guard (line 150-152) already prevents double-wrapping of calls that are already inside an `Await` node, so `await helper()` will not become `await await helper()`.

### Step 3: Add scope tracking to prevent incorrect cross-scope transformations

**File:** `rlm_adk/repl/ast_rewriter.py`, classes `_FuncDefPromoter` (line 122) and `_PromotedCallAwaiter` (line 144)

**Problem:** Both transformers use `generic_visit` which descends into all nested scopes. If a nested function shadows a promoted name (e.g., defines its own `helper`), the transformer would incorrectly operate on the inner scope's `helper`.

**Fix for `_FuncDefPromoter`:** This is lower risk because `visit_FunctionDef` (line 128) only promotes nodes whose `name` is in the target set. However, a nested `FunctionDef` with the same name as an outer promoted function would also be promoted. Add a depth counter or a set of "already seen at this scope" names. The simplest approach: when `visit_FunctionDef` encounters a node with `name` in `self._names`, promote it but do NOT call `self.generic_visit(node)` before the check -- instead, manually visit the body *after* promotion so that inner functions with the same name are not affected. Actually, the current code calls `self.generic_visit(node)` first (line 129), which descends into the body. This means an inner `def helper` inside an outer `def helper` would both be promoted if both names match. To fix: track scope depth or only promote top-level-in-module function definitions. A pragmatic fix: in `_promote_functions_to_async`, restrict the `ast.walk` scan (line 101) to only consider `FunctionDef` nodes that are direct children of `tree.body` (the module body), not deeply nested ones. This matches the actual use case: the LM defines functions at the top level of the REPL block.

**Fix for `_PromotedCallAwaiter`:** Add `visit_FunctionDef` and `visit_AsyncFunctionDef` methods that check whether the function's parameter list or body defines a local name that shadows a promoted name. If shadowed, process the node's body with a new `_PromotedCallAwaiter` instance that excludes the shadowed name. If not shadowed, use `generic_visit` normally. This ensures that `helper()` inside a nested scope that defines its own `helper` is left alone, while `helper()` calls that refer to the outer promoted function are correctly wrapped.

**Simpler alternative for Step 3:** If the scope-tracking complexity is disproportionate, document the limitation (name shadowing in nested scopes) and skip this step. The primary bugs (Steps 1 and 2) are the production-breaking issues. Step 3 is a correctness hardening measure. Prioritize Steps 1 and 2.

### Step 4: Add test file `tests_rlm_adk/test_ast_rewriter.py`

The previous test file `test_adk_ast_rewriter.py` no longer exists (compiled `.pyc` cache remains at `tests_rlm_adk/__pycache__/test_adk_ast_rewriter.cpython-312-pytest-9.0.2.pyc` but the source is gone). Create a new test file.

**Required test cases:**

| # | Input Code | Expected Behavior |
|---|-----------|-------------------|
| 1 | `result = llm_query("x")` | Becomes `result = await llm_query_async("x")` -- baseline, must not regress |
| 2 | `result = await llm_query("x")` | Becomes `result = await llm_query_async("x")` -- single await, NOT double |
| 3 | `result = await llm_query_batched(["a","b"])` | Same pattern for batched variant -- single await |
| 4 | `async def helper():\n    return llm_query("x")\nresult = helper()` | `helper` body: `await llm_query_async("x")`. Call site: `result = await helper()`. `helper` stays `async def`. |
| 5 | `async def helper():\n    return await llm_query("x")\nresult = await helper()` | No double-await anywhere. Inner becomes `await llm_query_async("x")`. Outer `await helper()` unchanged. |
| 6 | `def process():\n    return llm_query("x")\nresult = process()` | `process` promoted to `async def`. Inner: `await llm_query_async("x")`. Call site: `await process()`. |
| 7 | `def outer():\n    async def inner():\n        return llm_query("x")\n    return inner()\nresult = outer()` | `inner` body: `await llm_query_async("x")`. `inner()` call: `await inner()`. `outer` promoted to async (contains await). `result = await outer()`. |
| 8 | `def outer():\n    def inner():\n        return llm_query("x")\n    return inner()\nresult = outer()` | Both `inner` and `outer` promoted to async. All calls get await. |
| 9 | `x = llm_query(llm_query("inner"))` | Nested calls: `x = await llm_query_async(await llm_query_async("inner"))` |
| 10 | Code with no `llm_query` calls | `has_llm_calls` returns `False`, `rewrite_for_async` not called |

**Test approach:** Import `rewrite_for_async` and `has_llm_calls` directly. For each test, call `rewrite_for_async(code)`, then use `ast.unparse()` (Python 3.12) on the result to get a string representation and assert the expected patterns are present / double-await patterns are absent.

### Step 5: Run regression tests

```bash
# New test file
.venv/bin/python -m pytest tests_rlm_adk/test_ast_rewriter.py -x -q

# Default contract suite (~28 tests) to verify no regressions in the full REPL pipeline
.venv/bin/python -m pytest tests_rlm_adk/
```

**Do NOT run `.venv/bin/python -m pytest -m ""`** -- that executes the full 970+ test suite and takes 5+ minutes.

## Considerations

- **Backward compatibility:** The `rewrite_for_async(code: str) -> ast.Module` signature (line 161) and return type must not change. `REPLTool` imports and calls it at `rlm_adk/tools/repl_tool.py` line 26 (import) and line 189 (call site), then passes the result to `compile()`.
- **`has_llm_calls` behavior:** The detection function (line 15) uses `ast.walk` to find `Call` nodes with `func.id` in `{"llm_query", "llm_query_batched"}`. When the LM writes `await llm_query("x")`, the `Call` node still exists inside the `Await`, so `has_llm_calls` returns `True`. This is correct and must not change.
- **Transitive promotion soundness:** The `while True` loop in `_promote_functions_to_async` (line 97) runs until no new promotions occur. Changes must preserve this fixed-point property: the loop must terminate and must be complete.
- **The `_repl_exec` wrapper:** All module-level code is wrapped in `async def _repl_exec(): ... return locals()` (line 204). Top-level `await` expressions are valid inside this wrapper.
- **Performance:** The rewriter runs on every REPL execution containing `llm_query` calls. Keep the number of tree walks bounded. Current complexity is O(n * rounds) where rounds <= number of function definitions.
- **Existing `_PromotedCallAwaiter.visit_Await` guard:** The guard at line 150-152 returns the `Await` node without descending, preventing double-wrap during the promotion phase. This is separate from the `LlmCallRewriter` bug (Step 1) which occurs during the initial rewrite phase, before promotion. Both fixes are needed.

## Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/repl/ast_rewriter.py` | `has_llm_calls()` | 15 | Detection -- not changed, but behavior must be preserved |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter` class | 39 | **Bug 1 site** -- needs `visit_Await` to prevent double-await |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter._SYNC_TO_ASYNC` | 50 | Name mapping dict used by both `visit_Call` and new `visit_Await` |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter.visit_Call` | 55 | Unconditionally wraps in `Await` -- root cause of Bug 1 |
| `rlm_adk/repl/ast_rewriter.py` | `_contains_await()` | 70 | Scope-aware await detection -- correctly skips nested scopes, do not modify |
| `rlm_adk/repl/ast_rewriter.py` | `_promote_functions_to_async()` | 82 | **Bug 2 site** -- only scans `FunctionDef`, misses `AsyncFunctionDef` |
| `rlm_adk/repl/ast_rewriter.py` | Promotion loop `while True` | 97 | Fixed-point iteration -- changes must preserve termination |
| `rlm_adk/repl/ast_rewriter.py` | `isinstance(node, ast.FunctionDef)` check | 102 | The specific line that skips `AsyncFunctionDef` |
| `rlm_adk/repl/ast_rewriter.py` | `_FuncDefPromoter` class | 122 | Replaces FunctionDef with AsyncFunctionDef; may need scope guard |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter` class | 144 | Wraps call sites with await; may need scope guard |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter.visit_Await` | 150 | Existing double-wrap guard -- must preserve |
| `rlm_adk/repl/ast_rewriter.py` | `rewrite_for_async()` | 161 | Public entry point -- signature must not change |
| `rlm_adk/repl/ast_rewriter.py` | `async def _repl_exec` wrapper | 204 | All module body gets wrapped here |
| `rlm_adk/tools/repl_tool.py` | `from rlm_adk.repl.ast_rewriter import ...` | 26 | Import site -- consumer of the rewriter |
| `rlm_adk/tools/repl_tool.py` | `tree = rewrite_for_async(exec_code)` | 189 | Call site in REPLTool.run_async |
| `rlm_adk/tools/repl_tool.py` | `compiled = compile(tree, "<repl>", "exec")` | 198 | Compiles the rewriter output |

## Priming References

Before starting implementation, read these in order:
1. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow the **Core Loop** branch link)
2. `rlm_adk_docs/core_loop.md` -- Section 5 "AST Rewriter" (line 201) for the transformation pipeline overview
3. `rlm_adk/repl/ast_rewriter.py` -- the full 230-line source file; understand the complete pipeline before modifying
