# Skill System State -- Comprehensive Codebase Review

**Date**: 2026-03-24
**Scope**: All `*.py` files in the rlm-adk repository, plus related JSON/YAML/MD artifacts

---

## 1. Files That Exist in `rlm_adk/skills/`

### Active Files (in `rlm_adk/skills/` root)

| File | Status | Contents |
|------|--------|----------|
| `__init__.py` | **Active** | Docstring-only stub. Declares the package, states that skill modules (catalog, repomix, polya, etc.) have been moved to `obsolete/`. Points to `repl/skill_registry.py` and `expand_skill_imports()` as the active skill mechanism. Exports nothing. |
| `agent_findings.json` | **Active (documentation)** | JSON transcript of a prior agent investigation into the skill system. Not executable code. |
| `agent_findings.md` | **Active (documentation)** | Markdown narrative of findings from the agent investigation. Not executable code. |

### Obsolete Files (in `rlm_adk/skills/obsolete/`)

All of these were moved here from the `rlm_adk/skills/` root as part of the "skill system reset." None are imported by any active code path.

| File | Original Purpose |
|------|-----------------|
| `catalog.py` | Central catalog registry (`PROMPT_SKILL_REGISTRY`, `PromptSkillRegistration`). Imported from every polya/repomix skill module. Contains `collect_skill_objects()`, `activate_side_effect_modules()`, `normalize_enabled_skill_names()`, `build_enabled_skill_instruction_blocks()`, `selected_skill_summaries()`. |
| `skill_toolset.py` | `RLMSkillToolset(BaseTool)` -- hybrid prompt-injection + tool-use skill discovery. Implemented ADK's L1/L2 skill pattern locally: `process_llm_request()` injected XML into system_instruction, `run_async()` returned full L2 instructions on `load_skill` tool call. Imported `collect_skill_objects` from `catalog.py`. |
| `polya_understand.py` | Polya-understand skill -- ADK `Skill` object with frontmatter + multi-thousand-line instruction block. |
| `polya_understand_t1_workflow.py` | T1 Workflow-First 3-Layer topology variant. |
| `polya_understand_t2_flat.py` | T2 Flat topology variant. |
| `polya_understand_t3_adaptive.py` | T3 Adaptive topology variant. |
| `polya_understand_t4_debate.py` | T4 Debate topology variant. |
| `polya_narrative_skill.py` | Polya narrative skill for storytelling-based analysis. |
| `repomix_skill.py` | Repomix skill -- ADK `Skill` object with frontmatter + instruction block for repository analysis. |
| `repomix_helpers.py` | Helper functions for repomix operations. |
| `README.md` | Documentation for the old skill system. |
| `repl_skills/__init__.py` | Package init for REPL-expandable skills. |
| `repl_skills/ping.py` | Source-expandable REPL skill: recursive ping. Registered `ReplSkillExport` entries at import time for `from rlm_repl_skills.ping import run_recursive_ping`. |
| `repl_skills/repomix.py` | Source-expandable REPL skill: repomix helpers (`probe_repo`, `pack_repo`, `shard_repo`). Registered `ReplSkillExport` entries at import time. |
| `research/` | Research sources sub-package (substack client, DAG template, process docs). |

### Deleted Files (tracked by git as deletions from `rlm_adk/skills/`)

The following files show as git `D` (deleted) in the working tree because they were moved to `obsolete/`:
- `catalog.py`, `polya_narrative_skill.py`, `polya_understand.py`, `polya_understand_t1_workflow.py`, `polya_understand_t2_flat.py`, `polya_understand_t3_adaptive.py`, `polya_understand_t4_debate.py`, `repl_skills/__init__.py`, `repl_skills/ping.py`, `repomix_helpers.py`, `repomix_skill.py`, `skill_toolset.py`, `research/` (entire subtree), `README.md`

### Stale `.pyc` Files

The `__pycache__/` directory under `rlm_adk/skills/` still contains compiled bytecode for the old modules:
`catalog.cpython-312.pyc`, `polya_narrative_skill.cpython-312.pyc`, `polya_understand.cpython-312.pyc`, `polya_understand_t1_workflow.cpython-312.pyc`, `polya_understand_t2_flat.cpython-312.pyc`, `polya_understand_t3_adaptive.cpython-312.pyc`, `polya_understand_t4_debate.cpython-312.pyc`, `repomix_skill.cpython-312.pyc`, `skill_toolset.cpython-312.pyc`, `repomix_helpers.cpython-312.pyc`

These are harmless but reflect the previous iteration.

---

