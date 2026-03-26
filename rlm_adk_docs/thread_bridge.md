# Thread Bridge Implementation (Plan B)

Thread bridge + ADK SkillToolset migration completed 2026-03-24 via Plan B TDD roadmap (27 cycles, 8 phases).

**Why:** AST rewriter couldn't handle `llm_query()` inside module-imported functions (opaque bytecode). Thread bridge makes `llm_query()` a real sync callable via `asyncio.run_coroutine_threadsafe()`.

**How to apply:** The thread bridge is now the ONLY execution path for REPL code. No AST rewriter fallback exists.

## Key Files Created/Modified

### New files:
- `rlm_adk/repl/thread_bridge.py` — `make_sync_llm_query()`, `make_sync_llm_query_batched()`, `_THREAD_DEPTH` ContextVar
- `rlm_adk/skills/loader.py` — `discover_skill_dirs()`, `collect_skill_repl_globals()`, `load_adk_skills()`, `_wrap_with_llm_query_injection()`
- `rlm_adk/skills/recursive_ping/` — First concrete skill (SKILL.md, ping.py, __init__.py)
- `tests_rlm_adk/test_thread_bridge.py` — 30 unit tests
- `tests_rlm_adk/test_skill_loader.py` — 23 unit tests
- `tests_rlm_adk/test_skill_toolset_integration.py` — 28 integration tests
- `tests_rlm_adk/test_skill_thread_bridge_e2e.py` — 15 e2e tests

### Deleted files:
- `rlm_adk/repl/ast_rewriter.py` — AST rewriter (Phase 0A)
- `rlm_adk/repl/skill_registry.py` — Source expansion registry (Phase 0B)
- `rlm_adk/skills/test_skill.py` — Old source-expandable test skill

### Key modifications:
- `rlm_adk/tools/repl_tool.py` — Uses `execute_code_threaded()`, `_finalize_telemetry` in `finally`, `execution_mode` in result
- `rlm_adk/repl/local_repl.py` — `_execute_code_threadsafe()` (lock-free), `execute_code_threaded()` (one-shot executor)
- `rlm_adk/orchestrator.py` — Wires sync bridge via `set_llm_query_fns()`, unconditional skill globals injection, conditional SkillToolset
- `rlm_adk/callbacks/reasoning.py` — CRITICAL: `append_instructions()` instead of overwriting `system_instruction` (preserves SkillToolset L1 XML)
- `rlm_adk/state.py` — Added `REPL_SKILL_GLOBALS_INJECTED`, removed 4 expansion keys
- `rlm_adk/types.py` — Expanded `LineageEnvelope.decision_mode` Literal
- `rlm_adk/plugins/sqlite_tracing.py` — Skill tool telemetry branches

## Architecture Summary

```text
Orchestrator._run_async_impl()
  │
  ├─ create_dispatch_closures() → (llm_query_async, llm_query_batched_async, flush_fn)
  │
  ├─ make_sync_llm_query(llm_query_async, loop) → sync closure
  ├─ make_sync_llm_query_batched(llm_query_batched_async, loop) → sync closure
  │
  ├─ repl.set_llm_query_fns(sync_llm_query, sync_llm_query_batched)
  │     └─ repl.globals["llm_query"] = sync_llm_query
  │     └─ repl.globals["llm_query_batched"] = sync_llm_query_batched
  │
  ├─ collect_skill_repl_globals() → {name: wrapped_fn, ...}
  │     └─ repl.globals.update(skill_globals)
  │
  └─ reasoning_agent.run_async(ctx)
       └─ REPLTool.run_async()
            └─ await repl.execute_code_threaded(code, trace)
                 │
                 ├─ ThreadPoolExecutor(max_workers=1)  [one-shot]
                 └─ loop.run_in_executor(executor, _execute_code_threadsafe, code)
                      │
                      │  [worker thread — lock-free, ContextVar capture]
                      ├─ exec(code, namespace)
                      │    └─ llm_query("prompt")
                      │         └─ run_coroutine_threadsafe(llm_query_async("prompt"), loop)
                      │              └─ future.result(timeout=300)
                      │                   └─ child orchestrator dispatches → worker returns
                      └─ return (stdout, stderr, success)
```

