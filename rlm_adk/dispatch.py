"""Worker pool and dispatch mechanism for sub-LM calls.

Replaces the TCP socket-based LMHandler with ADK LlmAgent workers
dispatched via ParallelAgent.

Architecture:
- WorkerPool: Pre-allocated asyncio.Queue of LlmAgent instances per model
- llm_query_async: Acquire 1 worker, dispatch, return string
- llm_query_batched_async: Acquire K workers, dispatch via ParallelAgent, return K strings
- Model routing: model=None uses depth-based default; model="X" uses specific pool

State mutation discipline:
- All state writes go through Event objects via event_queue (AR-CRIT-001).
- Reads from ctx.session.state.get() are acceptable.
- Worker results are read from agent objects (_result, _result_ready) not state.
"""

import asyncio
import logging
import os
import time
from typing import Any

from google.adk.agents import LlmAgent, ParallelAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from google.genai.types import HttpOptions, HttpRetryOptions

from rlm_adk.callbacks.worker import (
    worker_before_model,
    worker_after_model,
    worker_on_model_error,
)
from rlm_adk.repl.trace import DataFlowTracker
from rlm_adk.types import LLMResult, ModelUsageSummary, RLMChatCompletion, UsageSummary
from rlm_adk.state import (
    OBS_WORKER_DIRTY_READ_MISMATCHES,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_TOTAL_BATCH_DISPATCHES,
    OBS_WORKER_TOTAL_DISPATCHES,
    WORKER_DIRTY_READ_COUNT,
    WORKER_DISPATCH_COUNT,
    WORKER_INPUT_TOKENS,
    WORKER_OUTPUT_TOKENS,
    WORKER_PROMPT_CHARS,
    WORKER_CONTENT_COUNT,
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
        worker._result_usage = {"input_tokens": 0, "output_tokens": 0}  # type: ignore[attr-defined]
        worker._result_error = False  # type: ignore[attr-defined]

        # Prompt metrics (written by before_model callback)
        worker._prompt_chars = 0  # type: ignore[attr-defined]
        worker._content_count = 0  # type: ignore[attr-defined]

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
            logger.info(
                "Pool '%s' exhausted, creating worker on demand", target_model
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


async def _drain_events(
    run_iter: Any,
    event_queue: asyncio.Queue[Event],
) -> None:
    """Drain events from an agent's run_async iterator into the event queue."""
    async for event in run_iter:
        event_queue.put_nowait(event)


def create_dispatch_closures(
    worker_pool: WorkerPool,
    ctx: InvocationContext,
    event_queue: asyncio.Queue[Event],
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
) -> tuple[Any, Any]:
    """Create llm_query_async and llm_query_batched_async closures.

    These closures capture the worker pool and invocation context,
    and are injected into the REPL namespace so that LM-generated code
    can call sub-LM queries.

    The closures are async functions. The AST rewriter transforms
    llm_query(p) -> await llm_query_async(p) so that the REPL code
    can call them natively from within async def _repl_exec().

    Args:
        worker_pool: The pre-allocated worker pool
        ctx: Current invocation context
        event_queue: Queue for collecting events from worker dispatch.
            The orchestrator's _run_async_impl drain loop yields these
            to the Runner.
        call_log_sink: Optional list to accumulate RLMChatCompletion records.
        trace_sink: Optional mutable list[REPLTrace | None] holder.
            trace_sink[0] is the current REPLTrace for per-call recording.

    Returns:
        (llm_query_async, llm_query_batched_async) tuple of async callables
    """

    async def llm_query_async(prompt: str, model: str | None = None) -> LLMResult:
        """Dispatch a single sub-LM query via worker pool.

        This is the K=1 case: delegates to llm_query_batched_async.

        Args:
            prompt: The text prompt to send to the sub-LM.
            model: Optional model name override. None uses depth-based default.

        Returns:
            An LLMResult (str subclass) with metadata.
        """
        current_trace = trace_sink[0] if trace_sink else None
        call_index = -1
        call_start = 0.0

        if current_trace is not None:
            call_index = current_trace._call_counter
            current_trace._call_counter += 1
            current_trace.record_llm_start(call_index, prompt, "single")
            call_start = time.perf_counter()

        results = await llm_query_batched_async([prompt], model=model)

        if current_trace is not None:
            elapsed_ms = (time.perf_counter() - call_start) * 1000
            current_trace.record_llm_end(
                call_index, results[0], elapsed_ms,
                error=results[0].error if isinstance(results[0], LLMResult) else False,
            )

        return results[0]

    async def llm_query_batched_async(
        prompts: list[str], model: str | None = None
    ) -> list[LLMResult]:
        """Dispatch K sub-LM queries via ParallelAgent, chunked by max_concurrent.

        When K > max_concurrent, prompts are split into sequential batches
        of at most max_concurrent, each batch dispatched in parallel.

        All state mutations are emitted as Event objects via event_queue
        (AR-CRIT-001: no direct ctx.session.state writes).

        Args:
            prompts: List of text prompts to send concurrently.
            model: Optional model name override. None uses depth-based default.

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

        # Read previous counts for delta computation (reads are safe)
        prev_dispatch_count = ctx.session.state.get(WORKER_DISPATCH_COUNT, 0)
        prev_total = ctx.session.state.get(OBS_WORKER_TOTAL_DISPATCHES, 0)
        prev_batch = ctx.session.state.get(OBS_WORKER_TOTAL_BATCH_DISPATCHES, 0)

        # Emit dispatch accounting as a proper Event via event_queue
        dispatch_delta: dict[str, Any] = {
            WORKER_DISPATCH_COUNT: prev_dispatch_count + k,
            OBS_WORKER_TOTAL_DISPATCHES: prev_total + k,
        }
        if k > 1:
            dispatch_delta[OBS_WORKER_TOTAL_BATCH_DISPATCHES] = prev_batch + 1

        event_queue.put_nowait(Event(
            invocation_id=ctx.invocation_id,
            author="dispatch",
            actions=EventActions(state_delta=dispatch_delta),
        ))

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
                    workers.append(worker)

                if len(workers) == 1:
                    try:
                        await asyncio.wait_for(
                            _drain_events(workers[0].run_async(ctx), event_queue),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        workers[0]._result = f"[Worker {workers[0].name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
                        workers[0]._result_ready = True  # type: ignore[attr-defined]
                        workers[0]._result_error = True  # type: ignore[attr-defined]
                else:
                    parallel = ParallelAgent(
                        name=f"batch_{batch_num}_{len(workers)}",
                        sub_agents=list(workers),  # type: ignore[arg-type]
                    )
                    try:
                        await asyncio.wait_for(
                            _drain_events(parallel.run_async(ctx), event_queue),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        for w in workers:
                            if not getattr(w, '_result_ready', False):
                                w._result = f"[Worker {w.name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
                                w._result_ready = True  # type: ignore[attr-defined]
                                w._result_error = True  # type: ignore[attr-defined]

                # Read results from worker objects (no dirty state reads)
                dirty_read_count = 0
                mismatches = 0
                for worker in workers:
                    dirty_read_count += 1
                    record = getattr(worker, "_call_record", {}) or {}
                    if not worker._result_ready:  # type: ignore[attr-defined]
                        logger.error(
                            "Worker %s produced no result. Events pending: %d",
                            worker.name, event_queue.qsize(),
                        )
                        all_results.append(LLMResult(
                            "", error=True, error_category="NO_RESULT",
                        ))
                        mismatches += 1
                    elif getattr(worker, '_result_error', False):
                        logger.warning(
                            "Worker %s returned error result: %s",
                            worker.name, worker._result,  # type: ignore[attr-defined]
                        )
                        all_results.append(LLMResult(
                            worker._result,  # type: ignore[attr-defined]
                            error=True,
                            error_category=record.get("error_category", "UNKNOWN"),
                            http_status=record.get("http_status"),
                            finish_reason=record.get("finish_reason"),
                            model=record.get("model"),
                        ))
                    else:
                        all_results.append(LLMResult(
                            worker._result,  # type: ignore[attr-defined]
                            error=False,
                            finish_reason=record.get("finish_reason"),
                            input_tokens=record.get("input_tokens", 0),
                            output_tokens=record.get("output_tokens", 0),
                            model=record.get("model"),
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

                # Emit post-dispatch accounting via event_queue
                event_queue.put_nowait(Event(
                    invocation_id=ctx.invocation_id,
                    author="dispatch",
                    actions=EventActions(state_delta={
                        WORKER_DIRTY_READ_COUNT: dirty_read_count,
                        OBS_WORKER_DIRTY_READ_MISMATCHES: mismatches,
                    }),
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
                all_results.extend([
                    LLMResult(f"Error: {e}", error=True, error_category="UNKNOWN")
                    for _ in batch_prompts
                ])

            finally:
                for worker in workers:
                    worker._pending_prompt = None  # type: ignore[attr-defined]
                    worker._result = None  # type: ignore[attr-defined]
                    worker._result_error = False  # type: ignore[attr-defined]
                    worker._call_record = None  # type: ignore[attr-defined]
                    # Detach from ParallelAgent parent so the worker can be
                    # re-used in a future batch (ADK sets parent_agent in
                    # model_post_init and raises if already set).
                    worker.parent_agent = None
                    await worker_pool.release(worker, model)

        # Aggregate token accounting from worker objects (sequential, no race)
        # Note: workers have been released back to pool at this point, but we
        # already read all needed data above. For latency, we still have the
        # timing from dispatch_start.
        dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000
        latencies = ctx.session.state.get(OBS_WORKER_DISPATCH_LATENCY_MS, [])
        latencies_new = list(latencies) + [round(dispatch_elapsed_ms, 2)]

        event_queue.put_nowait(Event(
            invocation_id=ctx.invocation_id,
            author="dispatch",
            actions=EventActions(state_delta={
                OBS_WORKER_DISPATCH_LATENCY_MS: latencies_new,
            }),
        ))

        return all_results

    return llm_query_async, llm_query_batched_async
