# Provider Fake: Fixture Strategy

## Matching Strategy: Sequential with Fault Injection Overlay

**Primary strategy**: Responses are consumed in FIFO order from the fixture's `responses` array.

**Why sequential** (not prompt-hash or content-matching):
1. **Determinism**: Exact same order every run
2. **Simplicity**: Fixtures are human-readable ordered lists
3. **Debuggability**: "Call #3 returned response #3" is trivially traceable
4. **Multi-turn support**: The orchestrator loop naturally produces a predictable call sequence

**Fault overlay**: If `call_index` appears in `fault_injections`, return the specified error instead of advancing the response pointer. The fault is consumed and does not affect subsequent calls.

**Call distinguisher**: The fake server can distinguish reasoning vs worker calls:
- Reasoning calls: have `systemInstruction` at top level + multi-turn `contents`
- Worker calls: single `contents` entry + `generationConfig.temperature=0.0`

The `caller` field in fixtures is documentation-only — matching is purely by call order.

---

## Fixture Schema

```json
{
  "scenario_id": "string (unique identifier)",
  "description": "string (human-readable description)",
  "config": {
    "model": "string (model name, default: gemini-fake)",
    "thinking_budget": "int (default: 0 for determinism)",
    "max_iterations": "int (default: 5)",
    "retry_delay": "float (default: 0.0 for instant retries in tests)"
  },
  "responses": [
    {
      "call_index": "int (0-based position in call sequence)",
      "caller": "string (reasoning|worker, documentation only)",
      "status": "int (HTTP status code, default: 200)",
      "body": {
        "candidates": [{
          "content": {"role": "model", "parts": [{"text": "response text"}]},
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {
          "promptTokenCount": "int",
          "candidatesTokenCount": "int",
          "totalTokenCount": "int"
        },
        "modelVersion": "string"
      }
    }
  ],
  "fault_injections": [
    {
      "call_index": "int (which call to fault)",
      "fault_type": "string (http_error|malformed_json|delay|empty_candidates)",
      "status": "int (HTTP status for http_error)",
      "body": "object (error body for http_error)",
      "body_raw": "string (raw text for malformed_json)",
      "delay_seconds": "float (for delay fault type)"
    }
  ],
  "expected": {
    "final_answer": "string|null (expected FINAL() value)",
    "total_iterations": "int (expected iteration count)",
    "total_model_calls": "int (total calls to fake server)"
  }
}
```

---

## Scenario Selection Mechanism

### In Tests: pytest parametrize with fixture file paths

```python
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_fake"

@pytest.mark.parametrize("fixture_path", [
    FIXTURE_DIR / "happy_path_single_iteration.json",
    FIXTURE_DIR / "fault_429_then_success.json",
], ids=["happy_path", "fault_429"])
async def test_e2e_scenario(fake_gemini_server, fixture_path):
    ...
```

### Fixture Loading

```python
from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter

router = ScenarioRouter.from_file("path/to/fixture.json")
response = router.next_response(request_body)  # returns (status, body)
```

---

## Fixture Stability Guidelines

### Directory Structure
```
tests_rlm_adk/
  fixtures/
    provider_fake/
      happy_path_single_iteration.json
      multi_iteration_with_workers.json
      fault_429_then_success.json
      malformed_response.json
      worker_batch_dispatch.json
```

### Naming Convention
- `{scenario_type}_{key_detail}.json`
- Use snake_case, descriptive names
- Group related fixtures by prefix (e.g., `fault_*`)

### Version Control
- Fixtures are committed as-is (no generation step)
- Response text should be minimal but realistic
- Code blocks in responses must use exact `repl` fence format: `` ```repl\n...\n``` ``
- `FINAL(...)` must be at start of line (regex: `r"^\s*FINAL\(.*\)\s*$"` with `re.MULTILINE`)

---

## Example Fixtures

See:
- `tests_rlm_adk/fixtures/provider_fake/happy_path_single_iteration.json`
- `tests_rlm_adk/fixtures/provider_fake/multi_iteration_with_workers.json`
- `tests_rlm_adk/fixtures/provider_fake/fault_429_then_success.json`
