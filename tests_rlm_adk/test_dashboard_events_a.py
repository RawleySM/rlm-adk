"""Tests for dashboard lineage plumbing (Agent A).

TDD cycles for 3 lineage fields that child orchestrators carry so the
dashboard event plugin can build an explicit parent->child tree:

1. parent_invocation_id — propagates to child reasoning agent
2. parent_tool_call_id — reads from InvocationContext
3. dispatch_call_index — increments per llm_query call
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Cycle 1 — parent_invocation_id propagates to child reasoning agent
# ---------------------------------------------------------------------------


class TestParentInvocationIdPropagates:
    """Child orchestrator's reasoning agent has _rlm_parent_invocation_id set."""

    def test_create_child_orchestrator_accepts_parent_invocation_id(self):
        """create_child_orchestrator accepts parent_invocation_id kwarg."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
            parent_invocation_id="test_inv_123",
        )
        assert orch.parent_invocation_id == "test_inv_123"

    def test_create_child_orchestrator_default_parent_invocation_id_none(self):
        """Without parent_invocation_id kwarg, the default is None."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
        )
        assert orch.parent_invocation_id is None

    @pytest.mark.asyncio
    async def test_parent_invocation_id_set_on_reasoning_agent(self):
        """_run_async_impl sets _rlm_parent_invocation_id on reasoning_agent."""
        from google.adk.agents import LlmAgent

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning_d1f0",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            depth=1,
            parent_invocation_id="parent_inv_abc",
            repl=repl,
            worker_pool=MagicMock(),
        )
        orch.worker_pool.ensure_initialized = MagicMock()

        def _fake_dispatch(*args, **kwargs):
            async def _noop(*a, **kw):
                return None

            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "child-inv-id"
        mock_ctx.session.state = {}

        with patch(
            "rlm_adk.orchestrator.create_dispatch_closures",
            side_effect=_fake_dispatch,
        ):
            events = []
            try:
                async for event in orch._run_async_impl(mock_ctx):
                    events.append(event)
                    if len(events) >= 3:
                        break
            except Exception:
                pass

        assert getattr(reasoning_agent, "_rlm_parent_invocation_id", None) == "parent_inv_abc", (
            f"Expected _rlm_parent_invocation_id='parent_inv_abc', "
            f"got: {getattr(reasoning_agent, '_rlm_parent_invocation_id', 'MISSING')}"
        )
        repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 2 — parent_tool_call_id reads from InvocationContext
# ---------------------------------------------------------------------------


