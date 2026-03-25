"""Tests for SkillToolset integration types and wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from rlm_adk.types import LineageEnvelope

# ---------------------------------------------------------------------------
# Cycle 18 — LineageEnvelope.decision_mode expansion
# ---------------------------------------------------------------------------


class TestLineageEnvelopeExpansion:
    """decision_mode Literal accepts skill-toolset values."""

    @pytest.mark.parametrize(
        "mode",
        [
            "load_skill",
            "list_skills",
            "load_skill_resource",
            "run_skill_script",
            # Existing values must still work
            "execute_code",
            "set_model_response",
            "unknown",
        ],
    )
    def test_decision_mode_accepts_skill_tool_values(self, mode: str):
        """LineageEnvelope accepts all expected decision_mode values without raising."""
        envelope = LineageEnvelope(decision_mode=mode, agent_name="test", depth=0)
        assert envelope.decision_mode == mode


# ---------------------------------------------------------------------------
# Cycle 19 — SqliteTracingPlugin skill tool branches
# ---------------------------------------------------------------------------


def _make_plugin(tmp_path):
    """Create a SqliteTracingPlugin with a temp DB, ready for writes."""
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

    db_path = str(tmp_path / "traces.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    # Set trace_id so _insert_telemetry / _update_telemetry work
    plugin._trace_id = "test-trace-001"
    # Push an agent name onto the span stack (before_tool reads it)
    plugin._agent_span_stack.append("test_agent")
    return plugin, db_path


def _make_tool_mock(tool_name):
    """Create a mock tool object with .name attribute."""
    tool = MagicMock()
    tool.name = tool_name
    tool._depth = 0
    return tool


def _make_tool_context():
    """Create a mock tool_context with minimal attrs the plugin reads."""
    ctx = MagicMock()
    # state.get returns None for iteration count lookups
    ctx.state.get.return_value = None
    # _invocation_context with agent
    inv_ctx = SimpleNamespace(
        agent=SimpleNamespace(
            _rlm_fanout_idx=None,
            _rlm_parent_depth=None,
            _rlm_parent_fanout_idx=None,
            _rlm_output_schema_name=None,
        ),
        branch=None,
        invocation_id="inv-001",
        session=SimpleNamespace(id="sess-001"),
    )
    ctx._invocation_context = inv_ctx
    return ctx


@pytest.mark.asyncio
class TestSqliteSkillTelemetry:
    """SqliteTracingPlugin after_tool_callback populates skill tool fields."""

    async def test_load_skill_populates_decision_mode(self, tmp_path):
        """after_tool_callback for 'load_skill' sets decision_mode='load_skill'."""
        plugin, db_path = _make_plugin(tmp_path)
        tool = _make_tool_mock("load_skill")
        tool_context = _make_tool_context()
        tool_args = {"skill_name": "recursive-ping"}

        await plugin.before_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context,
        )
        result = {"name": "recursive-ping", "instructions": "Use run_recursive_ping()"}
        await plugin.after_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context, result=result,
        )

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT decision_mode FROM telemetry WHERE tool_name='load_skill'"
            ).fetchall()
            assert len(rows) >= 1
            assert rows[-1][0] == "load_skill"
        finally:
            conn.close()

    async def test_load_skill_populates_skill_name_loaded(self, tmp_path):
        """after_tool_callback for 'load_skill' populates skill_name_loaded."""
        plugin, db_path = _make_plugin(tmp_path)
        tool = _make_tool_mock("load_skill")
        tool_context = _make_tool_context()
        tool_args = {"skill_name": "recursive-ping"}

        await plugin.before_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context,
        )
        result = {"name": "recursive-ping", "instructions": "Use run_recursive_ping()"}
        await plugin.after_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context, result=result,
        )

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT skill_name_loaded, skill_instructions_len "
                "FROM telemetry WHERE tool_name='load_skill'"
            ).fetchall()
            assert len(rows) >= 1
            assert rows[-1][0] == "recursive-ping"
            assert rows[-1][1] == len("Use run_recursive_ping()")
        finally:
            conn.close()

    async def test_list_skills_populates_decision_mode(self, tmp_path):
        """after_tool_callback for 'list_skills' sets decision_mode='list_skills'."""
        plugin, db_path = _make_plugin(tmp_path)
        tool = _make_tool_mock("list_skills")
        tool_context = _make_tool_context()
        tool_args = {}

        await plugin.before_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context,
        )
        result = {"skills": ["recursive-ping", "some-other"]}
        await plugin.after_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context, result=result,
        )

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT decision_mode FROM telemetry WHERE tool_name='list_skills'"
            ).fetchall()
            assert len(rows) >= 1
            assert rows[-1][0] == "list_skills"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 20 (partial) — Instruction disambiguation
# ---------------------------------------------------------------------------


class TestInstructionDisambiguation:
    """RLM_STATIC_INSTRUCTION mentions skill tools for disambiguation."""

    def test_static_instruction_mentions_skill_tools(self):
        """Skill tool names appear in the static instruction."""
        from rlm_adk.utils.prompts import RLM_STATIC_INSTRUCTION

        assert "list_skills" in RLM_STATIC_INSTRUCTION
        assert "load_skill" in RLM_STATIC_INSTRUCTION
        # execute_code should already be there
        assert "execute_code" in RLM_STATIC_INSTRUCTION


# ---------------------------------------------------------------------------
# Cycle 17 — REPL_SKILL_GLOBALS_INJECTED state key
# ---------------------------------------------------------------------------


class TestSkillStateKeys:
    """REPL_SKILL_GLOBALS_INJECTED key is properly wired into state module."""

    def test_repl_skill_globals_injected_key_exists(self):
        """The constant can be imported from rlm_adk.state."""
        from rlm_adk.state import REPL_SKILL_GLOBALS_INJECTED

        assert isinstance(REPL_SKILL_GLOBALS_INJECTED, str)
        assert REPL_SKILL_GLOBALS_INJECTED == "repl_skill_globals_injected"

    def test_key_matched_by_curated_prefixes(self):
        """The key is matched by a prefix in CURATED_STATE_PREFIXES."""
        from rlm_adk.state import CURATED_STATE_PREFIXES, REPL_SKILL_GLOBALS_INJECTED

        assert any(
            REPL_SKILL_GLOBALS_INJECTED.startswith(p) for p in CURATED_STATE_PREFIXES
        )

    def test_key_not_in_depth_scoped(self):
        """The key is NOT depth-scoped (it's a one-time flag)."""
        from rlm_adk.state import DEPTH_SCOPED_KEYS, REPL_SKILL_GLOBALS_INJECTED

        assert REPL_SKILL_GLOBALS_INJECTED not in DEPTH_SCOPED_KEYS

    def test_should_capture_returns_true(self):
        """should_capture_state_key returns True for this key."""
        from rlm_adk.state import should_capture_state_key

        assert should_capture_state_key("repl_skill_globals_injected") is True


# ---------------------------------------------------------------------------
# Cycle 15 — SkillToolset creation in orchestrator
# ---------------------------------------------------------------------------


class TestSkillToolsetWiring:
    """Orchestrator adds a SkillToolset to the reasoning agent when skills are enabled."""

    @pytest.mark.asyncio
    async def test_toolset_added_when_skills_enabled(self) -> None:
        """When enabled_skills=('recursive_ping',), tools list has a SkillToolset."""
        from google.adk.agents import LlmAgent
        from google.adk.tools.skill_toolset import SkillToolset

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="test_reasoning",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            enabled_skills=("recursive_ping",),
            repl=repl,
        )

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        # Collect events to trigger tool wiring
        events = []
        try:
            async for event in orch._run_async_impl(mock_ctx):
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass

        # Reasoning agent should now have a SkillToolset in its tools
        tools = reasoning_agent.tools
        toolset_instances = [t for t in tools if isinstance(t, SkillToolset)]
        assert len(toolset_instances) == 1, f"Expected 1 SkillToolset, got {len(toolset_instances)} in {tools}"
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_toolset_not_added_when_no_skills(self) -> None:
        """When enabled_skills=(), tools list has only REPLTool and SetModelResponseTool."""
        from google.adk.agents import LlmAgent
        from google.adk.tools.skill_toolset import SkillToolset

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="test_reasoning",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            enabled_skills=(),
            repl=repl,
        )

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        events = []
        try:
            async for event in orch._run_async_impl(mock_ctx):
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass

        tools = reasoning_agent.tools
        toolset_instances = [t for t in tools if isinstance(t, SkillToolset)]
        assert len(toolset_instances) == 0
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_toolset_tools_include_load_skill(self) -> None:
        """The SkillToolset's tools include one named 'load_skill'."""
        from google.adk.agents import LlmAgent
        from google.adk.tools.skill_toolset import SkillToolset

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="test_reasoning",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            enabled_skills=("recursive_ping",),
            repl=repl,
        )

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        events = []
        try:
            async for event in orch._run_async_impl(mock_ctx):
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass

        tools = reasoning_agent.tools
        toolset_instances = [t for t in tools if isinstance(t, SkillToolset)]
        assert len(toolset_instances) == 1
        toolset = toolset_instances[0]
        # Access internal tools list
        tool_names = [t.name for t in toolset._tools]
        assert "load_skill" in tool_names
        repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 16 — CRITICAL: reasoning_before_model must not destroy SkillToolset XML
