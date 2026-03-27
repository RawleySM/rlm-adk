"""Tests for child orchestrator feature parity (GAP-A).

Children must receive enabled_skills so they can get SkillToolset
(list_skills/load_skill) when dispatched via create_child_orchestrator.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Cycle 5 — create_child_orchestrator accepts enabled_skills
# ---------------------------------------------------------------------------


class TestCreateChildOrchestratorEnabledSkills:
    """create_child_orchestrator must accept and forward enabled_skills."""

    def test_create_child_orchestrator_accepts_enabled_skills(self):
        """Calling with enabled_skills=(...) sets the field on the returned orchestrator."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
            enabled_skills=("test_skill",),
        )
        assert orch.enabled_skills == ("test_skill",)

    def test_create_child_orchestrator_default_enabled_skills_empty(self):
        """Without enabled_skills kwarg, the default is an empty tuple."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
        )
        assert orch.enabled_skills == ()


# ---------------------------------------------------------------------------
# Cycle 6 — dispatch closures propagate enabled_skills to child orchestrator
# ---------------------------------------------------------------------------


class TestDispatchPropagatesEnabledSkills:
    """create_dispatch_closures must forward enabled_skills to create_child_orchestrator."""

    @pytest.mark.asyncio
    async def test_dispatch_propagates_enabled_skills(self):
        """llm_query_async passes enabled_skills to create_child_orchestrator."""
        from rlm_adk.dispatch import WorkerPool, create_dispatch_closures

        # Build a minimal dispatch config
        pool = WorkerPool(default_model="gemini-fake")
        pool.ensure_initialized()

        # Mock InvocationContext
        mock_ctx = MagicMock()
        mock_ctx.session.state = {}
        mock_ctx.branch = None
        mock_ctx.agent.name = "test_parent"

        captured_kwargs: list[dict] = []

        def _capture_create_child(**kwargs):
            captured_kwargs.append(kwargs)
            mock_orch = MagicMock()
            mock_orch.name = "mock_child"

            async def _empty_run(ctx):
                return
                yield  # make it an async generator

            mock_orch.run_async = _empty_run
            return mock_orch

        llm_query_async, _, _ = create_dispatch_closures(
            pool,
            mock_ctx,
            depth=0,
            enabled_skills=("test_skill",),
        )

        # _run_child does: from rlm_adk.agent import create_child_orchestrator
        # Patching at the source module intercepts the lazy import.
        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=_capture_create_child):
            try:
                await llm_query_async("test prompt")
            except Exception:
                pass  # We only care about the kwargs captured

        assert len(captured_kwargs) >= 1, "create_child_orchestrator was never called"
        assert captured_kwargs[0].get("enabled_skills") == ("test_skill",), (
            f"Expected enabled_skills=('test_skill',), got: {captured_kwargs[0]}"
        )


# ---------------------------------------------------------------------------
# Cycle 7 — orchestrator passes enabled_skills to create_dispatch_closures
# ---------------------------------------------------------------------------


class TestOrchestratorPassesEnabledSkillsToDispatch:
    """_run_async_impl must pass enabled_skills to create_dispatch_closures."""

    @pytest.mark.asyncio
    async def test_orchestrator_passes_enabled_skills_to_dispatch(self):
        """create_dispatch_closures receives enabled_skills from orchestrator."""
        from google.adk.agents import LlmAgent

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
            enabled_skills=("test_skill",),
            repl=repl,
            worker_pool=MagicMock(),  # non-None so dispatch wiring triggers
        )
        # Make worker_pool.ensure_initialized() a no-op
        orch.worker_pool.ensure_initialized = MagicMock()

        captured_kwargs: list[dict] = []

        def _capture_dispatch(*args, **kwargs):
            captured_kwargs.append(kwargs)
            # Return a 3-tuple (llm_query_async, llm_query_batched_async, flush_fn)
            async def _noop(*a, **kw):
                return None
            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        with patch("rlm_adk.orchestrator.create_dispatch_closures", side_effect=_capture_dispatch):
            events = []
            try:
                async for event in orch._run_async_impl(mock_ctx):
                    events.append(event)
                    if len(events) >= 3:
                        break
            except Exception:
                pass

        assert len(captured_kwargs) >= 1, "create_dispatch_closures was never called"
        assert captured_kwargs[0].get("enabled_skills") == ("test_skill",), (
            f"Expected enabled_skills=('test_skill',), got: {captured_kwargs[0]}"
        )
        repl.cleanup()


# ---------------------------------------------------------------------------
# Depth-2 induction — child at depth=1 re-passes enabled_skills to its own dispatch
# ---------------------------------------------------------------------------


class TestDepth2InductionEnabledSkills:
    """A depth=1 child with enabled_skills must forward them when it dispatches grandchildren."""

    @pytest.mark.asyncio
    async def test_depth1_child_forwards_enabled_skills_to_dispatch(self):
        """create_dispatch_closures at depth=1 receives the same enabled_skills tuple."""
        from google.adk.agents import LlmAgent

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning_d1f0",
            model="gemini-2.0-flash",
        )
        # Simulate a depth=1 child orchestrator with enabled_skills
        child_orch = RLMOrchestratorAgent(
            name="child_orchestrator_d1f0",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            depth=1,
            enabled_skills=("test_skill",),
            repl=repl,
            worker_pool=MagicMock(),
        )
        child_orch.worker_pool.ensure_initialized = MagicMock()

        captured_kwargs: list[dict] = []

        def _capture_dispatch(*args, **kwargs):
            captured_kwargs.append(kwargs)
            async def _noop(*a, **kw):
                return None
            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id-d1"
        mock_ctx.session.state = {}

        with patch("rlm_adk.orchestrator.create_dispatch_closures", side_effect=_capture_dispatch):
            try:
                async for event in child_orch._run_async_impl(mock_ctx):
                    if len(captured_kwargs) >= 1:
                        break
            except Exception:
                pass

        assert len(captured_kwargs) >= 1, "create_dispatch_closures was never called by depth=1 child"
        assert captured_kwargs[0].get("enabled_skills") == ("test_skill",), (
            f"Depth-2 induction failed: depth=1 child did not forward enabled_skills. "
            f"Got: {captured_kwargs[0].get('enabled_skills')}"
        )
        repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 9 — create_child_orchestrator propagates repo_url
# ---------------------------------------------------------------------------


class TestCreateChildOrchestratorRepoUrl:
    """create_child_orchestrator must accept and forward repo_url."""

    def test_create_child_orchestrator_propagates_repo_url(self):
        """Calling with repo_url=... sets the field on the returned orchestrator."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
            repo_url="https://github.com/test",
        )
        assert orch.repo_url == "https://github.com/test"

    def test_create_child_orchestrator_default_repo_url_none(self):
        """Without repo_url kwarg, the default is None."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
        )
        assert orch.repo_url is None


# ---------------------------------------------------------------------------
# Cycle 10 — dispatch closures propagate repo_url to child orchestrator
# ---------------------------------------------------------------------------


class TestDispatchPropagatesRepoUrl:
    """create_dispatch_closures must forward repo_url to create_child_orchestrator."""

    @pytest.mark.asyncio
    async def test_dispatch_propagates_repo_url(self):
        """llm_query_async passes repo_url to create_child_orchestrator."""
        from rlm_adk.dispatch import WorkerPool, create_dispatch_closures

        pool = WorkerPool(default_model="gemini-fake")
        pool.ensure_initialized()

        mock_ctx = MagicMock()
        mock_ctx.session.state = {}
        mock_ctx.branch = None
        mock_ctx.agent.name = "test_parent"

        captured_kwargs: list[dict] = []

        def _capture_create_child(**kwargs):
            captured_kwargs.append(kwargs)
            mock_orch = MagicMock()
            mock_orch.name = "mock_child"

            async def _empty_run(ctx):
                return
                yield  # make it an async generator

            mock_orch.run_async = _empty_run
            return mock_orch

        llm_query_async, _, _ = create_dispatch_closures(
            pool,
            mock_ctx,
            depth=0,
            repo_url="https://test.com",
        )

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=_capture_create_child):
            try:
                await llm_query_async("test prompt")
            except Exception:
                pass

        assert len(captured_kwargs) >= 1, "create_child_orchestrator was never called"
        assert captured_kwargs[0].get("repo_url") == "https://test.com", (
            f"Expected repo_url='https://test.com', got: {captured_kwargs[0]}"
        )


# ---------------------------------------------------------------------------
# Cycle 11 — orchestrator passes repo_url to create_dispatch_closures
# ---------------------------------------------------------------------------


class TestOrchestratorPassesRepoUrlToDispatch:
    """_run_async_impl must pass repo_url to create_dispatch_closures."""

    @pytest.mark.asyncio
    async def test_orchestrator_passes_repo_url_to_dispatch(self):
        """create_dispatch_closures receives repo_url from orchestrator."""
        from google.adk.agents import LlmAgent

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
            repo_url="https://github.com/test-repo",
            repl=repl,
            worker_pool=MagicMock(),  # non-None so dispatch wiring triggers
        )
        orch.worker_pool.ensure_initialized = MagicMock()

        captured_kwargs: list[dict] = []

        def _capture_dispatch(*args, **kwargs):
            captured_kwargs.append(kwargs)
            async def _noop(*a, **kw):
                return None
            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        with patch("rlm_adk.orchestrator.create_dispatch_closures", side_effect=_capture_dispatch):
            events = []
            try:
                async for event in orch._run_async_impl(mock_ctx):
                    events.append(event)
                    if len(events) >= 3:
                        break
            except Exception:
                pass

        assert len(captured_kwargs) >= 1, "create_dispatch_closures was never called"
        assert captured_kwargs[0].get("repo_url") == "https://github.com/test-repo", (
            f"Expected repo_url='https://github.com/test-repo', got: {captured_kwargs[0]}"
        )
        repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 12 — RLM_CHILD_STATIC_INSTRUCTION mentions skill tools
# ---------------------------------------------------------------------------


class TestChildStaticInstructionMentionsSkillTools:
    """RLM_CHILD_STATIC_INSTRUCTION must reference list_skills and load_skill."""

    def test_child_static_instruction_mentions_skill_tools(self):
        """The child static instruction must mention list_skills and load_skill."""
        from rlm_adk.utils.prompts import RLM_CHILD_STATIC_INSTRUCTION

        assert "list_skills" in RLM_CHILD_STATIC_INSTRUCTION, (
            "RLM_CHILD_STATIC_INSTRUCTION must mention list_skills"
        )
        assert "load_skill" in RLM_CHILD_STATIC_INSTRUCTION, (
            "RLM_CHILD_STATIC_INSTRUCTION must mention load_skill"
        )

    def test_child_and_root_skill_tools_parity(self):
        """Both root and child static instructions must mention the same skill tools."""
        from rlm_adk.utils.prompts import (
            RLM_CHILD_STATIC_INSTRUCTION,
            RLM_STATIC_INSTRUCTION,
        )

        for tool_name in ("list_skills", "load_skill"):
            assert tool_name in RLM_STATIC_INSTRUCTION, (
                f"Root instruction missing {tool_name}"
            )
            assert tool_name in RLM_CHILD_STATIC_INSTRUCTION, (
                f"Child instruction missing {tool_name}"
            )


# ---------------------------------------------------------------------------
# Reviewer fix: verify child orchestrator actually seeds DYN_REPO_URL in state
# ---------------------------------------------------------------------------


class TestChildOrchestratorSeedsDynRepoUrl:
    """Child orchestrator must emit DYN_REPO_URL in its initial state delta."""

    @pytest.mark.asyncio
    async def test_child_seeds_dyn_repo_url_in_initial_state(self):
        """A child with repo_url emits DYN_REPO_URL in its first state delta event."""
        from google.adk.agents import LlmAgent

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.state import DYN_REPO_URL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="test_reasoning",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            depth=1,
            repo_url="https://github.com/test-repo",
            repl=repl,
            worker_pool=MagicMock(),
        )
        orch.worker_pool.ensure_initialized = MagicMock()

        # Patch create_dispatch_closures to avoid real wiring
        def _fake_dispatch(*args, **kwargs):
            async def _noop(*a, **kw):
                return None
            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        with patch("rlm_adk.orchestrator.create_dispatch_closures", side_effect=_fake_dispatch):
            events = []
            try:
                async for event in orch._run_async_impl(mock_ctx):
                    events.append(event)
                    if len(events) >= 3:
                        break
            except Exception:
                pass

        # Find the initial state delta event
        state_deltas = [
            e.actions.state_delta
            for e in events
            if hasattr(e, "actions")
            and hasattr(e.actions, "state_delta")
            and e.actions.state_delta
        ]
        assert len(state_deltas) >= 1, "No state delta events emitted"

        # DYN_REPO_URL should be in the first state delta
        initial_delta = state_deltas[0]
        assert DYN_REPO_URL in initial_delta, (
            f"DYN_REPO_URL not in initial state delta. Keys: {sorted(initial_delta.keys())}"
        )
        assert initial_delta[DYN_REPO_URL] == "https://github.com/test-repo", (
            f"Expected 'https://github.com/test-repo', got: {initial_delta[DYN_REPO_URL]}"
        )
        repl.cleanup()
