# RLM ADK Observability Implementation Summary

## Architecture Overview

**RLM ADK** (Recursive Language Models on Agent Development Kit) is a port of the original RLM system onto Google's ADK framework. The core idea: an LLM reasons iteratively inside a REPL loop, executing Python code blocks that can themselves dispatch sub-LLM queries (recursion). The system terminates when the LLM produces a `FINAL(...)` or `FINAL_VAR(...)` answer, or when max iterations are exhausted.

### Component Map

```
agent.py (RLMAdkEngine / root_agent)
  |
  +-- orchestrator.py (RLMOrchestratorAgent: BaseAgent)
  |     |   Main iteration loop: prompt -> reason -> extract code -> REPL exec -> repeat
  |     |
  |     +-- reasoning_agent (LlmAgent, depth=0)
  |     |     callbacks: reasoning.py (before_model / after_model)
  |     |
  |     +-- default_answer_agent (LlmAgent, fallback)
  |     |     callbacks: default_answer.py (before_model / after_model)
  |     |
  |     +-- dispatch.py (WorkerPool + ParallelAgent dispatch)
  |           callbacks: worker.py (before_model / after_model)
  |
  +-- plugins/
  |     +-- observability.py   (ObservabilityPlugin: token totals, timings, per-iteration breakdowns)
  |     +-- debug_logging.py   (DebugLoggingPlugin: full trace YAML, stdout prints)
  |     +-- depth_guard.py     (DepthGuardPlugin)
  |     +-- policy.py          (PolicyPlugin)
  |     +-- cache.py           (CachePlugin)
  |
  +-- state.py (all state key constants)
  +-- utils/prompts.py (RLM_SYSTEM_PROMPT, RLM_STATIC_INSTRUCTION, RLM_DYNAMIC_INSTRUCTION)
  +-- types.py (QueryMetadata, RLMChatCompletion, REPLResult, CodeBlock, etc.)
```

### ADK State Model

ADK scopes state keys by prefix:

| Prefix | Scope | Lifecycle |
|--------|-------|-----------|
| `app:` | Application | Persists across all users and sessions |
| `user:` | User | Persists across sessions for the same user |
| (none) | Session | Persists within a single session |
| `temp:` | Invocation | Discarded after each invocation completes |
| `obs:`, `cache:` | Session (convention) | Naming convention only; session-scoped |

---

## Agent Contributions

### 1. State Timing Guards (state-timing-expert)

**Goal:** Prevent dirty reads of worker output state that has not been committed by the ADK Runner.

**Problem:** When workers dispatch sub-LM calls, events are buffered in an `asyncio.Queue`. The worker's `after_model_callback` writes to `output_key` in state, but the Runner only commits `state_delta` values when events are yielded. Reading worker results before yielding those events is a "dirty read" -- valid within the same invocation but unreliable across invocation boundaries.

**Changes:**

- **`orchestrator.py`** -- After the reasoning agent runs, the orchestrator now drains the worker event queue and yields a **sync-point event** containing `TEMP_WORKER_EVENTS_DRAINED` and `TEMP_WORKER_RESULTS_COMMITTED`. This ensures the Runner processes worker state deltas before the orchestrator reads results. The same pattern is applied after the default-answer agent path.

- **`dispatch.py`** -- Added dirty-read guard logic around the worker result collection loop. When a worker's `output_key` is empty after dispatch, a warning is logged with the event queue size. Counters track:
  - `TEMP_WORKER_DISPATCH_COUNT` (invocation-scoped): how many workers were dispatched this invocation.
  - `TEMP_WORKER_DIRTY_READ_COUNT` (invocation-scoped): number of dirty reads performed.
  - `OBS_WORKER_DIRTY_READ_MISMATCHES` (session-scoped): mismatches where output was empty.
  - `OBS_WORKER_DISPATCH_LATENCY_MS` (session-scoped): list of per-dispatch latencies.
  - `OBS_WORKER_TOTAL_DISPATCHES` / `OBS_WORKER_TOTAL_BATCH_DISPATCHES` (session-scoped).

- **`state.py`** -- Added 8 new state keys under "Worker Dispatch Lifecycle" and "Worker Dispatch Timing" sections, plus the `obs_worker_dispatch_key()` helper.

### 2. Token Accounting (context-token-expert)

**Goal:** Provide per-invocation and per-agent-type token usage tracking visible in both state and plugin traces.

**Changes:**

