# RLM ADK Test Requirements Specification (Inferred)

## 1. Purpose

This document defines inferred test requirements for `./rlm_adk/` based on:

- Legacy tests under `./tests/`
- ADK rebuild contract in `docs/adk_port_and_rebuild_guide.md`

The intent is to provide a parity-oriented SRS that can drive implementation of a dedicated `tests_rlm_adk` suite.

## 2. Scope

In scope:

- Local ADK execution path (`RLMAdkEngine`, orchestrator, REPL, callbacks, plugins, dispatch)
- Functional parity with legacy behaviors validated by `./tests`
- ADK-specific invariants (CRIT/HIGH requirements from rebuild guide)

Out of scope:

- Isolated cloud environments (Modal/Prime/Docker/E2B broker paths), deferred by guide
- Exact byte-for-byte model outputs (semantic equivalence required)

## 3. Sources of Truth

- Legacy tests:
- `tests/test_local_repl.py`
- `tests/repl/test_local_repl.py`
- `tests/test_local_repl_persistent.py`
- `tests/test_multi_turn_integration.py`
- `tests/test_parsing.py`
- `tests/test_types.py`
- `tests/test_imports.py`
- `tests/clients/test_gemini.py`
- `tests/clients/portkey.py`
- `tests/README.md`

- Rebuild guide:
- `docs/adk_port_and_rebuild_guide.md` (sections A-K, especially CRIT-1, CRIT-3, HIGH-1..6, parity plan)

## 4. Quality Gates

- Critical requirements (`CRIT-*`) must pass before release.
- High-priority requirements (`HIGH-*`) must pass before defaulting to ADK engine.

## 5. Functional Requirements

### FR-001 Completion Contract Parity

- The engine shall expose `completion(prompt, root_prompt=None) -> RLMChatCompletion` and async equivalent.
- The completion response shall include: `root_model`, `prompt`, `response`, `usage_summary`, `execution_time`.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` A.1, A.3, K.4
- Legacy type expectations in `tests/test_types.py`

### FR-002 Iterative Orchestration Loop

- The orchestrator shall perform iterative cycles of:
- build prompt from message history
- call reasoning model
- extract `repl` blocks
- execute blocks
- detect final answer
- append formatted iteration
- stop on final answer or max iterations
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` A.1-3, B.1, C.1, K.4
- `tests/test_parsing.py`, `tests/test_multi_turn_integration.py`

### FR-003 Final Answer Extraction Semantics

- `FINAL(...)` must be parsed only at line start (allowing leading whitespace).
- `FINAL_VAR(...)` must take precedence over `FINAL(...)`.
- Without execution environment, `FINAL_VAR(...)` shall return `None`.
- Nested parentheses in `FINAL(...)` must parse correctly.
- Source basis:
- `tests/test_parsing.py` (`TestFindFinalAnswer`)
- `docs/adk_port_and_rebuild_guide.md` A.1, K.4

### FR-004 REPL Code Block Parsing

- Only fenced blocks tagged `repl` shall be extracted.
- Multiple blocks must preserve original order.
- Non-`repl` fences shall be ignored.
- Source basis:
- `tests/test_parsing.py` (`TestFindCodeBlocks`)

### FR-005 REPL Execution Core Behavior

- REPL must execute Python code and capture stdout/stderr.
- Runtime and syntax errors must surface in stderr.
- Variables/functions must persist within one REPL instance.
- `cleanup()` shall clear state and remove temp dir.
- Context manager usage shall cleanup correctly.
- Source basis:
- `tests/test_local_repl.py`
- `tests/repl/test_local_repl.py`
- `docs/adk_port_and_rebuild_guide.md` K.4

### FR-006 REPL Helpers

- `FINAL_VAR(name)` must return existing variable values as strings.
- Missing variables must return explicit error text.
- `SHOW_VARS()` behavior should expose available non-private symbols.
- Source basis:
- `tests/test_local_repl.py` (`TestLocalREPLHelpers`)
- `docs/adk_port_and_rebuild_guide.md` prompt contract in `utils/prompts`

### FR-007 Context Loading

- REPL shall support `str | dict | list` context payloads.
- Initial context alias `context` shall map to `context_0`.
- Source basis:
- `tests/test_local_repl.py` (`TestLocalREPLContext`)
- `tests/test_local_repl_persistent.py`

### FR-008 Persistent Session State

- In persistent mode, contexts shall accumulate as `context_0..N`.
- Histories shall accumulate as `history_0..N` with alias `history -> history_0`.
- Stored histories must be copied, not referenced.
- Variables must persist across turns in same persistent session.
- Source basis:
- `tests/test_local_repl_persistent.py`
- `tests/test_multi_turn_integration.py`
- `docs/adk_port_and_rebuild_guide.md` A.1, E.2, K.2, K.4

### FR-009 Non-Persistent Isolation

- Non-persistent mode shall create fresh execution environments per completion.
- Variables/functions from prior completion must not exist in subsequent completion.
- Default mode shall be non-persistent unless explicitly enabled.
- Source basis:
- `tests/test_local_repl.py` (`TestLocalREPLSimulatingRLMNoPersistence`)
- `tests/test_multi_turn_integration.py` (`TestNonPersistentMode`)

### FR-010 Prompt Awareness for Persistent Assets

- `build_user_prompt` shall append context-count and history-count notices when counts > 1.
- This is a pure-function unit test of `rlm_adk.utils.prompts.build_user_prompt`, not a persistence integration concern.
- Source basis:
- `tests/test_multi_turn_integration.py` (`TestMultiTurnPromptAwareness`)
- `docs/adk_port_and_rebuild_guide.md` A.1, K.2

### FR-011 Sub-LM Query Support

- Executed REPL code shall be able to call sub-LM functions.
- Single and batched sub-LM calls shall return responses in input order.
- Explicit `model=` override shall route to specified worker pool/model.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` A.1, C.3, F.1, F.3, K.2, K.4

### FR-012 Default Answer Fallback

- If no final answer is found after `max_iterations`, the system shall call default answer path and return it.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` A.3, B.1, D.2.3, K.2, K.4

### FR-013 Usage Tracking

- Usage accounting shall aggregate calls/input/output tokens per model.
- Last-usage summary and full usage summary must be available in canonical type shape.
- Source basis:
- `tests/clients/test_gemini.py`
- `tests/test_types.py`
- `docs/adk_port_and_rebuild_guide.md` A.3, D.1.3, K.2, K.4

### FR-014 Public API Importability

- Core ADK package exports must be importable without circular-import failures.
- `__all__` declarations must map to valid exports with no duplicate names.
- Source basis:
- `tests/test_imports.py`

## 6. ADK-Specific Critical/High Requirements

### AR-CRIT-001 State Delta Discipline (CRIT-1)

- No direct `ctx.session.state[key] = value` writes in orchestrator loop.
- All orchestrator state mutations must be emitted through `EventActions(state_delta=...)`.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` F.5, H.1, K.4

### AR-CRIT-002 Async Bridge via AST Rewrite (CRIT-3)

- Code containing `llm_query`/`llm_query_batched` shall be rewritten to async awaits.
- Rewritten code shall execute under async wrapper and preserve locals.
- Timeout handling shall wrap coroutine consumption, not async generator object.
- stdout/stderr capture shall be task-local to avoid cross-task leakage.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` F.2, K.1, K.4

### AR-HIGH-001 RunConfig Capacity (HIGH-1)

- `RunConfig.max_llm_calls` must be explicitly configured and tested against realistic iteration/sub-call workloads.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` C.4, K.1, K.4

### AR-HIGH-002 Model Error Handling (HIGH-2)

- Model errors (rate limits/auth/timeouts/other) must be surfaced via structured fallback behavior in plugin callbacks.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` D.1.1, K.1

### AR-HIGH-003 Worker Agent Isolation (HIGH-3)

- Worker agents must enforce:
- `include_contents='none'`
- `disallow_transfer_to_parent=True`
- `disallow_transfer_to_peers=True`
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` D.2.2, K.4

### AR-HIGH-004 Depth Semantics (HIGH-4)

- Depth is invocation-level and should not increment per concurrent worker dispatch.
- Depth guard must block calls above max depth and record block state.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` C.3, D.1.1, K.1

