# GAP-DC-011: Stale repomix XML snapshots contain deleted source code
**Severity**: LOW
**Category**: dead-code
**Files**: `repomix-architecture-flow-compressed.xml`, `repomix-rlm_adk-compressed.xml`

## Problem

Two repomix XML snapshot files at the repo root contain frozen copies of the deleted `ast_rewriter.py` source code, the deleted state key constants, and the old `expand_skill_imports` import in `repl_tool.py`. These files are used as context snapshots for LLM prompting but contain stale code that will mislead any agent reading them.

## Evidence

`repomix-architecture-flow-compressed.xml`:
```xml
<file name="ast_rewriter.py"/>
...
<path>rlm_adk/repl/ast_rewriter.py</path>
def has_llm_calls(code: str) -> bool:
class LlmCallRewriter(ast.NodeTransformer):
def rewrite_for_async(code: str) -> ast.Module:
...
from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async
```

`repomix-rlm_adk-compressed.xml`:
```xml
REPL_EXPANDED_CODE = "repl_expanded_code"
REPL_EXPANDED_CODE_HASH = "repl_expanded_code_hash"
REPL_SKILL_EXPANSION_META = "repl_skill_expansion_meta"
REPL_DID_EXPAND = "repl_did_expand"
...
REPL_DID_EXPAND,
REPL_EXPANDED_CODE,
REPL_EXPANDED_CODE_HASH,
REPL_SKILL_EXPANSION_META,
```

## Suggested Fix

Regenerate both repomix XML files from the current codebase. These are derived artifacts and should reflect the current state of the source.
