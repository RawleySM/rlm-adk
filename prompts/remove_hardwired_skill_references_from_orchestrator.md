<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Remove Hardwired Skill References from Orchestrator

## Context

The orchestrator (`rlm_adk/orchestrator.py`) hardwires three categories of skill activation directly in `_run_async_impl()`: (1) repomix helper function imports + `repl.globals` injection (lines 279-283), (2) polya_narrative_skill side-effect import (line 286), and (3) ping skill side-effect import (line 287). These should be driven by the skill catalog/registry system (`rlm_adk/skills/catalog.py`) the same way prompt-visible skill instruction blocks are already driven by `build_enabled_skill_instruction_blocks()`. The polya-understand skill proved out this catalog-driven pattern — apply it uniformly so no individual skill functions or modules are referenced by name in the orchestrator.

## Original Transcription

> Remove the hardwired repo mix skill references throughout the codebase specifically in orchestrator.py. I'm seeing them These should not be hardwired in the imports. They should be, part of the, skill registry that is imported in the same way that the narrative skill are imported. I don't wanna see specific, ripple skills, skill functions added, individually, they should be enabled with our enabling skill tool or function that was I think, proven out by the understand Poya skill.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Catalog-Ext` teammate to extend `PromptSkillRegistration` in `rlm_adk/skills/catalog.py` (line 25) with two optional fields for runtime activation.**

   Add to the `PromptSkillRegistration` dataclass:
   - `repl_globals_factory: Callable[[], dict[str, Any]] | None = None` — when not None, returns a `{name: callable}` dict to inject into `repl.globals`.
   - `side_effect_modules: tuple[str, ...] = ()` — module paths to import at orchestrator startup (triggers `register_skill_export()` side effects for source-expandable skills).

   Add two new catalog functions that mirror the existing `build_enabled_skill_instruction_blocks()` pattern:
   - `collect_repl_globals(enabled_skills) -> dict[str, Any]` — iterates enabled skills, calls each `repl_globals_factory`, merges results into a single dict.
   - `activate_side_effect_modules(enabled_skills) -> list[str]` — iterates enabled skills, imports each module in `side_effect_modules`, returns list of imported module paths for logging.

   **Constraint:** These functions must respect the same `enabled_skills` filtering as `build_enabled_skill_instruction_blocks()` — disabled skills must not inject globals or trigger side-effect imports.

2. **Spawn a `Skill-Reg` teammate to register the runtime activation metadata on each existing skill in `rlm_adk/skills/catalog.py` (lines 40-53).**

   Update the three entries in `PROMPT_SKILL_REGISTRY`:
   - `repomix-repl-helpers`: Set `repl_globals_factory` to a callable that returns `{"probe_repo": probe_repo, "pack_repo": pack_repo, "shard_repo": shard_repo}` (importing from `rlm_adk.skills.repomix_helpers`). No `side_effect_modules`.
   - `polya-understand`: No `repl_globals_factory`. Set `side_effect_modules=("rlm_adk.skills.polya_understand",)` since it registers source-expandable exports at import time.
   - `polya-narrative`: No `repl_globals_factory`. Set `side_effect_modules=("rlm_adk.skills.polya_narrative_skill",)` since it registers source-expandable exports at import time.

   *[Added — the transcription didn't mention the ping skill, but `rlm_adk/skills/repl_skills/ping.py` is also hardwired as a side-effect import at orchestrator.py line 287. It needs a catalog entry or must be folded into an existing skill's `side_effect_modules`. Since ping is a standalone REPL skill module, add a new `PROMPT_SKILL_REGISTRY` entry for it or attach it to an existing skill as appropriate. Discuss with the user if uncertain whether ping warrants its own catalog entry or should be always-on.]*

3. **Spawn a `Orch-Cleanup` teammate to replace the hardwired skill references in `rlm_adk/orchestrator.py` `_run_async_impl()` (lines 278-287) with catalog-driven calls.**

   Remove these lines:
   ```python
   # line 279
   from rlm_adk.skills.repomix_helpers import pack_repo, probe_repo, shard_repo
   # lines 281-283
   repl.globals["probe_repo"] = probe_repo
   repl.globals["pack_repo"] = pack_repo
   repl.globals["shard_repo"] = shard_repo
   # lines 286-287
   import rlm_adk.skills.polya_narrative_skill  # noqa: F401
   import rlm_adk.skills.repl_skills.ping  # noqa: F401
   ```

   Replace with:
   ```python
   from rlm_adk.skills.catalog import activate_side_effect_modules, collect_repl_globals
   repl.globals.update(collect_repl_globals(self.enabled_skills))
   activate_side_effect_modules(self.enabled_skills)
   ```

   The orchestrator must not import any skill module by name. All skill activation flows through `self.enabled_skills` → catalog functions.

   **Constraint:** `repl.globals["LLMResult"] = LLMResult` (line 246) and `repl.globals["user_ctx"]` (lines 377, 421) are NOT skills — they are core runtime globals. Leave them untouched.

4. **Spawn a `Flag-Rename` teammate to rename the `include_repomix` parameter in `create_reasoning_agent()` (`rlm_adk/agent.py` line 204) to `include_skills`.**

   The parameter name `include_repomix` is a vestige of when repomix was the only skill. It now controls whether ANY skill instruction blocks are appended to `static_instruction` (line 253). Rename to `include_skills` (or `include_skill_instructions`) throughout:
   - `create_reasoning_agent()` signature (line 204)
   - The `if include_repomix:` guard (line 253)
   - `create_child_orchestrator()` call site (line 369: `include_repomix=False` → `include_skills=False`)

   **Constraint:** Do not change the behavior. Children still get `include_skills=False`. This is a rename only.

5. **Spawn a `Test-Guard` teammate to verify the refactor didn't break existing behavior.**

   Run the default test suite (`.venv/bin/python -m pytest tests_rlm_adk/ -x -q`) and confirm all ~28 contract tests pass. Then write targeted tests for the new catalog functions:
   - `collect_repl_globals(None)` returns a dict containing `probe_repo`, `pack_repo`, `shard_repo`.
   - `collect_repl_globals(("polya-understand",))` returns an empty dict (no repomix globals).
   - `activate_side_effect_modules(None)` triggers side-effect imports without error.
   - `activate_side_effect_modules(("repomix-repl-helpers",))` does NOT import polya skill modules.

## Provider-Fake Fixture & TDD

**Fixture:** Existing fixtures in `tests_rlm_adk/fixtures/provider_fake/` should continue passing unchanged — this refactor is internal wiring, not behavior change.

**Essential requirements the tests must capture:**
- `collect_repl_globals()` returns exactly the expected callable names per enabled skill set — not more, not fewer. This prevents a skill's globals from "leaking" when it's disabled.
- `activate_side_effect_modules()` with a restricted skill set must NOT trigger side-effect imports for excluded skills. Verify by checking `SkillRegistry._exports` before and after.
- The full orchestrator pipeline still works end-to-end: run the default contract suite to confirm no regression.

**TDD sequence:**
1. Red: Write test asserting `collect_repl_globals(("polya-understand",))` has no `probe_repo` key. Run, confirm failure (function doesn't exist yet).
2. Green: Implement `collect_repl_globals()` in `catalog.py`. Run, confirm pass.
3. Red: Write test asserting `activate_side_effect_modules(("repomix-repl-helpers",))` does not register polya exports in `SkillRegistry`. Run, confirm failure.
4. Green: Implement `activate_side_effect_modules()`. Run, confirm pass.
5. Green: Run full default suite to confirm no regression.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the catalog-driven activation works end-to-end.

## Considerations

- **AR-CRIT-001 compliance:** This refactor does not touch state mutation paths. The `repl.globals` injection happens before the event loop — no dispatch closure or state key concerns.
- **Import ordering:** `activate_side_effect_modules()` must run BEFORE `REPLTool` is created, because REPLTool calls `expand_skill_imports()` which reads from the `SkillRegistry` populated by those side-effect imports. The current ordering in orchestrator.py already has the imports before REPLTool creation (line 290) — preserve this.
- **Lazy imports in catalog.py:** The `repl_globals_factory` for repomix should use a lazy import pattern (import inside the callable) to avoid pulling `repomix` at catalog import time — repomix is a heavy dependency. Current code uses a local import at line 279 of orchestrator.py for the same reason.
- **Ping skill registration:** The ping skill (`rlm_adk/skills/repl_skills/ping.py`) registers source-expandable exports but has no ADK `Skill` object or instruction block. Create a minimal `PING_SKILL` with `Frontmatter` and add it to the catalog.  

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/orchestrator.py` | `_run_async_impl` | L227 | Contains the hardwired skill imports to remove |
| `rlm_adk/orchestrator.py` | `from rlm_adk.skills.repomix_helpers import ...` | L279 | Hardwired repomix import |
| `rlm_adk/orchestrator.py` | `repl.globals["probe_repo"] = ...` | L281-283 | Hardwired globals injection |
| `rlm_adk/orchestrator.py` | `import rlm_adk.skills.polya_narrative_skill` | L286 | Hardwired side-effect import |
| `rlm_adk/orchestrator.py` | `import rlm_adk.skills.repl_skills.ping` | L287 | Hardwired side-effect import |
| `rlm_adk/skills/catalog.py` | `PromptSkillRegistration` | L25 | Dataclass to extend with runtime fields |
| `rlm_adk/skills/catalog.py` | `PROMPT_SKILL_REGISTRY` | L40 | Registry dict to update with new fields |
| `rlm_adk/skills/catalog.py` | `build_enabled_skill_instruction_blocks` | L71 | Pattern to follow for new functions |
| `rlm_adk/skills/catalog.py` | `normalize_enabled_skill_names` | L58 | Skill filtering function (reuse in new functions) |
| `rlm_adk/agent.py` | `create_reasoning_agent` | L195 | `include_repomix` parameter to rename |
| `rlm_adk/agent.py` | `if include_repomix:` | L253 | Guard clause to rename |
| `rlm_adk/agent.py` | `include_repomix=False` | L369 | Child orchestrator call site |
| `rlm_adk/repl/skill_registry.py` | `SkillRegistry` | L32 | Source expansion registry (populated by side-effect imports) |
| `rlm_adk/repl/skill_registry.py` | `register_skill_export` | L219 | Called by side-effect imports |
| `rlm_adk/skills/repomix_helpers.py` | `probe_repo`, `pack_repo`, `shard_repo` | L75, L102, L121 | Functions currently hardwired into repl.globals |
| `rlm_adk/skills/repomix_skill.py` | `REPOMIX_SKILL` | L16 | ADK Skill object for repomix |
| `rlm_adk/skills/polya_narrative_skill.py` | `POLYA_NARRATIVE_SKILL` | - | ADK Skill object + source-expandable exports |
| `rlm_adk/skills/polya_understand.py` | `POLYA_UNDERSTAND_SKILL` | L36 | ADK Skill object + source-expandable exports |
| `rlm_adk/skills/repl_skills/ping.py` | `register_skill_export` calls | - | Source-expandable exports (no ADK Skill object) |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow Skills & Prompts branch)
3. `rlm_adk_docs/skills_and_prompts.md` — full skill system documentation
