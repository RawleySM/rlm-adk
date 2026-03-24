Thread-Bridge and Skill System Migration Plan

Executive Summary

The migration replaces the AST-rewriting mechanism (which transforms llm_query() into await llm_query_async()) with a thread-bridge architecture where REPL code executes in a worker thread and llm_query() is a real sync callable that uses asyncio.run_coroutine_threadsafe() to dispatch back to the event loop. This eliminates the fundamental limitation that prevents module-imported functions from calling
llm_query(), which is the prerequisite for a proper skill system where skills are typed Python functions in regular .py modules.

Current Architecture Analysis

The current execution path has two branches in REPLTool.run_async() (line 223 of /home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py):

Branch A (async path): When has_llm_calls(exec_code) returns True:
1. rewrite_for_async(exec_code) AST-rewrites llm_query() calls to await llm_query_async()
2. The rewritten code is wrapped in async def _repl_exec(): ...; return locals()
3. repl.execute_code_async() runs the compiled async wrapper in the event loop

Branch B (sync path): When no llm_query calls are detected:
1. repl.execute_code(exec_code) runs synchronously in a ThreadPoolExecutor with timeout

The problem: Branch A only works for code submitted directly to the REPL, because has_llm_calls() does AST walking on the top-level code. If the code calls my_skill_function() which internally calls llm_query(), the AST walker does not see the llm_query() call inside the function body of an imported module. The AST rewriter has no way to transform code inside already-compiled .py modules.

Key ADK Discovery

ADK's functions.py (at .venv/lib/python3.12/site-packages/google/adk/flows/llm_flows/functions.py) already has infrastructure for running tools in thread pools:

- _get_tool_thread_pool(max_workers) -- global thread pool cache (line 83)
- _call_tool_in_thread_pool() -- runs tools via loop.run_in_executor() (line 116)
- __call_tool_async() -- the actual call site that invokes tool.run_async() (line 1105)

However, ADK calls REPLTool.run_async() directly via __call_tool_async() at line 1111 (just await tool.run_async(...)), NOT through the thread pool. The thread pool path is only for FunctionTool instances with sync underlying functions, or for Live API mode. So RLM-ADK's REPLTool.run_async() runs on the main event loop, which is why it can await the async dispatch closures today.

---
Phase 1: Thread-Bridge Foundation

1.1 Core Concept

Instead of:
REPLTool.run_async() [event loop]
    -> has_llm_calls() -> rewrite_for_async()
    -> repl.execute_code_async() [event loop, awaits llm_query_async]

The new architecture is:
REPLTool.run_async() [event loop]
    -> loop.run_in_executor(thread_pool, repl.execute_code_in_thread)
        [worker thread]
        -> exec(code, namespace)
        -> code calls llm_query(prompt)
        -> llm_query() calls asyncio.run_coroutine_threadsafe(llm_query_async(prompt), loop)
        -> .result() blocks the worker thread until child completes
        -> llm_query() returns the result as a string
    -> [event loop resumes when thread completes]

1.2 Changes to rlm_adk/dispatch.py

What changes: create_dispatch_closures() currently returns (llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn). It will additionally create and return sync wrappers that use run_coroutine_threadsafe().

New closures (added inside create_dispatch_closures()):

