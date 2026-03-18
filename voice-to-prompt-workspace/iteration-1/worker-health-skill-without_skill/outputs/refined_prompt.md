# Add Worker Pool Health Check REPL Skill

## Goal

Create a new source-expandable REPL skill called `worker_health` that dispatches a simple probe query to each worker in the pool, measures round-trip latency per worker, and reports whether each worker responded successfully. Place it alongside the existing ping skill in `rlm_adk/skills/repl_skills/`. The skill must auto-register with the `SkillRegistry` singleton at import time so the orchestrator picks it up with a single side-effect import -- no manual catalog or prompt-injection wiring required.

## Context: How Source-Expandable REPL Skills Work

Source-expandable skills use the `SkillRegistry` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/skill_registry.py`. Each skill module registers `ReplSkillExport` entries at import time via `register_skill_export()`. When the reasoning agent writes `from rlm_repl_skills.<module> import <symbol>` inside an `execute_code` block, the `REPLTool` intercepts the synthetic import and inlines the source (topologically sorted by `requires`) before AST rewriting. This makes any `llm_query()` calls inside the expanded source visible to the sync-to-async AST rewriter.

The existing ping skill at `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repl_skills/ping.py` is the canonical example to follow.

## Detailed Steps

### Step 1: Create the skill module

Create a new file at `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repl_skills/worker_health.py`.

Follow the exact pattern from `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repl_skills/ping.py`:

1. **Define source-code string constants** for each exportable symbol. The skill needs:

   - `WorkerHealthResult` (class) -- A result container dataclass/class holding:
     - `pool_size: int` -- number of workers probed
     - `results: list[dict]` -- per-worker dicts with keys `worker_index`, `latency_ms`, `success`, `response_preview`, `error`
     - `healthy_count: int` -- count of workers that responded successfully
     - `total_latency_ms: float` -- sum of all latencies
     - `all_healthy: bool` -- True if every worker succeeded
     - `debug_log: list[str]` -- debug messages (when `emit_debug=True`)
     - A `__repr__` method summarizing the result

   - `HEALTH_CHECK_PROMPT` (const) -- A simple prompt string for the health probe, e.g. `"Respond with exactly: HEALTHY"`. Keep it minimal to minimize latency/cost.

   - `run_worker_health_check` (function) -- The main entry point. Signature:
     ```python
     def run_worker_health_check(
         pool_size=3,
         prompt=None,
         emit_debug=True,
     ):
     ```
     This function must:
     - Default `prompt` to `HEALTH_CHECK_PROMPT` if not provided
     - Build a list of `pool_size` identical prompts
     - Call `llm_query_batched(prompts)` to dispatch all probes concurrently (this is why source expansion is needed -- `llm_query_batched` must be visible to the AST rewriter)
     - Measure wall-clock latency for the entire batch (individual per-worker latency is not available from `llm_query_batched`, so report the batch latency divided by pool_size as an approximation, or report total batch latency)
     - Inspect each result: check for errors (`.error` attribute on `LLMResult`), record `success`, `latency_ms`, `response_preview` (first 100 chars), and `error` (error message if any)
     - Return a `WorkerHealthResult`

2. **Register each symbol** via `register_skill_export(ReplSkillExport(...))` calls at module level (side-effect at import time). Use the synthetic module path `rlm_repl_skills.worker_health`.

   The dependency graph should be:
   ```
   HEALTH_CHECK_PROMPT (const, requires=[])
   WorkerHealthResult  (class, requires=[])
   run_worker_health_check (function, requires=["WorkerHealthResult", "HEALTH_CHECK_PROMPT"])
   ```

### Step 2: Register the side-effect import in the orchestrator

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`, add a side-effect import alongside the existing ping import at line 287:

```python
import rlm_adk.skills.repl_skills.ping  # noqa: F401  (existing)
import rlm_adk.skills.repl_skills.worker_health  # noqa: F401  (new)
```

