<!-- validated: 2026-03-22 -->

# Skills & Prompt System

Reference for the RLM-ADK instruction pipeline: static instructions, dynamic instructions, the skill system, and how they flow into the reasoning agent.

---

## 1. Static Instruction (RLM_STATIC_INSTRUCTION)

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py`

The static instruction is the primary system prompt. It is passed as `LlmAgent(static_instruction=...)`, which ADK places into `system_instruction` **without template processing** -- raw curly braces in Python code examples are safe.

**Contents:**
- Tool descriptions (`execute_code`, `set_model_response`) with calling conventions
- REPL environment capabilities: `open()`, `__import__()`, `llm_query()`, `llm_query_batched()`, `SHOW_VARS()`, `print()`
- Data processing strategy examples (chunking, batching, recursive sub-LLM queries)
- Repository processing section directing the agent to use `probe_repo()`, `pack_repo()`, `shard_repo()`
- Worked examples: JSON header chunking, repo analysis by size, batch synthesis

**Key design choice:** Because `static_instruction` bypasses ADK template processing, it can safely contain Python f-string examples like `f"Analyze: {xml}"` without escaping.

---

## 2. Dynamic Instruction (RLM_DYNAMIC_INSTRUCTION)

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py`

```python
RLM_DYNAMIC_INSTRUCTION = textwrap.dedent("""\
Repository URL: {repo_url?}
Original query: {root_prompt?}
Additional context: {test_context?}
Skill instruction: {skill_instruction?}
User context: {user_ctx_manifest?}
""")
```

This is set as `LlmAgent(instruction=...)`. ADK replaces `{var?}` placeholders with session state values at runtime. The `?` suffix makes each variable optional (no error if the key is missing from state).

**Resolution flow:**
1. Orchestrator writes `repo_url` and `root_prompt` to session state via `EventActions(state_delta=...)`
2. ADK's template engine resolves `{repo_url?}` and `{root_prompt?}` from state
3. `reasoning_before_model` callback merges the resolved dynamic instruction into `system_instruction`

**This is the PRIMARY EXTENSION POINT** for future features. To add task-specific priming (e.g., Polya topology hints, domain-specific guidance), add new `{var?}` placeholders here and write values to session state before the reasoning loop begins.

### Instruction Router

The `instruction_router` is a `Callable[[int, int], str]` (taking `depth` and `fanout_idx`) that produces per-agent skill instructions. When provided to the orchestrator:

1. The orchestrator calls `instruction_router(depth, fanout_idx)` to get the skill instruction text
2. The result is written to session state as `DYN_SKILL_INSTRUCTION` (`skill_instruction`)
3. ADK's template engine resolves `{skill_instruction?}` from state into the dynamic instruction
4. A `before_agent_callback` is wired onto the reasoning agent to seed the skill instruction into `callback_context.state` before the first model call

After child dispatch, `flush_fn` restores the parent's skill instruction to prevent child dispatch from clobbering the parent's `DYN_SKILL_INSTRUCTION` value.

The instruction router is threaded through the entire dispatch chain: `create_rlm_app` → `create_rlm_orchestrator` → `RLMOrchestratorAgent` → `create_dispatch_closures` → `create_child_orchestrator`.

---

## 3. Child Static Instruction (RLM_CHILD_STATIC_INSTRUCTION)

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py`

Condensed version (~1/3 the size of `RLM_STATIC_INSTRUCTION`) used by child orchestrators at depth > 0.

**Keeps:**
- Tool descriptions (`execute_code`, `set_model_response`)
- Core REPL helpers (`llm_query`, `llm_query_batched`, `SHOW_VARS`, `print`)
- General strategy guidance (chunking, batching, synthesis)

**Drops:**
- "Repository Processing" section
- Repomix code examples and `probe_repo`/`pack_repo`/`shard_repo` references
- Skill instruction blocks

Children don't get repomix because they operate on data passed via their prompt, not raw repositories. This is controlled by `include_skills=False` in `create_child_orchestrator()`.

---

## 4. Instruction Injection Flow

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py`

The `reasoning_before_model` callback merges the ADK-resolved dynamic instruction into the system instruction before each model call, largely handled by `_extract_adk_dynamic_instruction`:

1. ADK resolves `{repo_url?}`, `{root_prompt?}`, `{test_context?}` from session state based on the provided template.
2. ADK initially places the resolved `instruction` into the request contents as part of the user turn.
3. `reasoning_before_model` calls `_extract_adk_dynamic_instruction` to find, remove, and merge this dynamic instruction into `llm_request.config.system_instruction`.
4. This maintains proper Gemini role alternation (system instruction is completely separate from user/model turns) and prevents prompt formatting errors.

The callback also records per-invocation accounting: `REASONING_PROMPT_CHARS`, `REASONING_SYSTEM_CHARS`, `REASONING_CONTENT_COUNT`, `REASONING_HISTORY_MSG_COUNT`.

---

## 5. Skill System

**Files:** `rlm_adk/skills/catalog.py`, `rlm_adk/skills/repomix_skill.py`, `rlm_adk/skills/polya_narrative_skill.py`

Skills are the mechanism by which complex, multi-step algorithms are compressed into single-line function calls that the reasoning LLM can invoke inside `execute_code`. The skill system serves two roles simultaneously: it is **API documentation** the model reads to learn what abstractions are available, and it is a **runtime delivery mechanism** that makes those abstractions callable in the REPL.

