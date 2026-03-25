# GAP-DC-008: Legacy fixture description references deleted async path
**Severity**: LOW
**Category**: dead-code
**Files**: `tests_rlm_adk/fixtures/provider_fake/repl_cancelled_during_async.json`

## Problem

The `repl_cancelled_during_async.json` fixture's `description` field references the deleted AST rewriter execution path:

```json
"description": "FM-14 (RPN=96): ... Reasoning emits execute_code with llm_query (has_llm_calls=True, enters async path). ... tests patch asyncio to inject CancelledError during the async REPL execution path (repl_tool.py:120-143)."
```

The fixture is NOT excluded from the contract runner (it runs successfully). However, its description is misleading -- it references `has_llm_calls=True`, "enters async path", and line numbers in `repl_tool.py` that no longer correspond to the described behavior. The fixture's actual runtime behavior is through the thread bridge, not the async path.

## Evidence

The fixture name itself (`repl_cancelled_during_async`) references the old async execution path. Its description field also references the old code flow.

The fixture index entry (`index.json:903`) has the fixture named "execute_code_async CWD Race Condition" which references the deleted `execute_code_async` method.

## Suggested Fix

- Update the fixture's `description` field to reflect the thread bridge execution path
- Consider renaming the fixture from `repl_cancelled_during_async` to something like `repl_cancelled_during_execution` (would require updating all references in index.json and test files)
- Update the index.json name to remove "execute_code_async" reference
