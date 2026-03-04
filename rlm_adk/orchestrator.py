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
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from google.genai.errors import ClientError, ServerError

from google.adk.tools.set_model_response_tool import SetModelResponseTool

from rlm_adk.artifacts import save_final_answer
from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks
from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.trace import REPLTrace
from rlm_adk.state import (
    APP_MAX_ITERATIONS,
    CURRENT_DEPTH,
    DYN_REPO_URL,
    DYN_ROOT_PROMPT,
    FINAL_ANSWER,
    ITERATION_COUNT,
    REPO_URL,
    REQUEST_ID,
    ROOT_PROMPT,
    SHOULD_STOP,
    depth_key,
)
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.types import LLMResult, ReasoningOutput
from rlm_adk.utils.parsing import find_final_answer

logger = logging.getLogger(__name__)

# Transient HTTP status codes that warrant a retry.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


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
    output_schema: Any = None  # type[BaseModel] | None — caller's schema for children

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Collapsed orchestrator -- delegates to reasoning_agent with REPLTool.

        CRIT-1: All state writes MUST yield Event with EventActions(state_delta).
        """
        _default_max_iter = int(os.getenv("RLM_MAX_ITERATIONS", "30"))
        max_iterations = ctx.session.state.get(APP_MAX_ITERATIONS, _default_max_iter)
        trace_level = int(os.getenv("RLM_REPL_TRACE", "0"))

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
                self.worker_pool, ctx,
                call_log_sink=repl._pending_llm_calls,
                trace_sink=trace_holder if trace_level > 0 else None,
                depth=self.depth,
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

        # Create REPLTool with flush_fn for dispatch accumulator flushing
        repl_tool = REPLTool(
            repl,
            max_calls=max_iterations,
            flush_fn=flush_fn,
            trace_holder=trace_holder if trace_level > 0 else None,
            depth=self.depth,
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
        object.__setattr__(self.reasoning_agent, 'tools', [repl_tool, set_model_response_tool])
        # Tag depth for telemetry (read by reasoning callbacks)
        object.__setattr__(self.reasoning_agent, '_rlm_depth', self.depth)
        # Ensure ADK manages tool call/response history
        object.__setattr__(self.reasoning_agent, 'include_contents', 'default')

        # Wire structured output retry callbacks for set_model_response
        after_tool_cb, on_tool_error_cb = make_worker_tool_callbacks(max_retries=2)
        object.__setattr__(self.reasoning_agent, 'after_tool_callback', after_tool_cb)
        object.__setattr__(self.reasoning_agent, 'on_tool_error_callback', on_tool_error_cb)

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
                                f"retry exhausted after {attempt + 1} attempts "
                                f"(code={http_code})"
                            )
                        else:
                            err_detail = (
                                f"non-retryable error (code={http_code})"
                            )
                        error_msg = (
                            f"[RLM ERROR] {type(exc).__name__}: {err_detail}"
                        )
                        yield Event(
                            invocation_id=ctx.invocation_id,
                            author=self.name,
                            actions=EventActions(state_delta={
                                depth_key(FINAL_ANSWER, self.depth): error_msg,
                                depth_key(SHOULD_STOP, self.depth): True,
                            }),
                        )
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(
                        f"[RLM] transient error (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{type(exc).__name__}. Retrying in {delay:.1f}s...",
                        flush=True,
                    )
                    logger.warning(
                        "Transient LLM error at attempt=%d: %s. Retrying in %.1fs",
                        attempt + 1, exc, delay,
                    )
                    await asyncio.sleep(delay)

            # --- Extract final_answer from output_key ---
            # ADK's output_key stores the raw text of the final model response.
            # When output_schema is set, it's a JSON dict (ReasoningOutput).
            # When output_schema is NOT set, it's plain text.
            _output_key = self.reasoning_agent.output_key or "reasoning_output"
            raw = ctx.session.state.get(_output_key, "")
            final_answer = ""
            if isinstance(raw, dict):
                # Already parsed (output_schema was set)
                final_answer = raw.get("final_answer", "")
            elif isinstance(raw, str):
                # Try JSON first (ReasoningOutput format)
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        final_answer = parsed.get("final_answer", raw)
                    else:
                        final_answer = raw
                except (json.JSONDecodeError, ValueError):
                    # Plain text -- try FINAL() pattern extraction first
                    parsed_final = find_final_answer(raw)
                    if parsed_final is not None:
                        final_answer = parsed_final
                    else:
                        # No FINAL() marker -- use raw text as-is
                        final_answer = raw

            if final_answer:
                print(
                    f"[RLM] FINAL_ANSWER detected length={len(final_answer)}",
                    flush=True,
                )

                # Auto-save final answer as artifact
                await save_final_answer(ctx, answer=final_answer)

                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={
                        depth_key(FINAL_ANSWER, self.depth): final_answer,
                        depth_key(SHOULD_STOP, self.depth): True,
                    }),
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
                # No final answer extracted -- reasoning agent may not have
                # produced a valid ReasoningOutput
                logger.warning(
                    "Reasoning agent completed without a final_answer in output_key"
                )
                exhausted_msg = (
                    "[RLM ERROR] Reasoning agent completed without producing "
                    "a structured final answer. Check output_schema wiring."
                )
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={
                        depth_key(FINAL_ANSWER, self.depth): exhausted_msg,
                        depth_key(SHOULD_STOP, self.depth): True,
                    }),
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
            object.__setattr__(self.reasoning_agent, 'tools', [])
            object.__setattr__(self.reasoning_agent, 'after_tool_callback', None)
            object.__setattr__(self.reasoning_agent, 'on_tool_error_callback', None)
            if not self.persistent:
                repl.cleanup()
