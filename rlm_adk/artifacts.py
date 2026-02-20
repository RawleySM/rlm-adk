"""Artifact helper functions for the RLM ADK application.

Provides convenience wrappers around ADK's BaseArtifactService for common
artifact operations within the RLM orchestrator loop and callbacks.

Design principles:
- All functions accept InvocationContext (or CallbackContext via extraction)
- All functions return None/[]/False gracefully when no artifact service is configured
- All async functions wrap operations in try/except with warning-level logging (NFR-004)
- should_offload_to_artifact and get_invocation_context are synchronous
- Naming conventions: repl_output_iter_{N}.txt, worker_{name}_iter_{N}.txt, final_answer.md
"""

import logging
from typing import Optional, Union

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.genai import types

from rlm_adk.state import (
    ARTIFACT_LAST_SAVED_FILENAME,
    ARTIFACT_LAST_SAVED_VERSION,
    ARTIFACT_LOAD_COUNT,
    ARTIFACT_SAVE_COUNT,
    ARTIFACT_TOTAL_BYTES_SAVED,
)

logger = logging.getLogger(__name__)


def get_invocation_context(
    ctx: Union[InvocationContext, CallbackContext],
) -> InvocationContext:
    """Extract InvocationContext from either InvocationContext or CallbackContext.

    Args:
        ctx: An InvocationContext or CallbackContext instance.

    Returns:
        The underlying InvocationContext.
    """
    if isinstance(ctx, CallbackContext):
        return ctx._invocation_context
    return ctx


def should_offload_to_artifact(data: Union[str, bytes], threshold: int = 10240) -> bool:
    """Determine if data should be stored as artifact vs. inline in state.

    Args:
        data: The data to check (string or bytes).
        threshold: Byte threshold (default 10KB). Data larger than this
            should be offloaded to an artifact.

    Returns:
        True if len(data) > threshold.
    """
    return len(data) > threshold


async def save_repl_output(
    ctx: Union[InvocationContext, CallbackContext],
    iteration: int,
    stdout: str,
    stderr: str = "",
    mime_type: str = "text/plain",
) -> Optional[int]:
    """Save REPL output as a versioned artifact.

    The artifact is named ``repl_output_iter_{iteration}.txt``.

    Args:
        ctx: InvocationContext or CallbackContext.
        iteration: The current orchestrator iteration number.
        stdout: Standard output text from the REPL execution.
        stderr: Standard error text (optional).
        mime_type: MIME type for the artifact (default text/plain).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping save_repl_output")
        return None

    filename = f"repl_output_iter_{iteration}.txt"
    content = stdout
    if stderr:
        content = f"{stdout}\n--- STDERR ---\n{stderr}"

    try:
        artifact = types.Part.from_bytes(data=content.encode("utf-8"), mime_type=mime_type)
        version = await inv_ctx.artifact_service.save_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            artifact=artifact,
        )
        _update_save_tracking(inv_ctx, filename, version, len(content.encode("utf-8")))
        return version
    except Exception as e:
        logger.warning("Failed to save REPL output artifact: %s", e)
        return None


async def save_repl_code(
    ctx: Union[InvocationContext, CallbackContext],
    iteration: int,
    turn: int,
    code: str,
) -> Optional[int]:
    """Save REPL code block as a versioned artifact.

    The artifact is named ``repl_code_iter_{iteration}_turn_{turn}.py``.

    Args:
        ctx: InvocationContext or CallbackContext.
        iteration: The current orchestrator iteration number.
        turn: The code block index within this iteration (0-based).
        code: The Python source code to save.

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping save_repl_code")
        return None

    filename = f"repl_code_iter_{iteration}_turn_{turn}.py"

    try:
        artifact = types.Part(text=code)
        version = await inv_ctx.artifact_service.save_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            artifact=artifact,
        )
        _update_save_tracking(inv_ctx, filename, version, len(code.encode("utf-8")))
        return version
    except Exception as e:
        logger.warning("Failed to save REPL code artifact: %s", e)
        return None


