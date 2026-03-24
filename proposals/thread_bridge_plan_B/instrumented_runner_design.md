# Instrumented Contract Runner Design

**Author**: Callbacks-Expert Agent
**Date**: 2026-03-24
**Status**: Design Plan (not yet implemented)

---

## Overview

This document designs a NEW instrumented contract runner that captures the complete architecture state key and variable lineage from start to end of a fixture run. It builds on `run_fixture_contract_with_plugins()` without replacing it, adding:

1. An `InstrumentationPlugin(BasePlugin)` that fires for ALL agents (including child orchestrators)
2. Local callback wiring on the root orchestrator and reasoning_agent
3. Stdout capture via `io.StringIO` + `contextlib.redirect_stdout`
4. A new `InstrumentedContractResult` return type that includes the full instrumentation log

---

## 1. Complete `InstrumentationPlugin` Code

```python
"""InstrumentationPlugin — full callback coverage for architecture introspection tests.

Fires for ALL agents in the invocation tree (root + child orchestrators + workers).
All output uses tagged format consistent with test_skill.py tagged lines.
Observe-only: never returns a value, never blocks execution.
"""

import time
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types


class InstrumentationPlugin(BasePlugin):
    """Captures complete state key and variable lineage across all agents.

    All output uses tagged format:
    - [PLUGIN:hook:agent_name:key=value] for plugin-level data
    - [STATE:key=value] for state snapshots at each callback point
    - [TIMING:label=ms] for timing data

    Observe-only: never returns a value, never blocks execution.
    All errors are caught and suppressed.
    """

    def __init__(self, *, name: str = "instrumentation"):
        super().__init__(name=name)
        self._tool_start_times: dict[str, float] = {}
        self._agent_start_times: dict[str, float] = {}
        self._model_start_times: dict[str, float] = {}
        self._call_counter: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, hook: str, agent_name: str, **kwargs) -> None:
        """Emit a [PLUGIN:hook:agent_name:key=value] line to stdout."""
        for key, value in kwargs.items():
            print(f"[PLUGIN:{hook}:{agent_name}:{key}={value}]", flush=True)

    def _emit_state(self, state: Any, prefix: str = "") -> None:
        """Emit [STATE:key=value] lines for a subset of curated state keys."""
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
                # Truncate large values
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "...[truncated]"
                print(f"[STATE:{tag}={val_str}]", flush=True)

    def _agent_key(self, agent: BaseAgent, callback_context: CallbackContext) -> str:
        """Build a unique agent key for timing dict."""
        agent_name = getattr(agent, "name", "unknown")
        inv_id = getattr(callback_context, "invocation_id", "?")
        return f"{agent_name}#{inv_id}"

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

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

            self._emit("before_agent", agent_name,
                       depth=depth, fanout_idx=fanout,
                       agent_type=type(agent).__name__)
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

            self._emit("after_agent", agent_name,
                       depth=getattr(agent, "_rlm_depth", 0),
                       elapsed_ms=elapsed_ms)
            self._emit_state(callback_context.state, prefix="after_agent:")
            print(f"[TIMING:agent_{agent_name}_ms={elapsed_ms}]", flush=True)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        try:
            self._call_counter += 1
            call_num = self._call_counter
            inv_id = getattr(callback_context, "invocation_id", "?")
            agent_name = callback_context.agent_name
            depth = callback_context.state.get("current_depth", 0)

            # Capture model name and system instruction length
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

            self._emit("before_model", agent_name,
                       call_num=call_num,
                       model=model,
                       depth=depth,
                       sys_instr_len=sys_instr_len,
                       contents_count=contents_count,
                       tools_count=tools_count)

            # Emit curated state keys visible at model call time
            iter_count = callback_context.state.get("iteration_count", 0)
            should_stop = callback_context.state.get("should_stop", False)
            repl_did_expand = callback_context.state.get("repl_did_expand", False)
            print(f"[STATE:model_call_{call_num}:iteration_count={iter_count}]", flush=True)
            print(f"[STATE:model_call_{call_num}:should_stop={should_stop}]", flush=True)
            print(f"[STATE:model_call_{call_num}:repl_did_expand={repl_did_expand}]", flush=True)
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
                finish_reason = getattr(llm_response.finish_reason, "name", str(llm_response.finish_reason))

            # Count function calls in response
            func_calls = 0
            if llm_response.content and llm_response.content.parts:
                func_calls = sum(
                    1 for p in llm_response.content.parts
                    if hasattr(p, "function_call") and p.function_call is not None
                )

            input_tokens = 0
            output_tokens = 0
            if llm_response.usage_metadata:
                input_tokens = getattr(llm_response.usage_metadata, "prompt_token_count", 0) or 0
                output_tokens = getattr(llm_response.usage_metadata, "candidates_token_count", 0) or 0

            self._emit("after_model", agent_name,
                       call_num=call_num,
                       finish_reason=finish_reason,
                       func_calls=func_calls,
                       input_tokens=input_tokens,
                       output_tokens=output_tokens,
                       elapsed_ms=elapsed_ms)
            print(f"[TIMING:model_call_{call_num}_ms={elapsed_ms}]", flush=True)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Tool lifecycle
    # ------------------------------------------------------------------

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
            depth = tool_context.state.get("current_depth", 0)
            iter_count = tool_context.state.get("iteration_count", 0)

            # For execute_code: capture code preview (first 120 chars)
            code_preview = ""
            if tool_name == "execute_code" and "code" in tool_args:
                code_preview = str(tool_args["code"])[:120].replace("\n", "\\n")

            tk = f"{tool_name}#{agent_name}"
            self._tool_start_times[tk] = time.monotonic()

            self._emit("before_tool", agent_name,
                       tool_name=tool_name,
                       depth=depth,
                       iteration_count=iter_count,
                       code_preview=repr(code_preview) if code_preview else "n/a")

            # Emit full curated state snapshot before tool execution
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

            # Capture result preview
            result_preview = str(result)[:120] if result else "empty"

            self._emit("after_tool", agent_name,
                       tool_name=tool_name,
                       elapsed_ms=elapsed_ms,
                       result_preview=repr(result_preview))

            # Emit state delta after tool execution — key lineage point
            self._emit_state(tool_context.state, prefix="post_tool:")
            print(f"[TIMING:tool_{tool_name}_ms={elapsed_ms}]", flush=True)
        except Exception:
            pass
        return None
```

