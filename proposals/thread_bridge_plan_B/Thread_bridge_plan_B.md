# Thread Bridge + ADK SkillToolset: Detailed Implementation Spec

## Context

RLM-ADK's skill system has been fully gutted after several false starts. The vision is unchanged: skills are typed Python functions callable via `execute_code` that accumulate over time. The blocker was that module-imported functions calling `llm_query()` fail because the AST rewriter only transforms the submitted code string — imported function bodies are opaque bytecode. The sync `llm_query` stub in REPL globals intentionally raises `RuntimeError`.

This plan replaces the AST-rewriting execution model with a thread-bridge that makes `llm_query()` a real sync callable, then layers ADK's upstream `SkillToolset` for L1/L2 discovery. Skill functions accept `llm_query_fn` as a parameter (auto-injected by the loader) so they are testable in isolation.

**ADK compatibility verified**: ADK already runs sync tools in thread pools (`functions.py:_call_tool_in_thread_pool`). State mutations are GIL-protected plain dicts. Callbacks run sequentially in the event loop thread after tool completion. `ParallelAgent` uses `asyncio.TaskGroup` entirely in the event loop. Child dispatch via `run_coroutine_threadsafe()` works — full lifecycle stays in event loop. Event queue bridging unchanged.

---

## Phase 1: Thread Bridge Foundation

**Goal**: Make `llm_query()` a real sync callable so module-imported functions can call it.

### Step 1A: New file `rlm_adk/repl/thread_bridge.py`

```python
"""Sync-to-async bridge for llm_query dispatch from worker threads.

Replaces the AST rewriter approach. Instead of source-level transformation
(llm_query -> await llm_query_async), the sync wrappers use
asyncio.run_coroutine_threadsafe() to submit async dispatch coroutines
to the event loop and block the calling thread on future.result().

This works because REPL code executes in a worker thread (via
loop.run_in_executor) while the event loop thread is free to process
the submitted coroutines.
"""

import asyncio
import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


def make_sync_llm_query(
    llm_query_async: Callable,
    loop: asyncio.AbstractEventLoop,
    timeout: float | None = None,
) -> Callable:
    """Create a sync llm_query that bridges to async dispatch via the event loop.

    Args:
        llm_query_async: The async dispatch closure from create_dispatch_closures().
        loop: The running event loop (captured in orchestrator._run_async_impl).
        timeout: Max seconds to wait for child dispatch. Defaults to
            RLM_LLM_QUERY_TIMEOUT env var, then 600.0.

    Returns:
        A sync callable with signature: (prompt, model=None, output_schema=None) -> LLMResult
    """
    _timeout = timeout or float(os.getenv("RLM_LLM_QUERY_TIMEOUT", "600"))

    def llm_query(
        prompt: str,
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> Any:  # Returns LLMResult (avoid circular import)
        future = asyncio.run_coroutine_threadsafe(
            llm_query_async(prompt, model=model, output_schema=output_schema),
            loop,
        )
        return future.result(timeout=_timeout)

    return llm_query


def make_sync_llm_query_batched(
    llm_query_batched_async: Callable,
    loop: asyncio.AbstractEventLoop,
    timeout: float | None = None,
) -> Callable:
    """Create a sync llm_query_batched that bridges to async dispatch.

    Same pattern as make_sync_llm_query but for batched dispatch.
    asyncio.gather() inside llm_query_batched_async runs all N children
    concurrently in the event loop.

    Returns:
        A sync callable with signature: (prompts, model=None, output_schema=None) -> list[LLMResult]
    """
    _timeout = timeout or float(os.getenv("RLM_LLM_QUERY_TIMEOUT", "600"))

    def llm_query_batched(
        prompts: list[str],
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> list[Any]:  # Returns list[LLMResult]
        future = asyncio.run_coroutine_threadsafe(
            llm_query_batched_async(prompts, model=model, output_schema=output_schema),
            loop,
        )
        return future.result(timeout=_timeout)

    return llm_query_batched
```

### Step 1B: Add `execute_code_threaded()` to `rlm_adk/repl/local_repl.py`

Two new methods after `execute_code()` (line 367):

