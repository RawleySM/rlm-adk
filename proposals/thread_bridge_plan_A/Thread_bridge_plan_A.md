## Implementation Plan: Thread Bridge + ADK SkillToolset Integration

### Architecture Overview

**Current state**: REPL code execution has two paths in `REPLTool.run_async()` (lines 222-243 of `rlm_adk/tools/repl_tool.py`):
- Path A (sync): Code without `llm_query` calls runs via `LocalREPL.execute_code()` which uses `ThreadPoolExecutor` with `_EXEC_LOCK`
- Path B (async): Code with `llm_query` calls is AST-rewritten to async, compiled, and run via `LocalREPL.execute_code_async()` in the event loop thread

**Problem**: Module-imported skill functions that internally call `llm_query()` fail because the AST rewriter only transforms the submitted code string, not imported module bytecode. The sync `llm_query` in `repl.globals` is a stub that raises `RuntimeError` (orchestrator.py line 291-296).

**Target state**: One execution path. ALL REPL code runs in a worker thread via `loop.run_in_executor()`. `llm_query()` is a real sync function that uses `asyncio.run_coroutine_threadsafe()` to dispatch child orchestrators from the worker thread back to the event loop, then blocks on `future.result()`.

---

### Phase 1: Thread Bridge -- Make `llm_query()` a Real Sync Function

**Goal**: Replace the AST rewriter execution path with a universal thread-bridge model.

#### 1A. New module: `rlm_adk/repl/thread_bridge.py`

Create a module that provides the sync-callable `llm_query` and `llm_query_batched` functions. These capture the event loop reference and use `asyncio.run_coroutine_threadsafe()` to dispatch from a worker thread back to the async event loop.

```python
# rlm_adk/repl/thread_bridge.py

def make_sync_llm_query(
    llm_query_async: Callable,
    loop: asyncio.AbstractEventLoop,
    timeout: float = 600.0,
) -> Callable:
    """Create a sync llm_query that bridges to async dispatch via the event loop.
    
    Safe to call from a worker thread. Uses run_coroutine_threadsafe to
    schedule the async coroutine on the event loop, then blocks on the
    future.result().
    """
    def llm_query(
        prompt: str,
        model: str | None = None,
        output_schema: type | None = None,
    ) -> "LLMResult":
        coro = llm_query_async(prompt, model=model, output_schema=output_schema)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    return llm_query


def make_sync_llm_query_batched(
    llm_query_batched_async: Callable,
    loop: asyncio.AbstractEventLoop,
    timeout: float = 600.0,
) -> Callable:
    """Create a sync llm_query_batched that bridges to async dispatch."""
    def llm_query_batched(
        prompts: list[str],
        model: str | None = None,
        output_schema: type | None = None,
    ) -> list["LLMResult"]:
        coro = llm_query_batched_async(prompts, model=model, output_schema=output_schema)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    return llm_query_batched
```

**Key design decisions**:
- `loop` is captured at wiring time (in orchestrator `_run_async_impl`), guaranteeing it is the running event loop
- `timeout` is configurable (default 600s = 10 min), prevents infinite hangs
- The `future.result()` call blocks the worker thread, not the event loop
- `run_coroutine_threadsafe` is thread-safe by definition

**Thread safety analysis**:
- `tool_context.state[key] = value` writes to plain dicts, protected by GIL -- confirmed safe
- `dispatch.py` closures are pure-async and run on the event loop thread when scheduled via `run_coroutine_threadsafe`
- `_EXEC_LOCK` in `LocalREPL._execute_code_inner()` serializes process-global state (os.chdir), preventing CWD races between concurrent threads
- ADK callbacks run sequentially in the event loop thread AFTER tool completes
- Session persistence uses `asyncio.Lock` -- no thread-local state

#### 1B. Modify `LocalREPL` (`rlm_adk/repl/local_repl.py`)

Add a new method `execute_code_threaded()` that runs code in a worker thread via `loop.run_in_executor()`:

