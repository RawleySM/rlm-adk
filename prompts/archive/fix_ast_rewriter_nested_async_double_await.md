<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Fix AST Rewriter: Double-Await on Nested Async Functions

## Context

The AST rewriter (`rlm_adk/repl/ast_rewriter.py`) transforms sync `llm_query()` calls into `await llm_query_async()` and promotes containing functions to async. When the LM generates code that already uses `async def` with `llm_query()` calls inside, or manually writes `await llm_query(...)`, the rewriter produces double-await expressions (`await await llm_query_async(...)`) because `LlmCallRewriter` unconditionally wraps every `llm_query` call in `ast.Await` without checking whether the call is already inside an `Await` node. A secondary issue is that `_promote_functions_to_async` only scans `FunctionDef` nodes, so user-written `AsyncFunctionDef` nodes containing `llm_query` calls are invisible to the promotion system -- their callers never get `await` added.

## Original Transcription

> the ast rewriter is breaking on nested async functions. like if the LM generates code that defines an async helper inside the repl block and then calls llm query from inside that helper, the rewriter promotes it wrong and you get a double await. I saw it happen in production yesterday. Can you fix the node transformer so it tracks scope properly and doesn't re-promote functions that are already async.

## Refined Instructions

1. **Add a `visit_Await` method to `LlmCallRewriter`** in `rlm_adk/repl/ast_rewriter.py` (class at line 39). Currently `LlmCallRewriter` only has `visit_Call` (line 55). When the LM writes `await llm_query("x")`, the AST is `Await(value=Call(func=Name("llm_query")))`. The NodeTransformer descends into the `Await` node via `generic_visit`, visits the child `Call`, and `visit_Call` wraps it in another `Await` -- producing `Await(Await(Call(...)))`, i.e., `await await llm_query_async("x")`.

   The fix: override `visit_Await` in `LlmCallRewriter`. If the `Await.value` is a `Call` to `llm_query` or `llm_query_batched`, rewrite the call name to its async variant but return the *original* `Await` node (with the modified Call as its value) -- do NOT wrap in a second `Await`. If the `Await.value` is not a target call, use `generic_visit` to process children normally.

2. **Make `_promote_functions_to_async` aware of user-written `AsyncFunctionDef` nodes** (line 82). Currently, the function scans only `isinstance(node, ast.FunctionDef)`. If the LM writes `async def helper(): return llm_query("x")`, the rewriter correctly transforms the inner call to `await llm_query_async("x")`, but `helper` is never added to the `promoted` set. Call sites like `result = helper()` at the module level (or inside sync enclosing functions) never get `await` added.

   The fix: after the promotion loop completes, do a second scan of the tree for `AsyncFunctionDef` nodes (user-written ones that were never in `promoted`). Collect their names. Then run `_PromotedCallAwaiter` on those names so that call sites of user-written async functions also get `await`. Add these names to the returned `promoted` set so the wrapper logic has a complete picture. Be careful not to double-wrap calls that are already inside an `Await` node -- `_PromotedCallAwaiter.visit_Await` (line 150) already handles this by returning the node without descending.

3. **Make `_PromotedCallAwaiter` and `_FuncDefPromoter` scope-aware** so they do not descend into nested function bodies where name semantics differ. Currently both transformers use `generic_visit` which descends into nested `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` bodies. This means a call to `helper()` inside a nested function gets wrapped even though `helper` might refer to a different binding in that scope. While the current `_PromotedCallAwaiter.visit_Await` guard prevents double-wrapping of already-awaited calls, the scope-blind descent is still semantically wrong for shadowed names and could cause issues with complex nesting.

   The fix: add `visit_FunctionDef`, `visit_AsyncFunctionDef`, and `visit_ClassDef` methods to both `_FuncDefPromoter` and `_PromotedCallAwaiter` that return the node unchanged (without calling `generic_visit`) for scopes where the promoted name is shadowed by a local definition, or that explicitly descend with scope tracking. A simpler approach: in `_PromotedCallAwaiter`, override these visit methods to still descend (since a call to a promoted outer function from a nested scope IS valid Python and DOES need `await`), but ensure they do not re-promote function definitions that happen to share a name with the promoted function in an inner scope. For `_FuncDefPromoter`, it already only transforms `FunctionDef` nodes whose `name` is in the target set, so name-collision in nested scopes is the main risk -- add a check that the node is at the expected scope depth or track seen scopes.

