<!-- validated: 2026-03-17 -->

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

Children don't get repomix because they operate on data passed via their prompt, not raw repositories. This is controlled by `include_repomix=False` in `create_child_orchestrator()`.

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

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repomix_skill.py`

Skills use ADK's `google.adk.skills.models.Skill` and `Frontmatter` classes:

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

**`build_skill_instruction_block()`** returns the skill discovery XML (via `format_skills_as_xml()`) concatenated with the full instructions text. This block is appended to `static_instruction` in `create_reasoning_agent()`:

```python
# agent.py line 204-208
if include_repomix:
    from rlm_adk.skills.repomix_skill import build_skill_instruction_block
    static_instruction = static_instruction + "\n" + build_skill_instruction_block()
```

Skills are injected once at root level only (`include_repomix=True` for root, `False` for children).

---

## 6. repomix-repl-helpers Skill

The only skill currently defined. Provides three pre-loaded REPL functions (injected into `REPL.globals` by the orchestrator):

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

1. **ADK Skill discovery** — `POLYA_NARRATIVE_SKILL` (a `google.adk.skills.models.Skill` with `Frontmatter`) is appended to `static_instruction` via `build_polya_skill_instruction_block()` in `create_reasoning_agent()`. This gives the reasoning agent an `<available_skills>` XML block describing the skill's purpose and usage.

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

### Step 2: Append to static_instruction

In `create_reasoning_agent()` (`agent.py`), append the skill block:

```python
from rlm_adk.skills.my_skill import build_my_skill_block
static_instruction = static_instruction + "\n" + build_my_skill_block()
```

### Step 3: Inject functions into REPL globals

In `orchestrator.py` `_run_async_impl()`, inject callable functions:

```python
repl.globals["my_function"] = my_function
```

### Step 4: Reference in REPL code

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
| REPOMIX_SKILL | `rlm_adk/skills/repomix_skill.py` | Skill definition + build function |
| build_skill_instruction_block() | `rlm_adk/skills/repomix_skill.py` | Returns XML discovery + instructions |
| create_reasoning_agent() | `rlm_adk/agent.py` | Wires static + dynamic + skills |
| reasoning_before_model | `rlm_adk/callbacks/reasoning.py` | Merges dynamic into system_instruction |
| SkillRegistry | `rlm_adk/repl/skill_registry.py` | Synthetic import expansion registry |
| register_skill_export() | `rlm_adk/repl/skill_registry.py` | Module-level registration API |
| expand_skill_imports() | `rlm_adk/repl/skill_registry.py` | Expansion entry point (called by REPLTool) |
| DYN_SKILL_INSTRUCTION | `rlm_adk/state.py` | Dynamic skill instruction state key |
| POLYA_NARRATIVE_SKILL | `rlm_adk/skills/polya_narrative_skill.py` | Skill definition + build function (Polya loop) |
| build_polya_skill_instruction_block() | `rlm_adk/skills/polya_narrative_skill.py` | Returns XML discovery + instructions |
| run_polya_narrative | `rlm_repl_skills.polya_narrative` (synthetic) | Main orchestrator: Understand→Plan→Implement→Reflect |
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

- **2026-03-09 13:00** — Initial branch doc created from codebase exploration.
- **2026-03-10 09:40** — Added section 8 (Source-Expandable REPL Skills) documenting skill registry, expansion contract, and ping skill module.
- **2026-03-12 13:25** — `prompts.py`, `orchestrator.py`, `state.py`, `dispatch.py`: Instruction router feature — `{skill_instruction?}` placeholder in dynamic instruction, `DYN_SKILL_INSTRUCTION` state key, `before_agent_callback` seeding, flush_fn parent restoration.
- **2026-03-13 10:50** — Moved `skills/repl_skills/polya_narrative.py` → `skills/polya_narrative_skill.py`. Added ADK `Skill` object (`POLYA_NARRATIVE_SKILL`) with `Frontmatter` + `instructions` following the repomix pattern. Added `build_polya_skill_instruction_block()` for XML discovery injection. `skills/__init__.py` now exports `POLYA_NARRATIVE_SKILL`. Skill is now discoverable by the reasoning agent via `<available_skills>` XML in static instruction — no instruction_router needed for depth-0 activation.
- **2026-03-17 14:35** — `skills/__init__.py`: Added `normalize_enabled_skill_names()` and `build_enabled_skill_instruction_blocks()` exports. `skills/catalog.py`: New skill catalog module. `prompts.py`: Updated child static instruction and dynamic instruction templates.
- **2026-03-17 16:55** — `catalog.py`: Extended `PromptSkillRegistration` with `repl_globals_factory` and `side_effect_modules` fields. Added `collect_repl_globals()` and `activate_side_effect_modules()` catalog functions. Added ping skill entry to `PROMPT_SKILL_REGISTRY`. `orchestrator.py`: Replaced hardwired repomix/polya/ping imports (lines 278-287) with catalog-driven `collect_repl_globals()` and `activate_side_effect_modules()` calls. `agent.py`: Renamed `include_repomix` parameter to `include_skills` in `create_reasoning_agent()` and `create_child_orchestrator()`.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
