# ADK Python v1.27.0 — Opportunity Review Summary

**Release date:** March 12, 2026
**Release notes:** [ai_docs/adk_v1.27_updates.md](../ai_docs/adk_v1.27_updates.md)
**Source:** https://github.com/google/adk-python/releases/tag/v1.27.0

---

## Proposal Documents

Six Opportunity-Agent teammates reviewed logical sections of the RLM-ADK codebase against v1.27.0 changes. Each proposal lives in `rlm_adk_docs/adk_v1_27_0_update/`:

| # | Proposal | File | Effort | Impact | Risk |
|---|----------|------|--------|--------|------|
| 1 | SchemaUnion Output | [updated_adk_schema_union.md](adk_v1_27_0_update/updated_adk_schema_union.md) | S | Medium | Low |
| 2 | BashTool & Skills | [updated_adk_bash_tool_and_skills.md](adk_v1_27_0_update/updated_adk_bash_tool_and_skills.md) | S | **High** | Medium |
| 3 | Observability OTEL | [updated_adk_observability_otel.md](adk_v1_27_0_update/updated_adk_observability_otel.md) | S-M | Medium-High | Low-Medium |
| 4 | Session & State | [updated_adk_session_and_state.md](adk_v1_27_0_update/updated_adk_session_and_state.md) | S | **High** | Low |
| 5 | Callbacks & Retry | [updated_adk_callbacks_and_retry.md](adk_v1_27_0_update/updated_adk_callbacks_and_retry.md) | S | Medium | **Medium** |
| 6 | A2A & Multi-Agent | [updated_adk_a2a_multi_agent.md](adk_v1_27_0_update/updated_adk_a2a_multi_agent.md) | S-L | Medium | Medium |

---

## Key Findings Per Proposal

### 1. SchemaUnion Output (`types.SchemaUnion` as `output_schema`)

ADK v1.27.0 widens `LlmAgent.output_schema` from `type[BaseModel]` to `types.SchemaUnion` (includes `type[BaseModel] | dict | google.genai.types.Schema`).

- **11 locations** across `dispatch.py`, `agent.py`, `orchestrator.py`, and `types.py` currently constrain `output_schema` to `type[BaseModel]` or `type`
- **Bottleneck:** `SetModelResponseTool.__init__` calls Pydantic-only methods (`model_fields`, `model_validate`). Proposed two-phase approach: shim `to_pydantic_model()` for dict/Schema inputs now, remove once ADK handles SchemaUnion natively
- BUG-13 patch, WorkerRetryPlugin, and `LLMResult.parsed` are schema-type-agnostic — no changes needed
- **User benefit:** REPL code can pass raw JSON Schema dicts to `llm_query(output_schema=...)` instead of defining Pydantic models at runtime

### 2. BashTool & Skills

ADK v1.27.0 adds `ExecuteBashTool` (BashTool), `RunSkillScriptTool`, and SkillToolset composition enhancements.

- **BashTool is the highest-value single opportunity.** Currently the reasoning agent invokes CLI tools via `subprocess.run()` inside REPL code — no policy enforcement, no dedicated observability. BashTool adds prefix-based command allowlisting, structured output, and discrete tool calls in the event stream
- **Mandatory user confirmation must be bypassed** for autonomous RLM operation — proposal includes an `RLMBashTool` subclass pattern that auto-approves policy-validated commands
- Enables headless coding agent invocation (e.g., `claude` CLI, `adk run`, `repomix`, `ruff`, `pytest`) as first-class ADK tools
- `RunSkillScriptTool` complements (not replaces) existing source-expandable REPL skills — REPL skills need `llm_query` and shared state; script skills are better for isolated CLI workflows
- `SkillToolset` composition deferred — with only 3 registered skills, token savings from dynamic loading are negligible
- **Security:** BashTool executes real subprocesses. Mitigated by strict `BashToolPolicy` prefix restrictions, `shell=False` + `shlex.split`, workspace isolation

### 3. Observability OTEL

ADK v1.27.0 adds new OTel span attributes, tool error code capture, and BQ plugin enhancements.

- **Automatic on upgrade:** Langfuse and Google Cloud Tracing plugins get `gen_ai.agent.version`, `gen_ai.tool.definitions`, and tool error codes for free
- **Gap:** Child dispatch errors inside `_run_child()` are caught and wrapped as `LLMResult` — invisible to ADK's automatic tool error capture. Needs custom OTel span enrichment in `REPLTool.run_async()`
- 5 concrete enhancements proposed: agent version propagation, tool error summary via `after_tool_callback`, BQ plugin config pass-through, custom OTel span enrichment for child errors
- Includes a 6-step upgrade risk assessment covering BUG-13 patch compat, `_invocation_context` private API stability, and instrumentor version compatibility