### 5.1 Google ADK Skill Architecture (Upstream)

ADK's native skill system (preview, `@experimental(FeatureName.SKILL_TOOLSET)`) uses a **hybrid prompt-injection + tool-use** activation model with three content layers:

| Layer | Content | When Loaded | Mechanism |
|-------|---------|-------------|-----------|
| **L1 — Frontmatter** | Name + description (max 1024 chars) | Always in system prompt | `format_skills_as_xml()` → `<available_skills>` XML |
| **L2 — Instructions** | Full markdown body (`SKILL.md`) | On-demand via tool call | `load_skill(name="...")` tool response |
| **L3 — Resources** | `references/`, `assets/`, `scripts/` | On-demand via tool call | `load_skill_resource(skill_name="...", path="...")` |

**Native activation flow:**

1. A `SkillToolset` is attached to the agent's `tools` list, containing `Skill` objects.
2. Before every LLM request, `SkillToolset.process_llm_request()` injects the L1 XML index into `system_instruction` along with a prompt telling the model: *"If a skill seems relevant, you MUST use the `load_skill` tool."*
3. The model reads the XML index, decides a skill is relevant, and makes a **function call** to `load_skill(name="greeting-skill")`.
4. The tool returns the full L2 instructions as a tool response. The model then follows those instructions.
5. If the model needs supplementary material, it calls `load_skill_resource` to fetch L3 content.

This is **context-efficient**: only lightweight L1 metadata (names + descriptions) occupies permanent system prompt space. Full instructions are loaded on-demand via tool-use turns, keeping the baseline context footprint small. The model acts as the router — there is no automatic skill injection based on query matching.

**Key ADK source files:**

| File | Role |
|------|------|
| `google.adk.skills.models` | `Skill`, `Frontmatter`, `Resources` data models |
| `google.adk.skills.prompt` | `format_skills_as_xml(frontmatters) -> str` |
| `google.adk.tools.skill_toolset` | `SkillToolset`, `LoadSkillTool`, `LoadSkillResourceTool` |
| `google.adk.tools.base_toolset` | `BaseToolset.process_llm_request()` hook |

### 5.2 RLM-ADK Hybrid: RLMSkillToolset

RLM-ADK implements a hybrid prompt-injection + tool-use model via `RLMSkillToolset` (`rlm_adk/skills/skill_toolset.py`). The installed ADK does not ship a `SkillToolset` class; RLM-ADK builds its own as a `BaseTool` subclass.

| Aspect | RLMSkillToolset (hybrid) |
|--------|--------------------------|
| Discovery | L1 XML injected into `system_instruction` via `process_llm_request()` on every LLM call |
| Full instructions | On-demand via `load_skill` tool call (L2) |
| Activation trigger | Model calls `load_skill(skill_name=...)` — a tool-use turn |
| State tracking | `skill_last_loaded`, `skill_load_count`, `skill_loaded_names` written via `tool_context.state` (AR-CRIT-001) |
| Skill invocation | Model reads returned instructions, then calls `execute_code` with function call or synthetic import |
| Context cost | Low (L1 only until activated); full L2 loaded on demand |
| Telemetry | `load_skill` calls flow through all three data planes (completion, lineage, state events) |

**Wiring:** The orchestrator creates `RLMSkillToolset(enabled_skills=...)` at depth 0 only and appends it to the reasoning agent's tools list alongside `REPLTool` and `SetModelResponseTool`. Children (depth > 0) never get skill tools — they operate on data passed via their prompt.

**Lineage is automatic:** `sqlite_tracing.py`'s `before_tool_callback` captures depth, fanout_idx, branch, and invocation_id for all tool calls including `load_skill`. The `after_tool_callback` enriches telemetry rows with `decision_mode="load_skill"`, `skill_name_loaded`, and `skill_instructions_len`.

**REPL delivery modes unchanged:** `collect_repl_globals()` (Mode 1) and `activate_side_effect_modules()` (Mode 2) remain orthogonal to how the model discovers skills. After `load_skill` returns the API docs, the model still calls `execute_code` with `probe_repo()` or `from rlm_repl_skills.polya_narrative import ...`.

### 5.3 The `<available_skills>` XML Discovery Block

Each skill produces a structured XML discovery block via `format_skills_as_xml()` from `google.adk.skills.prompt`. For a single skill:

```xml
<available_skills>
<skill>
<name>
repomix-repl-helpers
</name>
<description>
Pre-built REPL functions for packing, probing, and sharding git repositories...
</description>
</skill>
</available_skills>
```

In RLM-ADK, each skill's `build_instruction_block()` produces the XML discovery block followed immediately by the full markdown instructions:

```python
# repomix_skill.py:81-87
def build_skill_instruction_block() -> str:
    discovery_xml = format_skills_as_xml([REPOMIX_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{REPOMIX_SKILL.instructions}"
```

The XML block serves as a **structured discovery token** — a machine-readable envelope the model can quickly scan to determine whether a skill is relevant to the current task. The full markdown instructions that follow provide the API documentation the model needs to actually use the skill.

The resulting `static_instruction` seen by the reasoning agent looks like:

```
[base RLM_STATIC_INSTRUCTION — tool descriptions, REPL capabilities, strategy examples]

<available_skills>
  <skill><name>repomix-repl-helpers</name><description>...</description></skill>
</available_skills>

## repomix-repl-helpers — Pre-built REPL Functions
[function signatures, parameter docs, usage examples]

<available_skills>
  <skill><name>polya-narrative</name><description>...</description></skill>
</available_skills>

## polya-narrative — Iterative Refinement
[synthetic import examples, result types, cycle documentation]
```

