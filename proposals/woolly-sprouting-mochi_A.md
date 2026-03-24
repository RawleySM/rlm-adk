# Thread Bridge + ADK SkillToolset Integration

## Context

RLM-ADK's skill system has been fully gutted after several false starts. The vision is unchanged: skills are typed Python functions callable via `execute_code` that accumulate over time. The blocker was that module-imported functions calling `llm_query()` fail because the AST rewriter only transforms the submitted code string. This plan replaces the AST-rewriting execution model with a thread-bridge that makes `llm_query()` a real sync callable, then wires ADK's upstream `SkillToolset` for L1/L2 discovery.

**ADK callback compatibility confirmed**: ADK already runs tools in thread pools, state mutations are GIL-protected plain dicts, callbacks run sequentially in the event loop thread after tool completion.

---

## Phase 1: Thread Bridge — Make `llm_query()` a Real Sync Callable

### 1A. New module: `rlm_adk/repl/thread_bridge.py`

Two factory functions that create sync wrappers around the existing async dispatch closures:

```python
def make_sync_llm_query(llm_query_async, loop, timeout=600.0):
    def llm_query(prompt, model=None, output_schema=None):
        coro = llm_query_async(prompt, model=model, output_schema=output_schema)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    return llm_query

def make_sync_llm_query_batched(llm_query_batched_async, loop, timeout=600.0):
    # Same pattern for batched
```

- `loop` captured at wiring time in orchestrator `_run_async_impl` via `asyncio.get_running_loop()`
- `future.result()` blocks the worker thread, not the event loop

### 1B. New method: `LocalREPL.execute_code_threaded()` (`rlm_adk/repl/local_repl.py`)

**CRITICAL**: Must NOT use `_EXEC_LOCK` or `os.chdir()`. These are process-global — using them would deadlock when a parent REPL holds the lock and a child REPL (spawned via `llm_query()` → event loop → child orchestrator → executor thread) tries to acquire it.

Instead, follows the same CWD-safe pattern as `execute_code_async()`: inject `_make_cwd_open()` into namespace + set `_repl_cwd`.

```python
async def execute_code_threaded(self, code, trace=None):
    """Execute code in a dedicated worker thread. llm_query() bridges to event loop."""
    start_time = time.perf_counter()
    self._pending_llm_calls.clear()
    loop = asyncio.get_running_loop()

    # One-shot executor avoids default pool exhaustion under recursive dispatch
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        stdout, stderr, success = await asyncio.wait_for(
            loop.run_in_executor(executor, self._execute_code_threadsafe, code, trace),
            timeout=self.sync_timeout,
        )
    except asyncio.TimeoutError:
        stdout, stderr, success = "", f"TimeoutError: exceeded {self.sync_timeout}s", False
    finally:
        executor.shutdown(wait=False)

    return REPLResult(stdout=stdout, stderr=stderr, locals=self.locals.copy(),
                      execution_time=time.perf_counter() - start_time,
                      llm_calls=self._pending_llm_calls.copy(),
                      trace=trace.to_dict() if trace else None)
```

New `_execute_code_threadsafe()` inner method (NO `_EXEC_LOCK`, NO `os.chdir`):
- Inject `_make_cwd_open()` as `open` in namespace (CWD-safe file access)
- Inject `_repl_cwd = self.temp_dir` for explicit CWD access
- Call `self._executor.execute_sync(code, combined)` directly
- Update `self.locals` on success
- Capture stdout/stderr via thread-local buffers or direct StringIO

**One-shot executor**: Each call creates `ThreadPoolExecutor(max_workers=1)`. This prevents deadlock from default-pool exhaustion under recursive dispatch (parent T1 blocked, child T2, grandchild T3 all need threads).

### 1C. Modify `REPLTool.run_async()` (`rlm_adk/tools/repl_tool.py`, lines 222-243)

Replace the two-path branch with thread bridge as default:

