# Dispatch Fixes -- Showboat Demo

Executable proof-of-correctness for 4 fixes in `rlm_adk/dispatch.py`.

Each section: import, setup, exercise fix, assert, print PASS/FAIL.
All 7 tests verified passing.

---

## BUG-D: Timeout Error Category

Proves that timed-out workers get `error_category='TIMEOUT'` in both
single-worker and multi-worker paths, instead of the previous `'UNKNOWN'`.

```python
"""BUG-D: Timeout _call_record propagation.

Verifies that:
1. Single-worker timeout writes _call_record with error_category='TIMEOUT'
2. Multi-worker timeout writes _call_record only for incomplete workers
3. flush_fn populates OBS_WORKER_TIMEOUT_COUNT from the accumulator
"""
import asyncio
from unittest.mock import MagicMock

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.state import OBS_WORKER_TIMEOUT_COUNT, OBS_WORKER_ERROR_COUNTS
import rlm_adk.dispatch as _d


def _make_ctx():
    ctx = MagicMock()
    ctx.invocation_id = "test-bugd"
    ctx.session.state = {}
    return ctx


def _patch_worker_run(worker, run_fn):
    object.__setattr__(worker, "run_async", run_fn)


async def test_single_worker_timeout_category():
    """Single-worker timeout must yield error_category='TIMEOUT'."""
    _d._WORKER_DISPATCH_TIMEOUT = 0.01  # 10ms

    pool = WorkerPool(default_model="test-model", pool_size=1)
    pool.ensure_initialized()

    worker = pool._pools["test-model"].get_nowait()

    async def slow_run(_ctx):
        await asyncio.sleep(5)  # way longer than 10ms timeout
        return
        yield  # make it an async generator

    _patch_worker_run(worker, slow_run)
    pool._pools["test-model"].put_nowait(worker)

    ctx = _make_ctx()
    llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

    result = await llm_query_async("test timeout")

    # Result should be an error with TIMEOUT category
    assert result.error is True, f"Expected error=True, got {result.error}"
    assert result.error_category == "TIMEOUT", (
        f"Expected error_category='TIMEOUT', got '{result.error_category}'"
    )

    # flush_fn should have TIMEOUT in error counts
    delta = flush_fn()
    assert OBS_WORKER_ERROR_COUNTS in delta, (
        f"Expected {OBS_WORKER_ERROR_COUNTS} in flush delta"
    )
    assert "TIMEOUT" in delta[OBS_WORKER_ERROR_COUNTS], (
        f"Expected 'TIMEOUT' in error_counts dict"
    )
    assert OBS_WORKER_TIMEOUT_COUNT in delta, (
        f"Expected {OBS_WORKER_TIMEOUT_COUNT} in flush delta"
    )
    assert delta[OBS_WORKER_TIMEOUT_COUNT] == 1

    _d._WORKER_DISPATCH_TIMEOUT = 180.0
    print("PASS: BUG-D single-worker timeout -> error_category='TIMEOUT'")


async def test_multi_worker_timeout_preserves_completed():
    """Multi-worker timeout: completed workers keep their results, timed-out get TIMEOUT.

    Uses a custom ParallelAgent stand-in that simulates worker 0 completing
    fast while worker 1 blocks until the dispatch-level asyncio.wait_for
    fires the TimeoutError.
    """
    _d._WORKER_DISPATCH_TIMEOUT = 0.05  # 50ms

    pool = WorkerPool(default_model="test-model", pool_size=2)
    pool.ensure_initialized()
    ctx = _make_ctx()
    _, llm_query_batched_async, flush_fn = create_dispatch_closures(pool, ctx)

    OrigParallel = _d.ParallelAgent

    class SlowParallelAgent:
        """Worker 0 completes instantly; worker 1 sleeps past the timeout."""
        def __init__(self, **kwargs):
            self.sub_agents = kwargs.get("sub_agents", [])

        async def _run(self, ctx):
            w0 = self.sub_agents[0]
            w0._result = "fast result"
            w0._result_ready = True
            w0._result_error = False
            w0._call_record = {
                "prompt": "p0", "response": "fast result",
                "input_tokens": 10, "output_tokens": 5,
                "model": "test", "finish_reason": "STOP", "error": False,
            }
            # Worker 1 blocks — will be caught by dispatch timeout
            await asyncio.sleep(10)
            return
            yield

        def run_async(self, ctx):
            return self._run(ctx)

    _d.ParallelAgent = SlowParallelAgent

    try:
        results = await llm_query_batched_async(["p0", "p1"])
    finally:
        _d.ParallelAgent = OrigParallel
        _d._WORKER_DISPATCH_TIMEOUT = 180.0

    assert len(results) == 2, f"Expected 2 results, got {len(results)}"

    # Worker 0: completed before timeout -> preserved
    assert results[0].error is False, (
        f"Fast worker should succeed, got error={results[0].error}"
    )
    assert str(results[0]) == "fast result"

    # Worker 1: timed out -> TIMEOUT category
    assert results[1].error is True
    assert results[1].error_category == "TIMEOUT", (
        f"Expected 'TIMEOUT', got '{results[1].error_category}'"
    )

    delta = flush_fn()
    assert delta.get(OBS_WORKER_TIMEOUT_COUNT) == 1

    print("PASS: BUG-D multi-worker timeout preserves completed, marks timed-out as TIMEOUT")


asyncio.run(test_single_worker_timeout_category())
asyncio.run(test_multi_worker_timeout_preserves_completed())
```


## FM-16: Structured Output Retry Exhaustion

Proves that when `output_schema` is requested but `_structured_result` remains
`None` (retries exhausted), the result gets `error=True` and
`error_category='SCHEMA_VALIDATION_EXHAUSTED'`.

```python
"""FM-16: Structured output retry exhaustion detection.

Verifies that:
1. When output_schema is provided and _structured_result is None,
   result.error=True and error_category='SCHEMA_VALIDATION_EXHAUSTED'
2. When output_schema is provided and _structured_result is set,
   result.error=False and result.parsed contains the structured data
3. Accumulator counts SCHEMA_VALIDATION_EXHAUSTED in flush_fn
"""
import asyncio
from unittest.mock import MagicMock

from pydantic import BaseModel, Field

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.state import OBS_WORKER_ERROR_COUNTS


class TestSchema(BaseModel):
    answer: str = Field(description="The answer")
    confidence: float = Field(description="Confidence score")


def _make_ctx():
    ctx = MagicMock()
    ctx.invocation_id = "test-fm16"
    ctx.session.state = {}
    return ctx


def _patch_worker_run(worker, run_fn):
    object.__setattr__(worker, "run_async", run_fn)


async def test_schema_exhaustion_detected():
    """output_schema requested, _structured_result=None -> error=True."""
    pool = WorkerPool(default_model="test-model", pool_size=1)
    pool.ensure_initialized()

    worker = pool._pools["test-model"].get_nowait()

    async def mock_run(_ctx):
        # Simulate: worker completed but structured output never validated.
        # _structured_result stays None (set to None by dispatch at line 374).
        worker._result = "plain text fallback"
        worker._result_ready = True
        worker._result_error = False  # worker itself didn't error
        worker._call_record = {
            "prompt": "test", "response": "plain text fallback",
            "input_tokens": 50, "output_tokens": 20,
            "model": "test-model", "finish_reason": "STOP",
            "error": False,
        }
        # Note: _structured_result stays None (never set by after_tool_cb)
        return
        yield

    _patch_worker_run(worker, mock_run)
    pool._pools["test-model"].put_nowait(worker)

    ctx = _make_ctx()
    llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

    result = await llm_query_async("give me structured", output_schema=TestSchema)

    assert result.error is True, f"Expected error=True, got {result.error}"
    assert result.error_category == "SCHEMA_VALIDATION_EXHAUSTED", (
        f"Expected 'SCHEMA_VALIDATION_EXHAUSTED', got '{result.error_category}'"
    )
    assert result.parsed is None, f"Expected parsed=None, got {result.parsed}"
    assert str(result) == "plain text fallback"

    delta = flush_fn()
    assert OBS_WORKER_ERROR_COUNTS in delta
    assert delta[OBS_WORKER_ERROR_COUNTS].get("SCHEMA_VALIDATION_EXHAUSTED") == 1

    print("PASS: FM-16 exhaustion -> error=True, SCHEMA_VALIDATION_EXHAUSTED")


async def test_schema_success_not_flagged():
    """output_schema requested, _structured_result set -> error=False."""
    pool = WorkerPool(default_model="test-model", pool_size=1)
    pool.ensure_initialized()

    worker = pool._pools["test-model"].get_nowait()
    structured_data = {"answer": "42", "confidence": 0.95}

    async def mock_run(_ctx):
        worker._result = "structured response"
        worker._result_ready = True
        worker._result_error = False
        worker._structured_result = structured_data
        worker._call_record = {
            "prompt": "test", "response": '{"answer":"42","confidence":0.95}',
            "input_tokens": 50, "output_tokens": 20,
            "model": "test-model", "finish_reason": "STOP",
            "error": False,
        }
        return
        yield

    _patch_worker_run(worker, mock_run)
    pool._pools["test-model"].put_nowait(worker)

    ctx = _make_ctx()
    llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

    result = await llm_query_async("give me structured", output_schema=TestSchema)

    assert result.error is False, f"Expected error=False, got {result.error}"
    assert result.parsed == structured_data, (
        f"Expected parsed={structured_data}, got {result.parsed}"
    )

    delta = flush_fn()
    assert OBS_WORKER_ERROR_COUNTS not in delta, (
        "No error counts should be present on success"
    )

    print("PASS: FM-16 success -> error=False, parsed carries structured data")


asyncio.run(test_schema_exhaustion_detected())
asyncio.run(test_schema_success_not_flagged())
```


## FM-20: Sibling Result Preservation

Proves that when an exception occurs during dispatch, workers that already
completed successfully have their results preserved instead of being
overwritten with error `LLMResult` objects.

```python
"""FM-20: Sibling result preservation in except handler.

Verifies that:
1. Workers with _result_ready=True keep their actual results
2. Workers without results get error LLMResult objects
3. Error vs success distinction is preserved for completed workers

Strategy: Replace ParallelAgent with a stand-in that sets partial results
on sub_agents then raises, triggering the except handler at dispatch.py:555.
The handler must check _result_ready before overwriting.
"""
import asyncio
from unittest.mock import MagicMock

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
import rlm_adk.dispatch as _d


def _make_ctx():
    ctx = MagicMock()
    ctx.invocation_id = "test-fm20"
    ctx.session.state = {}
    return ctx


async def test_sibling_preservation_on_exception():
    """Exception during batch: completed workers keep their results."""
    pool = WorkerPool(default_model="test-model", pool_size=3)
    pool.ensure_initialized()
    ctx = _make_ctx()
    _, llm_query_batched_async, flush_fn = create_dispatch_closures(pool, ctx)

    OrigParallel = _d.ParallelAgent

    class CrashingParallelAgent:
        """Simulates partial completion: workers 0 and 1 complete,
        worker 2 never does, then the agent crashes."""
        def __init__(self, **kwargs):
            self.sub_agents = kwargs.get("sub_agents", [])

        def run_async(self, ctx):
            # Worker 0: success
            if len(self.sub_agents) >= 1:
                w0 = self.sub_agents[0]
                w0._result = "success from w0"
                w0._result_ready = True
                w0._result_error = False
                w0._call_record = {
                    "prompt": "p0", "response": "success from w0",
                    "input_tokens": 10, "output_tokens": 5,
                    "model": "test", "finish_reason": "STOP", "error": False,
                }
            # Worker 1: completed with error
            if len(self.sub_agents) >= 2:
                w1 = self.sub_agents[1]
                w1._result = "[Worker error]"
                w1._result_ready = True
                w1._result_error = True
                w1._call_record = {
                    "prompt": "p1", "response": "[Worker error]",
                    "input_tokens": 0, "output_tokens": 0,
                    "model": None, "finish_reason": None,
                    "error": True, "error_category": "SERVER",
                }
            # Worker 2: _result_ready stays False (never completed)
            raise RuntimeError("Simulated ParallelAgent crash")

    _d.ParallelAgent = CrashingParallelAgent

    try:
        results = await llm_query_batched_async(["p0", "p1", "p2"])
    finally:
        _d.ParallelAgent = OrigParallel

    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    # Worker 0: success preserved (not overwritten)
    assert results[0].error is False, (
        f"Worker 0 success should be preserved, got error={results[0].error}"
    )
    assert str(results[0]) == "success from w0"

    # Worker 1: error with original SERVER category preserved
    assert results[1].error is True
    assert results[1].error_category == "SERVER", (
        f"Worker 1 error category should be 'SERVER', got '{results[1].error_category}'"
    )

    # Worker 2: error (never completed, filled in by except handler)
    assert results[2].error is True
    assert "Error" in str(results[2]) or "error" in str(results[2]).lower()

    print("PASS: FM-20 sibling preservation -- success/error results preserved, incomplete get error")


asyncio.run(test_sibling_preservation_on_exception())
```


## Obs Keys: Error Count Accumulation

Proves that `_acc_error_counts` accumulates across multiple dispatches,
`flush_fn` populates `OBS_WORKER_ERROR_COUNTS`, `OBS_WORKER_RATE_LIMIT_COUNT`,
and `OBS_WORKER_TIMEOUT_COUNT`, then resets the accumulator.