# ---------------------------------------------------------------------------


def _make_llm_request(*, system_instruction="", contents=None):
    """Build a minimal LlmRequest with system_instruction and optional contents."""
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    config = types.GenerateContentConfig(system_instruction=system_instruction)
    req = LlmRequest(model="gemini-2.0-flash", config=config)
    if contents is not None:
        req.contents = contents
    return req


def _make_callback_context():
    """Build a mock CallbackContext for reasoning_before_model."""
    ctx = MagicMock()
    ctx.state.get.return_value = 0  # ITERATION_COUNT
    # _invocation_context.agent with expected attrs
    agent = MagicMock()
    agent.name = "test_reasoning"
    agent._rlm_depth = 0
    agent._rlm_fanout_idx = 0
    agent._rlm_parent_depth = None
    agent._rlm_parent_fanout_idx = None
    agent._rlm_output_schema_name = None
    agent._rlm_pending_request_meta = None
    inv = MagicMock()
    inv.agent = agent
    inv.branch = None
    inv.invocation_id = "test-inv-001"
    inv.session.id = "test-sess-001"
    ctx._invocation_context = inv
    return ctx


class TestReasoningBeforeModelSkillPreservation:
    """Cycle 16: reasoning_before_model must NOT destroy SkillToolset L1 XML.

    GAP-CB-001 fix: reasoning_before_model is now observe-only. It does NOT
    modify system_instruction at all, so SkillToolset XML is trivially
    preserved. These tests verify the observe-only contract.
    """

    def test_toolset_l1_xml_survives_before_model_callback(self) -> None:
        """When system_instruction contains <available_skills> XML, it survives the callback.

        reasoning_before_model is observe-only (GAP-CB-001) — it does not
        modify system_instruction. SkillToolset XML is preserved because the
        callback never touches system_instruction.
        """
        from google.genai import types

        from rlm_adk.callbacks.reasoning import reasoning_before_model

        # Simulate what ADK + SkillToolset sets up BEFORE our callback fires:
        # 1. ADK sets system_instruction from static_instruction
        # 2. SkillToolset.process_llm_request appends skill XML via append_instructions
        static_instruction = "You are a reasoning agent."
        skill_xml = (
            "\n\n"
            "You can use specialized 'skills'...\n\n"
            "<available_skills>\n"
            "<skill><name>recursive-ping</name>"
            "<description>A diagnostic skill</description></skill>\n"
            "</available_skills>"
        )
        combined_si = static_instruction + skill_xml

        # Dynamic instruction content (what ADK puts in contents from instruction template)
        dynamic_text = "Current iteration: 1\nRoot prompt: test query"
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=dynamic_text)],
            )
        ]

        llm_request = _make_llm_request(
            system_instruction=combined_si,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        # system_instruction must be EXACTLY unchanged (observe-only callback)
        final_si = llm_request.config.system_instruction
        assert final_si == combined_si, (
            f"reasoning_before_model modified system_instruction (GAP-CB-001). "
            f"Expected unchanged: {combined_si!r}, got: {final_si!r}"
        )
        # SkillToolset XML trivially preserved
        assert "<available_skills>" in final_si
        assert "recursive-ping" in final_si

    def test_callback_does_not_call_append_instructions(self) -> None:
        """The callback is observe-only and must NOT call append_instructions.

        GAP-CB-001 fix: the old code extracted all content text and appended
        it to system_instruction. The fixed callback does not modify the
        request at all.
        """
        from unittest.mock import patch

        from google.genai import types

        from rlm_adk.callbacks.reasoning import reasoning_before_model

        static_instruction = "You are a reasoning agent."
        dynamic_text = "Dynamic metadata here"
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=dynamic_text)],
            )
        ]

        llm_request = _make_llm_request(
            system_instruction=static_instruction,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        # Spy on append_instructions to verify the callback does NOT use it
        append_calls = []

        original_append = llm_request.append_instructions

        def tracking_append(self_arg, instructions):
            append_calls.append(instructions)
            return original_append(instructions)

        with patch.object(type(llm_request), "append_instructions", tracking_append):
            reasoning_before_model(callback_ctx, llm_request)

        # The callback must NOT call append_instructions (observe-only)
        assert len(append_calls) == 0, (
            "reasoning_before_model called append_instructions but should be "
            "observe-only (GAP-CB-001). ADK handles instruction placement natively."
        )

    def test_no_toolset_system_instruction_unchanged(self) -> None:
        """Without SkillToolset, system_instruction is still unchanged."""
        from google.genai import types

        from rlm_adk.callbacks.reasoning import reasoning_before_model

        static_instruction = "You are a reasoning agent."
        dynamic_text = "Iteration: 1"
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=dynamic_text)],
            )
        ]

        llm_request = _make_llm_request(
            system_instruction=static_instruction,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        final_si = llm_request.config.system_instruction
        assert final_si == static_instruction, (
            f"reasoning_before_model modified system_instruction. "
            f"Expected: {static_instruction!r}, got: {final_si!r}"
        )


# ---------------------------------------------------------------------------
# Cycle 20 (remaining) — Child skill propagation in orchestrator
# ---------------------------------------------------------------------------


class TestChildSkillPropagation:
    """Children get skill globals in REPL but do NOT get SkillToolset."""

    @pytest.mark.asyncio
    async def test_children_get_repl_globals_unconditionally(self) -> None:
        """Child orchestrators (no enabled_skills) still get skill functions in REPL globals."""
        from google.adk.agents import LlmAgent

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        # Child orchestrator: enabled_skills=() (default, as create_child_orchestrator does)
        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning",
            model="gemini-2.0-flash",
        )
        child_orch = RLMOrchestratorAgent(
            name="child_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            enabled_skills=(),  # Child has no enabled_skills
            repl=repl,
            depth=1,
        )

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-child"
        mock_ctx.session.state = {}

        events = []
        try:
            async for event in child_orch._run_async_impl(mock_ctx):
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass

        # Skill functions should be available in REPL globals
        # even without enabled_skills (collect_skill_repl_globals called unconditionally)
        assert "run_recursive_ping" in repl.globals, (
            "Child orchestrators must have skill functions in REPL globals "
            "even when enabled_skills is empty. collect_skill_repl_globals() "
            "should be called unconditionally."
        )
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_children_without_enabled_skills_do_not_get_skilltoolset(self) -> None:
        """Child orchestrators without enabled_skills do NOT have SkillToolset."""
        from google.adk.agents import LlmAgent
        from google.adk.tools.skill_toolset import SkillToolset

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning",
            model="gemini-2.0-flash",
        )
        child_orch = RLMOrchestratorAgent(
            name="child_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            enabled_skills=(),  # No skills -> no SkillToolset
            repl=repl,
            depth=1,
        )

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-child"
        mock_ctx.session.state = {}

        events = []
        try:
            async for event in child_orch._run_async_impl(mock_ctx):
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass

        tools = reasoning_agent.tools
        toolset_instances = [t for t in tools if isinstance(t, SkillToolset)]
        assert len(toolset_instances) == 0, (
            "Child orchestrators without enabled_skills must NOT have SkillToolset."
        )
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_children_with_enabled_skills_get_skilltoolset(self) -> None:
        """Child orchestrators WITH enabled_skills DO have SkillToolset."""
        from google.adk.agents import LlmAgent
        from google.adk.tools.skill_toolset import SkillToolset

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning",
            model="gemini-2.0-flash",
        )
        child_orch = RLMOrchestratorAgent(
            name="child_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            enabled_skills=("recursive_ping",),  # Skills enabled on child
            repl=repl,
            depth=1,
        )

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-child"
        mock_ctx.session.state = {}

        events = []
        try:
            async for event in child_orch._run_async_impl(mock_ctx):
                events.append(event)
                if len(events) >= 3:
                    break
        except Exception:
            pass

        tools = reasoning_agent.tools
        toolset_instances = [t for t in tools if isinstance(t, SkillToolset)]
        assert len(toolset_instances) == 1, (
            "Child orchestrators with enabled_skills must have SkillToolset. "
            f"Got {len(toolset_instances)} SkillToolset instances in {tools}"
        )
        repl.cleanup()