---

## 2. Local Callback Wiring Code

The plugin above fires for ALL agents via the Runner plugin list. For additional
local callbacks on the root orchestrator and reasoning_agent specifically, we chain
onto the existing `_wire_test_hooks()` pattern:

```python
def _wire_instrumentation_hooks(
    app: Any,
    log_lines: list[str],
) -> None:
    """Wire local instrumentation callbacks onto root orchestrator + reasoning_agent.

    These supplement the InstrumentationPlugin (which fires for all agents).
    Local hooks have access to agent-internal attrs (_rlm_depth, _rlm_fanout_idx,
    _rlm_pending_request_meta, _rlm_last_response_meta) not visible from plugins.

    The log_lines list is shared by reference — callbacks append to it directly.
    This avoids stdout capture complexity for local hook output.
    """
    orchestrator = app.root_agent
    reasoning_agent = orchestrator.reasoning_agent

    # --- Orchestrator before_agent: log initial state keys + agent attrs ---
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

    # --- Orchestrator after_agent: log final state diff ---
    def _instr_orch_after(callback_context):
        try:
            final_keys = sorted(callback_context.state.to_dict().keys())
            log_lines.append(
                f"[CALLBACK:after_agent:rlm_orchestrator:final_state_key_count={len(final_keys)}]"
            )
            # Capture the specific lineage keys we care about
            state = callback_context.state
            for key in (
                "current_depth", "iteration_count", "should_stop",
                "final_response_text", "repl_did_expand", "repl_skill_expansion_meta",
                "obs:rewrite_count", "obs:rewrite_total_ms",
            ):
                val = state.get(key)
                if val is not None:
                    log_lines.append(f"[CALLBACK:after_agent:rlm_orchestrator:{key}={val}]")
        except Exception:
            pass
        return None

    object.__setattr__(orchestrator, "after_agent_callback", _instr_orch_after)

    # --- Reasoning agent before_model: log every LLM request with depth + lineage attrs ---
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
            return original_reasoning_before(callback_context=callback_context, llm_request=llm_request)
        return None

    object.__setattr__(reasoning_agent, "before_model_callback", _instr_reasoning_before_model)

    # --- Reasoning agent after_model: log finish reason + token counts ---
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
            return original_reasoning_after(callback_context=callback_context, llm_response=llm_response)
        return None

    object.__setattr__(reasoning_agent, "after_model_callback", _instr_reasoning_after_model)

    # --- Reasoning agent before_tool: snapshot state before execute_code ---
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
            # Full state snapshot before tool (all curated keys)
            from rlm_adk.state import CURATED_STATE_KEYS, CURATED_STATE_PREFIXES
            for key, val in state.to_dict().items():
                base = key.split("@")[0]
                if base in CURATED_STATE_KEYS or any(base.startswith(p) for p in CURATED_STATE_PREFIXES):
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

    # --- Reasoning agent after_tool: capture state delta ---
    original_after_tool = getattr(reasoning_agent, "after_tool_callback", None)

    def _instr_after_tool(tool, args, tool_context, tool_response):
        try:
            tool_name = getattr(tool, "name", str(tool))
            state = tool_context.state
            log_lines.append(
                f"[CALLBACK:after_tool:reasoning_agent:tool={tool_name}]"
            )
            # State delta post-execution (all curated keys including depth-scoped)
            from rlm_adk.state import CURATED_STATE_KEYS, CURATED_STATE_PREFIXES
            for key, val in state.to_dict().items():
                base = key.split("@")[0]
                if base in CURATED_STATE_KEYS or any(base.startswith(p) for p in CURATED_STATE_PREFIXES):
                    val_str = str(val)
                    if len(val_str) > 200:
                        val_str = val_str[:200] + "...[truncated]"
                    log_lines.append(f"[STATE:post_tool:{key}={val_str}]")
        except Exception:
            pass
        if original_after_tool:
            return original_after_tool(tool, args, tool_context, tool_response)
        return None

    object.__setattr__(reasoning_agent, "after_tool_callback", _instr_after_tool)
```

