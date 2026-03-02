# Provider Fake Fixtures

Replay fixtures for `FakeApiClient`. Each JSON encodes a deterministic
request/response sequence that the fake Gemini provider replays during
`pytest` runs, giving full e2e coverage without network calls.

---

## Feature Classification

### 1. Baseline / No Workers

| Fixture | What it proves |
|---------|---------------|
| `happy_path_single_iteration` | `FINAL(...)` detection on the very first model response — no tool calls, no workers. |
| `fault_429_then_success` | HTTP 429 (`RESOURCE_EXHAUSTED`) fault injection + `HttpRetryOptions` recovery. Only fixture using `fault_injections`. |
| `battlefield_report_telemetry` | Pure local REPL computation (no `llm_query` calls). `battlefield_report()` formatting, disposition tables, adaptive-gate telemetry, next-action recommendation paths. |

### 2. `llm_query()` — Single Worker Dispatch

| Fixture | What it proves |
|---------|---------------|
| `multi_iteration_with_workers` | Minimal single-worker round-trip: REPL calls `llm_query()`, worker returns text, reasoning emits `FINAL`. |
| `deterministic_guardrails` | `parse_with_retry` self-healing loop — first worker returns malformed JSON, correction prompt + second `llm_query()` succeeds. Also tests `DeduplicationRing` (SHA-256 content hashing). |
| `exec_sandbox_codegen` | Worker generates Python code at runtime; REPL validates it via forbidden-token check + AST import whitelist, then `exec()`s it in a sandboxed namespace. |

### 3. `llm_query_batched()` — Parallel Batch Dispatch

| Fixture | What it proves |
|---------|---------------|
| `structured_control_plane` | Pydantic-typed decision gates: `Disposition` enum, `model_validator`, hallucinated-entity grounding check. K=3 batch, no `output_schema` (manual `model_validate()`). |
| `sliding_window_chunking` | `SlidingWindow` with 50 % prefix overlap. 3 successive `llm_query_batched()` calls (8 workers total) process 8 records across 3 overlapping chunks. |
| `polymorphic_dag_routing` | Two-phase DAG: K=4 triage batch fans out by disposition, then K=2 comparison batch for fuzzy-match records only. Conditional second dispatch. |
| `adaptive_confidence_gating` | `AdaptiveGate` with rolling-mean window. Two batched dispatches across 2 REPL iterations; dynamic batch-size and retry-policy adjustment based on confidence drift. |

### 4. Both `llm_query()` and `llm_query_batched()`

| Fixture | What it proves |
|---------|---------------|
| `hierarchical_summarization` | Map-reduce: `llm_query_batched()` K=3 map phase, then `llm_query()` reduce phase. Both dispatch modes in a single REPL iteration. |
| `full_pipeline` | Dedup ring + K=4 batched triage + malformed-JSON error on one worker + targeted single `llm_query()` retry. Full error-recovery loop. |
| `multi_turn_repl_session` | 3-turn REPL session: K=5 triage, single codegen `llm_query()`, K=3 re-triage after data cleaning. Cross-iteration variable persistence, sandbox exec of LLM-generated code. |
| `skill_helper` | `probe_repo`, `pack_repo`, `shard_repo` skill helpers, then K=2 `llm_query_batched()` to analyse shards. |

### 5. `output_schema` — ADK Structured Output Pipeline

All four fixtures exercise `set_model_response` functionCalls from workers
and the `LLMResult.parsed` carrier.

| Fixture | What it proves |
|---------|---------------|
| `structured_output_happy_path` | `llm_query()` + `output_schema=AnalysisResult`. Worker's `set_model_response` is valid on first try. |
| `structured_output_batched_k1` | `llm_query_batched()` K=1 + `output_schema=SentimentResult`. Batched code path with single-item edge case. |
| `structured_output_retry_empty` | `WorkerRetryPlugin` detects empty-string value (`summary: ""`), returns `ToolFailureResponse`, worker self-heals on retry. |
| `structured_output_retry_validation` | Missing required field triggers Pydantic `ValidationError` inside `SetModelResponseTool`, `on_tool_error_callback` returns reflection guidance, worker retries with all fields. Exercises BUG-13 monkey-patch. |