4. **Add tests** covering at minimum these scenarios:
   - LM writes `await llm_query("x")` at module level -- must NOT produce double await.
   - LM writes `async def helper(): return llm_query("x")` then calls `helper()` at module level -- call must get `await`.
   - LM writes `async def helper(): return await llm_query("x")` then calls `await helper()` -- no double await anywhere.
   - Sync function containing `llm_query` nested inside an async function -- both get properly promoted without double await.
   - LM writes `def outer(): async def inner(): return llm_query("x"); return inner()` -- `inner()` call gets `await`, `outer` gets promoted to async.
   - Name shadowing: nested function defines a local `helper` that shadows the outer promoted `helper` -- the inner call should NOT be wrapped.

   *[Added -- the transcription did not mention tests, but changes to the AST rewriter affect all REPL code execution and regressions here would silently break production. Existing test file `test_adk_ast_rewriter.py` was deleted at some point; a new test file is needed.]*

5. **Run the default test suite** (`.venv/bin/python -m pytest tests_rlm_adk/`) to confirm no regressions in the provider-fake contract tests that exercise the full REPL pipeline including AST rewriting.

   *[Added -- the transcription did not mention regression testing, but the AST rewriter is on the critical path for all REPL execution.]*

## Considerations

- **Backward compatibility**: The `rewrite_for_async` function's public signature and return type (`ast.Module`) must not change. `REPLTool` (line 189 in `repl_tool.py`) calls it directly and compiles the result.
- **`has_llm_calls` detection**: The detection function (line 15) uses `ast.walk` to find `llm_query` Call nodes. It does NOT check for `await llm_query(...)` patterns. If the LM writes `await llm_query("x")`, `has_llm_calls` still returns `True` (because the Call node exists inside the Await). This is correct and should not change.
- **Transitive promotion soundness**: The `_promote_functions_to_async` loop runs until stable. Any changes must preserve this fixed-point property -- the loop must still terminate and must still be complete (every function that transitively contains an await gets promoted).
- **The `_repl_exec` wrapper**: All module-level code is wrapped in `async def _repl_exec(): ... return locals()` (line 204). Top-level `await` expressions are valid inside this wrapper. The fix must ensure user-written `async def` calls at the module level get `await` added.
- **Performance**: The AST rewriter runs on every REPL execution that contains `llm_query` calls. Avoid adding expensive tree walks. The current implementation is O(n * rounds) where rounds is bounded by the number of nested function definitions.
- **`_PromotedCallAwaiter.visit_Await` existing guard**: The current guard at line 150 prevents double-wrapping by returning the `Await` node without descending. This is critical and must be preserved. The `LlmCallRewriter` fix (step 1) addresses a different path -- the initial rewrite phase before promotion, where the guard does not exist.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/repl/ast_rewriter.py` | `has_llm_calls` | L15 | Detection function -- not directly changed but behavior context |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter` | L39 | Primary bug site -- needs `visit_Await` to prevent double-await |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter.visit_Call` | L55 | Unconditionally wraps in Await -- root cause of double-await |
| `rlm_adk/repl/ast_rewriter.py` | `_contains_await` | L70 | Scope-aware await detection -- correctly skips nested scopes |
| `rlm_adk/repl/ast_rewriter.py` | `_promote_functions_to_async` | L82 | Only scans FunctionDef, misses user-written AsyncFunctionDef |
| `rlm_adk/repl/ast_rewriter.py` | `_FuncDefPromoter` | L122 | Needs scope awareness for nested same-name functions |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter` | L144 | Needs scope awareness; existing `visit_Await` guard is correct |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter.visit_Await` | L150 | Existing double-wrap guard -- must preserve |
| `rlm_adk/repl/ast_rewriter.py` | `rewrite_for_async` | L161 | Public entry point -- signature must not change |
| `rlm_adk/tools/repl_tool.py` | `import has_llm_calls, rewrite_for_async` | L26 | Consumer of the rewriter |
| `rlm_adk/tools/repl_tool.py` | `rewrite_for_async(exec_code)` call | L189 | Call site in REPLTool.run_async |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow the **Core Loop** branch link for AST rewriting details)
3. `rlm_adk/repl/ast_rewriter.py` -- the full source file (230 lines) to understand current implementation before modifying