class TestParentToolCallIdReadsFromCtx:
    """_run_child reads _dashboard_execute_code_event_id from ctx."""

    def test_create_child_orchestrator_accepts_parent_tool_call_id(self):
        """create_child_orchestrator accepts parent_tool_call_id kwarg."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
            parent_tool_call_id="evt_456",
        )
        assert orch.parent_tool_call_id == "evt_456"

    def test_create_child_orchestrator_default_parent_tool_call_id_none(self):
        """Without parent_tool_call_id kwarg, the default is None."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
        )
        assert orch.parent_tool_call_id is None

    @pytest.mark.asyncio
    async def test_dispatch_reads_dashboard_execute_code_event_id(self):
        """llm_query_batched_async reads _dashboard_execute_code_event_id from ctx."""
        from rlm_adk.dispatch import WorkerPool, create_dispatch_closures

        pool = WorkerPool(default_model="gemini-fake")
        pool.ensure_initialized()

        mock_ctx = MagicMock()
        mock_ctx.session.state = {}
        mock_ctx.branch = None
        mock_ctx.agent.name = "test_parent"
        mock_ctx.invocation_id = "parent_inv_xyz"
        # The dispatch reads from ctx.agent.reasoning_agent (the orchestrator's
        # reasoning_agent), since the plugin sets attrs on inv_ctx.agent which
        # is the reasoning_agent, but ctx.agent is the orchestrator.
        mock_reasoning = MagicMock()
        mock_reasoning._dashboard_execute_code_event_id = "evt_tool_789"
        mock_reasoning._dashboard_dispatch_call_counter = 0
        mock_ctx.agent.reasoning_agent = mock_reasoning

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
        )

        with patch(
            "rlm_adk.agent.create_child_orchestrator",
            side_effect=_capture_create_child,
        ):
            try:
                await llm_query_async("test prompt")
            except Exception:
                pass

        assert len(captured_kwargs) >= 1, "create_child_orchestrator was never called"
        assert captured_kwargs[0].get("parent_tool_call_id") == "evt_tool_789", (
            f"Expected parent_tool_call_id='evt_tool_789', "
            f"got: {captured_kwargs[0].get('parent_tool_call_id')}"
        )

    @pytest.mark.asyncio
    async def test_parent_tool_call_id_set_on_reasoning_agent(self):
        """_run_async_impl sets _rlm_parent_tool_call_id on reasoning_agent."""
        from google.adk.agents import LlmAgent

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning_d1f0",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            depth=1,
            parent_tool_call_id="evt_tool_999",
            repl=repl,
            worker_pool=MagicMock(),
        )
        orch.worker_pool.ensure_initialized = MagicMock()

        def _fake_dispatch(*args, **kwargs):
            async def _noop(*a, **kw):
                return None

            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "child-inv-id"
        mock_ctx.session.state = {}

        with patch(
            "rlm_adk.orchestrator.create_dispatch_closures",
            side_effect=_fake_dispatch,
        ):
            events = []
            try:
                async for event in orch._run_async_impl(mock_ctx):
                    events.append(event)
                    if len(events) >= 3:
                        break
            except Exception:
                pass

        assert getattr(reasoning_agent, "_rlm_parent_tool_call_id", None) == "evt_tool_999", (
            f"Expected _rlm_parent_tool_call_id='evt_tool_999', "
            f"got: {getattr(reasoning_agent, '_rlm_parent_tool_call_id', 'MISSING')}"
        )
        repl.cleanup()


# ---------------------------------------------------------------------------
# Cycle 3 — dispatch_call_index increments per llm_query
# ---------------------------------------------------------------------------


