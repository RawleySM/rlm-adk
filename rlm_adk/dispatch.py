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
- post_dispatch_state_patch_fn() returns minimal working-state patch
  (DYN_SKILL_INSTRUCTION restoration only).
- Child completion is read from _rlm_terminal_completion attrs, not state.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import BaseModel

from rlm_adk.repl.trace import DataFlowTracker
from rlm_adk.state import DYN_SKILL_INSTRUCTION, parse_depth_key, should_capture_state_key
from rlm_adk.types import (
    CompletionEnvelope,
    LLMResult,
    ModelUsageSummary,
    RLMChatCompletion,
    UsageSummary,
    render_completion_text,
)

logger = logging.getLogger(__name__)


def _classify_error(error: Exception) -> str:
    """Classify an exception into an error category for observability."""
    import json as _json_mod

    code = getattr(error, "code", None)
    # LiteLLM exceptions use status_code (int) instead of code (str).
    # Fall back to status_code when code is missing or non-integer.
    status_code = getattr(error, "status_code", None)
    if (code is None or not isinstance(code, int)) and isinstance(status_code, int):
        code = status_code
    if isinstance(error, asyncio.TimeoutError):
        return "TIMEOUT"
    # Also detect litellm.Timeout which is not an asyncio.TimeoutError
    try:
        import litellm as _litellm_mod

        if isinstance(error, _litellm_mod.Timeout):
            return "TIMEOUT"
    except ImportError:
        pass
    if code == 429:
        return "RATE_LIMIT"
    if code in (401, 403):
        return "AUTH"
    if code and isinstance(code, int) and code >= 500:
        return "SERVER"
    if code and isinstance(code, int) and code >= 400:
        return "CLIENT"
    if isinstance(error, (ConnectionError, OSError)):
        return "NETWORK"
    # Detect JSON parse / malformed response errors
    if isinstance(error, (_json_mod.JSONDecodeError, ValueError)):
        err_msg = str(error).lower()
        if isinstance(error, _json_mod.JSONDecodeError) or "json" in err_msg:
            return "PARSE_ERROR"
    # Check error message for JSON-related patterns (e.g., wrapped exceptions)
    err_str = str(error).lower()
    if any(pat in err_str for pat in ("json", "malformed", "parse error", "decode")):
        return "PARSE_ERROR"
    return "UNKNOWN"


