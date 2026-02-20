# Bug 002: Worker accounting keys overwritten in parallel batches

**Bug ID:** BUG-002
**Title:** Worker accounting keys overwritten in parallel batches (last-writer-wins)
**Severity:** High
**Status:** Open

## Affected Files

| File | Lines | Description |
|------|-------|-------------|
| `rlm_adk/callbacks/worker.py` | 55-66 | `worker_before_model` plain-assigns `WORKER_PROMPT_CHARS` and `WORKER_CONTENT_COUNT` |
| `rlm_adk/callbacks/worker.py` | 86-94 | `worker_after_model` plain-assigns `WORKER_INPUT_TOKENS` and `WORKER_OUTPUT_TOKENS` |
| `rlm_adk/state.py` | 64-67 | Defines scalar key constants `WORKER_PROMPT_CHARS`, `WORKER_CONTENT_COUNT`, `WORKER_INPUT_TOKENS`, `WORKER_OUTPUT_TOKENS` |
| `rlm_adk/dispatch.py` | 260-268 | `llm_query_batched_async` dispatches multiple workers via `ParallelAgent` which runs them concurrently |

## Classes and Functions Involved

- **`worker_before_model(callback_context, llm_request)`** in `rlm_adk/callbacks/worker.py`: Calculates `total_prompt_chars` and `content_count` from the request, then does a plain scalar assignment to `callback_context.state[WORKER_PROMPT_CHARS]` and `callback_context.state[WORKER_CONTENT_COUNT]`.

- **`worker_after_model(callback_context, llm_response)`** in `rlm_adk/callbacks/worker.py`: Reads `usage_metadata` from the response and does a plain scalar assignment to `callback_context.state[WORKER_INPUT_TOKENS]` and `callback_context.state[WORKER_OUTPUT_TOKENS]`.

- **`llm_query_batched_async(prompts, model)`** in `rlm_adk/dispatch.py`: When `len(workers) > 1`, creates a `ParallelAgent` with all workers as `sub_agents` and dispatches them concurrently via `parallel.run_async(ctx)`. Each worker's callbacks write to the same shared state keys.

- **State key constants** in `rlm_adk/state.py` (lines 64-67):
  - `WORKER_PROMPT_CHARS = "worker_prompt_chars"`
  - `WORKER_CONTENT_COUNT = "worker_content_count"`
  - `WORKER_INPUT_TOKENS = "worker_input_tokens"`
  - `WORKER_OUTPUT_TOKENS = "worker_output_tokens"`

## Detailed Explanation

When `llm_query_batched_async` is called with multiple prompts (K > 1), it acquires K workers and dispatches them concurrently via `ParallelAgent`. Each worker runs its `worker_before_model` and `worker_after_model` callbacks independently. However, all workers write their accounting data to the **same four scalar state keys**:

```python
# In worker_before_model (line 64-65):
callback_context.state[WORKER_PROMPT_CHARS] = total_prompt_chars
callback_context.state[WORKER_CONTENT_COUNT] = content_count

# In worker_after_model (line 89-94):
callback_context.state[WORKER_INPUT_TOKENS] = (
    getattr(usage, "prompt_token_count", 0) or 0
)
callback_context.state[WORKER_OUTPUT_TOKENS] = (
    getattr(usage, "candidates_token_count", 0) or 0
)
```

Since these are plain scalar assignments (not appends or accumulations), each worker overwrites the value written by any previously-completed worker in the same batch. The result is **last-writer-wins**: only the final worker to complete has its accounting data preserved in state. The accounting data from all other N-1 workers in the batch is silently discarded.

This means:
1. Token usage tracking is incorrect -- it reflects only one worker's usage, not the total batch usage.
2. The `per_agent_tokens` logged in the debug YAML shows different values at different points in time as each worker overwrites the shared key, but the final state only preserves one worker's data.
3. Downstream consumers (observability plugin, debug logging) that read these keys get misleading accounting figures.

## Evidence from Logs

### Evidence 1: Four workers in a parallel batch, all writing to the same keys

The debug YAML at `rlm_adk_debug.yaml` shows a batch of 4 workers (worker_1 through worker_4) dispatched via `batch_1_4`. Each worker's `on_event` emits a `state_delta_keys` list that includes the same four accounting keys:

```yaml
# Lines 2317-2350: Four sequential on_event emissions from the same parallel batch
- event: on_event
  author: worker_3
  state_delta_keys:
  - worker_prompt_chars      # <-- same key
  - worker_content_count     # <-- same key
  - worker_3_output
  - worker_input_tokens      # <-- same key
  - worker_output_tokens     # <-- same key
- event: on_event
  author: worker_1
  state_delta_keys:
  - worker_prompt_chars      # <-- overwrites worker_3's value
  - worker_content_count
  - worker_1_output
  - worker_input_tokens      # <-- overwrites worker_3's value
  - worker_output_tokens
- event: on_event
  author: worker_4
  state_delta_keys:
  - worker_prompt_chars      # <-- overwrites worker_1's value
  - worker_content_count
  - worker_4_output
  - worker_input_tokens      # <-- overwrites worker_1's value
  - worker_output_tokens
- event: on_event
  author: worker_2
  state_delta_keys:
  - worker_prompt_chars      # <-- overwrites worker_4's value (final winner)
  - worker_content_count
  - worker_2_output
  - worker_input_tokens      # <-- overwrites worker_4's value (final winner)
  - worker_output_tokens
```

