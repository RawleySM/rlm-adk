# Add `worker-health` Source-Expandable REPL Skill

## Goal

Create a new source-expandable REPL skill called `worker-health` that dispatches a simple probe query to each worker in the pool, measures per-worker round-trip latency, and reports a structured health check result (latency per worker, pass/fail status, any errors). Place it alongside the existing `ping` skill in the `repl_skills/` directory.

The skill must be automatically discovered by both the source-expansion skill registry (so the model can `from rlm_repl_skills.worker_health import run_worker_health`) and the prompt-visible skill catalog (so the reasoning agent sees it in `<available_skills>` XML).

## Context: How the Existing Ping Skill Works

Read these files for the pattern to follow:

- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repl_skills/ping.py` -- the existing source-expandable REPL skill (6 `ReplSkillExport` entries under `rlm_repl_skills.ping`, registered at import time via `register_skill_export()`)
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/skill_registry.py` -- the `SkillRegistry` singleton, `ReplSkillExport` dataclass, `register_skill_export()` API, and `expand_skill_imports()` entry point
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/polya_narrative_skill.py` -- example of dual registration: both an ADK `Skill` object (prompt-visible) AND source-expandable `ReplSkillExport` entries. This is the pattern to follow for worker-health since the skill calls `llm_query()`.
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py` -- the `PROMPT_SKILL_REGISTRY` dict and `PromptSkillRegistration` dataclass. Adding an entry here is what makes a skill appear in the reasoning agent's prompt.

## Detailed Steps

### Step 1: Create the Skill File

Create `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repl_skills/worker_health.py`.

Follow the dual-registration pattern from `polya_narrative_skill.py`:

**Part A -- ADK Skill definition (prompt discovery):**

Define a `WORKER_HEALTH_SKILL` using `google.adk.skills.models.Skill` with `Frontmatter`:
- `name`: `"worker-health"` (kebab-case, per convention)
- `description`: Concise explanation that this skill dispatches probe queries to each worker in the pool and reports per-worker latency and health status
- `instructions`: Markdown block explaining usage (`from rlm_repl_skills.worker_health import run_worker_health`)

Define a `build_worker_health_skill_instruction_block()` function that returns the XML discovery block + instructions text, following the exact pattern at `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/polya_narrative_skill.py` lines 108-115:
```python
def build_worker_health_skill_instruction_block() -> str:
    from google.adk.skills.prompt import format_skills_as_xml
    discovery_xml = format_skills_as_xml([WORKER_HEALTH_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{WORKER_HEALTH_SKILL.instructions}"
```

**Part B -- Source-expandable REPL exports:**

Register `ReplSkillExport` entries under the synthetic module `rlm_repl_skills.worker_health`. The skill needs `llm_query()` calls (to dispatch probe queries to workers), so source expansion is required (the AST rewriter must see the `llm_query()` calls).

Minimum exports to register:

| Symbol | Kind | Dependencies | Purpose |
|--------|------|-------------|---------|
| `WORKER_HEALTH_PROBE_PROMPT` | const | -- | The simple prompt string sent to each worker (e.g., `"Respond with exactly: HEALTHY"`) |
| `WorkerHealthResult` | class | -- | Result container: `worker_count`, `results` (list of per-worker dicts with `worker_idx`, `latency_ms`, `healthy`, `response`, `error`), `all_healthy`, `summary` |
| `run_worker_health` | function | `WORKER_HEALTH_PROBE_PROMPT`, `WorkerHealthResult` | Main entry point: dispatches probe queries via `llm_query_batched()`, measures latency, builds result |

The `run_worker_health` function source should:
1. Accept `worker_count` parameter (default 3 or use pool_size) and optional `probe_prompt` override
2. Build a list of identical probe prompts (one per worker)
3. Record `time.time()` before and after each dispatch
4. Call `llm_query_batched(prompts)` to fan out to all workers concurrently
5. For each response, check whether it contains the expected "HEALTHY" token and record latency
6. Return a `WorkerHealthResult` with per-worker details and an `all_healthy` boolean
7. Include `emit_debug` parameter (default `True`) with `print()` calls for debug logging, matching the ping skill's pattern

**Important:** The expanded source may reference `llm_query_batched` (not `llm_query_batched_async`) because the AST rewriter transforms the sync call to async. Follow the same pattern as `run_recursive_ping` which calls `llm_query()` (sync form). For batched dispatch, use `llm_query_batched(prompts)`.

