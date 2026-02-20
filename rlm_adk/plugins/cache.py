"""CachePlugin - Global LLM response cache using intervene pattern.

Trigger points: before_model_callback (check), after_model_callback (store)
State keys: cache:store, cache:hit_count, cache:miss_count, cache:last_hit_key
"""

import hashlib
import logging
import time
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from rlm_adk.state import (
    CACHE_HIT_COUNT,
    CACHE_LAST_HIT_KEY,
    CACHE_MISS_COUNT,
    CACHE_STORE,
)

logger = logging.getLogger(__name__)

# State key for passing fingerprint from before_model to after_model
_CACHE_PENDING_FP = "cache_pending_fingerprint"


class CachePlugin(BasePlugin):
    """Caches LLM responses by request fingerprint.

    - before_model_callback: Check cache. If hit, return cached response (intervene).
      Also stores fingerprint in temp state for after_model_callback.
    - after_model_callback: Store response in cache using the pending fingerprint.
    """

    def __init__(
        self,
        *,
        name: str = "cache",
        max_entries: int = 1000,
        ttl_seconds: float = 300.0,
    ):
        super().__init__(name=name)
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Check cache for matching request. Store fingerprint for after_model."""
        try:
            state = callback_context.state
            fingerprint = _fingerprint(llm_request)

            # Always store fingerprint so after_model_callback can use it
            state[_CACHE_PENDING_FP] = fingerprint

            cache_store: dict = state.get(CACHE_STORE, {})

            if fingerprint in cache_store:
                entry = cache_store[fingerprint]
                if time.time() - entry.get("timestamp", 0) < self.ttl_seconds:
                    state[CACHE_HIT_COUNT] = state.get(CACHE_HIT_COUNT, 0) + 1
                    state[CACHE_LAST_HIT_KEY] = fingerprint
                    logger.info("Cache hit: %s...", fingerprint[:12])
                    return _deserialize_response(entry["response"])
                else:
                    del cache_store[fingerprint]
                    state[CACHE_STORE] = cache_store

            state[CACHE_MISS_COUNT] = state.get(CACHE_MISS_COUNT, 0) + 1
            return None

        except Exception as e:
            logger.warning("Cache check error: %s", e)
            return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Store response in cache after successful model call."""
        try:
            state = callback_context.state
            pending_fp = state.get(_CACHE_PENDING_FP)
            if not pending_fp:
                return None

            cache_store: dict = state.get(CACHE_STORE, {})
            cache_store[pending_fp] = {
                "response": _serialize_response(llm_response),
                "timestamp": time.time(),
            }

            # LRU eviction if over capacity
            if len(cache_store) > self.max_entries:
                sorted_keys = sorted(
                    cache_store.keys(),
                    key=lambda k: cache_store[k].get("timestamp", 0),
                )
                for key in sorted_keys[: len(cache_store) - self.max_entries]:
                    del cache_store[key]

            state[CACHE_STORE] = cache_store

        except Exception as e:
            logger.warning("Cache store error: %s", e)

        return None


def _fingerprint(llm_request: LlmRequest) -> str:
    """Generate cache key from LlmRequest.

    Key format: SHA-256(model || prompt_normalized || system_instruction_hash || temperature)
    """
    parts: list[str] = []

    # Model name
    model = (llm_request.model or "").lower().strip()
    parts.append(model)

    # Prompt content - concatenate all text parts
    content_text = ""
    for content in llm_request.contents:
        if content.parts:
            for part in content.parts:
                if hasattr(part, "text") and part.text:
                    content_text += part.text
    parts.append(content_text.rstrip())

    # System instruction hash
    sys_instruction = ""
    if llm_request.config:
        si = getattr(llm_request.config, "system_instruction", None)
        if si:
            sys_instruction = str(si)
    parts.append(hashlib.sha256(sys_instruction.encode()).hexdigest())

    # Temperature
    temperature = 0.0
    if llm_request.config:
        temp = getattr(llm_request.config, "temperature", None)
        if temp is not None:
            temperature = float(temp)
    parts.append(str(temperature))

    combined = "||".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()


def _serialize_response(llm_response: LlmResponse) -> dict:
    """Serialize LlmResponse to JSON-safe dict."""
    try:
        text = ""
        if llm_response.content and llm_response.content.parts:
            for part in llm_response.content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
        return {"text": text}
    except Exception:
        return {"text": ""}


def _deserialize_response(data: dict) -> LlmResponse:
    """Deserialize cached response back to LlmResponse."""
    text = data.get("text", "")
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )
