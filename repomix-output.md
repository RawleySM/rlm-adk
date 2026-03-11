<?xml version="1.0" encoding="UTF-8"?>
<repository>
<repository_structure>
  <file name="ast_rewriter.py"/>
  <file name="local_repl.py"/>
  <file name="__init__.py"/>
  <file name="trace.py"/>
</repository_structure>
<repository_files>
  <file>
    
  
    <path>ast_rewriter.py</path>
    
  
    <content>&quot;&quot;&quot;AST rewriter for sync-to-async bridge in REPL code execution.

Transforms LM-generated Python code so that:
- llm_query(p) -&gt; await llm_query_async(p)
- llm_query_batched(ps) -&gt; await llm_query_batched_async(ps)
- Wraps code in: async def _repl_exec(): ... return locals()

Only rewrites if the code actually contains llm_query calls.
If no LM calls, code runs synchronously via regular exec().
&quot;&quot;&quot;

import ast


def has_llm_calls(code: str) -&gt; bool:
    &quot;&quot;&quot;Check if code contains llm_query or llm_query_batched calls.

    Uses AST parsing to detect calls accurately (not just string matching,
    which could match comments or string literals).

    Returns False if code has syntax errors (will be caught during execution).
    &quot;&quot;&quot;
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in (
                &quot;llm_query&quot;,
                &quot;llm_query_batched&quot;,
            ):
                return True
    return False


class LlmCallRewriter(ast.NodeTransformer):
    &quot;&quot;&quot;Transforms llm_query/llm_query_batched calls to their async equivalents.

    Transformations:
    - llm_query(args) -&gt; await llm_query_async(args)
    - llm_query_batched(args) -&gt; await llm_query_batched_async(args)

    Preserves all arguments including keyword args (model=, etc).
    Handles nested calls, calls inside expressions, assignments, loops, etc.
    &quot;&quot;&quot;

    _SYNC_TO_ASYNC = {
        &quot;llm_query&quot;: &quot;llm_query_async&quot;,
        &quot;llm_query_batched&quot;: &quot;llm_query_batched_async&quot;,
    }

    def visit_Call(self, node: ast.Call) -&gt; ast.AST:
        &quot;&quot;&quot;Transform sync LM calls to async await expressions.&quot;&quot;&quot;
        # Transform children first (handles nested calls like
        # llm_query(llm_query(&quot;inner&quot;)))
        self.generic_visit(node)

        if isinstance(node.func, ast.Name) and node.func.id in self._SYNC_TO_ASYNC:
            # Replace function name with async variant
            node.func.id = self._SYNC_TO_ASYNC[node.func.id]
            # Wrap in Await node
            return ast.Await(value=node)

        return node


def _contains_await(node: ast.AST) -&gt; bool:
    &quot;&quot;&quot;Check if a node contains Await without descending into nested scopes.&quot;&quot;&quot;
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Await):
            return True
        if _contains_await(child):
            return True
    return False


def _promote_functions_to_async(tree: ast.Module) -&gt; set[str]:
    &quot;&quot;&quot;Promote sync FunctionDef nodes that contain await to AsyncFunctionDef.

    Also wraps call sites of promoted functions with await.  Repeats until
    no new promotions are needed (transitive closure: if ``foo()`` calls
    ``bar()`` and ``bar`` was promoted, then ``foo`` needs promotion too).

    Each round only transforms *newly* promoted names to prevent double-await.

    Returns the set of promoted function names.
    &quot;&quot;&quot;
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

        # Replace FunctionDef -&gt; AsyncFunctionDef for newly promoted names
        _FuncDefPromoter(newly_promoted).visit(tree)

        # Wrap call sites of newly promoted functions with await
        _PromotedCallAwaiter(newly_promoted).visit(tree)

        ast.fix_missing_locations(tree)

    return promoted


