"""Unit tests for the RLM ADK Artifact Service integration.

TDD test suite covering:
- FR-007: State key constants for artifact tracking
- FR-002: Artifact helper functions (save/load/list/delete)
- FR-005: Artifact versioning
- FR-006: Session-scoped and user-scoped artifacts
- NFR-004: Error handling (graceful failures)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def artifact_service():
    """Provide a fresh InMemoryArtifactService."""
    return InMemoryArtifactService()


@pytest.fixture
def mock_invocation_context(artifact_service):
    """Provide a mock InvocationContext with artifact service."""
    ctx = MagicMock()
    ctx.artifact_service = artifact_service
    ctx.app_name = "test_app"
    ctx.user_id = "test_user"
    ctx.session = MagicMock()
    ctx.session.id = "test_session"
    ctx.session.user_id = "test_user"
    ctx.session.state = {}
    ctx.invocation_id = "test_invocation"
    return ctx


# ---------------------------------------------------------------------------
# Phase 1: State Keys (FR-007)
# ---------------------------------------------------------------------------

class TestArtifactStateKeys:
    """FR-007: Artifact state key constants are defined and follow conventions."""

    def test_artifact_tracking_keys_defined(self):
        """Verify all artifact tracking state key constants are importable."""
        from rlm_adk.state import (
            ARTIFACT_SAVE_COUNT,
            ARTIFACT_LOAD_COUNT,
            ARTIFACT_TOTAL_BYTES_SAVED,
            ARTIFACT_LAST_SAVED_FILENAME,
            ARTIFACT_LAST_SAVED_VERSION,
        )
        assert ARTIFACT_SAVE_COUNT == "artifact_save_count"
        assert ARTIFACT_LOAD_COUNT == "artifact_load_count"
        assert ARTIFACT_TOTAL_BYTES_SAVED == "artifact_total_bytes_saved"
        assert ARTIFACT_LAST_SAVED_FILENAME == "artifact_last_saved_filename"
        assert ARTIFACT_LAST_SAVED_VERSION == "artifact_last_saved_version"

    def test_artifact_observability_keys_defined(self):
        """Verify artifact observability key constants are importable."""
        from rlm_adk.state import (
            OBS_ARTIFACT_SAVES,
            OBS_ARTIFACT_BYTES_SAVED,
        )
        assert OBS_ARTIFACT_SAVES == "obs:artifact_saves"
        assert OBS_ARTIFACT_BYTES_SAVED == "obs:artifact_bytes_saved"

    def test_artifact_config_key_defined(self):
        """Verify artifact configuration key is importable."""
        from rlm_adk.state import APP_ARTIFACT_OFFLOAD_THRESHOLD
        assert APP_ARTIFACT_OFFLOAD_THRESHOLD == "app:artifact_offload_threshold"

    def test_artifact_tracking_keys_are_session_scoped(self):
        """Artifact tracking keys have no prefix (session-scoped)."""
        from rlm_adk.state import (
            ARTIFACT_SAVE_COUNT,
            ARTIFACT_LOAD_COUNT,
            ARTIFACT_TOTAL_BYTES_SAVED,
            ARTIFACT_LAST_SAVED_FILENAME,
            ARTIFACT_LAST_SAVED_VERSION,
        )
        for key in [
            ARTIFACT_SAVE_COUNT,
            ARTIFACT_LOAD_COUNT,
            ARTIFACT_TOTAL_BYTES_SAVED,
            ARTIFACT_LAST_SAVED_FILENAME,
            ARTIFACT_LAST_SAVED_VERSION,
        ]:
            assert not key.startswith("obs:"), f"{key} should not be obs-prefixed"
            assert not key.startswith("app:"), f"{key} should not be app-prefixed"

    def test_artifact_obs_keys_are_obs_prefixed(self):
        """Artifact observability keys follow obs: convention."""
        from rlm_adk.state import (
            OBS_ARTIFACT_SAVES,
            OBS_ARTIFACT_BYTES_SAVED,
        )
        for key in [
            OBS_ARTIFACT_SAVES,
            OBS_ARTIFACT_BYTES_SAVED,
        ]:
            assert key.startswith("obs:"), f"{key} should start with 'obs:'"

    def test_artifact_config_key_is_app_scoped(self):
        """Artifact config key follows app: convention."""
        from rlm_adk.state import APP_ARTIFACT_OFFLOAD_THRESHOLD
        assert APP_ARTIFACT_OFFLOAD_THRESHOLD.startswith("app:")


# ---------------------------------------------------------------------------
# Phase 1: Threshold Logic (FR-002)
# ---------------------------------------------------------------------------

class TestShouldOffloadToArtifact:
    """FR-002: should_offload_to_artifact threshold logic."""

    def test_small_string_not_offloaded(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact("short") is False

    def test_large_string_offloaded(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact("x" * 20000) is True

    def test_exactly_at_threshold_not_offloaded(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        # len(data) must be > threshold, not >=
        assert should_offload_to_artifact("x" * 10240) is False

    def test_one_over_threshold_offloaded(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact("x" * 10241) is True

    def test_custom_threshold(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact("hello", threshold=3) is True
        assert should_offload_to_artifact("hi", threshold=3) is False

    def test_bytes_large(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact(b"\x00" * 20000) is True

    def test_bytes_small(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact(b"\x00" * 100) is False

    def test_empty_string(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact("") is False

    def test_empty_bytes(self):
        from rlm_adk.artifacts import should_offload_to_artifact
        assert should_offload_to_artifact(b"") is False


# ---------------------------------------------------------------------------
# Phase 1: Graceful None returns (NFR-004)
# ---------------------------------------------------------------------------

class TestGracefulNoService:
    """NFR-004: Helper functions return None/[]/False when no artifact service."""

    async def test_save_repl_output_no_service(self):
        from rlm_adk.artifacts import save_repl_output
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_repl_output(ctx, iteration=0, stdout="output")
        assert result is None

    async def test_save_worker_result_no_service(self):
        from rlm_adk.artifacts import save_worker_result
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_worker_result(ctx, worker_name="w1", iteration=0, result_text="r")
        assert result is None

    async def test_save_final_answer_no_service(self):
        from rlm_adk.artifacts import save_final_answer
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_final_answer(ctx, answer="42")
        assert result is None

    async def test_save_binary_artifact_no_service(self):
        from rlm_adk.artifacts import save_binary_artifact
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_binary_artifact(ctx, filename="f.bin", data=b"\x00", mime_type="application/octet-stream")
        assert result is None

    async def test_load_artifact_no_service(self):
        from rlm_adk.artifacts import load_artifact
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await load_artifact(ctx, "test.txt")
        assert result is None

    async def test_list_artifacts_no_service(self):
        from rlm_adk.artifacts import list_artifacts
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await list_artifacts(ctx)
        assert result == []

    async def test_delete_artifact_no_service(self):
        from rlm_adk.artifacts import delete_artifact
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await delete_artifact(ctx, "test.txt")
        assert result is False


# ---------------------------------------------------------------------------
# Phase 1: get_invocation_context helper (FR-010)
# ---------------------------------------------------------------------------

class TestGetInvocationContext:
    """FR-010: Context extraction utility works with both context types."""

    def test_returns_invocation_context_as_is(self):
        from rlm_adk.artifacts import get_invocation_context
        ctx = MagicMock()
        ctx.__class__.__name__ = "InvocationContext"
        # When it's not a CallbackContext, return as-is
        result = get_invocation_context(ctx)
        assert result is ctx

    def test_extracts_from_callback_context(self):
        from google.adk.agents.callback_context import CallbackContext
        from rlm_adk.artifacts import get_invocation_context
        ctx = MagicMock(spec=CallbackContext)
        inner = MagicMock()
        ctx._invocation_context = inner
        result = get_invocation_context(ctx)
        assert result is inner


# ---------------------------------------------------------------------------
# Phase 2: CRUD Operations (FR-002, FR-005)
# ---------------------------------------------------------------------------

class TestSaveAndLoadReplOutput:
    """FR-002: Save and load REPL output artifacts."""

    async def test_save_and_load_repl_output(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_output, load_artifact
        version = await save_repl_output(
            mock_invocation_context, iteration=0, stdout="Hello World"
        )
        assert version == 0
        loaded = await load_artifact(mock_invocation_context, "repl_output_iter_0.txt")
        assert loaded is not None
        # Text content should contain stdout
        if loaded.text:
            assert "Hello World" in loaded.text
        elif loaded.inline_data:
            assert b"Hello World" in loaded.inline_data.data

    async def test_save_repl_output_with_stderr(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_output, load_artifact
        version = await save_repl_output(
            mock_invocation_context, iteration=1, stdout="out", stderr="err"
        )
        assert version == 0
        loaded = await load_artifact(mock_invocation_context, "repl_output_iter_1.txt")
        assert loaded is not None


class TestSaveAndLoadWorkerResult:
    """FR-002: Save and load worker result artifacts."""

    async def test_save_and_load_worker_result(self, mock_invocation_context):
        from rlm_adk.artifacts import save_worker_result, load_artifact
        version = await save_worker_result(
            mock_invocation_context,
            worker_name="worker_1",
            iteration=3,
            result_text="Analysis complete: 42 findings",
        )
        assert version == 0
        loaded = await load_artifact(
            mock_invocation_context, "worker_worker_1_iter_3.txt"
        )
        assert loaded is not None


class TestSaveFinalAnswer:
    """FR-002: Save and load final answer artifacts."""

    async def test_save_final_answer(self, mock_invocation_context):
        from rlm_adk.artifacts import save_final_answer, load_artifact
        version = await save_final_answer(
            mock_invocation_context, answer="The answer is 42."
        )
        assert version == 0
        loaded = await load_artifact(mock_invocation_context, "final_answer.md")
        assert loaded is not None

    async def test_save_final_answer_markdown_mime(self, mock_invocation_context):
        """Final answer defaults to text/markdown mime type."""
        from rlm_adk.artifacts import save_final_answer
        version = await save_final_answer(
            mock_invocation_context, answer="# Answer\nDone."
        )
        assert version == 0


class TestSaveBinaryArtifact:
    """FR-002: Save and load binary artifacts."""

    async def test_save_binary_artifact(self, mock_invocation_context):
        from rlm_adk.artifacts import save_binary_artifact, load_artifact
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header
        version = await save_binary_artifact(
            mock_invocation_context,
            filename="chart.png",
            data=data,
            mime_type="image/png",
        )
        assert version == 0
        loaded = await load_artifact(mock_invocation_context, "chart.png")
        assert loaded is not None
        assert loaded.inline_data.data == data
        assert loaded.inline_data.mime_type == "image/png"


class TestArtifactVersioning:
    """FR-005: Repeated saves create new versions."""

    async def test_versioning_increments(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_output, load_artifact
        v0 = await save_repl_output(mock_invocation_context, iteration=0, stdout="v0")
        v1 = await save_repl_output(mock_invocation_context, iteration=0, stdout="v1")
        assert v0 == 0
        assert v1 == 1

    async def test_load_latest_version(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_output, load_artifact
        await save_repl_output(mock_invocation_context, iteration=0, stdout="v0")
        await save_repl_output(mock_invocation_context, iteration=0, stdout="v1")
        latest = await load_artifact(mock_invocation_context, "repl_output_iter_0.txt")
        assert latest is not None

    async def test_load_specific_version(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_output, load_artifact
        await save_repl_output(mock_invocation_context, iteration=0, stdout="v0")
        await save_repl_output(mock_invocation_context, iteration=0, stdout="v1")
        original = await load_artifact(
            mock_invocation_context, "repl_output_iter_0.txt", version=0
        )
        assert original is not None


class TestListArtifacts:
    """FR-002: List artifact filenames."""

    async def test_list_artifacts(self, mock_invocation_context):
        from rlm_adk.artifacts import list_artifacts, save_final_answer, save_repl_output
        await save_repl_output(mock_invocation_context, iteration=0, stdout="out")
        await save_final_answer(mock_invocation_context, answer="done")
        filenames = await list_artifacts(mock_invocation_context)
        assert "repl_output_iter_0.txt" in filenames
        assert "final_answer.md" in filenames

    async def test_list_artifacts_empty(self, mock_invocation_context):
        from rlm_adk.artifacts import list_artifacts
        filenames = await list_artifacts(mock_invocation_context)
        assert filenames == []


class TestDeleteArtifact:
    """FR-002: Delete artifacts."""

    async def test_delete_artifact(self, mock_invocation_context):
        from rlm_adk.artifacts import delete_artifact, list_artifacts, save_repl_output
        await save_repl_output(mock_invocation_context, iteration=0, stdout="out")
        result = await delete_artifact(mock_invocation_context, "repl_output_iter_0.txt")
        assert result is True
        filenames = await list_artifacts(mock_invocation_context)
        assert "repl_output_iter_0.txt" not in filenames

    async def test_delete_nonexistent_artifact(self, mock_invocation_context):
        """Deleting a nonexistent artifact should still return True (no error)."""
        from rlm_adk.artifacts import delete_artifact
        result = await delete_artifact(mock_invocation_context, "nonexistent.txt")
        assert result is True


# ---------------------------------------------------------------------------
# Phase 3: Scoping (FR-006)
# ---------------------------------------------------------------------------

class TestSessionScopedIsolation:
    """FR-006: Session-scoped artifacts are isolated between sessions."""

    async def test_session_scoped_artifact_isolation(self, artifact_service):
        """Artifacts in different sessions are isolated."""
        part = types.Part.from_text(text="session data")
        await artifact_service.save_artifact(
            app_name="test", user_id="u1", session_id="s1",
            filename="data.txt", artifact=part,
        )
        loaded = await artifact_service.load_artifact(
            app_name="test", user_id="u1", session_id="s2",
            filename="data.txt",
        )
        assert loaded is None  # Different session, not found


class TestUserScopedArtifacts:
    """FR-006: User-scoped artifacts accessible across sessions."""

    async def test_user_scoped_artifact_cross_session(self, artifact_service):
        """User-scoped artifacts are accessible across sessions."""
        part = types.Part.from_text(text="user config")
        await artifact_service.save_artifact(
            app_name="test", user_id="u1", session_id="s1",
            filename="user:config.json", artifact=part,
        )
        loaded = await artifact_service.load_artifact(
            app_name="test", user_id="u1",
            filename="user:config.json",
        )
        assert loaded is not None
        assert loaded.text == "user config"


# ---------------------------------------------------------------------------
# Phase 6: Error Handling (NFR-004)
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """NFR-004: Graceful error handling in artifact operations."""

    async def test_save_handles_service_error(self):
        """Save returns None on service errors, does not raise."""
        from rlm_adk.artifacts import save_repl_output
        ctx = MagicMock()
        ctx.artifact_service = MagicMock()
        ctx.artifact_service.save_artifact = AsyncMock(side_effect=Exception("disk full"))
        ctx.app_name = "test"
        ctx.session = MagicMock()
        ctx.session.id = "s1"
        ctx.session.user_id = "u1"
        ctx.session.state = {}
        result = await save_repl_output(ctx, iteration=0, stdout="data")
        assert result is None  # Graceful failure, no exception raised

    async def test_load_returns_none_for_missing(self, mock_invocation_context):
        """Loading a nonexistent artifact returns None."""
        from rlm_adk.artifacts import load_artifact
        result = await load_artifact(mock_invocation_context, "nonexistent.txt")
        assert result is None

    async def test_load_handles_service_error(self):
        """Load returns None on service errors, does not raise."""
        from rlm_adk.artifacts import load_artifact
        ctx = MagicMock()
        ctx.artifact_service = MagicMock()
        ctx.artifact_service.load_artifact = AsyncMock(side_effect=Exception("network error"))
        ctx.app_name = "test"
        ctx.session = MagicMock()
        ctx.session.id = "s1"
        ctx.session.user_id = "u1"
        ctx.session.state = {}
        result = await load_artifact(ctx, "test.txt")
        assert result is None

    async def test_list_handles_service_error(self):
        """List returns empty list on service errors."""
        from rlm_adk.artifacts import list_artifacts
        ctx = MagicMock()
        ctx.artifact_service = MagicMock()
        ctx.artifact_service.list_artifact_keys = AsyncMock(side_effect=Exception("error"))
        ctx.app_name = "test"
        ctx.session = MagicMock()
        ctx.session.id = "s1"
        ctx.session.user_id = "u1"
        ctx.session.state = {}
        result = await list_artifacts(ctx)
        assert result == []

    async def test_delete_handles_service_error(self):
        """Delete returns False on service errors."""
        from rlm_adk.artifacts import delete_artifact
        ctx = MagicMock()
        ctx.artifact_service = MagicMock()
        ctx.artifact_service.delete_artifact = AsyncMock(side_effect=Exception("error"))
        ctx.app_name = "test"
        ctx.session = MagicMock()
        ctx.session.id = "s1"
        ctx.session.user_id = "u1"
        ctx.session.state = {}
        result = await delete_artifact(ctx, "test.txt")
        assert result is False
