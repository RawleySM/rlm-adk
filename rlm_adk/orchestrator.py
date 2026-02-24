"""RLM Orchestrator Agent - Custom BaseAgent implementing the RLM iteration loop.

This is the ADK equivalent of rlm.core.rlm.RLM.completion().
It orchestrates: prompt -> reason -> extract code -> execute -> check final -> repeat.

CRIT-1: All state writes inside _run_async_impl use yield Event(actions=EventActions(state_delta={})).
"""

import asyncio
import logging
import os
import time
import uuid
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from rlm_adk.artifacts import save_final_answer, save_repl_code, save_repl_output
from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import (
    APP_MAX_DEPTH,
    APP_MAX_ITERATIONS,
    CURRENT_DEPTH,
    DYN_REPO_URL,
    DYN_ROOT_PROMPT,
    FINAL_ANSWER,
    ITERATION_COUNT,
    LAST_REASONING_RESPONSE,
    LAST_REPL_RESULT,
    MESSAGE_HISTORY,
    REPO_URL,
    REQUEST_ID,
    ROOT_PROMPT,
    SHOULD_STOP,
    WORKER_EVENTS_DRAINED,
    WORKER_RESULTS_COMMITTED,
)
from rlm_adk.types import CodeBlock, REPLResult, RLMIteration
from rlm_adk.utils.parsing import find_code_blocks, find_final_answer, format_iteration
from rlm_adk.utils.prompts import build_user_prompt

logger = logging.getLogger(__name__)

# Transient HTTP status codes that warrant a retry.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def is_transient_error(exc: Exception) -> bool:
    """Classify an exception as transient (retryable) using type-based checks.

    Only ``google.genai.errors.ServerError`` and ``ClientError`` with known
    transient HTTP status codes are considered retryable.  Generic exceptions
    are never retried, even if their message happens to contain a status code
    string like "503".
    """
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    return False