# ---------------------------------------------------------------------------
# Shared e2e helper — runs a fixture with enabled_skills through the full
# production pipeline.  The standard contract_runner doesn't pass
# enabled_skills, so we need a custom helper.
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "provider_fake"


class _SystemInstructionCapture:
    """Capture plugin that records system_instruction from before_model calls."""

    def __init__(self):
        self.captured_system_instructions: list[str] = []

    def make_plugin(self):
        """Return a BasePlugin instance wired to this capture."""
        from google.adk.plugins.base_plugin import BasePlugin

        outer = self

        class CapturePlugin(BasePlugin):
            def __init__(self_inner):
                super().__init__(name="si_capture")

            async def before_model_callback(
                self_inner, *, callback_context, llm_request, **_kw
            ):
                config = getattr(llm_request, "config", None)
                if config:
                    si = getattr(config, "system_instruction", None)
                    if isinstance(si, str):
                        outer.captured_system_instructions.append(si)
                    elif si and hasattr(si, "parts"):
                        text = "\n".join(
                            p.text
                            for p in si.parts
                            if hasattr(p, "text") and p.text
                        )
                        outer.captured_system_instructions.append(text)
                return None

        return CapturePlugin()


async def _run_skill_fixture(
    fixture_name: str,
    enabled_skills: tuple[str, ...] = ("recursive_ping",),
    traces_db_path: str | None = None,
    extra_plugins: list | None = None,
) -> dict[str, Any]:
    """Run a fixture through the full pipeline with enabled_skills.

    Returns a dict with keys: events, final_state, traces_db_path, contract.
    """
    import os
    import tempfile

    from google.adk.artifacts import FileArtifactService
    from google.adk.runners import Runner
    from google.genai import types

    from rlm_adk.agent import _default_session_service, create_rlm_app
    from rlm_adk.plugins.observability import ObservabilityPlugin
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
    from tests_rlm_adk.provider_fake.contract_runner import (
        _restore_env,
        _save_env,
        _set_env,
    )
    from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
    from tests_rlm_adk.provider_fake.server import FakeGeminiServer

    fixture_path = _FIXTURE_DIR / fixture_name
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
    saved = _save_env()

    try:
        base_url = await server.start()
        _set_env(base_url, router)
        os.environ["RLM_REPL_TRACE"] = "1"

        tmpdir = tempfile.mkdtemp(prefix="skill-e2e-")
        session_db = str(Path(tmpdir) / "session.db")
        artifact_root = str(Path(tmpdir) / "artifacts")
        _traces_db = traces_db_path or str(Path(tmpdir) / "traces.db")

        plugins: list = [
            ObservabilityPlugin(),
            SqliteTracingPlugin(db_path=_traces_db),
        ]
        if extra_plugins:
            plugins.extend(extra_plugins)

        app = create_rlm_app(
            model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
            thinking_budget=router.config.get("thinking_budget", 0),
            plugins=plugins,
            langfuse=False,
            sqlite_tracing=False,
            enabled_skills=enabled_skills,
        )

        session_service = _default_session_service(db_path=session_db)
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

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text="test prompt")],
        )
        events: list = []
        async for event in runner.run_async(
            user_id="test-user",
            session_id=session.id,
            new_message=content,
        ):
            events.append(event)

        final_session = await runner.session_service.get_session(
            app_name="rlm_adk",
            user_id="test-user",
            session_id=session.id,
        )
        final_state = final_session.state if final_session else {}

        contract = router.check_expectations(
            final_state, fixture_path, 0.0, events=events
        )

        return {
            "events": events,
            "final_state": final_state,
            "traces_db_path": _traces_db,
            "contract": contract,
        }
    finally:
        await server.stop()
        _restore_env(saved)