```python
def _execute_code_threadsafe(
    self, code: str, trace: REPLTrace | None = None,
) -> tuple[str, str, bool]:
    """Execute code in a worker thread WITHOUT _EXEC_LOCK or os.chdir().

    Uses _make_cwd_open() for CWD-safe file access (same pattern as
    execute_code_async). This avoids deadlock under recursive dispatch:
    parent holds worker thread -> llm_query() -> child orchestrator ->
    child REPL needs its own worker thread.

    Returns (stdout, stderr, success).
    """
    trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))

    # CWD-safe namespace injection (NO os.chdir)
    old_open = self.globals.get("__builtins__", {}).get("open")
    self.globals.setdefault("__builtins__", {})["open"] = self._make_cwd_open()
    self.globals["_repl_cwd"] = self.temp_dir

    # stdout/stderr capture via ContextVar (thread-safe)
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    tok_out = _capture_stdout.set(stdout_buf)
    tok_err = _capture_stderr.set(stderr_buf)

    try:
        combined = {**self.globals, **self.locals}

        # Register trace callbacks
        pre_cb = post_cb = None
        if trace is not None and trace_level >= 1:
            pre_cb, post_cb = self._executor.register_trace_callbacks(
                trace, trace_level,
            )

        try:
            stdout_raw, stderr_raw, success = self._executor.execute_sync(
                code, combined,
            )
        finally:
            if pre_cb is not None:
                self._executor.unregister_trace_callbacks(pre_cb, post_cb)

        # Merge ContextVar capture with executor capture
        ctx_stdout = stdout_buf.getvalue()
        ctx_stderr = stderr_buf.getvalue()
        stdout = ctx_stdout + stdout_raw if ctx_stdout else stdout_raw
        stderr = ctx_stderr + stderr_raw if ctx_stderr else stderr_raw

        if success:
            for key, value in combined.items():
                if key not in self.globals and not key.startswith("_"):
                    self.locals[key] = value
            last_expr = combined.get("_last_expr")
            if last_expr is not None:
                self.locals["_last_expr"] = last_expr
            else:
                self.locals.pop("_last_expr", None)
            self._last_exec_error = None
        else:
            self._last_exec_error = (
                stderr.strip().split("\n")[-1] if stderr.strip() else None
            )
            self.locals.pop("_last_expr", None)

        return stdout, stderr, success
    finally:
        _capture_stdout.reset(tok_out)
        _capture_stderr.reset(tok_err)
        # Restore builtins
        if old_open is not None:
            self.globals.setdefault("__builtins__", {})["open"] = old_open
        self.globals.pop("_repl_cwd", None)


async def execute_code_threaded(
    self, code: str, trace: REPLTrace | None = None,
) -> REPLResult:
    """Execute code in a dedicated worker thread.

    llm_query() (a real sync callable in self.globals) bridges back to
    the event loop via run_coroutine_threadsafe(). The event loop is
    free because this method yields via run_in_executor().

    One-shot ThreadPoolExecutor prevents default-pool exhaustion under
    recursive dispatch (parent/child/grandchild each need a thread).
    """
    start_time = time.perf_counter()
    self._pending_llm_calls.clear()

    if trace is not None:
        trace.start_time = time.perf_counter()
        trace.execution_mode = "thread_bridge"

    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    timed_out = False

    try:
        stdout, stderr, _success = await asyncio.wait_for(
            loop.run_in_executor(
                executor, self._execute_code_threadsafe, code, trace,
            ),
            timeout=self.sync_timeout,
        )
    except asyncio.TimeoutError:
        timed_out = True
        stdout = ""
        stderr = (
            f"\nTimeoutError: Thread-bridge execution exceeded "
            f"{self.sync_timeout}s timeout"
        )
        self._last_exec_error = stderr.strip()
    finally:
        executor.shutdown(wait=not timed_out, cancel_futures=True)

    if trace is not None and not trace.end_time:
        trace.end_time = time.perf_counter()

    return REPLResult(
        stdout=stdout,
        stderr=stderr,
        locals=self.locals.copy(),
        execution_time=time.perf_counter() - start_time,
        llm_calls=self._pending_llm_calls.copy(),
        trace=trace.to_dict() if trace else None,
    )
```

**Why no `_EXEC_LOCK`**: Parent worker thread T1 holds `_EXEC_LOCK` → calls `llm_query()` → blocks on `future.result()` → event loop runs child → child REPLTool → child worker T2 tries `_EXEC_LOCK` → **DEADLOCK**. The `_execute_code_threadsafe` method avoids this entirely by using `_make_cwd_open()` (already exists at line 369) instead of `os.chdir()`.

**Why one-shot executor**: Default `ThreadPoolExecutor` has limited workers. Recursive dispatch needs N threads simultaneously (one per depth level, all blocked waiting). One-shot executors are created per-call and cleaned up immediately.

### Step 1C: Modify `REPLTool.__init__()` and `run_async()` in `rlm_adk/tools/repl_tool.py`

**`__init__` changes** (add after line 72, modify line 92-94):

```python
# Add parameter:
use_thread_bridge: bool = True,

# In body, add:
self._use_thread_bridge = use_thread_bridge if os.getenv(
    "RLM_REPL_THREAD_BRIDGE", "1"
) != "0" else False
```

Remove lines 92-94 (AST rewriter telemetry — obsolete for default path):
```python
# DELETE:
self._rewrite_count = 0
self._rewrite_total_ms = 0.0
self._rewrite_failure_count = 0
```

**`run_async` changes** — replace lines 222-243:

```python
        # --- Execution: thread bridge (default) or AST rewriter (fallback) ---
        try:
            if self._use_thread_bridge:
                # Thread bridge: all code runs in worker thread.
                # llm_query() is a real sync callable that bridges to event loop.
                llm_calls_made = has_llm_calls(exec_code)  # observability only
                result = await self.repl.execute_code_threaded(exec_code, trace=trace)
            else:
                # Legacy fallback: AST rewriter path
                if has_llm_calls(exec_code):
                    llm_calls_made = True
                    tree = rewrite_for_async(exec_code)
                    compiled = compile(tree, "<repl>", "exec")
                    result = await self.repl.execute_code_async(
                        code, trace=trace, compiled=compiled,
                    )
                else:
                    result = self.repl.execute_code(exec_code, trace=trace)
```

**Import changes** at top of file (line 26): keep `has_llm_calls` import, make `rewrite_for_async` conditional:

```python
from rlm_adk.repl.ast_rewriter import has_llm_calls
# rewrite_for_async imported lazily in fallback path
```

### Step 1D: Modify orchestrator wiring in `rlm_adk/orchestrator.py`

Replace lines 288-297 (the sync stub block):

```python
            # --- Wire dispatch closures ---
            from rlm_adk.repl.thread_bridge import (
                make_sync_llm_query,
                make_sync_llm_query_batched,
            )

            _loop = asyncio.get_running_loop()

            # Sync bridge: real llm_query() callable for thread-bridge mode
            repl.set_llm_query_fns(
                make_sync_llm_query(llm_query_async, _loop),
                make_sync_llm_query_batched(llm_query_batched_async, _loop),
            )
            # Async closures kept for AST rewriter fallback path
            repl.set_async_llm_query_fns(
                llm_query_async, llm_query_batched_async,
            )
```

### Step 1D.5: Builtins safety net for ad-hoc code (`rlm_adk/orchestrator.py`)

**Problem**: The `llm_query_fn` parameter pattern (Phase 2) solves module-import scoping for *registered skill functions*. But reasoning agents also write ad-hoc code: one-off helper functions defined in `execute_code`, quick utility modules the model creates and imports, or third-party library callbacks. These ad-hoc functions have their own `__globals__` dicts and cannot see `llm_query` from REPL globals. The `llm_query_fn` parameter convention does not apply to code the model invents on the fly.

