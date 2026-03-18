<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Add Worker Health Check REPL Skill

## Context

RLM-ADK needs a new source-expandable REPL skill that health-checks the child dispatch pipeline by sending simple queries to multiple workers concurrently via `llm_query_batched()` and reporting per-worker latency and response status. The skill follows the same registration pattern as the existing recursive ping skill (`rlm_adk/skills/repl_skills/ping.py`) and must be auto-discovered by the skill registry via a side-effect import in the orchestrator.

## Original Transcription

> I want to add a new skill, like a repl skill similar to the ping one but this one should do like a health check on the worker pool. It should dispatch a simple query to each worker and report back latency and whether they responded. Put it next to the ping skill I guess. And make sure the skill registry picks it up automatically.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Skill-Author` teammate to create the skill module at `rlm_adk/skills/repl_skills/worker_health.py`.** Follow the exact structure of `rlm_adk/skills/repl_skills/ping.py` (L1-211):
   - Import `ReplSkillExport` and `register_skill_export` from `rlm_adk.repl.skill_registry` (L219).
   - Define source strings as module-level constants (Python string literals containing the code that will be inlined into the REPL).
   - Call `register_skill_export()` at module level for each export, registering under the synthetic module `rlm_repl_skills.worker_health`.
   - Define these exports (minimum set):

   | Symbol | Kind | Dependencies | Purpose |
   |--------|------|-------------|---------|
   | `HEALTH_CHECK_PROMPT` | const | -- | Simple prompt string for the health check query (e.g., `"Respond with exactly: OK"`) |
   | `WorkerHealthResult` | class | -- | Result container: `worker_count: int`, `results: list[dict]` (each dict has `worker_idx`, `latency_ms`, `responded: bool`, `error_category: str | None`, `response_preview: str`), `all_healthy: bool`, `total_latency_ms: float`, `debug_log: list` |
   | `run_worker_health_check` | function | `HEALTH_CHECK_PROMPT`, `WorkerHealthResult` | Main entry point. Accepts `worker_count: int = 5`, `emit_debug: bool = True`. Dispatches `worker_count` identical simple prompts via `llm_query_batched()`, collects per-result latency and error status from `LLMResult` attributes, returns a `WorkerHealthResult` |

2. **Spawn a `Skill-Impl` teammate to implement the `run_worker_health_check` source string.** The function source must:
   - Build a list of `worker_count` copies of `HEALTH_CHECK_PROMPT`.
   - Call `llm_query_batched(prompts)` to dispatch all queries concurrently. Use `llm_query_batched()` (sync form) -- the AST rewriter in `rlm_adk/repl/ast_rewriter.py` (L132 `rewrite_for_async`) handles sync-to-async transformation.
   - For each `LLMResult` in the returned list, extract:
     - `wall_time_ms` (latency) -- `LLMResult.wall_time_ms` at `rlm_adk/types.py` L118
     - `error` (bool) -- `LLMResult.error` at `rlm_adk/types.py` L110
     - `error_category` (string category if error) -- `LLMResult.error_category` at `rlm_adk/types.py` L111
     - A preview of the response text (first 100 chars)
   - Compute `all_healthy = all(not r["error"] for r in per_worker_results)` and `total_latency_ms = max(latencies)` (wall-clock time for the batch, since workers run concurrently).
   - Include a `debug_log` list and `emit_debug` parameter (matching the ping skill pattern at `ping.py` L79) that prints status messages via `print()`.
   - The source may rely on `LLMResult` being available in REPL globals (injected at `rlm_adk/orchestrator.py` L246).

3. **Spawn a `Registry-Wire` teammate to register the side-effect import in `rlm_adk/orchestrator.py`.** Add the import at L288 (after the existing ping import at L287):
   ```python
   import rlm_adk.skills.repl_skills.worker_health  # noqa: F401
   ```
   This is the mechanism that triggers `register_skill_export()` calls at import time, making the skill available to the `SkillRegistry` singleton (`rlm_adk/repl/skill_registry.py` L216) for synthetic import expansion.

4. **Spawn a `Expansion-Test` teammate to add expansion tests in `tests_rlm_adk/test_worker_health_skill.py`.** Verify:
   - Importing `rlm_adk.skills.repl_skills.worker_health` registers the expected three symbols (`HEALTH_CHECK_PROMPT`, `WorkerHealthResult`, `run_worker_health_check`) in the skill registry.
   - `expand_skill_imports()` correctly expands `from rlm_repl_skills.worker_health import run_worker_health_check` into inline source containing all three symbols in topological order.
   - The expanded source is valid Python (parses with `ast.parse()`).
   - The expanded source contains `llm_query_batched(` (confirming the AST rewriter will find it).

5. *[Added -- the transcription did not mention a provider-fake fixture, but new behavioral skills need one for the contract test suite.]* **Spawn a `Fixture-Author` teammate to create a provider-fake fixture and contract test.** See the Provider-Fake Fixture & TDD section below.

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/worker_health_check.json`

**Essential requirements the fixture must capture:**

- The fixture must verify that the health check dispatches exactly N concurrent queries via `llm_query_batched()` (not N sequential `llm_query()` calls) -- the function call in the reasoning agent's code block must use `llm_query_batched`.
- The fixture must include at least one worker that returns an error response (e.g., a 500 or safety-blocked response), verifying the skill correctly reports partial failures in the `WorkerHealthResult.results` list with `responded=False` and a non-null `error_category`.
- The fixture must verify latency measurement comes from `LLMResult.wall_time_ms` (not hardcoded). Since the provider-fake server controls response timing, the fixture can assert that reported latency is non-zero.
- The fixture must verify `all_healthy` is `False` when any worker errors, and `True` when all succeed.

**TDD sequence:**

1. Red: Write a test importing `run_worker_health_check` via `expand_skill_imports()` and asserting the expanded source contains `llm_query_batched(` and `WorkerHealthResult`. Run, confirm failure (module does not exist yet).
2. Green: Create `worker_health.py` with all three exports. Run, confirm pass.
3. Red: Write a contract test using the `worker_health_check.json` fixture that asserts the reasoning agent dispatches a health check and the final output contains worker status information. Run, confirm failure (fixture does not exist yet).
4. Green: Create the fixture with canned responses (3 workers: 2 healthy, 1 error). Run, confirm pass.
5. Red: Write an assertion that the contract test output includes `all_healthy: False` (due to the error worker). Refine fixture/assertion until this passes.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the skill expansion and health check dispatch work end-to-end.

## Considerations

- **Source expansion, not `repl.globals` injection**: This skill uses `llm_query_batched()`, so it must be source-expandable (not injected via `repl.globals`). The AST rewriter (`rlm_adk/repl/ast_rewriter.py`) only operates on submitted code text -- functions in `repl.globals` that call `llm_query()` internally are invisible to the rewriter.

- **`DispatchConfig` is not directly accessible from REPL code**: The REPL environment does not have access to the `DispatchConfig` / `WorkerPool` object (`rlm_adk/dispatch.py` L145-164). The `worker_count` parameter should default to 5 (matching `DispatchConfig.__init__` default `pool_size=5` at L152) but the skill cannot dynamically read the actual pool size at runtime. This is acceptable for a health check -- the user can pass a different count if needed.

- **`LLMResult` attributes**: The expanded source can rely on `LLMResult` being available in REPL globals (injected at `rlm_adk/orchestrator.py` L246). The `wall_time_ms`, `error`, and `error_category` attributes are all public on `LLMResult` (`rlm_adk/types.py` L110-122).

- **AR-CRIT-001 compliance**: This skill only reads `LLMResult` attributes returned by `llm_query_batched()`. It does not write to session state. No state mutation concerns.

- **Topological sort**: Ensure the `requires` fields correctly express that `run_worker_health_check` depends on both `HEALTH_CHECK_PROMPT` and `WorkerHealthResult`. The `SkillRegistry._topo_sort` (L171) will inline constants and the class before the function.

- **Existing test suite**: Run `.venv/bin/python -m pytest tests_rlm_adk/` after implementation to verify no regressions. Do NOT run with `-m ""`.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/skills/repl_skills/ping.py` | Full module (template) | L1-211 | Template for new skill registration pattern |
| `rlm_adk/repl/skill_registry.py` | `ReplSkillExport` | L15 | Dataclass for skill export definition |
| `rlm_adk/repl/skill_registry.py` | `register_skill_export()` | L219 | Module-level registration API |
| `rlm_adk/repl/skill_registry.py` | `SkillRegistry.expand()` | L58 | Expansion entry point (verifies synthetic imports work) |
| `rlm_adk/repl/skill_registry.py` | `SkillRegistry._topo_sort()` | L171 | Topological sort for dependency ordering |
| `rlm_adk/repl/skill_registry.py` | `_registry` singleton | L216 | Module-level singleton instance |
| `rlm_adk/orchestrator.py` | Side-effect imports | L285-287 | Where to add the new import for auto-registration |
| `rlm_adk/orchestrator.py` | `repl.globals["LLMResult"]` | L246 | LLMResult availability in REPL namespace |
| `rlm_adk/dispatch.py` | `DispatchConfig.__init__` | L148-156 | `pool_size` default (5) for worker count reference |
| `rlm_adk/dispatch.py` | `llm_query_batched_async` | L695 | Batched dispatch implementation (what `llm_query_batched()` becomes after AST rewrite) |
| `rlm_adk/types.py` | `LLMResult` | L95-134 | Result type with `.wall_time_ms`, `.error`, `.error_category` |
| `rlm_adk/repl/ast_rewriter.py` | `rewrite_for_async()` | L132 | AST rewriter entry point (transforms `llm_query_batched` to async) |
| `rlm_adk/skills/repl_skills/__init__.py` | Package init | L1 | No changes needed |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow the "Skills & Prompts" branch link for this task)
3. `rlm_adk/skills/repl_skills/ping.py` -- the template skill to mirror