class _FuncDefPromoter(ast.NodeTransformer):
    &quot;&quot;&quot;Replace FunctionDef with AsyncFunctionDef for named functions.&quot;&quot;&quot;

    def __init__(self, names: set[str]) -&gt; None:
        self._names = names

    def visit_FunctionDef(self, node: ast.FunctionDef) -&gt; ast.AST:
        self.generic_visit(node)
        if node.name in self._names:
            new_node = ast.AsyncFunctionDef(
                name=node.name,
                args=node.args,
                body=node.body,
                decorator_list=node.decorator_list,
                returns=node.returns,
                type_comment=getattr(node, &quot;type_comment&quot;, None),
                type_params=getattr(node, &quot;type_params&quot;, []),
            )
            return ast.copy_location(new_node, node)
        return node


class _PromotedCallAwaiter(ast.NodeTransformer):
    &quot;&quot;&quot;Wrap calls to promoted functions with await (if not already awaited).&quot;&quot;&quot;

    def __init__(self, names: set[str]) -&gt; None:
        self._names = names

    def visit_Await(self, node: ast.Await) -&gt; ast.AST:
        # Already awaited -- leave untouched to prevent double-wrapping.
        return node

    def visit_Call(self, node: ast.Call) -&gt; ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in self._names:
            return ast.Await(value=node)
        return node


def rewrite_for_async(code: str) -&gt; ast.Module:
    &quot;&quot;&quot;Rewrite code block for async execution.

    1. Parse the code into AST
    2. Transform llm_query -&gt; await llm_query_async
    3. Wrap in async def _repl_exec(): ... return locals()
    4. Return the modified AST module (ready for compile())

    Args:
        code: Python source code from LM-generated ```repl``` block

    Returns:
        ast.Module ready for compile() and exec()

    Raises:
        SyntaxError: If code cannot be parsed
    &quot;&quot;&quot;
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
            func=ast.Name(id=&quot;locals&quot;, ctx=ast.Load()),
            args=[],
            keywords=[],
        )
    )
    body_stmts.append(return_locals)

    # Create async def _repl_exec(): &lt;body&gt;
    async_func = ast.AsyncFunctionDef(
        name=&quot;_repl_exec&quot;,
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

    return new_module</content>
    

  </file>
  <file>
    
  
    <path>local_repl.py</path>
    
  
    <content>&quot;&quot;&quot;Local REPL environment adapted for ADK.

Provides sandboxed Python code execution with:
- Safe builtins (blocks eval/exec/input)
- Context loading (context_0, context_1, ...)
- FINAL_VAR and SHOW_VARS helpers
- stdout/stderr capture
- Slots for async llm_query/llm_query_batched closures (injected by orchestrator)
&quot;&quot;&quot;

import concurrent.futures
import contextvars
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable

from rlm_adk.repl.trace import (
    REPLTrace,
    TRACE_HEADER,
    TRACE_HEADER_MEMORY,
    TRACE_FOOTER,
    TRACE_FOOTER_MEMORY,
)
from rlm_adk.types import REPLResult, RLMChatCompletion

# Task-local stdout/stderr capture (CRIT-3.4)
_capture_stdout: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    &quot;_capture_stdout&quot;, default=None
)
_capture_stderr: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    &quot;_capture_stderr&quot;, default=None
)


class _TaskLocalStream:
    &quot;&quot;&quot;Proxy stream that routes writes to a task-local ContextVar buffer when set,
    otherwise falls through to the original stream.&quot;&quot;&quot;

    def __init__(self, original: io.TextIOBase, ctx_var: contextvars.ContextVar):
        self._original = original
        self._ctx_var = ctx_var

    @property
    def encoding(self):
        return self._original.encoding

    def isatty(self):
        return self._original.isatty()

    def write(self, s):
        buf = self._ctx_var.get(None)
        if buf is not None:
            return buf.write(s)
        return self._original.write(s)

    def flush(self):
        buf = self._ctx_var.get(None)
        if buf is not None:
            buf.flush()
        else:
            self._original.flush()

    def fileno(self):
        raise io.UnsupportedOperation(&quot;fileno&quot;)