**Solution**: Inject `llm_query` and `llm_query_batched` into Python's `builtins` module as a complementary safety net. This is the established IPython/Jupyter kernel pattern — `get_ipython()` works this way. Builtins are the last resort in Python's LEGB name resolution chain, so any code anywhere in the process can resolve `llm_query` without explicit imports or parameter passing.

In `_run_async_impl()`, after wiring sync closures (Step 1D) and before REPL execution begins:

```python
            import builtins

            _sync_llm_query = make_sync_llm_query(llm_query_async, _loop)
            _sync_llm_query_batched = make_sync_llm_query_batched(
                llm_query_batched_async, _loop,
            )

            # Primary path: REPL globals (for direct REPL code)
            repl.set_llm_query_fns(_sync_llm_query, _sync_llm_query_batched)
            # Async closures kept for AST rewriter fallback path
            repl.set_async_llm_query_fns(
                llm_query_async, llm_query_batched_async,
            )

            # Safety net: builtins injection (IPython/Jupyter kernel pattern)
            # Allows ad-hoc functions, dynamically-imported modules, and
            # third-party callbacks to resolve llm_query without explicit
            # parameter passing. Cleaned up in finally block.
            builtins.llm_query = _sync_llm_query
            builtins.llm_query_batched = _sync_llm_query_batched
```

Cleanup in the `finally` block of `_run_async_impl()`:

```python
        finally:
            # Remove builtins safety net (process-global, must clean up)
            import builtins
            builtins.__dict__.pop("llm_query", None)
            builtins.__dict__.pop("llm_query_batched", None)
```

**Relationship to `llm_query_fn` parameter pattern**: The two mechanisms serve different populations:

| Mechanism | Serves | Testability | Scope |
|---|---|---|---|
| `llm_query_fn` parameter (Phase 2) | Registered skill functions | Excellent: pass mock in tests | Per-function |
| `builtins` injection (this step) | Ad-hoc model-written code, dynamic imports | Implicit: available everywhere | Process-global |

Registered skills should continue using the `llm_query_fn` parameter pattern for testability. The builtins injection is a fallback for the long tail of unstructured code.

**Thread safety under recursive dispatch**: Under single-child dispatch (`llm_query()`), the parent worker thread is blocked on `future.result()` when the child orchestrator writes to builtins — no concurrent mutation. Under batched dispatch (`llm_query_batched()`), multiple children run concurrently on the event loop. Each child's `_run_async_impl` writes to `builtins.llm_query` with its own closure. Since children are async coroutines on the event loop (cooperative scheduling), writes interleave at `await` points. If Child A writes builtins, then Child B writes before Child A's REPL code runs, Child A's REPL code picks up Child B's closure — a correctness bug. However, this only affects ad-hoc code that relies on builtins resolution; registered skill functions use the `llm_query_fn` parameter and are unaffected. For the batched case, the builtins safety net is best-effort, not authoritative. Document this caveat in the code comment.

**Why not builtins-only**: Builtins are process-global. Multiple concurrent top-level orchestrators in the same process would clobber each other. The `llm_query_fn` parameter pattern is scoped per-function-call and is the correct primary mechanism. Builtins injection is a convenience fallback, not a replacement.

### Step 1E: Add `"execution_mode"` to LAST_REPL_RESULT

In `repl_tool.py`, in the `last_repl` dict construction (around line 314), add:

```python
"execution_mode": "thread_bridge" if self._use_thread_bridge else (
    "async_rewrite" if llm_calls_made else "sync"
),
```

---

## Phase 2: Skill Infrastructure with `llm_query_fn` Parameter Pattern

**Goal**: Skills are typed Python functions in regular modules. Functions that need LLM dispatch accept `llm_query_fn` as a parameter. The loader auto-injects it from REPL globals.

### Step 2A: Skill directory convention

```
rlm_adk/skills/<skill-name>/          # kebab-case, matches SKILL.md name field
    SKILL.md                           # ADK L1 frontmatter + L2 instructions
    __init__.py                        # SKILL_EXPORTS list
    <impl>.py                          # Typed function(s)
    references/                        # Optional: for load_skill_resource
    assets/                            # Optional: for load_skill_resource
```

ADK constraint: directory name must exactly match `frontmatter.name` (enforced by `load_skill_from_dir`, `_utils.py`).

Python module path: `rlm_adk.skills.<skill_name_underscored>` (e.g., `rlm_adk.skills.recursive_ping`).

### Step 2B: The `llm_query_fn` parameter pattern

Skill functions that need LLM dispatch declare `llm_query_fn` as a keyword parameter:

```python
# rlm_adk/skills/recursive_ping/ping.py
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RecursivePingResult:
    layer: int
    payload: dict[str, Any]


def run_recursive_ping(
    max_layer: int = 2,
    starting_layer: int = 0,
    terminal_payload: dict | None = None,
    *,
    llm_query_fn: Callable | None = None,  # auto-injected by loader
) -> RecursivePingResult:
    """Dispatch recursive llm_query() calls across depth layers.

    Args:
        max_layer: Maximum recursion depth.
        starting_layer: Current layer index.
        terminal_payload: JSON payload returned by terminal layer.
        llm_query_fn: LLM dispatch callable. Auto-injected when called
            from REPL; pass explicitly in tests.
    """
    if llm_query_fn is None:
        raise RuntimeError(
            "llm_query_fn not provided. This function must be called "
            "from the REPL (auto-injected) or with an explicit llm_query_fn."
        )

    payload = terminal_payload or {"my_response": "pong", "your_response": "ping"}

    if starting_layer >= max_layer:
        # Terminal layer
        return RecursivePingResult(layer=starting_layer, payload=payload)

    # Dispatch to next layer
    child_result = llm_query_fn(
        f"You are layer {starting_layer + 1}. "
        f"Call run_recursive_ping(starting_layer={starting_layer + 1}) "
        f"and return the result."
    )
    return RecursivePingResult(layer=starting_layer, payload=payload)
```