```python
async def execute_code_threaded(
    self,
    code: str,
    trace: REPLTrace | None = None,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> REPLResult:
    """Execute code in a worker thread, allowing sync llm_query() calls.
    
    Uses loop.run_in_executor() to run _execute_code_inner() in a thread.
    The sync llm_query() functions in self.globals use 
    run_coroutine_threadsafe() to dispatch back to this event loop.
    """
    _loop = loop or asyncio.get_running_loop()
    start_time = time.perf_counter()
    self._pending_llm_calls.clear()
    
    # Run the existing _execute_code_inner in the default executor (thread pool)
    stdout, stderr, success = await _loop.run_in_executor(
        None,  # default ThreadPoolExecutor
        self._execute_code_inner,
        code,
        trace,
    )
    
    return REPLResult(
        stdout=stdout,
        stderr=stderr,
        locals=self.locals.copy(),
        execution_time=time.perf_counter() - start_time,
        llm_calls=self._pending_llm_calls.copy(),
        trace=trace.to_dict() if trace else None,
    )
```

**Key insight**: `_execute_code_inner()` already acquires `_EXEC_LOCK`, handles `os.chdir()`, captures stdout/stderr, and updates `self.locals`. It is already designed for thread execution. The only change is we now run it via `loop.run_in_executor()` instead of the existing `ThreadPoolExecutor` in `execute_code()`.

**Timeout handling**: The current `execute_code()` uses `future.result(timeout=self.sync_timeout)` with a ThreadPoolExecutor. For `execute_code_threaded()`, timeout should be handled by wrapping `run_in_executor` with `asyncio.wait_for()`:

```python
try:
    stdout, stderr, success = await asyncio.wait_for(
        _loop.run_in_executor(None, self._execute_code_inner, code, trace),
        timeout=self.sync_timeout,
    )
except asyncio.TimeoutError:
    # Same handling as current execute_code timeout path
    ...
```

#### 1C. Modify `REPLTool.run_async()` (`rlm_adk/tools/repl_tool.py`)

**Change the execution dispatch** (lines 222-243). Replace the two-path branching:

```python
# BEFORE (current):
if has_llm_calls(exec_code):
    llm_calls_made = True
    tree = rewrite_for_async(exec_code)
    compiled = compile(tree, "<repl>", "exec")
    result = await self.repl.execute_code_async(code, trace=trace, compiled=compiled)
else:
    result = self.repl.execute_code(exec_code, trace=trace)

# AFTER (thread bridge):
use_thread_bridge = self._use_thread_bridge  # New bool flag, default True
if use_thread_bridge:
    llm_calls_made = has_llm_calls(exec_code)  # Keep for observability only
    result = await self.repl.execute_code_threaded(exec_code, trace=trace)
else:
    # Fallback: legacy AST rewriter path (retained but not default)
    if has_llm_calls(exec_code):
        llm_calls_made = True
        tree = rewrite_for_async(exec_code)
        compiled = compile(tree, "<repl>", "exec")
        result = await self.repl.execute_code_async(code, trace=trace, compiled=compiled)
    else:
        result = self.repl.execute_code(exec_code, trace=trace)
```

Add `_use_thread_bridge: bool = True` to `REPLTool.__init__()`.

Add env var override: `_use_thread_bridge = os.getenv("RLM_REPL_THREAD_BRIDGE", "1") != "0"`.

`has_llm_calls()` is still called for observability metadata (`llm_calls_made` in the return dict) but no longer controls the execution path.

#### 1D. Modify Orchestrator wiring (`rlm_adk/orchestrator.py`, lines 252-297)

Replace the current dual-wiring (async + sync stub) with the thread bridge:

```python
# BEFORE:
repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)

def sync_llm_query_unsupported(*args, **kwargs):
    raise RuntimeError(...)

repl.set_llm_query_fns(sync_llm_query_unsupported, sync_llm_query_unsupported)

# AFTER:
from rlm_adk.repl.thread_bridge import make_sync_llm_query, make_sync_llm_query_batched

_loop = asyncio.get_running_loop()

sync_llm_query = make_sync_llm_query(llm_query_async, _loop)
sync_llm_query_batched = make_sync_llm_query_batched(llm_query_batched_async, _loop)

repl.set_llm_query_fns(sync_llm_query, sync_llm_query_batched)
# Keep async fns for backward compat / fallback path
repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)
```

**Critical**: The `_loop` must be captured inside `_run_async_impl()`, where the event loop is guaranteed to be running. `asyncio.get_running_loop()` is the correct call.

#### 1E. Preserve existing mechanisms