sys.stdout = _TaskLocalStream(sys.stdout, _capture_stdout)
sys.stderr = _TaskLocalStream(sys.stderr, _capture_stderr)

# Module-level lock protecting process-global state (os.chdir, sys.stdout/stderr)
# during synchronous execute_code. Ensures concurrent REPLs running in threads
# do not race on CWD or output capture.
_EXEC_LOCK = threading.Lock()

# Safe builtins - blocks dangerous operations like eval/exec/input
_SAFE_BUILTINS = {
    # Core types and functions
    &quot;print&quot;: print,
    &quot;len&quot;: len,
    &quot;str&quot;: str,
    &quot;int&quot;: int,
    &quot;float&quot;: float,
    &quot;list&quot;: list,
    &quot;dict&quot;: dict,
    &quot;set&quot;: set,
    &quot;tuple&quot;: tuple,
    &quot;bool&quot;: bool,
    &quot;type&quot;: type,
    &quot;isinstance&quot;: isinstance,
    &quot;issubclass&quot;: issubclass,
    &quot;enumerate&quot;: enumerate,
    &quot;zip&quot;: zip,
    &quot;map&quot;: map,
    &quot;filter&quot;: filter,
    &quot;sorted&quot;: sorted,
    &quot;reversed&quot;: reversed,
    &quot;range&quot;: range,
    &quot;min&quot;: min,
    &quot;max&quot;: max,
    &quot;sum&quot;: sum,
    &quot;abs&quot;: abs,
    &quot;round&quot;: round,
    &quot;any&quot;: any,
    &quot;all&quot;: all,
    &quot;pow&quot;: pow,
    &quot;divmod&quot;: divmod,
    &quot;chr&quot;: chr,
    &quot;ord&quot;: ord,
    &quot;hex&quot;: hex,
    &quot;bin&quot;: bin,
    &quot;oct&quot;: oct,
    &quot;repr&quot;: repr,
    &quot;ascii&quot;: ascii,
    &quot;format&quot;: format,
    &quot;hash&quot;: hash,
    &quot;id&quot;: id,
    &quot;iter&quot;: iter,
    &quot;next&quot;: next,
    &quot;slice&quot;: slice,
    &quot;callable&quot;: callable,
    &quot;hasattr&quot;: hasattr,
    &quot;getattr&quot;: getattr,
    &quot;setattr&quot;: setattr,
    &quot;delattr&quot;: delattr,
    &quot;dir&quot;: dir,
    &quot;vars&quot;: vars,
    &quot;bytes&quot;: bytes,
    &quot;bytearray&quot;: bytearray,
    &quot;memoryview&quot;: memoryview,
    &quot;complex&quot;: complex,
    &quot;object&quot;: object,
    &quot;super&quot;: super,
    &quot;property&quot;: property,
    &quot;staticmethod&quot;: staticmethod,
    &quot;classmethod&quot;: classmethod,
    &quot;__import__&quot;: __import__,
    &quot;__build_class__&quot;: __build_class__,
    &quot;exec&quot;: exec,
    &quot;open&quot;: open,
    # Exceptions
    &quot;Exception&quot;: Exception,
    &quot;BaseException&quot;: BaseException,
    &quot;ValueError&quot;: ValueError,
    &quot;TypeError&quot;: TypeError,
    &quot;KeyError&quot;: KeyError,
    &quot;IndexError&quot;: IndexError,
    &quot;AttributeError&quot;: AttributeError,
    &quot;FileNotFoundError&quot;: FileNotFoundError,
    &quot;OSError&quot;: OSError,
    &quot;IOError&quot;: IOError,
    &quot;RuntimeError&quot;: RuntimeError,
    &quot;NameError&quot;: NameError,
    &quot;ImportError&quot;: ImportError,
    &quot;StopIteration&quot;: StopIteration,
    &quot;AssertionError&quot;: AssertionError,
    &quot;NotImplementedError&quot;: NotImplementedError,
    &quot;ArithmeticError&quot;: ArithmeticError,
    &quot;LookupError&quot;: LookupError,
    &quot;Warning&quot;: Warning,
    # Blocked
    &quot;input&quot;: None,
    &quot;eval&quot;: None,
    &quot;compile&quot;: None,
    &quot;globals&quot;: None,
    &quot;locals&quot;: locals,
}