def llm_query_sync(
    prompt: str,
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> LLMResult:
    """Sync bridge: submits async dispatch to event loop, blocks worker thread."""
    future = asyncio.run_coroutine_threadsafe(
        llm_query_async(prompt, model=model, output_schema=output_schema),
        _loop,
    )
    return future.result()  # Blocks the calling thread

def llm_query_batched_sync(
    prompts: list[str],
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> list[LLMResult]:
    """Sync bridge: submits async batched dispatch to event loop, blocks worker thread."""
    future = asyncio.run_coroutine_threadsafe(
        llm_query_batched_async(prompts, model=model, output_schema=output_schema),
        _loop,
    )
    return future.result()  # Blocks the calling thread

Key requirement: The closures need a reference to the running event loop. This is passed as a new parameter event_loop: asyncio.AbstractEventLoop to create_dispatch_closures().

Return type change: The 3-tuple becomes a 4-tuple:
return (
    llm_query_async,
    llm_query_batched_async,
    post_dispatch_state_patch_fn,
    llm_query_sync,           # NEW
    llm_query_batched_sync,   # NEW
)

Or better: return a named tuple / dataclass to avoid positional arg fragility at the 5-element mark.

Exact file: /home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py

Specific lines to modify:
- Function signature at line 109 (add event_loop parameter)
- New sync closure definitions (after llm_query_batched_async at ~line 535)
- Return statement at line 548 (add new closures)

1.3 Changes to rlm_adk/tools/repl_tool.py

What changes: The bifurcated has_llm_calls() / rewrite_for_async() path is replaced by a single path: always run in a worker thread.

Current code at line 222-243:
if has_llm_calls(exec_code):
    llm_calls_made = True
    tree = rewrite_for_async(exec_code)
    compiled = compile(tree, "<repl>", "exec")
    result = await self.repl.execute_code_async(code, trace=trace, compiled=compiled)
else:
    result = self.repl.execute_code(exec_code, trace=trace)

New code: Replace with a single branch:
result = await self._execute_in_thread(exec_code, trace=trace)

Where _execute_in_thread is a new method on REPLTool that does:
async def _execute_in_thread(self, code: str, trace: REPLTrace | None = None) -> REPLResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,  # default executor
        self.repl.execute_code, code, trace,
    )

This works because LocalREPL.execute_code() is already a sync method that runs code in a thread with _EXEC_LOCK. The key difference is that now llm_query() in repl.globals is the real sync callable (the llm_query_sync closure from dispatch.py), not the sync_llm_query_unsupported stub.

Additional changes to REPLTool:
- Add self._event_loop: asyncio.AbstractEventLoop | None = None field
- Store the loop reference for dispatch closure creation
- Remove self._rewrite_count, self._rewrite_total_ms, self._rewrite_failure_count (AST rewriter telemetry becomes obsolete)
- Remove imports of has_llm_calls, rewrite_for_async from ast_rewriter

Exact file: /home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py

1.4 Changes to rlm_adk/repl/local_repl.py

What changes:
- set_llm_query_fns() (line 211) becomes the primary wiring point. It now receives the sync dispatch closures.
- set_async_llm_query_fns() (line 216) is kept for backward compatibility during transition but marked as deprecated. In the final state, it can be removed.
- execute_code_async() (line 385) is kept but marked as deprecated. It is only needed if the AST rewriter is retained as an optional optimization path.
- execute_code() (line 328) remains the primary execution method. The key change: the llm_query and llm_query_batched names in self.globals are now real sync callables that block the worker thread via run_coroutine_threadsafe(), so no AST rewriting is needed.

Exact file: /home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py

1.5 Changes to rlm_adk/orchestrator.py

What changes at the wiring site (lines 271-297):

Currently:
(llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn) = create_dispatch_closures(...)
repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)
# Sets sync stub that raises RuntimeError
repl.set_llm_query_fns(sync_llm_query_unsupported, sync_llm_query_unsupported)

New:
loop = asyncio.get_running_loop()
dispatch_result = create_dispatch_closures(
    ...,
    event_loop=loop,
)
# Wire the SYNC closures as the primary llm_query/llm_query_batched
repl.set_llm_query_fns(dispatch_result.llm_query_sync, dispatch_result.llm_query_batched_sync)
# Keep async closures wired for backward compatibility (deprecated path)
repl.set_async_llm_query_fns(dispatch_result.llm_query_async, dispatch_result.llm_query_batched_async)

Exact file: /home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py, lines 271-297

1.6 What Happens to the AST Rewriter

Decision: Keep as optional, disable by default.