- **`callbacks/reasoning.py`** -- `reasoning_before_model` now computes and stores:
  - `TEMP_REASONING_PROMPT_CHARS`: total character count across all Content parts.
  - `TEMP_REASONING_SYSTEM_CHARS`: length of system instruction text.
  - `TEMP_REASONING_CONTENT_COUNT`: number of Content objects.
  - `TEMP_REASONING_HISTORY_MSG_COUNT`: non-system messages from history.
  - `TEMP_CONTEXT_WINDOW_SNAPSHOT`: structured dict with agent type, counts, and total chars.

  `reasoning_after_model` extracts `prompt_token_count` and `candidates_token_count` from `usage_metadata` into `TEMP_REASONING_INPUT_TOKENS` / `TEMP_REASONING_OUTPUT_TOKENS`.

- **`callbacks/worker.py`** -- `worker_before_model` computes `TEMP_WORKER_PROMPT_CHARS` and `TEMP_WORKER_CONTENT_COUNT`. `worker_after_model` extracts `TEMP_WORKER_INPUT_TOKENS` / `TEMP_WORKER_OUTPUT_TOKENS` from usage metadata.

- **`callbacks/default_answer.py`** -- `default_before_model` computes `TEMP_DEFAULT_PROMPT_CHARS`, `TEMP_DEFAULT_SYSTEM_CHARS`, `TEMP_DEFAULT_HISTORY_MSG_COUNT`. `default_after_model` extracts `TEMP_DEFAULT_INPUT_TOKENS` / `TEMP_DEFAULT_OUTPUT_TOKENS`.

- **`plugins/observability.py`** -- `after_model_callback` now builds per-iteration token breakdowns stored in `OBS_PER_ITERATION_TOKEN_BREAKDOWN`. Each entry includes iteration number, call number, input/output tokens, agent type, prompt chars, system chars, and context window snapshot. `after_run_callback` logs reasoning vs worker call counts.

- **`plugins/debug_logging.py`** -- `before_model_callback` captures `TEMP_CONTEXT_WINDOW_SNAPSHOT` and all per-agent token accounting keys into trace entries. `after_model_callback` captures per-agent response token breakdowns.

- **`state.py`** -- Added 17 new state keys for per-invocation token accounting (reasoning, worker, default) and context window snapshots.

### 3. Stdout Observability (stdout-observer)

**Goal:** Add focused `[RLM]`/`[RLM_WARN]`/`[RLM_ERR]` prefixed print statements for runtime visibility without relying on log level configuration.

**Prefix conventions:**
- `[RLM]` -- Normal operational events (iteration start/end, agent entry/exit, model calls).
- `[RLM_WARN]` -- Unexpected but non-fatal conditions (empty responses, max iterations exhausted, model errors).
- `[RLM_ERR]` -- Errors in plugin callbacks (caught and suppressed to avoid blocking execution).

**Changes:**

- **`plugins/debug_logging.py`** -- Every callback method now has a print statement:
  - `before_agent_callback`: `[RLM] agent=<name> iter=<N> event=before_agent`
  - `after_agent_callback`: `[RLM] agent=<name> iter=<N> event=after_agent`
  - `before_model_callback`: One-line summary with model name, prompt chars, system chars, contents count (differentiated by agent type: reasoning, worker, default).
  - `after_model_callback`: Response summary with token counts, agent label, and worker dispatch status.
  - `on_model_error_callback`: `[RLM_ERR]` with error type and message.
  - `on_event_callback`: State delta key names (short form, stripped of prefix).
  - `after_run_callback`: Full run summary: iterations, total calls, tokens in/out, execution time, answer length, worker dispatch stats.
  - All error catches: `[RLM_ERR]` or `[RLM_WARN]` with the exception message.

- **`orchestrator.py`** -- Added print statements throughout the iteration loop:
  - `[RLM] --- iter=<N> START max=<max_iterations> ---`
  - `[RLM_WARN] iter=<N> empty response from reasoning agent`
  - `[RLM] iter=<N> code_blocks=<count> has_output=<bool>`
  - `[RLM] FINAL_ANSWER detected at iter=<N> length=<len>`
  - `[RLM] --- iter=<N> END ---`
  - `[RLM_WARN] max_iterations=<N> exhausted, falling back to default_answer_agent`
  - `[RLM] DEFAULT_ANSWER generated length=<len>`
  - `[RLM] iter=<N> worker_events_drained=<count>`

### 4. E2E Test Replay (e2e-test-expert)

**Goal:** Create ADK CLI `--replay` compatible JSON files for non-interactive end-to-end testing, plus validation tests to ensure replay files are well-formed.

**New files:**

- **`tests_rlm_adk/replay/test_repo_analysis.json`** -- Replay file that sets `repo_url`, `app:max_iterations=5`, `app:max_depth=1`, with a query asking for repository architectural analysis.