```python
"""Obs Keys: Error count accumulation via _acc_error_counts.

Verifies that:
1. Multiple error categories accumulate in _acc_error_counts
2. flush_fn emits OBS_WORKER_ERROR_COUNTS as a dict
3. flush_fn emits OBS_WORKER_RATE_LIMIT_COUNT when RATE_LIMIT errors occur
4. flush_fn emits OBS_WORKER_TIMEOUT_COUNT when TIMEOUT errors occur
5. Second flush_fn call returns empty error counts (reset)

Strategy: Patches pool.acquire to return fresh workers with mock run_async
that sets specific error categories. This avoids the pool acquire/release
cycle overwriting our patches.
"""
import asyncio
from unittest.mock import MagicMock

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.state import (
    OBS_WORKER_ERROR_COUNTS,
    OBS_WORKER_RATE_LIMIT_COUNT,
    OBS_WORKER_TIMEOUT_COUNT,
)


def _make_ctx():
    ctx = MagicMock()
    ctx.invocation_id = "test-obs"
    ctx.session.state = {}
    return ctx


def _patch_worker_run(worker, run_fn):
    object.__setattr__(worker, "run_async", run_fn)


async def test_error_count_accumulation():
    """Multiple dispatches with different error types accumulate correctly."""
    pool = WorkerPool(default_model="test-model", pool_size=1)
    pool.ensure_initialized()
    ctx = _make_ctx()
    llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

    call_count = 0

    async def patched_acquire(model=None):
        nonlocal call_count
        call_count += 1
        w = pool._create_worker(model or pool.other_model)

        if call_count == 1:
            async def rate_limit_run(_ctx):
                w._result = "[Rate limited]"
                w._result_ready = True
                w._result_error = True
                w._call_record = {
                    "prompt": "test", "response": "[Rate limited]",
                    "input_tokens": 0, "output_tokens": 0,
                    "model": None, "finish_reason": None,
                    "error": True, "error_category": "RATE_LIMIT",
                }
                return
                yield
            _patch_worker_run(w, rate_limit_run)
        elif call_count == 2:
            async def server_error_run(_ctx):
                w._result = "[Server error]"
                w._result_ready = True
                w._result_error = True
                w._call_record = {
                    "prompt": "test", "response": "[Server error]",
                    "input_tokens": 0, "output_tokens": 0,
                    "model": None, "finish_reason": None,
                    "error": True, "error_category": "SERVER",
                }
                return
                yield
            _patch_worker_run(w, server_error_run)
        return w

    pool.acquire = patched_acquire

    result1 = await llm_query_async("test rate limit")
    assert result1.error is True and result1.error_category == "RATE_LIMIT"

    result2 = await llm_query_async("test server error")
    assert result2.error is True and result2.error_category == "SERVER"

    # Flush and verify accumulation
    delta = flush_fn()

    # Full error counts dict
    assert OBS_WORKER_ERROR_COUNTS in delta, f"Missing {OBS_WORKER_ERROR_COUNTS}"
    error_counts = delta[OBS_WORKER_ERROR_COUNTS]
    assert error_counts["RATE_LIMIT"] == 1, (
        f"Expected RATE_LIMIT=1, got {error_counts.get('RATE_LIMIT')}"
    )
    assert error_counts["SERVER"] == 1, (
        f"Expected SERVER=1, got {error_counts.get('SERVER')}"
    )

    # Scalar convenience keys
    assert OBS_WORKER_RATE_LIMIT_COUNT in delta, f"Missing {OBS_WORKER_RATE_LIMIT_COUNT}"
    assert delta[OBS_WORKER_RATE_LIMIT_COUNT] == 1

    # TIMEOUT not present (no timeout errors in this test)
    assert OBS_WORKER_TIMEOUT_COUNT not in delta, (
        "TIMEOUT count should not be present when no timeouts occurred"
    )

    print("PASS: Obs keys accumulation -- RATE_LIMIT=1, SERVER=1, scalar keys correct")


async def test_flush_resets_error_counts():
    """After flush, error counts should be reset to empty."""
    pool = WorkerPool(default_model="test-model", pool_size=1)
    pool.ensure_initialized()
    ctx = _make_ctx()
    llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

    async def patched_acquire(model=None):
        w = pool._create_worker(model or pool.other_model)
        async def error_run(_ctx):
            w._result = "[error]"
            w._result_ready = True
            w._result_error = True
            w._call_record = {
                "prompt": "test", "response": "[error]",
                "input_tokens": 0, "output_tokens": 0,
                "model": None, "finish_reason": None,
                "error": True, "error_category": "NETWORK",
            }
            return
            yield
        _patch_worker_run(w, error_run)
        return w

    pool.acquire = patched_acquire
    await llm_query_async("test error")

    # First flush: should have counts
    delta1 = flush_fn()
    assert OBS_WORKER_ERROR_COUNTS in delta1
    assert delta1[OBS_WORKER_ERROR_COUNTS]["NETWORK"] == 1

    # Second flush: should be empty (reset)
    delta2 = flush_fn()
    assert OBS_WORKER_ERROR_COUNTS not in delta2, (
        "Error counts should not be present after reset (empty dict is falsy)"
    )
    assert OBS_WORKER_RATE_LIMIT_COUNT not in delta2
    assert OBS_WORKER_TIMEOUT_COUNT not in delta2

    print("PASS: Obs keys reset -- second flush has no error counts")


asyncio.run(test_error_count_accumulation())
asyncio.run(test_flush_resets_error_counts())
```