## 2. Skill Infrastructure in Other Modules

### `rlm_adk/agent.py`

- **`enabled_skills` parameter**: Threaded through `create_rlm_orchestrator()`, `create_rlm_app()`, and `create_rlm_runner()`. Converted to a tuple and passed as `enabled_skills=resolved_enabled_skills` to `RLMOrchestratorAgent(**kwargs)`.
- **No `instruction_router` default wiring from `enabled_skills`**: The `enabled_skills` tuple is stored on the orchestrator Pydantic model field but **nothing in agent.py constructs an `instruction_router` from it**. The `instruction_router` parameter is a separate, independent argument. There is no code that translates `enabled_skills` into an `instruction_router` or any other runtime behavior.
- **No skill toolset wiring**: `RLMSkillToolset` is NOT instantiated anywhere in `agent.py`. The old `skill_toolset.py` is in `obsolete/`.
- **No `catalog.py` import**: No active code imports from `rlm_adk.skills.catalog`.

### `rlm_adk/orchestrator.py`

- **`enabled_skills: tuple[str, ...] = ()`**: Declared as a Pydantic field on `RLMOrchestratorAgent`. **Never read** within `_run_async_impl()` or any method. It is a stored-but-unused field.
- **`instruction_router: Any = None`**: Separate field. When non-None, the orchestrator calls `self.instruction_router(self.depth, self.fanout_idx)` to get a `_skill_text` string, which is stored into `DYN_SKILL_INSTRUCTION` state key and seeded via `before_agent_callback`. This is the **active mechanism** for injecting skill-like instructions into the reasoning agent's dynamic prompt.
- **`DYN_SKILL_INSTRUCTION` import**: Imported from `rlm_adk.state` and used to write the skill instruction text into session state so the `{skill_instruction?}` template placeholder in `RLM_DYNAMIC_INSTRUCTION` gets resolved by ADK.
- **No `RLMSkillToolset` usage**: The tools wired onto the reasoning agent are `[repl_tool, set_model_response_tool]` only. No skill toolset is included.

### `rlm_adk/tools/repl_tool.py`

- **`expand_skill_imports`**: Imported from `rlm_adk.repl.skill_registry` and called on every `execute_code` invocation (line 177). This is the **active** source-expansion mechanism. If the submitted code contains `from rlm_repl_skills.<mod> import <sym>`, the registry expands it inline.
- **Skill expansion state keys**: When expansion occurs, writes `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` to `tool_context.state`.
- **Error handling**: `RuntimeError` from expansion (unknown module/symbol, name conflict) is caught and returned as `SkillExpansionError` in stderr.

### `rlm_adk/dispatch.py`

- **`DYN_SKILL_INSTRUCTION` import and usage**: The `post_dispatch_state_patch_fn()` closure restores `DYN_SKILL_INSTRUCTION` to the parent's value after child dispatch, so the parent reasoning agent's skill instruction is not clobbered by child state mutations.
- **`instruction_router` parameter**: Passed through to `create_child_orchestrator()` for recursive child dispatch.
- **No skill catalog/toolset references**: Dispatch operates purely through `instruction_router` for skill-like text injection.

### `rlm_adk/utils/prompts.py`

- **`{skill_instruction?}`**: The `RLM_DYNAMIC_INSTRUCTION` template includes `Skill instruction: {skill_instruction?}` which ADK resolves from session state at runtime. This is the prompt-visible endpoint for skill instruction injection.
- **No skill-specific static instruction content**: Neither `RLM_STATIC_INSTRUCTION` nor `RLM_CHILD_STATIC_INSTRUCTION` mention skills.

### `rlm_adk/state.py`

- **`DYN_SKILL_INSTRUCTION = "skill_instruction"`**: The state key constant for the dynamic skill instruction template variable.
- **`REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND`**: State keys for tracking when skill source expansion occurs in the REPL.
- **`# ENABLED_SKILLS removed -- skill catalog system reset`**: Explicit comment noting the removal.
- **`# Skill Loading Keys -- removed (skill catalog system reset)`**: Another explicit removal comment.
- **`CURATED_STATE_KEYS` includes `DYN_SKILL_INSTRUCTION`**: So it is captured by the child event re-emission filter.
- **`CURATED_STATE_PREFIXES` includes `"repl_skill_expansion_meta"` and `"repl_did_expand"`**: So these are captured for observability.

### `rlm_adk/types.py`

