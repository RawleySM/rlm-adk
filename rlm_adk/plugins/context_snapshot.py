"""ContextWindowSnapshotPlugin - Captures full context window decomposition.

Writes one JSONL line per LLM call, capturing the exact per-turn,
per-agent context decomposition (mirroring reasoning_before_model
logic) with full text for every chunk and token counts from
usage_metadata.

Opt-in: enabled when ``RLM_CONTEXT_SNAPSHOTS=1``.

Architecture note (ADK review correction):
    Plugins fire BEFORE agent callbacks.  The LlmRequest is not yet
    populated when before_model_callback runs.  We store a *reference*
    to the mutable LlmRequest in before_model_callback and decompose
    it in after_model_callback, by which point the agent callbacks
    (reasoning_before_model) have mutated the
    object in-place.

Thread safety (ADK review correction):
    ParallelAgent runs multiple workers concurrently.  We use a dict
    keyed by agent name (not a single ``_pending_request``) and an
    ``asyncio.Lock`` for JSONL writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from rlm_adk.state import ITERATION_COUNT

logger = logging.getLogger(__name__)


class ContextWindowSnapshotPlugin(BasePlugin):
    """Captures full context window decomposition at each LLM call.

    Stores a reference to the LlmRequest in before_model_callback,
    then decomposes the (now-mutated) request in after_model_callback
    along with token counts from usage_metadata.
    """

    def __init__(
        self,
        *,
        name: str = "context_snapshot",
        output_path: str = ".adk/context_snapshots.jsonl",
        output_capture_path: str = ".adk/model_outputs.jsonl",
    ):
        super().__init__(name=name)
        self._output_path = Path(output_path)
        self._output_capture_path = Path(output_capture_path)
        # Dict keyed by agent name for concurrent worker safety
        self._pending: dict[str, dict[str, Any]] = {}
        self._file_handle: TextIOWrapper | None = None
        self._output_file_handle: TextIOWrapper | None = None
        self._write_lock = asyncio.Lock()
        self._output_write_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # before_model_callback: stash reference (do NOT decompose yet)
    # ------------------------------------------------------------------

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Store a mutable reference to the LlmRequest.

        Agent callbacks (reasoning_before_model) will mutate this object
        in-place after all plugin callbacks complete.
        We read the mutated state in after_model_callback.
        """
        try:
            agent_name = callback_context._invocation_context.agent.name
            self._pending[agent_name] = {
                "request": llm_request,
                "timestamp": time.time(),
                "iteration": callback_context.state.get(ITERATION_COUNT, 0),
                "session_id": callback_context.session.id,
                "agent_name": agent_name,
            }
        except Exception as e:
            print(
                f"[RLM_SNAP] before_model error: {e}", file=sys.stdout, flush=True
            )
            logger.debug("ContextSnapshot before_model error: %s", e)
        return None

    # ------------------------------------------------------------------
    # after_model_callback: decompose the mutated request + token counts
    # ------------------------------------------------------------------

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Decompose the mutated LlmRequest and pair with token counts."""
        try:
            agent_name = callback_context._invocation_context.agent.name
            pending = self._pending.pop(agent_name, None)
            if pending is None:
                return None

            llm_request: LlmRequest = pending["request"]
            agent_type = (
                "reasoning" if agent_name == "reasoning_agent" else "worker"
            )

            # Decompose the mutated request into chunks
            chunks = self._decompose_request(llm_request, agent_type, agent_name, pending["iteration"])

            # Extract usage_metadata
            usage = llm_response.usage_metadata
            input_tokens = 0
            output_tokens = 0
            thoughts_tokens = 0
            if usage:
                input_tokens = getattr(usage, "prompt_token_count", 0) or 0
                output_tokens = getattr(usage, "candidates_token_count", 0) or 0
                thoughts_tokens = getattr(usage, "thoughts_token_count", 0) or 0

            entry: dict[str, Any] = {
                "timestamp": pending["timestamp"],
                "session_id": pending["session_id"],
                "iteration": pending["iteration"],
                "agent_type": agent_type,
                "agent_name": agent_name,
                "model": llm_request.model or "unknown",
                "model_version": llm_response.model_version or "unknown",
                "chunks": [self._chunk_to_dict(c) for c in chunks],
                "total_chars": sum(c["char_count"] for c in [self._chunk_to_dict(ch) for ch in chunks]),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "thoughts_tokens": thoughts_tokens,
            }

            await self._flush_entry(entry)

            # --- Model output capture ---
            output_text, thought_text = self._extract_response_text(llm_response)
            output_entry: dict[str, Any] = {
                "timestamp": pending["timestamp"],
                "session_id": pending["session_id"],
                "iteration": pending["iteration"],
                "agent_type": agent_type,
                "agent_name": agent_name,
                "model": llm_request.model or "unknown",
                "model_version": llm_response.model_version or "unknown",
                "output_text": output_text,
                "output_chars": len(output_text),
                "thought_chars": len(thought_text),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "thoughts_tokens": thoughts_tokens,
                "error": False,
                "error_message": None,
            }
            await self._flush_output_entry(output_entry)

        except Exception as e:
            print(
                f"[RLM_SNAP] after_model error: {e}", file=sys.stdout, flush=True
            )
            logger.debug("ContextSnapshot after_model error: %s", e)
        return None

    # ------------------------------------------------------------------
    # on_model_error_callback: flush pending with error flag
    # ------------------------------------------------------------------

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> Optional[LlmResponse]:
        """Flush pending entry with error flag when the model call fails."""
        try:
            agent_name = callback_context._invocation_context.agent.name
            pending = self._pending.pop(agent_name, None)
            if pending is None:
                return None

            agent_type = (
                "reasoning" if agent_name == "reasoning_agent" else "worker"
            )

            # The request has been mutated by now (agent callbacks ran)
            chunks = self._decompose_request(
                llm_request, agent_type, agent_name, pending["iteration"]
            )

            entry: dict[str, Any] = {
                "timestamp": pending["timestamp"],
                "session_id": pending["session_id"],
                "iteration": pending["iteration"],
                "agent_type": agent_type,
                "agent_name": agent_name,
                "model": llm_request.model or "unknown",
                "model_version": "unknown",
                "chunks": [self._chunk_to_dict(c) for c in chunks],
                "total_chars": sum(c["char_count"] for c in [self._chunk_to_dict(ch) for ch in chunks]),
                "input_tokens": 0,
                "output_tokens": 0,
                "thoughts_tokens": 0,
                "error": True,
                "error_message": f"{type(error).__name__}: {error}",
            }

            await self._flush_entry(entry)

            # --- Model output capture (error case) ---
            error_msg = f"{type(error).__name__}: {error}"
            output_entry: dict[str, Any] = {
                "timestamp": pending["timestamp"],
                "session_id": pending["session_id"],
                "iteration": pending["iteration"],
                "agent_type": agent_type,
                "agent_name": agent_name,
                "model": llm_request.model or "unknown",
                "model_version": "unknown",
                "output_text": "",
                "output_chars": 0,
                "thought_chars": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "thoughts_tokens": 0,
                "error": True,
                "error_message": error_msg,
            }
            await self._flush_output_entry(output_entry)

        except Exception as e:
            print(
                f"[RLM_SNAP] on_model_error error: {e}",
                file=sys.stdout,
                flush=True,
            )
            logger.debug("ContextSnapshot on_model_error error: %s", e)
        return None

    # ------------------------------------------------------------------
    # after_run_callback: close file handle
    # ------------------------------------------------------------------

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Close the JSONL file handles."""
        try:
            if self._file_handle is not None:
                self._file_handle.close()
                self._file_handle = None
                logger.info(
                    "Context snapshots written to %s", self._output_path
                )
            if self._output_file_handle is not None:
                self._output_file_handle.close()
                self._output_file_handle = None
                logger.info(
                    "Model outputs written to %s", self._output_capture_path
                )
        except Exception as e:
            logger.debug("ContextSnapshot after_run error: %s", e)

    # ------------------------------------------------------------------
    # Context decomposition
    # ------------------------------------------------------------------

    def _decompose_request(
        self,
        llm_request: LlmRequest,
        agent_type: str,
        agent_name: str,
        iteration: int,
    ) -> list[dict[str, Any]]:
        """Decompose the mutated LlmRequest into typed chunks."""
        if agent_type == "reasoning":
            return self._decompose_reasoning(llm_request, iteration)
        else:
            return self._decompose_worker(llm_request, agent_name, iteration)

    def _decompose_reasoning(
        self,
        llm_request: LlmRequest,
        iteration: int,
    ) -> list[dict[str, Any]]:
        """Decompose a reasoning agent's LlmRequest into chunks.

        After reasoning_before_model has mutated the request:
        - system_instruction contains static + dynamic (concatenated with \\n\\n)
        - contents contains the message history
        """
        chunks: list[dict[str, Any]] = []

        # 1. System instruction: split into static + dynamic
        si_text = self._extract_system_instruction_text(llm_request)
        if si_text:
            # ADK review correction: use "\\n\\nRepository URL:" as boundary
            boundary = "\n\nRepository URL:"
            boundary_idx = si_text.find(boundary)
            if boundary_idx >= 0:
                static_text = si_text[:boundary_idx]
                dynamic_text = si_text[boundary_idx + 2:]  # skip the \n\n
                chunks.append(self._make_chunk(
                    f"iter{iteration}_reasoning_static_instruction",
                    "static_instruction",
                    "RLM System Prompt",
                    static_text,
                    -1,
                ))
                chunks.append(self._make_chunk(
                    f"iter{iteration}_reasoning_dynamic_instruction",
                    "dynamic_instruction",
                    "Dynamic Context (repo_url, root_prompt)",
                    dynamic_text,
                    -1,
                ))
            else:
                # No dynamic instruction -- emit as single static chunk
                chunks.append(self._make_chunk(
                    f"iter{iteration}_reasoning_static_instruction",
                    "static_instruction",
                    "RLM System Prompt",
                    si_text,
                    -1,
                ))

        # 2. Contents: classify by role and content patterns
        contents = llm_request.contents or []
        content_idx = 0
        # Track iteration origin from message pattern:
        # Each iteration adds: 1 user prompt, 1 model response, N code blocks
        msg_iter = 0
        last_role = None

        for content in contents:
            text = self._extract_content_text(content)
            role = getattr(content, "role", "user")

            if role == "user":
                if content_idx == 0 and "You have not interacted with the REPL" in text:
                    # Iteration 0 user prompt with safeguard
                    chunks.append(self._make_chunk(
                        f"iter{iteration}_reasoning_user_prompt_0",
                        "user_prompt",
                        "User Prompt (iter 0)",
                        text,
                        0,
                    ))
                elif "Code executed:\n```python" in text:
                    # REPL code + output, possibly with context vars
                    code_text, output_text, context_var_text = self._split_repl_message(text)
                    if code_text:
                        chunks.append(self._make_chunk(
                            f"iter{iteration}_reasoning_repl_code_{msg_iter}_{content_idx}",
                            "repl_code",
                            f"REPL Code (iter {msg_iter}, block {content_idx})",
                            code_text,
                            msg_iter,
                        ))
                    if output_text:
                        chunks.append(self._make_chunk(
                            f"iter{iteration}_reasoning_repl_output_{msg_iter}_{content_idx}",
                            "repl_output",
                            f"REPL Output (iter {msg_iter}, block {content_idx})",
                            output_text,
                            msg_iter,
                        ))
                    # ADK review correction: CONTEXT_VAR is within REPL output text
                    if context_var_text:
                        chunks.append(self._make_chunk(
                            f"iter{iteration}_reasoning_context_var_{msg_iter}_{content_idx}",
                            "context_var",
                            f"REPL Variables (iter {msg_iter}, block {content_idx})",
                            context_var_text,
                            msg_iter,
                        ))
                elif "The history before is your previous" in text or (
                    "Think step-by-step" in text
                ):
                    # User prompt for iteration > 0
                    chunks.append(self._make_chunk(
                        f"iter{iteration}_reasoning_user_prompt_{msg_iter}",
                        "user_prompt",
                        f"User Prompt (iter {msg_iter})",
                        text,
                        msg_iter,
                    ))
                    # After a user prompt, we are starting a new iteration
                    if last_role == "model" or content_idx == 0:
                        msg_iter_candidate = msg_iter
                    else:
                        msg_iter_candidate = msg_iter
                else:
                    # Generic user content
                    chunks.append(self._make_chunk(
                        f"iter{iteration}_reasoning_user_{content_idx}",
                        "user_prompt",
                        f"User Content ({content_idx})",
                        text,
                        msg_iter,
                    ))
            elif role == "model":
                # Filter out thought parts
                visible_text = self._extract_content_text_no_thoughts(content)
                chunks.append(self._make_chunk(
                    f"iter{iteration}_reasoning_llm_response_{msg_iter}",
                    "llm_response",
                    f"LLM Response (iter {msg_iter})",
                    visible_text,
                    msg_iter,
                ))
                # After a model response, the next user message starts a new iteration
                msg_iter += 1

            last_role = role
            content_idx += 1

        return chunks

    def _decompose_worker(
        self,
        llm_request: LlmRequest,
        agent_name: str,
        iteration: int,
    ) -> list[dict[str, Any]]:
        """Decompose a worker agent's LlmRequest into chunks.

        Decompose a child agent's LlmRequest:
        - contents contains the pending prompt (string or message list)
        - No system_instruction for child agents
        """
        chunks: list[dict[str, Any]] = []
        contents = llm_request.contents or []

        if not contents:
            return chunks

        # ADK review correction: handle both string and list prompt formats
        if len(contents) == 1:
            # Single prompt (string format)
            text = self._extract_content_text(contents[0])
            chunks.append(self._make_chunk(
                f"iter{iteration}_{agent_name}_prompt",
                "worker_prompt",
                "Worker Prompt",
                text,
                iteration,
            ))
        else:
            # Multi-turn message list format
            for idx, content in enumerate(contents):
                text = self._extract_content_text(content)
                role = getattr(content, "role", "user")
                if role == "model":
                    category = "worker_response"
                    title = f"Worker Context (model, msg {idx})"
                else:
                    category = "worker_prompt"
                    title = f"Worker Prompt (msg {idx})"
                chunks.append(self._make_chunk(
                    f"iter{iteration}_{agent_name}_msg_{idx}",
                    category,
                    title,
                    text,
                    iteration,
                ))

        return chunks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_system_instruction_text(llm_request: LlmRequest) -> str:
        """Extract system_instruction text from the request config."""
        if not llm_request.config or not llm_request.config.system_instruction:
            return ""
        si = llm_request.config.system_instruction
        if isinstance(si, str):
            return si
        if isinstance(si, types.Content) and si.parts:
            return "".join(
                p.text
                for p in si.parts
                if isinstance(p, types.Part) and p.text
            )
        return str(si)

    @staticmethod
    def _extract_content_text(content: types.Content) -> str:
        """Extract all text from a Content object's parts."""
        if not content.parts:
            return ""
        return "".join(
            p.text
            for p in content.parts
            if isinstance(p, types.Part) and p.text
        )

    @staticmethod
    def _extract_content_text_no_thoughts(content: types.Content) -> str:
        """Extract text from Content, filtering out thought parts."""
        if not content.parts:
            return ""
        return "".join(
            p.text
            for p in content.parts
            if isinstance(p, types.Part) and p.text and not getattr(p, "thought", False)
        )

    @staticmethod
    def _split_repl_message(text: str) -> tuple[str, str, str]:
        """Split a REPL user message into code, output, and context_var.

        The format (from format_iteration in parsing.py) is:
            Code executed:
            ```python
            <code>
            ```

            REPL output:
            <output>

        Context variables are embedded within the REPL output text
        as a line starting with "REPL variables:".
        """
        code_text = ""
        output_text = ""
        context_var_text = ""

        # Split code from output
        repl_boundary = "\n\nREPL output:\n"
        boundary_idx = text.find(repl_boundary)
        if boundary_idx >= 0:
            code_section = text[:boundary_idx]
            output_section = text[boundary_idx + len(repl_boundary):]

            # Extract code from within ```python ... ```
            code_start = code_section.find("```python\n")
            code_end = code_section.rfind("\n```")
            if code_start >= 0 and code_end > code_start:
                code_text = code_section[code_start + len("```python\n"):code_end]

            # Check for CONTEXT_VAR within output (ADK review correction)
            repl_var_marker = "REPL variables:"
            var_idx = output_section.find(repl_var_marker)
            if var_idx >= 0:
                # Split output from context vars
                context_var_text = output_section[var_idx:].strip()
                output_text = output_section[:var_idx].strip()
            else:
                output_text = output_section.strip()
        else:
            # No REPL output boundary -- treat entire text as code section
            code_start = text.find("```python\n")
            code_end = text.rfind("\n```")
            if code_start >= 0 and code_end > code_start:
                code_text = text[code_start + len("```python\n"):code_end]

        return code_text, output_text, context_var_text

    @staticmethod
    def _make_chunk(
        chunk_id: str,
        category: str,
        title: str,
        text: str,
        iteration_origin: int,
    ) -> dict[str, Any]:
        """Create a chunk dict for serialization."""
        return {
            "chunk_id": chunk_id,
            "category": category,
            "title": title,
            "char_count": len(text),
            "text": text,
            "iteration_origin": iteration_origin,
        }

    @staticmethod
    def _chunk_to_dict(chunk: dict[str, Any]) -> dict[str, Any]:
        """Pass-through since chunks are already dicts."""
        return chunk

    # ------------------------------------------------------------------
    # Response text extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_response_text(llm_response: LlmResponse) -> tuple[str, str]:
        """Extract visible output text and thought text from LlmResponse.

        Returns:
            (output_text, thought_text) tuple.
        """
        output_parts: list[str] = []
        thought_parts: list[str] = []
        if llm_response.content and llm_response.content.parts:
            for p in llm_response.content.parts:
                if not isinstance(p, types.Part) or not p.text:
                    continue
                if getattr(p, "thought", False):
                    thought_parts.append(p.text)
                else:
                    output_parts.append(p.text)
        return "".join(output_parts), "".join(thought_parts)

    # ------------------------------------------------------------------
    # JSONL file I/O
    # ------------------------------------------------------------------

    def _ensure_file_open(self) -> None:
        """Lazily open the JSONL file on first write."""
        if self._file_handle is None:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(self._output_path, "a", encoding="utf-8")

    def _ensure_output_file_open(self) -> None:
        """Lazily open the model outputs JSONL file on first write."""
        if self._output_file_handle is None:
            self._output_capture_path.parent.mkdir(parents=True, exist_ok=True)
            self._output_file_handle = open(
                self._output_capture_path, "a", encoding="utf-8"
            )

    async def _flush_entry(self, entry: dict[str, Any]) -> None:
        """Write a single JSONL line atomically (asyncio.Lock for safety)."""
        try:
            line = json.dumps(entry, ensure_ascii=False)
            async with self._write_lock:
                self._ensure_file_open()
                assert self._file_handle is not None
                self._file_handle.write(line + "\n")
                self._file_handle.flush()
        except Exception as e:
            print(
                f"[RLM_SNAP] flush error: {e}", file=sys.stdout, flush=True
            )
            logger.debug("ContextSnapshot flush error: %s", e)

    async def _flush_output_entry(self, entry: dict[str, Any]) -> None:
        """Write a model output JSONL line atomically."""
        try:
            line = json.dumps(entry, ensure_ascii=False)
            async with self._output_write_lock:
                self._ensure_output_file_open()
                assert self._output_file_handle is not None
                self._output_file_handle.write(line + "\n")
                self._output_file_handle.flush()
        except Exception as e:
            print(
                f"[RLM_SNAP] output flush error: {e}",
                file=sys.stdout,
                flush=True,
            )
            logger.debug("ContextSnapshot output flush error: %s", e)
