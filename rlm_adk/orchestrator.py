"""RLM Orchestrator Agent - Custom BaseAgent delegating to reasoning_agent with REPLTool.

Phase 5B: The orchestrator no longer manually iterates, parses code blocks,
or executes them.  Instead it:
1. Creates a REPLTool wrapping LocalREPL
2. Wires the reasoning_agent with tools=[REPLTool] (output_key="reasoning_output")
3. Yields an initial user Content event with the root_prompt
4. Delegates to self.reasoning_agent.run_async(ctx) -- ADK's native tool-calling
   loop handles all iteration, code execution, and structured output
5. Extracts the final_answer from the output_key ("reasoning_output")

CRIT-1: All state writes inside _run_async_impl use yield Event(actions=EventActions(state_delta={})).
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools.set_model_response_tool import SetModelResponseTool
from google.genai import types
from google.genai.errors import ClientError, ServerError

from rlm_adk.artifacts import save_final_answer
from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks
from rlm_adk.dispatch import create_dispatch_closures
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.trace import REPLTrace
from rlm_adk.state import (
    APP_MAX_ITERATIONS,
    CURRENT_DEPTH,
    DYN_REPO_URL,
    DYN_ROOT_PROMPT,
    DYN_SKILL_INSTRUCTION,
    DYN_USER_CTX_MANIFEST,
    FINAL_ANSWER,
    ITERATION_COUNT,
    OBS_REASONING_RETRY_COUNT,
    OBS_REASONING_RETRY_DELAY_MS,
    REASONING_FINISH_REASON,
    REASONING_INPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
    REASONING_PARSED_OUTPUT,
    REASONING_RAW_OUTPUT,
    REASONING_SUMMARY,
    REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS,
    REASONING_VISIBLE_OUTPUT_TEXT,
    REPO_URL,
    REQUEST_ID,
    ROOT_PROMPT,
    SHOULD_STOP,
    USER_PROVIDED_CTX,
    USER_PROVIDED_CTX_EXCEEDED,
    USR_PROVIDED_FILES_SERIALIZED,
    USR_PROVIDED_FILES_UNSERIALIZED,
    depth_key,
)
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.types import LLMResult, ReasoningOutput, parse_reasoning_output

logger = logging.getLogger(__name__)

# Transient HTTP status codes that warrant a retry.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_COMPLIANCE_FINISH_REASONS = frozenset({"SAFETY", "RECITATION"})


def is_transient_error(exc: Exception) -> bool:
    """Classify an exception as transient (retryable) using type-based checks.

    Recognizes google.genai errors, asyncio timeouts, and network-level
    exceptions as transient.  Generic exceptions are never retried.
    """
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import httpx as _httpx

        if isinstance(exc, (_httpx.ConnectError, _httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    return False


def _serialize_completion_payload(value: Any) -> str:
    """Return a stable string form for structured child results."""
    if isinstance(value, dict):
        try:
            return json.dumps(value, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
    if value is None:
        return ""
    return str(value)


def _infer_completion_error(
    *,
    final_answer: str,
    finish_reason: str | None,
    output_schema: Any,
) -> tuple[str, str]:
    """Classify a missing/errored reasoning completion."""
    if finish_reason in _COMPLIANCE_FINISH_REASONS:
        return (
            finish_reason,
            f"[RLM ERROR] Reasoning agent finished with {finish_reason} before producing a final answer.",
        )
    if finish_reason == "MAX_TOKENS":
        return (
            finish_reason,
            "[RLM ERROR] Reasoning agent hit MAX_TOKENS before producing a final answer.",
        )
    if output_schema is not None:
        schema_name = getattr(output_schema, "__name__", "structured output schema")
        return (
            "SCHEMA_VALIDATION_EXHAUSTED",
            f"[RLM ERROR] Structured output validation exhausted before producing a valid {schema_name} result.",
        )
    if final_answer.startswith("[RLM ERROR]"):
        return ("UNKNOWN", final_answer)
    return (
        "NO_RESULT",
        "[RLM ERROR] Reasoning agent completed without producing a final answer.",
    )


def _collect_reasoning_completion(
    *,
    reasoning_agent: LlmAgent,
    session_state: dict[str, Any],
    depth: int,
    output_schema: Any,
) -> dict[str, Any]:
    """Normalize the final reasoning payload for dispatch + finalization."""
    output_key = reasoning_agent.output_key or "reasoning_output"
    raw = session_state.get(output_key)
    structured = getattr(reasoning_agent, "_structured_result", None)
    visible_text = session_state.get(depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth)) or ""
    thought_text = session_state.get(depth_key(REASONING_THOUGHT_TEXT, depth)) or ""
    finish_reason = session_state.get(depth_key(REASONING_FINISH_REASON, depth))

    payload = parse_reasoning_output(raw)
    source = "output_key"
    if not payload.final_answer and payload.parsed_output is None and structured is not None:
        payload = parse_reasoning_output(structured)
        source = "structured_result"
    elif not payload.final_answer and visible_text:
        payload = parse_reasoning_output(visible_text)
        source = "visible_output_text"

    parsed_output = payload.parsed_output if isinstance(payload.parsed_output, dict) else None
    result_text = payload.final_answer or _serialize_completion_payload(
        parsed_output or payload.raw_output or visible_text
    )
    error = False
    error_category = None

    if not result_text or result_text.startswith("[RLM ERROR]"):
        error = True
        error_category, result_text = _infer_completion_error(
            final_answer=result_text,
            finish_reason=finish_reason,
            output_schema=output_schema,
        )

    completion = {
        "source": source,
        "text": result_text,
        "error": error,
        "error_category": error_category,
        "raw_output": payload.raw_output,
        "parsed_output": parsed_output,
        "reasoning_summary": payload.reasoning_summary,
        "visible_output_text": visible_text or result_text,
        "thought_text": thought_text,
        "finish_reason": finish_reason,
        "input_tokens": session_state.get(depth_key(REASONING_INPUT_TOKENS, depth), 0) or 0,
        "output_tokens": session_state.get(depth_key(REASONING_OUTPUT_TOKENS, depth), 0) or 0,
        "thoughts_tokens": session_state.get(depth_key(REASONING_THOUGHT_TOKENS, depth), 0) or 0,
    }
    return completion


class RLMOrchestratorAgent(BaseAgent):
    """Custom BaseAgent that delegates to reasoning_agent with REPLTool.

    The orchestrator wires a REPLTool and ReasoningOutput schema onto the
    reasoning_agent at runtime, then delegates via run_async.  ADK's native
    tool-calling loop handles iteration, code execution, and structured output.

    Configuration (set via session state at invocation start):
    - app:max_iterations: Maximum tool calls (default 30)

    Sub-agents:
    - reasoning_agent: LlmAgent for main reasoning (depth=0)
    """

    model_config = {"arbitrary_types_allowed": True}

    # Sub-agents declared as Pydantic fields so ADK recognizes them
    reasoning_agent: LlmAgent

    # Configuration fields
    root_prompt: str | None = None
    repo_url: str | None = None
    persistent: bool = False
    worker_pool: Any = None
    repl: Any = None
    depth: int = 0
    fanout_idx: int = 0
    output_schema: Any = None  # type[BaseModel] | None — caller's schema for children
    instruction_router: Any = None  # Callable[[int, int], str] | None

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        """Collapsed orchestrator -- delegates to reasoning_agent with REPLTool.

        CRIT-1: All state writes MUST yield Event with EventActions(state_delta).
        """
        _default_max_iter = int(os.getenv("RLM_MAX_ITERATIONS", "30"))
        max_iterations = ctx.session.state.get(APP_MAX_ITERATIONS, _default_max_iter)
        trace_level = int(os.getenv("RLM_REPL_TRACE", "0"))
        object.__setattr__(self.reasoning_agent, "_structured_result", None)
        object.__setattr__(self.reasoning_agent, "_rlm_completion", None)
        object.__setattr__(self, "_rlm_completion", None)

        # Initialize REPL environment (reuse persistent REPL if provided)
        if self.repl is not None:
            repl = self.repl
        else:
            repl = LocalREPL(depth=1)

        # Inject LLMResult into REPL namespace for skill functions
        repl.globals["LLMResult"] = LLMResult

        # Mutable trace holder: trace_holder[0] is the current REPLTrace per code block.
        # Dispatch closures read this to record per-call timing.
        trace_holder: list[REPLTrace | None] = [None]

        # Wire up WorkerPool dispatch closures -- collapsed mode omits the
        # queue parameter.  The flush_fn is passed to REPLTool which flushes
        # accumulators into tool_context.state after each code execution.
        flush_fn = None
        if self.worker_pool is not None:
            self.worker_pool.ensure_initialized()
            llm_query_async, llm_query_batched_async, flush_fn = create_dispatch_closures(
                self.worker_pool,
                ctx,
                call_log_sink=repl._pending_llm_calls,
                trace_sink=trace_holder if trace_level > 0 else None,
                depth=self.depth,
                instruction_router=self.instruction_router,
                fanout_idx=self.fanout_idx,
            )
            repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)

            def sync_llm_query_unsupported(*args, **kwargs):
                raise RuntimeError(
                    "llm_query() cannot be called synchronously in ADK mode. "
                    "The AST rewriter should convert llm_query() to await llm_query_async(). "
                    "If you see this error, the AST rewriter failed to detect the call."
                )

            repl.set_llm_query_fns(sync_llm_query_unsupported, sync_llm_query_unsupported)

        # Inject repomix skill helpers into REPL globals
        from rlm_adk.skills.repomix_helpers import pack_repo, probe_repo, shard_repo

        repl.globals["probe_repo"] = probe_repo
        repl.globals["pack_repo"] = pack_repo
        repl.globals["shard_repo"] = shard_repo

        # Register expandable REPL skill modules (side-effect imports)
        import rlm_adk.skills.polya_narrative_skill  # noqa: F401
        import rlm_adk.skills.repl_skills.ping  # noqa: F401

        # Create REPLTool with flush_fn for dispatch accumulator flushing
        repl_tool = REPLTool(
            repl,
            max_calls=max_iterations,
            flush_fn=flush_fn,
            trace_holder=trace_holder if trace_level > 0 else None,
            depth=self.depth,
            fanout_idx=self.fanout_idx,
        )

        # Wire reasoning_agent at runtime with tools.
        # Uses object.__setattr__ because LlmAgent is a Pydantic model.
        # Note: output_schema=ReasoningOutput is NOT set on LlmAgent because
        # ADK's __maybe_save_output_to_state validates raw text responses
        # against the schema (fails for plain text).  Instead we add
        # SetModelResponseTool as a tool so the model can choose either
        # execute_code or set_model_response.  BUG-13 patch (process-global
        # in worker_retry.py) handles retry suppression.
        schema = self.output_schema or ReasoningOutput
        set_model_response_tool = SetModelResponseTool(schema)
        object.__setattr__(self.reasoning_agent, "tools", [repl_tool, set_model_response_tool])
        # Tag depth for telemetry (read by reasoning callbacks)
        object.__setattr__(self.reasoning_agent, "_rlm_depth", self.depth)
        # Ensure ADK manages tool call/response history
        object.__setattr__(self.reasoning_agent, "include_contents", "default")

        # Wire structured output retry callbacks for set_model_response
        after_tool_cb, on_tool_error_cb = make_worker_tool_callbacks(max_retries=2)
        object.__setattr__(self.reasoning_agent, "after_tool_callback", after_tool_cb)
        object.__setattr__(self.reasoning_agent, "on_tool_error_callback", on_tool_error_cb)

        try:
            # Build initial state delta.
            initial_state: dict[str, Any] = {
                CURRENT_DEPTH: self.depth,
                depth_key(ITERATION_COUNT, self.depth): 0,
                REQUEST_ID: str(uuid.uuid4()),
            }
            if self.root_prompt:
                initial_state[ROOT_PROMPT] = self.root_prompt
                initial_state[DYN_ROOT_PROMPT] = self.root_prompt
            if self.repo_url:
                initial_state[REPO_URL] = self.repo_url
                initial_state[DYN_REPO_URL] = self.repo_url

            if self.instruction_router is not None:
                _skill_text = self.instruction_router(self.depth, self.fanout_idx)
                if _skill_text:
                    initial_state[DYN_SKILL_INSTRUCTION] = _skill_text

                    # Seed skill instruction via before_agent_callback so it's
                    # visible to before_model_callback on the first model call.
                    # callback_context.state writes are tracked by ADK and applied
                    # to session state immediately (unlike EventActions state_delta
                    # which requires Runner processing to apply).
                    async def _seed_skill_instruction(
                        *,
                        callback_context,
                        **_kw,
                    ):
                        callback_context.state[DYN_SKILL_INSTRUCTION] = _skill_text
                        return None

                    object.__setattr__(
                        self.reasoning_agent,
                        "before_agent_callback",
                        _seed_skill_instruction,
                    )

            # --- User-provided context directory (Path A: env var) ---
            _ctx_dir = os.getenv("RLM_USER_CTX_DIR")
            if _ctx_dir and os.path.isdir(_ctx_dir):
                from rlm_adk.utils.user_context import load_user_context

                _max_chars = int(os.getenv("RLM_USER_CTX_MAX_CHARS", "500000"))
                uctx = load_user_context(_ctx_dir, _max_chars)
                initial_state[USER_PROVIDED_CTX] = uctx.ctx
                initial_state[USER_PROVIDED_CTX_EXCEEDED] = uctx.exceeded
                initial_state[USR_PROVIDED_FILES_SERIALIZED] = uctx.serialized
                initial_state[USR_PROVIDED_FILES_UNSERIALIZED] = uctx.unserialized
                initial_state[DYN_USER_CTX_MANIFEST] = uctx.build_manifest()
                # Pre-load context dict into REPL globals
                repl.globals["user_ctx"] = uctx.ctx
                logger.info(
                    "User context loaded: %d files serialized, %d unserialized, %d total chars",
                    len(uctx.serialized),
                    len(uctx.unserialized),
                    uctx.total_chars,
                )
            # --- Path B: pre-seeded user_provided_ctx in session state ---
            elif ctx.session.state.get(USER_PROVIDED_CTX):
                _pre_seeded = ctx.session.state[USER_PROVIDED_CTX]
                initial_state[USER_PROVIDED_CTX] = _pre_seeded
                # Build manifest from the pre-seeded dict
                _filenames = sorted(k for k in _pre_seeded if not k.startswith("_"))
                _manifest_lines = [
                    "Pre-loaded context variable: user_ctx (dict)",
                    'Pre-loaded files (access via user_ctx["<filename>"]):',
                ]
                for _fn in _filenames:
                    _content = _pre_seeded[_fn]
                    if isinstance(_content, str):
                        _chars = len(_content)
                    else:
                        import json as _json

                        _chars = len(_json.dumps(_content, default=str))
                    _manifest_lines.append(f"  - {_fn} ({_chars:,} chars)")
                _manifest_lines.append(
                    f"Total: {len(_filenames)} files, {len(_filenames)} pre-loaded"
                )
                _manifest_str = "\n".join(_manifest_lines)
                initial_state[DYN_USER_CTX_MANIFEST] = _manifest_str
                initial_state[USER_PROVIDED_CTX_EXCEEDED] = ctx.session.state.get(
                    USER_PROVIDED_CTX_EXCEEDED,
                    False,
                )
                initial_state[USR_PROVIDED_FILES_SERIALIZED] = ctx.session.state.get(
                    USR_PROVIDED_FILES_SERIALIZED,
                    _filenames,
                )
                initial_state[USR_PROVIDED_FILES_UNSERIALIZED] = ctx.session.state.get(
                    USR_PROVIDED_FILES_UNSERIALIZED,
                    [],
                )
                # Pre-load context dict into REPL globals
                repl.globals["user_ctx"] = _pre_seeded
                logger.info(
                    "User context loaded from session state: %d files",
                    len(_filenames),
                )

            # Yield initial state
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=initial_state),
            )

            # Yield initial prompt as a user Content event so the reasoning agent
            # receives the user's query in its conversation history.
            initial_prompt = self.root_prompt or "Analyze and answer the query."
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=initial_prompt)],
                ),
            )

            # --- Delegate to reasoning_agent (with retry for transient errors) ---
            max_retries = int(os.getenv("RLM_LLM_MAX_RETRIES", "3"))
            base_delay = float(os.getenv("RLM_LLM_RETRY_DELAY", "5.0"))
            total_retry_delay_ms = 0
            for attempt in range(max_retries + 1):
                try:
                    async for event in self.reasoning_agent.run_async(ctx):
                        yield event
                    break
                except Exception as exc:
                    transient = is_transient_error(exc)
                    if not transient or attempt >= max_retries:
                        # Yield a structured error event before propagating.
                        http_code = getattr(exc, "code", None)
                        if transient:
                            err_detail = (
                                f"retry exhausted after {attempt + 1} attempts (code={http_code})"
                            )
                        else:
                            err_detail = f"non-retryable error (code={http_code})"
                        error_msg = f"[RLM ERROR] {type(exc).__name__}: {err_detail}"
                        yield Event(
                            invocation_id=ctx.invocation_id,
                            author=self.name,
                            actions=EventActions(
                                state_delta={
                                    depth_key(FINAL_ANSWER, self.depth): error_msg,
                                    depth_key(SHOULD_STOP, self.depth): True,
                                }
                            ),
                        )
                        raise
                    delay = base_delay * (2**attempt)
                    total_retry_delay_ms += round(delay * 1000)
                    print(
                        f"[RLM] transient error (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{type(exc).__name__}. Retrying in {delay:.1f}s...",
                        flush=True,
                    )
                    logger.warning(
                        "Transient LLM error at attempt=%d: %s. Retrying in %.1fs",
                        attempt + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

            # Persist reasoning retry count if any retries occurred
            if attempt > 0:
                retry_state_delta: dict[str, Any] = {
                    OBS_REASONING_RETRY_COUNT: attempt,
                    OBS_REASONING_RETRY_DELAY_MS: total_retry_delay_ms,
                }
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta=retry_state_delta),
                )

            # --- Extract final_answer from output_key ---
            # ADK's output_key stores the raw text of the final model response.
            # When output_schema is set, it's a JSON dict (ReasoningOutput).
            # When output_schema is NOT set, it's plain text.
            completion = _collect_reasoning_completion(
                reasoning_agent=self.reasoning_agent,
                session_state=ctx.session.state,
                depth=self.depth,
                output_schema=self.output_schema,
            )
            object.__setattr__(self.reasoning_agent, "_rlm_completion", completion)
            object.__setattr__(self, "_rlm_completion", completion)
            final_answer = completion["text"]

            reasoning_state_delta: dict[str, Any] = {
                depth_key(REASONING_RAW_OUTPUT, self.depth): completion["raw_output"],
            }
            if completion["parsed_output"] is not None:
                reasoning_state_delta[depth_key(REASONING_PARSED_OUTPUT, self.depth)] = completion[
                    "parsed_output"
                ]
            if completion["reasoning_summary"]:
                reasoning_state_delta[depth_key(REASONING_SUMMARY, self.depth)] = completion[
                    "reasoning_summary"
                ]
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=reasoning_state_delta),
            )

            if final_answer and not completion["error"]:
                print(
                    f"[RLM] FINAL_ANSWER detected length={len(final_answer)}",
                    flush=True,
                )

                # Auto-save final answer as artifact
                await save_final_answer(
                    ctx,
                    answer=final_answer,
                    depth=self.depth,
                    fanout_idx=self.fanout_idx,
                )

                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(
                        state_delta={
                            depth_key(FINAL_ANSWER, self.depth): final_answer,
                            depth_key(SHOULD_STOP, self.depth): True,
                        }
                    ),
                )
                # Yield final content event
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=final_answer)],
                    ),
                )
            else:
                exhausted_msg = final_answer or (
                    "[RLM ERROR] Reasoning agent completed without producing a final answer."
                )
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(
                        state_delta={
                            depth_key(FINAL_ANSWER, self.depth): exhausted_msg,
                            depth_key(SHOULD_STOP, self.depth): True,
                        }
                    ),
                )
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=exhausted_msg)],
                    ),
                )

        finally:
            # Clean up reasoning_agent wiring
            object.__setattr__(self.reasoning_agent, "tools", [])
            object.__setattr__(self.reasoning_agent, "after_tool_callback", None)
            object.__setattr__(self.reasoning_agent, "on_tool_error_callback", None)
            if not self.persistent:
                repl.cleanup()
