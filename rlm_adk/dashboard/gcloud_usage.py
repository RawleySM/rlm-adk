"""Cloud Monitoring REST API client for token usage reconciliation.

Fetches ``generativelanguage.googleapis.com`` quota metrics from Google
Cloud Monitoring.  Uses ``gcloud auth print-access-token`` for OAuth
bearer tokens.

Graceful degradation:
- Returns ``None`` if no gcloud credentials are available
- Returns ``None`` if the Cloud Monitoring API is unreachable
- Never raises -- all errors are caught and logged
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Any

from rlm_adk.dashboard.data_models import APITokenUsage, ModelTokenUsage

logger = logging.getLogger(__name__)

_INPUT_TOKEN_METRIC = (
    "generativelanguage.googleapis.com/quota/"
    "generate_content_paid_tier_input_token_count/usage"
)
_REQUEST_COUNT_METRIC = (
    "generativelanguage.googleapis.com/quota/"
    "generate_requests_per_model/usage"
)
_MONITORING_API_BASE = "https://monitoring.googleapis.com/v3"


class GCloudUsageClient:
    """Fetches token usage from Google Cloud Monitoring API."""

    def __init__(self, project_id: str | None = None):
        self._project_id = project_id or "geminilogs"

    async def fetch_usage(
        self,
        start_time: float,
        end_time: float,
        project_id: str | None = None,
    ) -> APITokenUsage | None:
        """Fetch token usage for a time range.

        Returns ``None`` if credentials are unavailable or API errors out.
        """
        try:
            token = await self._get_access_token()
            if token is None:
                return None

            project = project_id or self._project_id
            start_iso = datetime.fromtimestamp(start_time, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            # Extend end time by 5 minutes to account for monitoring ingest delay
            end_iso = datetime.fromtimestamp(end_time + 300, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            # Fetch input token counts
            input_data = await self._query_metric(
                token, project, _INPUT_TOKEN_METRIC, start_iso, end_iso
            )

            # Fetch request counts
            request_data = await self._query_metric(
                token, project, _REQUEST_COUNT_METRIC, start_iso, end_iso
            )

            # Parse time series into per-model usage
            per_model: dict[str, ModelTokenUsage] = {}
            total_input = 0
            total_calls = 0

            if input_data:
                for ts in input_data.get("timeSeries", []):
                    model = ts.get("metric", {}).get("labels", {}).get("model", "unknown")
                    tokens = sum(
                        int(p.get("value", {}).get("int64Value", 0))
                        for p in ts.get("points", [])
                    )
                    if model not in per_model:
                        per_model[model] = ModelTokenUsage(
                            model=model, input_tokens=0, output_tokens=0, calls=0
                        )
                    # Deduplicate by taking max across limit_name entries
                    per_model[model].input_tokens = max(
                        per_model[model].input_tokens, tokens
                    )
                    total_input = max(total_input, sum(
                        m.input_tokens for m in per_model.values()
                    ))

            if request_data:
                for ts in request_data.get("timeSeries", []):
                    model = ts.get("metric", {}).get("labels", {}).get("model", "unknown")
                    calls = sum(
                        int(p.get("value", {}).get("int64Value", 0))
                        for p in ts.get("points", [])
                    )
                    if model not in per_model:
                        per_model[model] = ModelTokenUsage(
                            model=model, input_tokens=0, output_tokens=0, calls=0
                        )
                    per_model[model].calls = max(per_model[model].calls, calls)
                    total_calls = sum(m.calls for m in per_model.values())

            # Recompute totals from deduplicated per-model data
            total_input = sum(m.input_tokens for m in per_model.values())
            total_calls = sum(m.calls for m in per_model.values())

            return APITokenUsage(
                source="gcloud_monitoring",
                total_input_tokens=total_input,
                total_output_tokens=0,  # Cloud Monitoring does not track output tokens
                total_calls=total_calls,
                per_model=per_model,
            )

        except Exception as e:
            logger.debug("GCloudUsageClient.fetch_usage error: %s", e)
            return None

    async def _get_access_token(self) -> str | None:
        """Get OAuth access token via ``gcloud auth print-access-token``."""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["gcloud", "auth", "print-access-token"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    return token
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        except Exception:
            return None

    async def _query_metric(
        self,
        token: str,
        project: str,
        metric_type: str,
        start_iso: str,
        end_iso: str,
    ) -> dict[str, Any] | None:
        """Query a specific metric from Cloud Monitoring REST API."""
        try:
            import urllib.parse
            import urllib.request

            filter_str = f'metric.type="{metric_type}"'
            params = urllib.parse.urlencode({
                "filter": filter_str,
                "interval.startTime": start_iso,
                "interval.endTime": end_iso,
                "aggregation.alignmentPeriod": "86400s",
                "aggregation.perSeriesAligner": "ALIGN_SUM",
            })

            url = (
                f"{_MONITORING_API_BASE}/projects/{project}/timeSeries?{params}"
            )

            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token}")

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=15),
            )
            data = json.loads(response.read().decode("utf-8"))
            return data

        except Exception as e:
            logger.debug("Cloud Monitoring query error for %s: %s", metric_type, e)
            return None
