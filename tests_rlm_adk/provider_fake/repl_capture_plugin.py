"""REPLCapturePlugin — captures full REPL execution data for JSON export.

Fires for ALL agents (parent + child orchestrators) since child_ctx
preserves plugin_manager via ctx.model_copy().  Captures submitted code,
expanded code, stdout/stderr, variables, and lineage metadata at every
execute_code tool invocation across all depths/fanouts.

Usage::

    plugin = REPLCapturePlugin()
    result = await run_fixture_contract_with_plugins(
        fixture_path, extra_plugins=[plugin],
    )
    plugin.write_json(Path("/tmp/capture.json"), extra={...})
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin

from rlm_adk.state import (
    REPL_DID_EXPAND,
    REPL_EXPANDED_CODE,
    depth_key,
)


def _repl_globals_inventory(repl_globals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a static inventory of known REPL namespace injections.

    When *repl_globals* is provided (from a live REPL), classifies each
    entry.  Otherwise returns the canonical inventory from code analysis.
    """
    # Canonical inventory from codebase exploration
    canonical: dict[str, Any] = {
        # LocalREPL.__init__ (local_repl.py:201-209)
        "__builtins__": {"type": "dict", "source": "local_repl.py:202", "note": "safe builtins subset"},
        "__name__": {"type": "str", "source": "local_repl.py:203", "value": "__main__"},
        "FINAL_VAR": {"type": "function", "source": "local_repl.py:208"},
        "SHOW_VARS": {"type": "function", "source": "local_repl.py:209"},
        # Sync LLM query placeholders (orchestrator.py:295)
        "llm_query": {"type": "function", "source": "orchestrator.py:295", "note": "sync placeholder; AST rewriter converts to async"},
        "llm_query_batched": {"type": "function", "source": "orchestrator.py:295", "note": "sync placeholder; AST rewriter converts to async"},
        # Async LLM query closures (dispatch.py via orchestrator.py:286)
        "llm_query_async": {"type": "async function", "source": "dispatch.py:435", "note": "single child dispatch"},
        "llm_query_batched_async": {"type": "async function", "source": "dispatch.py:477", "note": "batched child dispatch"},
        # LLMResult class (orchestrator.py:260)
        "LLMResult": {"type": "class", "source": "orchestrator.py:260", "note": "str subclass with .error, .parsed, .model, etc."},
        # State snapshot (repl_tool.py:220)
        "_rlm_state": {
            "type": "dict",
            "source": "repl_tool.py:220",
            "keys": [
                "iteration_count", "current_depth", "app:max_iterations",
                "app:max_depth", "last_repl_result", "step:mode_enabled",
                "should_stop", "final_response_text",
                "_rlm_depth", "_rlm_fanout_idx", "_rlm_agent_name",
            ],
        },
    }

    if repl_globals is not None:
        live: dict[str, Any] = {}
        for name, val in repl_globals.items():
            if name.startswith("_") and name != "_rlm_state":
                continue
            entry = canonical.get(name, {})
            entry["type"] = type(val).__name__
            if callable(val) and not isinstance(val, type):
                entry["callable"] = True
            if isinstance(val, dict) and name == "_rlm_state":
                entry["live_keys"] = sorted(val.keys())
            live[name] = entry
        # Merge canonical entries not in live
        for name, entry in canonical.items():
            if name not in live:
                entry["present"] = False
                live[name] = entry
        return live

    return canonical


class REPLCapturePlugin(BasePlugin):
    """Captures full REPL execution data at every execute_code invocation."""

    def __init__(self) -> None:
        super().__init__(name="repl_capture")
        self.executions: list[dict[str, Any]] = []
        self._pending: dict[int, dict[str, Any]] = {}  # keyed by id(tool_context)
        # Populated by test code after run completes
        self.fixture_name: str = ""
        self.final_state: dict[str, Any] | None = None

    async def before_tool_callback(
        self, *, tool, tool_args, tool_context, **_kw
    ) -> None:
        if getattr(tool, "name", "") != "execute_code":
            return None

        inv = tool_context._invocation_context
        agent = inv.agent
        depth = getattr(agent, "_rlm_depth", 0)

        self._pending[id(tool_context)] = {
            "depth": depth,
            "fanout_idx": getattr(agent, "_rlm_fanout_idx", 0),
            "agent_name": getattr(agent, "name", "unknown"),
            "submitted_code": tool_args.get("code", ""),
            "timestamp_start": time.time(),
        }
        return None

    async def after_tool_callback(
        self, *, tool, tool_args, tool_context, result, **_kw
    ) -> None:
        if getattr(tool, "name", "") != "execute_code":
            return None

        pending = self._pending.pop(id(tool_context), None)
        if pending is None:
            return None

        depth = pending["depth"]

        # Read expanded code from state (if skill expansion occurred)
        expanded_code = tool_context.state.get(
            depth_key(REPL_EXPANDED_CODE, depth)
        )
        did_expand = bool(tool_context.state.get(
            depth_key(REPL_DID_EXPAND, depth)
        ))

        # Read the _rlm_state snapshot that was active during execution
        rlm_state = None
        repl = getattr(tool, "repl", None)
        if repl is not None:
            rlm_state_raw = repl.globals.get("_rlm_state")
            if isinstance(rlm_state_raw, dict):
                rlm_state = dict(rlm_state_raw)

        # Extract result fields
        stdout = ""
        stderr = ""
        variables = {}
        llm_calls_made = False
        call_number = 0
        if isinstance(result, dict):
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            variables = result.get("variables", {})
            llm_calls_made = result.get("llm_calls_made", False)
            call_number = result.get("call_number", 0)

        entry: dict[str, Any] = {
            "call_number": call_number,
            "depth": depth,
            "fanout_idx": pending["fanout_idx"],
            "agent_name": pending["agent_name"],
            "submitted_code": pending["submitted_code"],
            "expanded_code": expanded_code,
            "did_expand": did_expand,
            "stdout": stdout,
            "stderr": stderr,
            "variables": _safe_serialize(variables),
            "llm_calls_made": llm_calls_made,
            "rlm_state_snapshot": rlm_state,
            "wall_time_s": round(time.time() - pending["timestamp_start"], 4),
        }
        self.executions.append(entry)
        return None

    def build_output(
        self,
        *,
        test_name: str = "",
        fixture_name: str = "",
        final_state: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the full JSON-serializable output dict."""
        output: dict[str, Any] = {
            "test_name": test_name,
            "fixture": fixture_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "repl_globals_inventory": _repl_globals_inventory(),
            "repl_executions": self.executions,
        }
        if final_state is not None:
            output["final_state"] = _safe_serialize(final_state)
        if extra:
            output.update(extra)
        return output

    def write_json(
        self,
        path: Path,
        *,
        test_name: str = "",
        fixture_name: str = "",
        final_state: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Write captured data to a JSON file."""
        output = self.build_output(
            test_name=test_name,
            fixture_name=fixture_name,
            final_state=final_state,
            extra=extra,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        return path


def _safe_serialize(obj: Any) -> Any:
    """Recursively convert to JSON-safe types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(item) for item in obj]
    if isinstance(obj, set):
        return sorted(_safe_serialize(item) for item in obj)
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError, OverflowError):
        return repr(obj)