- **`decision_mode` Literal includes `"load_skill"` and `"load_skill_resource"`**: The `RLMStepRecord` dataclass (used by sqlite_tracing) has these as possible values for classifying what tool the model decided to call. This is **forward-compatible plumbing** -- it would work if a skill toolset were wired, but currently no code path produces these values since `RLMSkillToolset` is not wired.

### `rlm_adk/plugins/sqlite_tracing.py`

- **`skill_instruction TEXT` column**: The `telemetry` table schema includes a `skill_instruction` column, populated from `callback_context.state.get(DYN_SKILL_INSTRUCTION)` on each `before_model_callback`. This is **active** -- it captures whatever skill instruction text is in session state.
- **`skill_name_loaded TEXT` and `skill_instructions_len INTEGER` columns**: In the telemetry table schema. These would be populated when a `load_skill` tool call is detected, but since `RLMSkillToolset` is not wired, these columns are always NULL in practice.
- **`_classify_key()` function**: Classifies `"repl_skill_expansion_meta"` and `"repl_did_expand"` as `"repl"` category, and `"skill_instruction"` as `"request_meta"` category.

### `rlm_adk/plugins/repl_capture_plugin.py`

- **Line 131**: Comment: `# Read expanded code from state (if skill expansion occurred)`. No other skill references.

### `rlm_adk/dashboard/` (multiple files)

- **`live_models.py`**: `LiveSessionSummary.registered_skills: list[tuple[str, str]]`, `LiveModelCall.skill_instruction: str | None`, `LiveDashboardState.selected_skills: list[str]`. These data models carry skill metadata for the dashboard UI.
- **`live_loader.py`**: Populates `registered_skills=[]` (hardcoded empty list). Reads `skill_instruction` from telemetry rows for display. Renders `DYN_SKILL_INSTRUCTION` with label `"Skill instruction:"` in the dynamic keys banner.
- **`live_controller.py`**: `set_selected_skills()` method stores user selections. Passes `enabled_skills=self.state.selected_skills` to `prepare_replay_launch()` and `prepare_provider_fake_launch()`.
- **`live_app.py`**: Renders a "Skills in Prompt" section in the UI from `session_summary.registered_skills`.
- **`run_service.py`**: `prepare_replay_launch()` and `prepare_provider_fake_launch()` both accept `enabled_skills` and pass it to `create_rlm_runner()`.
- **`flow_models.py`**: `FlowInspectorData.skills: list[tuple[str, str]]`.
- **`flow_builder.py`**: Initializes `skills=[]` (empty).
- **`components/flow_context_inspector.py`**: `_skills_section()` renders "Enabled Skills" chips, or "No skills loaded" if empty.

### `rlm_adk/eval/` (benchmark runners)

- **`understand_bench/runner.py`**: Line 346-353 hardcodes a query that tells the agent to `from rlm_repl_skills.polya_understand import run_polya_understand`. This references the **obsolete** source-expandable skill system. Would fail at runtime since `rlm_adk.skills.polya_understand` is no longer importable from its original path, and no `activate_side_effect_modules()` call registers the exports.
- **`understand_bench_v2/types.py`**: Defines `FormatSkill` enum (TEXT_EXTRACTION, TABLE_PARSING, etc.) -- these are domain-level "skills" for file format processing, not the ADK skill system.
- **`understand_bench_v2/file_type_registry.py`**: `FORMAT_SKILLS` mapping from file extensions to `FormatSkill` enum values.

---

## 3. Skill Registry (`rlm_adk/repl/skill_registry.py`)

### What It Does

The `SkillRegistry` is a **source-expansion mechanism** for synthetic REPL imports. It is the one remaining active piece of skill infrastructure.

**Core data model:**
- `ReplSkillExport`: A dataclass holding `module`, `name`, `source` (Python code string), `requires` (dependency list), `kind` ("function").
- `ExpandedSkillCode`: Result of expansion -- `original_code`, `expanded_code`, `expanded_symbols`, `expanded_modules`, `did_expand`.

**How it works:**
1. Skill modules (like the old `repl_skills/ping.py`) call `register_skill_export(ReplSkillExport(...))` at import time as a side effect.
2. When a user's REPL code contains `from rlm_repl_skills.<mod> import <sym>`, the registry's `expand()` method detects these synthetic `ImportFrom` AST nodes.
3. It resolves the requested symbols, transitively resolves dependencies, topologically sorts them, checks for name conflicts, and replaces the synthetic import with inline source code.
4. The expanded code is what actually gets executed in the REPL.

**Module-level singleton:**
```python
_registry = SkillRegistry()
```
Exposed via `register_skill_export()`, `expand_skill_imports()`, and `build_auto_import_lines()`.

### How It's Wired

