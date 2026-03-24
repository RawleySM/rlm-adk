  ---
  Skill Registry & REPL Import Review — Unified Analysis

  Architecture as-is: Three Planes

  The skill system operates across three distinct planes that evolved somewhat independently:

  ┌────────────────┬────────────────────────────────────────┬───────────────────────────────────────┬─────────────────────────────────┐
  │     Plane      │                  What                  │                 Where                 │              When               │
  ├────────────────┼────────────────────────────────────────┼───────────────────────────────────────┼─────────────────────────────────┤
  │ A: Prompt      │ L1 XML discovery + L2 instruction text │ RLMSkillToolset.process_llm_request() │ Every model call (depth 0 only) │
  ├────────────────┼────────────────────────────────────────┼───────────────────────────────────────┼─────────────────────────────────┤
  │ B: Tool-Load   │ load_skill returns L2 instructions     │ RLMSkillToolset.run_async()           │ On model demand                 │
  ├────────────────┼────────────────────────────────────────┼───────────────────────────────────────┼─────────────────────────────────┤
  │ C: REPL Source │ Python source-string expansion         │ SkillRegistry + REPLTool auto-expand  │ First execute_code call         │
  └────────────────┴────────────────────────────────────────┴───────────────────────────────────────┴─────────────────────────────────┘

  ---
  Key Findings

  1. Upstream ADK features RLM-ADK isn't using

  The ADK Skills Expert found significant upstream surface area being bypassed:
  - SkillToolset(BaseToolset) — upstream provides list_skills, load_skill, load_skill_resource, and dynamic adk_additional_tools resolution. RLM-ADK reimplements a subset as a single BaseTool, missing list_skills, load_skill_resource, and dynamic tool gating.
  - Skill.resources (L3) — completely unused. Phase-instruction constants stored as Python string constants could live as Resources(references={...}) and be browsable via load_skill_resource.
  - adk_additional_tools metadata — the mechanism by which skill activation unlocks new ADK tools at runtime. Not wired.
  - format_skills_as_xml() from google.adk.skills.prompt — exists upstream but RLM-ADK rolls its own XML formatting.

  2. Plane A is disconnected

  The Skills README documents build_enabled_skill_instruction_blocks() appended to static_instruction in create_reasoning_agent(), but this call does not exist in current agent.py. The static instruction (RLM_STATIC_INSTRUCTION) only mentions "Use the load_skill tool" — meaning L2 content arrives only through process_llm_request() and the load_skill tool, not the static prompt. The README describes intended state, not actual wiring.

  3. Double-definition via Path A + Path B in REPL

  The Callbacks Expert identified that skill functions get defined twice: once via auto-expansion into repl.globals (Path A on first execute_code), and again if the model explicitly writes from rlm_repl_skills.* import * (Path B inlines source into the code block). Harmless but wasteful.

  4. Private API coupling

  REPLTool accesses _registry._exports directly — a private dict. The public API is expand_skill_imports() and register_skill_export(), but auto-expansion bypasses the expansion API entirely to iterate the internal dict and exec source strings into globals.

  5. No skill visibility for children (depth > 0)

  RLMSkillToolset is wired only at depth 0. create_child_orchestrator() does not pass enabled_skills. Children have no L1 discovery, no load_skill, and their REPL does get auto-expanded functions (since _registry is process-global), but without any context about what those functions do.

  6. No before_agent_callback plugin for skill seeding

  Skill instruction seeding into state uses a dynamically constructed async closure installed via object.__setattr__ on the reasoning agent. The ADK Callbacks Expert recommends this be a BasePlugin.before_agent_callback instead — plugin-scoped, testable, and avoids single-slot callback clobbering.

  7. No validation at registration time

  Source strings in ReplSkillExport are never syntax-checked until REPL execution. A compile() call at register_skill_export() time would catch errors immediately.

  ---
  Recommendations (Prioritized)

  HIGH — Adopt upstream SkillToolset
  Replace RLMSkillToolset(BaseTool) with ADK's native SkillToolset(BaseToolset). Pass Skill objects from collect_skill_objects(). This gives list_skills, load_skill_resource, and adk_additional_tools dynamic resolution for free, and eliminates ~150 lines of custom reimplementation. The @experimental(default_on=True) decorator only fires a UserWarning once.

  HIGH — Expose SkillRegistry public API for auto-expansion
  Add a registry.all_exports() -> dict[str, dict[str, ReplSkillExport]] method. Have REPLTool call this instead of reading _registry._exports. This decouples the tool from registry internals.

  HIGH — Validate source at registration time
  In register_skill_export(), call compile(export.source, f"<skill:{module}.{name}>", "exec") and raise ValueError on failure. Fail fast instead of silently swallowing errors 30 seconds into a reasoning session.

  MEDIUM — Move skill seeding to a BasePlugin
  Extract the _seed_skill_instruction closure into a SkillSeedingPlugin(BasePlugin) with before_agent_callback. Testable in isolation, avoids object.__setattr__, and doesn't compete for the single agent-level callback slot.

  MEDIUM — Wire enabled_skills to children
  Pass enabled_skills through create_child_orchestrator(). Even without the full SkillToolset, children should at least receive compressed L1 context through the instruction router.

  MEDIUM — Eliminate auto-expansion redundancy
  The Intent Agent recommends making skill activation demand-driven. Rather than auto-expanding all registered skills into repl.globals on first call, consider lazy expansion — only inject when the model uses from rlm_repl_skills.* or after load_skill. This keeps the REPL namespace smaller and becomes important as the skill set grows.

  LOW — Use Skill.resources for large instruction constants
  Move phase-instruction source strings into Resources(references={"phase_instructions.md": "..."}). Makes them browsable via load_skill_resource and removes the awkwardness of storing Python source as multi-line string constants in skill files.

  VISION — Close the skill-promotion loop
  The Intent Agent identified the largest strategic gap: CLAUDE.md describes skills as "symbolic compressions of recurring patterns" that get promoted from execution traces, but there is no automated path from REPL execution → pattern recognition → skill candidacy → registration. The dynamic_skill_loading.md vision doc describes the embedding pipeline. The foundational step is a post-run indexer that writes repl_traces.json into a vector store for cross-run pattern
  detection.

  ---
  Architecture Summary (Current vs. Ideal)

  Current:
    process_llm_request() → L1 XML (depth 0 only, custom impl)
    load_skill tool call  → L2 instructions (duplicates nothing — Plane A disconnected)
    activate_side_effects → ALL REPL source registered at startup unconditionally
    from rlm_repl_skills. → source expansion inlines into REPL
    adk_additional_tools  → unused
    Skill.resources       → unused
    list_skills           → not registered
    depth > 0 children    → no skills

  Recommended:
    SkillToolset(upstream) → L1 XML (every request, upstream format_skills_as_xml)
    load_skill (upstream)  → L2 instructions on demand only
    load_skill_resource    → L3 references/assets on demand
    adk_additional_tools   → dynamic tool gating after skill activation
    SkillRegistry          → demand-driven expansion, public API, syntax validation
    SkillSeedingPlugin     → plugin-based before_agent seeding
    Children               → compressed L1 via instruction_router