async def save_worker_result(
    ctx: Union[InvocationContext, CallbackContext],
    worker_name: str,
    iteration: int,
    result_text: str,
    mime_type: str = "text/plain",
) -> Optional[int]:
    """Save worker result as a versioned artifact.

    The artifact is named ``worker_{worker_name}_iter_{iteration}.txt``.

    Args:
        ctx: InvocationContext or CallbackContext.
        worker_name: Name of the worker agent.
        iteration: The current orchestrator iteration number.
        result_text: The worker's text response.
        mime_type: MIME type for the artifact (default text/plain).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping save_worker_result")
        return None

    filename = f"worker_{worker_name}_iter_{iteration}.txt"

    try:
        artifact = types.Part.from_bytes(data=result_text.encode("utf-8"), mime_type=mime_type)
        version = await inv_ctx.artifact_service.save_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            artifact=artifact,
        )
        _update_save_tracking(inv_ctx, filename, version, len(result_text.encode("utf-8")))
        return version
    except Exception as e:
        logger.warning("Failed to save worker result artifact: %s", e)
        return None


async def save_final_answer(
    ctx: Union[InvocationContext, CallbackContext],
    answer: str,
    mime_type: str = "text/markdown",
) -> Optional[int]:
    """Save the final answer as an artifact.

    The artifact is named ``final_answer.md``.

    Args:
        ctx: InvocationContext or CallbackContext.
        answer: The final answer text.
        mime_type: MIME type for the artifact (default text/markdown).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping save_final_answer")
        return None

    filename = "final_answer.md"

    try:
        artifact = types.Part.from_bytes(data=answer.encode("utf-8"), mime_type=mime_type)
        version = await inv_ctx.artifact_service.save_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            artifact=artifact,
        )
        _update_save_tracking(inv_ctx, filename, version, len(answer.encode("utf-8")))
        return version
    except Exception as e:
        logger.warning("Failed to save final answer artifact: %s", e)
        return None


async def save_binary_artifact(
    ctx: Union[InvocationContext, CallbackContext],
    filename: str,
    data: bytes,
    mime_type: str,
) -> Optional[int]:
    """Save arbitrary binary data as an artifact.

    Args:
        ctx: InvocationContext or CallbackContext.
        filename: The artifact filename.
        data: Raw binary data.
        mime_type: MIME type of the binary data.

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping save_binary_artifact")
        return None

    try:
        artifact = types.Part.from_bytes(data=data, mime_type=mime_type)
        version = await inv_ctx.artifact_service.save_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            artifact=artifact,
        )
        _update_save_tracking(inv_ctx, filename, version, len(data))
        return version
    except Exception as e:
        logger.warning("Failed to save binary artifact '%s': %s", filename, e)
        return None


async def load_artifact(
    ctx: Union[InvocationContext, CallbackContext],
    filename: str,
    version: Optional[int] = None,
) -> Optional[types.Part]:
    """Load an artifact by filename, optionally at a specific version.

    Args:
        ctx: InvocationContext or CallbackContext.
        filename: The artifact filename to load.
        version: Specific version to load. None loads the latest.

    Returns:
        The Part data, or None if not found, no service configured,
        or if the load operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping load_artifact")
        return None

    try:
        result = await inv_ctx.artifact_service.load_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            version=version,
        )
        if result is not None:
            state = inv_ctx.session.state
            state[ARTIFACT_LOAD_COUNT] = state.get(ARTIFACT_LOAD_COUNT, 0) + 1
        return result
    except Exception as e:
        logger.warning("Failed to load artifact '%s': %s", filename, e)
        return None


async def list_artifacts(
    ctx: Union[InvocationContext, CallbackContext],
) -> list[str]:
    """List all artifact filenames in the current session scope.

    Args:
        ctx: InvocationContext or CallbackContext.

    Returns:
        List of artifact filenames, or empty list if no service configured
        or if the operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping list_artifacts")
        return []

    try:
        return await inv_ctx.artifact_service.list_artifact_keys(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
        )
    except Exception as e:
        logger.warning("Failed to list artifacts: %s", e)
        return []


async def delete_artifact(
    ctx: Union[InvocationContext, CallbackContext],
    filename: str,
) -> bool:
    """Delete an artifact and all its versions.

    Args:
        ctx: InvocationContext or CallbackContext.
        filename: The artifact filename to delete.

    Returns:
        True if deleted (or no-op for nonexistent), False if no service
        configured or if the operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping delete_artifact")
        return False

    try:
        await inv_ctx.artifact_service.delete_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
        )
        return True
    except Exception as e:
        logger.warning("Failed to delete artifact '%s': %s", filename, e)
        return False


def _update_save_tracking(
    ctx: InvocationContext,
    filename: str,
    version: int,
    size_bytes: int,
) -> None:
    """Update session state with artifact save tracking metadata.

    Args:
        ctx: The InvocationContext.
        filename: The saved artifact filename.
        version: The version number returned by the service.
        size_bytes: Size of the saved data in bytes.
    """
    try:
        state = ctx.session.state
        state[ARTIFACT_SAVE_COUNT] = state.get(ARTIFACT_SAVE_COUNT, 0) + 1
        state[ARTIFACT_TOTAL_BYTES_SAVED] = state.get(ARTIFACT_TOTAL_BYTES_SAVED, 0) + size_bytes
        state[ARTIFACT_LAST_SAVED_FILENAME] = filename
        state[ARTIFACT_LAST_SAVED_VERSION] = version
    except Exception as e:
        logger.debug("Failed to update artifact save tracking: %s", e)