```python
# New: thread bridge path (default)
if self._use_thread_bridge:
    llm_calls_made = has_llm_calls(exec_code)  # observability only, not flow control
    result = await self.repl.execute_code_threaded(exec_code, trace=trace)
else:
    # Legacy fallback: AST rewriter path (RLM_REPL_THREAD_BRIDGE=0)
    if has_llm_calls(exec_code):
        llm_calls_made = True
        tree = rewrite_for_async(exec_code)
        compiled = compile(tree, "<repl>", "exec")
        result = await self.repl.execute_code_async(code, trace=trace, compiled=compiled)
    else:
        result = self.repl.execute_code(exec_code, trace=trace)
```

- Add `_use_thread_bridge` flag to `__init__`, default `True`, env override `RLM_REPL_THREAD_BRIDGE=0`
- `has_llm_calls()` still called for `llm_calls_made` return field (observability)
- AST rewriter retained as fallback, not deleted

### 1D. Modify orchestrator wiring (`rlm_adk/orchestrator.py`, lines 288-297)

Replace sync stub with real sync bridge:

```python
from rlm_adk.repl.thread_bridge import make_sync_llm_query, make_sync_llm_query_batched

_loop = asyncio.get_running_loop()
repl.set_llm_query_fns(
    make_sync_llm_query(llm_query_async, _loop),
    make_sync_llm_query_batched(llm_query_batched_async, _loop),
)
repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)  # keep for fallback
```

### 1E. Files changed

| File | Change |
|---|---|
| `rlm_adk/repl/thread_bridge.py` | **NEW** — `make_sync_llm_query()`, `make_sync_llm_query_batched()` |
| `rlm_adk/repl/local_repl.py` | **ADD** `execute_code_threaded()` + `_execute_code_threadsafe()` |
| `rlm_adk/tools/repl_tool.py` | **MODIFY** execution dispatch (lines 222-243), add `_use_thread_bridge` flag |
| `rlm_adk/orchestrator.py` | **MODIFY** sync wiring (lines 288-297) |
| `rlm_adk/repl/ast_rewriter.py` | **NO CHANGE** — retained as fallback |
| `rlm_adk/dispatch.py` | **NO CHANGE** — async closures work unchanged |

---

## Phase 2: Skill Directory Convention + Module Loading

### 2A. Skill directory structure

Each skill lives under `rlm_adk/skills/<skill-name>/`:

```
rlm_adk/skills/
    <skill-name>/
        SKILL.md           # ADK frontmatter (kebab-case name) + L2 I/O contract docs
        __init__.py        # Exports: from .impl import skill_fn
        impl.py            # Typed Python function(s), may call llm_query()
        references/        # Optional: additional docs for load_skill_resource
```

- Directory name = kebab-case (ADK `load_skill_from_dir` validates name matches dir)
- Python module imported via underscore-converted path: `rlm_adk.skills.skill_name`
- Skill functions call `llm_query()` as a global — it's in repl.globals, thread bridge handles dispatch

### 2B. New module: `rlm_adk/skills/loader.py`

```python
def discover_skill_dirs(enabled_skills=None) -> list[Path]:
    """Find dirs under rlm_adk/skills/ with SKILL.md, filtered by enabled_skills."""

def load_adk_skills(enabled_skills=None) -> list[Skill]:
    """Load ADK Skill objects via load_skill_from_dir for SkillToolset."""

def collect_skill_repl_globals(enabled_skills=None) -> dict[str, Any]:
    """Import skill Python modules, collect public callables for repl.globals."""
```

- `discover_skill_dirs` skips `obsolete/`, `__pycache__`, dotfiles
- `load_adk_skills` calls `google.adk.skills.load_skill_from_dir()` per discovered dir
- `collect_skill_repl_globals` dynamically imports the Python module (kebab→underscore), collects `__all__` or public callables

### 2C. Wire skill globals into REPL (`rlm_adk/orchestrator.py`)

After `repl.globals["LLMResult"] = LLMResult` (line 259), inject skill functions:

```python
from rlm_adk.skills.loader import collect_skill_repl_globals
skill_globals = collect_skill_repl_globals(enabled_skills=self.enabled_skills or None)
repl.globals.update(skill_globals)
```

### 2D. Files changed