1. Orchestrator creates dispatch closures → `make_sync_llm_query(async_fn, loop)` → real sync callable
2. Sync callable wired to `repl.globals["llm_query"]` via `set_llm_query_fns()`
3. REPLTool calls `execute_code_threaded()` → one-shot ThreadPoolExecutor → `_execute_code_threadsafe()` (lock-free, ContextVar capture)
4. Inside worker thread, `llm_query()` calls `run_coroutine_threadsafe()` back to event loop → child dispatch → return
5. Skill functions auto-injected via `_wrap_with_llm_query_injection()` (lazy binding from repl_globals)
6. ADK SkillToolset provides L1/L2 discovery; `reasoning_before_model` preserves SkillToolset XML via `append_instructions()`

## Thread Safety Properties

- **Lock-free execution**: `_execute_code_threadsafe()` does NOT acquire `_EXEC_LOCK`. Uses ContextVar tokens for stdout/stderr capture and `_make_cwd_open()` for CWD-safe file access. No `os.chdir()`.
- **One-shot executor**: Each `execute_code_threaded()` call creates a new `ThreadPoolExecutor(max_workers=1)`, shut down in `finally`. Prevents default-pool exhaustion under recursive dispatch.
- **Thread depth limit**: `_THREAD_DEPTH` ContextVar counter with configurable max (default 10 via `RLM_MAX_THREAD_DEPTH` env var). Prevents runaway recursive thread creation.
- **ContextVar boundary**: ContextVars set in the event-loop thread are NOT visible in the worker thread, and vice versa. The thread bridge crosses this boundary via `run_coroutine_threadsafe`.

## Skill System

### Discovery (ADK SkillToolset)
- **L1**: `list_skills` tool returns `<available_skills>` XML in system instruction
- **L2**: `load_skill(name)` tool returns detailed instructions from `SKILL.md`
- Only root orchestrators get SkillToolset (gated by `enabled_skills`)

### Delivery (module import + `llm_query_fn` injection)
- `collect_skill_repl_globals()` scans `rlm_adk/skills/*/` for `SKILL.md` + `SKILL_EXPORTS`
- Functions with `llm_query_fn` parameter are wrapped via `_wrap_with_llm_query_injection()`
- Wrapper reads `llm_query` from `repl.globals` at call time (lazy binding)
- All orchestrators (root + children) get skill functions in REPL globals unconditionally

### Creating a new skill
1. Create `rlm_adk/skills/<skill_name>/` directory
2. Add `SKILL.md` with ADK frontmatter (`name`, `display_name`, `description`) and L2 instructions
3. Add `__init__.py` with `SKILL_EXPORTS = ["fn_name", "TypeName"]`
4. Add implementation module with functions that accept `*, llm_query_fn=None` parameter
5. Terminal operations return without calling `llm_query_fn`; recursive operations require it

## Observability

- `LAST_REPL_RESULT["execution_mode"]` = `"thread_bridge"` or `"sync"`
- `REPLTrace.execution_mode` typed as `Literal["sync", "thread_bridge"]`
- `REPL_SKILL_GLOBALS_INJECTED` state key lists injected skill function names
- `LineageEnvelope.decision_mode` expanded with `load_skill`, `list_skills`, `load_skill_resource`, `run_skill_script`. (Note: `decision_mode` now also lives on `LineageEdge` after the Phase 2 type split -- see `core_loop.md` section 6 for details.)
- `SqliteTracingPlugin.after_tool_callback` populates `skill_name_loaded` and `skill_instructions_len` for skill tool calls
- `_finalize_telemetry()` in `finally` block ensures telemetry fires on all paths (success, exception, cancellation)

## TDD Implementation Phases

| Phase | Cycles | What |
|-------|--------|------|
| 0 | 0A-0E | Legacy cleanup: delete AST rewriter, skill registry, async exec path, state keys |
| 1 | 1-9 | Thread bridge core: sync bridge, lock-free execution, REPLTool + orchestrator wiring |
| 2 | 10-14 | Skill loader: discover, collect, wrap, recursive-ping skill, orchestrator wiring |
| 3 | 15-16 | SkillToolset creation + CRITICAL `reasoning_before_model` fix |
| 4 | 17-20 | Observability: state keys, LineageEnvelope (now split into LineageEdge + ProvenanceRecord), sqlite_tracing, instruction disambiguation |
| 5 | 21-24 | Provider-fake e2e: thread bridge contract + three-plane verification |
| 6 | 25-26 | SkillToolset L1/L2 e2e + recursive-ping capstone |
| 7 | 27 | Full regression (96 new pass, 0 regressions) |

## Known Remaining Work
- 5 old provider-fake fixtures need updating for thread bridge execution semantics (adaptive_confidence_gating, deterministic_guardrails, full_pipeline, structured_control_plane, fake_polya_t4_debate)
- Demo-showboat tasks not yet executed (10 demo files in `demos/thread_bridge/`)