class LocalREPL:
    &quot;&quot;&quot;Local REPL environment for ADK-based execution.

    Unlike the original LocalREPL which used socket-based llm_query,
    this version accepts callable closures for LM dispatch that are
    injected by the orchestrator.
    &quot;&quot;&quot;

    def __init__(self, depth: int = 1, sync_timeout: float | None = None):
        self.depth = depth
        self.sync_timeout = sync_timeout if sync_timeout is not None else float(
            os.environ.get(&quot;RLM_REPL_SYNC_TIMEOUT&quot;, &quot;30&quot;)
        )
        self.temp_dir = tempfile.mkdtemp(prefix=f&quot;repl_adk_{uuid.uuid4()}_&quot;)
        self.original_cwd = os.getcwd()
        self._pending_llm_calls: list[RLMChatCompletion] = []
        self._last_exec_error: str | None = None

        # Setup globals and locals
        self.globals: dict[str, Any] = {
            &quot;__builtins__&quot;: _SAFE_BUILTINS.copy(),
            &quot;__name__&quot;: &quot;__main__&quot;,
        }
        self.locals: dict[str, Any] = {}

        # Register helper functions
        self.globals[&quot;FINAL_VAR&quot;] = self._final_var
        self.globals[&quot;SHOW_VARS&quot;] = self._show_vars

    def set_llm_query_fns(self, llm_query_fn: Callable, llm_query_batched_fn: Callable) -&gt; None:
        &quot;&quot;&quot;Set/update the sync LM query functions (called by orchestrator).&quot;&quot;&quot;
        self.globals[&quot;llm_query&quot;] = llm_query_fn
        self.globals[&quot;llm_query_batched&quot;] = llm_query_batched_fn

    def set_async_llm_query_fns(
        self,
        llm_query_async_fn: Callable,
        llm_query_batched_async_fn: Callable,
    ) -&gt; None:
        &quot;&quot;&quot;Set async LM query functions for AST-rewritten code.&quot;&quot;&quot;
        self.globals[&quot;llm_query_async&quot;] = llm_query_async_fn
        self.globals[&quot;llm_query_batched_async&quot;] = llm_query_batched_async_fn

    def _final_var(self, variable_name: str) -&gt; str:
        &quot;&quot;&quot;Return the value of a variable as a final answer.&quot;&quot;&quot;
        variable_name = variable_name.strip().strip(&quot;\&quot;'&quot;)
        if variable_name in self.locals:
            return str(self.locals[variable_name])

        available = [k for k in self.locals.keys() if not k.startswith(&quot;_&quot;)]
        error_hint = &quot;&quot;
        if self._last_exec_error:
            error_hint = f&quot; Last execution error: {self._last_exec_error}&quot;
        if available:
            return (
                f&quot;Error: Variable '{variable_name}' not found. &quot;
                f&quot;Available variables: {available}. &quot;
                f&quot;You must create and assign a variable BEFORE calling FINAL_VAR on it.&quot;
                f&quot;{error_hint}&quot;
            )
        return (
            f&quot;Error: Variable '{variable_name}' not found. &quot;
            f&quot;No variables have been created yet. &quot;
            f&quot;You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it.&quot;
            f&quot;{error_hint}&quot;
        )

    def _show_vars(self) -&gt; str:
        &quot;&quot;&quot;Show all available variables in the REPL environment.&quot;&quot;&quot;
        available = {k: type(v).__name__ for k, v in self.locals.items() if not k.startswith(&quot;_&quot;)}
        if not available:
            return &quot;No variables created yet. Use ```repl``` blocks to create variables.&quot;
        return f&quot;Available variables: {available}&quot;

    @contextmanager
    def _capture_output(self):
        &quot;&quot;&quot;Context manager to capture stdout/stderr.&quot;&quot;&quot;
        old_stdout, old_stderr = sys.stdout, sys.stderr
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf
            yield stdout_buf, stderr_buf
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    @contextmanager
    def _temp_cwd(self):
        &quot;&quot;&quot;Temporarily change to temp directory for execution.&quot;&quot;&quot;
        old_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            yield
        finally:
            os.chdir(old_cwd)

    def _execute_code_inner(
        self, code: str, trace: REPLTrace | None = None,
    ) -&gt; tuple[str, str, bool]:
        &quot;&quot;&quot;Inner exec logic, runs under _EXEC_LOCK.

        Returns (stdout, stderr, success) where success=True means no exception.
        Side-effects: updates self.locals on success, self._last_exec_error on failure.
        &quot;&quot;&quot;
        trace_level = int(os.environ.get(&quot;RLM_REPL_TRACE&quot;, &quot;0&quot;))

        with _EXEC_LOCK, self._capture_output() as (stdout_buf, stderr_buf), self._temp_cwd():
            try:
                combined = {**self.globals, **self.locals}

                if trace is not None:
                    combined[&quot;_rlm_trace&quot;] = trace
                    if trace_level &gt;= 2:
                        instrumented = TRACE_HEADER_MEMORY + &quot;\n&quot; + code + &quot;\n&quot; + TRACE_FOOTER_MEMORY
                    else:
                        instrumented = TRACE_HEADER + &quot;\n&quot; + code + &quot;\n&quot; + TRACE_FOOTER
                else:
                    instrumented = code

                exec(instrumented, combined, combined)

                # Update locals with new variables (underscore filter hides _rlm_*)
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith(&quot;_&quot;):
                        self.locals[key] = value

                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue()
                self._last_exec_error = None
                return stdout, stderr, True
            except Exception as e:
                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue() + f&quot;\n{type(e).__name__}: {e}&quot;
                self._last_exec_error = f&quot;{type(e).__name__}: {e}&quot;
                return stdout, stderr, False

    def execute_code(self, code: str, trace: REPLTrace | None = None) -&gt; REPLResult:
        &quot;&quot;&quot;Execute code synchronously in the sandboxed namespace.

        Uses _EXEC_LOCK to serialize access to process-global state
        (os.chdir, sys.stdout/stderr) so that concurrent REPLs in
        threads do not race.

        Enforces self.sync_timeout seconds via ThreadPoolExecutor.
        &quot;&quot;&quot;
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()
        timed_out = False

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._execute_code_inner, code, trace)
        try:
            stdout, stderr, _success = future.result(timeout=self.sync_timeout)
        except concurrent.futures.TimeoutError:
            timed_out = True
            stdout = &quot;&quot;
            stderr = (
                f&quot;\nTimeoutError: Sync execution exceeded &quot;
                f&quot;{self.sync_timeout}s timeout&quot;
            )
        finally:
            # Shut down without waiting for the timed-out thread to finish,
            # so it doesn't overwrite _last_exec_error.
            pool.shutdown(wait=not timed_out, cancel_futures=True)

        if timed_out:
            self._last_exec_error = stderr.strip()

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

    def _make_cwd_open(self):
        &quot;&quot;&quot;Return an open() wrapper that resolves relative paths against self.temp_dir.

        This avoids the need for os.chdir() which modifies process-global state
        and is unsafe when multiple async REPL instances run concurrently.
        &quot;&quot;&quot;
        temp_dir = self.temp_dir
        builtin_open = open

        def _cwd_open(file, *args, **kwargs):
            if isinstance(file, str) and not os.path.isabs(file):
                file = os.path.join(temp_dir, file)
            return builtin_open(file, *args, **kwargs)

        return _cwd_open

    async def execute_code_async(
        self, code: str, repl_exec_fn: Any, trace: REPLTrace | None = None,
    ) -&gt; REPLResult:
        &quot;&quot;&quot;Execute AST-rewritten async code.

        Does NOT call os.chdir() to avoid modifying process-global state.
        Instead, injects a custom open() that resolves relative paths against
        self.temp_dir, and sets _repl_cwd for code that needs the working dir.

        Args:
            code: The original code (before AST rewriting -- for reference/logging)
            repl_exec_fn: The compiled async function from AST rewriter
            trace: Optional REPLTrace accumulator for this code block
        &quot;&quot;&quot;
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()

        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        tok_out = _capture_stdout.set(stdout_buf)
        tok_err = _capture_stderr.set(stderr_buf)
        # Also replace sys.stdout/stderr directly: the _TaskLocalStream proxy
        # installed at module load may have been displaced (e.g. by pytest
        # capture), so the ContextVar route alone is not reliable.
        old_stdout, old_stderr = sys.stdout, sys.stderr
        # Inject cwd-aware open() and _repl_cwd into REPL namespace
        # instead of calling os.chdir() (FM-27: avoid process-global state).
        old_open = self.globals.get(&quot;__builtins__&quot;, {}).get(&quot;open&quot;)
        self.globals.setdefault(&quot;__builtins__&quot;, {})[&quot;open&quot;] = self._make_cwd_open()
        self.globals[&quot;_repl_cwd&quot;] = self.temp_dir
        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf

            if trace is not None:
                # Inject trace into the globals the compiled function sees
                self.globals[&quot;_rlm_trace&quot;] = trace
                trace.start_time = time.perf_counter()
                trace.execution_mode = &quot;async&quot;

            # Run the async _repl_exec function
            new_locals = await repl_exec_fn()

            if trace is not None:
                trace.end_time = time.perf_counter()

            # Update locals with results
            if isinstance(new_locals, dict):
                for key, value in new_locals.items():
                    if not key.startswith(&quot;_&quot;):
                        self.locals[key] = value

            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()
            self._last_exec_error = None
        except Exception as e:
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue() + f&quot;\n{type(e).__name__}: {e}&quot;
            self._last_exec_error = f&quot;{type(e).__name__}: {e}&quot;
            if trace is not None:
                trace.end_time = time.perf_counter()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            _capture_stdout.reset(tok_out)
            _capture_stderr.reset(tok_err)
            # Restore original open() builtin
            if old_open is not None:
                self.globals.setdefault(&quot;__builtins__&quot;, {})[&quot;open&quot;] = old_open
            # Clean up trace and _repl_cwd from globals
            self.globals.pop(&quot;_rlm_trace&quot;, None)
            self.globals.pop(&quot;_repl_cwd&quot;, None)

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

    def cleanup(self) -&gt; None:
        &quot;&quot;&quot;Clean up temp directory and reset state.&quot;&quot;&quot;
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
        self.globals.clear()
        self.locals.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()</content>
    

  </file>
  <file>
    
  
    <path>__init__.py</path>
    
  
    <content>&quot;&quot;&quot;RLM ADK REPL - Local REPL execution and AST rewriting.&quot;&quot;&quot;</content>
    

  </file>
  <file>
    
  
    <path>trace.py</path>
    
  
    <content>&quot;&quot;&quot;REPL execution tracing infrastructure.

