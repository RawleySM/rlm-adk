"""LangfuseTracingPlugin - OpenTelemetry-based tracing to self-hosted Langfuse.

Initializes the Langfuse client and Google ADK OpenInference instrumentor
so that every model call, tool invocation, and agent transition is captured
as an OTel span and forwarded to Langfuse automatically.

The plugin is a thin wrapper: all actual tracing is handled by the
``openinference-instrumentation-google-adk`` package.  This plugin simply
ensures initialization happens once and in the right order.

Requires environment variables:
    LANGFUSE_PUBLIC_KEY  - Project public key
    LANGFUSE_SECRET_KEY  - Project secret key
    LANGFUSE_BASE_URL    - Self-hosted Langfuse URL (e.g. http://localhost:3100)
"""

import logging
import os

from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

_INSTRUMENTED = False


def _init_langfuse_instrumentation() -> bool:
    """One-time initialization of Langfuse + GoogleADK OTel instrumentation.

    Returns True if instrumentation was successfully initialized.
    """
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return True

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL")

    if not all([public_key, secret_key, base_url]):
        logger.warning(
            "Langfuse tracing disabled: missing LANGFUSE_PUBLIC_KEY, "
            "LANGFUSE_SECRET_KEY, or LANGFUSE_BASE_URL environment variables."
        )
        return False

    try:
        from langfuse import get_client
        from openinference.instrumentation.google_adk import GoogleADKInstrumentor

        # Authenticate the Langfuse client
        client = get_client()
        if not client.auth_check():
            logger.error(
                "Langfuse authentication failed. Check credentials and base URL (%s).",
                base_url,
            )
            return False

        # Instrument Google ADK with OpenInference
        GoogleADKInstrumentor().instrument()

        _INSTRUMENTED = True
        logger.info(
            "Langfuse tracing initialized: base_url=%s, project_key=%s...",
            base_url,
            public_key[:12] + "..." if len(public_key) > 12 else public_key,
        )
        return True

    except ImportError as e:
        logger.warning(
            "Langfuse tracing disabled: missing dependency (%s). "
            "Install with: pip install langfuse openinference-instrumentation-google-adk",
            e,
        )
        return False
    except Exception as e:
        logger.error("Langfuse tracing initialization failed: %s", e)
        return False


class LangfuseTracingPlugin(BasePlugin):
    """ADK Plugin that enables Langfuse OpenTelemetry tracing.

    All actual span creation is handled automatically by the
    ``GoogleADKInstrumentor``.  This plugin's role is to:

    1. Trigger one-time initialization of the instrumentor.
    2. Provide a clean on/off toggle via the plugin system.
    3. Log whether tracing is active for operational visibility.

    The plugin is safe to include even when Langfuse env vars are not set:
    initialization is skipped with a warning and no callbacks fire.
    """

    def __init__(self, *, name: str = "langfuse_tracing"):
        super().__init__(name=name)
        self._enabled = _init_langfuse_instrumentation()

    @property
    def enabled(self) -> bool:
        return self._enabled
