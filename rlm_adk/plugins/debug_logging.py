"""DebugLoggingPlugin - Development-only detailed tracing.

Wraps/extends logging with full interaction traces.
Development only - not for production.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.state import (
    OBS_TOTAL_CALLS,
    OBS_TOTAL_EXECUTION_TIME,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_TOTAL_DISPATCHES,
    TEMP_CONTEXT_WINDOW_SNAPSHOT,
    TEMP_FINAL_ANSWER,
    TEMP_ITERATION_COUNT,
    TEMP_REASONING_CONTENT_COUNT,
    TEMP_REASONING_HISTORY_MSG_COUNT,
    TEMP_REASONING_INPUT_TOKENS,
    TEMP_REASONING_OUTPUT_TOKENS,
    TEMP_REASONING_PROMPT_CHARS,
    TEMP_REASONING_SYSTEM_CHARS,
    TEMP_REQUEST_ID,
    TEMP_WORKER_CONTENT_COUNT,
    TEMP_WORKER_DISPATCH_COUNT,
    TEMP_WORKER_EVENTS_DRAINED,
    TEMP_WORKER_INPUT_TOKENS,
    TEMP_WORKER_OUTPUT_TOKENS,
    TEMP_WORKER_PROMPT_CHARS,
    TEMP_WORKER_RESULTS_COMMITTED,
)

logger = logging.getLogger(__name__)


class DebugLoggingPlugin(BasePlugin):
    """Full interaction trace logging for development.

    Records prompts, responses, tool calls, and state snapshots.
    Writes traces to YAML on after_run_callback.
    Not for production use.
    """

    def __init__(
        self,
        *,
        name: str = "debug_logging",
        output_path: str = "rlm_adk_debug.yaml",
        include_session_state: bool = True,
        include_system_instruction: bool = True,
    ):
        super().__init__(name=name)
        self._output_path = Path(output_path)
        self._include_session_state = include_session_state
        self._include_system_instruction = include_system_instruction
        self._traces: list[dict[str, Any]] = []

    async def before_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Record agent entry with state snapshot."""
        try:
            state = callback_context.state
            agent_name = getattr(agent, "name", "unknown")
            iteration = state.get(TEMP_ITERATION_COUNT, 0)
            print(
                f"[RLM] agent={agent_name} iter={iteration} event=before_agent",
                flush=True,
            )
            entry: dict[str, Any] = {
                "event": "before_agent",
                "timestamp": time.time(),
                "agent_name": agent_name,
                "request_id": state.get(TEMP_REQUEST_ID, "unknown"),
            }
            if self._include_session_state:
                entry["state_snapshot"] = _safe_state_snapshot(state)
            self._traces.append(entry)
        except Exception as e:
            print(f"[RLM_ERR] before_agent: {e}", file=sys.stdout, flush=True)
            logger.debug("DebugLogging before_agent error: %s", e)
        return None

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Record agent exit."""
        try:
            agent_name = getattr(agent, "name", "unknown")
            iteration = callback_context.state.get(TEMP_ITERATION_COUNT, 0)
            print(
                f"[RLM] agent={agent_name} iter={iteration} event=after_agent",
                flush=True,
            )
            self._traces.append({
                "event": "after_agent",
                "timestamp": time.time(),
                "agent_name": agent_name,
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
            })
        except Exception as e:
            print(f"[RLM_ERR] after_agent: {e}", file=sys.stdout, flush=True)
            logger.debug("DebugLogging after_agent error: %s", e)
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Record model request details."""
        try:
            state = callback_context.state
            model = llm_request.model or "unknown"
            iteration = state.get(TEMP_ITERATION_COUNT, 0)
            num_contents = len(llm_request.contents)

            # Build focused one-line stdout summary with token accounting
            # Detect agent type from state keys set by before_model callbacks
            reasoning_chars = state.get(TEMP_REASONING_PROMPT_CHARS)
            worker_chars = state.get(TEMP_WORKER_PROMPT_CHARS)

            if reasoning_chars is not None:
                history_msgs = state.get(TEMP_REASONING_HISTORY_MSG_COUNT, 0)
                sys_chars = state.get(TEMP_REASONING_SYSTEM_CHARS, 0)
                print(
                    f"[RLM] iter={iteration} model={model} "
                    f"prompt_chars={reasoning_chars} system_chars={sys_chars} "
                    f"history_msgs={history_msgs} contents={num_contents}",
                    flush=True,
                )
            elif worker_chars is not None:
                worker_contents = state.get(TEMP_WORKER_CONTENT_COUNT, 0)
                print(
                    f"[RLM] iter={iteration} model={model} "
                    f"worker_prompt_chars={worker_chars} "
                    f"worker_contents={worker_contents}",
                    flush=True,
                )
            else:
                print(
                    f"[RLM] iter={iteration} model={model} "
                    f"contents={num_contents}",
                    flush=True,
                )

            entry: dict[str, Any] = {
                "event": "before_model",
                "timestamp": time.time(),
                "model": model,
                "request_id": state.get(TEMP_REQUEST_ID, "unknown"),
                "num_contents": num_contents,
            }
            # Record prompt text
            prompt_parts = []
            for content in llm_request.contents:
                if content.parts:
                    for part in content.parts:
                        if hasattr(part, "text") and part.text:
                            prompt_parts.append(part.text[:500])
            entry["prompt_preview"] = prompt_parts

            if self._include_system_instruction and llm_request.config:
                si = getattr(llm_request.config, "system_instruction", None)
                if si:
                    entry["system_instruction_preview"] = str(si)[:500]

            # Capture per-invocation token accounting from state
            context_snapshot = state.get(TEMP_CONTEXT_WINDOW_SNAPSHOT)
            if context_snapshot:
                entry["context_window_snapshot"] = context_snapshot

            token_accounting = {}
            for key, label in [
                (TEMP_REASONING_PROMPT_CHARS, "reasoning_prompt_chars"),
                (TEMP_REASONING_SYSTEM_CHARS, "reasoning_system_chars"),
                (TEMP_REASONING_CONTENT_COUNT, "reasoning_content_count"),
                (TEMP_REASONING_HISTORY_MSG_COUNT, "reasoning_history_msg_count"),
                (TEMP_WORKER_PROMPT_CHARS, "worker_prompt_chars"),
                (TEMP_WORKER_CONTENT_COUNT, "worker_content_count"),
            ]:
                val = state.get(key)
                if val is not None:
                    token_accounting[label] = val
            if token_accounting:
                entry["token_accounting"] = token_accounting

            self._traces.append(entry)
        except Exception as e:
            print(f"[RLM_ERR] before_model: {e}", file=sys.stdout, flush=True)
            logger.debug("DebugLogging before_model error: %s", e)
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Record model response details."""
        try:
            state = callback_context.state
            iteration = state.get(TEMP_ITERATION_COUNT, 0)

            # Extract token usage from response metadata
            tokens_in = 0
            tokens_out = 0
            if llm_response.usage_metadata:
                tokens_in = getattr(
                    llm_response.usage_metadata, "prompt_token_count", 0
                ) or 0
                tokens_out = getattr(
                    llm_response.usage_metadata, "candidates_token_count", 0
                ) or 0

            # Determine agent type from state keys
            reasoning_in = state.get(TEMP_REASONING_INPUT_TOKENS)
            worker_in = state.get(TEMP_WORKER_INPUT_TOKENS)

            if reasoning_in is not None:
                agent_label = "reasoning"
            elif worker_in is not None:
                agent_label = "worker"
            else:
                agent_label = "unknown"

            # Worker dispatch info
            dispatch_count = state.get(TEMP_WORKER_DISPATCH_COUNT, 0)
            results_committed = state.get(TEMP_WORKER_RESULTS_COMMITTED, False)

            parts = [
                f"[RLM] iter={iteration} response",
                f"agent={agent_label}",
                f"tokens_in={tokens_in} tokens_out={tokens_out}",
            ]
            if dispatch_count > 0:
                parts.append(
                    f"workers_dispatched={dispatch_count} "
                    f"results_committed={results_committed}"
                )
            print(" ".join(parts), flush=True)

            if llm_response.error_code:
                print(
                    f"[RLM_WARN] iter={iteration} model_error "
                    f"code={llm_response.error_code} "
                    f"msg={llm_response.error_message}",
                    flush=True,
                )

            entry: dict[str, Any] = {
                "event": "after_model",
                "timestamp": time.time(),
                "request_id": state.get(TEMP_REQUEST_ID, "unknown"),
            }
            # Record response text
            if llm_response.content and llm_response.content.parts:
                response_text = ""
                for part in llm_response.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
                entry["response_preview"] = response_text[:1000]

            # Record usage metadata
            if llm_response.usage_metadata:
                entry["usage"] = {
                    "prompt_tokens": tokens_in,
                    "candidates_tokens": tokens_out,
                }

            if llm_response.error_code:
                entry["error_code"] = llm_response.error_code
                entry["error_message"] = llm_response.error_message

            # Capture per-agent-type response token breakdowns from state
            response_tokens = {}
            for key, label in [
                (TEMP_REASONING_INPUT_TOKENS, "reasoning_input_tokens"),
                (TEMP_REASONING_OUTPUT_TOKENS, "reasoning_output_tokens"),
                (TEMP_WORKER_INPUT_TOKENS, "worker_input_tokens"),
                (TEMP_WORKER_OUTPUT_TOKENS, "worker_output_tokens"),
            ]:
                val = state.get(key)
                if val is not None:
                    response_tokens[label] = val
            if response_tokens:
                entry["per_agent_tokens"] = response_tokens

            self._traces.append(entry)
        except Exception as e:
            print(f"[RLM_ERR] after_model: {e}", file=sys.stdout, flush=True)
            logger.debug("DebugLogging after_model error: %s", e)
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> Optional[LlmResponse]:
        """Record model error details."""
        try:
            model = llm_request.model or "unknown"
            iteration = callback_context.state.get(TEMP_ITERATION_COUNT, 0)
            print(
                f"[RLM_ERR] iter={iteration} model={model} "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
            self._traces.append({
                "event": "model_error",
                "timestamp": time.time(),
                "model": model,
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
                "error_type": type(error).__name__,
                "error_message": str(error),
            })
        except Exception as e:
            print(f"[RLM_ERR] on_model_error: {e}", file=sys.stdout, flush=True)
            logger.debug("DebugLogging on_model_error error: %s", e)
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict]:
        """Record tool invocation."""
        try:
            self._traces.append({
                "event": "before_tool",
                "timestamp": time.time(),
                "tool_name": getattr(tool, "name", str(tool)),
                "args": {k: str(v)[:200] for k, v in tool_args.items()},
                "request_id": tool_context.state.get(TEMP_REQUEST_ID, "unknown"),
            })
        except Exception as e:
            logger.debug("DebugLogging before_tool error: %s", e)
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> Optional[dict]:
        """Record tool result."""
        try:
            self._traces.append({
                "event": "after_tool",
                "timestamp": time.time(),
                "tool_name": getattr(tool, "name", str(tool)),
                "result_preview": str(result)[:500],
                "request_id": tool_context.state.get(TEMP_REQUEST_ID, "unknown"),
            })
        except Exception as e:
            logger.debug("DebugLogging after_tool error: %s", e)
        return None

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Optional[Event]:
        """Record events."""
        try:
            entry: dict[str, Any] = {
                "event": "on_event",
                "timestamp": time.time(),
                "author": event.author,
            }
            if event.actions and event.actions.state_delta:
                delta_keys = list(event.actions.state_delta.keys())
                entry["state_delta_keys"] = delta_keys
                # Only print state delta summaries for non-trivial deltas
                if len(delta_keys) > 0:
                    # Compact display: show key names without the prefix
                    short_keys = [k.split(":")[-1] if ":" in k else k for k in delta_keys]
                    print(
                        f"[RLM] event author={event.author} "
                        f"state_delta=[{', '.join(short_keys)}]",
                        flush=True,
                    )
            self._traces.append(entry)
        except Exception as e:
            print(f"[RLM_ERR] on_event: {e}", file=sys.stdout, flush=True)
        return None

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Write all traces to YAML file and print run summary."""
        try:
            state = invocation_context.session.state

            # --- Print run summary to stdout ---
            total_iters = state.get(TEMP_ITERATION_COUNT, 0)
            total_in = state.get(OBS_TOTAL_INPUT_TOKENS, 0)
            total_out = state.get(OBS_TOTAL_OUTPUT_TOKENS, 0)
            total_calls = state.get(OBS_TOTAL_CALLS, 0)
            total_time = state.get(OBS_TOTAL_EXECUTION_TIME, 0)
            final_answer = state.get(TEMP_FINAL_ANSWER, "")
            answer_len = len(final_answer) if final_answer else 0

            summary_parts = [
                f"[RLM] RUN_COMPLETE iters={total_iters}",
                f"calls={total_calls}",
                f"tokens_in={total_in} tokens_out={total_out}",
                f"time={total_time:.2f}s" if isinstance(total_time, (int, float)) else f"time={total_time}",
                f"answer_len={answer_len}",
            ]

            # Worker dispatch stats
            total_dispatches = state.get(OBS_WORKER_TOTAL_DISPATCHES, 0)
            if total_dispatches > 0:
                latencies = state.get(OBS_WORKER_DISPATCH_LATENCY_MS, [])
                events_drained = state.get(TEMP_WORKER_EVENTS_DRAINED, 0)
                avg_latency = (
                    sum(latencies) / len(latencies) if latencies else 0
                )
                summary_parts.append(
                    f"worker_dispatches={total_dispatches} "
                    f"events_drained={events_drained} "
                    f"avg_latency_ms={avg_latency:.1f}"
                )

            print(" ".join(summary_parts), flush=True)

        except Exception as e:
            print(f"[RLM_ERR] after_run summary: {e}", file=sys.stdout, flush=True)

        try:
            import yaml

            state_snapshot = None
            if self._include_session_state:
                state_snapshot = _safe_state_snapshot(
                    invocation_context.session.state
                )

            output = {
                "session_id": invocation_context.session.id,
                "user_id": invocation_context.session.user_id,
                "final_state": state_snapshot,
                "traces": self._traces,
            }

            with open(self._output_path, "w") as f:
                yaml.dump(output, f, default_flow_style=False, sort_keys=False)

            logger.info("Debug traces written to %s", self._output_path)
        except Exception as e:
            print(f"[RLM_WARN] failed to write debug traces: {e}", flush=True)
            logger.warning("Failed to write debug traces: %s", e)
        finally:
            self._traces.clear()


def _safe_state_snapshot(state: Any) -> dict:
    """Create a JSON-safe snapshot of session state."""
    snapshot = {}
    try:
        # state may be a dict-like object
        items = state.items() if hasattr(state, "items") else {}
        for key, value in items:
            try:
                # Only include serializable values
                if isinstance(value, (str, int, float, bool, type(None))):
                    snapshot[key] = value
                elif isinstance(value, (list, dict)):
                    snapshot[key] = str(value)[:500]
                else:
                    snapshot[key] = f"<{type(value).__name__}>"
            except Exception:
                snapshot[key] = "<unserializable>"
    except Exception:
        pass
    return snapshot