Provides invisible instrumentation for REPL code block execution:
- REPLTrace: Per-code-block trace accumulator (timing, LLM calls, vars, memory)
- DataFlowTracker: Detects when one llm_query response feeds into a subsequent prompt
- Trace header/footer strings for optional code injection (trace_level &gt;= 2)

Trace levels (RLM_REPL_TRACE env var):
- 0: Off (default) - no tracing overhead
- 1: LLM call timing + variable snapshots + data flow tracking
- 2: + tracemalloc memory tracking via injected header/footer
&quot;&quot;&quot;

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class REPLTrace:
    &quot;&quot;&quot;Invisible trace accumulator for a single REPL code block execution.&quot;&quot;&quot;

    start_time: float = 0.0
    end_time: float = 0.0
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    var_snapshots: list[dict[str, Any]] = field(default_factory=list)
    peak_memory_bytes: int = 0
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    data_flow_edges: list[tuple[int, int]] = field(default_factory=list)
    execution_mode: str = &quot;sync&quot;  # &quot;sync&quot; | &quot;async&quot;
    submitted_code_chars: int = 0
    submitted_code_hash: str | None = None
    submitted_code_preview: str = &quot;&quot;
    _call_counter: int = field(default=0, repr=False)

    def record_llm_start(self, call_index: int, prompt: str, call_type: str = &quot;single&quot;) -&gt; None:
        &quot;&quot;&quot;Record the start of an LLM call.&quot;&quot;&quot;
        self.llm_calls.append({
            &quot;index&quot;: call_index,
            &quot;type&quot;: call_type,
            &quot;start_time&quot;: time.perf_counter(),
            &quot;prompt_len&quot;: len(prompt),
        })

    def record_llm_end(
        self,
        call_index: int,
        response: str,
        elapsed_ms: float,
        error: bool = False,
        **extra: Any,
    ) -&gt; None:
        &quot;&quot;&quot;Record the end of an LLM call, updating the existing entry.&quot;&quot;&quot;
        for entry in self.llm_calls:
            if entry.get(&quot;index&quot;) == call_index:
                entry[&quot;elapsed_ms&quot;] = round(elapsed_ms, 2)
                entry[&quot;response_len&quot;] = len(response)
                entry[&quot;error&quot;] = error
                entry.update(extra)
                return
        # If no matching start entry, create a new one
        self.llm_calls.append({
            &quot;index&quot;: call_index,
            &quot;elapsed_ms&quot;: round(elapsed_ms, 2),
            &quot;response_len&quot;: len(response),
            &quot;error&quot;: error,
            **extra,
        })

    def snapshot_vars(self, namespace: dict[str, Any], label: str = &quot;&quot;) -&gt; None:
        &quot;&quot;&quot;Capture a snapshot of user-visible variables.&quot;&quot;&quot;
        snapshot: dict[str, Any] = {&quot;label&quot;: label, &quot;time&quot;: time.perf_counter()}
        var_summary: dict[str, str] = {}
        for k, v in namespace.items():
            if k.startswith(&quot;_&quot;):
                continue
            try:
                type_name = type(v).__name__
                if isinstance(v, (str, int, float, bool)):
                    var_summary[k] = f&quot;{type_name}({repr(v)[:80]})&quot;
                elif isinstance(v, (list, dict, tuple, set)):
                    var_summary[k] = f&quot;{type_name}(len={len(v)})&quot;
                else:
                    var_summary[k] = type_name
            except Exception:
                var_summary[k] = &quot;?&quot;
        snapshot[&quot;vars&quot;] = var_summary
        self.var_snapshots.append(snapshot)

    def to_dict(self) -&gt; dict[str, Any]:
        &quot;&quot;&quot;Serialize to a JSON-compatible dict.&quot;&quot;&quot;
        return {
            &quot;wall_time_ms&quot;: round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0,
            &quot;execution_mode&quot;: self.execution_mode,
            &quot;submitted_code_chars&quot;: self.submitted_code_chars,
            &quot;submitted_code_hash&quot;: self.submitted_code_hash,
            &quot;submitted_code_preview&quot;: self.submitted_code_preview,
            &quot;llm_calls&quot;: self.llm_calls,
            &quot;var_snapshots&quot;: self.var_snapshots,
            &quot;peak_memory_bytes&quot;: self.peak_memory_bytes,
            &quot;exceptions&quot;: self.exceptions,
            &quot;data_flow_edges&quot;: self.data_flow_edges,
        }

    def summary(self) -&gt; dict[str, Any]:
        &quot;&quot;&quot;Compact summary for LAST_REPL_RESULT enrichment.&quot;&quot;&quot;
        return {
            &quot;wall_time_ms&quot;: round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0,
            &quot;llm_call_count&quot;: len(self.llm_calls),
            &quot;failed_llm_calls&quot;: sum(1 for c in self.llm_calls if c.get(&quot;error&quot;)),
            &quot;peak_memory_bytes&quot;: self.peak_memory_bytes,
            &quot;data_flow_edges&quot;: len(self.data_flow_edges),
            &quot;submitted_code_chars&quot;: self.submitted_code_chars,
            &quot;submitted_code_hash&quot;: self.submitted_code_hash,
        }