### 5.4 Skill Definition

**Files:** `rlm_adk/skills/repomix_skill.py`, `rlm_adk/skills/polya_narrative_skill.py`

Skills use ADK's `Skill` and `Frontmatter` Pydantic models as data containers:

```python
from google.adk.skills.models import Skill, Frontmatter

REPOMIX_SKILL = Skill(
    frontmatter=Frontmatter(
        name="repomix-repl-helpers",
        description="Pre-built REPL functions for packing, probing, and sharding git repositories...",
    ),
    instructions="## repomix-repl-helpers -- Pre-built REPL Functions\n..."
)
```

The `Frontmatter` carries the L1 discovery metadata (name + description). The `instructions` string carries the full L2 API documentation. RLM-ADK does not use `Resources` (L3) since skill content is entirely self-contained in the instruction markdown.

### 5.5 Skill Catalog

**File:** `rlm_adk/skills/catalog.py`

All prompt-visible skills are registered in a central catalog. Each entry is a `PromptSkillRegistration` dataclass:

```python
@dataclass(frozen=True)
class PromptSkillRegistration:
    skill: Skill                                              # ADK Skill object (frontmatter + instructions)
    build_instruction_block: Callable[[], str]                 # Returns XML discovery + instructions
    repl_globals_factory: Callable[[], dict[str, Any]] | None  # REPL globals to inject (optional)
    side_effect_modules: tuple[str, ...]                       # Modules to import for source-expansion registration
```

The four fields capture the full skill contract:
- `skill` — the ADK `Skill` object carrying frontmatter and instructions
- `build_instruction_block` — produces the prompt content (XML + markdown) for `static_instruction`
- `repl_globals_factory` — returns a dict to merge into `repl.globals` (Mode 1 delivery, see 5.7)
- `side_effect_modules` — module paths whose import triggers `register_skill_export()` calls (Mode 2 delivery, see 5.7)

A skill may set `repl_globals_factory`, `side_effect_modules`, both, or neither. The ping skill sets only `side_effect_modules` with an empty `build_instruction_block` (REPL-only, no prompt injection). The repomix skill sets only `repl_globals_factory`. The Polya skill sets only `side_effect_modules`.

The `PROMPT_SKILL_REGISTRY` dict maps skill names to their `PromptSkillRegistration`. All registered skills are enabled by default via `DEFAULT_ENABLED_SKILL_NAMES`.

**Key catalog functions:**

| Function | Purpose |
|----------|---------|
| `normalize_enabled_skill_names(names)` | Validates and returns skill names in registry order |
| `collect_skill_objects(names)` | Returns ADK `Skill` objects for enabled skills that have instructions (used by `RLMSkillToolset`) |
| `build_enabled_skill_instruction_blocks(names)` | Builds prompt instruction blocks for selected skills (legacy, no longer called by agent factory) |
| `collect_repl_globals(names)` | Merges REPL globals from all enabled skills with a `repl_globals_factory` |
| `activate_side_effect_modules(names)` | Imports side-effect modules to trigger `register_skill_export()` for source-expandable skills |
| `selected_skill_summaries(names)` | Returns `(name, description)` tuples for selected skills |

### 5.6 Skill Discovery via RLMSkillToolset

**Files:** `rlm_adk/skills/skill_toolset.py`, `rlm_adk/orchestrator.py`

Skill instructions are no longer pre-baked into `static_instruction` at agent creation. Instead, `RLMSkillToolset` handles both discovery (L1) and on-demand loading (L2):

```python
# orchestrator.py — skill toolset wiring (depth == 0 only)
if self.depth == 0 and self.enabled_skills:
    from rlm_adk.skills.skill_toolset import RLMSkillToolset
    skill_toolset = RLMSkillToolset(enabled_skills=self.enabled_skills)
    tools = [repl_tool, set_model_response_tool, skill_toolset]
```

On each LLM request, `RLMSkillToolset.process_llm_request()`:
1. Calls `format_skills_as_xml(frontmatters)` to build the L1 XML discovery block
2. Appends it to `system_instruction` via `llm_request.append_instructions()`
3. Registers the `load_skill` function declaration via `BaseTool.process_llm_request()`

When the model calls `load_skill(skill_name="...")`:
1. Returns `{skill_name, instructions, frontmatter}` — the full L2 content
2. Writes state keys via `tool_context.state` (AR-CRIT-001 compliant)

Child orchestrators (depth > 0) do not get skill tools. They receive `RLM_CHILD_STATIC_INSTRUCTION` which is ~1/3 the size and contains no skill documentation.

### 5.7 Two Runtime Delivery Modes

**File:** `rlm_adk/orchestrator.py` (lines 302-305)

The orchestrator uses catalog-driven calls to activate skills at runtime:

```python
# orchestrator.py:302-305
from rlm_adk.skills.catalog import activate_side_effect_modules, collect_repl_globals

repl.globals.update(collect_repl_globals(self.enabled_skills))
activate_side_effect_modules(self.enabled_skills)
```

These calls happen after the REPL is created but before the reasoning agent runs. They activate the two delivery modes:

| Mode | Mechanism | Use When | Example |
|------|-----------|----------|---------|
| **Mode 1: REPL Globals** | `collect_repl_globals()` → `repl.globals.update()` | Skill wraps heavy native dependencies with no `llm_query()` calls | `probe_repo()`, `pack_repo()`, `shard_repo()` |
| **Mode 2: Source Expansion** | `activate_side_effect_modules()` → `importlib.import_module()` → `register_skill_export()` | Skill implementation contains `llm_query()` / `llm_query_batched()` calls | `run_polya_narrative()`, `run_recursive_ping()` |

**Why two modes exist — the AST rewriter constraint:**

The choice between modes is not arbitrary. It is driven by whether the skill's implementation calls `llm_query()`:

- **Mode 1 (REPL globals)** injects real Python function objects directly into the REPL namespace. The LLM calls them with no import statement. This works for pure utility functions (repomix) because those functions never call `llm_query()` — they run entirely in the host process.

- **Mode 2 (source expansion)** stores skill source as raw strings. When the LLM writes `from rlm_repl_skills.<module> import <symbol>`, REPLTool intercepts the synthetic import, resolves the dependency graph, and inlines all source into the submitted code string. This is **required** when the skill calls `llm_query()` because the AST rewriter (`rewrite_for_async`) transforms `llm_query(p)` → `await llm_query_async(p)` and promotes containing functions to `async def`. The rewriter only operates on the submitted code text — it cannot see inside injected function objects. Source expansion makes `llm_query()` calls visible to the rewriter by inlining them into the code string.

**Lazy loading:** `_repomix_globals_factory()` (`catalog.py:63-67`) uses a lazy import pattern — `repomix_helpers` is imported only when the factory is called at invocation time, not at catalog import time. This avoids pulling in heavy dependencies for runs that don't need them.

**Process-global registry:** The `_registry` singleton in `skill_registry.py` is process-global. Once `activate_side_effect_modules()` imports a skill module, its `register_skill_export()` calls populate the registry for the lifetime of the process. `importlib.import_module()` is idempotent (Python's module cache), so repeated invocations are safe.

### 5.8 Full Skill Activation Lifecycle

The end-to-end flow from skill definition to LLM invocation:

```
┌─────────────────────────────────────────────────────────────────────┐
│  AGENT CONSTRUCTION (once)                                         │
│                                                                     │
│  create_rlm_app()                                                   │
│    → create_rlm_orchestrator()                                      │
│        → create_reasoning_agent()   (no skill injection here)       │
│            → LlmAgent(static_instruction=base_prompt)               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  INVOCATION STARTUP (per run)                                       │
│                                                                     │
│  RLMOrchestratorAgent._run_async_impl(ctx)                          │
│    → repl = LocalREPL()                                             │
│    → repl.globals.update(collect_repl_globals())                    │
│        → injects probe_repo, pack_repo, shard_repo (Mode 1)        │
│    → activate_side_effect_modules()                                 │
│        → imports polya/ping modules (Mode 2)                        │
│        → register_skill_export() populates SkillRegistry            │
│    → repl_tool = REPLTool(repl, ...)                                │
│    → skill_toolset = RLMSkillToolset(enabled_skills=...)            │
│    → reasoning_agent.tools = [repl_tool, smr_tool, skill_toolset]   │
│    → reasoning_agent.run_async(ctx)                                 │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLM STEP (per model call — process_llm_request fires)             │
│                                                                     │
│  RLMSkillToolset.process_llm_request():                             │
│    → format_skills_as_xml(frontmatters) → L1 XML discovery block    │
│    → llm_request.append_instructions([xml])                         │
│    → registers load_skill FunctionDeclaration                       │
│                                                                     │
│  Model sees in system_instruction:                                  │
│    <available_skills>                                               │
│      <skill><name>repomix-repl-helpers</name>                       │
│             <description>Pre-built REPL functions...</description>  │
│      </skill>                                                       │
│    </available_skills>                                               │
│                                                                     │
│  Model decides skill is relevant → calls load_skill(name="...")     │
│    → returns {skill_name, instructions, frontmatter}                │
│    → writes skill_last_loaded, skill_load_count, skill_loaded_names │
│                                                                     │
│  Model reads L2 instructions, writes execute_code call:             │
│    Mode 1: probe_repo("https://github.com/org/repo")               │
│    Mode 2: from rlm_repl_skills.polya_narrative import ...          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  REPL EXECUTION (REPLTool.run_async)                                │
│                                                                     │
│  1. expand_skill_imports(code)          [repl_tool.py:177-195]      │
│     → SkillRegistry.expand()                                        │
│     → finds synthetic ImportFrom (rlm_repl_skills.*)                │
│     → resolves transitive requires dependencies                     │
│     → topological sort all exports                                  │
│     → inlines source, removes synthetic import                      │
│                                                                     │
│  2. has_llm_calls(expanded_code)        [repl_tool.py:223]          │
│     → True if expanded source contains llm_query() calls            │
│                                                                     │
│  3. rewrite_for_async(expanded_code)    [repl_tool.py:227]          │
│     → llm_query(p) → await llm_query_async(p)                      │
│     → promote containing functions to async def                     │
│     → wrap in async def _repl_exec(): ... return locals()           │
│                                                                     │
│  4. repl.execute_code_async(compiled)                               │
│     → function runs, dispatches child LLMs via llm_query_async      │
│     → returns result to model as tool response                      │
└─────────────────────────────────────────────────────────────────────┘
```

**The model's perspective is simple:** it reads skill documentation in its system prompt, decides which skill is relevant, and calls `execute_code` with code that follows the documented API. The model never sees the synthetic import expansion, AST rewriting, or async transformation — those are implementation details of the REPL execution layer.

### 5.9 Skill Activation Flow Summary

| Step | RLMSkillToolset |
|------|----------------|
| 1. Discovery | `process_llm_request()` injects L1 XML into `system_instruction` before every LLM call |
| 2. Model reads | Sees `<available_skills>` XML index + `load_skill` tool declaration |
| 3. Activation | Model calls `load_skill(skill_name="...")` — a **tool-use turn** |
| 4. Instructions | Returned as `load_skill` tool response (L2 markdown) |
| 5. State tracking | `skill_last_loaded`, `skill_load_count`, `skill_loaded_names` written via `tool_context.state` |
| 6. Invocation | Model calls `execute_code` with function call or synthetic import |
| 7. Telemetry | `decision_mode="load_skill"` + `skill_name_loaded` + `skill_instructions_len` in telemetry table |

**Key insight:** ADK native skills optimize for **breadth** (many skills, low baseline context cost, on-demand loading). RLM-ADK skills optimize for **depth** (few skills with rich API docs, zero-latency access, enabling the model to write correct single-line function calls on the first attempt).

Adding a new skill to the catalog automatically wires its prompt injection, REPL globals, and side-effect modules without touching `agent.py` or `orchestrator.py` code.

---

## 6. repomix-repl-helpers Skill

The repomix skill provides three pre-loaded REPL functions (injected into `REPL.globals` via the catalog's `repl_globals_factory`):

### `probe_repo(source, calculate_tokens=True) -> ProbeResult`
Quick stats without the full packed content.
- `source`: local directory path or remote git URL
- Returns: `ProbeResult` with `.total_files`, `.total_chars`, `.total_tokens`, `.file_tree`

### `pack_repo(source, calculate_tokens=True) -> str`
Entire repo as a single XML string. Best for small repos (<125K tokens).

### `shard_repo(source, max_bytes_per_shard=512000, calculate_tokens=True) -> ShardResult`
Directory-aware chunks. Best for large repos.
- Returns: `ShardResult` with `.chunks` (list[str]), `.total_files`, `.total_chars`, `.total_tokens`

### Recommended usage pattern

```python
# Step 1: probe
info = probe_repo("https://github.com/org/repo")

# Step 2: branch on size
if info.total_tokens < 125_000:
    xml = pack_repo("https://github.com/org/repo")
    analysis = llm_query(f"Analyze: {xml}")
else:
    shards = shard_repo("https://github.com/org/repo")
    prompts = [f"Analyze:\n\n{chunk}" for chunk in shards.chunks]
    analyses = llm_query_batched(prompts)
    combined = "\n---\n".join(analyses)
    analysis = llm_query(f"Synthesize:\n\n{combined}")
```

---

## 7. polya-narrative Skill

**File:** `rlm_adk/skills/polya_narrative_skill.py`

A source-expandable REPL skill that orchestrates iterative narrative refinement using the Polya problem-solving loop: **Understand → Plan → Implement → Reflect**. Unlike the repomix skill (which injects utility functions into `repl.globals`), polya-narrative uses source expansion because its implementation calls `llm_query()` and `llm_query_batched()`, which must be visible to the AST rewriter.

### Dual Registration

The skill registers itself through **two** mechanisms simultaneously:

1. **ADK Skill discovery** — `POLYA_NARRATIVE_SKILL` (a `google.adk.skills.models.Skill` with `Frontmatter`) is registered in `PROMPT_SKILL_REGISTRY` and surfaced to the model via `RLMSkillToolset`. The toolset injects an `<available_skills>` XML block into `system_instruction` and provides a `load_skill` tool for on-demand L2 instruction loading.

2. **Source-expandable REPL exports** — 12 `ReplSkillExport` entries registered at import time under the synthetic module `rlm_repl_skills.polya_narrative`. When the model writes `from rlm_repl_skills.polya_narrative import run_polya_narrative`, the skill registry inlines all source transitively.

### Topology: Vertical Fanout with Sequential Spine

The Polya loop implements a **hybrid topology** — a sequential spine of four phases per cycle, with one phase (IMPLEMENT) using horizontal fanout:

```
                         ┌──────────────────────────────────┐
                         │   Parent REPL (depth 0)          │
                         │   run_polya_narrative(story)      │
                         └──────────────┬───────────────────┘
                                        │
                    ┌───────────────── CYCLE N ──────────────────┐
                    │                                            │
          ┌─────────▼──────────┐                                 │
          │  1. UNDERSTAND      │  llm_query()                   │
          │  (sequential child) │  → 1 child at depth+1          │
          └─────────┬──────────┘                                 │
                    │                                            │
          ┌─────────▼──────────┐                                 │
          │  2. PLAN            │  llm_query()                   │
          │  (sequential child) │  → 1 child at depth+1          │
          └─────────┬──────────┘                                 │
                    │                                            │
                    │  extract_work_packets() → 3-5 packets      │
                    │                                            │
          ┌─────────▼──────────┐                                 │
          │  3. IMPLEMENT       │  llm_query_batched()           │
          │  (parallel fanout)  │  → K children at depth+1       │
          │                     │    (semaphore-limited)          │
          └─────────┬──────────┘                                 │
                    │  merge implementations into narrative       │
                    │                                            │
          ┌─────────▼──────────┐                                 │
          │  4. REFLECT         │  llm_query()                   │
          │  (sequential child) │  → 1 child at depth+1          │
          │                     │  emits VERDICT: COMPLETE/      │
          │                     │        CONTINUE                │
          └─────────┬──────────┘                                 │
                    │                                            │
                    ▼                                            │
            COMPLETE? ──yes──► return PolyaNarrativeResult       │
                │                                                │
                no                                               │
                │                                                │
                └──────────── next cycle ────────────────────────┘
```

**Per-cycle dispatch pattern:**
- 3 sequential `llm_query()` calls (UNDERSTAND, PLAN, REFLECT) — each spawns 1 child orchestrator at depth+1
- 1 `llm_query_batched()` call (IMPLEMENT) — spawns 3-5 children concurrently at depth+1
- Total children per cycle: 6-8

**Depth consumption:** The skill runs inside a depth-0 REPL `execute_code` call. Each `llm_query` / `llm_query_batched` call spawns child orchestrators at depth+1. With `max_cycles=2` (default), total LLM calls are bounded: 2 cycles × (3 sequential + 3-5 batched) = 12-16 child dispatches.

### Phase Details

| Phase | Dispatch | Prompt Builder | What It Produces |
|-------|----------|---------------|-----------------|
| UNDERSTAND | `llm_query()` | `build_understand_prompt()` | Structured assessment: gaps, strengths, themes, technical details, user journey |
| PLAN | `llm_query()` | `build_plan_prompt()` | 3-5 numbered work packets, each specifying section, content, tone, success criteria |
| IMPLEMENT | `llm_query_batched()` | `build_implement_prompt()` | One enriched narrative section per work packet (concurrent) |
| REFLECT | `llm_query()` | `build_reflect_prompt()` | Quality assessment (1-10 scale), `VERDICT: COMPLETE` (≥8) or `VERDICT: CONTINUE` |

### Source Expansion Dependency Graph

The `run_polya_narrative` function has transitive dependencies on all other exports. The skill registry topologically sorts them:

```
POLYA_UNDERSTAND_INSTRUCTIONS  ─┐
POLYA_PLAN_INSTRUCTIONS         ├─► build_understand_prompt  ─┐
POLYA_IMPLEMENT_INSTRUCTIONS    ├─► build_plan_prompt         ├─► run_polya_narrative
POLYA_REFLECT_INSTRUCTIONS      ├─► build_implement_prompt    │
                                ├─► build_reflect_prompt      │
PolyaPhaseResult ───────────────┤                             │
PolyaNarrativeResult ───────────┤                             │
extract_work_packets ───────────┘─────────────────────────────┘
```

When the model writes `from rlm_repl_skills.polya_narrative import run_polya_narrative`, all 12 symbols are inlined in dependency order. The `llm_query()` and `llm_query_batched()` calls inside the expanded source are then visible to the AST rewriter for sync-to-async transformation.

### Relationship to Polya Topology Engine (Vision)

This skill is a **concrete, fixed-topology implementation** of the Polya cycle. It always uses the same hybrid topology (sequential spine + IMPLEMENT fanout). The planned [Polya Topology Engine](vision/polya_topology_engine.md) is a more general system that would dynamically select between horizontal, vertical, and hybrid topologies based on task classification. The polya-narrative skill serves as a working proof-of-concept for the vertical/hybrid pattern.

### Result Type

`PolyaNarrativeResult` — returned by `run_polya_narrative()`:

| Attribute | Type | Description |
|-----------|------|-------------|
| `.narrative` | `str` | Fully refined narrative text |
| `.cycles_completed` | `int` | Number of cycles that ran |
| `.verdict` | `str` | `"COMPLETE"` or `"CONTINUE"` |
| `.phase_results` | `list[PolyaPhaseResult]` | Per-phase per-cycle artifacts |
| `.final_reflection` | `str` | Last REFLECT phase output |
| `.debug_log` | `list[str]` | Debug messages (when `emit_debug=True`) |

---

## 8. How to Add a New Skill

### Step 1: Define the Skill

Create a new file in `rlm_adk/skills/`:

```python
# rlm_adk/skills/my_skill.py
from google.adk.skills.models import Skill, Frontmatter

MY_SKILL = Skill(
    frontmatter=Frontmatter(name="my-skill", description="..."),
    instructions="## my-skill\n\nAPI docs and usage examples..."
)

def build_my_skill_block() -> str:
    from google.adk.skills.prompt import format_skills_as_xml
    discovery_xml = format_skills_as_xml([MY_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{MY_SKILL.instructions}"
```

### Step 2: Register in the Catalog

Add a `PromptSkillRegistration` entry to `PROMPT_SKILL_REGISTRY` in `rlm_adk/skills/catalog.py`:

```python
from rlm_adk.skills.my_skill import MY_SKILL, build_my_skill_block

PROMPT_SKILL_REGISTRY: dict[str, PromptSkillRegistration] = {
    # ... existing entries ...
    MY_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=MY_SKILL,
        build_instruction_block=build_my_skill_block,
        repl_globals_factory=_my_globals_factory,     # optional: for repl.globals injection
        side_effect_modules=("rlm_adk.skills.my_skill",),  # optional: for source-expandable imports
    ),
}
```

The catalog automatically handles instruction block injection (via `build_enabled_skill_instruction_blocks()`), REPL globals injection (via `collect_repl_globals()`), and side-effect module activation (via `activate_side_effect_modules()`). No changes to `agent.py` or `orchestrator.py` are needed.

### Step 3: (Optional) Inject functions into REPL globals

If your skill provides pure utility functions (no `llm_query()` calls), define a `repl_globals_factory` on the catalog entry:

```python
def _my_globals_factory() -> dict[str, Any]:
    from rlm_adk.skills.my_helpers import my_function
    return {"my_function": my_function}
```

The orchestrator calls `collect_repl_globals()` which merges all enabled skills' factories into `repl.globals`.

### Step 4: (Optional) Export to `skills/__init__.py`

Re-export the `Skill` object and any public symbols from `rlm_adk/skills/__init__.py` if external callers need direct access.

### Step 5: Reference in REPL code

The agent can now call `my_function()` directly in `execute_code` blocks -- no imports needed.

---

## 9. Source-Expandable REPL Skills

**Files:** `rlm_adk/repl/skill_registry.py`, `rlm_adk/skills/repl_skills/ping.py`

### Two Skill Delivery Modes

RLM-ADK has two distinct mechanisms for making skill functions available in the REPL:

| Mode | Mechanism | Use When |
|------|-----------|----------|
| `repl.globals` injection | Function injected directly into REPL namespace | Skill is pure Python utility with no `llm_query()` / `llm_query_batched()` calls |
| Source expansion | Synthetic import expanded to inline source before AST rewrite | Skill implementation contains `llm_query()` or `llm_query_batched()` calls |

The `repl.globals` path (used by `probe_repo`, `pack_repo`, `shard_repo`) is simpler: the function exists at runtime and the model calls it directly. However, `llm_query()` calls inside injected globals are invisible to the AST rewriter, which only operates on submitted code text. Source expansion solves this by inlining skill source into the submitted code before AST analysis, making any `llm_query()` calls visible for sync-to-async rewriting.

### Defining a Synthetic REPL Skill Module

A skill module registers `ReplSkillExport` entries at import time via `register_skill_export()`. Each export describes one symbol. The `SkillRegistry` implements topological sorting based on the `requires` fields, allowing complex dependencies between exported symbols, and features a conflict detection mechanism to prevent expanding symbols that clash with user-defined names in the submitted code.

```python
from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.my_skill",   # synthetic module path
        name="my_function",                    # exported symbol name
        source='def my_function(x):\n    return llm_query(f"Process: {x}")',
        requires=["helper_const"],             # dependencies (other exports in same module)
        kind="function",                       # "function", "class", "const", or "source_block"
    )
)
```

**`ReplSkillExport` fields:**

| Field | Type | Description |
|-------|------|-------------|
| `module` | `str` | Synthetic module path (e.g. `rlm_repl_skills.ping`) |
| `name` | `str` | Exported symbol name |
| `source` | `str` | Full source text to inline (must be valid standalone Python) |
| `requires` | `list[str]` | Ordered dependencies by symbol name (same module) |
| `kind` | `str` | One of `function`, `class`, `const`, `source_block` |

### The Synthetic Import Contract

The model writes standard Python import syntax targeting the `rlm_repl_skills` namespace:

```python
from rlm_repl_skills.ping import run_recursive_ping, RecursivePingResult
```

REPLTool intercepts this before AST rewriting and expands it into inline source blocks. The expanded code replaces the import statement with the full source of the requested symbols and all their transitive dependencies, topologically sorted.

**v1 limitations:**
- Only `from rlm_repl_skills.<module> import <symbol>[, <symbol>...]` is supported
- No wildcard imports (`from rlm_repl_skills.ping import *`)
- No aliasing (`from rlm_repl_skills.ping import run_recursive_ping as rp`)
- No plain imports (`import rlm_repl_skills.ping`)

### Constraints on Exported Source

- Source must be valid standalone Python when inlined at module level
- Source may assume REPL globals: `llm_query`, `llm_query_batched`, `LLMResult`, safe builtins, and any other globals present in `LocalREPL`
- Source must not rely on runtime imports for `llm_query`-containing helpers (the whole point of expansion is making these visible to the AST rewriter)
- If expansion would create a name conflict with a user-defined name in the same submitted code block, the expansion fails with a clear error

### When to Choose Expansion vs repl.globals

- **Use `repl.globals`** for pure utility functions (no LM calls): file helpers, data transformers, repo tools
- **Use source expansion** when the skill's implementation calls `llm_query()` or `llm_query_batched()`, because these calls must be visible to the AST rewriter for sync-to-async transformation

### Example: The Ping Skill Module

**File:** `rlm_adk/skills/repl_skills/ping.py`

The first expandable skill module implements a recursive ping workflow. It registers six exports under `rlm_repl_skills.ping`:

| Symbol | Kind | Dependencies | Purpose |
|--------|------|-------------|---------|
| `PING_TERMINAL_PAYLOAD` | const | -- | Terminal layer JSON payload |
| `PING_REASONING_LAYER_1` | const | -- | Layer 1 reasoning summary |
| `PING_REASONING_LAYER_2` | const | -- | Layer 2 reasoning summary |
| `RecursivePingResult` | class | -- | Result container with layer, payload, child_response, debug_log |
| `build_recursive_ping_prompt` | function | `PING_TERMINAL_PAYLOAD`, `PING_REASONING_LAYER_1`, `PING_REASONING_LAYER_2` | Constructs per-layer prompts |
| `run_recursive_ping` | function | All five above | Orchestrates the recursive ping with debug logging and `llm_query()` |

Usage in REPL code:

```python
from rlm_repl_skills.ping import run_recursive_ping

result = run_recursive_ping(max_layer=2)
print(result.payload)  # {"my_response": "pong", "your_response": "ping"}
```

The expansion inlines all six symbols (topologically sorted) into the submitted code, making the `llm_query()` call inside `run_recursive_ping` visible to the AST rewriter.

---

## 10. Future: Dynamic Skill Activation

The current skill system is static -- skills are compiled into the system prompt at agent creation time. A planned enhancement involves:

- A vector store of available skills indexed by description/capability
- Query-time skill retrieval based on the user's prompt
- Dynamic injection of only relevant skills to reduce prompt size
- Activation/deactivation of skills mid-session based on task evolution

Details will be documented in a future `dynamic_skills.md` when the implementation lands. The `Frontmatter.description` field already provides the metadata needed for vector similarity search.

---

## 11. Quick Reference

| Component | File | Role |
|-----------|------|------|
| RLM_STATIC_INSTRUCTION | `rlm_adk/utils/prompts.py` | Main system prompt (no template processing) |
| RLM_DYNAMIC_INSTRUCTION | `rlm_adk/utils/prompts.py` | Template with `{var?}` placeholders |
| RLM_CHILD_STATIC_INSTRUCTION | `rlm_adk/utils/prompts.py` | Condensed prompt for depth > 0 |
| PROMPT_SKILL_REGISTRY | `rlm_adk/skills/catalog.py` | Central registry of all prompt-visible skills |
| PromptSkillRegistration | `rlm_adk/skills/catalog.py` | Dataclass: skill + builder + globals factory + side-effect modules |
| normalize_enabled_skill_names() | `rlm_adk/skills/catalog.py` | Validates and orders requested skill names |
| build_enabled_skill_instruction_blocks() | `rlm_adk/skills/catalog.py` | Builds prompt blocks for selected skills |
| collect_repl_globals() | `rlm_adk/skills/catalog.py` | Merges REPL globals from enabled skills' factories |
| activate_side_effect_modules() | `rlm_adk/skills/catalog.py` | Imports modules to trigger source-expansion registration |
| REPOMIX_SKILL | `rlm_adk/skills/repomix_skill.py` | Skill definition + build function |
| build_skill_instruction_block() | `rlm_adk/skills/repomix_skill.py` | Returns XML discovery + instructions |
| RLMSkillToolset | `rlm_adk/skills/skill_toolset.py` | Hybrid L1 XML injection + `load_skill` tool + state tracking |
| collect_skill_objects() | `rlm_adk/skills/catalog.py` | Returns ADK Skill objects for skills with instructions |
| create_reasoning_agent() | `rlm_adk/agent.py` | Wires static + dynamic instructions (skills wired by orchestrator) |
| reasoning_before_model | `rlm_adk/callbacks/reasoning.py` | Merges dynamic into system_instruction |
| SkillRegistry | `rlm_adk/repl/skill_registry.py` | Synthetic import expansion registry |
| register_skill_export() | `rlm_adk/repl/skill_registry.py` | Module-level registration API |
| expand_skill_imports() | `rlm_adk/repl/skill_registry.py` | Expansion entry point (called by REPLTool) |
| DYN_SKILL_INSTRUCTION | `rlm_adk/state.py` | Dynamic skill instruction state key |
| POLYA_NARRATIVE_SKILL | `rlm_adk/skills/polya_narrative_skill.py` | Skill definition + build function (Polya loop) |
| build_polya_skill_instruction_block() | `rlm_adk/skills/polya_narrative_skill.py` | Returns XML discovery + instructions |
| run_polya_narrative | `rlm_repl_skills.polya_narrative` (synthetic) | Main orchestrator: Understand->Plan->Implement->Reflect |
| ping skill module | `rlm_adk/skills/repl_skills/ping.py` | First expandable skill (recursive ping) |

---

## ADK Gotchas

### Pydantic model constraints on agents

ADK agents are Pydantic models. When injecting skill functions into REPL globals via `orchestrator._run_async_impl()`, the REPL itself is not Pydantic-constrained — but if you need to set attributes on the reasoning agent (e.g., wiring tools), use `object.__setattr__()`:

```python
# WRONG
self.reasoning_agent.tools = [repl_tool]

# CORRECT
object.__setattr__(self.reasoning_agent, "tools", [repl_tool])
```

### State mutation (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
- **2026-03-25 16:00** — `rlm_adk/skills/loader.py`: GAP-C: Added `_has_llm_query_batched_fn_param()`, extended `_wrap_with_llm_query_injection()` to inject `llm_query_batched_fn` from REPL globals, updated `collect_skill_repl_globals()` guard to wrap functions declaring either param `[session: cd2d9e3f]`
- **2026-03-25 16:00** — `rlm_adk/skills/test_skill/skill.py`: GAP-C: Added `llm_query_batched_fn=None` parameter to `run_test_skill()` signature `[session: cd2d9e3f]`
- **2026-03-25 16:45** — `rlm_adk/utils/prompts.py`: GAP-D: Added skill tools section (list_skills/load_skill) to `RLM_CHILD_STATIC_INSTRUCTION` `[session: cd2d9e3f]`
