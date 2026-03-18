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

from rlm_adk.callbacks.worker_retry import _bug13_stats
from rlm_adk.repl.trace import DataFlowTracker
from rlm_adk.state import (
    DYN_SKILL_INSTRUCTION,
    OBS_BUG13_SUPPRESS_COUNT,
    OBS_CHILD_BATCH_DISPATCHES_TOTAL,
    OBS_CHILD_DISPATCH_COUNT,
    OBS_CHILD_DISPATCH_COUNT_TOTAL,
    OBS_CHILD_DISPATCH_LATENCY_MS,
    OBS_CHILD_ERROR_COUNTS,
    OBS_CHILD_ERROR_COUNTS_TOTAL,
    OBS_CHILD_TOTAL_BATCH_DISPATCHES,
    OBS_REASONING_RETRY_COUNT,
    OBS_REASONING_RETRY_DELAY_MS,
    OBS_STRUCTURED_OUTPUT_FAILURES,
    OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL,
    REASONING_FINISH_REASON,
    REASONING_INPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
    REASONING_PARSED_OUTPUT,
    REASONING_RAW_OUTPUT,
    REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS,
    REASONING_VISIBLE_OUTPUT_TEXT,
    child_obs_key,
    depth_key,
)
from rlm_adk.types import LLMResult, ModelUsageSummary, RLMChatCompletion, UsageSummary

logger = logging.getLogger(__name__)
_CHILD_PREVIEW_LIMIT = 500


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