- **AST rewriter** (`rlm_adk/repl/ast_rewriter.py`): NOT deleted. Retained as fallback, toggled by `RLM_REPL_THREAD_BRIDGE=0` env var.
- **Source expansion** (`rlm_adk/repl/skill_registry.py`): Still called in `REPLTool.run_async()` line 177. The `expand_skill_imports()` call remains before execution regardless of path. Source expansion is orthogonal to the execution model -- it just textually inlines code before execution.
- **`execute_code_async()`**: Kept for fallback path.
- **`execute_code()`**: Kept for non-LLM sync code in fallback path.
- **`_pending_llm_calls`**: The `call_log_sink` passed to `create_dispatch_closures()` still references `repl._pending_llm_calls`. Since dispatch closures run on the event loop thread via `run_coroutine_threadsafe`, and the worker thread blocks on `future.result()`, there is no concurrent mutation -- the append to `call_log_sink` in `_build_call_log` completes before the worker thread resumes.

#### 1F. Test plan for Phase 1

1. **Unit test**: `test_thread_bridge.py` -- Create mock async llm_query, create event loop, verify sync wrapper dispatches and returns correctly from a worker thread.
2. **Integration test**: Existing provider-fake fixtures (`fake_recursive_ping.json`, `multi_iteration_with_workers.json`, etc.) must pass with `RLM_REPL_THREAD_BRIDGE=1`.
3. **Fallback test**: Same fixtures must pass with `RLM_REPL_THREAD_BRIDGE=0`.
4. **Module-imported skill test**: New fixture where REPL code does `from some_skill_module import analyze; result = analyze(data)` where `analyze()` internally calls `llm_query()`. This is the previously-impossible case that the thread bridge enables.

---

### Phase 2: Skill Directory Convention and Module Loading

**Goal**: Establish the convention for skill directories that contain both SKILL.md (for ADK discovery) and Python modules (for REPL import).

#### 2A. Skill directory structure

Each skill lives under `rlm_adk/skills/<skill-name>/`:

```
rlm_adk/skills/
  example-analyzer/
    SKILL.md           # ADK frontmatter + L2 instructions
    __init__.py        # Exports skill functions
    analyzer.py        # Python module with typed functions
    references/        # Optional: additional docs
    assets/            # Optional: templates, schemas
    scripts/           # Optional: executable scripts
```

SKILL.md format (ADK-compatible):
```yaml
---
name: example-analyzer
description: Analyzes documents using recursive LLM decomposition
metadata:
  io_schema:
    input: "str (document text)"
    output: "dict with 'summary' and 'themes' keys"
  uses_llm_query: true
---

## Example Analyzer

Call `analyze_document(text)` in the REPL to use this skill.
The function accepts a document string and returns a structured analysis.

### I/O Contract
- **Input**: `text: str` -- document content
- **Output**: `dict` with keys `summary` (str) and `themes` (list[str])
```

The Python module:
```python
# rlm_adk/skills/example-analyzer/analyzer.py

def analyze_document(text: str) -> dict:
    """Analyze a document using recursive LLM decomposition."""
    # llm_query is available in REPL globals -- injected by orchestrator
    summary = llm_query(f"Summarize this document:\n{text[:50000]}")
    themes = llm_query(f"List the key themes in:\n{text[:50000]}")
    return {"summary": str(summary), "themes": str(themes)}
```

**Key design**: The skill function calls `llm_query()` as a global. It does NOT import it. When the function runs inside the REPL, `llm_query` is already in the REPL globals namespace. The thread bridge ensures this works even though `llm_query()` was not in the submitted code string.

#### 2B. Skill auto-loader: `rlm_adk/skills/loader.py`

New module that scans the skills directory, loads SKILL.md metadata, and prepares modules for REPL injection:

```python
# rlm_adk/skills/loader.py

from pathlib import Path
from google.adk.skills import load_skill_from_dir, Skill

_SKILLS_ROOT = Path(__file__).parent

def discover_skill_dirs(
    enabled_skills: tuple[str, ...] | None = None,
) -> list[Path]:
    """Find valid skill directories under rlm_adk/skills/."""
    dirs = []
    for child in sorted(_SKILLS_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        if child.name == "obsolete":
            continue
        if (child / "SKILL.md").exists():
            if enabled_skills is None or child.name in enabled_skills:
                dirs.append(child)
    return dirs

def load_adk_skills(
    enabled_skills: tuple[str, ...] | None = None,
) -> list[Skill]:
    """Load ADK Skill objects from discovered directories."""
    skills = []
    for skill_dir in discover_skill_dirs(enabled_skills):
        try:
            skill = load_skill_from_dir(skill_dir)
            skills.append(skill)
        except (FileNotFoundError, ValueError) as e:
            logger.warning("Skipping skill %s: %s", skill_dir.name, e)
    return skills

def collect_skill_repl_globals(
    enabled_skills: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Import and collect all skill functions for REPL injection.
    
    Returns a dict of {function_name: callable} for injection into
    repl.globals.
    """
    globals_dict = {}
    for skill_dir in discover_skill_dirs(enabled_skills):
        init_path = skill_dir / "__init__.py"
        if not init_path.exists():
            continue
        # Import the skill module dynamically
        module_name = f"rlm_adk.skills.{skill_dir.name.replace('-', '_')}"
        try:
            mod = importlib.import_module(module_name)
            # Collect all public callables from __all__ or non-underscore names
            exports = getattr(mod, "__all__", None)
            if exports is None:
                exports = [n for n in dir(mod) if not n.startswith("_") and callable(getattr(mod, n))]
            for name in exports:
                obj = getattr(mod, name)
                if callable(obj):
                    globals_dict[name] = obj
        except ImportError as e:
            logger.warning("Failed to import skill module %s: %s", module_name, e)
    return globals_dict
```

**Note on kebab-case**: ADK skill names are kebab-case (`example-analyzer`). Python module names must be valid identifiers. The convention is: directory name is kebab-case (for ADK `load_skill_from_dir` compatibility), but the Python package uses underscore conversion: `rlm_adk.skills.example_analyzer`. The `__init__.py` in each skill dir handles the module import.

However, since Python does not allow hyphens in import paths, skill directories that contain Python modules should use underscore naming. This means the `name` field in SKILL.md frontmatter should also use underscores (or we add a `module_name` metadata field). **Simpler approach**: Use underscore names for skills that have Python modules. The ADK `Frontmatter` validator requires kebab-case (`_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")`). 

**Resolution**: Two options:
1. Override the ADK validator by constructing `Frontmatter` directly (not via `load_skill_from_dir`)
2. Use kebab-case for directory names and add a `_resolve_module_name` that converts hyphens to underscores, placing `__init__.py` under a symlinked or re-exported underscore name

**Recommended**: Option 2 is fragile. Option 1 is simpler -- construct `Skill` objects programmatically for skills with Python modules, only using `load_skill_from_dir` for pure-SKILL.md skills. OR: modify `discover_skill_dirs` to handle both, with the Python module path derived by replacing hyphens with underscores in `importlib.import_module()`.

#### 2C. Wire skill globals into REPL (`rlm_adk/orchestrator.py`)

In `_run_async_impl()`, after creating the REPL and before wiring tools:

```python
# After: repl.globals["LLMResult"] = LLMResult

from rlm_adk.skills.loader import collect_skill_repl_globals

skill_globals = collect_skill_repl_globals(
    enabled_skills=self.enabled_skills or None,
)
repl.globals.update(skill_globals)
```

This injects all skill functions into the REPL namespace so they can be called directly from `execute_code` submissions.

---

### Phase 3: Wire ADK SkillToolset for L1/L2 Discovery

**Goal**: Use ADK's upstream `SkillToolset` so the reasoning agent can discover skills via L1 XML and load detailed instructions via L2 `load_skill`.

#### 3A. Create `SkillToolset` and wire onto reasoning agent

In `rlm_adk/orchestrator.py`, after creating `repl_tool` and `set_model_response_tool`:

```python
from google.adk.tools.skill_toolset import SkillToolset
from rlm_adk.skills.loader import load_adk_skills

# Load ADK Skill objects for SkillToolset
adk_skills = load_adk_skills(
    enabled_skills=self.enabled_skills or None,
)

if adk_skills:
    skill_toolset = SkillToolset(
        skills=adk_skills,
        # No code_executor needed -- our REPL handles execution
    )
    tools = [repl_tool, set_model_response_tool, skill_toolset]
else:
    tools = [repl_tool, set_model_response_tool]
```

**How this works with ADK's tool loop**:

Looking at `base_llm_flow.py` lines 417-444 (`_process_agent_tools`):
1. For each `tool_union` in `agent.tools`:
   - If it's a `BaseToolset`, call `tool_union.process_llm_request()` first (injects L1 XML)
   - Then call `_convert_tool_union_to_tools()` to get individual `BaseTool` instances
   - Call `tool.process_llm_request()` on each resolved tool

