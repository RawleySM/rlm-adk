"""RLM Orchestrator Agent - Custom BaseAgent implementing the RLM iteration loop.

This is the ADK equivalent of rlm.core.rlm.RLM.completion().
It orchestrates: prompt -> reason -> extract code -> execute -> check final -> repeat.

CRIT-1: All state writes inside _run_async_impl use yield Event(actions=EventActions(state_delta={})).
"""

import asyncio
import logging
from typing import Any, AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import (
    APP_MAX_DEPTH,
    APP_MAX_ITERATIONS,
    TEMP_CURRENT_DEPTH,
    TEMP_FINAL_ANSWER,
    TEMP_ITERATION_COUNT,
    TEMP_LAST_REASONING_RESPONSE,
    TEMP_LAST_REPL_RESULT,
    TEMP_MESSAGE_HISTORY,
    TEMP_SHOULD_STOP,
    TEMP_USED_DEFAULT_ANSWER,
)
from rlm_adk.types import CodeBlock, REPLResult, RLMIteration
from rlm_adk.utils.parsing import find_code_blocks, find_final_answer, format_iteration
from rlm_adk.utils.prompts import (
    RLM_SYSTEM_PROMPT,
    QueryMetadata,
    build_rlm_system_prompt,
    build_user_prompt,
)

logger = logging.getLogger(__name__)


class RLMOrchestratorAgent(BaseAgent):
    """Custom BaseAgent that implements the RLM recursive iteration loop.

    Configuration (set via session state at invocation start):
    - app:max_depth: Maximum recursion depth (default 1)
    - app:max_iterations: Maximum iteration count (default 30)

    Sub-agents:
    - reasoning_agent: LlmAgent for main reasoning (depth=0)
    - default_answer_agent: LlmAgent for fallback answer generation

    The orchestrator does NOT use ADK's built-in agent transfer.
    Instead, it manually dispatches to sub-agents and processes their output.
    """

    model_config = {"arbitrary_types_allowed": True}

    # Sub-agents declared as Pydantic fields so ADK recognizes them
    reasoning_agent: LlmAgent
    default_answer_agent: LlmAgent

    # Configuration fields
    system_prompt: str = RLM_SYSTEM_PROMPT
    context_payload: Any = None
    root_prompt: str | None = None
    persistent: bool = False
    worker_pool: Any = None
    repl: Any = None

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Main iteration loop - the core of the RLM port.

        CRIT-1: All state writes MUST yield Event with EventActions(state_delta).
        """
        max_iterations = ctx.session.state.get(APP_MAX_ITERATIONS, 30)
        max_depth = ctx.session.state.get(APP_MAX_DEPTH, 1)

        # Initialize REPL environment (BUG-8: reuse persistent REPL if provided)
        if self.repl is not None:
            repl = self.repl
        else:
            repl = LocalREPL(
                context_payload=self.context_payload,
                depth=1,
            )

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
            # Build initial message history
            metadata = QueryMetadata(self.context_payload or "")
            message_history = build_rlm_system_prompt(
                system_prompt=self.system_prompt,
                query_metadata=metadata,
            )

            # Yield initial state
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={
                    TEMP_MESSAGE_HISTORY: message_history,
                    TEMP_CURRENT_DEPTH: 1,
                    TEMP_ITERATION_COUNT: 0,
                }),
            )

            for i in range(max_iterations):
                # Build current prompt = message history + user prompt suffix
                context_count = repl.get_context_count()
                history_count = repl.get_history_count()
                current_prompt = message_history + [
                    build_user_prompt(self.root_prompt, i, context_count, history_count)
                ]

                # --- Inject prompt into state for reasoning_before_model callback ---
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={
                        TEMP_MESSAGE_HISTORY: current_prompt,
                    }),
                )

                # --- Dispatch to ReasoningAgent ---
                async for event in self.reasoning_agent.run_async(ctx):
                    yield event

                # Drain worker event queue (BUG-3)
                if event_queue is not None:
                    while not event_queue.empty():
                        yield event_queue.get_nowait()

                # Get response from state (written by reasoning_after_model callback)
                response = ctx.session.state.get(TEMP_LAST_REASONING_RESPONSE, "")

                if not response:
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

                # --- Check for final answer ---
                final_answer = find_final_answer(response, environment=repl)

                if final_answer is not None:
                    yield Event(
                        invocation_id=ctx.invocation_id,
                        author=self.name,
                        actions=EventActions(state_delta={
                            TEMP_FINAL_ANSWER: final_answer,
                            TEMP_SHOULD_STOP: True,
                            TEMP_ITERATION_COUNT: i + 1,
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
                        TEMP_ITERATION_COUNT: i + 1,
                        TEMP_LAST_REPL_RESULT: {
                            "code_blocks": len(code_blocks),
                            "has_output": any(cb.result.stdout for cb in code_blocks),
                        },
                    }),
                )

            # --- Max iterations exhausted -> default answer ---
            # Update state with full history for the default answer callback
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={
                    TEMP_MESSAGE_HISTORY: message_history,
                }),
            )

            async for event in self.default_answer_agent.run_async(ctx):
                yield event

            # Drain worker event queue (BUG-3)
            if event_queue is not None:
                while not event_queue.empty():
                    yield event_queue.get_nowait()

            default_answer = ctx.session.state.get("default_answer", "")

            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={
                    TEMP_FINAL_ANSWER: default_answer,
                    TEMP_USED_DEFAULT_ANSWER: True,
                    TEMP_ITERATION_COUNT: max_iterations,
                }),
            )
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=default_answer)],
                ),
            )

            # Store message history in persistent environment
            if self.persistent:
                repl.add_history(message_history)

        finally:
            if not self.persistent:
                repl.cleanup()
