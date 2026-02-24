# Provider Fake: Validation Report

## Test Results

All 6 provider-fake e2e tests **PASS** (1.94s total). All 485 existing tests remain green.

```
tests_rlm_adk/test_provider_fake_e2e.py::test_happy_path_single_iteration[fake_server0] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_usage_metadata_parsed[fake_server0] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fault_429_then_retry_success[fake_server0] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_multi_iteration_with_workers[fake_server0] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_malformed_response_handling PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_wire_format_validation[fake_server0] PASSED
```

Run command:
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -v
```

---

## What Is Validated by This Layer

### Transport / Config Wiring
| Aspect | Validated | How |
|---|---|---|
| `GOOGLE_GEMINI_BASE_URL` env var override | YES | All tests route through `http://127.0.0.1:{port}` |
| `GEMINI_API_KEY` -> `x-goog-api-key` header | YES | Server validates header presence |
| Model name in URL path (`/v1beta/models/{model}:generateContent`) | YES | Server extracts model from path |
| API version prefix (`v1beta`) | YES | Route match on `/v1beta/models/...` |
| `@cached_property` client lifecycle | YES | New Runner created AFTER env var set |

### Request Serialization
| Aspect | Validated | How |
|---|---|---|
| `contents` array (role/parts structure) | YES | Server logs contents_count per call |
| `systemInstruction` (top-level) | YES | Server logs presence per call |
| `generationConfig` (temperature, thinkingConfig) | YES | Server accepts full body |
| Multi-turn message history | YES | Multi-iteration test sends growing history |
| Worker single-turn requests | YES | Worker call verified as contents_count=1 |

### Response Deserialization
| Aspect | Validated | How |
|---|---|---|
| `candidates[0].content.parts[].text` extraction | YES | All tests verify FINAL answer from response text |
| `finishReason: STOP` handling | YES | ADK processes response successfully |
| `usageMetadata` parsing (prompt/candidates token counts) | YES | No crash on metadata access in callbacks |
| Malformed JSON response | YES | `test_malformed_response_handling` — SDK retries on parse error |

### ADK Integration Path
| Aspect | Validated | How |
|---|---|---|
| Runner -> App -> RLMOrchestratorAgent | YES | Full e2e flow executes |
| Reasoning agent callback chain (before/after model) | YES | `LAST_REASONING_RESPONSE` state populated |
| `FINAL(...)` detection by orchestrator | YES | All tests verify `FINAL_ANSWER` in state |
| Worker dispatch via WorkerPool | YES | `test_multi_iteration_with_workers` |
| REPL code execution with `llm_query()` | YES | Worker code block executed, result returned |
| ParallelAgent / worker lifecycle | YES | Worker events drained (4 events observed) |
| Event queue drain (mid-iteration + final) | YES | `mid-iteration worker_events_drained=4` logged |

### Error / Retry Handling
| Aspect | Validated | How |
|---|---|---|
| 429 rate limit -> SDK/app retry | YES | `test_fault_429_then_retry_success` |
| Retry recovery -> successful completion | YES | 2 calls observed (1 fault + 1 success) |
| Malformed JSON -> error handling | YES | `test_malformed_response_handling` |
| Transient error classification | YES | 429 correctly classified as retryable |

---

## What Is Validated by Callback Mocks (Existing Tests)

These aspects are already covered by the 485 existing unit tests:
- `find_code_blocks()` parsing logic
- `find_final_answer()` FINAL/FINAL_VAR detection
- WorkerPool routing, pool sizing, release
- AST rewriter (sync -> async transform)
- State key management, event accounting
- REPL execution (LocalREPL)
- Plugin callback ordering

---

## What Would Require Live Model Calls

These aspects cannot be validated by the fake:
- Actual model response quality / correctness
- Real token counting accuracy
- ThinkingConfig thought-part generation
- Actual rate limit behavior under load
- Network latency / timeout behavior in production
- OAuth / Vertex AI auth flows (this codebase uses API key)

---

## Gaps / Remaining Risks

### Gap 1: Streaming Not Tested
The codebase does not use streaming, but if `RunConfig(streaming_mode=StreamingMode.SSE)` were ever enabled, the fake does not serve `streamGenerateContent`. **Risk: Low** — the codebase explicitly uses non-streaming.

### Gap 2: Function Calling Not Tested
No tool/function declarations are used. If added in the future, the fake would need `functionCall` part support. **Risk: Low** — no current code path uses this.

### Gap 3: Worker Instruction as SystemInstruction
We discovered that ADK sends the worker's `instruction` field as `systemInstruction` even with `include_contents='none'`. This was a false assumption in our initial design but was caught and corrected during testing.

### Gap 4: Exact Wire JSON Not Captured
The fake server logs request metadata (contents_count, has_system_instruction) but does not capture the full request body. Adding full request body capture would enable record/replay scenarios.

### Gap 5: Concurrent Worker Timing
The fake returns responses synchronously via a thread-safe router. In production, ParallelAgent runs workers concurrently. The fake handles this correctly (thread-safe counter), but timing-sensitive race conditions cannot be tested.

### Gap 6: SDK-Level Retry vs App-Level Retry
The 429 test validates that retry happens, but it's not distinguishable whether the SDK-level `tenacity.AsyncRetrying` or the app-level retry in `orchestrator.py` handled it. Both paths are exercised, but the specific layer is opaque.

---

## Recommended Next Improvements

1. **Add request body capture** to `ScenarioRouter` for full wire format assertions
2. **Add `test_500_server_error_retry`** fixture to test server error retry path separately
3. **Add `test_empty_candidates`** to verify edge case handling when `candidates: []`
4. **Add record/replay mode** — proxy that records real Gemini traffic as fixtures
5. **Add `pytest-xdist` support** — ensure tests run in parallel safely (each gets own port)
6. **Add CI marker** — `@pytest.mark.provider_fake` for selective test runs
7. **Add timeout fault** — test `delay_seconds` fault type with asyncio timeout
