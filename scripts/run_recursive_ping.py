#!/usr/bin/env python
"""Run the recursive_ping fixture via the programmatic API.

Bypasses the ADK CLI's line-by-line input() limitation so the full prompt
is delivered as one user message, hitting the real LLM.

Usage:
    .venv/bin/python scripts/run_recursive_ping.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Enable logging so we can see dispatch/child activity
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
# Reduce noise from LiteLLM/httpx
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("opentelemetry").setLevel(logging.WARNING)

import os
os.environ["RLM_ADK_LITELLM"] = ""  # bypass LiteLLM — use Gemini directly

from google.genai import types
from rlm_adk.agent import create_rlm_runner

FIXTURE = PROJECT_ROOT / "tests_rlm_adk" / "replay" / "recursive_ping.json"


def _fmt_event(event) -> str:
    """Format any event for debugging — shows tool calls, text, and state."""
    parts = []
    author = event.author or "?"

    if event.content and event.content.parts:
        for p in event.content.parts:
            if p.text:
                parts.append(f"[{author}] TEXT: {p.text[:300]}")
            if p.function_call:
                fc = p.function_call
                args_str = json.dumps(dict(fc.args) if fc.args else {})
                if len(args_str) > 300:
                    args_str = args_str[:300] + "..."
                parts.append(f"[{author}] TOOL_CALL: {fc.name}({args_str})")
            if p.function_response:
                fr = p.function_response
                resp_str = json.dumps(dict(fr.response) if fr.response else {})
                if len(resp_str) > 300:
                    resp_str = resp_str[:300] + "..."
                parts.append(f"[{author}] TOOL_RESP: {fr.name} -> {resp_str}")

    # State deltas
    if event.actions and event.actions.state_delta:
        delta = event.actions.state_delta
        interesting = {k: v for k, v in delta.items()
                      if not k.startswith("obs:") and v is not None}
        if interesting:
            delta_str = json.dumps(interesting, default=str)
            if len(delta_str) > 200:
                delta_str = delta_str[:200] + "..."
            parts.append(f"[{author}] STATE: {delta_str}")

    return "\n".join(parts)


async def main() -> None:
    with open(FIXTURE) as f:
        fixture = json.load(f)

    runner = create_rlm_runner(
        model="gemini-3.1-pro-preview",
        plugins=[],
        sqlite_tracing=False,
    )

    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id="test_user",
        state=fixture["state"],
    )

    for query in fixture["queries"]:
        print(f"\n{'='*60}", flush=True)
        print(f"[user]: {query[:200]}", flush=True)
        print(f"{'='*60}", flush=True)
        content = types.Content(
            role="user",
            parts=[types.Part(text=query)],
        )
        event_count = 0
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=content,
        ):
            event_count += 1
            formatted = _fmt_event(event)
            if formatted:
                print(f"  #{event_count} {formatted}", flush=True)

    await runner.close()
    print("\n--- done ---", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