**Critical notes on wiring:**
- The orchestrator's `before_agent_callback` and `after_agent_callback` are set here BEFORE the runner
  starts, but `orchestrator.py`'s `_run_async_impl` may overwrite `before_agent_callback` at runtime
  (line 401–405) when `instruction_router` is set. Our chain must run AFTER that instruction seeding.
  To handle this: the `_seed_skill_instruction` closure in orchestrator.py runs at `_run_async_impl`
  startup and calls our wrapper, which calls the original. The wiring order in `_wire_instrumentation_hooks`
  must capture the pre-existing callback first and wrap it — which the code above does correctly.
- The `after_tool_callback` on reasoning_agent is set by `make_worker_tool_callbacks()` inside
  `_run_async_impl` (line 363). Our local hook is set at app-creation time and will be OVERWRITTEN
  by orchestrator's runtime wiring. **Resolution**: Do NOT wire `after_tool_callback` as a local hook
  — rely on `InstrumentationPlugin.after_tool_callback` instead (plugins take precedence over agent
  callbacks and cannot be overwritten at runtime). The local `before_tool_callback` is safe because
  orchestrator does not overwrite it.

---

## 3. Runner Function Signature and Integration

```python
@dataclasses.dataclass
class InstrumentedContractResult:
    """Enriched result from an instrumented fixture run."""

    plugin_result: PluginContractResult
    instrumentation_log: str         # Complete tagged log: PLUGIN + CALLBACK + STATE + TIMING lines
    local_callback_log: list[str]    # Lines from local callbacks (not captured via stdout redirect)
    repl_stdout: str                 # Raw stdout captured during the run (TEST_SKILL + PLUGIN lines)
    state_key_timeline: dict[str, list[tuple[str, Any]]]
    # Maps state key → list of (hook_point, value) tuples showing full lifecycle.
    # e.g. "iteration_count" → [("before_agent", 0), ("after_tool:execute_code", 1), ...]


async def run_fixture_contract_instrumented(
    fixture_path: Path,
    prompt: str = "test prompt",
    traces_db_path: str | None = None,
    repl_trace_level: int = 1,
    litellm_mode: bool = False,
    tmpdir: str | None = None,
    wire_local_hooks: bool = True,
    wire_test_hooks: bool = False,
) -> InstrumentedContractResult:
    """Execute a fixture with full instrumentation: plugin + local callbacks + stdout capture.

    Extends run_fixture_contract_with_plugins() with:
    - InstrumentationPlugin added to the plugin list
    - Local callbacks wired on root orchestrator + reasoning_agent (if wire_local_hooks=True)
    - Complete stdout capture via io.StringIO + contextlib.redirect_stdout
    - State key timeline construction from tagged log lines

    The InstrumentationPlugin fires for ALL agents (root + children).
    Local hooks fire only for root orchestrator + reasoning_agent.

    Args:
        fixture_path: Path to the fixture JSON file.
        prompt: User prompt to send to the runner.
        traces_db_path: Path for SqliteTracingPlugin DB. None disables sqlite tracing.
        repl_trace_level: RLM_REPL_TRACE env var value (0 = off).
        litellm_mode: When True, route via LiteLLM Router.
        tmpdir: Directory for session DB and artifact files.
        wire_local_hooks: Whether to also wire local callbacks on root orchestrator +
            reasoning_agent. Default True. Disable to test plugin-only coverage.
        wire_test_hooks: Whether to also wire test_hooks (CB_REASONING_CONTEXT etc).
            Useful when combining instrumentation with state hook verification.

    Returns:
        InstrumentedContractResult with full log, timeline, and underlying PluginContractResult.
    """
    ...
```