class DispatchConfig:
    """Holds model configuration for child dispatch (replaces WorkerPool)."""

    def __init__(
        self,
        default_model: "str | Any",
        other_model: "str | Any | None" = None,
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
    max_depth: int = 10,
    instruction_router: Any = None,
    fanout_idx: int = 0,
    child_event_queue: "asyncio.Queue[Event] | None" = None,
) -> tuple[Any, Any, Any]:
    """Create dispatch closures for child orchestrator sub-LM calls.

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
        (llm_query_async, llm_query_batched_async,
         post_dispatch_state_patch_fn) 3-tuple.
        post_dispatch_state_patch_fn() returns a minimal working-state
        patch dict (DYN_SKILL_INSTRUCTION restoration only).
    """
    max_depth = int(os.getenv("RLM_MAX_DEPTH", str(max_depth)))
    max_concurrent = int(os.getenv("RLM_MAX_CONCURRENT_CHILDREN", "3"))
    _child_semaphore = asyncio.Semaphore(max_concurrent)

    _parent_fanout_idx = fanout_idx

    # Pre-compute parent's skill instruction for state patch restoration
    _parent_skill_instruction: str | None = None
    if instruction_router is not None:
        _parent_skill_instruction = instruction_router(depth, _parent_fanout_idx)

    def _build_call_log(
        prompt: str,
        result: LLMResult,
        elapsed_ms: float,
    ) -> None:
        """Append a structured child-call record for REPL observability."""
        if call_log_sink is None:
            return
        model_name = str(result.model or dispatch_config.other_model)
        call_log_sink.append(
            RLMChatCompletion(
                root_model=model_name,
                prompt=prompt,
                response=str(result),
                usage_summary=UsageSummary(
                    model_usage_summaries={
                        model_name: ModelUsageSummary(
                            total_calls=1,
                            total_input_tokens=getattr(result, "input_tokens", 0) or 0,
                            total_output_tokens=getattr(result, "output_tokens", 0) or 0,
                        )
                    }
                ),
                execution_time=elapsed_ms / 1000.0,
                finish_reason=result.finish_reason,
                thoughts_tokens=result.thoughts_tokens,
                visible_response=result.visible_text,
                thought_response=result.thought_text,
                raw_response=result.raw_output,
                parsed_response=result.parsed,
            )
        )

    def _read_child_completion(
        child: Any,
        child_depth: int,
        child_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect the child's normalized completion payload.

        Priority order:
        1. child._rlm_terminal_completion (on orchestrator)
        2. child.reasoning_agent._rlm_terminal_completion
        3. fallback to _structured_result (any type)
        4. fallback to output_key
        5. error

        Does NOT mine child_state for OBS_REASONING_RETRY_*,
        OBS_CHILD_*, or other nested observability keys.
        """
        agent = getattr(child, "reasoning_agent", None)

        # Priority 1 & 2: CompletionEnvelope
        envelope = getattr(child, "_rlm_terminal_completion", None)
        if envelope is None:
            envelope = getattr(agent, "_rlm_terminal_completion", None)

        if isinstance(envelope, CompletionEnvelope):
            return {
                "text": envelope.display_text or "",
                "error": envelope.error,
                "error_category": envelope.error_category,
                "parsed_output": envelope.validated_output,
                "raw_output": envelope.raw_output,
                "finish_reason": envelope.finish_reason,
                "reasoning_summary": (envelope.reasoning_summary or ""),
            }

        # Priority 3: _structured_result (any validated type)
        structured = getattr(agent, "_structured_result", None)
        if structured is not None:
            text = render_completion_text(structured)
            return {
                "text": text,
                "error": False,
                "error_category": None,
                "parsed_output": structured,
                "raw_output": structured,
                "finish_reason": None,
                "reasoning_summary": "",
            }

        # Priority 4: output_key fallback
        output_key = getattr(agent, "output_key", None) or f"reasoning_output@d{child_depth}"
        raw = child_state.get(output_key)
        if raw is not None:
            text = render_completion_text(raw)
            parsed_payload = None
            if isinstance(raw, dict):
                parsed_payload = dict(raw)
            elif isinstance(raw, str):
                try:
                    decoded = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    decoded = None
                if isinstance(decoded, dict):
                    parsed_payload = decoded
            return {
                "text": text,
                "error": False,
                "error_category": None,
                "parsed_output": parsed_payload,
                "raw_output": raw,
                "finish_reason": None,
                "reasoning_summary": "",
            }

        # Priority 5: error
        return {
            "text": "",
            "error": True,
            "error_category": "NO_RESULT",
            "parsed_output": None,
            "raw_output": None,
            "finish_reason": None,
            "reasoning_summary": "",
        }

    async def _run_child(
        prompt: str,
        model: str | None,
        output_schema: type[BaseModel] | None,
        fanout_idx: int,
    ) -> LLMResult:
        """Spawn a child orchestrator for a single sub-query."""
        # Preserve the raw model object for create_child_orchestrator
        # so _resolve_model()'s CRIT-1 check can pass LiteLlm objects
        # through unchanged.  str() only for logging / LLMResult.model.
        raw_model = model if model is not None else dispatch_config.other_model
        target_model = str(raw_model)
        if depth + 1 >= max_depth:
            result = LLMResult(
                f"[DEPTH_LIMIT] Cannot dispatch at depth {depth + 1} (max_depth={max_depth})",
                error=True,
                error_category="DEPTH_LIMIT",
                model=target_model,
            )
            _build_call_log(prompt, result, 0.0)
            return result

        child_start = time.perf_counter()
        elapsed_ms = 0.0
        _child_result: LLMResult | None = None
        _call_logged = False
        _child_state: dict[str, Any] = {}

        from rlm_adk.agent import create_child_orchestrator

        child = create_child_orchestrator(
            model=raw_model,
            depth=depth + 1,
            prompt=prompt,
            worker_pool=dispatch_config,
            output_schema=output_schema,
            fanout_idx=fanout_idx,
            parent_fanout_idx=_parent_fanout_idx,
            instruction_router=instruction_router,
        )

        try:
            async with _child_semaphore:
                # Branch isolation: give the child its own event-history
                # branch so it doesn't see (or pollute) the parent's
                # conversation history.  Same pattern as ParallelAgent.
                child_ctx = ctx.model_copy()
                branch_suffix = f"{ctx.agent.name}.{child.name}"
                child_ctx.branch = f"{ctx.branch}.{branch_suffix}" if ctx.branch else branch_suffix
                async for _event in child.run_async(child_ctx):
                    actions = getattr(_event, "actions", None)
                    state_delta = getattr(actions, "state_delta", None) if actions else None
                    if isinstance(state_delta, dict):
                        _child_state.update(state_delta)
                        # Push curated state-delta events onto queue for parent re-emission
                        if child_event_queue is not None:
                            curated = {
                                k: v
                                for k, v in state_delta.items()
                                if should_capture_state_key(parse_depth_key(k)[0])
                            }
                            if curated:
                                child_event_queue.put_nowait(
                                    Event(
                                        invocation_id=ctx.invocation_id,
                                        author=_event.author or f"child_d{depth + 1}f{fanout_idx}",
                                        branch=child_ctx.branch,
                                        actions=EventActions(state_delta=curated),
                                        custom_metadata={
                                            "rlm_child_event": True,
                                            "child_depth": depth + 1,
                                            "child_fanout_idx": fanout_idx,
                                        },
                                    )
                                )

            child_depth = depth + 1
            completion = _read_child_completion(
                child,
                child_depth,
                _child_state,
            )
            answer = completion["text"]

            elapsed_ms = (time.perf_counter() - child_start) * 1000

            if answer:
                parsed_payload = completion.get("parsed_output")
                raw_payload = completion.get("raw_output")
                is_error = bool(completion.get("error"))
                error_category = completion.get("error_category")
                finish_reason = completion.get("finish_reason")
                _child_result = LLMResult(
                    answer,
                    error=is_error,
                    error_category=(error_category if is_error else None),
                    model=target_model,
                    raw_output=raw_payload,
                    parsed=parsed_payload,
                    finish_reason=finish_reason,
                    wall_time_ms=round(elapsed_ms, 2),
                )
            else:
                error_text = (
                    "[Child structured output validation exhausted before producing a result]"
                    if output_schema is not None
                    else "[Child orchestrator produced no answer]"
                )
                _child_result = LLMResult(
                    error_text,
                    error=True,
                    error_category=(
                        "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else "NO_RESULT"
                    ),
                    model=target_model,
                    wall_time_ms=round(elapsed_ms, 2),
                )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - child_start) * 1000
            logger.error(
                "Child dispatch error at depth %d: %s",
                depth + 1,
                e,
            )
            cat = (
                "SCHEMA_VALIDATION_EXHAUSTED"
                if output_schema is not None
                else (
                    _classify_error(e)
                    if (hasattr(e, "code") or hasattr(e, "status_code"))
                    else "UNKNOWN"
                )
            )
            _child_result = LLMResult(
                f"Error: {e}",
                error=True,
                error_category=cat,
                model=target_model,
                wall_time_ms=round(elapsed_ms, 2),
            )
        finally:
            if _child_result is not None and not _call_logged:
                _build_call_log(prompt, _child_result, elapsed_ms)
                _call_logged = True
            # Clean up child's REPL
            if hasattr(child, "repl") and child.repl is not None and not child.persistent:
                try:
                    child.repl.cleanup()
                except Exception:
                    pass

        return _child_result

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
            [prompt],
            model=model,
            output_schema=output_schema,
            _record_trace_entries=False,
        )

        if current_trace is not None:
            elapsed_ms = (time.perf_counter() - call_start) * 1000
            current_trace.record_llm_end(
                call_index,
                results[0],
                elapsed_ms,
                error=results[0].error if isinstance(results[0], LLMResult) else False,
                input_tokens=getattr(results[0], "input_tokens", 0),
                output_tokens=getattr(results[0], "output_tokens", 0),
                thoughts_tokens=getattr(results[0], "thoughts_tokens", 0),
                finish_reason=getattr(results[0], "finish_reason", None),
                model=getattr(results[0], "model", None),
            )

        return results[0]

    async def llm_query_batched_async(
        prompts: list[str],
        model: str | None = None,
        output_schema: type[BaseModel] | None = None,
        _record_trace_entries: bool = True,
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

        if k > 1:
            print(
                f"[RLM] child dispatch batch ({k} prompts, depth={depth + 1})",
                flush=True,
            )

        # Run all children concurrently (semaphore limits actual concurrency)
        tasks = [_run_child(p, model, output_schema, idx) for idx, p in enumerate(prompts)]
        results = await asyncio.gather(*tasks)
        all_results = list(results)

        dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000

        # Record trace entries
        if current_trace is not None and _record_trace_entries:
            batch_elapsed = dispatch_elapsed_ms
            for idx, r in enumerate(all_results):
                ci = batch_start_index + idx
                current_trace.llm_calls.append(
                    {
                        "index": ci,
                        "type": "batch" if k > 1 else "single",
                        "batch_size": k,
                        "elapsed_ms": round(batch_elapsed, 2),
                        "prompt_len": len(prompts[idx]),
                        "response_len": len(r),
                        "input_tokens": getattr(r, "input_tokens", 0),
                        "output_tokens": getattr(r, "output_tokens", 0),
                        "thoughts_tokens": getattr(r, "thoughts_tokens", 0),
                        "model": r.model if isinstance(r, LLMResult) else None,
                        "finish_reason": getattr(r, "finish_reason", None),
                        "error": r.error if isinstance(r, LLMResult) else False,
                        "error_category": r.error_category if isinstance(r, LLMResult) else None,
                    }
                )
            if _data_flow is not None:
                for idx in range(k):
                    _data_flow.register_response(
                        batch_start_index + idx,
                        str(all_results[idx]),
                    )
                current_trace.data_flow_edges.extend(_data_flow.get_edges())

        return all_results

    def post_dispatch_state_patch_fn() -> dict[str, Any]:
        """Return minimal working-state patch after dispatch.

        Only restores DYN_SKILL_INSTRUCTION if an instruction
        router was configured.  No lineage or observability keys.
        """
        delta: dict[str, Any] = {}
        if _parent_skill_instruction is not None:
            delta[DYN_SKILL_INSTRUCTION] = _parent_skill_instruction
        return delta

    return (
        llm_query_async,
        llm_query_batched_async,
        post_dispatch_state_patch_fn,
    )