- `REPLTool.run_async()` calls `expand_skill_imports(code)` on every code execution (line 177 of `repl_tool.py`).
- **However**: No code in the active execution path calls `register_skill_export()`. The old `activate_side_effect_modules()` from `catalog.py` was the mechanism that imported skill modules to trigger their registration side effects. Since `catalog.py` is in `obsolete/` and nothing replaces it, the **registry singleton `_registry._exports` is always empty** in the current codebase.
- As a result, `expand_skill_imports()` always returns `ExpandedSkillCode(did_expand=False)` and the code passes through unchanged.
- `build_auto_import_lines()` is defined but never called from active code.

---

## 4. Imports and References

### Active `from rlm_adk.skills` Imports

**None.** No active (non-obsolete) `.py` file contains `from rlm_adk.skills` imports of anything other than the package itself (which is empty).

### Active Skill-Related Imports Across the Codebase

| Import | File | Status |
|--------|------|--------|
| `from rlm_adk.repl.skill_registry import expand_skill_imports` | `tools/repl_tool.py` | **Active** -- called every execution |
| `from rlm_adk.state import DYN_SKILL_INSTRUCTION` | `orchestrator.py`, `dispatch.py`, `plugins/sqlite_tracing.py`, `dashboard/live_loader.py` | **Active** -- instruction_router mechanism |
| `from rlm_adk.state import REPL_SKILL_EXPANSION_META, REPL_DID_EXPAND, REPL_EXPANDED_CODE, REPL_EXPANDED_CODE_HASH` | `tools/repl_tool.py`, `state.py` | **Active** -- observability keys (but expansion never triggers) |

### Dead/Orphaned Imports (in obsolete/ only)

| Import | File |
|--------|------|
| `from rlm_adk.skills.catalog import collect_skill_objects` | `obsolete/skill_toolset.py` |
| `from rlm_adk.skills.polya_*` | `obsolete/catalog.py` |
| `from rlm_adk.skills.repomix_skill` | `obsolete/catalog.py` |
| `from google.adk.skills.models import Frontmatter, Skill` | `obsolete/catalog.py` |
| `from google.adk.skills.prompt import format_skills_as_xml` | `obsolete/skill_toolset.py` |
| `from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export` | `obsolete/repl_skills/ping.py`, `obsolete/repl_skills/repomix.py` |

---

## 5. Callsite Hover Data

### `callsite_hover/skill_toolset_google-adk_callsite_hover.json`

This file documents the Google ADK API surface used by the **now-obsolete** `rlm_adk/skills/skill_toolset.py`:

- **`format_skills_as_xml`**: `(function) def format_skills_as_xml(skills: List[Frontmatter]) -> str` -- Formats skill frontmatter into XML for LLM instruction injection.
- **`BaseTool`**: Used as base class for `RLMSkillToolset`.
- **`ToolContext`**: Parameter type in `process_llm_request` and `run_async`.

The hover data references `line 28: base:RLMSkillToolset`, `line 72/89: param:tool_context`, `line 79: xml = format_skills_as_xml(...)`. All of these are in the obsolete file.

---

## 6. What's Actually Wired vs Dead Code

### ACTIVE in the Current Execution Path

1. **`SkillRegistry` singleton + `expand_skill_imports()`** (in `repl/skill_registry.py`): Called on every REPL execution. However, with no registered exports, it is a **no-op pass-through** -- structurally active but functionally inert.

2. **`DYN_SKILL_INSTRUCTION` state key** (in `state.py`): Actively used by:
   - `orchestrator.py`: Written from `instruction_router(depth, fanout_idx)` result
   - `dispatch.py`: Preserved/restored in `post_dispatch_state_patch_fn()`
   - `plugins/sqlite_tracing.py`: Captured in telemetry rows
   - `utils/prompts.py`: Template placeholder `{skill_instruction?}` in dynamic instruction
   - Dashboard: Displayed in session detail views

3. **`instruction_router` mechanism**: The orchestrator accepts an `instruction_router: Callable[[int, int], str]` that produces skill-like instruction text per (depth, fanout_idx). This is a **fully active** mechanism for injecting context-specific instructions into reasoning agents. It just happens to not be wired to the old skill catalog.

4. **`enabled_skills` parameter plumbing**: Accepted by `create_rlm_orchestrator()`, `create_rlm_app()`, `create_rlm_runner()`, and the dashboard `run_service.py`. Stored as `RLMOrchestratorAgent.enabled_skills: tuple[str, ...]`. **But the stored tuple is never read or used** -- it is a dangling parameter with no consumer.