### Integration with existing infra

The runner **does not replace** `run_fixture_contract_with_plugins`. It wraps it with three additions:

1. **InstrumentationPlugin** is appended to `extra_plugins` before the call.
2. **Local hooks** are wired via `_wire_instrumentation_hooks()` which is called after `create_rlm_app()`
   but before the runner starts (same timing as `_wire_test_hooks()`).
3. **Stdout capture** wraps the entire `run_fixture_contract_with_plugins()` call.

Because `run_fixture_contract_with_plugins()` already accepts `extra_plugins`, the instrumentation plugin
slots in cleanly. The local hooks require access to the `app` object, which means we need to replicate
the app-creation logic from `run_fixture_contract_with_plugins` rather than calling it as a black box.
The cleanest approach is to call the existing function with `extra_plugins=[InstrumentationPlugin()]` for
the plugin path, and separately build the app to wire local hooks if needed.

**Pragmatic resolution**: restructure as a thin wrapper that monkey-patches the `create_rlm_app` call
inside `run_fixture_contract_with_plugins` — but this is brittle. Instead, the runner should inline the
necessary setup and call the underlying machinery directly. See full implementation in Section 6.

---

## 4. Stdout Format Specification

### Format categories

| Prefix | Source | Purpose |
|--------|--------|---------|
| `[PLUGIN:hook:agent:key=value]` | `InstrumentationPlugin` | Per-callback structured data |
| `[CALLBACK:hook:agent:key=value]` | Local callbacks | Root-agent-specific data with agent attrs |
| `[STATE:scope:key=value]` | Both | State key values at specific hook points |
| `[TIMING:label=ms]` | Both | Elapsed milliseconds for labeled operations |
| `[TEST_SKILL:key=value]` | test_skill.py | Skill-internal diagnostic lines |
| `[RLM:...]` | orchestrator.py | Orchestrator-internal print statements |

### Example stdout from a skill_arch_test run

