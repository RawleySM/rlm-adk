"""PS-001: Cache plugin behavior.

- Cache check on before_model_callback; cache store on after_model_callback.
- Cache hit should short-circuit model call with cached response.
- Cache hit/miss counters and last-hit key must be tracked in state.
"""

import time
from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.plugins.cache import CachePlugin, _fingerprint
from rlm_adk.state import CACHE_HIT_COUNT, CACHE_LAST_HIT_KEY, CACHE_MISS_COUNT, CACHE_STORE


def _make_callback_context(state: dict | None = None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def _make_request(text: str = "hello", model: str = "test-model") -> LlmRequest:
    return LlmRequest(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            )
        ],
    )


def _make_response(text: str = "world") -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )


class TestCacheFingerprint:
    """Fingerprint generation is deterministic and stable."""

    def test_same_request_same_fingerprint(self):
        r1 = _make_request("hello")
        r2 = _make_request("hello")
        assert _fingerprint(r1) == _fingerprint(r2)

    def test_different_text_different_fingerprint(self):
        r1 = _make_request("hello")
        r2 = _make_request("goodbye")
        assert _fingerprint(r1) != _fingerprint(r2)

    def test_different_model_different_fingerprint(self):
        r1 = _make_request("hello", model="model-a")
        r2 = _make_request("hello", model="model-b")
        assert _fingerprint(r1) != _fingerprint(r2)


class TestCacheMiss:
    """Cache miss: before_model returns None (proceeds to model)."""

    @pytest.mark.asyncio
    async def test_empty_cache_miss(self):
        plugin = CachePlugin(name="cache")
        state = {}
        ctx = _make_callback_context(state)
        request = _make_request()

        result = await plugin.before_model_callback(callback_context=ctx, llm_request=request)

        assert result is None
        assert state[CACHE_MISS_COUNT] == 1

    @pytest.mark.asyncio
    async def test_miss_stores_pending_fingerprint(self):
        plugin = CachePlugin(name="cache")
        state = {}
        ctx = _make_callback_context(state)
        request = _make_request()

        await plugin.before_model_callback(callback_context=ctx, llm_request=request)

        assert "cache_pending_fingerprint" in state


class TestCacheStore:
    """after_model_callback stores response in cache."""

    @pytest.mark.asyncio
    async def test_stores_after_model(self):
        plugin = CachePlugin(name="cache")
        request = _make_request()
        response = _make_response("cached answer")

        # Simulate before_model (sets pending fingerprint)
        state = {}
        ctx = _make_callback_context(state)
        await plugin.before_model_callback(callback_context=ctx, llm_request=request)

        # Simulate after_model (stores response)
        await plugin.after_model_callback(callback_context=ctx, llm_response=response)

        assert CACHE_STORE in state
        assert len(state[CACHE_STORE]) == 1


class TestCacheHit:
    """Cache hit: before_model returns cached LlmResponse."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_response(self):
        plugin = CachePlugin(name="cache")
        request = _make_request("hello")
        response = _make_response("cached answer")

        # First call: miss + store
        state = {}
        ctx = _make_callback_context(state)
        await plugin.before_model_callback(callback_context=ctx, llm_request=request)
        await plugin.after_model_callback(callback_context=ctx, llm_response=response)

        # Second call: hit
        request2 = _make_request("hello")
        hit_result = await plugin.before_model_callback(callback_context=ctx, llm_request=request2)

        assert hit_result is not None
        assert hit_result.content.parts[0].text == "cached answer"
        assert state[CACHE_HIT_COUNT] == 1
        assert CACHE_LAST_HIT_KEY in state

    @pytest.mark.asyncio
    async def test_hit_miss_counters(self):
        plugin = CachePlugin(name="cache")
        state = {}
        ctx = _make_callback_context(state)

        # Miss
        req = _make_request("q1")
        await plugin.before_model_callback(callback_context=ctx, llm_request=req)
        await plugin.after_model_callback(callback_context=ctx, llm_response=_make_response("a1"))

        # Miss (different request)
        req2 = _make_request("q2")
        await plugin.before_model_callback(callback_context=ctx, llm_request=req2)
        await plugin.after_model_callback(callback_context=ctx, llm_response=_make_response("a2"))

        # Hit
        req3 = _make_request("q1")
        await plugin.before_model_callback(callback_context=ctx, llm_request=req3)

        assert state[CACHE_MISS_COUNT] == 2
        assert state[CACHE_HIT_COUNT] == 1


class TestCacheTTL:
    """Expired entries should be treated as misses."""

    @pytest.mark.asyncio
    async def test_expired_entry_is_miss(self):
        plugin = CachePlugin(name="cache", ttl_seconds=0.0)  # immediate expiry
        request = _make_request()
        response = _make_response("old")

        state = {}
        ctx = _make_callback_context(state)

        # Store
        await plugin.before_model_callback(callback_context=ctx, llm_request=request)
        await plugin.after_model_callback(callback_context=ctx, llm_response=response)

        # Try to hit (should miss due to TTL=0)
        time.sleep(0.01)
        result = await plugin.before_model_callback(callback_context=ctx, llm_request=request)
        assert result is None


class TestCacheEviction:
    """LRU eviction when over max_entries."""

    @pytest.mark.asyncio
    async def test_evicts_oldest(self):
        plugin = CachePlugin(name="cache", max_entries=2)
        state = {}
        ctx = _make_callback_context(state)

        # Fill cache with 3 entries (max=2)
        for i in range(3):
            req = _make_request(f"q{i}")
            await plugin.before_model_callback(callback_context=ctx, llm_request=req)
            await plugin.after_model_callback(
                callback_context=ctx, llm_response=_make_response(f"a{i}")
            )
            time.sleep(0.01)  # ensure timestamp ordering

        assert len(state[CACHE_STORE]) == 2