### AR-HIGH-005 Routing Semantics (HIGH-5)

- Default routing: depth=0 main model, depth=1 other model.
- Explicit `model=` must override depth default and route correctly.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` C.3, F.3, K.2

### AR-HIGH-006 Callback Completeness (HIGH-6)

- Reasoning, worker, and default-answer agents shall each have defined before/after callback behavior for prompt injection and output extraction.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` D.2

## 7. Plugin and State Requirements

### PS-001 Cache Plugin Behavior

- Cache check on `before_model_callback`; cache store on `after_model_callback`.
- Cache hit should short-circuit model call with cached response.
- Cache hit/miss counters and last-hit key must be tracked in state.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` D.1.2, G.1-G.4

### PS-002 Observability Plugin Behavior

- Must track total and per-model token usage/call counts.
- Must record total execution timing and tool invocation summary.
- Must not block execution on logging failures.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` D.1.3, H.1-H.3

### PS-004 State Schema Conformance

- Key names/scopes shall match declared schema (`app:`, `temp:`, `user:` and session keys).
- Values written to state should be JSON-serializable.
- Source basis:
- `docs/adk_port_and_rebuild_guide.md` E.1-E.2, I.1-I.2

## 8. Data Type and Serialization Requirements (DT-002 only)

### DT-002 Safe Serialization

- Non-JSON values in locals/state must be represented safely (string/repr fallback) without crashing serialization.
- Source basis:
- `tests/test_types.py`
- `docs/adk_port_and_rebuild_guide.md` I.1-I.2

## 9. Negative and Failure Requirements

### NF-002 Invalid Configuration

- Invalid model names / unsupported persistent environments shall raise explicit errors.
- Source basis:
- `tests/test_multi_turn_integration.py` (`TestPersistentModeValidation`)
- `docs/adk_port_and_rebuild_guide.md` I.2-I.3, K.2

### NF-003 REPL Runtime Failures

- Execution errors shall be surfaced to stderr and remain available for iterative correction.
- Source basis:
- `tests/test_local_repl.py`
- `docs/adk_port_and_rebuild_guide.md` I.3

## 10. Traceability Matrix (Condensed)

| Requirement Group | Primary Legacy Evidence | Primary ADK Guide Evidence |
|---|---|---|
| REPL execution semantics | `tests/test_local_repl.py` | A, B.1, K.4 |
| Persistent multi-turn behavior | `tests/test_local_repl_persistent.py`, `tests/test_multi_turn_integration.py` | A, E, K.2 |
| Parsing/final-answer behavior | `tests/test_parsing.py` | A, K.4 |
| Type/serialization behavior | `tests/test_types.py` | I, K.4 |
| API/import surface | `tests/test_imports.py` | K.4 |
| ADK state/callback/plugin architecture | N/A in legacy | C, D, E, F, G, H |

## 11. Proposed Initial Test Suite Breakdown for `tests_rlm_adk`

- `test_adk_orchestrator_loop.py` (FR-001/002/012, AR-CRIT-001)
- `test_adk_ast_rewriter.py` (AR-CRIT-002)
- `test_adk_dispatch_worker_pool.py` (FR-011, AR-HIGH-003/005)
- `test_adk_repl_local.py` (FR-005/006/007, NF-003)
- `test_adk_persistence.py` (FR-008/009)
- `test_adk_prompts.py` (FR-010)
- `test_adk_callbacks.py` (AR-HIGH-006)
- `test_adk_plugins_cache.py` (PS-001)
- `test_adk_plugins_observability.py` (PS-002)
- `test_adk_plugins_depth_guard.py` (AR-HIGH-002/004)
- `test_adk_state_schema.py` (PS-004, AR-CRIT-001)
- `test_adk_types.py` (DT-002)
- `test_adk_imports.py` (FR-014)

## 12. Exit Criteria

The ADK test suite is considered release-ready when:

- All `CRIT-*` and `HIGH-*` requirements pass.
- Legacy-equivalent core behaviors (REPL, parsing, persistence, usage) pass.
- No blocking gaps remain in state schema, plugin wiring, or callback contracts.