```
[PLUGIN:before_agent:rlm_orchestrator:depth=0]
[PLUGIN:before_agent:rlm_orchestrator:fanout_idx=0]
[PLUGIN:before_agent:rlm_orchestrator:agent_type=RLMOrchestratorAgent]
[CALLBACK:before_agent:rlm_orchestrator:state_key_count=0]
[CALLBACK:before_agent:rlm_orchestrator:initial_state_keys=[]]
[PLUGIN:before_model:reasoning_agent:call_num=1]
[PLUGIN:before_model:reasoning_agent:model=gemini-fake]
[PLUGIN:before_model:reasoning_agent:depth=0]
[PLUGIN:before_model:reasoning_agent:sys_instr_len=2847]
[PLUGIN:before_model:reasoning_agent:contents_count=1]
[PLUGIN:before_model:reasoning_agent:tools_count=2]
[STATE:model_call_1:iteration_count=0]
[STATE:model_call_1:should_stop=False]
[STATE:model_call_1:repl_did_expand=False]
[CALLBACK:before_model:reasoning_agent:depth=0,fanout=0,iteration=0]
[PLUGIN:before_tool:reasoning_agent:tool_name=execute_code]
[PLUGIN:before_tool:reasoning_agent:depth=0]
[PLUGIN:before_tool:reasoning_agent:iteration_count=0]
[PLUGIN:before_tool:reasoning_agent:code_preview='from rlm_repl_skills.test_skill import run_test_skill\n\nresult = run_test_skill(']
[STATE:pre_tool:iteration_count=0]
[STATE:pre_tool:current_depth=0]
[STATE:pre_tool:should_stop=False]
[CALLBACK:before_tool:reasoning_agent:tool=execute_code,iter=0,depth=0]
[TEST_SKILL:depth=0]
[TEST_SKILL:rlm_agent_name=reasoning_agent]
[TEST_SKILL:iteration_count=0]
[TEST_SKILL:current_depth=0]
[TEST_SKILL:should_stop=False]
[TEST_SKILL:state_keys_count=7]
[TEST_SKILL:repl_globals_count=12]
[TEST_SKILL:llm_query_type=function]
[TEST_SKILL:execution_mode=async_rewrite]
[TEST_SKILL:calling_llm_query=True]
[PLUGIN:before_agent:reasoning_agent:depth=1]
[PLUGIN:before_agent:reasoning_agent:agent_type=LlmAgent]
[PLUGIN:before_model:reasoning_agent:call_num=2]
[PLUGIN:before_model:reasoning_agent:depth=1]
[PLUGIN:after_model:reasoning_agent:call_num=2]
[PLUGIN:after_model:reasoning_agent:finish_reason=STOP]
[PLUGIN:after_model:reasoning_agent:func_calls=1]
[PLUGIN:after_agent:reasoning_agent:depth=1]
[TIMING:agent_reasoning_agent_ms=12.4]
[TEST_SKILL:child_result_preview=arch_test_ok]
[TEST_SKILL:thread_bridge_latency_ms=45.23]
[TEST_SKILL:COMPLETE=True]
[TEST_SKILL:summary=depth=0 mode=async_rewrite latency_ms=45.2 child_ok=True]
[PLUGIN:after_tool:reasoning_agent:tool_name=execute_code]
[PLUGIN:after_tool:reasoning_agent:elapsed_ms=67.1]
[STATE:post_tool:iteration_count=1]
[STATE:post_tool:current_depth=0]
[STATE:post_tool:repl_did_expand=True]
[STATE:post_tool:repl_skill_expansion_meta={'symbols': ['TestSkillResult', 'run_test_skill'], 'modules': ['rlm_repl_skills.test_skill']}]
[STATE:post_tool:last_repl_result=stdout_preview:..., llm_calls:1]
[TIMING:tool_execute_code_ms=67.1]
[PLUGIN:before_model:reasoning_agent:call_num=3]
[PLUGIN:after_model:reasoning_agent:call_num=3]
[PLUGIN:after_model:reasoning_agent:finish_reason=STOP]
[PLUGIN:after_model:reasoning_agent:func_calls=1]
[PLUGIN:before_tool:reasoning_agent:tool_name=set_model_response]
[PLUGIN:after_tool:reasoning_agent:tool_name=set_model_response]
[PLUGIN:after_agent:rlm_orchestrator:depth=0]
[PLUGIN:after_agent:rlm_orchestrator:elapsed_ms=312.7]
[STATE:after_agent:final_response_text=Architecture test complete...]
[STATE:after_agent:iteration_count=1]
[CALLBACK:after_agent:rlm_orchestrator:final_state_key_count=18]
[CALLBACK:after_agent:rlm_orchestrator:repl_did_expand=True]
[TIMING:agent_rlm_orchestrator_ms=312.7]
[RLM] FINAL_RESPONSE_TEXT detected length=74
```