def _truncate_text(value: Any, limit: int = _CHILD_PREVIEW_LIMIT) -> str | None:
    """Return a bounded text preview for evaluator-facing state."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text[:limit]


def _preview_payload(value: Any, limit: int = _CHILD_PREVIEW_LIMIT) -> str | None:
    """Return a bounded preview for arbitrary payloads."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.dumps(value, sort_keys=True)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def _persist_payload(value: Any) -> Any:
    """Return a JSON-serializable full payload for persisted child summaries."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_persist_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_persist_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _persist_payload(item) for key, item in value.items()}
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _safe_int(value: Any) -> int:
    """Best-effort integer coercion for telemetry fields."""
    return value if isinstance(value, int) else 0


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
    max_depth: int = 5,
    instruction_router: Any = None,
    fanout_idx: int = 0,
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
    _acc_child_summaries: dict[str, dict] = {}
    _acc_structured_output_failures = 0
    _parent_fanout_idx = fanout_idx

    # Cumulative accumulators — never reset by flush_fn (monotonically non-decreasing)
    _cum_child_dispatches = 0
    _cum_child_batch_dispatches = 0
    _cum_child_error_counts: dict[str, int] = {}
    _cum_structured_output_failures = 0

    # Pre-compute parent's skill instruction for flush_fn restoration
    _parent_skill_instruction: str | None = None
    if instruction_router is not None:
        _parent_skill_instruction = instruction_router(depth, _parent_fanout_idx)

    def _child_obs_value(
        child_state: dict[str, Any],
        shared_state: dict[str, Any],
        key: str,
        child_depth: int,
    ) -> Any:
        """Read a child-scoped observability key, preferring child-local deltas."""
        scoped_key = depth_key(key, child_depth)
        if scoped_key in child_state:
            return child_state.get(scoped_key)
        return shared_state.get(scoped_key)

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

    def _serialize_child_payload(value: Any) -> str:
        """Return a stable text form for child structured results."""
        if isinstance(value, dict):
            try:
                return json.dumps(value, separators=(",", ":"), sort_keys=True)
            except (TypeError, ValueError):
                return str(value)
        if value is None:
            return ""
        return str(value)

    def _read_child_completion(
        child: Any,
        child_depth: int,
        child_state: dict[str, Any],
        shared_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect the child's normalized completion payload.

        Args:
            child: The child orchestrator agent whose completion to read.
            child_depth: Recursion depth of the child agent.
            child_state: Session state dict local to the child agent.
            shared_state: Shared session state dict accessible across depths.
        """
        agent = getattr(child, "reasoning_agent", None)
        completion = getattr(child, "_rlm_completion", None) or getattr(
            agent, "_rlm_completion", None
        )
        normalized = dict(completion) if isinstance(completion, dict) else {}

        parsed_payload = normalized.get("parsed_output")
        if not isinstance(parsed_payload, dict):
            parsed_payload = None

        raw_payload = normalized.get("raw_output")
        text = str(normalized.get("text", "") or "")
        error = bool(normalized.get("error", False))
        error_category = normalized.get("error_category")
        parsed_from_state = _child_obs_value(
            child_state, shared_state, REASONING_PARSED_OUTPUT, child_depth
        )
        if isinstance(parsed_from_state, dict):
            parsed_payload = dict(parsed_from_state)
        raw_from_state = _child_obs_value(
            child_state, shared_state, REASONING_RAW_OUTPUT, child_depth
        )
        if raw_from_state is not None:
            raw_payload = raw_from_state

        output_key = getattr(agent, "output_key", None) or f"reasoning_output@d{child_depth}"
        raw = child_state.get(output_key, shared_state.get(output_key))
        if raw_payload is None and raw is not None:
            raw_payload = raw

        if not text and raw is not None:
            if isinstance(raw, dict):
                parsed_payload = dict(raw)
                text = str(raw.get("final_answer", "") or "") or _serialize_child_payload(raw)
            elif isinstance(raw, str):
                try:
                    decoded = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    decoded = None
                if isinstance(decoded, dict):
                    parsed_payload = decoded
                    text = str(decoded.get("final_answer", "") or "") or _serialize_child_payload(
                        decoded
                    )
                else:
                    text = raw
            else:
                text = str(raw)

        structured = getattr(agent, "_structured_result", None)
        if not text and isinstance(structured, dict):
            parsed_payload = dict(structured)
            raw_payload = structured
            text = str(structured.get("final_answer", "") or "") or _serialize_child_payload(
                structured
            )

        if text.startswith("[RLM ERROR]"):
            error = True
            error_category = error_category or "UNKNOWN"

        def _read(key: str) -> Any:
            return _child_obs_value(child_state, shared_state, key, child_depth)

        return {
            "text": text,
            "error": error,
            "error_category": error_category,
            "parsed_output": parsed_payload,
            "raw_output": raw_payload,
            "reasoning_summary": normalized.get("reasoning_summary"),
            "visible_output_text": (
                _read(REASONING_VISIBLE_OUTPUT_TEXT) or normalized.get("visible_output_text")
            ),
            "thought_text": (_read(REASONING_THOUGHT_TEXT) or normalized.get("thought_text")),
            "finish_reason": _read(REASONING_FINISH_REASON) or normalized.get("finish_reason"),
            "input_tokens": _read(REASONING_INPUT_TOKENS) or normalized.get("input_tokens"),
            "output_tokens": _read(REASONING_OUTPUT_TOKENS) or normalized.get("output_tokens"),
            "thoughts_tokens": (
                _read(REASONING_THOUGHT_TOKENS) or normalized.get("thoughts_tokens")
            ),
            "reasoning_retry_count": _safe_int(child_state.get(OBS_REASONING_RETRY_COUNT, 0)),
            "reasoning_retry_delay_ms": _safe_int(child_state.get(OBS_REASONING_RETRY_DELAY_MS, 0)),
            "nested_child_dispatch_count": _safe_int(child_state.get(OBS_CHILD_DISPATCH_COUNT, 0)),
            "nested_child_batch_dispatches": _safe_int(
                child_state.get(OBS_CHILD_TOTAL_BATCH_DISPATCHES, 0)
            ),
            "nested_child_error_counts": child_state.get(OBS_CHILD_ERROR_COUNTS),
            "nested_structured_output_failures": _safe_int(
                child_state.get(OBS_STRUCTURED_OUTPUT_FAILURES, 0)
            ),
        }

    async def _run_child(
        prompt: str,
        model: str | None,
        output_schema: type[BaseModel] | None,
        fanout_idx: int,
    ) -> LLMResult:
        """Spawn a child orchestrator for a single sub-query."""
        nonlocal _acc_structured_output_failures, _cum_structured_output_failures
        # Preserve the raw model object for create_child_orchestrator so that
        # _resolve_model()'s CRIT-1 check can pass LiteLlm objects through
        # unchanged.  Use str() only for logging / dict keys / LLMResult.model.
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
        _error_message: str | None = None
        _call_logged = False
        completion: dict[str, Any] = {}
        _child_state: dict[str, Any] = {}
        session = getattr(ctx, "session", None)
        shared_state = getattr(session, "state", {})

        from rlm_adk.agent import create_child_orchestrator

        child = create_child_orchestrator(
            model=raw_model,
            depth=depth + 1,
            prompt=prompt,
            worker_pool=dispatch_config,
            output_schema=output_schema,
            fanout_idx=fanout_idx,
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
                    state_delta = getattr(actions, "state_delta", None)
                    if isinstance(state_delta, dict):
                        _child_state.update(state_delta)

            child_depth = depth + 1
            completion = _read_child_completion(child, child_depth, _child_state, shared_state)
            answer = completion["text"]

            elapsed_ms = (time.perf_counter() - child_start) * 1000

            if answer:
                input_tokens = completion.get("input_tokens") or 0
                output_tokens = completion.get("output_tokens") or 0
                thought_tokens = completion.get("thoughts_tokens") or 0
                finish_reason = completion.get("finish_reason")
                visible_text = completion.get("visible_output_text") or answer
                thought_text = completion.get("thought_text") or ""
                parsed_payload = completion.get("parsed_output")
                raw_payload = completion.get("raw_output")
                is_error = bool(completion.get("error"))
                error_category = completion.get("error_category")
                if is_error and error_category == "SCHEMA_VALIDATION_EXHAUSTED":
                    _acc_structured_output_failures += 1
                    _cum_structured_output_failures += 1
                _child_result = LLMResult(
                    answer,
                    error=is_error,
                    error_category=error_category if is_error else None,
                    model=target_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    thoughts_tokens=thought_tokens,
                    finish_reason=finish_reason,
                    visible_text=visible_text,
                    thought_text=thought_text,
                    raw_output=raw_payload,
                    parsed=parsed_payload if isinstance(parsed_payload, dict) else None,
                    wall_time_ms=round(elapsed_ms, 2),
                )
                _error_message = answer if is_error else None
            else:
                if output_schema is not None:
                    _acc_structured_output_failures += 1
                    _cum_structured_output_failures += 1
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
                _error_message = error_text
        except Exception as e:
            elapsed_ms = (time.perf_counter() - child_start) * 1000
            logger.error("Child dispatch error at depth %d: %s", depth + 1, e)
            cat = (
                "SCHEMA_VALIDATION_EXHAUSTED"
                if output_schema is not None
                else (
                    _classify_error(e)
                    if (hasattr(e, "code") or hasattr(e, "status_code"))
                    else "UNKNOWN"
                )
            )
            if cat == "SCHEMA_VALIDATION_EXHAUSTED":
                _acc_structured_output_failures += 1
                _cum_structured_output_failures += 1
            _error_message = str(e)
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
            child_depth = depth + 1
            child_reasoning = getattr(child, "reasoning_agent", None)
            structured_obs = getattr(child_reasoning, "_structured_output_obs", {})
            structured_result = getattr(child_reasoning, "_structured_result", None)
            structured_attempts = _safe_int(
                structured_obs.get("attempts") if isinstance(structured_obs, dict) else 0
            )
            structured_retries = _safe_int(
                structured_obs.get("retry_count") if isinstance(structured_obs, dict) else 0
            )
            structured_events = (
                list(structured_obs.get("events", [])) if isinstance(structured_obs, dict) else []
            )
            parsed_output = (
                getattr(_child_result, "parsed", None)
                if isinstance(_child_result, LLMResult)
                else None
            )
            if not isinstance(parsed_output, dict) and isinstance(structured_result, dict):
                parsed_output = dict(structured_result)
            validated_structured_result = (
                dict(structured_result)
                if isinstance(structured_result, dict)
                else (dict(parsed_output) if isinstance(parsed_output, dict) else None)
            )
            if output_schema is None:
                structured_outcome = "not_applicable"
            elif (
                isinstance(_child_result, LLMResult)
                and _child_result.error
                and structured_attempts > 0
            ):
                structured_outcome = "retry_exhausted"
            elif isinstance(parsed_output, dict):
                structured_outcome = "retry_recovered" if structured_retries > 0 else "validated"
            elif structured_attempts > 0:
                structured_outcome = "incomplete"
            else:
                structured_outcome = "missing"
            # Write per-child observability summary
            _acc_child_summaries[child_obs_key(depth + 1, fanout_idx)] = {
                "model": target_model,
                "depth": child_depth,
                "fanout_idx": fanout_idx,
                "parent_depth": depth,
                "parent_fanout_idx": _parent_fanout_idx if depth > 0 else None,
                "elapsed_ms": round(elapsed_ms, 2),
                "error": _child_result.error if isinstance(_child_result, LLMResult) else True,
                "error_category": _child_result.error_category
                if isinstance(_child_result, LLMResult)
                else None,
                "prompt": prompt,
                "prompt_preview": prompt[:500],
                "result_text": str(_child_result) if _child_result is not None else None,
                "result_preview": str(_child_result)[:500] if _child_result is not None else None,
                "input_tokens": getattr(_child_result, "input_tokens", 0)
                if _child_result is not None
                else 0,
                "output_tokens": getattr(_child_result, "output_tokens", 0)
                if _child_result is not None
                else 0,
                "thought_tokens": getattr(_child_result, "thoughts_tokens", 0)
                if _child_result is not None
                else 0,
                "finish_reason": getattr(_child_result, "finish_reason", None)
                if _child_result is not None
                else None,
                "error_message": _error_message,
                "final_answer": _truncate_text(_child_result),
                "visible_output_text": getattr(_child_result, "visible_text", None),
                "visible_output_preview": _truncate_text(
                    getattr(_child_result, "visible_text", None),
                ),
                "thought_text": getattr(_child_result, "thought_text", None),
                "thought_preview": _truncate_text(
                    getattr(_child_result, "thought_text", None),
                ),
                "raw_output": _persist_payload(
                    getattr(_child_result, "raw_output", None),
                ),
                "raw_output_preview": _preview_payload(
                    getattr(_child_result, "raw_output", None),
                ),
                "parsed_output": (
                    parsed_output
                    if isinstance(parsed_output, dict)
                    and not (isinstance(_child_result, LLMResult) and _child_result.error)
                    else None
                ),
                "reasoning_summary": completion.get("reasoning_summary"),
                "reasoning_retry": {
                    "count": completion.get("reasoning_retry_count", 0),
                    "delay_ms": completion.get("reasoning_retry_delay_ms", 0),
                    "used": bool(completion.get("reasoning_retry_count", 0)),
                },
                "nested_dispatch": {
                    "count": completion.get("nested_child_dispatch_count", 0),
                    "batch_dispatches": completion.get("nested_child_batch_dispatches", 0),
                    "error_counts": (
                        dict(completion.get("nested_child_error_counts", {}))
                        if isinstance(completion.get("nested_child_error_counts"), dict)
                        else {}
                    ),
                    "structured_output_failures": completion.get(
                        "nested_structured_output_failures", 0
                    ),
                },
                "structured_output": {
                    "expected": output_schema is not None,
                    "schema_name": getattr(output_schema, "__name__", None),
                    "attempts": structured_attempts,
                    "retry_count": structured_retries,
                    "outcome": structured_outcome,
                    "validated_result": (
                        validated_structured_result
                        if (
                            isinstance(validated_structured_result, dict)
                            and not (isinstance(_child_result, LLMResult) and _child_result.error)
                        )
                        else None
                    ),
                    "events": structured_events,
                },
            }
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

        # Update local accumulators (per-iteration and cumulative)
        nonlocal _acc_child_dispatches, _acc_child_batch_dispatches
        nonlocal _cum_child_dispatches, _cum_child_batch_dispatches
        _acc_child_dispatches += k
        _cum_child_dispatches += k
        if k > 1:
            _acc_child_batch_dispatches += 1
            _cum_child_batch_dispatches += 1

        if k > 1:
            print(
                f"[RLM] child dispatch batch ({k} prompts, depth={depth + 1})",
                flush=True,
            )

        # Run all children concurrently (semaphore limits actual concurrency)
        tasks = [_run_child(p, model, output_schema, idx) for idx, p in enumerate(prompts)]
        results = await asyncio.gather(*tasks)
        all_results = list(results)

        # Aggregate latency
        dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000
        _acc_child_latencies.append(round(dispatch_elapsed_ms, 2))

        # Accumulate errors (per-iteration and cumulative)
        for r in all_results:
            if r.error:
                cat = r.error_category or "UNKNOWN"
                _acc_child_error_counts[cat] = _acc_child_error_counts.get(cat, 0) + 1
                _cum_child_error_counts[cat] = _cum_child_error_counts.get(cat, 0) + 1

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
                current_trace.data_flow_edges = _data_flow.get_edges()

        return all_results

    def flush_fn() -> dict:
        """Return accumulated dispatch state and reset accumulators."""
        nonlocal _acc_child_dispatches, _acc_child_batch_dispatches, _acc_structured_output_failures
        delta: dict[str, Any] = {
            OBS_CHILD_DISPATCH_COUNT: _acc_child_dispatches,
            OBS_CHILD_DISPATCH_LATENCY_MS: list(_acc_child_latencies),
        }
        if _acc_child_batch_dispatches > 0:
            delta[OBS_CHILD_TOTAL_BATCH_DISPATCHES] = _acc_child_batch_dispatches
        if _acc_child_error_counts:
            delta[OBS_CHILD_ERROR_COUNTS] = dict(_acc_child_error_counts)
        if _acc_structured_output_failures > 0:
            delta[OBS_STRUCTURED_OUTPUT_FAILURES] = _acc_structured_output_failures
        # Cumulative counters — monotonically non-decreasing, never reset
        delta[OBS_CHILD_DISPATCH_COUNT_TOTAL] = _cum_child_dispatches
        if _cum_child_batch_dispatches > 0:
            delta[OBS_CHILD_BATCH_DISPATCHES_TOTAL] = _cum_child_batch_dispatches
        if _cum_child_error_counts:
            delta[OBS_CHILD_ERROR_COUNTS_TOTAL] = dict(_cum_child_error_counts)
        if _cum_structured_output_failures > 0:
            delta[OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL] = _cum_structured_output_failures
        # BUG-13 monkey-patch invocation count
        bug13_count = _bug13_stats.get("suppress_count", 0)
        if bug13_count > 0:
            delta[OBS_BUG13_SUPPRESS_COUNT] = bug13_count
        # Restore parent's skill instruction after child dispatch
        if _parent_skill_instruction is not None:
            delta[DYN_SKILL_INSTRUCTION] = _parent_skill_instruction
        # Merge per-child summaries into delta
        delta.update(_acc_child_summaries)
        # Reset per-iteration accumulators (cumulative accumulators are NOT reset)
        _acc_child_dispatches = 0
        _acc_child_batch_dispatches = 0
        _acc_child_latencies.clear()
        _acc_child_error_counts.clear()
        _acc_child_summaries.clear()
        _acc_structured_output_failures = 0
        return delta

    return llm_query_async, llm_query_batched_async, flush_fn
