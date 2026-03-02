  ---
  ADK Runtime & Event Loop Expert — Review Report

  CRITICAL Findings

  1. include_contents='none' + collapsed loop = stale MESSAGE_HISTORY (Confidence: 95)
  - Today the orchestrator writes a fresh MESSAGE_HISTORY state delta before each reasoning_agent.run_async(ctx) call. With the collapsed loop, run_async runs once and drives all steps internally. The reasoning_before_model callback will read a stale MESSAGE_HISTORY on every step after the first tool call.
  - The plan mentions switching to include_contents='default' but doesn't specify how reasoning_before_model must be substantially simplified or removed to avoid duplicating conversation history.

  2. Worker event queue drain is insufficient (Confidence: 95)
  - The plan drains worker events once-per-event inside async for event. But worker events deposited by llm_query_batched_async during a REPLTool call sit in the queue until the next event — which could be the terminal set_model_response event. The Runner commits the final response before seeing worker accounting events.
  - The current code has three explicit drain points (post-reasoning, mid-iteration after REPL, before final answer). All three existing drain-test assertions (TestFinalAnswerDrain, TestMidIterationDrain, TestMaxIterationsDrain) will break.

  3a. max_llm_calls counts ALL calls including workers (Confidence: 92)
  - Formula APP_MAX_ITERATIONS * 2 will be exhausted prematurely. 5 parallel workers = 5 calls per "iteration." With max_iterations=30 and max_llm_calls=60, a single multi-worker batch burns the budget in ~12 iterations.

  3b. max_llm_calls exceeded = abort, not graceful termination (Confidence: 92)
  - Unlike the current max_iterations path which yields a final exhausted-error Event, exceeding max_llm_calls simply terminates the step loop. Downstream consumers waiting for is_final_response() may hang.

  3c. RunConfig wiring unspecified (Confidence: 92)
  - APP_MAX_ITERATIONS is a session-state key set at invocation time, not available at Runner construction. The plan doesn't specify where the wiring happens.

  4a. output_schema SUPPRESSES tools on LlmAgent (Confidence: 85)
  - Setting output_schema=ReasoningOutput causes _OutputSchemaRequestProcessor to disable all other tools at the API call level. The model will never be able to call execute_code. This is a fatal design flaw in Phase 3 as written.

  WARNING Findings

  6a. LoopAgent + exit_loop is the ADK-native primitive (Confidence: 85)
  - The plan doesn't consider LoopAgent wrapping the LlmAgent with exit_loop alongside execute_code. This gives multi-iteration reasoning with built-in max_iterations guard, predictable final events, and no interference with the event queue drain pattern.

  INFO Findings

  - 5. run_async async generator pattern is correct and already in use today
  - 4b. No race condition for sequential set_model_response
  - 6b. EventActions.end_of_agent unleveraged but not blocking

  ---
  The Finding 4a (output_schema suppresses tools) is potentially the biggest issue — it would make REPLTool unreachable. I'll cross-reference this with the Input/Output Schema expert's findings when they come back.

✻ Crunched for 2m 2s · 2 background tasks still running (↓ to manage)

● Agent "ADK events expert review" completed

● Events expert is back. Two down, two to go. Let me check on the remaining agents.

● Bash(python3 << 'PYEOF'
      import json, os…)
  ⎿  callbacks-resumed: 42 lines, last type=user
     input-output-schema: 80 lines, last type=user