class DataFlowTracker:
    &quot;&quot;&quot;Detects when one llm_query() response feeds into a subsequent prompt.

    Uses substring fingerprinting: if a significant substring of a previous
    response appears in a later prompt, we record a data flow edge.
    &quot;&quot;&quot;

    def __init__(self, min_fingerprint_len: int = 40):
        self._responses: dict[int, str] = {}  # call_index -&gt; response text
        self._edges: list[tuple[int, int]] = []
        self._min_len = min_fingerprint_len

    def register_response(self, call_index: int, response: str) -&gt; None:
        &quot;&quot;&quot;Register a completed LLM response for future fingerprint matching.&quot;&quot;&quot;
        self._responses[call_index] = response

    def check_prompt(self, call_index: int, prompt: str) -&gt; None:
        &quot;&quot;&quot;Check if this prompt contains substrings from previous responses.&quot;&quot;&quot;
        if len(prompt) &lt; self._min_len:
            return
        for prev_index, prev_response in self._responses.items():
            if prev_index &gt;= call_index:
                continue
            if len(prev_response) &lt; self._min_len:
                continue
            # Check if a significant substring of the response appears in the prompt
            fingerprint = prev_response[:self._min_len]
            if fingerprint in prompt:
                edge = (prev_index, call_index)
                if edge not in self._edges:
                    self._edges.append(edge)

    def get_edges(self) -&gt; list[tuple[int, int]]:
        &quot;&quot;&quot;Return detected data flow edges as (source_index, target_index) tuples.&quot;&quot;&quot;
        return list(self._edges)


