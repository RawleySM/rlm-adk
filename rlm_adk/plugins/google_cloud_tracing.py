"""GoogleCloudTracingPlugin - OpenTelemetry tracing to Google Cloud Trace.

This plugin configures the OpenTelemetry SDK to export spans to Google Cloud
Trace using the CloudTraceSpanExporter. It instruments the Google ADK
automatically to capture agent calls, tool invocations, and model interactions.

This works alongside local tracing (SqliteTracingPlugin) and Langfuse.
"""

import logging
import os

from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

_INSTRUMENTED = False


def _init_cloud_trace_instrumentation() -> bool:
    """One-time initialization of Cloud Trace + GoogleADK OTel instrumentation."""
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from openinference.instrumentation.google_adk import GoogleADKInstrumentor

        # Check if project ID is available
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            logger.warning(
                "Google Cloud Trace disabled: missing GOOGLE_CLOUD_PROJECT environment variable."
            )
            return False

        # Ensure a TracerProvider is set. If one already exists (e.g. from Langfuse),
        # we add our exporter to it if possible, otherwise we set a new one.
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)

        # Add Cloud Trace exporter
        exporter = CloudTraceSpanExporter(project_id=project_id)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Instrument Google ADK with OpenInference (idempotent)
        GoogleADKInstrumentor().instrument()

        _INSTRUMENTED = True
        logger.info(
            "Google Cloud Trace tracing initialized for project: %s",
            project_id,
        )
        return True

    except ImportError as e:
        logger.warning(
            "Google Cloud Trace tracing disabled: missing dependency (%s). "
            "Install with: pip install opentelemetry-exporter-gcp-trace openinference-instrumentation-google-adk",
            e,
        )
        return False
    except Exception as e:
        logger.error("Google Cloud Trace tracing initialization failed: %s", e)
        return False


class GoogleCloudTracingPlugin(BasePlugin):
    """ADK Plugin that enables Google Cloud Trace OpenTelemetry tracing."""

    def __init__(self, *, name: str = "google_cloud_tracing"):
        super().__init__(name=name)
        self._enabled = _init_cloud_trace_instrumentation()

    @property
    def enabled(self) -> bool:
        return self._enabled
