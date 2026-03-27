"""Instrumented contract runner for architecture introspection e2e tests.

Extends the provider-fake contract runner with:
- InstrumentationPlugin for global callback coverage
- Local callback hooks for root agent introspection
- Dynamic instruction capture via dyn_instr_capture_hook
- Stdout capture via TeeWriter
- State key timeline construction

Usage::

    from tests_rlm_adk.provider_fake.instrumented_runner import (
        run_fixture_contract_instrumented,
    )

    result = await run_fixture_contract_instrumented(
        Path("tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json"),
        traces_db_path=str(tmp_path / "traces.db"),
    )
    assert result.passed, result.diagnostics()
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.artifacts import FileArtifactService
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.agent import _default_session_service, create_rlm_app

from .contract_runner import (
    PluginContractResult,
    _make_repl,
    _restore_env,
    _save_env,
    _set_env,
    _set_env_litellm,
    _setup_litellm_client,
    _teardown_litellm_client,
    _wire_test_hooks,
)
from .fixtures import ScenarioRouter
from .server import FakeGeminiServer

# ---------------------------------------------------------------------------
# InstrumentationPlugin — full callback coverage for all agents
# ---------------------------------------------------------------------------


class InstrumentationPlugin(BasePlugin):
    """Captures complete state key and variable lineage across all agents.

    All output uses tagged format:
    - [PLUGIN:hook:agent_name:key=value] for plugin-level data
    - [STATE:key=value] for state snapshots at each callback point
    - [TIMING:label=ms] for timing data

    Output is buffered to ``self._log_lines`` instead of printing directly
    to stdout.  This prevents interference with the REPL's stdout capture
    during child agent execution (plugin callbacks fire on the event loop
    while execute_code blocks on the thread bridge, and stdout prints from
    plugin callbacks leak into the REPL tool response, causing ADK's output
    parser to terminate child agent loops prematurely).

    Observe-only: never returns a value, never blocks execution.
    All errors are caught and suppressed.
    """

    def __init__(self, *, name: str = "instrumentation"):
        super().__init__(name=name)
        self._tool_start_times: dict[str, float] = {}
        self._agent_start_times: dict[str, float] = {}
        self._model_start_times: dict[str, float] = {}
        self._call_counter: int = 0
        self._log_lines: list[str] = []

    def _emit(self, hook: str, agent_name: str, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            self._log_lines.append(f"[PLUGIN:{hook}:{agent_name}:{key}={value}]")

    def _emit_state(self, state: Any, prefix: str = "") -> None:
        from rlm_adk.state import CURATED_STATE_KEYS, CURATED_STATE_PREFIXES

        try:
            state_dict = dict(state) if state else {}
        except Exception:
            return

        for key, value in state_dict.items():
            base_key = key.split("@")[0]
            if base_key in CURATED_STATE_KEYS or any(
                base_key.startswith(p) for p in CURATED_STATE_PREFIXES
            ):
                tag = f"{prefix}{key}"
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "...[truncated]"
                self._log_lines.append(f"[STATE:{tag}={val_str}]")

    def _agent_key(self, agent: BaseAgent, callback_context: CallbackContext) -> str:
        agent_name = getattr(agent, "name", "unknown")
        inv_id = getattr(callback_context, "invocation_id", "?")
        return f"{agent_name}#{inv_id}"

    # --- Agent lifecycle ---

    async def before_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> types.Content | None:
        try:
            agent_name = getattr(agent, "name", "unknown")
            depth = getattr(agent, "_rlm_depth", 0)
            fanout = getattr(agent, "_rlm_fanout_idx", 0)
            key = self._agent_key(agent, callback_context)
            self._agent_start_times[key] = time.monotonic()

            self._emit(
                "before_agent",
                agent_name,
                depth=depth,
                fanout_idx=fanout,
                agent_type=type(agent).__name__,
            )
            self._emit_state(callback_context.state, prefix="before_agent:")
        except Exception:
            pass
        return None

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> types.Content | None:
        try:
            agent_name = getattr(agent, "name", "unknown")
            key = self._agent_key(agent, callback_context)
            start = self._agent_start_times.pop(key, None)
            elapsed_ms = round((time.monotonic() - start) * 1000, 2) if start else -1

            self._emit(
                "after_agent",
                agent_name,
                depth=getattr(agent, "_rlm_depth", 0),
                elapsed_ms=elapsed_ms,
            )
            self._emit_state(callback_context.state, prefix="after_agent:")
            self._log_lines.append(f"[TIMING:agent_{agent_name}_ms={elapsed_ms}]")
        except Exception:
            pass
        return None

    # --- Model lifecycle ---

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        try:
            self._call_counter += 1
            call_num = self._call_counter
            agent_name = callback_context.agent_name

            model = getattr(llm_request, "model", "unknown") or "unknown"
            sys_instr_len = 0
            if llm_request.config and llm_request.config.system_instruction:
                si = llm_request.config.system_instruction
                if isinstance(si, str):
                    sys_instr_len = len(si)
                elif hasattr(si, "parts") and si.parts:
                    sys_instr_len = sum(len(p.text or "") for p in si.parts if hasattr(p, "text"))

            contents_count = len(llm_request.contents) if llm_request.contents else 0
            tools_count = len(llm_request.tools_dict) if llm_request.tools_dict else 0

            self._model_start_times[f"{agent_name}#{call_num}"] = time.monotonic()

            self._emit(
                "before_model",
                agent_name,
                call_num=call_num,
                model=model,
                depth=callback_context.state.get("current_depth", 0),
                sys_instr_len=sys_instr_len,
                contents_count=contents_count,
                tools_count=tools_count,
            )

            iter_count = callback_context.state.get("iteration_count", 0)
            should_stop = callback_context.state.get("should_stop", False)
            repl_did_expand = callback_context.state.get("repl_did_expand", False)
            self._log_lines.append(
                f"[STATE:model_call_{call_num}:iteration_count={iter_count}]"
            )
            self._log_lines.append(
                f"[STATE:model_call_{call_num}:should_stop={should_stop}]"
            )
            self._log_lines.append(
                f"[STATE:model_call_{call_num}:repl_did_expand={repl_did_expand}]"
            )
        except Exception:
            pass
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        try:
            agent_name = callback_context.agent_name
            call_num = self._call_counter
            key = f"{agent_name}#{call_num}"
            start = self._model_start_times.pop(key, None)
            elapsed_ms = round((time.monotonic() - start) * 1000, 2) if start else -1

            finish_reason = None
            if llm_response.finish_reason:
                finish_reason = getattr(
                    llm_response.finish_reason,
                    "name",
                    str(llm_response.finish_reason),
                )

            func_calls = 0
            if llm_response.content and llm_response.content.parts:
                func_calls = sum(
                    1
                    for p in llm_response.content.parts
                    if hasattr(p, "function_call") and p.function_call is not None
                )

            input_tokens = 0
            output_tokens = 0
            if llm_response.usage_metadata:
                input_tokens = getattr(llm_response.usage_metadata, "prompt_token_count", 0) or 0
                output_tokens = (
                    getattr(llm_response.usage_metadata, "candidates_token_count", 0) or 0
                )

            self._emit(
                "after_model",
                agent_name,
                call_num=call_num,
                finish_reason=finish_reason,
                func_calls=func_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                elapsed_ms=elapsed_ms,
            )
            self._log_lines.append(f"[TIMING:model_call_{call_num}_ms={elapsed_ms}]")
        except Exception:
            pass
        return None

    # --- Tool lifecycle ---

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict | None:
        try:
            tool_name = getattr(tool, "name", str(tool))
            agent_name = getattr(tool_context, "agent_name", "unknown")
            # BUG-014 fix: resolve depth from agent._rlm_depth (matches
            # SqliteTracingPlugin.before_model_callback pattern), falling
            # back to state for backward compat.
            inv_ctx = getattr(tool_context, "_invocation_context", None)
            _agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
            depth = getattr(_agent, "_rlm_depth", None)
            if depth is None:
                depth = tool_context.state.get("current_depth", 0)
            iter_count = tool_context.state.get("iteration_count", 0)

            code_preview = ""
            if tool_name == "execute_code" and "code" in tool_args:
                code_preview = str(tool_args["code"])[:120].replace("\n", "\\n")

            tk = f"{tool_name}#{agent_name}"
            self._tool_start_times[tk] = time.monotonic()

            self._emit(
                "before_tool",
                agent_name,
                tool_name=tool_name,
                depth=depth,
                iteration_count=iter_count,
                code_preview=repr(code_preview) if code_preview else "n/a",
            )
            self._emit_state(tool_context.state, prefix="pre_tool:")
        except Exception:
            pass
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> dict | None:
        try:
            tool_name = getattr(tool, "name", str(tool))
            agent_name = getattr(tool_context, "agent_name", "unknown")
            tk = f"{tool_name}#{agent_name}"
            start = self._tool_start_times.pop(tk, None)
            elapsed_ms = round((time.monotonic() - start) * 1000, 2) if start else -1

            result_preview = str(result)[:120] if result else "empty"

            self._emit(
                "after_tool",
                agent_name,
                tool_name=tool_name,
                elapsed_ms=elapsed_ms,
                result_preview=repr(result_preview),
            )
            self._emit_state(tool_context.state, prefix="post_tool:")
            self._log_lines.append(f"[TIMING:tool_{tool_name}_ms={elapsed_ms}]")
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Local callback wiring (root orchestrator + reasoning_agent only)
# ---------------------------------------------------------------------------


def _wire_instrumentation_hooks(app: Any, log_lines: list[str]) -> None:
    """Wire local instrumentation callbacks onto root orchestrator + reasoning_agent."""
    orchestrator = app.root_agent
    reasoning_agent = orchestrator.reasoning_agent

    # --- Orchestrator before_agent ---
    original_orch_before = getattr(orchestrator, "before_agent_callback", None)

    def _instr_orch_before(callback_context):
        try:
            state_keys = sorted(callback_context.state.to_dict().keys())
            log_lines.append(
                f"[CALLBACK:before_agent:rlm_orchestrator:state_key_count={len(state_keys)}]"
            )
            log_lines.append(
                f"[CALLBACK:before_agent:rlm_orchestrator:initial_state_keys={state_keys}]"
            )
        except Exception:
            pass
        if original_orch_before:
            return original_orch_before(callback_context)
        return None

    object.__setattr__(orchestrator, "before_agent_callback", _instr_orch_before)

    # --- Orchestrator after_agent ---
    def _instr_orch_after(callback_context):
        try:
            final_keys = sorted(callback_context.state.to_dict().keys())
            log_lines.append(
                f"[CALLBACK:after_agent:rlm_orchestrator:final_state_key_count={len(final_keys)}]"
            )
            state = callback_context.state
            for key in (
                "current_depth",
                "iteration_count",
                "should_stop",
                "final_response_text",
                "repl_did_expand",
                "repl_skill_expansion_meta",
            ):
                val = state.get(key)
                if val is not None:
                    log_lines.append(f"[CALLBACK:after_agent:rlm_orchestrator:{key}={val}]")
        except Exception:
            pass
        return None

    object.__setattr__(orchestrator, "after_agent_callback", _instr_orch_after)

    # --- Reasoning agent before_model ---
    original_reasoning_before = getattr(reasoning_agent, "before_model_callback", None)

    def _instr_reasoning_before_model(callback_context, llm_request):
        try:
            inv = getattr(callback_context, "_invocation_context", None)
            agent = getattr(inv, "agent", None) if inv else None
            depth = getattr(agent, "_rlm_depth", "?")
            fanout = getattr(agent, "_rlm_fanout_idx", "?")
            iteration = callback_context.state.get("iteration_count", "?")
            log_lines.append(
                f"[CALLBACK:before_model:reasoning_agent:"
                f"depth={depth},fanout={fanout},iteration={iteration}]"
            )
        except Exception:
            pass
        if original_reasoning_before:
            return original_reasoning_before(
                callback_context=callback_context, llm_request=llm_request
            )
        return None

    object.__setattr__(reasoning_agent, "before_model_callback", _instr_reasoning_before_model)

    # --- Reasoning agent after_model ---
    original_reasoning_after = getattr(reasoning_agent, "after_model_callback", None)

    def _instr_reasoning_after_model(callback_context, llm_response):
        try:
            inv = getattr(callback_context, "_invocation_context", None)
            agent = getattr(inv, "agent", None) if inv else None
            response_meta = getattr(agent, "_rlm_last_response_meta", None) or {}
            finish_reason = response_meta.get("finish_reason", "?")
            input_tokens = response_meta.get("input_tokens", 0)
            output_tokens = response_meta.get("output_tokens", 0)
            log_lines.append(
                f"[CALLBACK:after_model:reasoning_agent:"
                f"finish_reason={finish_reason},"
                f"input_tokens={input_tokens},"
                f"output_tokens={output_tokens}]"
            )
        except Exception:
            pass
        if original_reasoning_after:
            return original_reasoning_after(
                callback_context=callback_context, llm_response=llm_response
            )
        return None

    object.__setattr__(reasoning_agent, "after_model_callback", _instr_reasoning_after_model)

    # --- Reasoning agent before_tool ---
    original_before_tool = getattr(reasoning_agent, "before_tool_callback", None)

    def _instr_before_tool(tool, args, tool_context):
        try:
            tool_name = getattr(tool, "name", str(tool))
            state = tool_context.state
            iter_count = state.get("iteration_count", "?")
            depth = state.get("current_depth", "?")
            log_lines.append(
                f"[CALLBACK:before_tool:reasoning_agent:"
                f"tool={tool_name},iter={iter_count},depth={depth}]"
            )
            from rlm_adk.state import CURATED_STATE_KEYS, CURATED_STATE_PREFIXES

            for key, val in state.to_dict().items():
                base = key.split("@")[0]
                if base in CURATED_STATE_KEYS or any(
                    base.startswith(p) for p in CURATED_STATE_PREFIXES
                ):
                    val_str = str(val)
                    if len(val_str) > 200:
                        val_str = val_str[:200] + "...[truncated]"
                    log_lines.append(f"[STATE:pre_tool:{key}={val_str}]")
        except Exception:
            pass
        if original_before_tool:
            return original_before_tool(tool, args, tool_context)
        return None

    object.__setattr__(reasoning_agent, "before_tool_callback", _instr_before_tool)

    # NOTE: after_tool_callback is NOT wired locally — orchestrator overwrites it
    # at runtime via make_worker_tool_callbacks(). Rely on InstrumentationPlugin instead.


# ---------------------------------------------------------------------------
# Dynamic instruction capture hook (from Doc 3)
# ---------------------------------------------------------------------------

_DYN_INSTR_KEYS = {
    "{repo_url?}": "repo_url",
    "{root_prompt?}": "root_prompt",
    "{test_context?}": "test_context",
    "{skill_instruction?}": "skill_instruction",
    "{user_ctx_manifest?}": "user_ctx_manifest",
}


def make_dyn_instr_capture_hook(
    expected_keys: dict[str, str] | None = None,
) -> Any:
    """Factory returning a before_model_callback that captures systemInstruction."""
    _call_count = [0]

    def hook(callback_context: CallbackContext, llm_request: LlmRequest):
        if _call_count[0] > 0:
            _call_count[0] += 1
            return None  # only capture first call
        _call_count[0] += 1

        # Extract system instruction text (handles both str and Content-with-parts)
        si_text = ""
        config = getattr(llm_request, "config", None)
        if config:
            si = getattr(config, "system_instruction", None)
            if isinstance(si, str):
                si_text = si
            elif si and hasattr(si, "parts") and si.parts:
                si_text = "\n".join(p.text for p in si.parts if hasattr(p, "text") and p.text)

        callback_context.state["_captured_system_instruction_0"] = si_text[:10000]

        # Print verification tags
        keys_to_check = expected_keys or _DYN_INSTR_KEYS
        for placeholder, state_key in keys_to_check.items():
            resolved = placeholder not in si_text
            state_val = callback_context.state.get(state_key, "<missing>")
            print(f"[DYN_INSTR:{state_key}=resolved={resolved}]", flush=True)
            if resolved and isinstance(state_val, str):
                print(f"[DYN_INSTR:{state_key}_preview={state_val[:60]}]", flush=True)

        return None  # never short-circuit

    return hook


# ---------------------------------------------------------------------------
# Stdout capture via TeeWriter
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _capture_stdout():
    """Capture all stdout to a string buffer while also writing to real stdout."""
    captured = io.StringIO()
    original_stdout = sys.stdout

    class TeeWriter:
        def write(self, text: str) -> int:
            captured.write(text)
            original_stdout.write(text)
            return len(text)

        def flush(self) -> None:
            captured.flush()
            original_stdout.flush()

        def fileno(self) -> int:
            return original_stdout.fileno()

    sys.stdout = TeeWriter()  # type: ignore[assignment]
    try:
        yield captured
    finally:
        sys.stdout = original_stdout


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class InstrumentedContractResult:
    """Complete result from run_fixture_contract_instrumented()."""

    plugin_result: PluginContractResult
    instrumentation_log: str
    local_callback_log: list[str]
    repl_stdout: str
    state_key_timeline: dict[str, list[tuple[str, Any]]]

    @property
    def contract(self) -> Any:
        return self.plugin_result.contract

    @property
    def final_state(self) -> dict[str, Any]:
        return self.plugin_result.final_state

    @property
    def traces_db_path(self) -> str | None:
        return self.plugin_result.traces_db_path

    @property
    def passed(self) -> bool:
        return self.plugin_result.contract.passed

    def diagnostics(self) -> str:
        return self.plugin_result.contract.diagnostics()

    @property
    def repl_stderr(self) -> str:
        """Extract REPL stderr from last_repl_result if available."""
        lrr = self.final_state.get("last_repl_result")
        if isinstance(lrr, dict):
            return lrr.get("stderr", "")
        return ""


# ---------------------------------------------------------------------------
# State key timeline builder
# ---------------------------------------------------------------------------

_STATE_TIMELINE_RE = re.compile(r"\[STATE:([^\]]+)\]")


def _build_state_key_timeline(log: str) -> dict[str, list[tuple[str, str]]]:
    """Parse STATE: lines from the log into a key -> [(hook_point, value)] timeline."""
    timeline: dict[str, list[tuple[str, str]]] = {}
    for m in _STATE_TIMELINE_RE.finditer(log):
        body = m.group(1)
        if "=" not in body:
            continue
        eq_idx = body.index("=")
        full_key = body[:eq_idx]
        value = body[eq_idx + 1 :]
        parts = full_key.rsplit(":", 1)
        if len(parts) == 2:
            scope, key = parts[0], parts[1]
        else:
            scope, key = "global", parts[0]
        timeline.setdefault(key, []).append((scope, value))
    return timeline


# ---------------------------------------------------------------------------
# Debug instrumentation env vars
# ---------------------------------------------------------------------------


def _set_debug_instrumentation_env() -> dict[str, str | None]:
    """Set debug instrumentation env vars for the skill_arch_test fixture."""
    saved = {
        "RLM_REPL_TRACE": os.environ.get("RLM_REPL_TRACE"),
        "RLM_REPL_XMODE": os.environ.get("RLM_REPL_XMODE"),
        "RLM_REPL_DEBUG": os.environ.get("RLM_REPL_DEBUG"),
    }
    os.environ["RLM_REPL_TRACE"] = "2"
    os.environ["RLM_REPL_XMODE"] = "Verbose"
    os.environ["RLM_REPL_DEBUG"] = "1"
    return saved


def _restore_debug_instrumentation_env(saved: dict[str, str | None]) -> None:
    """Restore env vars after a debug instrumented run."""
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


# ---------------------------------------------------------------------------
# Main runner function
# ---------------------------------------------------------------------------


async def run_fixture_contract_instrumented(
    fixture_path: Path,
    prompt: str = "test prompt",
    traces_db_path: str | None = None,
    repl_trace_level: int = 1,
    litellm_mode: bool = False,
    tmpdir: str | None = None,
    wire_local_hooks: bool = True,
    wire_test_hooks: bool = False,
    wire_dyn_instr_hook: bool = True,
) -> InstrumentedContractResult:
    """Execute a fixture with full instrumentation.

    Extends run_fixture_contract_with_plugins() with:
    - InstrumentationPlugin added to the plugin list
    - Local callbacks wired on root orchestrator + reasoning_agent
    - Dynamic instruction capture hook
    - Complete stdout capture via TeeWriter
    - State key timeline construction from tagged log lines
    """
    from rlm_adk.plugins.dashboard_events import DashboardEventPlugin
    from rlm_adk.plugins.observability import ObservabilityPlugin
    from rlm_adk.plugins.repl_tracing import REPLTracingPlugin
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
    saved = _save_env()

    local_callback_log: list[str] = []
    instrumentation_plugin = InstrumentationPlugin()

    try:
        base_url = await server.start()
        if litellm_mode:
            _set_env_litellm(base_url, router)
            _setup_litellm_client(base_url)
        else:
            _set_env(base_url, router)
        os.environ["RLM_REPL_TRACE"] = str(repl_trace_level)

        _tmpdir = tmpdir or tempfile.mkdtemp(prefix="provider-fake-instr-")
        session_db_path = str(Path(_tmpdir) / "session.db")
        artifact_root = str(Path(_tmpdir) / "artifacts")

        _traces_db = traces_db_path or str(Path(_tmpdir) / "traces.db")
        _dashboard_jsonl = str(Path(_tmpdir) / "dashboard_events.jsonl")
        plugins: list[BasePlugin] = [
            instrumentation_plugin,
            ObservabilityPlugin(),
            SqliteTracingPlugin(db_path=_traces_db),
            DashboardEventPlugin(output_path=_dashboard_jsonl),
        ]
        if repl_trace_level > 0:
            plugins.append(REPLTracingPlugin())

        repl = _make_repl(router)
        _enabled_skills = router.config.get("enabled_skills") or None
        app = create_rlm_app(
            model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
            thinking_budget=router.config.get("thinking_budget", 0),
            repl=repl,
            plugins=plugins,
            langfuse=False,
            sqlite_tracing=False,
            enabled_skills=_enabled_skills,
        )

        if wire_test_hooks:
            _wire_test_hooks(app)
        if wire_local_hooks:
            _wire_instrumentation_hooks(app, local_callback_log)

        # Chain dyn_instr_capture_hook AFTER the local instrumentation hook
        if wire_dyn_instr_hook:
            reasoning_agent = app.root_agent.reasoning_agent
            _existing_model_cb = reasoning_agent.before_model_callback
            _dyn_hook = make_dyn_instr_capture_hook()

            def _chained_before_model(callback_context, llm_request):
                # 1. Existing hook (instrumentation + original reasoning cb)
                result = None
                if _existing_model_cb:
                    result = _existing_model_cb(
                        callback_context=callback_context, llm_request=llm_request
                    )
                    if result is not None:
                        return result
                # 2. Dynamic instruction capture hook
                return _dyn_hook(callback_context, llm_request)

            object.__setattr__(reasoning_agent, "before_model_callback", _chained_before_model)

        session_service = _default_session_service(db_path=session_db_path)
        artifact_service = FileArtifactService(root_dir=artifact_root)
        runner = Runner(
            app=app,
            session_service=session_service,
            artifact_service=artifact_service,
        )

        initial_state = router.config.get("initial_state") or None
        session = await session_service.create_session(
            app_name="rlm_adk",
            user_id="test-user",
            state=initial_state,
        )

        t0 = time.monotonic()
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
        events: list[Any] = []

        with _capture_stdout() as captured:
            async for event in runner.run_async(
                user_id="test-user",
                session_id=session.id,
                new_message=content,
            ):
                events.append(event)
        repl_stdout = captured.getvalue()

        elapsed = time.monotonic() - t0
        final_session = await runner.session_service.get_session(
            app_name="rlm_adk",
            user_id="test-user",
            session_id=session.id,
        )
        final_state = final_session.state if final_session else {}

        contract = router.check_expectations(
            final_state,
            fixture_path,
            elapsed,
            events=events,
            litellm_mode=litellm_mode,
        )

        # Merge local callback log + REPL internal stdout into instrumentation log.
        # The TeeWriter captures system stdout (plugin/callback tags), but
        # REPL output (TEST_SKILL, DYN_INSTR tags from skill code) is captured
        # separately in last_repl_result['stdout'].  Include it so the
        # stdout_parser sees all tagged lines.
        #
        # Multi-turn fix: accumulate stdout from ALL events with state_delta
        # containing last_repl_result, not just the final state (which only
        # has the last turn's result).
        _all_repl_stdouts: list[str] = []
        for ev in events:
            if not hasattr(ev, "actions") or not ev.actions:
                continue
            sd = getattr(ev.actions, "state_delta", None)
            if not sd or not isinstance(sd, dict):
                continue
            lrr = sd.get("last_repl_result")
            if isinstance(lrr, dict):
                s = lrr.get("stdout", "")
                if s:
                    _all_repl_stdouts.append(s)
        _repl_internal_stdout = "\n".join(_all_repl_stdouts)
        _plugin_log = "\n".join(instrumentation_plugin._log_lines)
        full_log = (
            repl_stdout
            + "\n"
            + "\n".join(local_callback_log)
            + "\n"
            + _repl_internal_stdout
            + "\n"
            + _plugin_log
        )
        state_timeline = _build_state_key_timeline(full_log)

        plugin_result = PluginContractResult(
            contract=contract,
            events=events,
            final_state=final_state,
            artifact_service=artifact_service,
            traces_db_path=_traces_db,
            session_db_path=session_db_path,
            artifact_root=artifact_root,
            router=router,
        )
        return InstrumentedContractResult(
            plugin_result=plugin_result,
            instrumentation_log=full_log,
            local_callback_log=local_callback_log,
            repl_stdout=repl_stdout,
            state_key_timeline=state_timeline,
        )
    finally:
        await server.stop()
        if litellm_mode:
            _teardown_litellm_client()
        _restore_env(saved)
