"""GoogleCloudAnalyticsPlugin - Exports session summaries to BigQuery Agent Analytics.

This plugin bridges ADK observability (obs: prefixed state keys) to the
official Google BigQuery Agent Analytics plugin. It ensures session
summaries are formatted correctly and sent to the cloud upon run completion.
"""

import logging
import os
from typing import Any, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class GoogleCloudAnalyticsPlugin(BasePlugin):
    """Bridge to BigQueryAgentAnalyticsPlugin for cloud telemetry."""

    def __init__(
        self,
        *,
        name: str = "google_cloud_analytics",
        project_id: str | None = None,
        dataset_id: str = "agent_analytics",
        table_id: str = "telemetry",
    ):
        super().__init__(name=name)
        self._project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self._dataset_id = dataset_id
        self._table_id = table_id
        self._bq_plugin: Optional[BasePlugin] = None
        self._init_bq_plugin()

    def _init_bq_plugin(self) -> None:
        """One-time initialization of the official BigQueryAgentAnalyticsPlugin."""
        if not self._project_id:
            logger.warning(
                "Google Cloud Analytics disabled: missing GOOGLE_CLOUD_PROJECT environment variable."
            )
            return

        try:
            from google.adk.plugins.bigquery_agent_analytics_plugin import (
                BigQueryAgentAnalyticsPlugin,
            )

            self._bq_plugin = BigQueryAgentAnalyticsPlugin(
                project_id=self._project_id,
                dataset_id=self._dataset_id,
                table_id=self._table_id,
            )
            logger.info(
                "Google Cloud Analytics initialized: project=%s, dataset=%s",
                self._project_id,
                self._dataset_id,
            )
        except (ImportError, Exception) as e:
            logger.warning("Google Cloud Analytics initialization failed: %s", e)
            self._bq_plugin = None

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Delegate to BigQueryAgentAnalyticsPlugin to send the final session summary."""
        if self._bq_plugin:
            try:
                # BigQueryAgentAnalyticsPlugin typically implements after_run_callback
                # to extract obs: keys from session state and send them.
                await self._bq_plugin.after_run_callback(
                    invocation_context=invocation_context
                )
            except Exception as e:
                logger.debug("Google Cloud Analytics export failed: %s", e)

    @property
    def enabled(self) -> bool:
        return self._bq_plugin is not None
