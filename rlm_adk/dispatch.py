"""Worker pool and dispatch mechanism for sub-LM calls.

Replaces the TCP socket-based LMHandler with ADK LlmAgent workers
dispatched via ParallelAgent.

Architecture:
- WorkerPool: Pre-allocated asyncio.Queue of LlmAgent instances per model
- llm_query_async: Acquire 1 worker, dispatch, return string
- llm_query_batched_async: Acquire K workers, dispatch via ParallelAgent, return K strings
- Model routing: model=None uses depth-based default; model="X" uses specific pool

State mutation discipline (AR-CRIT-001):
- Local accumulators in the closure replace ctx.session.state reads.
- flush_fn() snapshots accumulators into tool_context.state via REPLTool.
- Worker results are read from agent objects (_result, _result_ready) not state.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any

from google.adk.agents import LlmAgent, ParallelAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.tools.set_model_response_tool import SetModelResponseTool
from google.genai import types
from google.genai.types import HttpOptions, HttpRetryOptions
from pydantic import BaseModel

from rlm_adk.callbacks.worker import (
    worker_before_model,
    worker_after_model,
    worker_on_model_error,
)
from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks
from rlm_adk.repl.trace import DataFlowTracker
from rlm_adk.types import LLMResult, ModelUsageSummary, RLMChatCompletion, UsageSummary
from rlm_adk.state import (
    OBS_STRUCTURED_OUTPUT_FAILURES,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_ERROR_COUNTS,
    OBS_WORKER_POOL_EXHAUSTION_COUNT,
    OBS_WORKER_RATE_LIMIT_COUNT,
    OBS_WORKER_TIMEOUT_COUNT,
    OBS_WORKER_TOTAL_BATCH_DISPATCHES,
    OBS_WORKER_TOTAL_DISPATCHES,
    WORKER_DISPATCH_COUNT,
)

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages pools of pre-allocated LlmAgent workers per model backend.

    Each registered model has its own asyncio.Queue of LlmAgent instances.
    Workers are configured per HIGH-3:
    - include_contents='none'
    - disallow_transfer_to_parent=True
    - disallow_transfer_to_peers=True
    """

    def __init__(
        self,
        default_model: str,
        other_model: str | None = None,
        pool_size: int = 5,
    ):
        """Initialize worker pools.

        Args:
            default_model: Model name for depth=0 (main backend)
            other_model: Model name for depth=1 (sub-call backend)
            pool_size: Number of workers per model pool
        """
        self.default_model = default_model
        self.other_model = other_model or default_model
        self.pool_size = pool_size
        self._pools: dict[str, asyncio.Queue[LlmAgent]] = {}
        self._worker_counter = 0
        self._pool_exhaustion_count = 0

    def register_model(self, model_name: str, pool_size: int | None = None):
        """Register a model and create its worker pool.

        Args:
            model_name: The model identifier (e.g. "gemini-2.5-flash")
            pool_size: Override pool size for this model. Defaults to self.pool_size.
        """
        size = pool_size or self.pool_size
        # Unbounded queue so that dynamically-created workers can be returned
        queue: asyncio.Queue[LlmAgent] = asyncio.Queue()

        for _ in range(size):
            worker = self._create_worker(model_name)
            queue.put_nowait(worker)

        self._pools[model_name] = queue
        logger.info(f"Registered model pool '{model_name}' with {size} workers")

    def _create_worker(self, model_name: str) -> LlmAgent:
        """Create a single LlmAgent worker configured per HIGH-3.

        Workers are isolated: they receive prompts only via
        before_model_callback (include_contents='none') and cannot
        transfer to parent or peer agents.

        Each worker is initialized with result carrier attributes for
        the dispatch closure to read after dispatch completes.
        """
        self._worker_counter += 1
        worker_name = f"worker_{self._worker_counter}"

        worker = LlmAgent(
            name=worker_name,
            model=model_name,
            description=f"Sub-LM worker for {model_name}",
            instruction="Answer the user's query directly and concisely.",
            include_contents="none",
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
            output_key=f"{worker_name}_output",
            before_model_callback=worker_before_model,
            after_model_callback=worker_after_model,
            on_model_error_callback=worker_on_model_error,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.0,
                http_options=HttpOptions(
                    timeout=int(os.getenv("RLM_WORKER_HTTP_TIMEOUT", "120000")),
                    retry_options=HttpRetryOptions(
                        attempts=2, initial_delay=1.0, max_delay=30.0,
                    ),
                ),
            ),
        )
        # Slot for the dispatch closure to inject the prompt before dispatch.
        # The worker's before_model_callback reads this to build the LlmRequest.
        worker._pending_prompt = None  # type: ignore[attr-defined]

        # Result carrier attributes (written by after_model / on_model_error callbacks)
        worker._result = None  # type: ignore[attr-defined]
        worker._result_ready = False  # type: ignore[attr-defined]
        worker._result_error = False  # type: ignore[attr-defined]

        # Call record (written by after_model / on_model_error callbacks)
        worker._call_record = None  # type: ignore[attr-defined]

        return worker

    async def acquire(self, model: str | None = None) -> LlmAgent:
        """Acquire a worker from the appropriate pool.

        If the pool is empty, creates a new worker on demand to prevent
        deadlocks when batch size exceeds pool capacity.

        Args:
            model: Model name. None uses the depth=1 default (other_model).

        Returns:
            An LlmAgent worker ready for prompt injection and dispatch.
        """
        target_model = model or self.other_model

        if target_model not in self._pools:
            # Auto-register on first use for dynamically-specified models
            self.register_model(target_model)

        try:
            return self._pools[target_model].get_nowait()
        except asyncio.QueueEmpty:
            # Pool exhausted — create a worker on demand to avoid deadlock
            self._pool_exhaustion_count += 1
            logger.info(
                "Pool '%s' exhausted, creating worker on demand (exhaustion_count=%d)",
                target_model, self._pool_exhaustion_count,
            )
            return self._create_worker(target_model)

    async def release(self, worker: LlmAgent, model: str | None = None):
        """Return a worker to its pool after dispatch completes.

        Only returns the worker if the pool has not yet reached its
        configured pool_size. On-demand workers created during pool
        exhaustion are discarded to prevent unbounded pool growth.

        Args:
            worker: The LlmAgent to return.
            model: The model pool to return it to. None uses the depth=1 default.
        """
        target_model = model or self.other_model
        if target_model in self._pools:
            if self._pools[target_model].qsize() < self.pool_size:
                await self._pools[target_model].put(worker)
            else:
                logger.debug(
                    "Pool '%s' at capacity (%d), discarding on-demand worker %s",
                    target_model, self.pool_size, worker.name,
                )

    def ensure_initialized(self):
        """Ensure default and other model pools are created.

        Called during App/orchestrator initialization to pre-allocate workers.
        """
        if self.default_model not in self._pools:
            self.register_model(self.default_model)
        if self.other_model and self.other_model not in self._pools:
            self.register_model(self.other_model)


_WORKER_DISPATCH_TIMEOUT = float(os.getenv("RLM_WORKER_TIMEOUT", "180"))


async def _consume_events(run_iter: Any) -> None:
    """Consume events from an agent's run_async iterator, discarding them."""
    async for _ in run_iter:
        pass


def create_dispatch_closures(
    worker_pool: WorkerPool,
    ctx: InvocationContext,
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
) -> tuple[Any, Any, Any]:
    """Create llm_query_async, llm_query_batched_async, and flush_fn closures.

    These closures capture the worker pool and invocation context,
    and are injected into the REPL namespace so that LM-generated code
    can call sub-LM queries.

    The closures are async functions. The AST rewriter transforms
    llm_query(p) -> await llm_query_async(p) so that the REPL code
    can call them natively from within async def _repl_exec().

    Args:
        worker_pool: The pre-allocated worker pool
        ctx: Current invocation context
        call_log_sink: Optional list to accumulate RLMChatCompletion records.
        trace_sink: Optional mutable list[REPLTrace | None] holder.
            trace_sink[0] is the current REPLTrace for per-call recording.

    Returns:
        (llm_query_async, llm_query_batched_async, flush_fn) 3-tuple.
        flush_fn() returns a dict of accumulated state and resets accumulators.
    """

    # Local accumulators — replaces ctx.session.state reads (AR-CRIT-001)
    _acc_dispatch_count = 0
    _acc_batch_dispatches = 0
    _acc_latencies: list[float] = []
    _acc_error_counts: dict[str, int] = {}  # category -> count
    _acc_structured_output_failures = 0

    async def llm_query_async(
        prompt: str,
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> LLMResult:
        """Dispatch a single sub-LM query via worker pool.

        This is the K=1 case: delegates to llm_query_batched_async.

        Args:
            prompt: The text prompt to send to the sub-LM.
            model: Optional model name override. None uses depth-based default.
            output_schema: Optional Pydantic model for structured output validation.
                When provided, the worker uses SetModelResponseTool + ReflectAndRetry
                for self-healing structured output.

        Returns:
            An LLMResult (str subclass) with metadata. If output_schema was provided,
            result.parsed contains the validated dict.
        """
        current_trace = trace_sink[0] if trace_sink else None
        call_index = -1
        call_start = 0.0

        if current_trace is not None:
            call_index = current_trace._call_counter
            current_trace._call_counter += 1
            current_trace.record_llm_start(call_index, prompt, "single")
            call_start = time.perf_counter()

        results = await llm_query_batched_async(
            [prompt], model=model, output_schema=output_schema,
        )

        if current_trace is not None:
            elapsed_ms = (time.perf_counter() - call_start) * 1000
            current_trace.record_llm_end(
                call_index, results[0], elapsed_ms,
                error=results[0].error if isinstance(results[0], LLMResult) else False,
            )

        return results[0]

    async def llm_query_batched_async(
        prompts: list[str],
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> list[LLMResult]:
        """Dispatch K sub-LM queries via ParallelAgent, chunked by max_concurrent.

        When K > max_concurrent, prompts are split into sequential batches
        of at most max_concurrent, each batch dispatched in parallel.

        State is tracked via local accumulators and flushed by flush_fn()
        (AR-CRIT-001: no direct ctx.session.state writes).

        Args:
            prompts: List of text prompts to send concurrently.
            model: Optional model name override. None uses depth-based default.
            output_schema: Optional Pydantic model for structured output validation.

        Returns:
            List of LLMResult (str subclass) responses, in the same order as prompts.
        """
        if not prompts:
            return []

        max_concurrent = int(os.getenv("RLM_MAX_CONCURRENT_WORKERS", "4"))
        k = len(prompts)
        dispatch_start = time.perf_counter()

        # Trace support: get current trace and set up data flow tracker
        current_trace = trace_sink[0] if trace_sink else None
        _data_flow = DataFlowTracker() if current_trace is not None else None

        # Register prompts with data flow tracker for dependency detection
        if _data_flow is not None and current_trace is not None:
            batch_start_index = current_trace._call_counter
            current_trace._call_counter += k
            for idx, p in enumerate(prompts):
                _data_flow.check_prompt(batch_start_index + idx, p)
        else:
            batch_start_index = 0

        # Update local accumulators (no ctx.session.state reads)
        nonlocal _acc_dispatch_count, _acc_batch_dispatches
        _acc_dispatch_count += k
        if k > 1:
            _acc_batch_dispatches += 1

        all_results: list[LLMResult] = []

        # Split prompts into chunks of max_concurrent
        for batch_idx in range(0, k, max_concurrent):
            batch_prompts = prompts[batch_idx : batch_idx + max_concurrent]
            batch_num = batch_idx // max_concurrent + 1
            total_batches = (k + max_concurrent - 1) // max_concurrent

            if total_batches > 1:
                print(
                    f"[RLM] worker batch {batch_num}/{total_batches} "
                    f"({len(batch_prompts)} prompts)",
                    flush=True,
                )

            workers: list[LlmAgent] = []
            try:
                # Acquire workers and inject prompts for this batch
                for prompt in batch_prompts:
                    worker = await worker_pool.acquire(model)
                    # Reset result carrier before dispatch
                    worker._pending_prompt = prompt  # type: ignore[attr-defined]
                    worker._result = None  # type: ignore[attr-defined]
                    worker._result_ready = False  # type: ignore[attr-defined]
                    worker._result_error = False  # type: ignore[attr-defined]

                    # Wire structured output when output_schema provided.
                    if output_schema is not None:
                        worker.output_schema = output_schema
                        worker.tools = [SetModelResponseTool(output_schema)]  # type: ignore[list-item]
                        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
                        worker.after_tool_callback = after_cb  # type: ignore[assignment]
                        worker.on_tool_error_callback = error_cb  # type: ignore[assignment]
                        worker._structured_result = None  # type: ignore[attr-defined]

                    workers.append(worker)

                if len(workers) == 1:
                    try:
                        await asyncio.wait_for(
                            _consume_events(workers[0].run_async(ctx)),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        workers[0]._result = f"[Worker {workers[0].name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
                        workers[0]._result_ready = True  # type: ignore[attr-defined]
                        workers[0]._result_error = True  # type: ignore[attr-defined]
                        # BUG-D fix: write _call_record so error_category='TIMEOUT' propagates
                        workers[0]._call_record = {  # type: ignore[attr-defined]
                            "prompt": getattr(workers[0], "_pending_prompt", None),
                            "response": workers[0]._result,  # type: ignore[attr-defined]
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "model": None,
                            "finish_reason": None,
                            "error": True,
                            "error_category": "TIMEOUT",
                        }
                else:
                    parallel = ParallelAgent(
                        name=f"batch_{batch_num}_{len(workers)}",
                        sub_agents=list(workers),  # type: ignore[arg-type]
                    )
                    try:
                        await asyncio.wait_for(
                            _consume_events(parallel.run_async(ctx)),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        for w in workers:
                            if not getattr(w, '_result_ready', False):
                                w._result = f"[Worker {w.name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
                                w._result_ready = True  # type: ignore[attr-defined]
                                w._result_error = True  # type: ignore[attr-defined]
                                # BUG-D fix: write _call_record so error_category='TIMEOUT' propagates
                                w._call_record = {  # type: ignore[attr-defined]
                                    "prompt": getattr(w, "_pending_prompt", None),
                                    "response": w._result,  # type: ignore[attr-defined]
                                    "input_tokens": 0,
                                    "output_tokens": 0,
                                    "model": None,
                                    "finish_reason": None,
                                    "error": True,
                                    "error_category": "TIMEOUT",
                                }

                # Read results from worker objects
                for worker in workers:
                    record = getattr(worker, "_call_record", {}) or {}
                    if not worker._result_ready:  # type: ignore[attr-defined]
                        logger.error(
                            "Worker %s produced no result", worker.name,
                        )
                        all_results.append(LLMResult(
                            "", error=True, error_category="NO_RESULT",
                        ))
                        _acc_error_counts["NO_RESULT"] = _acc_error_counts.get("NO_RESULT", 0) + 1
                    elif getattr(worker, '_result_error', False):
                        logger.warning(
                            "Worker %s returned error result: %s",
                            worker.name, worker._result,  # type: ignore[attr-defined]
                        )
                        cat = record.get("error_category", "UNKNOWN")
                        all_results.append(LLMResult(
                            worker._result,  # type: ignore[attr-defined]
                            error=True,
                            error_category=cat,
                            http_status=record.get("http_status"),
                            finish_reason=record.get("finish_reason"),
                            model=record.get("model"),
                        ))
                        _acc_error_counts[cat] = _acc_error_counts.get(cat, 0) + 1
                    else:
                        # Extract structured result if available
                        structured = getattr(worker, "_structured_result", None)
                        if structured is not None:
                            result_text = json.dumps(structured)
                        else:
                            result_text = worker._result  # type: ignore[attr-defined]
                        # FM-16 fix: detect retry exhaustion for structured output
                        if output_schema is not None and structured is None:
                            logger.warning(
                                "Worker %s: structured output retry exhausted "
                                "(schema=%s, result is plain text)",
                                worker.name, output_schema.__name__,
                            )
                            all_results.append(LLMResult(
                                result_text,
                                error=True,
                                error_category="SCHEMA_VALIDATION_EXHAUSTED",
                                finish_reason=record.get("finish_reason"),
                                input_tokens=record.get("input_tokens", 0),
                                output_tokens=record.get("output_tokens", 0),
                                model=record.get("model"),
                                parsed=None,
                            ))
                            _acc_error_counts["SCHEMA_VALIDATION_EXHAUSTED"] = (
                                _acc_error_counts.get("SCHEMA_VALIDATION_EXHAUSTED", 0) + 1
                            )
                            nonlocal _acc_structured_output_failures
                            _acc_structured_output_failures += 1
                        else:
                            all_results.append(LLMResult(
                                result_text,
                                error=False,
                                finish_reason=record.get("finish_reason"),
                                input_tokens=record.get("input_tokens", 0),
                                output_tokens=record.get("output_tokens", 0),
                                model=record.get("model"),
                                parsed=structured,
                            ))

                # Accumulate call records into sink for REPLResult.llm_calls
                if call_log_sink is not None:
                    for worker in workers:
                        record = getattr(worker, "_call_record", None)
                        if record:
                            model_name = record.get("model") or "unknown"
                            raw_prompt = record["prompt"]
                            if raw_prompt is None:
                                prompt_val: str | dict = ""
                            elif isinstance(raw_prompt, list):
                                prompt_val = " | ".join(
                                    m.get("content", "") for m in raw_prompt
                                    if isinstance(m, dict)
                                )
                            else:
                                prompt_val = raw_prompt
                            call_log_sink.append(RLMChatCompletion(
                                root_model=model_name,
                                prompt=prompt_val,
                                response=record["response"],
                                usage_summary=UsageSummary(
                                    model_usage_summaries={
                                        model_name: ModelUsageSummary(
                                            total_calls=1,
                                            total_input_tokens=record["input_tokens"],
                                            total_output_tokens=record["output_tokens"],
                                        )
                                    }
                                ),
                                execution_time=0.0,
                            ))

                # Record batch-level trace entries and data flow edges
                if current_trace is not None:
                    batch_elapsed = (time.perf_counter() - dispatch_start) * 1000
                    for idx, worker in enumerate(workers):
                        record = getattr(worker, "_call_record", None) or {}
                        ci = batch_start_index + batch_idx + idx
                        result_idx = batch_idx + idx
                        current_trace.llm_calls.append({
                            "index": ci,
                            "type": "batch" if len(batch_prompts) > 1 else "single",
                            "batch_size": len(batch_prompts),
                            "elapsed_ms": round(batch_elapsed, 2),
                            "prompt_len": len(batch_prompts[idx]),
                            "response_len": len(all_results[result_idx]) if result_idx < len(all_results) else 0,
                            "input_tokens": record.get("input_tokens", 0),
                            "output_tokens": record.get("output_tokens", 0),
                            "model": record.get("model"),
                            "finish_reason": record.get("finish_reason"),
                            "error": record.get("error", False),
                            "error_category": record.get("error_category"),
                        })
                    # Register responses with data flow tracker
                    if _data_flow is not None:
                        for idx in range(len(batch_prompts)):
                            result_idx = batch_idx + idx
                            if result_idx < len(all_results):
                                _data_flow.register_response(
                                    batch_start_index + batch_idx + idx,
                                    str(all_results[result_idx]),
                                )
                        current_trace.data_flow_edges = _data_flow.get_edges()

            except Exception as e:
                logger.error(f"Worker dispatch error in batch {batch_num}: {e}")
                # FM-20 fix: preserve results from workers that already completed
                existing = {i for i, w in enumerate(workers) if getattr(w, '_result_ready', False)}
                for idx, _ in enumerate(batch_prompts):
                    if idx not in existing:
                        all_results.append(
                            LLMResult(f"Error: {e}", error=True, error_category="UNKNOWN")
                        )
                    elif idx < len(workers):
                        w = workers[idx]
                        record = getattr(w, "_call_record", {}) or {}
                        if getattr(w, '_result_error', False):
                            all_results.append(LLMResult(
                                w._result, error=True,  # type: ignore[attr-defined]
                                error_category=record.get("error_category", "UNKNOWN"),
                            ))
                        else:
                            all_results.append(LLMResult(
                                w._result, error=False,  # type: ignore[attr-defined]
                                finish_reason=record.get("finish_reason"),
                                input_tokens=record.get("input_tokens", 0),
                                output_tokens=record.get("output_tokens", 0),
                            ))
                    else:
                        all_results.append(
                            LLMResult(f"Error: {e}", error=True, error_category="UNKNOWN")
                        )

            finally:
                for worker in workers:
                    try:
                        worker._pending_prompt = None  # type: ignore[attr-defined]
                        worker._result = None  # type: ignore[attr-defined]
                        worker._result_error = False  # type: ignore[attr-defined]
                        worker._call_record = None  # type: ignore[attr-defined]
                        # Reset structured output wiring
                        if output_schema is not None:
                            worker.output_schema = None
                            worker.tools = []
                            worker.after_tool_callback = None
                            worker.on_tool_error_callback = None
                            if hasattr(worker, "_structured_result"):
                                worker._structured_result = None  # type: ignore[attr-defined]
                        # Detach from ParallelAgent parent so the worker can be
                        # re-used in a future batch (ADK sets parent_agent in
                        # model_post_init and raises if already set).
                        worker.parent_agent = None
                        await worker_pool.release(worker, model)
                    except Exception:
                        logger.warning(
                            "Cleanup failed for worker %s, continuing with remaining workers",
                            getattr(worker, "name", "<unknown>"),
                            exc_info=True,
                        )

        # Aggregate latency via local accumulator (no ctx.session.state reads)
        dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000
        _acc_latencies.append(round(dispatch_elapsed_ms, 2))

        return all_results

    def flush_fn() -> dict:
        """Return accumulated dispatch state and reset accumulators.

        Returns a dict suitable for merging into session state or
        passing to tool_context.state.  After the call, all accumulators
        are reset to zero so the next flush returns only new deltas.
        """
        nonlocal _acc_dispatch_count, _acc_batch_dispatches, _acc_structured_output_failures
        delta: dict[str, Any] = {
            WORKER_DISPATCH_COUNT: _acc_dispatch_count,
            OBS_WORKER_TOTAL_DISPATCHES: _acc_dispatch_count,
            OBS_WORKER_DISPATCH_LATENCY_MS: list(_acc_latencies),
        }
        if _acc_batch_dispatches > 0:
            delta[OBS_WORKER_TOTAL_BATCH_DISPATCHES] = _acc_batch_dispatches
        # Populate per-category error counts (previously dead state keys)
        if _acc_error_counts:
            delta[OBS_WORKER_ERROR_COUNTS] = dict(_acc_error_counts)
            if "RATE_LIMIT" in _acc_error_counts:
                delta[OBS_WORKER_RATE_LIMIT_COUNT] = _acc_error_counts["RATE_LIMIT"]
            if "TIMEOUT" in _acc_error_counts:
                delta[OBS_WORKER_TIMEOUT_COUNT] = _acc_error_counts["TIMEOUT"]
        # Pool exhaustion counter (read from pool object, not local accumulator)
        if worker_pool._pool_exhaustion_count > 0:
            delta[OBS_WORKER_POOL_EXHAUSTION_COUNT] = worker_pool._pool_exhaustion_count
        # Structured output failure counter
        if _acc_structured_output_failures > 0:
            delta[OBS_STRUCTURED_OUTPUT_FAILURES] = _acc_structured_output_failures
        # Reset accumulators
        _acc_dispatch_count = 0
        _acc_batch_dispatches = 0
        _acc_latencies.clear()
        _acc_error_counts.clear()
        _acc_structured_output_failures = 0
        return delta

    return llm_query_async, llm_query_batched_async, flush_fn