### Key assertions for test code

```python
def parse_instrumentation_tags(log: str) -> dict[str, list[str]]:
    """Parse tagged log into dict[tag_prefix → list of values]."""
    import re
    result: dict[str, list[str]] = {}
    pattern = re.compile(r"\[(PLUGIN|CALLBACK|STATE|TIMING|TEST_SKILL):([^\]]+)\]")
    for m in pattern.finditer(log):
        prefix = m.group(1)
        body = m.group(2)
        result.setdefault(prefix, []).append(body)
    return result

# Example assertions:
tags = parse_instrumentation_tags(result.instrumentation_log)

# Plugin fired for all agents including child
plugin_lines = tags["PLUGIN"]
assert any("before_agent:rlm_orchestrator" in l for l in plugin_lines)
assert any("before_agent:reasoning_agent" in l for l in plugin_lines)

# State lineage: repl_did_expand transitioned to True
state_lines = tags["STATE"]
pre_tool_expand = [l for l in state_lines if "pre_tool:repl_did_expand" in l]
post_tool_expand = [l for l in state_lines if "post_tool:repl_did_expand" in l]
assert any("False" in l for l in pre_tool_expand)
assert any("True" in l for l in post_tool_expand)

# Timing: all labeled timings are present and positive
timing_lines = tags["TIMING"]
assert any(l.startswith("tool_execute_code_ms=") for l in timing_lines)
```

---

## 5. Stdout Capture Implementation

```python
import contextlib
import io
import sys

@contextlib.contextmanager
def _capture_stdout():
    """Capture all stdout to a string buffer while also writing to real stdout.

    Uses io.StringIO as a tee: captured buffer receives all output, and
    the original stdout receives it too for test visibility.
    """
    captured = io.StringIO()
    original_stdout = sys.stdout

    class TeeWriter:
        def write(self, text):
            captured.write(text)
            original_stdout.write(text)
        def flush(self):
            captured.flush()
            original_stdout.flush()
        def fileno(self):
            return original_stdout.fileno()

    sys.stdout = TeeWriter()
    try:
        yield captured
    finally:
        sys.stdout = original_stdout


# Usage in the runner:
with _capture_stdout() as captured:
    plugin_result = await run_fixture_contract_with_plugins(
        fixture_path,
        prompt=prompt,
        traces_db_path=traces_db_path,
        repl_trace_level=repl_trace_level,
        litellm_mode=litellm_mode,
        tmpdir=tmpdir,
        extra_plugins=[instrumentation_plugin],
    )
repl_stdout = captured.getvalue()
```

**Note on thread safety**: The orchestrator runs in the asyncio event loop, but child
dispatch can run `run_in_executor` coroutines. The `TeeWriter` uses `sys.stdout` assignment
which is process-global. In the current AST-rewriter path this is safe (no threads). After
the thread bridge lands, stdout capture may require `threading.local()` or per-thread capture.
For the current design (AST-rewriter mode), `contextlib.redirect_stdout` + `io.StringIO` is
simpler and avoids the tee complexity if real-time output is not required:

```python
# Simpler alternative (no tee — output not visible during test):
with contextlib.redirect_stdout(io.StringIO()) as captured:
    plugin_result = await run_fixture_contract_with_plugins(...)
repl_stdout = captured.getvalue()
```

Use the `TeeWriter` approach when debugging; use `redirect_stdout` for CI.

---

## 6. Return Type and State Key Timeline Construction