The AST rewriter (/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/ast_rewriter.py) should NOT be deleted in Phase 1. Instead:
1. The thread-bridge path becomes the default (and only) path in REPLTool.run_async().
2. The AST rewriter module is left in place but is no longer imported by repl_tool.py.
3. Tests for the AST rewriter itself remain (they test a standalone module).
4. An environment variable RLM_USE_AST_REWRITER=1 could be offered as a fallback escape hatch during the transition period.
5. After the thread-bridge is proven stable across the full test suite, the AST rewriter can be removed in a cleanup pass.

1.7 Thread Safety Analysis

Why this is safe (referencing the verified constraints from the task description):

1. tool_context.state writes: All tool_context.state[key] = value calls happen in REPLTool.run_async() (on the event loop thread), BEFORE and AFTER the run_in_executor() call. The REPL code in the worker thread never writes to tool_context.state. The sync llm_query() closure dispatches to the event loop via run_coroutine_threadsafe(), and child state mutations happen entirely in the event loop.
2. Plugin/agent callbacks: Fire in _execute_single_function_call_async() (ADK's functions.py) which runs on the event loop. They fire AFTER tool.run_async() returns, which happens after the run_in_executor() future completes. No concurrency with tool execution.
3. Child dispatch: _run_child() (dispatch.py line 269) creates a child RLMOrchestratorAgent and iterates its events via async for _event in child.run_async(child_ctx). This runs entirely on the event loop (submitted via run_coroutine_threadsafe). The event queue bridging (child_event_queue.put_nowait()) is also on the event loop thread, safe with the existing drain loop.
4. stdout/stderr capture: _capture_stdout/_capture_stderr ContextVars in local_repl.py are already thread-safe by design (ContextVars are task/thread-local). The _TaskLocalStream proxy at lines 39-68 already handles this.
5. _EXEC_LOCK: Already exists (line 77 of local_repl.py) and serializes concurrent REPL executions. The thread-bridge adds no new concurrency concern here.
6. GIL protection: dict.__setitem__ (which is what tool_context.state[key] = value does) is GIL-atomic for simple dict operations.

1.8 Validation Test: Module-Level Function with llm_query

New test file: tests_rlm_adk/test_thread_bridge.py

The core validation test creates a Python module-level function that calls llm_query(), injects it into REPL globals, and verifies the function works when called from REPL code:

# Concept (not exact code):
def test_module_function_with_llm_query():
    """Verify that a regular Python function calling llm_query() works
    when imported into REPL globals and called from execute_code."""

    # Define a regular Python function (not source-expanded, not AST-rewritten)
    def analyze_text(text: str) -> str:
        """A skill function that calls llm_query() internally."""
        result = llm_query(f"Summarize: {text}")
        return f"Summary: {result}"

    # Set up REPL + dispatch closures
    # Wire analyze_text into repl.globals
    # Submit code: result = analyze_text("Hello world")
    # Verify result contains the child's response

This test MUST use the provider_fake infrastructure (not mocks) to exercise the full pipeline. A new fixture JSON file would script the API responses for the child dispatch triggered by llm_query() inside analyze_text().

Additional tests:
- Test that llm_query_batched() works from a module-level function
- Test that nested calls work (function A calls function B which calls llm_query())
- Test timeout behavior (sync call blocks too long)
- Test error propagation (child dispatch fails, error surfaces in calling thread)

1.9 What Can Break and How to Detect It

┌────────────────────────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────┐
│                                                Risk                                                │                                                                                        Detection                                                                                         │                                       Mitigation                                       │
├────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Deadlock: worker thread blocks on future.result() while event loop is blocked on run_in_executor() │ This CANNOT happen because run_in_executor() is non-blocking on the event loop. The event loop is free to process the run_coroutine_threadsafe future.                                   │ N/A -- architecturally safe                                                            │
├────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Timeout: child dispatch takes too long, worker thread blocks indefinitely                          │ Add optional timeout parameter to the sync closures, defaulting to RLM_LLM_QUERY_TIMEOUT env var                                                                                         │ future.result(timeout=...) raises TimeoutError which surfaces as REPL stderr           │
├────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ stdout/stderr capture: output from worker thread not captured                                      │ Existing _TaskLocalStream + ContextVar mechanism handles this                                                                                                                            │ Verify in thread-bridge test that print() output from worker thread appears in result  │
├────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Existing tests break because they mock llm_query_async directly                                    │ Tests that directly mock set_async_llm_query_fns may need updating                                                                                                                       │ Keep both sync and async closures wired during transition; audit test mocking patterns │
├────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ _EXEC_LOCK contention with batched dispatch                                                        │ Batched dispatch runs N children concurrently on the event loop, but the parent REPL thread holds _EXEC_LOCK the entire time. Since children don't use the parent's REPL, no contention. │ N/A -- architecturally safe                                                            │
└────────────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────┘

1.10 Files Modified in Phase 1

┌────────────────────────────┬────────────────────────────────────────────────────────────────────────────┐
│            File            │                                   Change                                   │
├────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/dispatch.py        │ Add event_loop parameter, create sync closure wrappers, change return type │
├────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/tools/repl_tool.py │ Remove AST rewriter bifurcation, replace with single run_in_executor path  │
├────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/orchestrator.py    │ Wire sync closures via set_llm_query_fns(), pass event loop to dispatch    │
├────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/repl/local_repl.py │ Minor: document that set_llm_query_fns now receives sync bridge closures   │
└────────────────────────────┴────────────────────────────────────────────────────────────────────────────┘

1.11 New Files in Phase 1

┌──────────────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────┐
│                                 File                                 │                       Purpose                        │
├──────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ tests_rlm_adk/test_thread_bridge.py                                  │ Validation tests for the thread-bridge               │
├──────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ tests_rlm_adk/fixtures/provider_fake/thread_bridge_module_skill.json │ Provider-fake fixture for module-level function test │
└──────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────┘

1.12 Dependencies and Sequencing

1. Modify dispatch.py first (add sync closures) -- this is additive, breaks nothing
2. Modify orchestrator.py to wire sync closures -- still additive, the async path still works
3. Modify repl_tool.py to use the thread-bridge path -- this is the breaking change
4. Run the full test suite (654 tests) to verify nothing regresses
5. Add test_thread_bridge.py with the new module-function validation test

---
Phase 2: Skill Infrastructure

2.1 Skill Definition Pattern

A skill is a directory containing:
rlm_adk/skills/<skill-name>/
    SKILL.md          # ADK L1/L2: frontmatter + instructions
    __init__.py       # Python module exporting skill functions
    <module>.py       # Implementation files
    references/       # Optional: reference docs
    assets/           # Optional: static assets

The key insight: SKILL.md is for the model (discovery + instructions), Python modules are for the REPL (executable functions). These are two independent delivery mechanisms that happen to live in the same directory.

2.2 How Skill Functions Get Into repl.globals

New module: rlm_adk/skills/loader.py

This module provides:

@dataclass
class SkillFunctionExport:
    """A typed Python function exported by a skill for REPL use."""
    name: str           # Function name in repl.globals
    callable: Callable  # The actual function object
    skill_name: str     # Which skill provides it
    doc: str            # Docstring for discovery

def load_skill_functions(skill_names: Iterable[str]) -> dict[str, SkillFunctionExport]:
    """Load all exported functions from the named skills.
    
    Scans rlm_adk/skills/<name>/__init__.py for a SKILL_EXPORTS list.
    Returns {function_name: SkillFunctionExport}.
    """

def inject_skill_functions(repl: LocalREPL, exports: dict[str, SkillFunctionExport]) -> None:
    """Inject skill function exports into REPL globals."""
    for name, export in exports.items():
        repl.globals[name] = export.callable

Each skill's __init__.py declares its exports:
# rlm_adk/skills/recursive-ping/__init__.py
from rlm_adk.skills.recursive_ping.ping import run_recursive_ping, RecursivePingResult

SKILL_EXPORTS = [
    run_recursive_ping,
    RecursivePingResult,
]

The functions reference llm_query as a global name. Because the thread-bridge (Phase 1) has already wired llm_query as a real sync callable in repl.globals, these functions just work when called from REPL code.

2.3 ADK SkillToolset Integration (L1/L2 Discovery)

New module: rlm_adk/skills/toolset.py

This module creates an SkillToolset from the skills directories, following ADK's L1/L2 pattern documented in /home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/adk_skill_state.md:

- L1 (Frontmatter): Always injected into the system instruction as XML. Tells the model what skills are available and what they do.
- L2 (Instructions): Loaded on demand when the model calls load_skill. Tells the model HOW to use the skill, including function signatures, parameters, example code.

from google.adk.tools.skill_toolset import SkillToolset
from google.adk.skills import load_skill_from_dir

def create_rlm_skill_toolset(skill_names: Iterable[str]) -> SkillToolset:
    """Create an ADK SkillToolset from the named skill directories."""
    skills_dir = Path(__file__).parent
    skills = []
    for name in skill_names:
        skill_dir = skills_dir / name
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            skills.append(load_skill_from_dir(skill_dir))
    return SkillToolset(skills=skills)

2.4 Wiring in the Orchestrator

Changes to rlm_adk/orchestrator.py:

In _run_async_impl(), after REPL setup and dispatch closure wiring:

# Load and inject skill functions into REPL
if self.enabled_skills:
    from rlm_adk.skills.loader import load_skill_functions, inject_skill_functions
    skill_exports = load_skill_functions(self.enabled_skills)
    inject_skill_functions(repl, skill_exports)

Changes to rlm_adk/agent.py:

In create_rlm_orchestrator() and create_child_orchestrator():

When enabled_skills is non-empty, create the SkillToolset and include it in the reasoning agent's tools list alongside repl_tool and set_model_response_tool:

# In orchestrator._run_async_impl(), when building tools list:
tools = [repl_tool, set_model_response_tool]
if self.enabled_skills:
    from rlm_adk.skills.toolset import create_rlm_skill_toolset
    skill_toolset = create_rlm_skill_toolset(self.enabled_skills)
    tools.append(skill_toolset)

This gives the model three capabilities:
1. execute_code -- run Python in the REPL (with skill functions available as globals)
2. set_model_response -- return final answer
3. list_skills / load_skill -- discover and load skill instructions

2.5 What Happens to the Existing SkillRegistry

Decision: Keep but deprecate.

The SkillRegistry in /home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/skill_registry.py is a source-expansion mechanism (replacing synthetic imports with inline source). The thread-bridge makes this unnecessary because real Python modules can now call llm_query(). However:

1. expand_skill_imports() is called on every REPL execution in repl_tool.py (line 177). Since the registry is empty, it is already a no-op.
2. Keep the call in place for Phase 2 but add a comment that it is deprecated.
3. Remove in a later cleanup pass.

2.6 What Happens to instruction_router

Decision: Keep as the foundational mechanism, layer SkillToolset on top.

The instruction_router is the active mechanism for injecting skill-like instructions per (depth, fanout_idx). The new skill system should create an instruction_router from the active skills:

def build_instruction_router_from_skills(
    skill_names: Iterable[str],
) -> Callable[[int, int], str]:
    """Build an instruction_router that composes L2 instructions from active skills."""
    # Load L2 instructions from SKILL.md files
    # Return a callable that generates the composite instruction

This is wired in create_rlm_orchestrator() when enabled_skills is provided but no explicit instruction_router is given.

2.7 Skill Activation Tracking

ADK's LoadSkillTool already tracks activation in session state under _adk_activated_skill_{agent_name}. The RLM system can read this to know which skills the model has loaded. For observability:

- sqlite_tracing.py already has skill_name_loaded and skill_instructions_len columns
- DYN_SKILL_INSTRUCTION state key already captures the instruction text per turn
- Dashboard registered_skills (currently hardcoded []) should be populated from skill metadata

2.8 Files Modified in Phase 2

┌──────────────────────────────────┬────────────────────────────────────────────────────────────────────────────┐
│               File               │                                   Change                                   │
├──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/orchestrator.py          │ Inject skill functions into REPL globals; add SkillToolset to tools list   │
├──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/agent.py                 │ Build instruction_router from enabled_skills when no explicit router given │
├──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/state.py                 │ Add any new state key constants for skill tracking                         │
├──────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
│ rlm_adk/dashboard/live_loader.py │ Populate registered_skills from skill metadata                             │
└──────────────────────────────────┴────────────────────────────────────────────────────────────────────────────┘

2.9 New Files in Phase 2

┌────────────────────────────────────┬───────────────────────────────────────────────────────┐
│                File                │                        Purpose                        │
├────────────────────────────────────┼───────────────────────────────────────────────────────┤
│ rlm_adk/skills/loader.py           │ Load skill function exports, inject into REPL globals │
├────────────────────────────────────┼───────────────────────────────────────────────────────┤
│ rlm_adk/skills/toolset.py          │ Create ADK SkillToolset from skill directories        │
├────────────────────────────────────┼───────────────────────────────────────────────────────┤
│ tests_rlm_adk/test_skill_loader.py │ Unit tests for skill loading and injection            │
└────────────────────────────────────┴───────────────────────────────────────────────────────┘

2.10 Dependencies and Sequencing

Phase 2 depends on Phase 1 being complete (thread-bridge must work for skill functions to call llm_query()).

1. Create loader.py and toolset.py -- standalone, no integration yet
2. Create the first skill directory (Phase 3)
3. Wire loader into orchestrator
4. Wire SkillToolset into reasoning agent tools
5. Update dashboard to populate registered_skills
6. Run full test suite

---
Phase 3: First Real Skill -- recursive-ping

3.1 Why recursive-ping

The recursive ping is the ideal first skill because:
1. It already exists as an obsolete source-expanded skill (/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/obsolete/repl_skills/ping.py)
2. It exercises the core capability: a module-level function calling llm_query()
3. It has a provider_fake fixture (fake_recursive_ping.json) that validates the full recursive dispatch pipeline
4. It is small enough to validate the entire skill lifecycle without domain complexity

3.2 Skill Directory Structure

rlm_adk/skills/recursive-ping/
    SKILL.md              # Frontmatter + instructions
    __init__.py           # SKILL_EXPORTS declaration
    ping.py               # run_recursive_ping() and helpers

3.3 SKILL.md Content

---
name: recursive-ping
description: "Test skill that dispatches recursive llm_query() calls across depth layers. Use for verifying recursive dispatch, depth-limited execution, and child event re-emission."
allowed-tools: execute_code
---

# Recursive Ping Skill

This skill provides `run_recursive_ping()` for testing recursive LLM dispatch.

## Available Functions

### run_recursive_ping(max_layer=2, starting_layer=0, ...)

Dispatches recursive `llm_query()` calls through depth layers. Layer 0 dispatches to layer 1, layer 1 dispatches to layer 2 (terminal), and the terminal layer returns a JSON payload that propagates back up.

**Usage in execute_code:**
```python
result = run_recursive_ping(max_layer=2)
print(result.payload)  # {"my_response": "pong", "your_response": "ping"}
print(result.layer)    # 0

Parameters:
- max_layer (int): Maximum recursion depth. Default 2.
- starting_layer (int): Starting layer index. Default 0.
- terminal_payload (dict): JSON payload returned by terminal layer. Default: {"my_response": "pong", "your_response": "ping"}.

Returns: RecursivePingResult with .layer, .payload, .child_response, .debug_log attributes.

### 3.4 ping.py Content

The function bodies are extracted from the existing source strings in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/obsolete/repl_skills/ping.py`, converted from inline source strings to regular Python code.

The critical difference from the obsolete version: `llm_query` is NOT defined in this module. It is resolved at call time from the REPL globals because the function executes inside the REPL namespace where `llm_query` is already wired as a sync callable.

To make this work cleanly, the function should accept `llm_query` as a parameter with a default that falls back to the global:

```python
def run_recursive_ping(
    max_layer=2,
    starting_layer=0,
    terminal_layer=2,
    emit_debug=True,
    terminal_payload=None,
    layer1_reasoning_summary=None,
    layer2_reasoning_summary=None,
    llm_query_fn=None,  # defaults to globals()['llm_query'] at call time
):
    import json

    if llm_query_fn is None:
        # Resolve from REPL globals at call time
        import builtins
        _globals = getattr(builtins, '__import__')('__main__').__dict__
        # Actually: simpler to just reference the name directly since
        # the function runs in the REPL namespace where llm_query is defined
        pass
    ...

Actually, the simplest and most correct approach: the skill function references llm_query as a free variable. When it executes in the REPL namespace (via exec()), llm_query is resolved from the REPL globals. This is how the obsolete source-expanded version worked -- the expanded source was exec()'d in the REPL namespace, so llm_query was available as a global.

For a regular module import, the function needs llm_query injected. The cleanest pattern:

# ping.py
def run_recursive_ping(..., _llm_query=None):
    """..."""
    _query = _llm_query or llm_query  # llm_query resolved from caller's globals

But this is fragile. The better pattern for the skill loader:

When inject_skill_functions() injects a skill function into REPL globals, it wraps it with functools.partial or creates a closure that binds llm_query from the REPL globals:

# In loader.py:
def inject_skill_functions(repl, exports):
    for name, export in exports.items():
        if export.needs_llm_query:
            # Create a wrapper that binds llm_query from repl.globals
            original_fn = export.callable
            def _bound(*args, _fn=original_fn, _repl=repl, **kwargs):
                kwargs.setdefault('llm_query_fn', _repl.globals.get('llm_query'))
                return _fn(*args, **kwargs)
            repl.globals[name] = _bound
        else:
            repl.globals[name] = export.callable

Or even simpler: inject llm_query into the skill module's own globals at load time:

# In loader.py:
import rlm_adk.skills.recursive_ping.ping as ping_module
ping_module.llm_query = repl.globals['llm_query']

This approach is dangerous (mutates module globals, not thread-safe for multiple REPL instances). The cleanest approach for Phase 3:

The skill function accepts llm_query as a parameter. The REPL code calls it by passing the global:

# REPL code:
result = run_recursive_ping(llm_query_fn=llm_query)

Or even better: the skill loader wraps the function to auto-inject:

# loader.py
def _make_bound_skill_fn(fn, repl):
    """Wrap a skill function to auto-inject llm_query from REPL globals."""
    sig = inspect.signature(fn)
    if 'llm_query_fn' in sig.parameters:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if 'llm_query_fn' not in kwargs:
                kwargs['llm_query_fn'] = repl.globals.get('llm_query')
            return fn(*args, **kwargs)
        return wrapper
    return fn

This is the best of both worlds: the skill function is a regular Python function testable in isolation (pass llm_query_fn explicitly in tests), and when used in the REPL it gets the real llm_query injected automatically.

3.5 Testing Without Reward-Hacking

The test must exercise the real pipeline:

1. Use the provider_fake infrastructure with a fixture that scripts API responses for the full recursive dispatch chain (root reasoning -> execute_code -> llm_query -> child reasoning -> execute_code -> llm_query -> terminal child -> response propagation)
2. The fixture must script the model deciding to call run_recursive_ping() via execute_code, NOT have the test directly call the function
3. The fixture scripts the child responses realistically (they use execute_code and set_model_response)
4. Assertions verify the final answer contains the propagated payload

New fixture: tests_rlm_adk/fixtures/provider_fake/skill_recursive_ping.json

This fixture is structurally similar to the existing fake_recursive_ping.json but the root reasoning's execute_code block calls run_recursive_ping() (the skill function) instead of inline llm_query() code.

3.6 Files in Phase 3

┌────────────────────────────────────────────────────────────────┬────────────────────────────┐
│                              File                              │          Purpose           │
├────────────────────────────────────────────────────────────────┼────────────────────────────┤
│ rlm_adk/skills/recursive-ping/SKILL.md                         │ Frontmatter + instructions │
├────────────────────────────────────────────────────────────────┼────────────────────────────┤
│ rlm_adk/skills/recursive-ping/__init__.py                      │ SKILL_EXPORTS              │
├────────────────────────────────────────────────────────────────┼────────────────────────────┤
│ rlm_adk/skills/recursive-ping/ping.py                          │ Implementation             │
├────────────────────────────────────────────────────────────────┼────────────────────────────┤
│ tests_rlm_adk/test_skill_recursive_ping.py                     │ E2E test                   │
├────────────────────────────────────────────────────────────────┼────────────────────────────┤
│ tests_rlm_adk/fixtures/provider_fake/skill_recursive_ping.json │ Fixture                    │
└────────────────────────────────────────────────────────────────┴────────────────────────────┘

---
Risk Summary Across All Phases

┌───────┬───────────────────────────────────────────────────────┬─────────────┬──────────┬───────────────────────────────────────────────────────────────────────┐
│ Phase │                     Highest Risk                      │ Probability │  Impact  │                              Mitigation                               │
├───────┼───────────────────────────────────────────────────────┼─────────────┼──────────┼───────────────────────────────────────────────────────────────────────┤
│ 1     │ Existing tests break due to changed execution path    │ Medium      │ High     │ Run full suite after each step; keep AST rewriter as fallback         │
├───────┼───────────────────────────────────────────────────────┼─────────────┼──────────┼───────────────────────────────────────────────────────────────────────┤
│ 1     │ Deadlock in thread-bridge                             │ Very Low    │ Critical │ Architecturally impossible (event loop never blocks on worker thread) │
├───────┼───────────────────────────────────────────────────────┼─────────────┼──────────┼───────────────────────────────────────────────────────────────────────┤
│ 1     │ stdout/stderr capture misses output                   │ Low         │ Medium   │ ContextVar mechanism already handles threads; validate in tests       │
├───────┼───────────────────────────────────────────────────────┼─────────────┼──────────┼───────────────────────────────────────────────────────────────────────┤
│ 2     │ SkillToolset conflicts with existing tool wiring      │ Low         │ Medium   │ SkillToolset appended to tools list, does not replace existing tools  │
├───────┼───────────────────────────────────────────────────────┼─────────────┼──────────┼───────────────────────────────────────────────────────────────────────┤
│ 2     │ Model ignores skill instructions                      │ Medium      │ Low      │ L1 XML injection is proven in ADK; iterative prompt improvement       │
├───────┼───────────────────────────────────────────────────────┼─────────────┼──────────┼───────────────────────────────────────────────────────────────────────┤
│ 3     │ Provider-fake fixture doesn't match real API behavior │ Low         │ Medium   │ Fixture follows established patterns from 18 existing fixtures        │
└───────┴───────────────────────────────────────────────────────┴─────────────┴──────────┴───────────────────────────────────────────────────────────────────────┘

---
Critical Files for Implementation

- /home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py - Core change: add sync bridge closures using run_coroutine_threadsafe(), add event_loop parameter
- /home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py - Core change: replace AST rewriter bifurcation with single run_in_executor() thread-bridge path
- /home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py - Wiring change: pass event loop to dispatch, wire sync closures, inject skill functions into REPL
- /home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py - Minor change: document that set_llm_query_fns now receives sync bridge closures; execution path unchanged
- /home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/obsolete/repl_skills/ping.py - Reference: existing source-expanded ping skill, to be converted to a real Python module in Phase 3