● Both still running. Here's the ADK Events Expert report while we wait:

  ---
  ADK Events Expert — Review Report

  CRITICAL Findings

  1. Worker event_queue drain eliminated with no replacement (Confidence: 100)
  - The dispatch closures push worker events into event_queue during llm_query_batched_async, which runs inside REPLTool.run_async. But REPLTool.run_async is a coroutine that returns a dict — it has no mechanism to yield events mid-execution.
  - The collapsed orchestrator's async for event loop only yields events that ADK's LlmFlow produces — not events in the application-level event_queue.
  - After reasoning_agent.run_async(ctx) exhausts, there's no post-loop drain site.
  - All worker state_delta events are silently leaked.

  2. Worker state_delta never reaches SessionService.append_event (Confidence: 100)
  - Direct consequence of #1. Worker accounting keys (WORKER_DISPATCH_COUNT, OBS_WORKER_TOTAL_DISPATCHES, dispatch latency, token accounting) go stale for the entire lifetime of the collapsed orchestrator.
  - Observability plugins and dashboard will see zeros or stale values.

  3. output_schema + REPLTool coexistence on workers unverified (Confidence: 92)
  - Phase 4 sets both worker.output_schema and worker.tools = [REPLTool]. The behavior of _OutputSchemaRequestProcessor when tools is non-empty is undocumented in the plan.
  - The test test_worker_with_repl_tool_and_output_schema asserts len(worker.tools) == 1 before the processor runs — it doesn't test the runtime state.
  - Cleanup finally block resets output_schema = None but may leave stale REPLTool on workers.

  WARNING Findings

  4. Event ordering non-deterministic — Worker events from inside REPLTool.run_async arrive during ADK's step-loop, making commit ordering relative to next LLM call unpredictable.

  5. Dispatch-level telemetry silently dropped — No migration path to tool_context.state writes proposed. This is the architecturally cleaner fix but the plan doesn't address it.

  6. output_key deserialization unspecified — Phase 3 says "Extract final_answer from structured output via output_key in state" but output_key writes serialized JSON, not final_answer directly. No parsing code is shown.

  7. DEPTH_SCOPED_KEYS includes dead keys — LAST_REASONING_RESPONSE and CURRENT_CODE_BLOCKS are in the set but Phase 3 removes them from the write path.

  INFO Findings

  8. @d{N} suffix keys correctly avoid temp: stripping — no regression.

  9. REPLTool.run_async lacks a top-level exception handler — unhandled exceptions (e.g., asyncio.CancelledError during async REPL exec) would bypass the {"stderr": "..."} return contract.

  ---
  A strong convergence is emerging between the Runtime and Events experts. The two biggest themes:

  1. The event queue drain pattern is fundamentally incompatible with the collapsed orchestrator — this needs an architectural decision: either preserve drain visibility or migrate worker telemetry to tool_context.state writes inside REPLTool.
  2. output_schema + tools coexistence — both agents flagged this as problematic. The Input/Output Schema expert will hopefully confirm whether _OutputSchemaRequestProcessor actually suppresses tools or just injects alongside them.

● Agent "ADK input/output schema review" completed

● Input/Output Schema expert is back. Let me check on the last remaining agent (callbacks resumed).

● Bash(python3 << 'PYEOF'
      import json…)
  ⎿  Total lines: 43, last type: assistant

     Found report (19352 chars):
     … +56 lines (ctrl+o to expand)

● Agent "Resume callbacks expert review" completed