```python
@dataclasses.dataclass
class InstrumentedContractResult:
    """Complete result from run_fixture_contract_instrumented()."""

    plugin_result: PluginContractResult
    """Underlying PluginContractResult from run_fixture_contract_with_plugins()."""

    instrumentation_log: str
    """Complete stdout captured during the run. Contains all tagged lines from:
    - InstrumentationPlugin (PLUGIN: prefix)
    - Local callbacks (CALLBACK: prefix)
    - test_skill.py print statements (TEST_SKILL: prefix)
    - orchestrator.py print statements (RLM: prefix)
    - STATE: and TIMING: lines from both sources.
    """

    local_callback_log: list[str]
    """Lines appended by local callbacks (not captured via stdout — written to shared list)."""

    repl_stdout: str
    """Alias for instrumentation_log (same buffer; both are the full captured stdout)."""

    state_key_timeline: dict[str, list[tuple[str, Any]]]
    """Lifecycle of each state key: key → [(hook_point, value), ...].

    Constructed by scanning STATE: lines in instrumentation_log.
    Example:
        "iteration_count": [
            ("pre_tool:execute_code", "0"),
            ("post_tool:execute_code", "1"),
        ]
    """

    @property
    def passed(self) -> bool:
        return self.plugin_result.contract.passed

    def diagnostics(self) -> str:
        return self.plugin_result.contract.diagnostics()


def _build_state_key_timeline(log: str) -> dict[str, list[tuple[str, str]]]:
    """Parse STATE: lines from the log into a key → [(hook_point, value)] timeline."""
    import re
    timeline: dict[str, list[tuple[str, str]]] = {}
    # Match [STATE:scope:key=value] or [STATE:key=value]
    pattern = re.compile(r"\[STATE:([^\]]+)\]")
    for m in pattern.finditer(log):
        body = m.group(1)
        # body is either "scope:key=value" or "key=value"
        if "=" not in body:
            continue
        eq_idx = body.index("=")
        full_key = body[:eq_idx]
        value = body[eq_idx + 1:]
        # Split scope from key
        parts = full_key.rsplit(":", 1)
        if len(parts) == 2:
            scope, key = parts[0], parts[1]
        else:
            scope, key = "global", parts[0]
        timeline.setdefault(key, []).append((scope, value))
    return timeline
```

---

## 7. Key Design Decisions

### Decision 1: Plugin for global coverage, local hooks for root-agent depth

`InstrumentationPlugin` fires for every agent in the tree (orchestrator, reasoning_agent,
child orchestrators spawned by dispatch.py). This gives visibility into child dispatch.
Local callbacks are added only for the root orchestrator and root reasoning_agent to capture
agent-internal attrs (`_rlm_depth`, `_rlm_last_response_meta`, `_rlm_pending_request_meta`)
that are not accessible from the plugin's `callback_context`.

### Decision 2: Separate `log_lines` list for local callbacks

Local callbacks write to a `list[str]` passed by reference rather than printing to stdout.
This keeps local callback output separate from plugin + skill output, making it easier to
distinguish sources when debugging. The two are merged in `InstrumentedContractResult`:
`instrumentation_log` = stdout (plugin + skill), `local_callback_log` = list (local hooks).

### Decision 3: `after_tool_callback` on reasoning_agent NOT wired locally

The orchestrator's `_run_async_impl` calls `make_worker_tool_callbacks()` which overwrites
`reasoning_agent.after_tool_callback` at runtime (line 363 of orchestrator.py). Any local
hook wired at app-creation time will be overwritten. The `InstrumentationPlugin.after_tool_callback`
is immune to this because plugins are invoked by the Runner's plugin manager, not via agent
attrs. Therefore after-tool state capture relies entirely on the plugin.

### Decision 4: TeeWriter for stdout capture (not redirect_stdout only)

`contextlib.redirect_stdout` alone makes test output invisible during runs. The `TeeWriter`
approach sends output to both the captured buffer and the original stdout, giving real-time
visibility during development. In CI, switch to `redirect_stdout` for cleaner output.

### Decision 5: State key timeline from log parsing, not real-time accumulation

The timeline is constructed post-run by scanning `STATE:` lines in the captured log rather
than accumulating state diffs in real time during callbacks. This is simpler (no shared mutable
state between async callbacks) and sufficient for test assertions (ordering is preserved in log
output order).

