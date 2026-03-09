**Findings**

1. High: root/child orchestration does not persist full LLM outputs, only the extracted final answer and coarse token counts.
[orchestrator.py#L106](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L106)
[RLMOrchestratorAgent._run_async_impl#L228](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L228)
[orchestrator.py#L283](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L283)
What to update:
- Add an orchestrator-level capture path for visible model text, thought text, and full structured payload per depth.
- Persist more than `final_answer`; include `reasoning_summary` and raw/parsed output by depth.

2. High: REPL code submitted by the model is not captured as observability payload.
[repl_tool.py#L86](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L86)
[repl_tool.py#L89](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L89)
[repl_tool.py#L195](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L195)
What to update:
- Capture `args["code"]` before execution.
- Persist code preview/hash/chars and a token estimate or provider token count if available.
- Include depth-scoped submitted-code state, not just `LAST_REPL_RESULT`.

3. High: child-layer LLM outputs/tokens are dropped during recursive dispatch.
[dispatch.py#L68](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L68)
[dispatch.py#L106](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L106)
[dispatch.py#L142](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L142)
[dispatch.py#L196](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L196)
[dispatch.py#L228](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L228)
[dispatch.py#L290](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L290)
What to update:
- Populate `LLMResult` with child output text, thought tokens, finish reason, input/output tokens.
- Stop writing hardcoded zeros into REPL trace entries.
- Actually use `call_log_sink` so parent REPL results can include child call records.

4. High: state schema is missing the keys needed to store full output observability at parent and child depths.
[state.py#L19](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L19)
[state.py#L40](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L40)
[state.py#L50](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L50)
[state.py#L79](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L79)
[state.py#L86](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L86)
[state.py#L121](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L121)
[state.py#L129](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L129)
What to create/update:
- New keys for thought tokens, visible output text, thought text, full structured output, submitted REPL code, REPL code token estimate, and child-layer output summaries.
- Depth/fanout-aware helpers for child observability keys.
- Decide which new keys belong in `DEPTH_SCOPED_KEYS`.

5. High: core reasoning callbacks ignore thought-token accounting even though the agent enables thoughts.
[agent.py#L151](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L151)
[agent.py#L199](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L199)
[reasoning.py#L143](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L143)
[observability.py#L160](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py#L160)
What to update:
- Extend `reasoning_after_model` and `ObservabilityPlugin.after_model_callback` to read `thoughts_token_count`.
- Persist visible output vs thought output as separate observability fields.

6. Medium: trace/persistence plugins only store summaries or root-level keys, so recursive child REPL/output observability is incomplete.
[repl_tracing.py#L30](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py#L30)
[repl_tracing.py#L39](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py#L39)
[trace.py#L21](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py#L21)
[trace.py#L101](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py#L101)
[sqlite_tracing.py#L711](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L711)
[sqlite_tracing.py#L824](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L824)
What to update:
- Make `REPLTracingPlugin` read depth-suffixed `LAST_REPL_RESULT@dN`.
- Extend `REPLTrace` summary/detail to include submitted-code metrics and child-call token data.
- Expand SQLite tool/model rows beyond `result_preview` and coarse booleans.

7. Medium: current types cannot carry the missing observability fields end-to-end.
[types.py#L12](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py#L12)
[types.py#L50](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py#L50)
[types.py#L135](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py#L135)
[types.py#L165](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py#L165)
What to update:
- `ReasoningOutput`: persistable full payload fields if desired.
- `LLMResult`: thought tokens, visible/thought text, parsed structured payload.
- `RLMChatCompletion` / `REPLResult`: submitted code metadata and child output token fields.

8. Medium: there is already a reference implementation for thought/output extraction; reuse it instead of inventing a second parser.
[context_snapshot.py#L108](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L108)
[context_snapshot.py#L129](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L129)
[context_snapshot.py#L156](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L156)
What to reuse:
- `thoughts_token_count` extraction.
- response splitting into visible output and thought text.

**Architecture map to hand the implementation agent**
[repomix-architecture-flow-compressed.xml#L241](/home/rawley-stanhope/dev/rlm-adk/repomix-architecture-flow-compressed.xml#L241)
[repomix-architecture-flow-compressed.xml#L690](/home/rawley-stanhope/dev/rlm-adk/repomix-architecture-flow-compressed.xml#L690)
[repomix-architecture-flow-compressed.xml#L890](/home/rawley-stanhope/dev/rlm-adk/repomix-architecture-flow-compressed.xml#L890)
[repomix-architecture-flow-compressed.xml#L1305](/home/rawley-stanhope/dev/rlm-adk/repomix-architecture-flow-compressed.xml#L1305)
[repomix-architecture-flow-compressed.xml#L1473](/home/rawley-stanhope/dev/rlm-adk/repomix-architecture-flow-compressed.xml#L1473)

**Focused file list**
- [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py)
- [rlm_adk/state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py)
- [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py)
- [rlm_adk/tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py)
- [rlm_adk/callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py)
- [rlm_adk/plugins/observability.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py)
- [rlm_adk/plugins/sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py)
- [rlm_adk/plugins/repl_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py)
- [rlm_adk/plugins/context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py)
- [rlm_adk/repl/trace.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py)
- [rlm_adk/repl/local_repl.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py)
- [rlm_adk/types.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py)
- [rlm_adk/agent.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py)

**Additional Notable Gaps From `observability_gaps.md`**

9. Medium: `obs:child_total_batch_dispatches` is produced by dispatch but not persisted into the SQLite `traces` summary row.
[dispatch.py:322](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py:322)
[sqlite_tracing.py:586](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py:586)
[sqlite_tracing.py:613](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py:613)
What to update:
- Add `obs:child_total_batch_dispatches` to the SQLite trace enrichment path so recursive dispatch volume is queryable alongside child output capture.

10. Medium: retry/backoff observability is incomplete at attempt-level, especially for SDK-internal retries.
[agent.py:123](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py:123)
[agent.py:143](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py:143)
[orchestrator.py:224](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py:224)
[orchestrator.py:257](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py:257)
What to update:
- Add attempt-level retry/backoff counters and delay metrics where exposed.
- Treat SDK-internal retry visibility as best-effort, since some of it may require lower-level instrumentation or monkey-patching.

11. Medium: AST rewrite failure count/classification is not tracked, only successful rewrite count/time.
[repl_tool.py:121](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py:121)
[repl_tool.py:128](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py:128)
[repl_tool.py:163](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py:163)
What to update:
- Add rewrite failure counters and basic failure classification so failed REPL-output capture can be distinguished from successful-but-empty execution.

**Implementation order**
1. Add new state keys and depth/fanout helpers in [state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py), including keys for thought output, submitted REPL code, rewrite failures, and retry/backoff metrics.
2. Capture reasoning visible/thought outputs in [callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py) and [orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py), and persist the full structured payload per depth.
3. Capture submitted REPL code and rewrite-failure telemetry in [tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py), with supporting detail in [rlm_adk/repl/trace.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py) as needed.
4. Propagate child output/token metadata through [dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py) and [types.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py), including `call_log_sink` plumbing and `obs:child_total_batch_dispatches` continuity.
5. Persist/query the new fields in [plugins/observability.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py), [plugins/sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py), and [plugins/repl_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py), making sure SQLite trace enrichment includes `obs:child_total_batch_dispatches`.
6. Add attempt-level retry/backoff observability in [agent.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py) and [orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py), treating SDK-internal retries as best-effort instrumentation.

If you want, I can turn this into a concrete implementation checklist or start the patch.

---