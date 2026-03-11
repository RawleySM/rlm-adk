<!-- validated: 2026-03-09 -->

# Phase 6 Results: LiteLLM Testing

## Deliverables

### 1. `scripts/validate_litellm_keys.py`
Pre-flight API key validation script. Reads `.env` from `rlm_adk/.env` via python-dotenv, tests each provider with a minimal `litellm.acompletion(max_tokens=5)` call, reports per-provider status.

**Validation run (2026-03-09):**
```
  [+] Gemini     OK     OK
  [+] OpenAI     OK     OK!
  [+] DeepSeek   OK     OK
  [+] Groq       OK     OK

4/4 providers available.
```

Exit code: 0 (at least one provider works).

### 2. `tests_rlm_adk/test_litellm_live.py`
Two live integration tests, auto-excluded from default pytest run:

| Test | What it verifies |
|------|-----------------|
| `test_litellm_single_query_live` | Single query through Router produces events with model content |
| `test_litellm_batched_query_live` | `llm_query_batched` with 3 prompts produces events and completes |

**Review fixes incorporated:**
- **MED-3**: Does NOT assert `obs:child_dispatch_count` (resets per REPL iteration). Instead verifies events contain model responses and agent produces a final event.
- **MIN-5**: Does NOT use `RLM_TEST_LITELLM_MODEL`. Uses `model="reasoning"` with Router tier selection.

**Skip behavior verified:**
```
tests_rlm_adk/test_litellm_live.py::test_litellm_single_query_live SKIPPED
tests_rlm_adk/test_litellm_live.py::test_litellm_batched_query_live SKIPPED
======================== 2 skipped in 0.04s =========================
```

### 3. `tests_rlm_adk/replay/litellm_batched_multi_model.json`
Replay fixture for `adk run --replay` testing multi-model parallel dispatch. Follows the same schema as `recursive_ping.json` (validated: `state` + `queries` keys only).

Run with: `RLM_ADK_LITELLM=1 .venv/bin/adk run --replay tests_rlm_adk/replay/litellm_batched_multi_model.json rlm_adk`

### 4. `pyproject.toml` marker
Added: `"litellm_live: live LiteLLM integration tests requiring real API keys"`

## Verification

| Check | Result |
|-------|--------|
| `scripts/validate_litellm_keys.py` runs successfully | 4/4 providers OK |
| Live tests skip when `RLM_ADK_LITELLM` unset | 2 skipped |
| Default pytest run unaffected | 28/1062 collected (unchanged) |
| Lint passes (`ruff check`) | All checks passed |
| Format passes (`ruff format --check`) | All files formatted |
| Replay fixture schema valid | state + queries keys only |

## Files Created/Modified

| File | Action |
|------|--------|
| `scripts/validate_litellm_keys.py` | Created (executable) |
| `tests_rlm_adk/test_litellm_live.py` | Created |
| `tests_rlm_adk/replay/litellm_batched_multi_model.json` | Created |
| `pyproject.toml` | Modified (added marker) |
