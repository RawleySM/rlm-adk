"""DashboardEventPlugin - Captures model + tool events to append-only JSONL.

Writes one JSONL line per model call and one per tool invocation, with
explicit lineage fields (parent_invocation_id, parent_tool_call_id,
dispatch_call_index) so the dashboard can reconstruct the full
parent->child tree without inference.

Thread safety: uses threading.Lock (not asyncio.Lock) because the
GAP-06 finalizer is called synchronously from the REPL worker thread.
"""

import json
import logging
import threading
import time
import uuid
from io import TextIOWrapper
from pathlib import Path
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class DashboardEventPlugin(BasePlugin):
    """Captures model + tool events to append-only JSONL with explicit lineage."""

    def __init__(
        self,
        *,
        name: str = "dashboard_events",
        output_path: str = ".adk/dashboard_events.jsonl",
    ):
        super().__init__(name=name)
        self._output_path = Path(output_path)
        self._pending_model: dict[int, dict] = {}  # keyed by id(inv_ctx)
        self._pending_tool: dict[int, dict] = {}  # keyed by id(tool_context)
        self._last_model_event_id: dict[int, str] = {}  # id(inv_ctx) -> event_id
        self._write_lock = threading.Lock()  # NOT asyncio.Lock (R4-2)
        self._file_handle: TextIOWrapper | None = None

    # ── Callbacks ──

    async def before_model_callback(self, *, callback_context, llm_request, **kwargs):
        """Stash mutable LlmRequest ref + lineage, keyed by id(inv_ctx)."""
        inv_ctx = callback_context._invocation_context
        inv_id = getattr(inv_ctx, "invocation_id", "") or f"fallback_{id(callback_context)}"
        ctx_key = id(inv_ctx)
        agent = inv_ctx.agent
        self._pending_model[ctx_key] = {
            "request": llm_request,
            "timestamp": time.time(),
            "agent_name": getattr(agent, "name", ""),
            "depth": getattr(agent, "_rlm_depth", 0),
            "fanout_idx": getattr(agent, "_rlm_fanout_idx", None),
            "invocation_id": inv_id,
            "parent_invocation_id": getattr(agent, "_rlm_parent_invocation_id", None),
            "parent_tool_call_id": getattr(agent, "_rlm_parent_tool_call_id", None),
            "dispatch_call_index": getattr(agent, "_rlm_dispatch_call_index", 0),
            "branch": getattr(inv_ctx, "branch", None),
            "session_id": (
                getattr(inv_ctx, "session", None) and str(getattr(inv_ctx.session, "id", ""))
            ),
        }
        return None  # Don't short-circuit

    async def after_model_callback(self, *, callback_context, llm_response, **kwargs):
        """Decompose mutated request + tokens -> emit StepEvent(phase='model')."""
        inv_ctx = callback_context._invocation_context
        ctx_key = id(inv_ctx)
        pending = self._pending_model.pop(ctx_key, None)
        if pending is None:
            return None

        event_id = uuid.uuid4().hex
        self._last_model_event_id[ctx_key] = event_id

        # Extract token counts from llm_response
        usage = getattr(llm_response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
        thought_tokens = getattr(usage, "thoughts_token_count", 0) or 0 if usage else 0

        # Extract model name
        model = getattr(pending["request"], "model", "") or ""

        # Build event dict
        event = {
            "event_id": event_id,
            "phase": "model",
            "invocation_id": pending["invocation_id"],
            "parent_invocation_id": pending.get("parent_invocation_id"),
            "parent_tool_call_id": pending.get("parent_tool_call_id"),
            "dispatch_call_index": pending.get("dispatch_call_index", 0),
            "branch": pending.get("branch"),
            "session_id": pending.get("session_id"),
            "model_event_id": None,  # model events don't reference other model events
            "agent_name": pending.get("agent_name", ""),
            "depth": pending.get("depth", 0),
            "fanout_idx": pending.get("fanout_idx"),
            "ts": pending["timestamp"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thought_tokens": thought_tokens,
            "model": str(model),
            "error": bool(getattr(llm_response, "error_code", None)),
            "error_message": getattr(llm_response, "error_message", None),
        }
        self._write_event(event)
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context, **kwargs):
        """Stash tool start info. For execute_code: set InvCtx attrs."""
        event_id = uuid.uuid4().hex
        inv_ctx = tool_context._invocation_context
        inv_id = getattr(inv_ctx, "invocation_id", "")
        agent = inv_ctx.agent

        self._pending_tool[id(tool_context)] = {
            "event_id": event_id,
            "start_time": time.time(),
            "tool_name": getattr(tool, "name", ""),
            "tool_args": tool_args,
            "invocation_id": inv_id,
            "ctx_key": id(inv_ctx),
            "agent_name": getattr(agent, "name", ""),
            "depth": getattr(agent, "_rlm_depth", 0),
            "fanout_idx": getattr(agent, "_rlm_fanout_idx", None),
            "parent_invocation_id": getattr(agent, "_rlm_parent_invocation_id", None),
            "parent_tool_call_id": getattr(agent, "_rlm_parent_tool_call_id", None),
            "dispatch_call_index": getattr(agent, "_rlm_dispatch_call_index", 0),
            "branch": getattr(inv_ctx, "branch", None),
            "session_id": (
                getattr(inv_ctx, "session", None) and str(getattr(inv_ctx.session, "id", ""))
            ),
        }

        # For execute_code: set attrs on AGENT (not InvocationContext) for child dispatch.
        # The dispatch closure reads from ctx (orchestrator's InvocationContext), but
        # the plugin's tool_context._invocation_context is a DIFFERENT object (ADK
        # creates a new InvocationContext for tool callbacks). The agent object is the
        # same across both, so use it as the bridge.
        tool_name = getattr(tool, "name", "")
        if tool_name == "execute_code":
            object.__setattr__(agent, "_dashboard_execute_code_event_id", event_id)
            object.__setattr__(agent, "_dashboard_dispatch_call_counter", 0)  # R4-1 reset

        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result, **kwargs):
        """Pop pending -> emit StepEvent(phase='tool') with model_event_id link."""
        pending = self._pending_tool.pop(id(tool_context), None)
        if pending is None:
            return None

        inv_ctx = tool_context._invocation_context
        ctx_key = id(inv_ctx)
        model_event_id = self._last_model_event_id.get(ctx_key)
        end_time = time.time()
        duration_ms = (end_time - pending["start_time"]) * 1000

        tool_name = pending["tool_name"]

        event = {
            "event_id": pending["event_id"],
            "phase": "tool",
            "invocation_id": pending["invocation_id"],
            "parent_invocation_id": pending.get("parent_invocation_id"),
            "parent_tool_call_id": pending.get("parent_tool_call_id"),
            "dispatch_call_index": pending.get("dispatch_call_index", 0),
            "branch": pending.get("branch"),
            "session_id": pending.get("session_id"),
            "model_event_id": model_event_id,
            "agent_name": pending.get("agent_name", ""),
            "depth": pending.get("depth", 0),
            "fanout_idx": pending.get("fanout_idx"),
            "ts": end_time,
            "tool_name": tool_name,
            "tool_args": _safe_serialize(tool_args),
            "tool_result": _safe_serialize(result),
            "duration_ms": round(duration_ms, 2),
            "code": (
                tool_args.get("code")
                if isinstance(tool_args, dict) and tool_name == "execute_code"
                else None
            ),
            "stdout": result.get("stdout") if isinstance(result, dict) else None,
            "stderr": result.get("stderr") if isinstance(result, dict) else None,
            "llm_query_detected": (
                bool(result.get("llm_calls_made")) if isinstance(result, dict) else False
            ),
            "llm_query_count": (
                result.get("total_llm_calls", 0) if isinstance(result, dict) else 0
            ),
            "error": False,
            "error_message": None,
        }
        self._write_event(event)

        # Cleanup: set_model_response is terminal -- no more model->tool pairs (R5-2)
        if tool_name == "set_model_response":
            self._last_model_event_id.pop(ctx_key, None)

        return None

    # ── GAP-06 Finalizer ──

    def make_telemetry_finalizer(self):
        """Create sync finalizer closure for GAP-06 path (REPLTool calls this)."""
        pending = self._pending_tool
        write = self._write_event
        last_model = self._last_model_event_id

        def _finalize(tool_context_id: int, result: dict) -> None:
            entry = pending.pop(tool_context_id, None)
            if entry is None:
                return  # Already finalized by after_tool_callback

            ctx_key = entry.get("ctx_key")
            model_event_id = last_model.get(ctx_key) if ctx_key else None
            end_time = time.time()
            duration_ms = (end_time - entry["start_time"]) * 1000
            tool_name = entry["tool_name"]

            event = {
                "event_id": entry["event_id"],
                "phase": "tool",
                "invocation_id": entry["invocation_id"],
                "parent_invocation_id": entry.get("parent_invocation_id"),
                "parent_tool_call_id": entry.get("parent_tool_call_id"),
                "dispatch_call_index": entry.get("dispatch_call_index", 0),
                "branch": entry.get("branch"),
                "session_id": entry.get("session_id"),
                "model_event_id": model_event_id,
                "agent_name": entry.get("agent_name", ""),
                "depth": entry.get("depth", 0),
                "fanout_idx": entry.get("fanout_idx"),
                "ts": end_time,
                "tool_name": tool_name,
                "tool_args": _safe_serialize(entry.get("tool_args")),
                "tool_result": _safe_serialize(result),
                "duration_ms": round(duration_ms, 2),
                "code": (
                    entry["tool_args"].get("code")
                    if isinstance(entry.get("tool_args"), dict) and tool_name == "execute_code"
                    else None
                ),
                "stdout": result.get("stdout") if isinstance(result, dict) else None,
                "stderr": result.get("stderr") if isinstance(result, dict) else None,
                "llm_query_detected": (
                    bool(result.get("llm_calls_made")) if isinstance(result, dict) else False
                ),
                "llm_query_count": (
                    result.get("total_llm_calls", 0) if isinstance(result, dict) else 0
                ),
                "error": False,
                "error_message": None,
            }
            write(event)

        return _finalize

    # ── JSONL Writer ──

    def _write_event(self, event: dict) -> None:
        """Synchronous serialized JSONL append under threading.Lock.

        Safe from async callbacks AND sync GAP-06 finalizer.
        """
        with self._write_lock:
            if self._file_handle is None:
                self._output_path.parent.mkdir(parents=True, exist_ok=True)
                self._file_handle = open(self._output_path, "a")
            self._file_handle.write(json.dumps(event, default=str) + "\n")
            self._file_handle.flush()

    def close(self):
        """Clean up file handle."""
        with self._write_lock:
            if self._file_handle is not None:
                self._file_handle.close()
                self._file_handle = None


def _safe_serialize(obj: Any) -> Any:
    """Safely serialize objects for JSON, truncating large values."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    try:
        return str(obj)[:2000]
    except Exception:
        return "<unserializable>"
