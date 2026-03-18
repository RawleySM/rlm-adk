<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Fix AST Rewriter: Scope-Aware Promotion to Prevent Double-Await on Nested Async Functions

## Context

The AST rewriter (`rlm_adk/repl/ast_rewriter.py`) transforms synchronous `llm_query()` calls into `await llm_query_async()` and promotes enclosing sync functions to `async def`. When the LM generates code that defines an `async def` helper inside the REPL block and calls `llm_query()` from within that helper, the rewriter produces a double-await (`await await llm_query_async(...)`) because: (1) `LlmCallRewriter.visit_Call` unconditionally wraps every `llm_query` call in `ast.Await` without checking if it is already inside an `Await` node, and (2) `_promote_functions_to_async` only scans `ast.FunctionDef` nodes, so user-written `AsyncFunctionDef` nodes are invisible to the promotion system -- their call sites never receive `await` wrapping, and the interaction between the two passes is not coordinated. This was observed in production.

## Original Transcription

> the ast rewriter is breaking on nested async functions. like if the LM generates code that defines an async helper inside the repl block and then calls llm query from inside that helper, the rewriter promotes it wrong and you get a double await. I saw it happen in production yesterday. Can you fix the node transformer so it tracks scope properly and doesn't re-promote functions that are already async.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Rewriter-Guard` teammate to add a `visit_Await` method to `LlmCallRewriter` in `rlm_adk/repl/ast_rewriter.py` (class at line 39).**

   Currently `LlmCallRewriter` only defines `visit_Call` (line 55). When the LM writes `await llm_query("x")`, the AST is `Await(value=Call(func=Name("llm_query")))`. The `NodeTransformer` descends into the `Await` node via `generic_visit`, visits the child `Call`, and `visit_Call` wraps it in another `Await` -- producing `Await(Await(Call(...)))`, i.e., `await await llm_query_async("x")`.

   The fix: override `visit_Await` in `LlmCallRewriter`. If the `Await.value` is a `Call` to `llm_query` or `llm_query_batched`, rename the function to its async variant but return the *original* `Await` node (with the modified `Call` as its value) -- do NOT wrap in a second `Await`. If the `Await.value` is not a target call, fall through to `generic_visit` to process children normally. This prevents the initial rewrite phase from producing double-await before promotion even runs.

2. **Spawn a `Promotion-Scope` teammate to make `_promote_functions_to_async` (line 82) aware of user-written `AsyncFunctionDef` nodes.**

   Currently the promotion loop only scans `isinstance(node, ast.FunctionDef)`. If the LM writes `async def helper(): return llm_query("x")`, the rewriter correctly transforms the inner call to `await llm_query_async("x")`, but `helper` is never added to the `promoted` set. Consequently, call sites like `result = helper()` at module level never receive `await` wrapping.

   The fix: after the while-loop stabilizes, do a second scan of the tree for `AsyncFunctionDef` nodes whose names are NOT already in `promoted`. Collect these names as "user-written async" functions. Run `_PromotedCallAwaiter` on those names so their call sites get `await` added. Add these names to the returned `promoted` set so downstream logic has a complete picture. `_PromotedCallAwaiter.visit_Await` (line 150) already prevents double-wrapping of calls that are already awaited, so this is safe.

3. **Spawn a `Scope-Tracker` teammate to add scope awareness to `_PromotedCallAwaiter` and `_FuncDefPromoter` in `rlm_adk/repl/ast_rewriter.py`.**

   Both transformers currently use `generic_visit` which descends into nested `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` bodies without tracking scope. This means a call to `helper()` inside a nested function that shadows the outer `helper` name would incorrectly get `await` wrapped.

   The fix for `_PromotedCallAwaiter`: add `visit_FunctionDef`, `visit_AsyncFunctionDef`, and `visit_ClassDef` methods. These should still descend (a call to a promoted outer function from a nested scope IS valid Python and DOES need `await`), but should exclude names that are shadowed by a local definition in the nested scope. Track a set of locally-shadowed names: if a nested function defines a parameter or local function with the same name as a promoted function, do not wrap calls to that name within that scope.

   The fix for `_FuncDefPromoter`: it already only transforms `FunctionDef` nodes whose `name` is in the target set, which limits the blast radius. However, add a guard to skip `FunctionDef` nodes that are nested inside another function and happen to share a name with a promoted function at the outer scope -- only promote top-level (module-body) definitions or definitions at the scope level where `_contains_await` found the await. A simpler approach: since `_promote_functions_to_async` uses `ast.walk` which finds all `FunctionDef` nodes at any depth, and a nested function with the same name as a top-level function should not be promoted just because the top-level one was, add a depth/parent check or limit the walk to direct children of the module body during the collection phase.