**Why `llm_query_fn` parameter, not global reference**:
- **Testable in isolation**: pass a mock `llm_query_fn` in unit tests
- **No module-level global mutation**: no patching `ping_module.llm_query`
- **Explicit dependency**: the function signature documents that it needs LLM dispatch
- **Thread-safe**: no shared mutable state between concurrent REPL instances

### Step 2C: Skill `__init__.py` convention

```python
# rlm_adk/skills/recursive_ping/__init__.py
from rlm_adk.skills.recursive_ping.ping import (
    RecursivePingResult,
    run_recursive_ping,
)

# Functions and types to inject into REPL globals.
# Functions with a `llm_query_fn` parameter get it auto-injected.
SKILL_EXPORTS = [run_recursive_ping, RecursivePingResult]
```

### Step 2D: New file `rlm_adk/skills/loader.py`

```python
"""Skill discovery, ADK loading, and REPL globals injection.

Three responsibilities:
1. discover_skill_dirs() — find skill directories with SKILL.md
2. load_adk_skills() — load ADK Skill objects for SkillToolset
3. collect_skill_repl_globals() — import Python modules, wrap functions
   with llm_query_fn auto-injection, return dict for repl.globals.update()
"""

import functools
import importlib
import inspect
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent
_SKIP_DIRS = {"obsolete", "__pycache__", ".git"}


def discover_skill_dirs(
    enabled_skills: Iterable[str] | None = None,
) -> list[Path]:
    """Find skill directories under rlm_adk/skills/ containing SKILL.md.

    Args:
        enabled_skills: If provided, only return dirs whose name is in this set.
            If None, return all discovered skill dirs.

    Returns:
        List of Path objects for valid skill directories.
    """
    enabled_set = set(enabled_skills) if enabled_skills is not None else None
    dirs = []
    for child in sorted(_SKILLS_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIRS or child.name.startswith("."):
            continue
        if not (child / "SKILL.md").exists():
            continue
        if enabled_set is not None and child.name not in enabled_set:
            continue
        dirs.append(child)
    return dirs


def load_adk_skills(
    enabled_skills: Iterable[str] | None = None,
) -> list:
    """Load ADK Skill objects from discovered skill directories.

    Uses google.adk.skills.load_skill_from_dir() for each directory.
    Returns list[Skill] for passing to SkillToolset(skills=...).
    """
    from google.adk.skills import load_skill_from_dir

    skills = []
    for skill_dir in discover_skill_dirs(enabled_skills):
        try:
            skill = load_skill_from_dir(skill_dir)
            skills.append(skill)
            logger.debug("Loaded ADK skill: %s", skill.name)
        except Exception:
            logger.warning(
                "Failed to load ADK skill from %s", skill_dir, exc_info=True,
            )
    return skills


def _has_llm_query_fn_param(fn: Callable) -> bool:
    """Check if a callable has a 'llm_query_fn' parameter."""
    try:
        sig = inspect.signature(fn)
        return "llm_query_fn" in sig.parameters
    except (ValueError, TypeError):
        return False


def _wrap_with_llm_query_injection(
    fn: Callable, repl_globals: dict[str, Any],
) -> Callable:
    """Wrap a skill function to auto-inject llm_query_fn from REPL globals.

    The wrapper checks if llm_query_fn is already provided (e.g., in tests).
    If not, injects the llm_query from repl.globals at call time.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if "llm_query_fn" not in kwargs or kwargs["llm_query_fn"] is None:
            _llm_query = repl_globals.get("llm_query")
            if _llm_query is None:
                raise RuntimeError(
                    f"llm_query not available in REPL globals when calling "
                    f"{fn.__name__}(). Ensure dispatch closures are wired."
                )
            kwargs["llm_query_fn"] = _llm_query
        return fn(*args, **kwargs)

    return wrapper


def collect_skill_repl_globals(
    enabled_skills: Iterable[str] | None = None,
    repl_globals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Import skill Python modules and collect exports for REPL globals.

    For each discovered skill directory:
    1. Convert kebab-case dir name to underscore module path
    2. Import rlm_adk.skills.<module_name>
    3. Read SKILL_EXPORTS list
    4. Wrap functions with llm_query_fn auto-injection if they have the param
    5. Collect into {name: callable_or_type} dict

    Args:
        enabled_skills: Filter to these skill names (None = all).
        repl_globals: The REPL globals dict (needed for llm_query injection).
            If None, wrapping is skipped (functions injected unwrapped).

    Returns:
        Dict of {export_name: callable_or_type} to merge into repl.globals.
    """
    exports: dict[str, Any] = {}
    injected_names: list[str] = []

    for skill_dir in discover_skill_dirs(enabled_skills):
        module_name = skill_dir.name.replace("-", "_")
        module_path = f"rlm_adk.skills.{module_name}"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            logger.warning(
                "Skill dir %s has SKILL.md but no importable module %s",
                skill_dir.name, module_path,
            )
            continue

        skill_exports = getattr(mod, "SKILL_EXPORTS", None)
        if not skill_exports:
            logger.debug(
                "Skill module %s has no SKILL_EXPORTS, skipping", module_path,
            )
            continue

        for obj in skill_exports:
            name = getattr(obj, "__name__", None) or getattr(obj, "__qualname__", None)
            if name is None:
                continue

            if callable(obj) and _has_llm_query_fn_param(obj) and repl_globals is not None:
                exports[name] = _wrap_with_llm_query_injection(obj, repl_globals)
            else:
                exports[name] = obj
            injected_names.append(name)

    if injected_names:
        logger.info("Skill REPL globals injected: %s", injected_names)

    return exports
```

### Step 2E: Wire skill globals in orchestrator

In `rlm_adk/orchestrator.py`, after line 259 (`repl.globals["LLMResult"] = LLMResult`), add:

```python
        # Inject skill function exports into REPL globals
        if self.enabled_skills:
            from rlm_adk.skills.loader import collect_skill_repl_globals

            _skill_globals = collect_skill_repl_globals(
                enabled_skills=self.enabled_skills,
                repl_globals=repl.globals,
            )
            repl.globals.update(_skill_globals)
```

