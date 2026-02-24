"""Pytest fixtures for provider-fake tests.

Provides ``fake_gemini`` — an async fixture that starts a
:class:`FakeGeminiServer`, sets the env vars to redirect all
google-genai SDK traffic to it, and tears everything down after.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

import pytest

from .fixtures import ScenarioRouter
from .server import FakeGeminiServer

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "provider_fake"


@pytest.fixture
async def fake_gemini(request) -> AsyncIterator[FakeGeminiServer]:
    """Start a fake Gemini server from a parametrised fixture file.

    Usage::

        @pytest.mark.parametrize("fake_gemini", [
            FIXTURE_DIR / "happy_path_single_iteration.json",
        ], indirect=True)
        async def test_foo(fake_gemini):
            ...
    """
    fixture_path: Path = request.param
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
    url = await server.start()

    # Save and override env vars
    saved = {}
    for key in ("GOOGLE_GEMINI_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        saved[key] = os.environ.get(key)

    os.environ["GOOGLE_GEMINI_BASE_URL"] = url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    # Remove GOOGLE_API_KEY to avoid precedence issues
    os.environ.pop("GOOGLE_API_KEY", None)

    # Also set fast retry for tests
    os.environ.setdefault("RLM_LLM_RETRY_DELAY", "0.01")
    os.environ.setdefault("RLM_LLM_MAX_RETRIES", "3")

    yield server

    await server.stop()

    # Restore env vars
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val