4. **Spawn a `AST-Test` teammate to add comprehensive tests in `tests_rlm_adk/test_ast_rewriter_scope.py`.**

   Cover at minimum these scenarios:
   - LM writes `await llm_query("x")` at module level -- must NOT produce double-await after rewriting.
   - LM writes `async def helper(): return llm_query("x")` then calls `helper()` at module level -- the call site must get `await` added.
   - LM writes `async def helper(): return await llm_query("x")` then calls `await helper()` -- no double-await anywhere in the output.
   - Sync `def` containing `llm_query` nested inside an `async def` -- both get properly handled without double-await.
   - LM writes `def outer(): async def inner(): return llm_query("x"); return inner()` -- `inner()` call gets `await`, `outer` gets promoted to `async def`.
   - Name shadowing: outer scope defines `async def helper` with `llm_query`, nested scope defines `def helper` (different function) -- the inner `helper()` call should NOT be wrapped with `await`.
   - End-to-end execution: compile the rewritten AST, execute it with a mock `llm_query_async`, and verify the result is correct (no `TypeError: object coroutine can't be used in 'await' expression`).
   - Existing test coverage from `TestPromotionAndDoubleAwait` and `TestPromotedFunctionExecution` patterns (see worktree file `tests_rlm_adk/test_adk_ast_rewriter.py` for reference patterns).

   *[Added -- the transcription did not mention tests, but changes to the AST rewriter affect all REPL code execution and regressions would silently break production. The original test file `test_adk_ast_rewriter.py` exists only in worktrees, not on main -- ensure the new tests cover the existing test scenarios plus the new scope-tracking ones.]*

