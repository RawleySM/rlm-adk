"""AST rewriter for sync-to-async bridge in REPL code execution.

Transforms LM-generated Python code so that:
- llm_query(p) -> await llm_query_async(p)
- llm_query_batched(ps) -> await llm_query_batched_async(ps)
- Wraps code in: async def _repl_exec(): ... return locals()

Only rewrites if the code actually contains llm_query calls.
If no LM calls, code runs synchronously via regular exec().
"""

import ast
from typing import Any


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


class LlmCallRewriter(ast.NodeTransformer):
    """Transforms llm_query/llm_query_batched calls to their async equivalents.

    Transformations:
    - llm_query(args) -> await llm_query_async(args)
    - llm_query_batched(args) -> await llm_query_batched_async(args)

    Preserves all arguments including keyword args (model=, etc).
    Handles nested calls, calls inside expressions, assignments, loops, etc.
    """

    _SYNC_TO_ASYNC = {
        "llm_query": "llm_query_async",
        "llm_query_batched": "llm_query_batched_async",
    }

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


def _contains_await(node: ast.AST) -> bool:
    """Check if a node contains Await without descending into nested scopes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Await):
            return True
        if _contains_await(child):
            return True
    return False


def _promote_functions_to_async(tree: ast.Module) -> set[str]:
    """Promote sync FunctionDef nodes that contain await to AsyncFunctionDef.

    Also wraps call sites of promoted functions with await.  Repeats until
    no new promotions are needed (transitive closure: if ``foo()`` calls
    ``bar()`` and ``bar`` was promoted, then ``foo`` needs promotion too).

    Each round only transforms *newly* promoted names to prevent double-await.

    Returns the set of promoted function names.
    """
    promoted: set[str] = set()

    # Iterate until stable — each round may promote new functions whose
    # callers also need promotion.
    while True:
        newly_promoted: set[str] = set()

        # Collect FunctionDef nodes that need promotion
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name not in promoted:
                if _contains_await(node):
                    newly_promoted.add(node.name)

        if not newly_promoted:
            break

        promoted |= newly_promoted

        # Replace FunctionDef -> AsyncFunctionDef for newly promoted names
        _FuncDefPromoter(newly_promoted).visit(tree)

        # Wrap call sites of newly promoted functions with await
        _PromotedCallAwaiter(newly_promoted).visit(tree)

        ast.fix_missing_locations(tree)

    return promoted


class _FuncDefPromoter(ast.NodeTransformer):
    """Replace FunctionDef with AsyncFunctionDef for named functions."""

    def __init__(self, names: set[str]) -> None:
        self._names = names

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        if node.name in self._names:
            new_node = ast.AsyncFunctionDef(
                name=node.name,
                args=node.args,
                body=node.body,
                decorator_list=node.decorator_list,
                returns=node.returns,
                type_comment=getattr(node, "type_comment", None),
                type_params=getattr(node, "type_params", []),
            )
            return ast.copy_location(new_node, node)
        return node


class _PromotedCallAwaiter(ast.NodeTransformer):
    """Wrap calls to promoted functions with await (if not already awaited)."""

    def __init__(self, names: set[str]) -> None:
        self._names = names

    def visit_Await(self, node: ast.Await) -> ast.AST:
        # Already awaited -- leave untouched to prevent double-wrapping.
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in self._names:
            return ast.Await(value=node)
        return node


def rewrite_for_async(code: str) -> ast.Module:
    """Rewrite code block for async execution.

    1. Parse the code into AST
    2. Transform llm_query -> await llm_query_async
    3. Wrap in async def _repl_exec(): ... return locals()
    4. Return the modified AST module (ready for compile())

    Args:
        code: Python source code from LM-generated ```repl``` block

    Returns:
        ast.Module ready for compile() and exec()

    Raises:
        SyntaxError: If code cannot be parsed
    """
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


def compile_repl_code(code: str) -> tuple[Any, bool]:
    """Compile REPL code, handling both sync and async cases.

    If the code contains llm_query/llm_query_batched calls, it is
    AST-rewritten to an async function wrapper. Otherwise it is
    compiled as regular synchronous code.

    Returns:
        (compiled_code, is_async): The compiled code object and whether
        it needs async execution via _repl_exec().
    """
    if has_llm_calls(code):
        rewritten = rewrite_for_async(code)
        return compile(rewritten, "<repl>", "exec"), True
    else:
        return compile(code, "<repl>", "exec"), False