- **`tests_rlm_adk/replay/test_basic_context.json`** -- Minimal replay file with `app:max_iterations=3`, `app:max_depth=1`, and a simple summarization query.

- **`tests_rlm_adk/test_e2e_replay.py`** -- Pytest test suite with three test classes:
  - `TestReplaySchema` (parametrized over all `.json` files in `replay/`): validates JSON structure, required keys (`state`, `queries`), types, and no extra top-level keys.
  - `TestStateKeys` (parametrized): verifies that any state key using a scoped prefix (`app:`, `temp:`, `obs:`, `cache:`, `user:`) matches a constant defined in `rlm_adk.state`.
  - `TestRepoAnalysisReplay` / `TestBasicContextReplay`: file-specific content assertions (e.g., repo_url starts with `https://`, max_iterations values match expected).

**Usage:**
```bash
# Validate replay files
pytest tests_rlm_adk/test_e2e_replay.py

# Run the agent with a replay file
adk run --replay tests_rlm_adk/replay/test_repo_analysis.json rlm_adk
```

### 5. Instruction Architecture (instruction-architect)

**Goal:** Create ADK-safe instruction strings that avoid the `{state_var}` injection pitfall, and wire dynamic context metadata into the reasoning agent.

**Problem:** ADK's `LlmAgent(instruction=...)` parameter interprets single curly braces `{var}` as state variable injection placeholders. The RLM system prompt contains many f-string code examples with `{chunk}`, `{query}`, etc. that would be mistakenly interpreted by ADK.

**Changes:**

- **`utils/prompts.py`** -- Added two new constants:
  - `RLM_STATIC_INSTRUCTION`: Full system prompt with all curly braces in code examples doubled (`{{` / `}}`). Includes appended repomix-python guidance section for repository analysis workflows. This is safe to pass to `LlmAgent(instruction=...)`.
  - `RLM_DYNAMIC_INSTRUCTION`: Template string using ADK state variable injection with `?` suffix for optional vars: `{context_type?}`, `{context_total_length?}`, `{context_lengths?}`, `{repo_url?}`, `{root_prompt?}`.

- **`agent.py`** -- `create_reasoning_agent()` now accepts a `static_instruction` parameter (defaults to `RLM_STATIC_INSTRUCTION`) and passes it as the `instruction=` argument to `LlmAgent`. `create_rlm_orchestrator()` accepts `static_instruction` and forwards it.

- **`callbacks/reasoning.py`** -- `reasoning_before_model` now appends dynamic context metadata to the system instruction at runtime. It reads `TEMP_CONTEXT_TYPE`, `TEMP_CONTEXT_TOTAL_LENGTH`, `TEMP_CONTEXT_LENGTHS`, `TEMP_REPO_URL`, and `TEMP_ROOT_PROMPT` from state and builds a dynamic section appended to the system instruction text.

- **`orchestrator.py`** -- The orchestrator's `_run_async_impl` now populates context metadata state keys (`TEMP_CONTEXT_TYPE`, `TEMP_CONTEXT_TOTAL_LENGTH`, `TEMP_CONTEXT_LENGTHS`, `TEMP_ROOT_PROMPT`, `TEMP_REPO_URL`) in the initial state delta, making them available for dynamic instruction injection.

- **`state.py`** -- Added 5 context metadata keys: `TEMP_CONTEXT_TYPE`, `TEMP_CONTEXT_TOTAL_LENGTH`, `TEMP_CONTEXT_LENGTHS`, `TEMP_REPO_URL`, `TEMP_ROOT_PROMPT`.

---

## All New State Keys

### Flow Control (pre-existing, unchanged)

| Key | Scope | Purpose |
|-----|-------|---------|
| `app:max_depth` | App | Maximum recursion depth |
| `app:max_iterations` | App | Maximum iteration count |
| `temp:current_depth` | Invocation | Current recursion depth |
| `temp:iteration_count` | Invocation | Current iteration number |
| `temp:should_stop` | Invocation | Stop flag |
| `temp:used_default_answer` | Invocation | Whether default answer was used |
| `temp:depth_guard_blocked` | Invocation | Blocked by depth guard |
| `temp:policy_violation` | Invocation | Policy violation detected |

### Context Metadata (NEW - Agent 5: instruction-architect)

| Key | Scope | Purpose |
|-----|-------|---------|
| `temp:context_type` | Invocation | Type of context payload (`str`, `list`, `dict`) |
| `temp:context_total_length` | Invocation | Total character length of all context chunks |
| `temp:context_lengths` | Invocation | Per-chunk character lengths (truncated at 100 chunks) |
| `temp:repo_url` | Invocation | Repository URL if provided |
| `temp:root_prompt` | Invocation | Original user query/prompt |