### 6. Error / Retry Scenarios

| Fixture | Error type | Recovery mechanism |
|---------|-----------|-------------------|
| `fault_429_then_success` | HTTP 429 `RESOURCE_EXHAUSTED` | SDK-level `HttpRetryOptions` |
| `deterministic_guardrails` | Malformed JSON from worker | App-level `parse_with_retry` loop |
| `full_pipeline` | Malformed JSON from one worker in batch | Targeted single `llm_query()` retry |
| `structured_output_retry_empty` | Empty string in structured field | `WorkerRetryPlugin` + `ToolFailureResponse` |
| `structured_output_retry_validation` | Missing required Pydantic field | `SetModelResponseTool` `ValidationError` + reflection |

---

## Running the E2E Suite

All provider-fake e2e tests are tagged with the `provider_fake` pytest marker.

```bash
# Run only provider-fake e2e tests
.venv/bin/python -m pytest -m provider_fake -v

# Run everything EXCEPT provider-fake e2e tests (fast unit-test only)
.venv/bin/python -m pytest -m "not provider_fake" -v

# Run a single fixture by keyword
.venv/bin/python -m pytest -m provider_fake -k happy_path_single_iteration -v

# Run only the structured-output subset
.venv/bin/python -m pytest tests_rlm_adk/test_structured_output_e2e.py -v
```

### Test files in this group

| File | Tests | What it covers |
|------|:-----:|----------------|
| `test_provider_fake_e2e.py` | 7 | Contract validation (all 18 fixtures), plugin/artifact/tracing integration |
| `test_structured_output_e2e.py` | 9 | `output_schema` happy path, batched K=1, retry (empty + validation), plugins |
| `test_skill_helper_e2e.py` | 5 | Skill instruction coverage (sync) + `skill_helper` fixture pipeline (async) |

The marker is registered in `pyproject.toml` under `[tool.pytest.ini_options].markers`.

---

## Quick-Reference Matrix

| Fixture | `llm_query` | `llm_query_batched` | `output_schema` | REPL iters | Error/Retry | Workers |
|---------|:-----------:|:-------------------:|:---------------:|:----------:|:-----------:|:-------:|
| `happy_path_single_iteration` | -- | -- | -- | 0 | -- | 0 |
| `fault_429_then_success` | -- | -- | -- | 0 | 429 | 0 |
| `multi_iteration_with_workers` | 1 | -- | -- | 1 | -- | 1 |
| `structured_output_happy_path` | 1 | -- | Yes | 1 | -- | 1 |
| `structured_output_batched_k1` | -- | K=1 | Yes | 1 | -- | 1 |
| `structured_output_retry_empty` | 1 | -- | Yes | 1 | empty val | 2 |
| `structured_output_retry_validation` | 1 | -- | Yes | 1 | validation | 2 |
| `structured_control_plane` | -- | K=3 | -- | 1 | -- | 3 |
| `deterministic_guardrails` | 2 | -- | -- | 1 | bad JSON | 2 |
| `sliding_window_chunking` | -- | K=4,2,2 | -- | 1 | -- | 8 |
| `polymorphic_dag_routing` | -- | K=4,2 | -- | 1 | -- | 6 |
| `hierarchical_summarization` | 1 | K=3 | -- | 1 | -- | 4 |
| `adaptive_confidence_gating` | -- | K=3,2 | -- | 2 | -- | 5 |
| `exec_sandbox_codegen` | 1 | -- | -- | 2 | -- | 1 |
| `battlefield_report_telemetry` | -- | -- | -- | 2 | -- | 0 |
| `full_pipeline` | 1 | K=4 | -- | 2 | bad JSON | 5 |
| `multi_turn_repl_session` | 1 | K=5,3 | -- | 2 | -- | 9 |
| `skill_helper` | -- | K=2 | -- | 2 | -- | 2 |