| File | Change |
|---|---|
| `rlm_adk/skills/loader.py` | **NEW** — discovery, ADK loading, REPL globals collection |
| `rlm_adk/skills/__init__.py` | **MODIFY** — update docstring |
| `rlm_adk/orchestrator.py` | **MODIFY** — inject skill globals after REPL creation |

---

## Phase 3: Wire ADK SkillToolset for L1/L2 Discovery

### 3A. Create SkillToolset and wire onto reasoning_agent (`rlm_adk/orchestrator.py`)

After creating `repl_tool` and `set_model_response_tool` (line ~329):

```python
from google.adk.tools.skill_toolset import SkillToolset
from rlm_adk.skills.loader import load_adk_skills

adk_skills = load_adk_skills(enabled_skills=self.enabled_skills or None)
tools = [repl_tool, set_model_response_tool]
if adk_skills:
    tools.append(SkillToolset(skills=adk_skills))

object.__setattr__(self.reasoning_agent, "tools", tools)
```

ADK's `_process_agent_tools` (in `base_llm_flow.py`) handles the rest:
1. Calls `SkillToolset.process_llm_request()` → injects L1 XML into system instruction
2. Extracts individual tools via `get_tools()` → `list_skills`, `load_skill`, `load_skill_resource`, `run_skill_script`
3. Model can call `load_skill(name="example-analyzer")` to see full I/O contract

### 3B. Keep `instruction_router` orthogonal

`instruction_router` continues to inject per-depth/fanout instructions via `DYN_SKILL_INSTRUCTION`. `SkillToolset` operates at the tool level (model discovers and loads). They coexist.

### 3C. `enabled_skills` now consumed

The currently-inert `enabled_skills` tuple on `RLMOrchestratorAgent` (line 237) is now consumed by:
- `collect_skill_repl_globals(enabled_skills=...)` → filters REPL injections
- `load_adk_skills(enabled_skills=...)` → filters SkillToolset skills

### 3D. Files changed

| File | Change |
|---|---|
| `rlm_adk/orchestrator.py` | **MODIFY** — create SkillToolset, add to tools list |

---

## Phase 4: Observability

### 4A. State keys (`rlm_adk/state.py`)

Add:
```python
SKILL_REPL_GLOBALS_INJECTED = "skill_repl_globals_injected"  # list of function names
```

### 4B. Execution mode tracking

In `REPLTool.run_async()` return dict, add `"execution_mode": "thread_bridge"` (or `"async_rewrite"` / `"sync"` for fallback). Also in `LAST_REPL_RESULT` summary.

### 4C. SqliteTracingPlugin compatibility

No changes needed — `SkillToolset` tools are regular ADK tools, captured by existing `before_tool_callback` / `after_tool_callback`. The `skill_instruction` and `skill_name_loaded` telemetry columns already exist.

---

## Phase 5: Testing

### 5A. Unit tests

| Test | Validates |
|---|---|
| `test_thread_bridge.py` | `make_sync_llm_query` dispatches from worker thread via `run_coroutine_threadsafe`; timeout; error propagation |
| `test_skill_loader.py` | `discover_skill_dirs`, `load_adk_skills`, `collect_skill_repl_globals` with mock skill dirs |
| `test_repl_threaded.py` | `execute_code_threaded` runs code in thread; sync `llm_query()` works from imported function; no deadlock with recursive dispatch |

### 5B. Integration tests

- All existing provider-fake fixtures pass unchanged (thread bridge is backward compatible)
- New fixture: skill function that internally calls `llm_query()` via module import (the previously-impossible case)

### 5C. Regression safeguard

`RLM_REPL_THREAD_BRIDGE=0` env var falls back to AST rewriter path — existing tests can run in both modes.

---

## Critical Design Details

### Deadlock Prevention

`_EXEC_LOCK` is a **module-level** `threading.Lock()` in `local_repl.py:77`. If `execute_code_threaded()` naively used `_execute_code_inner()` (which acquires `_EXEC_LOCK`), recursive dispatch would deadlock:

```
T1 (parent worker): holds _EXEC_LOCK → calls llm_query() → blocks on future.result()
T0 (event loop): runs child dispatch → child orchestrator → child REPLTool
T2 (child worker): execute_code_threaded → _execute_code_inner → tries _EXEC_LOCK → DEADLOCK
```

**Fix**: `_execute_code_threadsafe()` does NOT use `_EXEC_LOCK` or `os.chdir()`. Uses `_make_cwd_open()` pattern (already exists at line 369) for CWD-safe file access.

### Thread Pool Exhaustion Prevention

Each `execute_code_threaded()` creates a one-shot `ThreadPoolExecutor(max_workers=1)`. This prevents exhaustion of the default executor under recursive dispatch (parent, child, grandchild all need threads simultaneously).

### `_pending_llm_calls` Thread Safety

No race: dispatch closures append to `call_log_sink` on the event loop thread while the worker thread is blocked on `future.result()`. The list is only read after the entire code block completes.

---

## Execution Flow (New Model)

```
Model calls execute_code("result = analyze_document(text)")
  │
  ├─ REPLTool.run_async() [event loop thread T0]
  │   ├─ expand_skill_imports(code)
  │   ├─ has_llm_calls(code)  → observability metadata only
  │   └─ await repl.execute_code_threaded(code)
  │       └─ await loop.run_in_executor(one_shot_executor, _execute_code_threadsafe, code)
  │           │
  │           └─ [worker thread T1]
  │               ├─ inject _make_cwd_open(), _repl_cwd into namespace
  │               ├─ exec(code, namespace)
  │               │   └─ analyze_document(text) called (module-imported function)
  │               │       └─ llm_query("Summarize: ...") — REAL sync function
  │               │           └─ run_coroutine_threadsafe(llm_query_async(...), loop)
  │               │               │
  │               │               └─ [event loop T0, free because T1 yielded via run_in_executor]
  │               │                   └─ child orchestrator runs → child events → LLMResult
  │               │               │
  │               │           └─ future.result() → LLMResult returned
  │               │       └─ dict returned
  │               ├─ update self.locals
  │               └─ return (stdout, stderr, success)
  │
  ├─ post_dispatch_state_patch_fn()
  ├─ write LAST_REPL_RESULT to tool_context.state
  └─ return result dict
```

---

## File Change Summary

| File | Type | Description |
|---|---|---|
| `rlm_adk/repl/thread_bridge.py` | NEW | `make_sync_llm_query()`, `make_sync_llm_query_batched()` |
| `rlm_adk/repl/local_repl.py` | MODIFY | Add `execute_code_threaded()`, `_execute_code_threadsafe()` |
| `rlm_adk/tools/repl_tool.py` | MODIFY | Thread bridge execution path, `_use_thread_bridge` flag |
| `rlm_adk/orchestrator.py` | MODIFY | Wire sync llm_query bridge; inject skill globals; create SkillToolset |
| `rlm_adk/skills/loader.py` | NEW | Skill directory discovery, ADK loading, REPL globals collection |
| `rlm_adk/skills/__init__.py` | MODIFY | Update docstring |
| `rlm_adk/state.py` | MODIFY | Add `SKILL_REPL_GLOBALS_INJECTED` key |
| `rlm_adk/repl/ast_rewriter.py` | NO CHANGE | Retained as fallback |
| `rlm_adk/repl/skill_registry.py` | NO CHANGE | Source expansion coexists |
| `rlm_adk/dispatch.py` | NO CHANGE | Async closures work unchanged |
| `rlm_adk/agent.py` | NO CHANGE | `enabled_skills` already flows through |

---

## Verification

1. **Thread bridge**: Run existing provider-fake suite: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q`
2. **Fallback**: `RLM_REPL_THREAD_BRIDGE=0 .venv/bin/python -m pytest tests_rlm_adk/ -x -q`
3. **Module-imported skill**: New test with skill function calling `llm_query()` from an imported module
4. **Recursive dispatch**: Test with depth>1 dispatch to verify no deadlock
5. **SkillToolset**: Test that `load_skill` returns L2 instructions, then `execute_code` calls the skill function
6. **Dashboard**: Restart dashboard, verify "Skills in Prompt" section populates when skills exist