class RLMOrchestratorAgent(BaseAgent):
    """Custom BaseAgent that implements the RLM recursive iteration loop.

    Configuration (set via session state at invocation start):
    - app:max_depth: Maximum recursion depth (default 1)
    - app:max_iterations: Maximum iteration count (default 30)

    Sub-agents:
    - reasoning_agent: LlmAgent for main reasoning (depth=0)

    The orchestrator does NOT use ADK's built-in agent transfer.
    Instead, it manually dispatches to sub-agents and processes their output.
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

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Main iteration loop - the core of the RLM port.

        CRIT-1: All state writes MUST yield Event with EventActions(state_delta).
        """
        _default_max_iter = int(os.getenv("RLM_MAX_ITERATIONS", "30"))
        max_iterations = ctx.session.state.get(APP_MAX_ITERATIONS, _default_max_iter)
        max_depth = ctx.session.state.get(APP_MAX_DEPTH, 1)

        # Initialize REPL environment (BUG-8: reuse persistent REPL if provided)
        if self.repl is not None:
            repl = self.repl
        else:
            repl = LocalREPL(depth=1)

        # Wire up WorkerPool dispatch closures (BUG-3)
        event_queue: asyncio.Queue | None = None
        if self.worker_pool is not None:
            self.worker_pool.ensure_initialized()
            event_queue = asyncio.Queue()
            llm_query_async, llm_query_batched_async = create_dispatch_closures(
                self.worker_pool, ctx, event_queue
            )
            repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)

            def sync_llm_query_unsupported(*args, **kwargs):
                raise RuntimeError(
                    "llm_query() cannot be called synchronously in ADK mode. "
                    "The AST rewriter should convert llm_query() to await llm_query_async(). "
                    "If you see this error, the AST rewriter failed to detect the call."
                )

            repl.set_llm_query_fns(sync_llm_query_unsupported, sync_llm_query_unsupported)

        try:
            # Message history starts empty — ADK handles the system prompt
            # via static_instruction= and context metadata via instruction=
            # template resolution.  Only iterative conversation messages
            # (user prompts, model responses, REPL output) go here.
            message_history: list[dict[str, str]] = []

            # Build initial state delta.
            # - Unprefixed keys are session-scoped.
            # - DYN_ keys are session-scoped for ADK instruction
            #   template resolution ({repo_url?}, {root_prompt?}).
            initial_state: dict[str, Any] = {
                MESSAGE_HISTORY: message_history,
                CURRENT_DEPTH: 1,
                ITERATION_COUNT: 0,
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

            for i in range(max_iterations):
                print(
                    f"[RLM] --- iter={i} START max={max_iterations} ---",
                    flush=True,
                )

                # Build current prompt = message history + user prompt suffix
                history_count = repl.get_history_count()
                current_prompt = message_history + [
                    build_user_prompt(self.root_prompt, i, history_count)
                ]

                # --- Inject prompt into state for reasoning_before_model callback ---
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={
                        MESSAGE_HISTORY: current_prompt,
                    }),
                )

                # --- Dispatch to ReasoningAgent (with retry for transient errors) ---
                max_retries = int(os.getenv("RLM_LLM_MAX_RETRIES", "3"))
                base_delay = float(os.getenv("RLM_LLM_RETRY_DELAY", "5.0"))
                for attempt in range(max_retries + 1):
                    try:
                        async for event in self.reasoning_agent.run_async(ctx):
                            yield event
                        break
                    except Exception as exc:
                        if not is_transient_error(exc) or attempt >= max_retries:
                            raise
                        delay = base_delay * (2 ** attempt)
                        print(
                            f"[RLM] iter={i} transient error (attempt {attempt + 1}/{max_retries + 1}): "
                            f"{type(exc).__name__}. Retrying in {delay:.1f}s...",
                            flush=True,
                        )
                        logger.warning(
                            "Transient LLM error at iter=%d attempt=%d: %s. Retrying in %.1fs",
                            i, attempt + 1, exc, delay,
                        )
                        await asyncio.sleep(delay)

                # Drain worker event queue (BUG-3)
                # After drain, yield a sync-point event so the Runner commits
                # worker state_deltas before we read any worker results.
                if event_queue is not None:
                    drained = 0
                    while not event_queue.empty():
                        yield event_queue.get_nowait()
                        drained += 1
                    if drained > 0:
                        prev_drained = ctx.session.state.get(WORKER_EVENTS_DRAINED, 0)
                        yield Event(
                            invocation_id=ctx.invocation_id,
                            author=self.name,
                            actions=EventActions(state_delta={
                                WORKER_EVENTS_DRAINED: prev_drained + drained,
                                WORKER_RESULTS_COMMITTED: True,
                            }),
                        )
                        print(
                            f"[RLM] iter={i} worker_events_drained={drained}",
                            flush=True,
                        )

                # Get response from state (written by reasoning_after_model callback)
                response = ctx.session.state.get(LAST_REASONING_RESPONSE, "")

                if not response:
                    print(
                        f"[RLM_WARN] iter={i} empty response from reasoning agent",
                        flush=True,
                    )
                    logger.warning("Empty response from reasoning agent at iteration %d", i)

                # --- Extract and execute code blocks ---
                code_block_strs = find_code_blocks(response)
                code_blocks: list[CodeBlock] = []

                for code_str in code_block_strs:
                    # Check if code contains llm_query calls that need AST rewriting
                    try:
                        from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async
                    except ImportError:
                        has_llm_calls = None
                        rewrite_for_async = None

                    needs_async = has_llm_calls is not None and has_llm_calls(code_str)

                    if needs_async and rewrite_for_async is not None:
                        # AST rewrite and execute async
                        try:
                            rewritten = rewrite_for_async(code_str)
                            ns = {**repl.globals, **repl.locals}
                            exec(compile(rewritten, "<repl>", "exec"), ns)
                            repl_exec_fn = ns["_repl_exec"]
                            result = await repl.execute_code_async(code_str, repl_exec_fn)
                        except SyntaxError as e:
                            result = REPLResult(
                                stdout="",
                                stderr=f"SyntaxError in AST rewrite: {e}",
                                locals=repl.locals.copy(),
                            )
                    else:
                        # No LM calls (or no AST rewriter available) - execute synchronously
                        result = repl.execute_code(code_str)

                    code_blocks.append(CodeBlock(code=code_str, result=result))

                    # Auto-save REPL code as artifact
                    turn_idx = len(code_blocks) - 1
                    await save_repl_code(ctx, iteration=i, turn=turn_idx, code=code_str)

                print(
                    f"[RLM] iter={i} code_blocks={len(code_blocks)} "
                    f"has_output={any(cb.result.stdout for cb in code_blocks)}",
                    flush=True,
                )

                # Auto-save REPL outputs as artifacts
                for cb_idx, cb in enumerate(code_blocks):
                    if cb.result.stdout or cb.result.stderr:
                        await save_repl_output(
                            ctx,
                            iteration=i,
                            stdout=cb.result.stdout,
                            stderr=cb.result.stderr,
                        )

                # --- Mid-iteration event queue drain (Fix 7) ---
                # Drain worker events from llm_query calls in code blocks
                # BEFORE checking for the final answer.
                if event_queue is not None:
                    mid_drained = 0
                    while not event_queue.empty():
                        yield event_queue.get_nowait()
                        mid_drained += 1
                    if mid_drained > 0:
                        print(
                            f"[RLM] iter={i} mid-iteration worker_events_drained={mid_drained}",
                            flush=True,
                        )

                # --- Check for final answer ---
                # Skip FINAL_VAR resolution when code blocks had errors: the
                # variable likely doesn't exist yet and the error string would
                # be returned as the "final answer", terminating the loop
                # before the reasoning agent can see the error and retry.
                any_code_error = any(cb.result.stderr for cb in code_blocks)

                if any_code_error and code_blocks:
                    logger.warning(
                        "Skipping FINAL_VAR resolution at iter %d: code block had errors",
                        i,
                    )
                    final_answer = None
                else:
                    final_answer = find_final_answer(response, environment=repl)

                if final_answer is not None:
                    print(
                        f"[RLM] FINAL_ANSWER detected at iter={i + 1} "
                        f"length={len(final_answer)}",
                        flush=True,
                    )

                    # Drain event queue before yielding final answer (Fix 3)
                    if event_queue is not None:
                        while not event_queue.empty():
                            yield event_queue.get_nowait()

                    # Auto-save final answer as artifact
                    await save_final_answer(ctx, answer=final_answer)

                    yield Event(
                        invocation_id=ctx.invocation_id,
                        author=self.name,
                        actions=EventActions(state_delta={
                            FINAL_ANSWER: final_answer,
                            SHOULD_STOP: True,
                            ITERATION_COUNT: i + 1,
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

                    # Store message history in persistent environment
                    if self.persistent:
                        repl.add_history(message_history)

                    return

                # --- Format iteration and update history ---
                iteration = RLMIteration(
                    prompt=current_prompt,
                    response=response,
                    code_blocks=code_blocks,
                )
                new_messages = format_iteration(iteration)
                message_history.extend(new_messages)

                # Yield iteration state delta
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={
                        ITERATION_COUNT: i + 1,
                        LAST_REPL_RESULT: {
                            "code_blocks": len(code_blocks),
                            "has_output": any(cb.result.stdout for cb in code_blocks),
                        },
                    }),
                )

                print(
                    f"[RLM] --- iter={i} END ---",
                    flush=True,
                )

            # --- Drain event queue before max-iterations exhausted (Fix 3) ---
            if event_queue is not None:
                while not event_queue.empty():
                    yield event_queue.get_nowait()

            # --- Max iterations exhausted ---
            logger.warning(
                "max_iterations=%d exhausted without FINAL answer. "
                "Consider increasing max_iterations.",
                max_iterations,
            )
            print(
                f"[RLM_WARN] max_iterations={max_iterations} exhausted "
                f"without FINAL answer. Increase max_iterations.",
                flush=True,
            )

            exhausted_msg = (
                f"[RLM ERROR] Max iterations ({max_iterations}) exhausted "
                f"without producing a FINAL answer. "
                f"Increase max_iterations and retry."
            )

            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={
                    FINAL_ANSWER: exhausted_msg,
                    SHOULD_STOP: True,
                    ITERATION_COUNT: max_iterations,
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

            # Store message history in persistent environment
            if self.persistent:
                repl.add_history(message_history)

        finally:
            if not self.persistent:
                repl.cleanup()