### Per-Invocation Token Accounting (NEW - Agent 2: context-token-expert)

| Key | Scope | Purpose |
|-----|-------|---------|
| `temp:reasoning_prompt_chars` | Invocation | Total chars in reasoning agent prompt contents |
| `temp:reasoning_system_chars` | Invocation | Length of reasoning system instruction |
| `temp:reasoning_history_msg_count` | Invocation | Non-system messages in reasoning history |
| `temp:reasoning_content_count` | Invocation | Number of Content objects sent to reasoning LLM |
| `temp:reasoning_input_tokens` | Invocation | Prompt tokens from reasoning LLM response metadata |
| `temp:reasoning_output_tokens` | Invocation | Output tokens from reasoning LLM response metadata |
| `temp:worker_prompt_chars` | Invocation | Total chars in worker prompt |
| `temp:worker_content_count` | Invocation | Number of Content objects sent to worker LLM |
| `temp:worker_input_tokens` | Invocation | Prompt tokens from worker LLM response metadata |
| `temp:worker_output_tokens` | Invocation | Output tokens from worker LLM response metadata |
| `temp:default_prompt_chars` | Invocation | Total chars in default answer prompt |
| `temp:default_system_chars` | Invocation | Length of default answer system instruction |
| `temp:default_history_msg_count` | Invocation | Non-system messages in default answer history |
| `temp:default_input_tokens` | Invocation | Prompt tokens from default answer LLM |
| `temp:default_output_tokens` | Invocation | Output tokens from default answer LLM |
| `temp:context_window_snapshot` | Invocation | Structured dict: agent type, content count, chars |
| `temp:reasoning_call_start` | Invocation | `time.perf_counter()` at reasoning call start |

### Worker Dispatch Lifecycle (NEW - Agent 1: state-timing-expert)

| Key | Scope | Purpose |
|-----|-------|---------|
| `temp:worker_dispatch_count` | Invocation | Workers dispatched this invocation |
| `temp:worker_results_committed` | Invocation | Whether sync-point event has been yielded |
| `temp:worker_dirty_read_count` | Invocation | Dirty reads performed this invocation |
| `temp:worker_events_drained` | Invocation | Worker events drained from queue |

### Worker Dispatch Timing (NEW - Agent 1: state-timing-expert)

| Key | Scope | Purpose |
|-----|-------|---------|
| `obs:worker_dispatch_latency_ms` | Session | List of per-dispatch latency values (ms) |
| `obs:worker_total_dispatches` | Session | Total individual worker dispatches |
| `obs:worker_total_batch_dispatches` | Session | Total batch dispatches (K>1) |
| `obs:worker_dirty_read_mismatches` | Session | Accumulated empty-output dirty reads |

### Observability Aggregates (NEW - Agent 2: context-token-expert)

| Key | Scope | Purpose |
|-----|-------|---------|
| `obs:per_iteration_token_breakdown` | Session | List of dicts with per-call token details |

### Helper Functions (NEW - Agent 1)

| Function | Returns | Purpose |
|----------|---------|---------|
| `obs_worker_dispatch_key(worker_name)` | `obs:worker_dispatch:<name>` | Per-worker dispatch timing key |
| `obs_model_usage_key(model_name)` | `obs:model_usage:<name>` | Per-model usage stats key |

---

## Files Modified

| File | Agents | Description |
|------|--------|-------------|
| `rlm_adk/state.py` | 1, 2, 5 | Added 30 new state key constants and 2 helper functions |
| `rlm_adk/dispatch.py` | 1 | Dirty-read guards, dispatch timing/counting |
| `rlm_adk/orchestrator.py` | 1, 3, 5 | Sync-point yields, context metadata, stdout prints |
| `rlm_adk/callbacks/reasoning.py` | 2, 5 | Token accounting, dynamic context injection |
| `rlm_adk/callbacks/worker.py` | 2 | Per-invocation token accounting |
| `rlm_adk/callbacks/default_answer.py` | 2 | Per-invocation token accounting |
| `rlm_adk/plugins/debug_logging.py` | 2, 3 | Token accounting traces, stdout prints |
| `rlm_adk/plugins/observability.py` | 2 | Per-iteration token breakdown aggregation |
| `rlm_adk/utils/prompts.py` | 5 | `RLM_STATIC_INSTRUCTION`, `RLM_DYNAMIC_INSTRUCTION` |
| `rlm_adk/agent.py` | 5 | Wired `static_instruction` into reasoning agent factory |