● All four agents have completed. Here's the full synthesized report:

  ---
  Consolidated Review — All 4 Expert Agents

  CRITICAL Findings (consensus across agents)

  C1. reasoning_before_model is incompatible with the collapsed orchestrator (Callbacks + Runtime — Confidence: 92-97)

  Three interrelated issues:
  - The callback overwrites llm_request.contents on every LLM turn, including tool-response turns. Under the collapsed loop, this wipes ADK's accumulated tool call/response context — the model will never see REPL output.
  - Switching to include_contents='default' AND retaining the llm_request.contents = contents write are mutually exclusive. The plan says to do both.
  - No mechanism defined to distinguish turn 1 (inject history) from turn N (let ADK handle it).
  - The _extract_adk_dynamic_instruction helper will concatenate the entire conversation into system_instruction under 'default'.

  Fix: Must pick Option B — switch to include_contents='default', delete the llm_request.contents = contents line, keep only system_instruction merge and token accounting. Add a first-turn guard or remove the callback entirely.

  ---
  C2. Worker event queue drain has no replacement (Events + Runtime — Confidence: 95-100)

  - REPLTool.run_async is a coroutine returning a dict — it cannot yield events.
  - The collapsed async for event loop only sees events from ADK's LlmFlow, not the application-level event_queue.
  - All worker state_delta events (dispatch counts, latency, token accounting) are silently leaked.
  - Three existing drain-test assertions (TestFinalAnswerDrain, TestMidIterationDrain, TestMaxIterationsDrain) will break.

  Fix: Either preserve drain visibility (orchestrator retains knowledge of when execute_code calls complete) or migrate worker telemetry entirely to tool_context.state writes inside REPLTool — the architecturally cleaner path.

  ---
  C3. output_schema + empty tools on workers breaks structured output (I/O Schema — Confidence: 100)

  Phase 4 proposes worker.output_schema = output_schema. But when worker_repl is None (plain structured output, no REPL), worker.tools remains []. The processor checks not agent.tools → True → early return — no SetModelResponseTool gets injected. The model emits raw JSON text instead of a tool call. LLMResult.parsed will always be None.

  Fix: Keep explicit SetModelResponseTool injection for the no-REPL case:
  if output_schema is not None:
      worker.output_schema = output_schema
      if worker_repl is None:
          worker.tools = [SetModelResponseTool(output_schema)]  # processor won't fire
      # ...

  ---
  C4. RunConfig.max_llm_calls is unsuitable as primary safety (Runtime — Confidence: 92)

  - Counts ALL calls globally including workers — formula APP_MAX_ITERATIONS * 2 will be exhausted prematurely with parallel worker batches.
  - Exceeding the limit aborts without yielding a final answer event — downstream consumers hang.
  - APP_MAX_ITERATIONS is a session-state key, not available at Runner construction time — wiring is unspecified.
  - Alternative: LoopAgent + exit_loop is the ADK-native primitive for bounded iteration with predictable final events.

  ---
  WARNING Findings

  ┌─────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬─────────────────────────────────┐
  │  #  │                                                                  Finding                                                                   │             Source              │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W1  │ reasoning_after_model token accounting (REASONING_INPUT_TOKENS/OUTPUT_TOKENS) will go dark if callback is removed without relocating logic │ Callbacks                       │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W2  │ on_tool_error_callback on workers has no tool-name guard — REPL errors trigger spurious structured-output retry reflection                 │ Callbacks                       │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W3  │ ReasoningOutput schema missing finish_reason/repl_call_count — insufficient for observability                                              │ I/O Schema                      │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W4  │ output_key writes serialized JSON string, not dict — deserialization path unspecified in Phase 3                                           │ Callbacks + I/O Schema + Events │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W5  │ DEPTH_SCOPED_KEYS includes LAST_REASONING_RESPONSE and CURRENT_CODE_BLOCKS which Phase 3 removes from write path — dead keys               │ Events                          │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W6  │ Dispatch-level telemetry silently dropped with no migration to tool_context.state                                                          │ Events                          │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W7  │ Reasoning agent missing disallow_transfer_to_parent/peers flags                                                                            │ I/O Schema                      │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W8  │ Worker event ordering non-deterministic relative to state commits under collapsed loop                                                     │ Events                          │
  ├─────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────────────────────┤
  │ W9  │ Plan does not verify synthesized SetModelResponseTool name matches "set_model_response" guard in WorkerRetryPlugin                         │ Callbacks                       │
  └─────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴─────────────────────────────────┘

  Test Gaps

  ┌─────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬────────────────────────┐
  │  #  │                                                         Gap                                                         │         Source         │
  ├─────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────┤
  │ T1  │ No test for multi-turn contents integrity (tool-response turn must retain prior tool context)                       │ Callbacks              │
  ├─────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────┤
  │ T2  │ TestWorkerRetryPluginUnchanged calls omit required tool_args and tool_context kwargs — will raise TypeError         │ Callbacks              │
  ├─────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────┤
  │ T3  │ No test for output_key deserialization roundtrip (state["reasoning_output"] → ReasoningOutput.final_answer)         │ Callbacks + I/O Schema │
  ├─────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────┤
  │ T4  │ No test that worker with output_schema + empty tools does NOT get SetModelResponseTool injected (the C3 regression) │ I/O Schema             │
  ├─────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼────────────────────────┤
  │ T5  │ test_worker_with_repl_tool_and_output_schema asserts pre-processor state, not runtime state                         │ Events                 │
  └─────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴────────────────────────┘

  INFO Findings

  - output_schema + REPLTool coexistence on reasoning agent works correctly — processor injects SetModelResponseTool into the request, not agent.tools. No duplication with REPLTool. (I/O Schema overrides Runtime's concern here — the I/O Schema expert traced the actual source)
  - @d{N} suffix keys correctly avoid temp: stripping.
  - run_async async generator pattern is correct and already in use.
  - REPLTool.run_async lacks a top-level exception handler for asyncio.CancelledError etc.

  Key Correction: Finding 4a from Runtime Agent

  The Runtime agent flagged "output_schema suppresses tools" as CRITICAL. The I/O Schema agent refuted this after tracing the actual ADK source: _OutputSchemaRequestProcessor fires when output_schema is set AND tools is non-empty AND can_use_output_schema_with_tools() returns False (always False on Gemini API). It injects SetModelResponseTool into the request, not agent.tools.
  REPLTool remains reachable. The design is structurally sound for Phase 3's reasoning agent.
