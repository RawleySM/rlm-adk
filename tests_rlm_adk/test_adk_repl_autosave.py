"""Tests for REPL code auto-save and final answer auto-save.

Verifies:
- save_repl_code() saves code artifacts with correct naming
- save_repl_code() handles missing artifact service gracefully
- save_repl_code() updates tracking state
- save_final_answer() works as expected (already exists, just verify wiring)
"""

from unittest.mock import MagicMock

import pytest
from google.adk.artifacts import InMemoryArtifactService


@pytest.fixture
def artifact_service():
    return InMemoryArtifactService()


@pytest.fixture
def mock_invocation_context(artifact_service):
    ctx = MagicMock()
    ctx.artifact_service = artifact_service
    ctx.app_name = "test_app"
    ctx.session = MagicMock()
    ctx.session.id = "test_session"
    ctx.session.user_id = "test_user"
    ctx.session.state = {}
    ctx.invocation_id = "test_invocation"
    return ctx


class TestSaveReplCode:
    """Tests for the save_repl_code() artifact helper."""

    @pytest.mark.asyncio
    async def test_save_repl_code_writes_artifact(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_repl_code

        code = "print('hello world')"
        version = await save_repl_code(mock_invocation_context, iteration=0, turn=0, code=code)
        assert version == 0
        loaded = await artifact_service.load_artifact(
            app_name="test_app", user_id="test_user",
            session_id="test_session", filename="repl_code_iter_0_turn_0.py",
        )
        assert loaded is not None
        assert loaded.text == code

    @pytest.mark.asyncio
    async def test_save_repl_code_naming_convention(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_repl_code

        await save_repl_code(mock_invocation_context, iteration=2, turn=1, code="x = 1")
        keys = await artifact_service.list_artifact_keys(
            app_name="test_app", user_id="test_user", session_id="test_session",
        )
        assert "repl_code_iter_2_turn_1.py" in keys

    @pytest.mark.asyncio
    async def test_save_repl_code_multiple_turns(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_repl_code

        await save_repl_code(mock_invocation_context, iteration=0, turn=0, code="a = 1")
        await save_repl_code(mock_invocation_context, iteration=0, turn=1, code="b = 2")
        await save_repl_code(mock_invocation_context, iteration=0, turn=2, code="c = 3")
        keys = await artifact_service.list_artifact_keys(
            app_name="test_app", user_id="test_user", session_id="test_session",
        )
        assert "repl_code_iter_0_turn_0.py" in keys
        assert "repl_code_iter_0_turn_1.py" in keys
        assert "repl_code_iter_0_turn_2.py" in keys

    @pytest.mark.asyncio
    async def test_save_repl_code_no_service_returns_none(self):
        from rlm_adk.artifacts import save_repl_code

        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_repl_code(ctx, iteration=0, turn=0, code="x = 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_repl_code_updates_tracking_state(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_code
        from rlm_adk.state import ARTIFACT_SAVE_COUNT, ARTIFACT_LAST_SAVED_FILENAME

        await save_repl_code(mock_invocation_context, iteration=0, turn=0, code="x = 1")
        state = mock_invocation_context.session.state
        assert state[ARTIFACT_SAVE_COUNT] == 1
        assert state[ARTIFACT_LAST_SAVED_FILENAME] == "repl_code_iter_0_turn_0.py"


class TestFinalAnswerAutoSave:
    """Tests for save_final_answer() -- already exists but verify behavior."""

    @pytest.mark.asyncio
    async def test_final_answer_saved_as_artifact(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_final_answer

        version = await save_final_answer(mock_invocation_context, answer="The answer is 42.")
        assert version == 0
        loaded = await artifact_service.load_artifact(
            app_name="test_app", user_id="test_user",
            session_id="test_session", filename="final_answer.md",
        )
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_final_answer_not_saved_when_no_service(self):
        from rlm_adk.artifacts import save_final_answer

        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_final_answer(ctx, answer="test")
        assert result is None
