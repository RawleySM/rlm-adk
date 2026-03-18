# Fix: AST Rewriter Scope-Blind Promotion Produces Double-Await on Nested Async Functions

## Problem

The AST rewriter at `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/ast_rewriter.py` breaks when the LM generates code containing nested `async def` helpers that call `llm_query()`. The root cause is that neither `LlmCallRewriter`, `_promote_functions_to_async`, `_FuncDefPromoter`, nor `_PromotedCallAwaiter` track function scope -- they operate on names via flat tree traversal (`ast.walk` / `generic_visit`), so identically-named functions at different nesting depths are conflated, and call-site wrapping ignores which scope a call belongs to.

### Concrete failing scenario

```python
# LM-generated REPL code
async def helper(prompt):
    return llm_query(prompt)

def process(items):
    def helper(item):          # local shadow -- different function, same name
        return item.upper()
    return [helper(i) for i in items]

result = await helper("summarize this")
processed = process(["a", "b"])
```

**What should happen:** `llm_query(prompt)` inside the outer `async def helper` is rewritten to `await llm_query_async(prompt)`. The inner `helper` inside `process` is a plain sync function that does not call `llm_query` and should be left alone. `process` should remain sync.

**What actually happens:**

1. `LlmCallRewriter` (line 55) correctly transforms `llm_query(prompt)` to `await llm_query_async(prompt)` inside the outer `async def helper`. (No bug here -- `generic_visit` descends everywhere, but `await` inside an async function is valid.)

2. `_promote_functions_to_async` (line 82) calls `ast.walk(tree)` which yields ALL `FunctionDef` nodes at every nesting depth. It finds:
   - The inner `def helper(item)` inside `process` (a `FunctionDef`).
   - `def process(items)` (a `FunctionDef`).
   - The outer `helper` is `AsyncFunctionDef`, so line 102 correctly skips it.

3. `_FuncDefPromoter` (line 122) is instantiated with `names={"helper"}` when the outer `helper`'s await is detected... but actually the outer `helper` is already `AsyncFunctionDef` and is skipped. However, if ANY code path causes `"helper"` to enter the `promoted` set (e.g., a sync `def helper` at module scope that wraps `llm_query`), then `_FuncDefPromoter` promotes ALL `FunctionDef` nodes named `"helper"`, including the unrelated local one inside `process`.

4. `_PromotedCallAwaiter` (line 144) similarly wraps ALL `helper()` calls with `await`, including the `helper(i)` inside the list comprehension in `process` -- producing an incorrect `await` on a call to the local sync function.

5. This incorrect `await` inside `process` causes `_contains_await(process)` to return `True` in the next round, promoting `process` to `async def` and wrapping its call site with `await` -- cascading the error upward.

### Additional scope-tracking gaps

- **`_PromotedCallAwaiter.visit_Await` (line 150) suppresses ALL descent into `Await` nodes** by returning without `generic_visit`. This prevents double-wrapping but also prevents the awaiter from reaching calls nested inside already-awaited expressions (e.g., `await llm_query_async(helper("x"))` -- the `helper("x")` inside the Await is never visited, so even if `helper` was promoted, its call is not wrapped).

- **`_contains_await` (line 70) correctly skips nested `FunctionDef`/`AsyncFunctionDef`/`ClassDef` scopes**, but `_promote_functions_to_async` (line 101) uses `ast.walk` which does NOT skip scopes -- so it finds nested functions that `_contains_await` intentionally ignored.

## Files to modify

