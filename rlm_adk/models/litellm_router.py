"""LiteLLM Router integration for RLM-ADK.

Provides RouterLiteLlmClient (drop-in LiteLLMClient replacement that delegates
to litellm.Router) and helper functions to build model lists from env vars.

Gated by RLM_ADK_LITELLM=1 env var at the call site (agent.py).
"""

import logging
import os
import threading
from typing import Any

from google.adk.models.lite_llm import LiteLLMClient

logger = logging.getLogger(__name__)

_litellm = None
_Router = None


def _ensure_litellm():
    global _litellm, _Router
    if _litellm is None:
        import litellm as _lit
        from litellm import Router as _R

        _litellm = _lit
        _Router = _R


class RouterLiteLlmClient(LiteLLMClient):
    """LiteLLMClient subclass that routes through litellm.Router.

    Inherits from ADK's ``LiteLLMClient`` so Pydantic ``isinstance`` checks
    pass when injected via ``LiteLlm(llm_client=...)``.
    """

    def __init__(
        self,
        model_list: list[dict[str, Any]],
        routing_strategy: str = "simple-shuffle",
        num_retries: int = 2,
        allowed_fails: int = 1,
        cooldown_time: int = 60,
        timeout: int | None = None,
        fallbacks: list[dict[str, list[str]]] | None = None,
        **kwargs: Any,
    ):
        _ensure_litellm()
        router_kwargs: dict[str, Any] = {
            "model_list": model_list,
            "routing_strategy": routing_strategy,
            "num_retries": num_retries,
            "allowed_fails": allowed_fails,
            "cooldown_time": cooldown_time,
        }
        if fallbacks:
            router_kwargs["fallbacks"] = fallbacks
        if timeout is not None:
            router_kwargs["timeout"] = timeout
        router_kwargs.update(kwargs)
        self._router = _Router(**router_kwargs)

    async def acompletion(self, model: str, messages: list, tools: Any, **kwargs: Any) -> Any:
        return await self._router.acompletion(model=model, messages=messages, tools=tools, **kwargs)

    def completion(
        self,
        model: str,
        messages: list,
        tools: Any,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        return self._router.completion(
            model=model, messages=messages, tools=tools, stream=stream, **kwargs
        )


# ---------------------------------------------------------------------------
# Provider configurations
# ---------------------------------------------------------------------------
_PROVIDER_CONFIGS: list[tuple[str, str, list[tuple[str, str, dict[str, Any]]]]] = [
    (
        "GEMINI_API_KEY",
        "gemini/",
        [
            ("gemini-2.5-pro", "reasoning", {"rpm": 10, "tpm": 4_000_000}),
            ("gemini-2.5-flash", "worker", {"rpm": 100, "tpm": 4_000_000}),
        ],
    ),
    (
        "OPENAI_API_KEY",
        "openai/",
        [
            ("o3", "reasoning", {"rpm": 30, "tpm": 1_000_000}),
            ("gpt-4o-mini", "worker", {"rpm": 100, "tpm": 1_000_000}),
        ],
    ),
    (
        "DEEPSEEK_API_KEY",
        "deepseek/",
        [
            ("deepseek-reasoner", "reasoning", {"rpm": 20}),
            ("deepseek-chat", "worker", {"rpm": 60}),
        ],
    ),
    (
        "GROQ_API_KEY",
        "groq/",
        [
            ("llama-3.3-70b-versatile", "worker", {"rpm": 30}),
        ],
    ),
    (
        "DASHSCOPE_API_KEY",
        "dashscope/",
        [
            ("qwen-plus", "worker", {"rpm": 60}),
        ],
    ),
    (
        "MINIMAX_API_KEY",
        "minimax/",
        [
            ("MiniMax-M2.5", "worker", {"rpm": 30}),
        ],
    ),
    (
        "PERPLEXITY_API_KEY",
        "perplexity/",
        [
            ("sonar-pro", "search", {"rpm": 30}),
        ],
    ),
]


def _build_openrouter_config() -> tuple[str, str, list[tuple[str, str, dict[str, Any]]]] | None:
    """Build OpenRouter provider config dynamically from env vars.

    Returns None if OPENROUTER_API_KEY is not set.
    Models are configurable via:
    - RLM_OPENROUTER_REASONING_MODEL (default: google/gemini-2.5-pro-preview)
    - RLM_OPENROUTER_WORKER_MODEL (default: google/gemini-2.5-flash-preview)
    """
    if not os.environ.get("OPENROUTER_API_KEY"):
        return None
    reasoning_model = os.environ.get(
        "RLM_OPENROUTER_REASONING_MODEL", "google/gemini-3.1-pro-preview"
    )
    worker_model = os.environ.get("RLM_OPENROUTER_WORKER_MODEL", "anthropic/claude-sonnet-4.6")
    return (
        "OPENROUTER_API_KEY",
        "openrouter/",
        [
            (reasoning_model, "reasoning", {"rpm": 100, "tpm": 10_000_000}),
            (worker_model, "worker", {"rpm": 200, "tpm": 10_000_000}),
        ],
    )


def build_model_list(
    provider_configs: list[tuple[str, str, list[tuple[str, str, dict[str, Any]]]]] | None = None,
) -> list[dict[str, Any]]:
    """Build a LiteLLM Router model list from environment variables.

    Each provider is included only if its API key env var is set.

    When ``RLM_LITELLM_PROVIDER`` is set (e.g. "openrouter"), only
    deployments whose prefix starts with that provider are included.
    """
    configs: list[tuple[str, str, list[tuple[str, str, dict[str, Any]]]]] = list(
        provider_configs or _PROVIDER_CONFIGS
    )
    # Include dynamically-built OpenRouter config
    or_config = _build_openrouter_config()
    if or_config is not None and provider_configs is None:
        configs.append(or_config)

    provider_filter = os.environ.get("RLM_LITELLM_PROVIDER", "").strip().lower()

    # Parse OpenRouter fallback models
    fallback_raw = os.environ.get("RLM_OPENROUTER_FALLBACK_MODELS", "").strip()
    fallback_models: list[str] = (
        [m.strip() for m in fallback_raw.split(",") if m.strip()] if fallback_raw else []
    )
    if len(fallback_models) > 3:
        logger.warning(
            "OpenRouter limits 'models' array to 3 items; truncating from %d",
            len(fallback_models),
        )
        fallback_models = fallback_models[:3]

    model_list: list[dict[str, Any]] = []
    for env_var, prefix, models in configs:
        api_key = os.environ.get(env_var)
        if not api_key:
            continue
        # Apply provider filter: prefix is e.g. "openrouter/", filter is e.g. "openrouter"
        if provider_filter and not prefix.lower().startswith(provider_filter + "/"):
            continue
        for model_name, tier, limits in models:
            litellm_params: dict[str, Any] = {
                "model": f"{prefix}{model_name}",
                "api_key": api_key,
                **limits,
            }
            # Attach OpenRouter native fallback if configured
            if prefix == "openrouter/" and fallback_models:
                litellm_params["extra_body"] = {"models": fallback_models}
            model_list.append(
                {
                    "model_name": tier,
                    "litellm_params": litellm_params,
                }
            )
    return model_list


# ---------------------------------------------------------------------------
# Singleton client (CRIT-2: thread-safe with double-checked locking)
# ---------------------------------------------------------------------------
_cached_client: RouterLiteLlmClient | None = None
_client_lock = threading.Lock()


def _get_or_create_client(
    model_list: list[dict[str, Any]] | None = None, **kwargs: Any
) -> RouterLiteLlmClient:
    """Return the singleton RouterLiteLlmClient, creating it if necessary.

    Uses double-checked locking (CRIT-2) for thread safety under
    concurrent asyncio.gather / threading scenarios.

    Raises RuntimeError if the resolved model list is empty (CRIT-4).
    """
    global _cached_client
    if _cached_client is not None:
        return _cached_client
    with _client_lock:
        # Double-check inside lock
        if _cached_client is not None:
            return _cached_client
        if model_list is None:
            model_list = build_model_list()
        if not model_list:
            raise RuntimeError(
                "No LiteLLM provider API keys found in environment. "
                "Set at least one of: GEMINI_API_KEY, OPENAI_API_KEY, "
                "DEEPSEEK_API_KEY, GROQ_API_KEY, DASHSCOPE_API_KEY, "
                "MINIMAX_API_KEY, PERPLEXITY_API_KEY, OPENROUTER_API_KEY"
            )
        # Read env var overrides (CRIT-3)
        routing_strategy = os.environ.get("RLM_LITELLM_ROUTING_STRATEGY", "simple-shuffle")
        num_retries = int(os.environ.get("RLM_LITELLM_NUM_RETRIES", "2"))
        cooldown_time = int(os.environ.get("RLM_LITELLM_COOLDOWN_TIME", "60"))
        timeout_str = os.environ.get("RLM_LITELLM_TIMEOUT")
        timeout = int(timeout_str) if timeout_str else None

        _cached_client = RouterLiteLlmClient(
            model_list=model_list,
            routing_strategy=routing_strategy,
            num_retries=num_retries,
            cooldown_time=cooldown_time,
            timeout=timeout,
            **kwargs,
        )
        logger.info(
            "LiteLLM Router created: %d deployments, strategy=%s",
            len(model_list),
            routing_strategy,
        )
        return _cached_client


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_litellm_model(
    logical_name: str = "reasoning",
    model_list: list[dict[str, Any]] | None = None,
    **router_kwargs: Any,
) -> Any:
    """Create an ADK ``LiteLlm`` model backed by the singleton Router.

    Args:
        logical_name: Logical tier name (e.g. "reasoning", "worker").
            Must match a ``model_name`` in the Router's model list.
        model_list: Override model list (mainly for testing).
        **router_kwargs: Extra kwargs forwarded to Router construction.
    """
    from google.adk.models.lite_llm import LiteLlm

    client = _get_or_create_client(model_list=model_list, **router_kwargs)
    return LiteLlm(model=logical_name, llm_client=client)