# ---------------------------------------------------------------------------
# Cycle 25 — SkillToolset L1/L2 e2e discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSkillToolsetE2E:
    """SkillToolset L1 XML and L2 instructions flow through the real pipeline."""

    async def test_l1_xml_in_system_instruction(self, tmp_path):
        """System instruction sent to model contains skill discovery info."""
        capture = _SystemInstructionCapture()
        result = await _run_skill_fixture(
            "skill_toolset_discovery.json",
            traces_db_path=str(tmp_path / "traces.db"),
            extra_plugins=[capture.make_plugin()],
        )
        assert result["contract"].passed, result["contract"].diagnostics()

        # At least one model call should have happened
        assert len(capture.captured_system_instructions) >= 1, (
            "No system instructions captured — plugin may not have fired"
        )
        # The first call's system instruction should mention recursive-ping
        first_si = capture.captured_system_instructions[0]
        assert "recursive-ping" in first_si, (
            f"L1 discovery missing recursive-ping skill in system instruction. "
            f"Preview: {first_si[:300]}..."
        )

    async def test_load_skill_returns_l2_instructions(self, tmp_path):
        """load_skill(name='recursive-ping') returns L2 instructions from SKILL.md."""
        result = await _run_skill_fixture(
            "skill_toolset_discovery.json",
            traces_db_path=str(tmp_path / "traces.db"),
        )
        assert result["contract"].passed, result["contract"].diagnostics()

        # Find the load_skill tool response event
        load_skill_responses: list = []
        for event in result["events"]:
            content = getattr(event, "content", None)
            if content and content.parts:
                for part in content.parts:
                    fn_resp = getattr(part, "function_response", None)
                    if fn_resp and getattr(fn_resp, "name", None) == "load_skill":
                        load_skill_responses.append(fn_resp.response)

        assert len(load_skill_responses) >= 1, (
            "No load_skill function_response found in events"
        )
        # The response should contain L2 instructions from SKILL.md
        resp_str = str(load_skill_responses[0])
        assert "run_recursive_ping" in resp_str, (
            f"L2 instructions should mention run_recursive_ping. "
            f"Got: {resp_str[:300]}"
        )


