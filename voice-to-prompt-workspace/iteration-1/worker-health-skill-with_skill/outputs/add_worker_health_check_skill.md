<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Add Worker Health Check REPL Skill

## Context

RLM-ADK needs a new source-expandable REPL skill that health-checks the child dispatch pipeline by sending simple queries to multiple workers concurrently via `llm_query_batched()` and reporting per-worker latency and error status. The skill follows the same pattern as the existing recursive ping skill (`rlm_adk/skills/repl_skills/ping.py`) and should be auto-discovered by the skill registry via a side-effect import in the orchestrator.

## Original Transcription

> I want to add a new skill, like a repl skill similar to the ping one but this one should do like a health check on the worker pool. It should dispatch a simple query to each worker and report back latency and whether they responded. Put it next to the ping skill I guess. And make sure the skill registry picks it up automatically.

## Refined Instructions

1. **Create the skill module** at `rlm_adk/skills/repl_skills/worker_health.py`. Follow the exact structure of `rlm_adk/skills/repl_skills/ping.py`:
   - Import `ReplSkillExport` and `register_skill_export` from `rlm_adk.repl.skill_registry`.
   - Define source strings as module-level constants (Python string literals containing the code that will be inlined into the REPL).
   - Call `register_skill_export()` at module level for each export, registering under the synthetic module `rlm_repl_skills.worker_health`.

2. **Define these exports** (minimum set):

   | Symbol | Kind | Dependencies | Purpose |
   |--------|------|-------------|---------|
   | `HEALTH_CHECK_PROMPT` | const | -- | Simple prompt string for the health check query (e.g., `"Respond with exactly: OK"`) |
   | `WorkerHealthResult` | class | -- | Result container with attributes: `worker_count: int`, `results: list[dict]` (each dict has `worker_idx`, `latency_ms`, `responded: bool`, `error_category: str | None`, `response_preview: str`), `all_healthy: bool`, `total_latency_ms: float` |
   | `run_worker_health_check` | function | `HEALTH_CHECK_PROMPT`, `WorkerHealthResult` | Main entry point. Accepts `worker_count: int = 5` (should default to the `DispatchConfig.pool_size` default). Dispatches `worker_count` identical simple prompts via `llm_query_batched()`, collects per-result latency (from `LLMResult.wall_time_ms`) and error status (from `LLMResult.error` / `LLMResult.error_category`), returns a `WorkerHealthResult` |

3. **Implementation details for `run_worker_health_check` source**:
   - Build a list of `worker_count` copies of `HEALTH_CHECK_PROMPT`.
   - Call `llm_query_batched(prompts)` to dispatch all queries concurrently.
   - For each `LLMResult` in the returned list, extract:
     - `wall_time_ms` (latency)
     - `error` (bool -- whether the worker responded successfully)
     - `error_category` (string category if error)
     - A preview of the response text (first 100 chars)
   - Compute `all_healthy = all(not r.error for r in results)` and `total_latency_ms = max(latencies)` (wall-clock time for the batch, since they run concurrently).
   - Include a `debug_log` list and optional `emit_debug` parameter (matching the ping skill pattern) that prints status messages via `print()`.
   - The source must use `llm_query_batched()` (not `llm_query_batched_async`) -- the AST rewriter handles the sync-to-async transformation.

4. **Register the side-effect import in `orchestrator.py`**. Add the import at line 288 (after the existing ping import at L287):
   ```python
   import rlm_adk.skills.repl_skills.worker_health  # noqa: F401
   ```
   This is the mechanism that triggers `register_skill_export()` calls at import time, making the skill available to the `SkillRegistry` singleton for synthetic import expansion.

5. **Verify the skill works with the synthetic import contract**. The model should be able to write:
   ```python
   from rlm_repl_skills.worker_health import run_worker_health_check

   result = run_worker_health_check(worker_count=3)
   print(f"All healthy: {result.all_healthy}")
   for r in result.results:
       print(f"  Worker {r['worker_idx']}: {r['latency_ms']:.0f}ms, responded={r['responded']}")
   ```
   The `SkillRegistry.expand()` method should inline all three exports (topologically sorted) before the AST rewriter runs, making the `llm_query_batched()` call visible for sync-to-async rewriting.

6. *[Added -- the transcription did not mention testing, but all new skill modules need at least a basic expansion test.]* **Add a basic test** in `tests_rlm_adk/` that verifies:
   - Importing `rlm_adk.skills.repl_skills.worker_health` registers the expected symbols in the skill registry.
   - `expand_skill_imports()` correctly expands `from rlm_repl_skills.worker_health import run_worker_health_check` into inline source containing all three symbols.
   - The expanded source is valid Python (parses with `ast.parse()`).

## Considerations

- **Source expansion, not `repl.globals` injection**: This skill uses `llm_query_batched()`, so it must be source-expandable (not injected via `repl.globals`). The AST rewriter only operates on submitted code text -- functions in `repl.globals` that call `llm_query()` internally are invisible to the rewriter.

- **`DispatchConfig` is not directly accessible from REPL code**: The REPL environment does not have access to the `DispatchConfig` / `WorkerPool` object. The `worker_count` parameter should default to 5 (matching `DispatchConfig.__init__` default `pool_size=5` at `dispatch.py` L152) but the skill cannot dynamically read the actual pool size at runtime. This is acceptable for a health check -- the user can pass a different count if needed.

- **`LLMResult` attributes**: The expanded source can rely on `LLMResult` being available in REPL globals (it is injected at `orchestrator.py` L246). The `wall_time_ms`, `error`, and `error_category` attributes are all public on `LLMResult` (`types.py` L110-122).

- **AR-CRIT-001 compliance**: This skill only reads `LLMResult` attributes returned by `llm_query_batched()`. It does not write to session state. No state mutation concerns.

- **Topological sort**: Ensure the `requires` fields correctly express that `run_worker_health_check` depends on both `HEALTH_CHECK_PROMPT` and `WorkerHealthResult`. The `SkillRegistry._topo_sort` will inline constants and the class before the function.

- **Existing test suite**: Run `.venv/bin/python -m pytest tests_rlm_adk/` after implementation to verify no regressions. Do NOT run with `-m ""`.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/skills/repl_skills/ping.py` | `register_skill_export()` calls | L147-211 | Template for new skill registration pattern |
| `rlm_adk/repl/skill_registry.py` | `ReplSkillExport` | L15 | Dataclass for skill export definition |
| `rlm_adk/repl/skill_registry.py` | `register_skill_export()` | L219 | Module-level registration API |
| `rlm_adk/repl/skill_registry.py` | `SkillRegistry.expand()` | L58 | Expansion entry point (verifies synthetic imports work) |
| `rlm_adk/orchestrator.py` | Side-effect imports | L286-287 | Where to add the new import for auto-registration |
| `rlm_adk/orchestrator.py` | `repl.globals["LLMResult"] = LLMResult` | L246 | LLMResult availability in REPL namespace |
| `rlm_adk/dispatch.py` | `DispatchConfig.__init__` | L148-156 | `pool_size` default (5) for worker count reference |
| `rlm_adk/dispatch.py` | `llm_query_batched_async` | L695 | Batched dispatch implementation (what `llm_query_batched()` calls after AST rewrite) |
| `rlm_adk/types.py` | `LLMResult` | L95-128 | Result type with `.wall_time_ms`, `.error`, `.error_category` |
| `rlm_adk/skills/repl_skills/__init__.py` | Module docstring | L1 | Package init (no changes needed) |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow the "Skills & Prompts" branch link for this task)
3. `rlm_adk/skills/repl_skills/ping.py` -- the template skill to mirror