### Decision 6: `extra_plugins` parameter on existing runner

`run_fixture_contract_with_plugins()` already has an `extra_plugins` parameter (line 367 of
contract_runner.py). The `InstrumentationPlugin` slots in via this parameter, so we do NOT
need to fork or replicate the runner. The local hook wiring requires access to the `app` object
which means we need a thin wrapper that creates the app, wires hooks, then calls the runner with
the pre-wired app. This is achieved by reusing `create_rlm_app()` directly.

---

## 8. Complete Runner Function (Skeleton)

```python
async def run_fixture_contract_instrumented(
    fixture_path: Path,
    prompt: str = "test prompt",
    traces_db_path: str | None = None,
    repl_trace_level: int = 1,
    litellm_mode: bool = False,
    tmpdir: str | None = None,
    wire_local_hooks: bool = True,
    wire_test_hooks: bool = False,
) -> InstrumentedContractResult:
    from tests_rlm_adk.provider_fake.contract_runner import (
        PluginContractResult,
        _make_runner_and_session,
        _restore_env,
        _run_to_completion,
        _save_env,
        _set_env,
        _set_env_litellm,
        _setup_litellm_client,
        _teardown_litellm_client,
    )
    from tests_rlm_adk.provider_fake.fixtures import ContractResult, ScenarioRouter
    from tests_rlm_adk.provider_fake.server import FakeGeminiServer

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

        # Build plugins list (instrumentation plugin first so it fires before others)
        from rlm_adk.plugins.observability import ObservabilityPlugin
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        _traces_db = traces_db_path or str(Path(_tmpdir) / "traces.db")
        plugins = [
            instrumentation_plugin,
            ObservabilityPlugin(),
            SqliteTracingPlugin(db_path=_traces_db),
        ]

        # Create app with local hook wiring
        repl = _make_repl(router)
        app = create_rlm_app(
            model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
            thinking_budget=router.config.get("thinking_budget", 0),
            repl=repl,
            langfuse=False,
            sqlite_tracing=False,
        )

        if wire_test_hooks:
            _wire_test_hooks(app)
        if wire_local_hooks:
            _wire_instrumentation_hooks(app, local_callback_log)

        session_service = _default_session_service(db_path=session_db_path)
        artifact_service = FileArtifactService(root_dir=artifact_root)
        runner = Runner(app=app, session_service=session_service,
                        artifact_service=artifact_service)

        initial_state = router.config.get("initial_state") or None
        session = await session_service.create_session(
            app_name="rlm_adk", user_id="test-user", state=initial_state,
        )

        # Run with stdout capture
        import contextlib, io, time as _time
        t0 = _time.monotonic()
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        events = []

        with contextlib.redirect_stdout(io.StringIO()) as _captured:
            async for event in runner.run_async(
                user_id="test-user", session_id=session.id, new_message=content,
            ):
                events.append(event)
        repl_stdout = _captured.getvalue()

        elapsed = _time.monotonic() - t0
        final_session = await runner.session_service.get_session(
            app_name="rlm_adk", user_id="test-user", session_id=session.id,
        )
        final_state = final_session.state if final_session else {}

        contract = router.check_expectations(
            final_state, fixture_path, elapsed, events=events, litellm_mode=litellm_mode,
        )

        # Merge local callback log into instrumentation log
        full_log = repl_stdout + "\n".join(local_callback_log)
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
```

---

## 9. Files to Create

| File | Action |
|------|--------|
| `tests_rlm_adk/provider_fake/instrumented_runner.py` | **Create** — `InstrumentationPlugin`, `_wire_instrumentation_hooks()`, `InstrumentedContractResult`, `run_fixture_contract_instrumented()` |
| `tests_rlm_adk/test_skill_arch_e2e.py` | **Create** (by separate agent per task scope) — uses `run_fixture_contract_instrumented()` and asserts on tagged output |

The implementation should live in `tests_rlm_adk/provider_fake/instrumented_runner.py` and import
from `contract_runner.py` for the helpers it needs.