### 4. Session & State

ADK v1.27.0 adds row-level locking, temp-scoped state fix, EventCompaction, durable runtime, and artifact dict support.

- **EventCompaction is the #1 quick win.** Wire `EventsCompactionConfig` into `create_rlm_app()` behind `RLM_COMPACTION_TOKEN_THRESHOLD` env var to prevent context window overflow in multi-turn sessions. Effort S, Impact High, Risk Low
- **WAL pragmas still needed** — ADK doesn't set WAL mode; `_SQLITE_STARTUP_PRAGMAS` in `agent.py` remains complementary to row-level locking
- **Temp-scoped state fix does NOT simplify AR-CRIT-001** — the accumulator pattern in `dispatch.py` exists because closures lack `ToolContext`/`CallbackContext`, a different problem than temp-state visibility
- Session validation and artifact dict support are automatic on upgrade
- **Durable runtime deferred** — REPL state loss on resumption + non-idempotent tool calls make it unusable until REPL checkpointing is implemented

### 5. Callbacks & Retry (BUG-13 critical path)

ADK v1.27.0 refactors internal callback infrastructure and improves LiteLLM support.

- **BUG-13 patch is still needed** — no v1.27.0 changelog item addresses the underlying premature worker termination on `ToolFailureResponse` dicts
- **P0 risk:** The HITL/auth "reusable function extraction" refactoring touches `_postprocess_handle_function_calls_async` — the same function containing the BUG-13 call site (`base_llm_flow.py:849`). If the call site changes from module-attribute lookup to direct import, the patch breaks **silently**
- 4-step verification protocol provided for safe upgrade
- LiteLLM `thought_signature` preservation and expanded reasoning extraction require no code changes — existing `reasoning_after_model` callback handles thought parts generically
- Live mode tool callback fixes have zero immediate impact (RLM uses standard flow)

### 6. A2A & Multi-Agent (strategic/vision)

ADK v1.27.0 adds `RemoteA2aAgent`, `A2aAgentExecutor`, and A2A-ADK conversion utilities.

- `RemoteA2aAgent` fits cleanly as an alternative dispatch target alongside in-process child orchestrators
- **Caveat:** `to_a2a()` defaults to `InMemorySessionService` — breaks RLM observability/persistence; must pass custom Runner
- **Thought propagation gap:** `adk:thought` metadata is serialized but not restored on the receiving side
- State isolation means depth-scoped keys and `user_ctx` REPL globals don't cross A2A boundaries
- Structured output validation (WorkerRetryPlugin, BUG-13 patch) can't be enforced on remote agents
- **Phased approach:** Expose RLM as A2A service (~1 day) → Consume external agents (~3-5 days) → Full hybrid dispatch with Polya integration (~2 weeks)

---

## Recommended Priority Order

| Priority | Opportunity | Effort | Impact | Risk | Rationale |
|----------|-----------|--------|--------|------|-----------|
| **P0** | BUG-13 verification | S | Medium | Medium | Must happen before any upgrade — silent breakage risk |
| **P1** | EventCompaction | S | High | Low | Immediate value, prevents context window overflow |
| **P2** | BashTool | S | High | Medium | Enables headless CLI/coding agent invocation as first-class tools |
| **P3** | SchemaUnion | S | Medium | Low | Unblocks dict-based schemas in REPL `llm_query()` |
| **P4** | OTEL enhancements | M | Medium-High | Low-Medium | Incremental, do alongside upgrade |
| **P5** | A2A | L | Medium | Medium | Vision/roadmap — phase after core upgrade stabilizes |

---

## Upgrade Checklist

1. **Pre-upgrade:** Run BUG-13 verification protocol (see [callbacks proposal](adk_v1_27_0_update/updated_adk_callbacks_and_retry.md))
2. **Upgrade:** `pip install google-adk==1.27.0`
3. **Verify:** Run default test suite (`.venv/bin/python -m pytest tests_rlm_adk/`)
4. **Verify:** Confirm BUG-13 patch installs (`_rlm_patched` attribute on `get_structured_model_response`)
5. **Wire:** EventCompaction env var (`RLM_COMPACTION_TOKEN_THRESHOLD`)
6. **Wire:** BashTool as additional reasoning agent tool (behind `RLM_BASH_TOOL` env var)
7. **Wire:** SchemaUnion type widening in `dispatch.py` and `agent.py`
8. **Observe:** Check Langfuse/Cloud Trace for new span attributes automatically

---

*Generated 2026-03-17 by 6 parallel Opportunity-Agent teammates reviewing RLM-ADK against ADK Python v1.27.0.*
