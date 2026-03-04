"""Child orchestrator dispatch mechanism for sub-LM calls.

Replaces the leaf LlmAgent worker pool with recursive child
RLMOrchestratorAgent instances.  Each sub-query spawns a child
orchestrator (with its own REPL + SetModelResponseTool) at depth+1.

Architecture:
- DispatchConfig: Holds model configuration (replaces WorkerPool)
- llm_query_async: Spawn 1 child orchestrator, return LLMResult
- llm_query_batched_async: Spawn K children concurrently (semaphore-limited)
- Depth limit: max_depth prevents infinite recursion

State mutation discipline (AR-CRIT-001):
- Local accumulators in the closure replace ctx.session.state reads.
- flush_fn() snapshots accumulators into tool_context.state via REPLTool.
- Child results are read from child's output_key in session state.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any

from google.adk.agents.invocation_context import InvocationContext
from pydantic import BaseModel

from rlm_adk.callbacks.worker import _classify_error
from rlm_adk.repl.trace import DataFlowTracker
from rlm_adk.types import LLMResult, ModelUsageSummary, RLMChatCompletion, UsageSummary
from rlm_adk.state import (
    OBS_CHILD_DISPATCH_COUNT,
    OBS_CHILD_DISPATCH_LATENCY_MS,
    OBS_CHILD_ERROR_COUNTS,
    OBS_CHILD_TOTAL_BATCH_DISPATCHES,
    OBS_STRUCTURED_OUTPUT_FAILURES,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_ERROR_COUNTS,
    OBS_WORKER_TOTAL_BATCH_DISPATCHES,
    OBS_WORKER_TOTAL_DISPATCHES,
    WORKER_DISPATCH_COUNT,
)

logger = logging.getLogger(__name__)


class DispatchConfig:
    """Holds model configuration for child dispatch (replaces WorkerPool)."""

    def __init__(
        self,
        default_model: str,
        other_model: str | None = None,
        pool_size: int = 5,
    ):
        self.default_model = default_model
        self.other_model = other_model or default_model
        self.pool_size = pool_size

    def ensure_initialized(self):
        """No-op for backward compatibility."""
        pass


# Backward-compatible alias so existing imports continue to work.
WorkerPool = DispatchConfig


def create_dispatch_closures(
    dispatch_config: DispatchConfig,
    ctx: InvocationContext,
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> tuple[Any, Any, Any]:
    """Create llm_query_async, llm_query_batched_async, and flush_fn closures.

    These closures capture the dispatch config and invocation context,
    and are injected into the REPL namespace so that LM-generated code
    can call sub-LM queries via child orchestrators.

    Args:
        dispatch_config: Model configuration (DispatchConfig / WorkerPool alias)
        ctx: Current invocation context
        call_log_sink: Optional list to accumulate RLMChatCompletion records.
        trace_sink: Optional mutable list[REPLTrace | None] holder.
        depth: Current nesting depth (0 = root orchestrator).
        max_depth: Maximum allowed depth.  Overridden by RLM_MAX_DEPTH env var.

    Returns:
        (llm_query_async, llm_query_batched_async, flush_fn) 3-tuple.
        flush_fn() returns a dict of accumulated state and resets accumulators.
    """
    max_depth = int(os.getenv("RLM_MAX_DEPTH", str(max_depth)))
    max_concurrent = int(os.getenv("RLM_MAX_CONCURRENT_CHILDREN", "3"))
    _child_semaphore = asyncio.Semaphore(max_concurrent)

    # Local accumulators — replaces ctx.session.state reads (AR-CRIT-001)
    _acc_child_dispatches = 0
    _acc_child_batch_dispatches = 0
    _acc_child_latencies: list[float] = []
    _acc_child_error_counts: dict[str, int] = {}
    _acc_structured_output_failures = 0

    async def _run_child(
        prompt: str,
        model: str | None,
        output_schema: type[BaseModel] | None,
        fanout_idx: int,
    ) -> LLMResult:
        """Spawn a child orchestrator for a single sub-query."""
        if depth + 1 >= max_depth:
            return LLMResult(
                f"[DEPTH_LIMIT] Cannot dispatch at depth {depth + 1} (max_depth={max_depth})",
                error=True,
                error_category="DEPTH_LIMIT",
            )

        target_model = model or dispatch_config.other_model
        child_start = time.perf_counter()

        from rlm_adk.agent import create_child_orchestrator

        child = create_child_orchestrator(
            model=target_model,
            depth=depth + 1,
            prompt=prompt,
            worker_pool=dispatch_config,
            output_schema=output_schema,
        )

        try:
            async with _child_semaphore:
                async for _event in child.run_async(ctx):
                    pass  # consume events

            # Read result from child's output_key
            _child_output_key = child.reasoning_agent.output_key or f"reasoning_output@d{depth + 1}"
            raw = ctx.session.state.get(_child_output_key, "")

            # Parse the result
            if isinstance(raw, dict):
                answer = raw.get("final_answer", str(raw))
            elif isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        answer = parsed.get("final_answer", raw)
                    else:
                        answer = raw
                except (json.JSONDecodeError, ValueError):
                    answer = raw
            else:
                answer = str(raw)

            elapsed_ms = (time.perf_counter() - child_start) * 1000

            if answer:
                return LLMResult(answer, error=False, model=target_model)
            else:
                return LLMResult(
                    "[Child orchestrator produced no answer]",
                    error=True,
                    error_category="NO_RESULT",
                )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - child_start) * 1000
            logger.error("Child dispatch error at depth %d: %s", depth + 1, e)
            cat = _classify_error(e) if hasattr(e, "code") else "UNKNOWN"
            return LLMResult(f"Error: {e}", error=True, error_category=cat)
        finally:
            # Clean up child's REPL
            if hasattr(child, "repl") and child.repl is not None and not child.persistent:
                try:
                    child.repl.cleanup()
                except Exception:
                    pass

    async def llm_query_async(
        prompt: str,
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> LLMResult:
        """Dispatch a single sub-LM query via child orchestrator.

        Delegates to llm_query_batched_async for consistency.
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
        """Dispatch K sub-LM queries via child orchestrators, concurrently.

        Concurrency is limited by _child_semaphore (max_concurrent).
        """
        if not prompts:
            return []

        k = len(prompts)
        dispatch_start = time.perf_counter()

        # Trace support
        current_trace = trace_sink[0] if trace_sink else None
        _data_flow = DataFlowTracker() if current_trace is not None else None

        if _data_flow is not None and current_trace is not None:
            batch_start_index = current_trace._call_counter
            current_trace._call_counter += k
            for idx, p in enumerate(prompts):
                _data_flow.check_prompt(batch_start_index + idx, p)
        else:
            batch_start_index = 0

        # Update local accumulators
        nonlocal _acc_child_dispatches, _acc_child_batch_dispatches
        _acc_child_dispatches += k
        if k > 1:
            _acc_child_batch_dispatches += 1

        if k > 1:
            print(
                f"[RLM] child dispatch batch ({k} prompts, depth={depth + 1})",
                flush=True,
            )

        # Run all children concurrently (semaphore limits actual concurrency)
        tasks = [
            _run_child(p, model, output_schema, idx)
            for idx, p in enumerate(prompts)
        ]
        results = await asyncio.gather(*tasks)
        all_results = list(results)

        # Aggregate latency
        dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000
        _acc_child_latencies.append(round(dispatch_elapsed_ms, 2))

        # Accumulate errors
        for r in all_results:
            if r.error:
                cat = r.error_category or "UNKNOWN"
                _acc_child_error_counts[cat] = _acc_child_error_counts.get(cat, 0) + 1

        # Record trace entries
        if current_trace is not None:
            batch_elapsed = dispatch_elapsed_ms
            for idx, r in enumerate(all_results):
                ci = batch_start_index + idx
                current_trace.llm_calls.append({
                    "index": ci,
                    "type": "batch" if k > 1 else "single",
                    "batch_size": k,
                    "elapsed_ms": round(batch_elapsed, 2),
                    "prompt_len": len(prompts[idx]),
                    "response_len": len(r),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "model": r.model if isinstance(r, LLMResult) else None,
                    "finish_reason": None,
                    "error": r.error if isinstance(r, LLMResult) else False,
                    "error_category": r.error_category if isinstance(r, LLMResult) else None,
                })
            if _data_flow is not None:
                for idx in range(k):
                    _data_flow.register_response(
                        batch_start_index + idx,
                        str(all_results[idx]),
                    )
                current_trace.data_flow_edges = _data_flow.get_edges()

        return all_results

    def flush_fn() -> dict:
        """Return accumulated dispatch state and reset accumulators."""
        nonlocal _acc_child_dispatches, _acc_child_batch_dispatches, _acc_structured_output_failures
        delta: dict[str, Any] = {
            # Keep WORKER_DISPATCH_COUNT for backward compat with REPLTool
            WORKER_DISPATCH_COUNT: _acc_child_dispatches,
            OBS_WORKER_TOTAL_DISPATCHES: _acc_child_dispatches,
            OBS_CHILD_DISPATCH_COUNT: _acc_child_dispatches,
            OBS_WORKER_DISPATCH_LATENCY_MS: list(_acc_child_latencies),
            OBS_CHILD_DISPATCH_LATENCY_MS: list(_acc_child_latencies),
        }
        if _acc_child_batch_dispatches > 0:
            delta[OBS_WORKER_TOTAL_BATCH_DISPATCHES] = _acc_child_batch_dispatches
            delta[OBS_CHILD_TOTAL_BATCH_DISPATCHES] = _acc_child_batch_dispatches
        if _acc_child_error_counts:
            delta[OBS_WORKER_ERROR_COUNTS] = dict(_acc_child_error_counts)
            delta[OBS_CHILD_ERROR_COUNTS] = dict(_acc_child_error_counts)
        if _acc_structured_output_failures > 0:
            delta[OBS_STRUCTURED_OUTPUT_FAILURES] = _acc_structured_output_failures
        # Reset accumulators
        _acc_child_dispatches = 0
        _acc_child_batch_dispatches = 0
        _acc_child_latencies.clear()
        _acc_child_error_counts.clear()
        _acc_structured_output_failures = 0
        return delta

    return llm_query_async, llm_query_batched_async, flush_fn