This is the **only wiring needed** for the skill registry to pick it up. When the orchestrator imports this module, `register_skill_export()` fires for each `ReplSkillExport`, populating the `_registry` singleton in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/skill_registry.py` (line 216). The `REPLTool` then calls `expand_skill_imports()` (line 223-224) when it encounters a `from rlm_repl_skills.worker_health import ...` statement in submitted code.

### Step 3: Verify auto-discovery

No changes are needed to:
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/skill_registry.py` -- The `SkillRegistry` singleton is module-global and registration happens at import time
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py` -- The catalog is for **prompt-visible** skills (ADK `Skill` objects with `Frontmatter` that get injected into `static_instruction`). Source-expandable REPL skills do NOT need catalog entries; they are invoked by the model writing synthetic imports
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/__init__.py` -- No exports needed for source-expandable skills
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` -- No changes; skill wiring happens in the orchestrator

### Step 4: Write a unit test

Create a test file at `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_worker_health_skill.py` that verifies:

1. **Registration test**: Import `rlm_adk.skills.repl_skills.worker_health`, then call `expand_skill_imports('from rlm_repl_skills.worker_health import run_worker_health_check')` and assert:
   - `result.did_expand is True`
   - `"run_worker_health_check"` is in `result.expanded_symbols`
   - `"WorkerHealthResult"` is in `result.expanded_symbols`
   - `"HEALTH_CHECK_PROMPT"` is in `result.expanded_symbols`
   - The expanded code contains the function definition text

2. **Dependency resolution test**: Verify that importing only `run_worker_health_check` transitively pulls in `WorkerHealthResult` and `HEALTH_CHECK_PROMPT` (the `requires` field).

3. **Source validity test**: Verify the expanded source parses as valid Python (`ast.parse(result.expanded_code)` does not raise).

Use the existing test infrastructure: `.venv/bin/python -m pytest tests_rlm_adk/test_worker_health_skill.py -x -q`

## Key Constraints

- **Source expansion required**: The skill calls `llm_query_batched()`, which must be visible to the AST rewriter (see `/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/skills_and_prompts.md`, Section 9 "When to Choose Expansion vs repl.globals"). This means it MUST be a source-expandable skill, not a `repl.globals` injection.
- **AR-CRIT-001**: The expanded skill source runs inside the REPL. It must not write to `ctx.session.state` directly. It can freely use `llm_query_batched()` (which the AST rewriter transforms to `await llm_query_batched_async()`) and `print()`.
- **No prompt injection needed**: This is a utility skill invoked on-demand via synthetic import, not a prompt-visible skill. It does NOT need an ADK `Skill` object, `Frontmatter`, or catalog registration.
- **Synthetic module path**: Must use `rlm_repl_skills.worker_health` to match the `rlm_repl_skills.*` prefix that the skill registry intercepts (see `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/skill_registry.py`, line 70).

## Usage (after implementation)

The reasoning agent would invoke this skill by writing:

```python
from rlm_repl_skills.worker_health import run_worker_health_check

result = run_worker_health_check(pool_size=3)
print(f"Healthy: {result.healthy_count}/{result.pool_size}")
print(f"All healthy: {result.all_healthy}")
for r in result.results:
    print(f"  Worker {r['worker_index']}: {'OK' if r['success'] else 'FAIL'} ({r['latency_ms']:.0f}ms)")
```

## Files to Create

| File | Purpose |
|------|---------|
| `rlm_adk/skills/repl_skills/worker_health.py` | Skill module with source constants + `register_skill_export()` calls |
| `tests_rlm_adk/test_worker_health_skill.py` | Unit tests for registration, dependency resolution, source validity |

## Files to Modify

| File | Line(s) | Change |
|------|---------|--------|
| `rlm_adk/orchestrator.py` | 287 (after existing ping import) | Add `import rlm_adk.skills.repl_skills.worker_health  # noqa: F401` |

## Verification

```bash
# Run the new test
.venv/bin/python -m pytest tests_rlm_adk/test_worker_health_skill.py -x -q

# Run the default test suite to check for regressions
.venv/bin/python -m pytest tests_rlm_adk/

# Lint
ruff check rlm_adk/skills/repl_skills/worker_health.py tests_rlm_adk/test_worker_health_skill.py
ruff format --check rlm_adk/skills/repl_skills/worker_health.py tests_rlm_adk/test_worker_health_skill.py
```
