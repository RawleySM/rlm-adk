"""ADK CLI service registry for RLM-ADK.

This module is auto-discovered by ``google.adk.cli.service_registry.load_services_module()``
when ``adk run rlm_adk`` or ``adk web rlm_adk`` is invoked.  It overrides the
built-in ``sqlite`` and ``file`` schemes so the CLI-created Runner gets the same
WAL-pragma'd SQLite session service and file-based artifact service that
``create_rlm_runner()`` provides programmatically — no CLI flags needed.

Registered schemes (override built-ins):
    sqlite://<db_path>  -- SqliteSessionService with WAL mode + performance pragmas
    file://<root_dir>   -- FileArtifactService with the given root directory
"""

import logging
from urllib.parse import urlparse

from google.adk.cli.service_registry import ServiceRegistry, get_service_registry

logger = logging.getLogger(__name__)


def _rlm_session_factory(uri: str, **kwargs):
    """Create a SqliteSessionService with WAL pragmas from a URI.

    Reuses ``_default_session_service()`` from ``rlm_adk.agent`` to avoid
    duplicating the WAL pragma logic.

    URI format: ``sqlite://<db_path>``
    If no path is provided, falls back to the default path (RLM_SESSION_DB
    env var or ``.adk/session.db``).
    """
    from rlm_adk.agent import _default_session_service

    parsed = urlparse(uri)
    # netloc + path gives the full file path after the scheme
    db_path = parsed.netloc + parsed.path if (parsed.netloc or parsed.path) else None
    # Pass None to let _default_session_service use its own default resolution
    return _default_session_service(db_path=db_path or None)


def _rlm_artifact_factory(uri: str, **kwargs):
    """Create a FileArtifactService from a URI.

    URI format: ``file://<root_dir>``
    If no path is provided, falls back to the default ``.adk/artifacts``.
    """
    from google.adk.artifacts import FileArtifactService

    from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT

    parsed = urlparse(uri)
    root_dir = parsed.netloc + parsed.path if (parsed.netloc or parsed.path) else _DEFAULT_ARTIFACT_ROOT
    return FileArtifactService(root_dir=root_dir)


def register_services(registry: ServiceRegistry | None = None) -> None:
    """Register RLM-ADK service factories in the given (or global) registry.

    Args:
        registry: The ServiceRegistry to register on.  When ``None``,
            uses the global singleton from ``get_service_registry()``.
    """
    if registry is None:
        registry = get_service_registry()
    registry.register_session_service("sqlite", _rlm_session_factory)
    registry.register_artifact_service("file", _rlm_artifact_factory)
    logger.info("RLM-ADK service factories registered (sqlite, file) — overrides built-ins")


# Auto-register when this module is imported (ADK CLI discovery path).
register_services()