Note: `repl_globals=repl.globals` is passed so the wrapper closure captures a reference to the same dict where `llm_query` will be wired later (Step 1D). The wrapper reads `llm_query` at call time (lazy), not at wrap time, so ordering doesn't matter.

### Step 2F: Update `rlm_adk/skills/__init__.py`

```python
"""RLM-ADK Skills — typed Python functions for REPL execution.

Skills are regular Python modules with ADK SKILL.md frontmatter.
Functions that need LLM dispatch accept llm_query_fn as a parameter,
which is auto-injected by the skill loader when running in the REPL.

Skill directories live under this package. Each has:
- SKILL.md: ADK L1 frontmatter + L2 instructions
- __init__.py: SKILL_EXPORTS list
- Implementation modules with typed functions
"""
```

---

## Phase 3: Wire ADK SkillToolset for L1/L2 Discovery

**Goal**: Model can discover skills via XML in system instruction, load full I/O contracts via `load_skill` tool call, then invoke skill functions via `execute_code`.

### Step 3A: Create SkillToolset in orchestrator

In `rlm_adk/orchestrator.py`, replace lines 331-332 (the tools list construction):

```python
        # Wire reasoning_agent at runtime with tools.
        schema = self.output_schema or ReasoningOutput
        set_model_response_tool = SetModelResponseTool(schema)

        tools = [repl_tool, set_model_response_tool]

        # Add SkillToolset for L1/L2 discovery if skills are enabled
        if self.enabled_skills:
            from google.adk.tools.skill_toolset import SkillToolset
            from rlm_adk.skills.loader import load_adk_skills

            _adk_skills = load_adk_skills(enabled_skills=self.enabled_skills)
            if _adk_skills:
                tools.append(SkillToolset(skills=_adk_skills))

        object.__setattr__(self.reasoning_agent, "tools", tools)
```

**What ADK does automatically** (via `_process_agent_tools` in `base_llm_flow.py`):
1. Calls `SkillToolset.process_llm_request()` → appends `_DEFAULT_SKILL_SYSTEM_INSTRUCTION` + `<available_skills>` XML to system instruction
2. Calls `get_tools()` → returns `[ListSkillsTool, LoadSkillTool, LoadSkillResourceTool, RunSkillScriptTool]`
3. Each tool registers its `FunctionDeclaration`

**Model's three-phase workflow**:
1. **Discover**: See skill names in system instruction XML (automatic, every turn)
2. **Understand**: Call `load_skill(name="recursive-ping")` → get full L2 instructions with function signatures, typed I/O, usage examples
3. **Invoke**: Call `execute_code` with code that calls the skill function

### Step 3B: `instruction_router` coexistence

`instruction_router` (lines 383-405) continues to inject per-depth/fanout instructions via `DYN_SKILL_INSTRUCTION` and `before_agent_callback`. `SkillToolset` operates at the tool level. They are orthogonal:
- `instruction_router` → template variable `{skill_instruction?}` in dynamic instruction
- `SkillToolset` → system instruction XML + `load_skill` / `list_skills` tools

No changes needed to instruction_router.

### Step 3C: `enabled_skills` is now consumed

The `enabled_skills` tuple on `RLMOrchestratorAgent` (line 237) is now consumed by:
- `collect_skill_repl_globals(enabled_skills=...)` → Phase 2E
- `load_adk_skills(enabled_skills=...)` → Phase 3A

The plumbing through `agent.py` factories (lines 286, 319, 523, 557) already works.

---

## Phase 3.5: CRITICAL — Fix `reasoning_before_model` System Instruction Overwrite

**Problem discovered by review**: ADK's execution order is:
1. `_process_agent_tools()` → `SkillToolset.process_llm_request()` → appends L1 XML to `llm_request.config.system_instruction`
2. `_handle_before_model_callback()` → `reasoning_before_model` → **REPLACES** `system_instruction` entirely with merged static+dynamic text

The `reasoning_before_model` callback in `rlm_adk/callbacks/reasoning.py` (line 144-146) does:
```python
llm_request.config.system_instruction = system_instruction_text
```
This **overwrites** anything `SkillToolset.process_llm_request()` appended. Skills would NEVER appear in the model's prompt.

### Fix in `rlm_adk/callbacks/reasoning.py`

Change `reasoning_before_model` to **append** to existing system_instruction rather than replace it. After computing `system_instruction_text`, read back any additions that toolsets made:

```python
# Preserve toolset-injected instructions (e.g., SkillToolset L1 XML)
existing_si = llm_request.config.system_instruction or ""
if isinstance(existing_si, str) and existing_si != system_instruction_text:
    # Toolsets appended content after static instruction was set
    # Find the toolset-added suffix and preserve it
    if existing_si.startswith(system_instruction_text):
        # No toolset additions — existing IS our text
        pass
    else:
        # Toolset content was appended; keep it
        llm_request.config.system_instruction = system_instruction_text + "\n\n" + existing_si
        return
llm_request.config.system_instruction = system_instruction_text
```

Alternatively (cleaner): change the callback to APPEND the dynamic instruction portion rather than replacing the full system_instruction. The static instruction is already set by ADK's `instructions.request_processor` before `_process_agent_tools` runs. The callback only needs to inject the dynamic portion.

---

## Phase 4: Observability (Revised per Review)

### Step 4A: State keys (`rlm_adk/state.py`)

```python
# Rename for consistency with repl_* prefix convention
REPL_SKILL_GLOBALS_INJECTED = "repl_skill_globals_injected"  # list[str] of function names
```

Add to `CURATED_STATE_PREFIXES`:
```python
"repl_skill_globals_injected",   # NEW
```

**Do NOT add to `DEPTH_SCOPED_KEYS`**. Skill globals are injected once at REPL creation time in `_run_async_impl`, not per-iteration. The value does not vary across depths — child orchestrators create their own REPLs with independently-injected globals. Same principle applies to `enabled_skills` itself: it is a construction-time Pydantic field, not a state-plane value. Depth-scoping is reserved for keys that change between iterations (e.g., `ITERATION_COUNT`, `LAST_REPL_RESULT`).

