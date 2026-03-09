"""Tests for depth + fanout_idx disambiguation in artifact filenames.

Verifies that artifact helpers produce unique filenames that include
d{depth}_f{fanout_idx} prefixes, preventing collisions between parent
and child orchestrators, and between batched siblings.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from rlm_adk.artifacts import (
    save_final_answer,
    save_repl_code,
    save_repl_output,
    save_repl_trace,
)
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.tools.repl_tool import REPLTool


def _make_invocation_context() -> MagicMock:
    """Create a mock InvocationContext with a mock artifact_service."""
    ctx = MagicMock()
    ctx.artifact_service = AsyncMock()
    ctx.artifact_service.save_artifact = AsyncMock(return_value=0)
    ctx.app_name = "test_app"
    ctx.session.user_id = "test_user"
    ctx.session.id = "test_session"
    ctx.session.state = {}
    return ctx


def _make_tool_context() -> MagicMock:
    """Create a mock ToolContext for REPLTool tests."""
    ctx = MagicMock()
    ctx.state = {}
    ctx._invocation_context = _make_invocation_context()
    return ctx


# ---------------------------------------------------------------------------
# save_repl_code filename tests
# ---------------------------------------------------------------------------


@pytest.mark.unit_nondefault
class TestSaveReplCodeNaming:
    @pytest.mark.asyncio
    async def test_root_depth_default_fanout(self):
        """depth=0, fanout_idx=0 produces d0_f0 prefix."""
        ctx = _make_invocation_context()
        await save_repl_code(ctx, iteration=1, turn=0, code="x = 1")
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_code_d0_f0_iter_1_turn_0.py"

    @pytest.mark.asyncio
    async def test_child_depth_with_fanout(self):
        """depth=1, fanout_idx=2 produces d1_f2 prefix."""
        ctx = _make_invocation_context()
        await save_repl_code(ctx, iteration=3, turn=1, code="y = 2", depth=1, fanout_idx=2)
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_code_d1_f2_iter_3_turn_1.py"

    @pytest.mark.asyncio
    async def test_deep_nesting(self):
        """depth=2, fanout_idx=0 produces d2_f0 prefix."""
        ctx = _make_invocation_context()
        await save_repl_code(ctx, iteration=1, turn=0, code="z = 3", depth=2, fanout_idx=0)
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_code_d2_f0_iter_1_turn_0.py"


# ---------------------------------------------------------------------------
# save_repl_output filename tests
# ---------------------------------------------------------------------------


@pytest.mark.unit_nondefault
class TestSaveReplOutputNaming:
    @pytest.mark.asyncio
    async def test_root_depth_default_fanout(self):
        ctx = _make_invocation_context()
        await save_repl_output(ctx, iteration=1, stdout="hello")
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_output_d0_f0_iter_1.txt"

    @pytest.mark.asyncio
    async def test_child_depth_with_fanout(self):
        ctx = _make_invocation_context()
        await save_repl_output(ctx, iteration=2, stdout="world", depth=1, fanout_idx=3)
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_output_d1_f3_iter_2.txt"


# ---------------------------------------------------------------------------
# save_repl_trace filename tests
# ---------------------------------------------------------------------------


@pytest.mark.unit_nondefault
class TestSaveReplTraceNaming:
    @pytest.mark.asyncio
    async def test_root_depth_default_fanout(self):
        ctx = _make_invocation_context()
        await save_repl_trace(ctx, iteration=1, turn=0, trace_dict={"key": "val"})
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_trace_d0_f0_iter_1_turn_0.json"

    @pytest.mark.asyncio
    async def test_child_depth_with_fanout(self):
        ctx = _make_invocation_context()
        await save_repl_trace(ctx, iteration=5, turn=2, trace_dict={}, depth=2, fanout_idx=1)
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_trace_d2_f1_iter_5_turn_2.json"


# ---------------------------------------------------------------------------
# save_final_answer filename tests
# ---------------------------------------------------------------------------


@pytest.mark.unit_nondefault
class TestSaveFinalAnswerNaming:
    @pytest.mark.asyncio
    async def test_root_depth_default_fanout(self):
        ctx = _make_invocation_context()
        await save_final_answer(ctx, answer="The answer is 42.")
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "final_answer_d0_f0.md"

    @pytest.mark.asyncio
    async def test_child_depth_with_fanout(self):
        ctx = _make_invocation_context()
        await save_final_answer(ctx, answer="Child result", depth=1, fanout_idx=4)
        call_args = ctx.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "final_answer_d1_f4.md"


# ---------------------------------------------------------------------------
# REPLTool threads depth + fanout_idx to save_repl_code
# ---------------------------------------------------------------------------


@pytest.mark.unit_nondefault
class TestREPLToolArtifactNaming:
    @pytest.mark.asyncio
    async def test_repl_tool_default_fanout_idx(self):
        """REPLTool with default fanout_idx=0 threads d{depth}_f0 to artifacts."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl, depth=1)
        tool_context = _make_tool_context()

        try:
            await tool.run_async(args={"code": "x = 1"}, tool_context=tool_context)
        finally:
            repl.cleanup()

        call_args = tool_context._invocation_context.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_code_d1_f0_iter_1_turn_0.py"

    @pytest.mark.asyncio
    async def test_repl_tool_custom_fanout_idx(self):
        """REPLTool with fanout_idx=2 threads d{depth}_f2 to artifacts."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl, depth=1, fanout_idx=2)
        tool_context = _make_tool_context()

        try:
            await tool.run_async(args={"code": "y = 2"}, tool_context=tool_context)
        finally:
            repl.cleanup()

        call_args = tool_context._invocation_context.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_code_d1_f2_iter_1_turn_0.py"

    @pytest.mark.asyncio
    async def test_repl_tool_root_depth(self):
        """REPLTool at root depth=0, fanout_idx=0 produces d0_f0 prefix."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl, depth=0, fanout_idx=0)
        tool_context = _make_tool_context()

        try:
            await tool.run_async(args={"code": "z = 3"}, tool_context=tool_context)
        finally:
            repl.cleanup()

        call_args = tool_context._invocation_context.artifact_service.save_artifact.call_args
        assert call_args.kwargs["filename"] == "repl_code_d0_f0_iter_1_turn_0.py"


