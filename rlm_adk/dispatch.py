"""Worker pool and dispatch mechanism for sub-LM calls.

Replaces the TCP socket-based LMHandler with ADK LlmAgent workers
dispatched via ParallelAgent.

Architecture:
- WorkerPool: Pre-allocated asyncio.Queue of LlmAgent instances per model
- llm_query_async: Acquire 1 worker, dispatch, return string
- llm_query_batched_async: Acquire K workers, dispatch via ParallelAgent, return K strings
- Model routing: model=None uses depth-based default; model="X" uses specific pool
"""

import asyncio
import logging
import os
import time
from typing import Any

from google.adk.agents import LlmAgent, ParallelAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from rlm_adk.callbacks.worker import worker_before_model, worker_after_model
from rlm_adk.state import (
    OBS_WORKER_DIRTY_READ_MISMATCHES,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_TOTAL_BATCH_DISPATCHES,
    OBS_WORKER_TOTAL_DISPATCHES,
    WORKER_DIRTY_READ_COUNT,
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
            generate_content_config=types.GenerateContentConfig(
                temperature=0.0,
            ),
        )
        # Slot for the dispatch closure to inject the prompt before dispatch.
        # The worker's before_model_callback reads this to build the LlmRequest.
        worker._pending_prompt = None  # type: ignore[attr-defined]
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


def create_dispatch_closures(
    worker_pool: WorkerPool,
    ctx: InvocationContext,
    event_queue: asyncio.Queue[Event],
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

    Returns:
        (llm_query_async, llm_query_batched_async) tuple of async callables
    """

    async def llm_query_async(prompt: str, model: str | None = None) -> str:
        """Dispatch a single sub-LM query via worker pool.

        This is the K=1 case: delegates to llm_query_batched_async.

        Args:
            prompt: The text prompt to send to the sub-LM.
            model: Optional model name override. None uses depth-based default.

        Returns:
            The LM's text response as a string.
        """
        results = await llm_query_batched_async([prompt], model=model)
        return results[0]

    async def llm_query_batched_async(
        prompts: list[str], model: str | None = None
    ) -> list[str]:
        """Dispatch K sub-LM queries via ParallelAgent, chunked by max_concurrent.

        When K > max_concurrent, prompts are split into sequential batches
        of at most max_concurrent, each batch dispatched in parallel.

        Args:
            prompts: List of text prompts to send concurrently.
            model: Optional model name override. None uses depth-based default.

        Returns:
            List of LM text responses, in the same order as prompts.
        """
        if not prompts:
            return []

        max_concurrent = int(os.getenv("RLM_MAX_CONCURRENT_WORKERS", "4"))
        k = len(prompts)
        dispatch_start = time.perf_counter()

        # Track dispatch count
        prev_dispatch_count = ctx.session.state.get(WORKER_DISPATCH_COUNT, 0)
        ctx.session.state[WORKER_DISPATCH_COUNT] = prev_dispatch_count + k

        # Track batch vs single dispatches (session-scoped)
        if k > 1:
            prev_batch = ctx.session.state.get(OBS_WORKER_TOTAL_BATCH_DISPATCHES, 0)
            ctx.session.state[OBS_WORKER_TOTAL_BATCH_DISPATCHES] = prev_batch + 1
        prev_total = ctx.session.state.get(OBS_WORKER_TOTAL_DISPATCHES, 0)
        ctx.session.state[OBS_WORKER_TOTAL_DISPATCHES] = prev_total + k

        all_results: list[str] = []

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
                    worker._pending_prompt = prompt  # type: ignore[attr-defined]
                    workers.append(worker)

                if len(workers) == 1:
                    async for event in workers[0].run_async(ctx):
                        event_queue.put_nowait(event)
                else:
                    parallel = ParallelAgent(
                        name=f"batch_{batch_num}_{len(workers)}",
                        sub_agents=workers,
                    )
                    async for event in parallel.run_async(ctx):
                        event_queue.put_nowait(event)

                # Dirty-read results for this batch
                dirty_read_count = ctx.session.state.get(WORKER_DIRTY_READ_COUNT, 0)
                mismatches = ctx.session.state.get(OBS_WORKER_DIRTY_READ_MISMATCHES, 0)

                for worker in workers:
                    output_key = worker.output_key
                    result = ctx.session.state.get(output_key, "")
                    dirty_read_count += 1

                    if not result:
                        logger.warning(
                            "State timing guard: worker %s output_key '%s' "
                            "returned empty after dispatch (dirty read). "
                            "Events pending in queue: %d",
                            worker.name, output_key, event_queue.qsize(),
                        )
                        mismatches += 1

                    all_results.append(str(result) if result else "")

                ctx.session.state[WORKER_DIRTY_READ_COUNT] = dirty_read_count
                ctx.session.state[OBS_WORKER_DIRTY_READ_MISMATCHES] = mismatches

            except Exception as e:
                logger.error(f"Worker dispatch error in batch {batch_num}: {e}")
                all_results.extend([f"Error: {e}"] * len(batch_prompts))

            finally:
                for worker in workers:
                    worker._pending_prompt = None  # type: ignore[attr-defined]
                    # Detach from ParallelAgent parent so the worker can be
                    # re-used in a future batch (ADK sets parent_agent in
                    # model_post_init and raises if already set).
                    worker.parent_agent = None
                    await worker_pool.release(worker, model)

        # Record total dispatch latency
        dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000
        latencies = ctx.session.state.get(OBS_WORKER_DISPATCH_LATENCY_MS, [])
        latencies.append(round(dispatch_elapsed_ms, 2))
        ctx.session.state[OBS_WORKER_DISPATCH_LATENCY_MS] = latencies

        return all_results

    return llm_query_async, llm_query_batched_async