In orchestrator, after skill globals injection (Phase 2E), emit:
```python
            if _skill_globals:
                initial_state[REPL_SKILL_GLOBALS_INJECTED] = sorted(_skill_globals.keys())
```

### Step 4B: LineageEnvelope decision_mode expansion (`rlm_adk/types.py`)

Expand `decision_mode` Literal to cover all SkillToolset tool names:
```python
decision_mode: Literal[
    "execute_code",
    "set_model_response",
    "load_skill",
    "load_skill_resource",
    "list_skills",        # NEW
    "run_skill_script",   # NEW
    "unknown",
] = "unknown"
```

### Step 4C: SqliteTracingPlugin skill telemetry (`rlm_adk/plugins/sqlite_tracing.py`)

Add explicit `elif` branches in `after_tool_callback` (after existing `execute_code` / `set_model_response` branches, ~line 1291-1303):

```python
elif tool_name in ("load_skill", "load_skill_resource", "list_skills", "run_skill_script"):
    update_kwargs["decision_mode"] = tool_name
    skill_name = tool_args.get("name") or tool_args.get("skill_name")
    if skill_name:
        update_kwargs["skill_name_loaded"] = skill_name
    if isinstance(result, dict):
        instructions = result.get("instructions") or result.get("content") or ""
        if isinstance(instructions, str):
            update_kwargs["skill_instructions_len"] = len(instructions)
```

This populates the existing-but-always-NULL `skill_name_loaded` and `skill_instructions_len` telemetry columns.

**Known gap: `_agent_span_stack` interleaving under batched children.** `SqliteTracingPlugin._agent_span_stack` is a flat list used as a stack for agent_name attribution. When batched children (`llm_query_batched()`) run concurrently on the event loop, cooperative interleaving at `await` points can corrupt the stack: Child A pushes, Child B pushes, Child A pops — now the stack is wrong for Child B. This produces incorrect `agent_name` in telemetry rows. The fix is to scope the stack per `invocation_id` (replace the flat list with a `dict[str, list[str]]`). This is not a Phase 1 blocker — single-child dispatch (the common case) is unaffected — but file as a follow-up before batched skill dispatch is exercised in production. See callback expert review (Question 1) for the full analysis.

### Step 4D: REPLTrace execution_mode (`rlm_adk/repl/trace.py`)

Type-narrow the execution_mode field:
```python
execution_mode: Literal["sync", "async", "thread_bridge"] = "sync"
```

Source `execution_mode` in LAST_REPL_RESULT from trace (not independently), and add lightweight skill metadata to make the summary self-contained:
```python
if trace is not None:
    last_repl["execution_mode"] = trace.execution_mode
else:
    last_repl["execution_mode"] = "thread_bridge" if self._use_thread_bridge else "sync"

# Skill metadata — makes LAST_REPL_RESULT self-contained for dashboard/sqlite consumers
last_repl["skill_globals_count"] = len(self._injected_skill_names) if hasattr(self, '_injected_skill_names') else 0
last_repl["skill_expansion_occurred"] = expansion.did_expand if expansion else False
```

Do NOT add `execution_mode` as a formal field on the `REPLResult(BaseModel)` Pydantic model. Execution mode is a property of the tool dispatch path, not the REPL result. It already lives correctly in `REPLTrace.execution_mode` — the LAST_REPL_RESULT dict and return dict should read from that single source of truth.

### Step 4E: Child skill propagation (`rlm_adk/dispatch.py`, `rlm_adk/agent.py`)

Pass `enabled_skills` through to `create_child_orchestrator()`:
- Add `enabled_skills: tuple[str, ...] = ()` parameter to `create_child_orchestrator`
- Pass parent's `enabled_skills` in `_run_child()` dispatch closure
- Each child creates its own REPL and injects its own skill globals

**Split gating: SkillToolset vs REPL globals.** `enabled_skills` gates two separate concerns with different appropriate policies:

1. **SkillToolset (L1/L2 discovery tools)**: Gate by `enabled_skills`. Children should NOT get the 4 discovery tools (`list_skills`, `load_skill`, etc.) — discovery is a root-agent concern. Children are narrow-scope workers.
2. **REPL globals (Python functions)**: Inject **unconditionally**. If a child orchestrator's REPL code calls a skill function via the thread bridge, the function must be in its namespace. The thread bridge's whole purpose is making `llm_query()` callable from imported functions at any depth.

Implementation: in `_run_async_impl`, call `collect_skill_repl_globals()` for ALL orchestrators regardless of `self.enabled_skills`, but only create `SkillToolset` when `self.enabled_skills` is non-empty. This is simpler than propagating `enabled_skills` to children just for REPL injection.

### Step 4F: Instruction disambiguation (`rlm_adk/utils/prompts.py`)

Add 2-3 sentences to `RLM_STATIC_INSTRUCTION` clarifying the boundary between execution tools and discovery tools. The risk is semantic overlap: `run_skill_script` executes code (like `execute_code`), `load_skill_resource` reads files (like `execute_code` with `open()`). The model might try to use skill tools when it should use `execute_code`.

Suggested wording:
```
The `list_skills`, `load_skill`, `load_skill_resource`, and `run_skill_script` tools are for
DISCOVERING available skills before you use them. Once you know what skill functions are available,
call them via execute_code like any other Python function. `run_skill_script` materializes a
temporary directory and executes in isolation — it is NOT a substitute for execute_code and should
not be used for routine code execution or for calling REPL skill functions.
```

### Step 4G: Document `additional_tools` as future extension (`rlm_adk/orchestrator.py`)

Add a code comment in the SkillToolset wiring block (Phase 3A) explaining that `SkillToolset.additional_tools` is intentionally not used. ADK's `additional_tools` feature dynamically exposes per-skill tools after activation — useful for gating specialized tools (web scraper, DB connector) behind skill load. Not appropriate now because `execute_code` is the primary tool and must be available from step 1 (before any skill is loaded). Note as a future extension point.

