#!/usr/bin/env python3
"""Pre-flight API key validation for LiteLLM providers.

Reads .env from the project root (via python-dotenv), then tests each provider
key by making a minimal ``litellm.acompletion(max_tokens=5)`` call.

Exit code 0 if at least one provider works, 1 if none work.
"""

import asyncio
import os
import sys
from pathlib import Path

# Load .env from project root (two levels up from scripts/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / "rlm_adk" / ".env"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ENV_FILE, override=False)

import litellm  # noqa: E402

# Suppress litellm's verbose logging during validation
litellm.suppress_debug_info = True

PROVIDERS = [
    {
        "name": "Gemini",
        "env_var": "GEMINI_API_KEY",
        "model": "gemini/gemini-2.5-flash",
    },
    {
        "name": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "model": "openai/gpt-4o-mini",
    },
    {
        "name": "DeepSeek",
        "env_var": "DEEPSEEK_API_KEY",
        "model": "deepseek/deepseek-chat",
    },
    {
        "name": "Groq",
        "env_var": "GROQ_API_KEY",
        "model": "groq/llama-3.3-70b-versatile",
    },
]


async def _check_provider(provider: dict) -> tuple[str, str, str]:
    """Test a single provider. Returns (name, status, detail)."""
    api_key = os.environ.get(provider["env_var"])
    if not api_key:
        return (provider["name"], "SKIP", f"{provider['env_var']} not set")
    try:
        resp = await litellm.acompletion(
            model=provider["model"],
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5,
            api_key=api_key,
        )
        text = resp.choices[0].message.content or ""
        return (provider["name"], "OK", text.strip()[:40])
    except Exception as exc:
        return (provider["name"], "FAIL", str(exc)[:80])


async def main() -> int:
    print(f"Validating LiteLLM provider keys from {_ENV_FILE}\n")
    results = await asyncio.gather(*[_check_provider(p) for p in PROVIDERS])

    ok_count = 0
    for name, status, detail in results:
        icon = {"OK": "+", "FAIL": "X", "SKIP": "-"}[status]
        print(f"  [{icon}] {name:10s} {status:5s}  {detail}")
        if status == "OK":
            ok_count += 1

    print(f"\n{ok_count}/{len(PROVIDERS)} providers available.")
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
