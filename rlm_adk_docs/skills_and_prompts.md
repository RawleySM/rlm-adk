<!-- validated: 2026-03-09 -->

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
""")
```

This is set as `LlmAgent(instruction=...)`. ADK replaces `{var?}` placeholders with session state values at runtime. The `?` suffix makes each variable optional (no error if the key is missing from state).

**Resolution flow:**
1. Orchestrator writes `repo_url` and `root_prompt` to session state via `EventActions(state_delta=...)`
2. ADK's template engine resolves `{repo_url?}` and `{root_prompt?}` from state
3. `reasoning_before_model` callback merges the resolved dynamic instruction into `system_instruction`

**This is the PRIMARY EXTENSION POINT** for future features. To add task-specific priming (e.g., Polya topology hints, domain-specific guidance), add new `{var?}` placeholders here and write values to session state before the reasoning loop begins.

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

The `reasoning_before_model` callback merges the ADK-resolved dynamic instruction into the system instruction before each model call:

1. ADK resolves `{repo_url?}`, `{root_prompt?}`, `{test_context?}` from session state
2. ADK places the resolved `instruction` into the request contents
3. `reasoning_before_model` extracts it and merges into `llm_request.config.system_instruction`
4. This maintains proper Gemini role alternation (system instruction is separate from user/model turns)

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

## 7. How to Add a New Skill

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

## 8. Future: Dynamic Skill Activation

The current skill system is static -- skills are compiled into the system prompt at agent creation time. A planned enhancement involves:

- A vector store of available skills indexed by description/capability
- Query-time skill retrieval based on the user's prompt
- Dynamic injection of only relevant skills to reduce prompt size
- Activation/deactivation of skills mid-session based on task evolution

Details will be documented in a future `dynamic_skills.md` when the implementation lands. The `Frontmatter.description` field already provides the metadata needed for vector similarity search.

---

## Quick Reference

| Component | File | Role |
|-----------|------|------|
| RLM_STATIC_INSTRUCTION | `rlm_adk/utils/prompts.py` | Main system prompt (no template processing) |
| RLM_DYNAMIC_INSTRUCTION | `rlm_adk/utils/prompts.py` | Template with `{var?}` placeholders |
| RLM_CHILD_STATIC_INSTRUCTION | `rlm_adk/utils/prompts.py` | Condensed prompt for depth > 0 |
| REPOMIX_SKILL | `rlm_adk/skills/repomix_skill.py` | Skill definition + build function |
| build_skill_instruction_block() | `rlm_adk/skills/repomix_skill.py` | Returns XML discovery + instructions |
| create_reasoning_agent() | `rlm_adk/agent.py` | Wires static + dynamic + skills |
| reasoning_before_model | `rlm_adk/callbacks/reasoning.py` | Merges dynamic into system_instruction |

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

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