5. **Skill expansion observability keys**: `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` are defined in `state.py`, written by `REPLTool` when expansion occurs, and tracked by `sqlite_tracing.py` and `DEPTH_SCOPED_KEYS`. Structurally complete but never triggered since the registry is empty.

6. **`decision_mode` literals**: `"load_skill"` and `"load_skill_resource"` in `types.py` `RLMStepRecord`. Forward-compatible plumbing, never produced by current code.

7. **Dashboard skill UI**: `LiveDashboardState.selected_skills`, `LiveSessionSummary.registered_skills`, skill chips in flow inspector -- all wired but always render as empty because `registered_skills` is hardcoded to `[]` in `live_loader.py` and no skill catalog populates it.

### DEAD CODE (Obsolete, Not Reachable)

1. **`rlm_adk/skills/obsolete/catalog.py`**: `PROMPT_SKILL_REGISTRY`, `collect_skill_objects()`, `activate_side_effect_modules()`, `normalize_enabled_skill_names()`, etc. Not imported by any active code.

2. **`rlm_adk/skills/obsolete/skill_toolset.py`**: `RLMSkillToolset(BaseTool)` with `process_llm_request()` and `run_async()`. Not imported or instantiated anywhere.

3. **All polya/repomix skill modules in `obsolete/`**: ADK `Skill` objects, instruction builders, `register_skill_export()` side effects. None importable from their original paths.

4. **`obsolete/repl_skills/ping.py` and `repomix.py`**: Source-expandable skill registrations. Would work if imported (they call `register_skill_export()`), but nothing imports them.

5. **`understand_bench/runner.py` skill reference**: The v1 benchmark runner's query string references `from rlm_repl_skills.polya_understand import run_polya_understand`. This would fail at runtime because the polya_understand module is in `obsolete/` and no side-effect import activates it.

6. **Disabled test files**: `test_catalog_activation.py`, `test_polya_t1_workflow.py`, `test_polya_t2_flat.py`, `test_polya_t3_adaptive.py`, `test_polya_t4_debate.py` -- all fully commented out with header comment `# DISABLED: skill system reset`.

---

## 7. Summary

The RLM-ADK skill system has undergone a **complete reset**. The previous architecture had three layers:

1. **Prompt-visible ADK skills** (`catalog.py` + `skill_toolset.py`): L1 XML frontmatter injection + L2 on-demand `load_skill` tool -- modeled after ADK's `SkillToolset` pattern.
2. **Source-expandable REPL skills** (`repl_skills/ping.py`, `repl_skills/repomix.py`): Synthetic `from rlm_repl_skills.<mod> import <sym>` imports expanded into inline source at execution time.
3. **Instruction-router mechanism** (`instruction_router: Callable[[int, int], str]`): Injects skill-like text into the `{skill_instruction?}` template variable per (depth, fanout_idx).

After the reset:

- **Layer 1 is fully disabled.** `catalog.py` and `skill_toolset.py` are in `obsolete/`. `RLMSkillToolset` is not wired. No ADK Skill/Frontmatter objects are created.
- **Layer 2 is structurally intact but functionally inert.** `SkillRegistry` exists, `expand_skill_imports()` is called on every execution, but no skill exports are registered, so expansion never occurs.
- **Layer 3 is fully active.** The `instruction_router` mechanism works end-to-end: orchestrator writes to `DYN_SKILL_INSTRUCTION`, dispatch preserves/restores it, the template resolves it, and telemetry captures it. This is currently the **only functioning skill-like mechanism** in the system.

The `enabled_skills` parameter is plumbed through the entire factory chain (`create_rlm_runner` -> `create_rlm_app` -> `create_rlm_orchestrator` -> `RLMOrchestratorAgent`) and through the dashboard launch service, but **the stored tuple is never consumed** by any active code. It is a vestigial parameter from the previous catalog-driven architecture.

### What Would Be Needed to Re-Enable Skills

To restore any form of skill activation:
- **For Layer 1 (ADK Skill Toolset)**: Move `skill_toolset.py` and `catalog.py` back to active, wire `RLMSkillToolset` as a tool on the reasoning agent alongside `repl_tool` and `set_model_response_tool`, and rebuild the skill catalog.
- **For Layer 2 (REPL source expansion)**: Import skill registration modules (e.g. `repl_skills/ping.py`) somewhere in the startup path so `register_skill_export()` populates the registry. The infrastructure is ready; it just needs registration calls.
- **For Layer 3 (instruction_router)**: Already active. Just needs a caller to pass an `instruction_router` function.
