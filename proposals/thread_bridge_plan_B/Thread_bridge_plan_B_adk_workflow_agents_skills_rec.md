# Workflow-Agent-Expert Review: Thread Bridge + ADK SkillToolset Integration

## Reviewed Plan
`/home/rawley-stanhope/.claude/plans/woolly-sprouting-mochi.md`

## Source Files Examined
- ADK `base_llm_flow.py` :: `_process_agent_tools()` (lines 398-445) — tool/toolset iteration & processing
- ADK `single_flow.py` :: `SingleFlow.__init__` — request_processors ordering (including `_output_schema_processor`)
- ADK `skill_toolset.py` :: `SkillToolset.process_llm_request()`, `get_tools()`, `LoadSkillTool`, activation state
- ADK `llm_agent.py` :: `LlmAgent._run_async_impl`, `canonical_tools`, `_llm_flow`, `ToolUnion`
- ADK `base_toolset.py` :: `BaseToolset.process_llm_request()`, `get_tools_with_prefix()`
- ADK `base_tool.py` :: `BaseTool.process_llm_request()` (default: `llm_request.append_tools([self])`)
- ADK `set_model_response_tool.py` :: `SetModelResponseTool` (no `process_llm_request` override, uses default)
- ADK `_output_schema_processor.py` :: `_OutputSchemaRequestProcessor` (injects `SetModelResponseTool` only when `agent.output_schema` is set AND tools present)
- RLM `orchestrator.py` :: `_run_async_impl`, tool wiring via `object.__setattr__`
- RLM `agent.py` :: `create_reasoning_agent`, `create_child_orchestrator`
- RLM `dispatch.py` :: `create_dispatch_closures`, `_run_child`, `WorkerPool` (alias for `DispatchConfig`)

---

## Question 1: SkillToolset on reasoning_agent via `object.__setattr__` — Does It Work?

**Verdict: YES, it works correctly.**

The critical path is:

1. `RLMOrchestratorAgent._run_async_impl()` calls `object.__setattr__(self.reasoning_agent, "tools", tools)` at line 332.
2. Then it calls `self.reasoning_agent.run_async(ctx)` at line 495.
3. `LlmAgent._run_async_impl` calls `self._llm_flow.run_async(ctx)`.
4. `SingleFlow` (since `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True` and no `sub_agents`) runs `_preprocess_async()`.
5. `_preprocess_async()` at line 881 calls `_process_agent_tools(invocation_context, llm_request)`.
6. `_process_agent_tools` reads `agent.tools` at line 418 (`if not hasattr(agent, 'tools') or not agent.tools`), then iterates `agent.tools` at line 423.

Since `_process_agent_tools` reads `agent.tools` **at call time** (not at construction time), the `object.__setattr__` mutation made before `run_async()` is fully visible. ADK does not cache or snapshot the tools list at agent creation. The tools list is read fresh on every `_preprocess_async` call (which happens at the start of every LLM step in the loop).

**One subtlety**: `len(agent.tools)` at line 421 determines `multiple_tools`. With `[repl_tool, set_model_response_tool, skill_toolset]`, `multiple_tools=True` (len=3). This is correct and affects only GoogleSearch/VertexAI workaround logic that is irrelevant here.

**No issues found.**

---

## Question 2: Tool Ordering — Does SkillToolset Position Matter?

**Verdict: ORDERING MATTERS, but the plan's ordering `[repl_tool, set_model_response_tool, skill_toolset]` is CORRECT.**

Here is exactly what `_process_agent_tools` does for each item in `agent.tools`:

```
For each tool_union in agent.tools:
  1. If it's a BaseToolset → call toolset.process_llm_request(tool_context, llm_request)
  2. Then call _convert_tool_union_to_tools(tool_union, ...) to get BaseTool list
  3. For each resolved BaseTool → call tool.process_llm_request(tool_context, llm_request)
```

With `[repl_tool, set_model_response_tool, skill_toolset]`, the processing order is:

| Step | Item | Action |
|------|------|--------|
| 1 | `repl_tool` (BaseTool) | Skip toolset check. `_convert_tool_union_to_tools` returns `[repl_tool]`. `repl_tool.process_llm_request()` adds `execute_code` function declaration to `llm_request.tools_dict`. |
| 2 | `set_model_response_tool` (BaseTool) | Skip toolset check. `_convert_tool_union_to_tools` returns `[set_model_response_tool]`. Default `process_llm_request()` adds `set_model_response` function declaration. |
| 3 | `skill_toolset` (BaseToolset) | **First**: `SkillToolset.process_llm_request()` fires — appends skill system instruction + `<available_skills>` XML to `llm_request.system_instruction` via `llm_request.append_instructions()`. **Then**: `_convert_tool_union_to_tools` calls `get_tools_with_prefix()` which calls `get_tools()` returning `[ListSkillsTool, LoadSkillTool, LoadSkillResourceTool, RunSkillScriptTool]` (plus any additional_tools from activated skills). Each of these then gets `process_llm_request()` called, adding their function declarations. `LoadSkillResourceTool` has an overridden `process_llm_request` that also handles binary content injection. |

