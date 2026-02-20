"""Tests for Rec 3: FileArtifactService as default.

Verifies that create_rlm_runner() defaults to FileArtifactService
instead of InMemoryArtifactService.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.adk.artifacts import FileArtifactService, InMemoryArtifactService
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import types


class TestFileArtifactServiceDefault:
    """Rec 3: create_rlm_runner() defaults to FileArtifactService."""

    def test_default_runner_uses_file_artifact_service(self, tmp_path):
        """Runner created without artifact_service kwarg uses FileArtifactService."""
        from rlm_adk.agent import create_rlm_runner

        artifact_root = str(tmp_path / "artifacts")
        mock_session = MagicMock(spec=BaseSessionService)
        with patch("rlm_adk.agent.create_rlm_app") as mock_app, \
             patch("rlm_adk.agent._DEFAULT_ARTIFACT_ROOT", artifact_root):
            mock_app.return_value = MagicMock()
            runner = create_rlm_runner(
                model="gemini-2.5-flash",
                session_service=mock_session,
            )
        assert isinstance(runner.artifact_service, FileArtifactService)

    def test_default_artifact_root_is_adk_artifacts(self):
        """Default FileArtifactService root resolves to .adk/artifacts."""
        from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT

        assert _DEFAULT_ARTIFACT_ROOT == ".adk/artifacts"

    def test_explicit_artifact_service_overrides_default(self):
        """Passing explicit artifact_service uses that instead."""
        from rlm_adk.agent import create_rlm_runner

        mem_service = InMemoryArtifactService()
        mock_session = MagicMock(spec=BaseSessionService)
        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock()
            runner = create_rlm_runner(
                model="gemini-2.5-flash",
                artifact_service=mem_service,
                session_service=mock_session,
            )
        assert runner.artifact_service is mem_service

    def test_file_artifact_service_creates_directory(self, tmp_path):
        """FileArtifactService creates the root directory on init."""
        root = str(tmp_path / "nested" / "artifacts")
        FileArtifactService(root_dir=root)
        assert os.path.isdir(root)

    @pytest.mark.asyncio
    async def test_file_artifact_service_save_and_load_roundtrip(self, tmp_path):
        """Save and load a text artifact through FileArtifactService."""
        service = FileArtifactService(root_dir=str(tmp_path))
        artifact = types.Part(text="hello world")
        version = await service.save_artifact(
            app_name="test", user_id="user1", session_id="sess1",
            filename="test.txt", artifact=artifact,
        )
        assert version == 0
        loaded = await service.load_artifact(
            app_name="test", user_id="user1", session_id="sess1",
            filename="test.txt",
        )
        assert loaded is not None
        assert loaded.text == "hello world"