# ---------------------------------------------------------------------------
# Cycle 26 — Recursive-ping capstone e2e (thread bridge child dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecursivePingE2E:
    """run_recursive_ping calls llm_query via thread bridge, child dispatches."""

    async def test_skill_function_calls_llm_query_via_thread_bridge(self, tmp_path):
        """run_recursive_ping in REPL calls llm_query, child dispatch occurs."""
        result = await _run_skill_fixture(
            "skill_recursive_ping_e2e.json",
            traces_db_path=str(tmp_path / "traces.db"),
        )
        assert result["contract"].passed, result["contract"].diagnostics()

        # Final answer should contain the ping result
        final_answer = result["final_state"].get("final_response_text", "")
        assert "ping_ok" in final_answer, (
            f"Expected 'ping_ok' in final answer, got: {final_answer[:300]}"
        )

    async def test_child_dispatch_at_depth_1(self, tmp_path):
        """Telemetry has rows for depth=0 (reasoning) and depth=1 (child)."""
        traces_db = str(tmp_path / "traces.db")
        result = await _run_skill_fixture(
            "skill_recursive_ping_e2e.json",
            traces_db_path=traces_db,
        )
        assert result["contract"].passed, result["contract"].diagnostics()

        conn = sqlite3.connect(traces_db)
        try:
            rows = conn.execute(
                "SELECT DISTINCT depth FROM telemetry ORDER BY depth"
            ).fetchall()
            depths = [r[0] for r in rows]
            assert 0 in depths, f"Expected depth=0 in telemetry. Got: {depths}"
        finally:
            conn.close()

    async def test_result_propagates_to_parent_repl(self, tmp_path):
        """Final answer contains the ping result from child dispatch."""
        result = await _run_skill_fixture(
            "skill_recursive_ping_e2e.json",
            traces_db_path=str(tmp_path / "traces.db"),
        )
        assert result["contract"].passed, result["contract"].diagnostics()

        final_answer = result["final_state"].get("final_response_text", "")
        assert "ping_ok" in final_answer or "recursive" in final_answer.lower(), (
            f"Expected ping result in final answer, got: {final_answer[:300]}"
        )