5. **Spawn a `Regression-Runner` teammate to run the default test suite** (`.venv/bin/python -m pytest tests_rlm_adk/`) and confirm no regressions in the provider-fake contract tests that exercise the full REPL pipeline including AST rewriting.

   *[Added -- the transcription did not mention regression testing, but the AST rewriter is on the critical path for all REPL code execution. Do NOT run `-m ""` (full 970+ test suite); the default run is sufficient.]*

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/nested_async_helper.json`

**Essential requirements the fixture must capture:**
- The fixture must include LM-generated code that defines an `async def` helper calling `llm_query()`, then invokes that helper -- verifying the full REPL pipeline does not produce a double-await `TypeError` at runtime.
- The fixture must include a case where the LM writes `await llm_query(...)` directly (already-awaited call) -- verifying the rewriter does not add a redundant second `await`.
- The fixture must verify that the returned result from the helper function propagates correctly through the REPL (the helper's return value appears in `variables` of the REPL output), not just that it compiles without error.

**TDD sequence:**
1. Red: Write test asserting `rewrite_for_async` on `await llm_query("x")` does NOT contain `await (await` in unparsed output. Run, confirm failure (current code produces double-await).
2. Green: Add `visit_Await` to `LlmCallRewriter`. Run, confirm pass.
3. Red: Write test asserting `rewrite_for_async` on `async def helper(): return llm_query("x")\nresult = helper()` produces `await helper()` at the call site. Run, confirm failure (current code does not wrap call).
4. Green: Add user-written `AsyncFunctionDef` scan to `_promote_functions_to_async`. Run, confirm pass.
5. Red: Write test asserting name-shadowed nested `helper()` call is NOT wrapped. Run, confirm failure if scope-blind descent wraps it.
6. Green: Add scope tracking to `_PromotedCallAwaiter`. Run, confirm pass.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the implementation works end-to-end.

## Considerations

- **Backward compatibility**: The `rewrite_for_async` function's public signature and return type (`ast.Module`) must not change. `REPLTool` (line 189 in `repl_tool.py`) calls it directly and compiles the result.
- **`has_llm_calls` detection**: The detection function (line 15) uses `ast.walk` to find `llm_query` `Call` nodes. It does NOT check for `await llm_query(...)` patterns. If the LM writes `await llm_query("x")`, `has_llm_calls` still returns `True` because the `Call` node exists inside the `Await`. This is correct and should not change.
- **Transitive promotion soundness**: The `_promote_functions_to_async` loop runs until stable (fixed-point). Any changes must preserve this termination property and completeness -- every function that transitively contains an `await` gets promoted.
- **The `_repl_exec` wrapper**: All module-level code is wrapped in `async def _repl_exec(): ... return locals()` (line 204). Top-level `await` expressions are valid inside this wrapper. The fix must ensure user-written `async def` function calls at the module level also get `await` added.
- **Performance**: The AST rewriter runs on every REPL execution that contains `llm_query` calls. Avoid adding expensive tree walks. The current implementation is O(n * rounds) where rounds is bounded by the number of nested function definitions. The scope-tracking addition should not change the asymptotic complexity.
- **`_PromotedCallAwaiter.visit_Await` existing guard**: The guard at line 150 prevents double-wrapping by returning the `Await` node without descending. This is critical and must be preserved. The `LlmCallRewriter` fix (step 1) addresses a different path -- the initial rewrite phase before promotion, where no such guard exists.
- **AR-CRIT-001 not directly relevant**: This change is in the REPL AST rewriting layer, not in dispatch/state. State mutation rules do not apply here.
- **Skill import expansion**: The skill registry expansion pass (`expand_skill_imports` in `rlm_adk/repl/skill_registry.py`) runs BEFORE the AST rewriter. Expanded skill code may contain `llm_query` calls and may define helper functions. The AST rewriter must handle these correctly too -- the same fix applies since expanded code goes through `rewrite_for_async` as a single code block.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/repl/ast_rewriter.py` | `has_llm_calls` | L15 | Detection function -- not changed, but behavior context for `await llm_query()` pattern |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter` | L39 | Primary bug site -- needs `visit_Await` to prevent double-await in initial rewrite |
| `rlm_adk/repl/ast_rewriter.py` | `LlmCallRewriter.visit_Call` | L55 | Unconditionally wraps in `Await` -- root cause of double-await when call is already awaited |
| `rlm_adk/repl/ast_rewriter.py` | `_contains_await` | L70 | Scope-aware await detection helper -- correctly skips nested scopes, not changed |
| `rlm_adk/repl/ast_rewriter.py` | `_promote_functions_to_async` | L82 | Only scans `FunctionDef`, misses user-written `AsyncFunctionDef` |
| `rlm_adk/repl/ast_rewriter.py` | `_FuncDefPromoter` | L122 | Needs scope awareness for nested same-name function definitions |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter` | L144 | Needs scope awareness; existing `visit_Await` guard at L150 must be preserved |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter.visit_Await` | L150 | Existing double-wrap guard -- prevents `await(await(...))` during promotion phase |
| `rlm_adk/repl/ast_rewriter.py` | `_PromotedCallAwaiter.visit_Call` | L154 | Wraps promoted function calls with `await` |
| `rlm_adk/repl/ast_rewriter.py` | `rewrite_for_async` | L161 | Public entry point -- signature must not change |
| `rlm_adk/tools/repl_tool.py` | `from rlm_adk.repl.ast_rewriter import ...` | L26 | Import site for `has_llm_calls` and `rewrite_for_async` |
| `rlm_adk/tools/repl_tool.py` | `if has_llm_calls(exec_code)` | L185 | Detection gate in REPLTool.run_async |
| `rlm_adk/tools/repl_tool.py` | `tree = rewrite_for_async(exec_code)` | L189 | Call site where rewritten AST is compiled and executed |
| `rlm_adk/repl/skill_registry.py` | `expand_skill_imports` | -- | Expansion pass runs before AST rewriting; expanded code may contain helper functions |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow the **Core Loop** branch link for AST rewriting details)
3. `rlm_adk/repl/ast_rewriter.py` -- the full source file (230 lines) to understand current implementation before modifying