class TestDispatchCallIndexIncrements:
    """Sequential llm_query() calls get incrementing dispatch_call_index."""

    def test_create_child_orchestrator_accepts_dispatch_call_index(self):
        """create_child_orchestrator accepts dispatch_call_index kwarg."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
            dispatch_call_index=5,
        )
        assert orch.dispatch_call_index == 5

    def test_create_child_orchestrator_default_dispatch_call_index_zero(self):
        """Without dispatch_call_index kwarg, the default is 0."""
        from rlm_adk.agent import create_child_orchestrator

        orch = create_child_orchestrator(
            model="gemini-fake",
            depth=1,
            prompt="test",
        )
        assert orch.dispatch_call_index == 0

    @pytest.mark.asyncio
    async def test_dispatch_call_index_increments_across_calls(self):
        """Sequential llm_query calls get dispatch_call_index 0, 1, then 2,3."""
        from rlm_adk.dispatch import WorkerPool, create_dispatch_closures

        pool = WorkerPool(default_model="gemini-fake")
        pool.ensure_initialized()

        mock_ctx = MagicMock()
        mock_ctx.session.state = {}
        mock_ctx.branch = None
        mock_ctx.agent.name = "test_parent"
        mock_ctx.invocation_id = "parent_inv_counter"
        # Dispatch reads from ctx.agent.reasoning_agent
        mock_reasoning = MagicMock()
        mock_reasoning._dashboard_dispatch_call_counter = 0
        mock_ctx.agent.reasoning_agent = mock_reasoning

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

        _, llm_query_batched_async, _ = create_dispatch_closures(
            pool,
            mock_ctx,
            depth=0,
        )

        with patch(
            "rlm_adk.agent.create_child_orchestrator",
            side_effect=_capture_create_child,
        ):
            # Call 1: single prompt -> child gets dispatch_call_index=0, counter becomes 1
            try:
                await llm_query_batched_async(["prompt_a"])
            except Exception:
                pass

            # Call 2: single prompt -> child gets dispatch_call_index=1, counter becomes 2
            try:
                await llm_query_batched_async(["prompt_b"])
            except Exception:
                pass

            # Call 3: batch of 2 -> children get dispatch_call_index=2,3, counter becomes 4
            try:
                await llm_query_batched_async(["prompt_c", "prompt_d"])
            except Exception:
                pass

        # Verify captured dispatch_call_index values
        assert len(captured_kwargs) == 4, (
            f"Expected 4 create_child_orchestrator calls, got {len(captured_kwargs)}"
        )
        indices = [kw.get("dispatch_call_index") for kw in captured_kwargs]
        assert indices == [0, 1, 2, 3], (
            f"Expected dispatch_call_index sequence [0, 1, 2, 3], got: {indices}"
        )

        # Verify the counter was advanced on the reasoning_agent
        assert mock_reasoning._dashboard_dispatch_call_counter == 4, (
            f"Expected _dashboard_dispatch_call_counter=4, got: {mock_reasoning._dashboard_dispatch_call_counter}"
        )

    @pytest.mark.asyncio
    async def test_dispatch_call_index_set_on_reasoning_agent(self):
        """_run_async_impl sets _rlm_dispatch_call_index on reasoning_agent."""
        from google.adk.agents import LlmAgent

        from rlm_adk.orchestrator import RLMOrchestratorAgent
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        reasoning_agent = LlmAgent(
            name="child_reasoning_d1f0",
            model="gemini-2.0-flash",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
            depth=1,
            dispatch_call_index=7,
            repl=repl,
            worker_pool=MagicMock(),
        )
        orch.worker_pool.ensure_initialized = MagicMock()

        def _fake_dispatch(*args, **kwargs):
            async def _noop(*a, **kw):
                return None

            return (_noop, _noop, None)

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "child-inv-id"
        mock_ctx.session.state = {}

        with patch(
            "rlm_adk.orchestrator.create_dispatch_closures",
            side_effect=_fake_dispatch,
        ):
            events = []
            try:
                async for event in orch._run_async_impl(mock_ctx):
                    events.append(event)
                    if len(events) >= 3:
                        break
            except Exception:
                pass

        assert getattr(reasoning_agent, "_rlm_dispatch_call_index", None) == 7, (
            f"Expected _rlm_dispatch_call_index=7, "
            f"got: {getattr(reasoning_agent, '_rlm_dispatch_call_index', 'MISSING')}"
        )
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_dispatch_passes_parent_invocation_id_from_ctx(self):
        """llm_query_batched_async reads ctx.invocation_id as parent_invocation_id."""
        from rlm_adk.dispatch import WorkerPool, create_dispatch_closures

        pool = WorkerPool(default_model="gemini-fake")
        pool.ensure_initialized()

        mock_ctx = MagicMock()
        mock_ctx.session.state = {}
        mock_ctx.branch = None
        mock_ctx.agent.name = "test_parent"
        mock_ctx.invocation_id = "parent_inv_from_ctx"

        captured_kwargs: list[dict] = []

        def _capture_create_child(**kwargs):
            captured_kwargs.append(kwargs)
            mock_orch = MagicMock()
            mock_orch.name = "mock_child"

            async def _empty_run(ctx):
                return
                yield

            mock_orch.run_async = _empty_run
            return mock_orch

        llm_query_async, _, _ = create_dispatch_closures(
            pool,
            mock_ctx,
            depth=0,
        )

        with patch(
            "rlm_adk.agent.create_child_orchestrator",
            side_effect=_capture_create_child,
        ):
            try:
                await llm_query_async("test prompt")
            except Exception:
                pass

        assert len(captured_kwargs) >= 1, "create_child_orchestrator was never called"
        assert captured_kwargs[0].get("parent_invocation_id") == "parent_inv_from_ctx", (
            f"Expected parent_invocation_id='parent_inv_from_ctx', "
            f"got: {captured_kwargs[0].get('parent_invocation_id')}"
        )