```python
        # NOTE: SkillToolset.additional_tools intentionally not used.
        # ADK supports dynamically exposing per-skill tools after activation,
        # but execute_code must be available from step 1 (before any skill load).
        # additional_tools is a future extension for per-skill tool gating
        # (e.g., exposing a web scraper only after loading a research skill).
```

### Step 4H: Follow-up — `_agent_span_stack` per-invocation scoping

File a follow-up issue to scope `SqliteTracingPlugin._agent_span_stack` per `invocation_id` instead of per plugin instance. Replace `self._agent_span_stack: list[str]` with `self._agent_span_stacks: dict[str, list[str]]` keyed by invocation_id. This prevents interleaving under batched child dispatch (see Step 4C note). Not a Phase 1 blocker — single-child dispatch is unaffected.

---

## Phase 5: Testing

### Step 5A: `tests_rlm_adk/test_thread_bridge.py`

```python
"""Tests for the thread-bridge llm_query sync wrapper."""
import asyncio
import pytest
from rlm_adk.repl.thread_bridge import make_sync_llm_query, make_sync_llm_query_batched


class TestMakeSyncLlmQuery:
    def test_dispatches_from_worker_thread(self):
        """Sync wrapper submits to event loop, blocks worker, returns result."""
        loop = asyncio.new_event_loop()

        async def fake_llm_query_async(prompt, model=None, output_schema=None):
            return f"response to: {prompt}"

        sync_fn = make_sync_llm_query(fake_llm_query_async, loop)

        # Run sync_fn in a thread (simulating REPL worker)
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        async def test():
            result = await loop.run_in_executor(executor, sync_fn, "hello")
            assert result == "response to: hello"
            executor.shutdown(wait=False)

        loop.run_until_complete(test())
        loop.close()

    def test_timeout_raises(self):
        """Sync wrapper raises TimeoutError if child takes too long."""
        # ...

    def test_error_propagation(self):
        """Exceptions from async dispatch propagate to worker thread."""
        # ...


class TestMakeSyncLlmQueryBatched:
    def test_batched_runs_concurrently(self):
        """All N children run concurrently via asyncio.gather in event loop."""
        # ...
```

### Step 5B: `tests_rlm_adk/test_skill_loader.py`

```python
"""Tests for skill directory discovery and REPL globals injection."""
import pytest
from pathlib import Path
from rlm_adk.skills.loader import (
    discover_skill_dirs,
    load_adk_skills,
    collect_skill_repl_globals,
    _has_llm_query_fn_param,
    _wrap_with_llm_query_injection,
)


class TestDiscoverSkillDirs:
    def test_skips_obsolete(self):
        dirs = discover_skill_dirs()
        names = [d.name for d in dirs]
        assert "obsolete" not in names

    def test_filters_by_enabled_skills(self):
        # Only returns dirs matching enabled_skills
        ...

    def test_requires_skill_md(self):
        # Dirs without SKILL.md are skipped
        ...


class TestLlmQueryFnInjection:
    def test_has_llm_query_fn_param_detects_param(self):
        def fn_with(*, llm_query_fn=None): pass
        def fn_without(): pass
        assert _has_llm_query_fn_param(fn_with) is True
        assert _has_llm_query_fn_param(fn_without) is False

    def test_wrapper_injects_from_globals(self):
        mock_llm_query = lambda p: f"mock: {p}"
        repl_globals = {"llm_query": mock_llm_query}

        def skill_fn(text, *, llm_query_fn=None):
            return llm_query_fn(text)

        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)
        assert wrapped("hello") == "mock: hello"

    def test_wrapper_respects_explicit_llm_query_fn(self):
        repl_globals = {"llm_query": lambda p: "should not be called"}

        def skill_fn(text, *, llm_query_fn=None):
            return llm_query_fn(text)

        custom = lambda p: f"custom: {p}"
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)
        assert wrapped("hello", llm_query_fn=custom) == "custom: hello"
```

### Step 5C: Integration test — module-imported skill with `llm_query()`

This is the **previously impossible** test. A provider-fake fixture scripts the model calling a skill function that internally calls `llm_query()` via the thread bridge.

Test file: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`
Fixture file: `tests_rlm_adk/fixtures/provider_fake/skill_thread_bridge.json`

The fixture scripts:
1. Reasoning agent calls `execute_code` with `result = run_recursive_ping(llm_query_fn=llm_query)`
2. Inside `run_recursive_ping`, `llm_query()` dispatches to child
3. Child returns response
4. Parent REPL continues, `result` has the payload
5. Reasoning agent calls `set_model_response`

**Companion spec**: The full fixture JSON, complete test class (6 test classes, ~25 tests covering contract/state/telemetry/trace planes), callback flow diagram, and verification matrix are in `Thread_bridge_plan_B_e2e_test_design_rec.md` in this directory. That document should be the implementation reference for this step — it includes:
- Complete provider-fake fixture with 3 scripted responses (reasoning execute_code → worker set_model_response → reasoning set_model_response)
- Callback-by-callback sequence diagram showing every plugin/agent callback firing and what it writes
- Verification matrix mapping each data flow to source → write target → SQLite table/column → test method
- Documented failure modes (fixture response count mismatch, child set_model_response format, SSE key capture gaps)

### Step 5D: Regression safeguard

`RLM_REPL_THREAD_BRIDGE=0` falls back to AST rewriter path. Run existing suite in both modes:
```bash
.venv/bin/python -m pytest tests_rlm_adk/ -x -q
RLM_REPL_THREAD_BRIDGE=0 .venv/bin/python -m pytest tests_rlm_adk/ -x -q
```

---

## Implementation Sequence

```
Phase 1: Thread Bridge (Steps 1A → 1E)
  1. Create rlm_adk/repl/thread_bridge.py (standalone, no integration)
  2. Add execute_code_threaded() to local_repl.py (standalone, no callers yet)
  3. Add _use_thread_bridge to REPLTool.__init__()
  4. Modify REPLTool.run_async() to use thread bridge
  5. Modify orchestrator wiring to create sync bridge closures
  5.5. Add builtins safety net (llm_query in builtins for ad-hoc code) + finally cleanup
  6. Run full test suite → verify no regression
  7. Write test_thread_bridge.py