# ---------------------------------------------------------------------------
# Trace header/footer strings for code injection (trace_level &gt;= 2)
# ---------------------------------------------------------------------------

TRACE_HEADER = '''\
# --- RLM Trace Header ---
try:
    import time as _rlm_time
    _rlm_trace.start_time = _rlm_time.perf_counter()
except Exception:
    pass
'''

TRACE_HEADER_MEMORY = '''\
# --- RLM Trace Header (with memory) ---
try:
    import time as _rlm_time
    import tracemalloc as _rlm_tracemalloc
    _rlm_trace.start_time = _rlm_time.perf_counter()
    _rlm_mem_was_tracing = _rlm_tracemalloc.is_tracing()
    if not _rlm_mem_was_tracing:
        _rlm_tracemalloc.start()
except Exception:
    pass
'''

TRACE_FOOTER = '''\
# --- RLM Trace Footer ---
try:
    _rlm_trace.end_time = _rlm_time.perf_counter()
except Exception:
    pass
'''

TRACE_FOOTER_MEMORY = '''\
# --- RLM Trace Footer (with memory) ---
try:
    if not _rlm_mem_was_tracing:
        _current, _peak = _rlm_tracemalloc.get_traced_memory()
        _rlm_trace.peak_memory_bytes = _peak
        _rlm_tracemalloc.stop()
    _rlm_trace.end_time = _rlm_time.perf_counter()
except Exception:
    pass
'''</content>
    

  </file>
</repository_files>
<statistics>
  <total_files>4</total_files>
  <total_chars>30999</total_chars>
  <total_tokens>0</total_tokens>
  <generated_at>2026-03-10 10:45:03</generated_at>
</statistics>
</repository>