**Why this ordering is correct**: The SkillToolset's system instruction injection (`_DEFAULT_SKILL_SYSTEM_INSTRUCTION` + XML skill listing) is appended via `llm_request.append_instructions()`, which concatenates to `system_instruction` with `\n\n`. Meanwhile, the `instructions.request_processor` (which resolves `static_instruction` and `instruction` fields) runs earlier as a **request_processor** in `SingleFlow.__init__` (line 44 of single_flow.py), well before `_process_agent_tools` is called at line 881. So the ordering is:

```
static_instruction → dynamic instruction → ... → _process_agent_tools:
   → execute_code declaration
   → set_model_response declaration
   → SkillToolset system instruction (appended to system_instruction)
   → list_skills, load_skill, load_skill_resource, run_skill_script declarations
```

The skill system instruction correctly comes AFTER the core RLM instructions. This is desirable because the model sees the RLM reasoning/REPL instructions first, then the skill discovery instructions as an addendum.

**One concern**: The `_output_schema_processor` (line 66 of single_flow.py) runs as a **request_processor** BEFORE `_process_agent_tools`. It checks `agent.output_schema` — since RLM-ADK intentionally does NOT set `output_schema` on the LlmAgent (the plan's comment at orchestrator.py:297-302 explains why), this processor is a no-op. The manually-created `SetModelResponseTool` in the tools list handles structured output instead. **No conflict.**

**Recommendation: No change needed to the plan's ordering.**

---

## Question 3: SkillToolset in Child Orchestrators

**Verdict: The plan SHOULD address this explicitly. Current gap.**

The plan wires `SkillToolset` in `orchestrator.py`'s `_run_async_impl()`. Since `create_child_orchestrator()` creates a new `RLMOrchestratorAgent` that also runs `_run_async_impl()`, the SkillToolset wiring code will execute for children too — IF the child has `enabled_skills` set.

However, looking at `create_child_orchestrator()` (agent.py lines 330-386): it does NOT pass `enabled_skills` to the child. The `RLMOrchestratorAgent` constructor defaults `enabled_skills` to `()` (empty tuple). So the plan's code:

```python
adk_skills = load_adk_skills(enabled_skills=self.enabled_skills or None)
# ...
if adk_skills:
    tools.append(SkillToolset(skills=adk_skills))
```

...will correctly produce an empty `adk_skills` list for children (since `self.enabled_skills = ()`), so SkillToolset will NOT be wired for children. The plan's code already handles this implicitly.

**But should children get skills?** That depends on the use case:

- **Pro**: If a child orchestrator (spawned by `llm_query()`) needs to use skill functions, those functions are already in the REPL globals (injected by `collect_skill_repl_globals` in the parent). BUT the child gets its own fresh `LocalREPL` (line 256 of orchestrator.py), so skill globals are NOT inherited.
- **Con**: Children are meant to be narrow-scope workers. Giving them the full SkillToolset (4 extra tools + system instruction overhead) dilutes their focus.

**Recommendation**:

1. **REPL globals gap**: The plan must ensure `collect_skill_repl_globals()` is also called for child REPLs. Currently the plan only injects skill globals after `repl.globals["LLMResult"] = LLMResult` (line 259), which runs for ALL orchestrators (parent and child) since they all run `_run_async_impl`. However, the filtering by `self.enabled_skills or None` means children get nothing. This needs a decision: either propagate `enabled_skills` to children, or inject skill globals unconditionally. The thread bridge makes `llm_query()` work from imported functions, but only if the functions are in the REPL namespace.

2. **SkillToolset for children**: Leave it OFF (current behavior is correct). Children should use `execute_code` to call skill functions directly, not the L1/L2 discovery tools. The discovery workflow is a root-agent concern.

3. **Propagate skill REPL globals to children**: Add `enabled_skills` forwarding in `create_child_orchestrator` OR (simpler) inject skill globals in `_run_async_impl` unconditionally regardless of `enabled_skills`. The latter is safer since the thread bridge already makes `llm_query()` available to all depths.

---

## Question 4: Workers and ParallelAgent — Do Workers Need Skills?

**Verdict: NO. Workers must NOT get SkillToolset. But there is a subtlety with the thread bridge.**

Workers are `LlmAgent` instances in a `ParallelAgent` batch. In the current architecture (post-dispatch refactor), `dispatch.py` spawns child `RLMOrchestratorAgent` instances, not raw `LlmAgent` workers in a `ParallelAgent`. The `WorkerPool` class has been aliased to `DispatchConfig` and no longer uses `ParallelAgent` at all.

Looking at dispatch.py line 106: `WorkerPool = DispatchConfig`. The `create_dispatch_closures` function spawns `create_child_orchestrator()` instances (line 299), not raw workers. There is no `ParallelAgent` usage in the current codebase for dispatch.

So the question about `ParallelAgent` workers is moot for the current architecture. Child orchestrators are the workers, and Question 3 covers their skill access.

**However**, if there is any residual `ParallelAgent` usage elsewhere (e.g., old worker pool code), those workers should definitely NOT get SkillToolset. They are leaf-level LLM calls that should respond directly.

**Recommendation: No action needed. The plan is correct as-is for the current dispatch architecture.**

---

## Question 5: SkillToolset's `additional_tools` Feature

**Verdict: Interesting but premature. Do NOT use for now.**

`SkillToolset.additional_tools` works as follows (skill_toolset.py lines 680-784):

1. Constructor accepts `additional_tools: list[ToolUnion]` — tools/toolsets available for dynamic activation.
2. When a skill is loaded via `LoadSkillTool`, its name is added to `_adk_activated_skill_{agent_name}` in session state.
3. On each `get_tools()` call, `_resolve_additional_tools_from_state()` checks activated skills' `frontmatter.metadata.adk_additional_tools` for tool names to expose.
4. These dynamically-resolved tools are returned alongside the 4 core skill tools.

The idea of gating `execute_code` behind skill activation is architecturally unsound for RLM-ADK because:

- `execute_code` is the PRIMARY tool. The reasoning agent needs it from step 1, before any skill is loaded.
- Skills are discovered USING `execute_code` (the agent writes code to explore, then decides to load a skill).
- Gating the core execution tool behind skill activation inverts the dependency.

**Where `additional_tools` COULD be useful**: If a skill needs a specialized tool (e.g., a web scraper, a database connector) that should only be exposed after the skill is loaded. This is a future concern.

**Recommendation: Do NOT use `additional_tools` in this plan. Note it as a future extension point in code comments.**

---

## Question 6: `include_contents` Interaction with Skill Activation State

**Verdict: POTENTIAL ISSUE. Activation state persists, but child agent names differ.**

Here is the activation flow:

1. `LoadSkillTool.run_async()` writes `tool_context.state[f"_adk_activated_skill_{agent_name}"]` (skill_toolset.py line 153-158).
2. `agent_name` comes from `tool_context.agent_name`, which reads `invocation_context.agent.name`.
3. `SkillToolset.get_tools()` calls `_resolve_additional_tools_from_state()` which reads `readonly_context.state.get(f"_adk_activated_skill_{agent_name}", [])`.

For the root reasoning_agent:
- `agent_name = "reasoning_agent"` (from agent.py line 200 default)
- State key: `_adk_activated_skill_reasoning_agent`
- State persists in session across LLM steps (since `tool_context.state` writes go through ADK event tracking)

For child reasoning agents:
- `agent_name = f"child_reasoning_d{depth}"` (agent.py line 359)
- State key: `_adk_activated_skill_child_reasoning_d1` (etc.)
- Different key from parent, so activation is NOT shared.

Since children don't get SkillToolset (Question 3), this is moot. But if children were ever given SkillToolset:

- `include_contents='none'` does NOT affect state. State persists in `session.state`, not in contents.
- The state key includes agent name, so parent's activations would NOT be visible to children (different agent name).
- Children would need to re-activate skills independently.

**Recommendation: No issue for the current plan. If children are given SkillToolset in the future, consider using a depth-agnostic state key (or propagating parent activations).**

---

## Question 7: Tool Count — 6 Tools Too Many?

**Verdict: NOT A PROBLEM, but consider a mitigation.**

With the plan, the reasoning_agent would have these tool declarations visible to the model:

| # | Tool | Source |
|---|------|--------|
| 1 | `execute_code` | REPLTool |
| 2 | `set_model_response` | SetModelResponseTool |
| 3 | `list_skills` | SkillToolset |
| 4 | `load_skill` | SkillToolset |
| 5 | `load_skill_resource` | SkillToolset |
| 6 | `run_skill_script` | SkillToolset |

**Model confusion risk**: Gemini models handle 6 tools well. The real risk is not count but **semantic overlap**: `run_skill_script` executes code (like `execute_code`), `load_skill_resource` reads files (like `execute_code` with `open()`). The model might try to use skill tools when it should use `execute_code`.

**Mitigations already in place**:
- `SkillToolset.process_llm_request()` injects a clear system instruction (`_DEFAULT_SKILL_SYSTEM_INSTRUCTION`) that explains when to use each tool.
- The RLM static instruction already tells the model to use `execute_code` as its primary actuator.

**Additional mitigation to consider**: In the RLM static instruction, add a brief disambiguation:
```
The `list_skills`, `load_skill`, `load_skill_resource`, and `run_skill_script` tools are for
DISCOVERING available skills before you use them. Once you know what skill functions are available,
call them via execute_code like any other Python function.
```

**Recommendation**: The tool count is fine. Add a brief instruction disambiguation to prevent the model from using `run_skill_script` instead of `execute_code` for routine code execution. `run_skill_script` materializes a temp directory and executes in isolation — it is NOT a substitute for `execute_code`.

---

## Summary of Recommendations

### Must-Fix (Before Implementation)

1. **Skill REPL globals for children** (Q3): Decide whether child orchestrators should have skill functions in their REPL namespace. Currently they won't because `enabled_skills=()` for children. If skill functions should be callable at depth > 0 via the thread bridge, either:
   - (A) Propagate `enabled_skills` from parent to child in `create_child_orchestrator`, OR
   - (B) Inject ALL skill globals unconditionally (ignore `enabled_skills` for REPL injection, only use it for SkillToolset filtering).

   Option (B) is simpler and consistent with the thread bridge's goal of making `llm_query()` callable from any depth.

### Should-Fix (Quality)

2. **Instruction disambiguation** (Q7): Add 2-3 sentences to the RLM static instruction explaining the boundary between `execute_code` (primary tool for all code execution) and the 4 skill discovery tools (for discovering and reading skill documentation only).

3. **Document `additional_tools` as future extension** (Q5): Add a code comment in the orchestrator's SkillToolset wiring explaining that `additional_tools` is intentionally not used now but available for future per-skill tool gating.

### No Change Needed

4. **`object.__setattr__` wiring** (Q1): Confirmed correct. ADK reads `agent.tools` at call time.
5. **Tool ordering** (Q2): `[repl_tool, set_model_response_tool, skill_toolset]` is correct. SkillToolset system instruction appends after core RLM instructions.
6. **Worker/ParallelAgent** (Q4): Current architecture uses child orchestrators, not ParallelAgent workers. No SkillToolset needed.
7. **`include_contents` interaction** (Q6): Activation state uses agent-name-scoped keys. No cross-agent leakage. Children don't get SkillToolset, so moot.

### Architecture Diagram (Post-Plan)

```
_preprocess_async (every LLM step):
  ├── request_processors (in order):
  │     ├── basic (model, config)
  │     ├── instructions (static_instruction → system_instruction,
  │     │                  dynamic instruction → user content)
  │     ├── contents (conversation history)
  │     ├── _output_schema_processor (NO-OP: agent.output_schema is None)
  │     └── ... (other processors)
  │
  ├── _resolve_toolset_auth (SkillToolset has no auth → no-op)
  │
  └── _process_agent_tools:
        ├── repl_tool (BaseTool)
        │     └── process_llm_request → adds execute_code declaration
        ├── set_model_response_tool (BaseTool)
        │     └── process_llm_request → adds set_model_response declaration
        └── skill_toolset (BaseToolset)
              ├── process_llm_request → appends skill system instruction + XML
              └── get_tools_with_prefix → [list_skills, load_skill,
                    load_skill_resource, run_skill_script]
                    └── each.process_llm_request → adds function declaration
                    └── LoadSkillResourceTool.process_llm_request →
                          also handles binary content injection
```

### `_OutputSchemaRequestProcessor` Non-Conflict Confirmation

The `_OutputSchemaRequestProcessor` (runs as a request_processor BEFORE tool processing) checks:
```python
if not agent.output_schema or not agent.tools or can_use_output_schema_with_tools(...):
    return  # NO-OP
```

Since RLM-ADK sets `output_schema=None` on the LlmAgent (the orchestrator manually creates `SetModelResponseTool`), this processor is always a no-op. No duplicate `set_model_response` tool injection. This is a safe coexistence with the plan's approach.