Phase 2: Skill Infrastructure (Steps 2A → 2F)
  8. Create recursive-ping skill directory + SKILL.md + __init__.py + ping.py
  9. Create rlm_adk/skills/loader.py
 10. Wire skill globals injection in orchestrator
 11. Update skills/__init__.py docstring
 12. Write test_skill_loader.py

Phase 3: SkillToolset (Steps 3A → 3C)
 13. Wire SkillToolset creation in orchestrator
 14. Run full test suite

Phase 3.5: CRITICAL — Fix reasoning_before_model
 15. Fix system_instruction overwrite in callbacks/reasoning.py
 16. Verify SkillToolset L1 XML survives through to model prompt

Phase 4: Observability (Steps 4A → 4H)
 17. Rename state key to REPL_SKILL_GLOBALS_INJECTED, add to CURATED_STATE_PREFIXES (NOT DEPTH_SCOPED_KEYS)
 18. Expand LineageEnvelope.decision_mode Literal
 19. Add skill tool branches in sqlite_tracing after_tool_callback
 20. Type-narrow REPLTrace.execution_mode, add skill_globals_count + skill_expansion_occurred to LAST_REPL_RESULT
 21. Pass enabled_skills to create_child_orchestrator; split gating (SkillToolset gated, REPL globals unconditional)
 22. Add instruction disambiguation to static prompt (explicit run_skill_script != execute_code)
 23. Add additional_tools future-extension comment in orchestrator SkillToolset wiring
 24. File follow-up: _agent_span_stack per-invocation scoping

Phase 5: Testing (Steps 5A → 5D)
 25. Write test_thread_bridge.py
 26. Write test_skill_loader.py
 27. Write test_skill_thread_bridge_e2e.py + fixture (see companion spec: Thread_bridge_plan_B_e2e_test_design_rec.md)
 28. Run both modes (thread bridge + fallback)
```

---

## Critical Files Reference

| File | Lines | What's There Now |
|---|---|---|
| `rlm_adk/repl/thread_bridge.py` | N/A | **NEW** |
| `rlm_adk/repl/local_repl.py:77` | `_EXEC_LOCK` | Must NOT use in threaded path |
| `rlm_adk/repl/local_repl.py:211-223` | `set_llm_query_fns`, `set_async_llm_query_fns` | Sync receives real bridge; async kept for fallback |
| `rlm_adk/repl/local_repl.py:328-367` | `execute_code()` | Existing sync path (uses `_EXEC_LOCK`) — kept for fallback |
| `rlm_adk/repl/local_repl.py:385-481` | `execute_code_async()` | Existing async path — kept for fallback |
| `rlm_adk/repl/local_repl.py:369-383` | `_make_cwd_open()` | **REUSE** in `_execute_code_threadsafe` |
| `rlm_adk/repl/ast_rewriter.py:15-36` | `has_llm_calls()` | Still called for observability metadata |
| `rlm_adk/repl/ast_rewriter.py:161-228` | `rewrite_for_async()` | Only used in fallback path |
| `rlm_adk/tools/repl_tool.py:58-94` | `REPLTool.__init__()` | Add `use_thread_bridge` param |
| `rlm_adk/tools/repl_tool.py:222-243` | Bifurcated execution | Replace with thread bridge default |
| `rlm_adk/orchestrator.py:274-277` | `create_dispatch_closures()` call | Unchanged |
| `rlm_adk/orchestrator.py:288-297` | Sync stub + async wiring | Replace stub with real bridge |
| `rlm_adk/orchestrator.py:259` | `repl.globals["LLMResult"]` | Add skill globals injection after |
| `rlm_adk/orchestrator.py:331-332` | `tools = [repl_tool, set_model_response_tool]` | Add SkillToolset |
| `rlm_adk/callbacks/reasoning.py:144-146` | `system_instruction = ...` | **CRITICAL FIX** — append, don't replace |
| `rlm_adk/plugins/sqlite_tracing.py:1291-1303` | `after_tool_callback` decision_mode | Add `load_skill` / `load_skill_resource` branches |
| `rlm_adk/types.py:273-278` | `LineageEnvelope.decision_mode` | Add `list_skills`, `run_skill_script` |
| `rlm_adk/repl/trace.py:32` | `REPLTrace.execution_mode` | Type-narrow to Literal |
| `rlm_adk/utils/prompts.py:16-82` | `RLM_STATIC_INSTRUCTION` | Add skill tool disambiguation |
| `rlm_adk/dispatch.py` | `_run_child` | Pass `enabled_skills` to child orchestrator |
| `rlm_adk/agent.py:330-386` | `create_child_orchestrator` | Add `enabled_skills` parameter |
| `rlm_adk/skills/loader.py` | N/A | **NEW** |
| `rlm_adk/skills/__init__.py` | 7 lines | Update docstring |
| `rlm_adk/plugins/sqlite_tracing.py:296-306` | `_agent_span_stack`, `_pending_*` dicts | Follow-up: scope per invocation_id |

---

## Verification

1. **Thread bridge works**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q`
2. **Fallback works**: `RLM_REPL_THREAD_BRIDGE=0 .venv/bin/python -m pytest tests_rlm_adk/ -x -q`
3. **Module-imported skill**: `test_skill_thread_bridge_e2e.py` — skill function calls `llm_query()` from imported module
4. **No deadlock**: Test with depth>1 recursive dispatch
5. **Skill discovery**: `test_skill_loader.py` — dirs discovered, REPL globals injected, `llm_query_fn` auto-injected
6. **SkillToolset**: Verify `load_skill` returns L2 instructions
7. **Dashboard**: Restart server, verify "Skills in Prompt" populates with registered skills