# ---------------------------------------------------------------------------
# Collision prevention: siblings at same depth get different filenames
# ---------------------------------------------------------------------------


@pytest.mark.unit_nondefault
class TestCollisionPrevention:
    @pytest.mark.asyncio
    async def test_sibling_children_have_distinct_filenames(self):
        """Three batched children at depth=1 with fanout_idx=0,1,2 produce unique filenames."""
        filenames = []
        for fanout_idx in range(3):
            ctx = _make_invocation_context()
            await save_repl_code(
                ctx, iteration=1, turn=0, code="x = 1", depth=1, fanout_idx=fanout_idx
            )
            call_args = ctx.artifact_service.save_artifact.call_args
            filenames.append(call_args.kwargs["filename"])

        assert len(filenames) == 3
        assert len(set(filenames)) == 3, f"Expected 3 unique filenames, got: {filenames}"
        assert filenames[0] == "repl_code_d1_f0_iter_1_turn_0.py"
        assert filenames[1] == "repl_code_d1_f1_iter_1_turn_0.py"
        assert filenames[2] == "repl_code_d1_f2_iter_1_turn_0.py"

    @pytest.mark.asyncio
    async def test_parent_child_have_distinct_filenames(self):
        """Parent at d0_f0 and child at d1_f0 produce different filenames."""
        parent_ctx = _make_invocation_context()
        child_ctx = _make_invocation_context()

        await save_repl_code(parent_ctx, iteration=1, turn=0, code="parent", depth=0, fanout_idx=0)
        await save_repl_code(child_ctx, iteration=1, turn=0, code="child", depth=1, fanout_idx=0)

        parent_fn = parent_ctx.artifact_service.save_artifact.call_args.kwargs["filename"]
        child_fn = child_ctx.artifact_service.save_artifact.call_args.kwargs["filename"]

        assert parent_fn != child_fn
        assert parent_fn == "repl_code_d0_f0_iter_1_turn_0.py"
        assert child_fn == "repl_code_d1_f0_iter_1_turn_0.py"