### Step 2: Register in the Prompt Skill Catalog

Edit `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py`:

1. Add an import at the top (around lines 10-21) for the new skill:
   ```python
   from rlm_adk.skills.repl_skills.worker_health import (
       WORKER_HEALTH_SKILL,
       build_worker_health_skill_instruction_block,
   )
   ```

2. Add an entry to the `PROMPT_SKILL_REGISTRY` dict (around lines 40-53):
   ```python
   WORKER_HEALTH_SKILL.frontmatter.name: PromptSkillRegistration(
       skill=WORKER_HEALTH_SKILL,
       build_instruction_block=build_worker_health_skill_instruction_block,
   ),
   ```

This is sufficient for automatic pickup. The `DEFAULT_ENABLED_SKILL_NAMES` tuple at line 55 is derived from `PROMPT_SKILL_REGISTRY.keys()`, so the new skill will be enabled by default. The `build_enabled_skill_instruction_blocks()` function (line 71) iterates over enabled skills, so the instruction block will be appended to the reasoning agent's `static_instruction` automatically. No changes to `agent.py` are needed.

### Step 3: Register the Side-Effect Import in the Orchestrator

Edit `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` at line 287 (the block of side-effect imports that trigger skill registration):

```python
# Register expandable REPL skill modules (side-effect imports)
import rlm_adk.skills.polya_narrative_skill  # noqa: F401
import rlm_adk.skills.repl_skills.ping  # noqa: F401
import rlm_adk.skills.repl_skills.worker_health  # noqa: F401  # <-- ADD THIS
```

This ensures the `register_skill_export()` calls in `worker_health.py` execute before any REPL code tries to expand the synthetic import.

### Step 4: Export from the Skills Package

Edit `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/__init__.py`:

1. Add import (around lines 10-13):
   ```python
   from rlm_adk.skills.repl_skills.worker_health import WORKER_HEALTH_SKILL
   ```

2. Add to `__all__` list (around lines 15-27):
   ```python
   "WORKER_HEALTH_SKILL",
   ```

### Step 5: Write Tests

Create `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_worker_health_skill.py` with at minimum:

1. **Registry test**: Verify that importing `rlm_adk.skills.repl_skills.worker_health` registers exports under `rlm_repl_skills.worker_health` in the skill registry singleton.

2. **Expansion test**: Verify that `expand_skill_imports('from rlm_repl_skills.worker_health import run_worker_health')` produces `ExpandedSkillCode` with `did_expand=True` and all transitive dependencies inlined.

3. **Catalog test**: Verify that `"worker-health"` appears in `PROMPT_SKILL_REGISTRY` and in `DEFAULT_ENABLED_SKILL_NAMES`.

4. **Result class test**: Verify `WorkerHealthResult` can be constructed with sample data and its `all_healthy` property works correctly.

Follow the existing test patterns. Run tests with:
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_worker_health_skill.py -x -q
```

Then verify no regressions in the default suite:
```bash
.venv/bin/python -m pytest tests_rlm_adk/
```

## Files to Create

| File | Purpose |
|------|---------|
| `rlm_adk/skills/repl_skills/worker_health.py` | Skill definition + source-expandable REPL exports |
| `tests_rlm_adk/test_worker_health_skill.py` | Unit tests for registry, expansion, catalog, result class |

## Files to Edit

| File | Change |
|------|--------|
| `rlm_adk/skills/catalog.py` (lines 10-21, 40-53) | Import `WORKER_HEALTH_SKILL` + `build_worker_health_skill_instruction_block`, add entry to `PROMPT_SKILL_REGISTRY` |
| `rlm_adk/orchestrator.py` (line 287) | Add side-effect import `import rlm_adk.skills.repl_skills.worker_health` |
| `rlm_adk/skills/__init__.py` (lines 10-13, 15-27) | Import and export `WORKER_HEALTH_SKILL` |

## Constraints

- The skill implementation source strings must call `llm_query_batched()` (sync form), NOT `llm_query_batched_async()`. The AST rewriter handles the sync-to-async transformation.
- All `ReplSkillExport.source` strings must be valid standalone Python when inlined at module level in the REPL.
- The expanded source may assume these REPL globals exist: `llm_query`, `llm_query_batched`, `LLMResult`, `print`, standard builtins.
- Follow AR-CRIT-001: no `ctx.session.state[key] = value` writes anywhere.
- Do NOT run `pytest -m ""` (full 970+ test suite). Use the default suite only.