| File | Lines | What to change |
|------|-------|----------------|
| `rlm_adk/repl/ast_rewriter.py` | 39-67 | `LlmCallRewriter` -- consider whether scope tracking is needed here (currently correct: `await` inside any async enclosing scope is valid) |
| `rlm_adk/repl/ast_rewriter.py` | 82-119 | `_promote_functions_to_async` -- replace `ast.walk(tree)` with a scope-aware walk that only finds `FunctionDef` nodes at the current scope level, not inside nested function/class bodies. Track which specific AST nodes (not just names) need promotion. |
| `rlm_adk/repl/ast_rewriter.py` | 122-141 | `_FuncDefPromoter` -- must match on the specific AST node identity (or scope-qualified name), not just `node.name`. Two functions named `"helper"` at different scopes must be distinguished. |
| `rlm_adk/repl/ast_rewriter.py` | 144-158 | `_PromotedCallAwaiter` -- must be scope-aware: only wrap calls that resolve to the promoted function at the correct scope level. Also reconsider `visit_Await` (line 150): it should call `generic_visit` on its children so nested calls inside Await expressions can still be processed, but it must not re-wrap the Await node itself. |

## Files to read first

Per `CLAUDE.md`, read `rlm_adk_docs/UNDERSTAND.md` first, then read `rlm_adk_docs/core_loop.md` (section 5: AST Rewriter).

| File | Purpose |
|------|---------|
| `rlm_adk_docs/UNDERSTAND.md` | Codebase entry point (required by CLAUDE.md) |
| `rlm_adk_docs/core_loop.md` | Section 5 documents the AST rewriter pipeline |
| `rlm_adk/repl/ast_rewriter.py` | The file to fix (230 lines) |
| `rlm_adk/tools/repl_tool.py` | Caller of `rewrite_for_async` (lines 93-277, step 5 in run_async) |
| `rlm_adk/repl/local_repl.py` | `execute_code_async` consumes the rewritten AST |

## Suggested approach

1. **Replace name-based matching with node-identity-based matching** in `_promote_functions_to_async`. Instead of collecting a `set[str]` of names, collect a `set[int]` of `id(node)` references (or a mapping from node to name). Pass these node references to `_FuncDefPromoter` and `_PromotedCallAwaiter` so they only operate on the specific function definitions and their corresponding call sites at the correct scope.

2. **Implement a scope-aware walk** for `_promote_functions_to_async` (line 101). Instead of `ast.walk(tree)`, write a helper that yields `FunctionDef` nodes only at the current scope level (module body and inside the bodies of functions being promoted), skipping nested function/class definitions that introduce new scopes. This mirrors what `_contains_await` already does (line 72-74) but for the discovery pass.

3. **Fix `_PromotedCallAwaiter.visit_Await`** (line 150) to call `self.generic_visit(node)` before returning, so that calls nested inside already-awaited expressions can still be processed. Guard against double-wrapping by checking whether the parent is already an `Await` node, not by skipping traversal entirely.

4. **Add regression tests** covering:
   - `async def` helper calling `llm_query` with a same-named sync `def` at a different scope (the double-await repro case)
   - Nested `def` inside `async def` calling `llm_query` (promotion should target only the inner function)
   - `await llm_query_async(promoted_fn("x"))` -- the nested `promoted_fn` call inside the Await must also be wrapped
   - Transitive promotion chain with nested scopes: `def a(): def b(): llm_query(...)` at depth 2+ still works correctly
   - All existing tests in the worktree test file continue to pass

## Test file

The existing AST rewriter tests are at `.claude/worktrees/agent-a8770869/tests_rlm_adk/test_adk_ast_rewriter.py` (not present on `main` -- only in the worktree). If it does not exist on the working branch, copy it from the worktree or write new tests. Relevant test classes:

- `TestContainsAwait` (line 254) -- tests `_contains_await` scope pruning
- `TestPromotionAndDoubleAwait` (line 318) -- tests double-await prevention
- `TestPromotedFunctionExecution` (line 396) -- end-to-end execution of promoted chains

## Validation

```bash
# Run the AST rewriter tests (if present on branch)
.venv/bin/python -m pytest tests_rlm_adk/test_adk_ast_rewriter.py -x -q

# Run the default contract test suite to check for regressions
.venv/bin/python -m pytest tests_rlm_adk/

# Lint
ruff check rlm_adk/repl/ast_rewriter.py
ruff format --check rlm_adk/repl/ast_rewriter.py
```

**Do NOT run `pytest -m ""`** -- that runs the full 970+ test suite and is reserved for CI.