### Evidence 2: Different prompt char values across workers, only one survives

The `before_model` events for the 4 parallel workers show different `worker_prompt_chars` values:
- worker_2 (line 1846): `worker_prompt_chars: 27584`
- worker_3 (line 1890): `worker_prompt_chars: 1212310`
- worker_4 (line 1935): `worker_prompt_chars: 102698`

Yet the final session state shows only a single scalar value:
- Line 71: `worker_prompt_chars: 28031`
- Line 72: `worker_content_count: 1`

This is the value from whichever worker wrote last. The 1,212,310-char prompt from worker_3 and the 102,698-char prompt from worker_4 are silently lost.

### Evidence 3: Token counts show same overwrite pattern

The `after_model` events record different token counts per worker:
- worker_2 (line 1984-1985): `worker_input_tokens: 25715`, `worker_output_tokens: 578`
- worker_1 (line 2012-2013): `worker_input_tokens: 7765`, `worker_output_tokens: 385`
- worker_4 (line 2039-2040): `worker_input_tokens: 22712`, `worker_output_tokens: 761`
- worker_3 (line 2034): `prompt_tokens: 321502`, `candidates_tokens: 824`

But the final state (line 157-158) shows only:
- `worker_input_tokens: 8629`
- `worker_output_tokens: 1523`

The total actual input tokens across all 4 workers was 25715 + 7765 + 22712 + 321502 = 377,694, but only 8,629 is recorded -- a **97.7% data loss** in token accounting for this batch.

## Resolution

### Fix Applied

Changed all four worker accounting state writes in `rlm_adk/callbacks/worker.py` from scalar assignment to list-append:

**`worker_before_model`** (lines 55-74): `WORKER_PROMPT_CHARS` and `WORKER_CONTENT_COUNT` now read the existing list from state (defaulting to `[]`), append the current worker's value, and write the list back. Includes a defensive `isinstance` check to migrate any pre-existing scalar values to a single-element list.

**`worker_after_model`** (lines 95-111): `WORKER_INPUT_TOKENS` and `WORKER_OUTPUT_TOKENS` use the same list-append pattern, again with defensive scalar-to-list migration.

**`rlm_adk/state.py`** (lines 64-70): Added documentation comment noting that worker accounting keys store lists (not scalars) for parallel safety (Bug 002 fix).

**`tests_rlm_adk/test_bug005_debug_token_lag.py`** (line 99-100): Updated test fixture to use list-format `[30]` and `[15]` instead of scalar `30` and `15` for worker token state values, matching the new list-based contract.

### Test Results

7 new tests in `tests_rlm_adk/test_bug002_worker_accounting.py`:
- `TestParallelWorkerAccountingPreserved` (4 tests): Simulates 3 parallel workers sharing state, asserts all 3 values preserved in lists for each of the 4 accounting keys.
- `TestWorkerAccountingUsesListAppend` (3 tests): Verifies list-append semantics (not overwrite), including a single-worker consistency test.

Full suite: **258 passed, 3 failed** (0 regressions). The 3 failures are pre-existing in `test_bug001_orchestrator_retry.py` (unrelated `retry_config` parameter not yet implemented in `create_rlm_orchestrator`).

### Concerns

1. **Downstream consumer compatibility**: The `debug_logging.py` and `observability.py` plugins now receive lists instead of scalars when reading these keys. In `debug_logging.py`, the `before_model_callback` stores values into the YAML trace dict as-is (line 207: `token_accounting[label] = val`), so the YAML output will now show lists like `worker_prompt_chars: [27584, 1212310, 102698, 28031]` instead of a single scalar. This is actually more informative and shows data from all workers. The `after_model_callback` uses these keys only for agent-type detection (`worker_in is not None` at line 245), which still evaluates truthy for non-empty lists. The `observability.py` plugin stores the value in `breakdown_entry["prompt_chars"]` (line 173), which will now be a list; downstream aggregation code should be reviewed.

2. **List growth across iterations**: The lists are appended to across the entire session lifetime, not just within a single batch. If the state is not cleared between iterations, the lists will grow monotonically. This may be intentional (full accounting history) or may need periodic clearing between orchestrator iterations. The current implementation matches the pre-fix behavior where values persisted across iterations -- the difference is that they now accumulate rather than being silently overwritten.

3. **Thread safety**: The get-append-set pattern (`list = state.get(...); list.append(...); state[...] = list`) is safe for ADK's `ParallelAgent` because ADK's parallel execution uses `asyncio` concurrency (cooperative multitasking), not OS threads. Each worker's callback runs to completion before the event loop switches. However, if ADK ever moved to true thread-based parallelism, this pattern would need a lock or atomic list-append operation.

4. **No sum/aggregation helper**: There is no utility function to sum a worker accounting list (e.g., `sum(state.get(WORKER_INPUT_TOKENS, []))`) for consumers that need a total. This would be a useful follow-up addition.
