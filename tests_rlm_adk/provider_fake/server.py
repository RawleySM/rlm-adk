"""Fake Gemini API server for deterministic testing.

Serves ``POST /v1beta/models/{model}:generateContent`` with responses
driven by a :class:`ScenarioRouter`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from .fixtures import ScenarioRouter

logger = logging.getLogger(__name__)


class FakeGeminiServer:
    """Lightweight aiohttp server emulating the Gemini generateContent endpoint."""

    def __init__(
        self,
        router: ScenarioRouter,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.router = router
        self._host = host
        self._port = port  # 0 = OS-assigned
        self._app = web.Application()
        self._app.router.add_post(
            "/v1beta/models/{model}:generateContent",
            self._handle_generate_content,
        )
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._base_url: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> str:
        """Start the server and return its base URL (e.g. ``http://127.0.0.1:54321``)."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        # Resolve the actual port (useful when port=0)
        sock = self._site._server.sockets[0]  # type: ignore[union-attr]
        actual_port = sock.getsockname()[1]
        self._base_url = f"http://{self._host}:{actual_port}"
        logger.info("FakeGeminiServer started at %s", self._base_url)
        return self._base_url

    async def stop(self) -> None:
        """Shut down the server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
        logger.info("FakeGeminiServer stopped")

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    async def _handle_generate_content(self, request: web.Request) -> web.Response:
        """Handle POST /v1beta/models/{model}:generateContent."""

        # Validate API key header is present (accept any value)
        api_key = request.headers.get("x-goog-api-key", "")
        if not api_key:
            return web.json_response(
                {"error": {"code": 401, "message": "Missing API key", "status": "UNAUTHENTICATED"}},
                status=401,
            )

        # Parse request body
        try:
            body: dict[str, Any] = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(
                {"error": {"code": 400, "message": "Invalid JSON body", "status": "INVALID_ARGUMENT"}},
                status=400,
            )

        model_name = request.match_info.get("model", "unknown")
        logger.debug(
            "FakeGeminiServer: model=%s contents_count=%d has_system=%s",
            model_name,
            len(body.get("contents", [])),
            bool(body.get("systemInstruction")),
        )

        # Get next scripted response
        status_code, response_body = self.router.next_response(
            body, request_meta={"model": model_name},
        )

        # Handle malformed JSON fault
        if status_code == -1:
            raw = response_body.get("_raw", "{bad json")
            return web.Response(
                text=raw,
                content_type="application/json",
                status=200,
            )

        return web.json_response(response_body, status=status_code)
