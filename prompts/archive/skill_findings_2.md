Deviations from Plan

  Justified deviations:

  1. Export names changed (Step 1): Plan used _repomix_imports, _make_config, _is_remote. Implementation uses repomix_imports, rmx_make_config, rmx_is_remote. Reason: LocalREPL's
  _execute_code_inner filters out names starting with _ when persisting to self.locals. Underscore-prefixed exports would silently vanish between REPL calls, causing NameError at runtime.
  This was discovered during testing and is the correct fix.
  2. Auto-expansion mechanism (Step 6): Plan said "prepend synthetic imports to code." Implementation uses exec(compile(...), self.repl.globals) per module. Reason: Three issues forced this:
    - Prepending to user code caused has_llm_calls() to detect llm_query() inside expanded function definitions, incorrectly routing all first code blocks through async execution
    - Using repl.execute_code() created throwaway combined dicts, so function __globals__ couldn't find sibling helpers
    - A single expansion blob meant any module failure (e.g. missing repomix) would block all others
  3. BaseToolset migration deferred (Step 7): Kept RLMSkillToolset as BaseTool. Reason: Testing showed the BaseToolset migration wasn't the cause of test failures, but it adds risk by
  changing how ADK resolves tool declarations. Orthogonal to the core goal.

  Gaps to address:

  1. Step 11 fixture (skill_toolset_load_skill.json) was not created — no e2e coverage of the load_skill path. This should be built as a follow-up.
  2. REPLTool accesses _registry._exports directly instead of using the build_auto_import_lines() public API from Step 5. A SkillRegistry.iter_modules() method would be cleaner.

  The core architectural goal — one consistent source-expansion pattern for ALL skills — was achieved correctly, and the deviations were driven by real runtime issues discovered during
  testing.

✻ Sautéed for 2m 38s

❯ delegate an agent to use deep-wiki to unearth skill registry pattern in google-adk python.  How do we diverge? Is there a good reason that we diverge?                                      


  
  Where we align with upstream

  - Same Skill model (Skill(frontmatter, instructions, resources)) from google.adk.skills.models
  - Same XML discovery format via format_skills_as_xml() from google.adk.skills.prompt
  - Same L1/L2 layering — lightweight discovery XML, then full instructions on demand

  Where we diverge (6 divergences found)

  ┌───────────────────────┬───────────────────────────────────────────┬─────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
  │      Divergence       │            Upstream ADK 1.25.0            │                       RLM-ADK                       │                         Justified?                         │
  ├───────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │                       │ SkillToolset(BaseToolset) with            │                                                     │ Yes — RLM skills have no L3 resources                      │
  │ Base class            │ LoadSkillTool + LoadSkillResourceTool     │ RLMSkillToolset(BaseTool) — single tool             │ (references/assets/scripts), so the extra tools would be   │
  │                       │                                           │                                                     │ dead weight                                                │
  ├───────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ State tracking        │ None — upstream LoadSkillTool.run_async   │ Writes skill_last_loaded, skill_load_count,         │ Yes — feeds sqlite_tracing, dashboard, replay debugging    │
  │                       │ just returns instructions                 │ skill_loaded_names to tool_context.state            │                                                            │
  ├───────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Dual instruction      │ Only process_llm_request at runtime       │ process_llm_request L1 XML + static_instruction     │ Yes — REPL code examples must be in system instruction     │
  │ injection             │                                           │ with full usage examples at agent creation          │ from the start, before any load_skill call                 │
  ├───────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Source-expandable     │ Nothing equivalent (only                  │ Full SkillRegistry with topo-sorted source          │ Yes — this is the core architectural innovation; makes     │
  │ REPL skills           │ RunSkillScriptTool for one-shot scripts)  │ expansion into persistent REPL namespace            │ skills part of the REPL's accumulated symbolic context     │
  ├───────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Catalog/registry      │ Plain list[Skill] passed to constructor   │ PROMPT_SKILL_REGISTRY coordinating 3 injection      │ Yes — necessary to coordinate the three injection          │
  │ pattern               │                                           │ paths (prompt, tool discovery, REPL expansion)      │ mechanisms                                                 │
  ├───────────────────────┼───────────────────────────────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Stale docstring       │ Upstream does ship SkillToolset as of     │ Comment says "upstream doesn't ship one yet"        │ Stale — should be updated                                  │
  │                       │ 1.25.0                                    │                                                     │                                                            │
  └───────────────────────┴───────────────────────────────────────────┴─────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

  Bottom line

  Every divergence except the stale docstring has a clear architectural reason. The SkillRegistry source-expansion system has no upstream equivalent at all — it's the mechanism that makes
  skills executable inside the REPL rather than just instructions for the model. Adopting upstream's SkillToolset directly would lose state tracking, REPL integration, and dual injection —
  all load-bearing in this architecture.

  One actionable fix: update skill_toolset.py line 3 — the claim "upstream doesn't ship one yet" is false as of ADK 1.25.0.