## Files Created

| File | Agent | Description |
|------|-------|-------------|
| `tests_rlm_adk/replay/test_repo_analysis.json` | 4 | ADK replay: repo analysis with `repo_url` state |
| `tests_rlm_adk/replay/test_basic_context.json` | 4 | ADK replay: basic context summarization |
| `tests_rlm_adk/test_e2e_replay.py` | 4 | Pytest validation of replay file schema and state keys |
| `docs/IMPLEMENTATION_SUMMARY.md` | reviewer | This document |

---

## Known Issues

### Pre-existing Type Errors

1. **`list[LlmAgent]` vs `list[BaseAgent]`** -- The `RLMOrchestratorAgent` passes `sub_agents=[reasoning, default_answer]` where `reasoning` and `default_answer` are `LlmAgent` instances. Pyright may flag this if `sub_agents` is typed as `list[BaseAgent]`, since `LlmAgent` is a subclass but Pyright enforces invariance on mutable lists. This is functionally correct at runtime.

2. **`LlmRequest` / `LlmResponse` import paths** -- The callbacks import from `google.adk.models.llm_request` and `google.adk.models.llm_response` directly. Some ADK versions expose these via `google.adk.models` (the `__init__.py` re-export). The debug_logging plugin already uses the shorthand `from google.adk.models import LlmRequest, LlmResponse`. Both patterns work but are inconsistent across files.

3. **`usage_metadata` attribute access** -- Token accounting uses `getattr(usage, "prompt_token_count", 0)` defensively. The actual attribute names depend on the ADK/GenAI version. If the API changes attribute names, these will silently return 0.

### Potential Runtime Issues

4. **Dirty read validity** -- The state timing guards log warnings when worker output is empty after dispatch, but do not block or retry. In practice, within a single invocation, the dirty read is valid because Python's GIL ensures the `after_model_callback` has completed by the time the dispatch loop finishes the `async for event in worker.run_async(ctx)`. The guard is primarily defensive instrumentation.

5. **`OBS_PER_ITERATION_TOKEN_BREAKDOWN` list growth** -- For very long sessions (many iterations), the per-iteration breakdown list grows unboundedly in session state. Consider adding a cap or rotating old entries for production use.

6. **`RLM_STATIC_INSTRUCTION` maintenance** -- The static instruction duplicates `RLM_SYSTEM_PROMPT` with doubled curly braces. Any future prompt changes must be applied to both constants, or one should be derived from the other programmatically.

---

## Recommendations for Follow-Up Work

### High Priority

1. **Derive `RLM_STATIC_INSTRUCTION` from `RLM_SYSTEM_PROMPT` automatically.** A simple transformation (`prompt.replace("{", "{{").replace("}", "}}")`) would eliminate the need to maintain two copies of the same prompt. This should be a function, not a manual duplication.

2. **Wire `RLM_DYNAMIC_INSTRUCTION` into the agent.** The dynamic instruction template exists in `utils/prompts.py` but is not currently used by any agent. It could complement the static instruction for cases where ADK's native state-var injection is preferred over the manual injection in `reasoning_before_model`.

3. **Add integration tests that actually run the agent with replay files.** The current test suite validates replay file structure but does not execute `adk run --replay`. A CI job or pytest fixture that runs the agent (with a mock or cheap model) would catch runtime integration issues.

### Medium Priority

4. **Cap `OBS_PER_ITERATION_TOKEN_BREAKDOWN` list size.** Add a maximum length (e.g., 100 entries) and rotate old entries to prevent unbounded state growth in long sessions.

5. **Unify import style for `LlmRequest`/`LlmResponse`.** Pick either `google.adk.models.llm_request.LlmRequest` or `google.adk.models.LlmRequest` and use it consistently across all callbacks and plugins.

6. **Add structured logging alongside stdout prints.** The `[RLM]` prefix prints are useful for development but not machine-parseable. Consider emitting structured JSON logs (e.g., via `structlog`) for production observability pipelines.

### Low Priority

7. **Add `obs:worker_dispatch:<worker_name>` per-worker tracking.** The `obs_worker_dispatch_key()` helper exists in `state.py` but is not yet used. It could track per-worker latency distributions for diagnosing slow workers.

8. **Add replay files for edge cases.** Additional replay JSONs for scenarios like: max iterations exhausted (default answer path), empty context, multiple contexts, and worker dispatch failures.

9. **Consider making `DebugLoggingPlugin` stdout prints configurable.** A `verbose_stdout: bool` flag on the plugin would let users disable the print statements without removing the plugin entirely.