So adding `SkillToolset` to the tools list automatically:
- Injects L1 XML (`<available_skills>` block) into every LLM request via `SkillToolset.process_llm_request()`
- Adds `list_skills`, `load_skill`, `load_skill_resource`, `run_skill_script` tools
- The model can call `load_skill(name="example-analyzer")` to get L2 instructions

**Critical consideration**: The `SkillToolset`'s default system instruction (`_DEFAULT_SKILL_SYSTEM_INSTRUCTION`) tells the model to use skill tools for interaction. This is additive -- it does not conflict with the existing `RLM_STATIC_INSTRUCTION` which tells the model about `execute_code` and `set_model_response`. The model will see both sets of tools and can choose appropriately.

#### 3B. Keep `instruction_router` orthogonal

The `instruction_router` mechanism (`DYN_SKILL_INSTRUCTION` in state, resolved by ADK's template engine in `RLM_DYNAMIC_INSTRUCTION` via `{skill_instruction?}`) remains unchanged. It is a separate mechanism that injects skill-specific context into the dynamic instruction based on depth/fanout. This is useful for routing specific skill instructions to child orchestrators.

`SkillToolset` operates at the tool level (model can discover and load skills). `instruction_router` operates at the instruction level (skills are pre-configured per depth/fanout). They serve different purposes and coexist cleanly.

#### 3C. `enabled_skills` filtering

The `enabled_skills` tuple on `RLMOrchestratorAgent` (line 237 of orchestrator.py) is currently stored but never consumed. After this change:

- `collect_skill_repl_globals(enabled_skills=...)` filters which skill functions are injected into the REPL
- `load_adk_skills(enabled_skills=...)` filters which skills appear in the `SkillToolset`
- When `enabled_skills` is empty/None, all discovered skills are loaded (default behavior)

---

### Phase 4: Observability and State Integration

#### 4A. New state keys (`rlm_adk/state.py`)

```python
# Skill Discovery Keys (session-scoped)
SKILL_LAST_LOADED = "skill_last_loaded"
SKILL_LOAD_COUNT = "skill_load_count"
SKILL_LOADED_NAMES = "skill_loaded_names"
SKILL_REPL_GLOBALS_INJECTED = "skill_repl_globals_injected"
```

These are written by the orchestrator when skill globals are injected, and by ADK's `LoadSkillTool` when the model loads a skill (via `tool_context.state`).

#### 4B. Thread bridge observability

Add to `REPLTool.run_async()` return dict:
```python
"execution_mode": "thread_bridge" if use_thread_bridge else ("async_rewrite" if llm_calls_made else "sync"),
```

Add to `LAST_REPL_RESULT` summary:
```python
last_repl["execution_mode"] = "thread_bridge"  # or "async_rewrite" / "sync"
```

#### 4C. SqliteTracingPlugin compatibility

The `sqlite_tracing` plugin reads `LAST_REPL_RESULT` from state and captures tool telemetry. No changes needed -- the `REPLTool` still writes the same state keys. The new `execution_mode` field is additive.

The `SkillToolset` tools (`load_skill`, `list_skills`, etc.) are regular ADK tools. `sqlite_tracing`'s `before_tool_callback` and `after_tool_callback` will capture them automatically.

---

### Phase 5: Testing Strategy

#### 5A. Unit tests

| Test file | What it validates |
|---|---|
| `test_thread_bridge.py` | `make_sync_llm_query` dispatches correctly from worker thread; timeout works; error propagation |
| `test_skill_loader.py` | `discover_skill_dirs`, `load_adk_skills`, `collect_skill_repl_globals` with mock skill directories |
| `test_repl_threaded.py` | `LocalREPL.execute_code_threaded()` runs code in thread; sync `llm_query()` works from inside executed code |

#### 5B. Integration tests (provider-fake)

- All existing provider-fake fixtures must pass unchanged (thread bridge is backward compatible)
- New fixture: `skill_function_dispatch.json` -- REPL code imports a skill function that internally calls `llm_query()`, verifying the thread bridge enables module-imported dispatch
- New fixture: `skill_toolset_discovery.json` -- Model calls `load_skill`, reads instructions, then uses `execute_code` with the skill function

#### 5C. Regression safeguards

- `RLM_REPL_THREAD_BRIDGE=0` env var falls back to AST rewriter path -- all existing tests run in both modes via parameterized fixture

---

### File Change Summary

| File | Change type | Description |
|---|---|---|
| `rlm_adk/repl/thread_bridge.py` | **NEW** | `make_sync_llm_query()`, `make_sync_llm_query_batched()` |
| `rlm_adk/repl/local_repl.py` | **MODIFY** | Add `execute_code_threaded()` method |
| `rlm_adk/tools/repl_tool.py` | **MODIFY** | Add thread bridge path (default), retain AST fallback |
| `rlm_adk/orchestrator.py` | **MODIFY** | Wire sync llm_query via thread bridge; inject skill globals; create SkillToolset |
| `rlm_adk/skills/__init__.py` | **MODIFY** | Update docstring to reflect new skill system |
| `rlm_adk/skills/loader.py` | **NEW** | Skill directory discovery, ADK Skill loading, REPL globals collection |
| `rlm_adk/state.py` | **MODIFY** | Add skill state keys |
| `rlm_adk/agent.py` | **MODIFY** | Pass `enabled_skills` through to orchestrator (already done, just needs consumption) |
| `rlm_adk/repl/ast_rewriter.py` | **NO CHANGE** | Retained as fallback |
| `rlm_adk/repl/skill_registry.py` | **NO CHANGE** | Source expansion coexists |
| `rlm_adk/dispatch.py` | **NO CHANGE** | Async closures work unchanged |

---

### Execution Flow (New Model)

```
1. Model calls execute_code(code="result = analyze_document(text)")

2. REPLTool.run_async():
   a. expand_skill_imports(code)  -- source expansion (unchanged)
   b. has_llm_calls(code)         -- observability only
   c. await repl.execute_code_threaded(code)
      └─ loop.run_in_executor(None, _execute_code_inner, code, trace)
         └─ Worker thread:
            ├─ _EXEC_LOCK acquired
            ├─ os.chdir(temp_dir)
            ├─ exec(code, namespace)
            │   └─ analyze_document(text) called
            │       └─ llm_query("Summarize: ...")  -- real sync function
            │           └─ asyncio.run_coroutine_threadsafe(
            │                 llm_query_async("Summarize: ..."),
            │                 loop  # captured at wiring time
            │              )
            │              └─ Event loop thread:
            │                 └─ llm_query_async → llm_query_batched_async
            │                     └─ _run_child → child orchestrator
            │                         └─ child events emitted
            │                         └─ LLMResult returned
            │              └─ future.result()  -- worker thread blocks here
            │           └─ LLMResult returned to analyze_document
            │       └─ analyze_document returns dict
            ├─ self.locals updated
            └─ _EXEC_LOCK released
   d. post_dispatch_state_patch_fn()  -- restores skill instruction
   e. Write LAST_REPL_RESULT to tool_context.state
   f. Return result dict to ADK
```

---

### Risk Analysis

| Risk | Mitigation |
|---|---|
| Deadlock: worker thread blocks on future.result(), event loop also blocked | Impossible -- `run_in_executor` yields control of the event loop. The event loop is free to run the `run_coroutine_threadsafe`-submitted coroutine. |
| Timeout: child dispatch takes too long | `future.result(timeout=600)` raises `TimeoutError`, caught by `_execute_code_inner`'s caller |
| GIL contention with concurrent REPL executions | `_EXEC_LOCK` already serializes REPL executions. Only one REPL code block runs at a time. |
| `_pending_llm_calls` race condition | No race: dispatch coroutine appends to `call_log_sink` on the event loop thread, worker thread is blocked on `future.result()` at that point |
| Recursive dispatch (child orchestrator also uses thread bridge) | Each child creates its own `LocalREPL` and its own thread bridge. The parent worker thread is blocked, so there is no resource contention. The event loop handles all async scheduling. |
| SkillToolset `@experimental` decorator | Feature flag `SKILL_TOOLSET` is `default_on=True` in the ADK registry -- no opt-in needed |
| ADK kebab-case skill name validation vs Python module names | Use kebab-case for SKILL.md `name`, derive Python module path by replacing hyphens with underscores |

---

### Critical Files for Implementation

- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py` - Add `execute_code_threaded()` method; core of the thread bridge execution
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py` - Switch default execution path to thread bridge; retain AST fallback
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` - Wire sync llm_query via thread bridge; inject skill globals; create SkillToolset; capture event loop reference
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` - No changes needed, but must be understood; async closures are the target of `run_coroutine_threadsafe`
- `/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/google/adk/tools/skill_toolset.py` - ADK upstream SkillToolset; pattern to follow for L1/L2 integration
