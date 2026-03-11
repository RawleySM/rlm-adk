"""Tests for metadata docstrings prepended to REPL code artifacts.

Verifies that save_repl_code() prepends a YAML-style docstring containing
session_id, model, depth, fanout, iteration, turn, stdout, and stderr
when metadata parameters are provided.
"""

from unittest.mock import MagicMock

import pytest
from google.adk.artifacts import InMemoryArtifactService

from rlm_adk.artifacts import save_repl_code


@pytest.fixture
def artifact_service():
    return InMemoryArtifactService()


@pytest.fixture
def mock_invocation_context(artifact_service):
    ctx = MagicMock()
    ctx.artifact_service = artifact_service
    ctx.app_name = "test_app"
    ctx.session = MagicMock()
    ctx.session.id = "sess-abc-123"
    ctx.session.user_id = "test_user"
    ctx.session.state = {}
    ctx.invocation_id = "test_invocation"
    return ctx


@pytest.mark.provider_fake_contract
class TestReplCodeMetadataDocstring:
    """Tests for metadata docstring prepended to REPL code artifacts."""

    @pytest.mark.asyncio
    async def test_metadata_docstring_prepended(self, mock_invocation_context, artifact_service):
        """When metadata kwargs are provided, the saved artifact starts with a docstring."""
        code = "import pandas as pd\nprint('hello')"
        await save_repl_code(
            mock_invocation_context,
            iteration=1,
            turn=0,
            code=code,
            depth=0,
            fanout_idx=0,
            model="gemini-2.5-pro",
            session_id="sess-abc-123",
            stdout="hello\n",
            stderr="",
        )

        loaded = await artifact_service.load_artifact(
            app_name="test_app",
            user_id="test_user",
            session_id="sess-abc-123",
            filename="repl_code_d0_f0_iter_1_turn_0.py",
        )
        assert loaded is not None
        text = loaded.text
        assert text.startswith('"""')
        assert "session_id: sess-abc-123" in text
        assert "model: gemini-2.5-pro" in text
        assert "depth: 0" in text
        assert "fanout: 0" in text
        assert "iteration: 1" in text
        assert "turn: 0" in text
        assert "stdout: |" in text
        assert "hello" in text
        assert "stderr: |" in text
        # The original code follows after the docstring
        assert "import pandas as pd" in text
        assert text.index('"""', 3) < text.index("import pandas as pd")

    @pytest.mark.asyncio
    async def test_metadata_docstring_multiline_stdout(
        self, mock_invocation_context, artifact_service
    ):
        """Multi-line stdout is indented under the stdout: | block."""
        code = "x = 1"
        await save_repl_code(
            mock_invocation_context,
            iteration=2,
            turn=1,
            code=code,
            depth=1,
            fanout_idx=3,
            model="gemini-2.5-flash",
            session_id="sess-abc-123",
            stdout="line1\nline2\nline3",
            stderr="some warning",
        )

        loaded = await artifact_service.load_artifact(
            app_name="test_app",
            user_id="test_user",
            session_id="sess-abc-123",
            filename="repl_code_d1_f3_iter_2_turn_1.py",
        )
        text = loaded.text
        assert "depth: 1" in text
        assert "fanout: 3" in text
        assert "iteration: 2" in text
        assert "turn: 1" in text
        assert "model: gemini-2.5-flash" in text
        assert "line1" in text
        assert "line2" in text
        assert "some warning" in text

    @pytest.mark.asyncio
    async def test_metadata_empty_stderr_shows_empty(
        self, mock_invocation_context, artifact_service
    ):
        """Empty stderr is rendered as '(empty)' in the docstring."""
        code = "x = 1"
        await save_repl_code(
            mock_invocation_context,
            iteration=1,
            turn=0,
            code=code,
            depth=0,
            fanout_idx=0,
            model="gemini-2.5-pro",
            session_id="sess-abc-123",
            stdout="",
            stderr="",
        )

        loaded = await artifact_service.load_artifact(
            app_name="test_app",
            user_id="test_user",
            session_id="sess-abc-123",
            filename="repl_code_d0_f0_iter_1_turn_0.py",
        )
        text = loaded.text
        # Both empty stdout and stderr show (empty)
        assert "(empty)" in text

    @pytest.mark.asyncio
    async def test_no_metadata_when_kwargs_absent(self, mock_invocation_context, artifact_service):
        """When metadata kwargs are NOT provided, code is saved without docstring (backward compat)."""
        code = "x = 1"
        await save_repl_code(
            mock_invocation_context,
            iteration=1,
            turn=0,
            code=code,
            depth=0,
            fanout_idx=0,
        )

        loaded = await artifact_service.load_artifact(
            app_name="test_app",
            user_id="test_user",
            session_id="sess-abc-123",
            filename="repl_code_d0_f0_iter_1_turn_0.py",
        )
        text = loaded.text
        assert text == code

    @pytest.mark.asyncio
    async def test_metadata_docstring_all_fields_present(
        self, mock_invocation_context, artifact_service
    ):
        """All 8 required metadata fields appear in the docstring."""
        code = "pass"
        await save_repl_code(
            mock_invocation_context,
            iteration=5,
            turn=2,
            code=code,
            depth=3,
            fanout_idx=1,
            model="gemini-2.5-pro",
            session_id="sess-abc-123",
            stdout="output here",
            stderr="error here",
        )

        loaded = await artifact_service.load_artifact(
            app_name="test_app",
            user_id="test_user",
            session_id="sess-abc-123",
            filename="repl_code_d3_f1_iter_5_turn_2.py",
        )
        text = loaded.text
        required_fields = [
            "session_id:",
            "model:",
            "depth:",
            "fanout:",
            "iteration:",
            "turn:",
            "stdout:",
            "stderr:",
        ]
        for field in required_fields:
            assert field in text, f"Missing field: {field}"
