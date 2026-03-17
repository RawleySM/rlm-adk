#!/usr/bin/env python
"""Test the child orchestrator in isolation to debug structured output convergence.

Creates a child_orchestrator_d1 directly and sends a simple prompt to it.
This bypasses the parent entirely to isolate child completion behavior.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("opentelemetry").setLevel(logging.WARNING)

from google.adk.apps.app import App
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types

from rlm_adk.agent import create_child_orchestrator


async def main() -> None:
    prompt = 'You are a test oracle. Return exactly: {"secret": 42}'

    # Use the worker model (same as dispatch.py uses for children)
    from rlm_adk.dispatch import WorkerPool
    wp = WorkerPool(default_model="gemini-3.1-pro-preview")
    wp.ensure_initialized()
    worker_model = wp.other_model  # LiteLLM worker tier (Claude Sonnet)
    print(f"[debug] worker model: {worker_model}", flush=True)

    child = create_child_orchestrator(
        model=worker_model,
        depth=1,
        prompt=prompt,
        worker_pool=wp,
        max_iterations=5,  # keep it short
    )

    app = App(name="child_test", root_agent=child, plugins=[])
    runner = Runner(
        app=app,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
    )

    session = await runner.session_service.create_session(
        app_name="child_test",
        user_id="test",
        state={"app:max_iterations": 5, "app:max_depth": 3},
    )

    content = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )

    event_count = 0
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=content,
    ):
        event_count += 1
        author = event.author or "?"

        if event.content and event.content.parts:
            for p in event.content.parts:
                if p.text:
                    print(f"  #{event_count} [{author}] TEXT: {p.text[:300]}", flush=True)
                if p.function_call:
                    fc = p.function_call
                    args_str = json.dumps(dict(fc.args) if fc.args else {})[:300]
                    print(f"  #{event_count} [{author}] CALL: {fc.name}({args_str})", flush=True)
                if p.function_response:
                    fr = p.function_response
                    resp_str = json.dumps(dict(fr.response) if fr.response else {})[:300]
                    print(f"  #{event_count} [{author}] RESP: {fr.name} -> {resp_str}", flush=True)

        if event.actions and event.actions.state_delta:
            delta = event.actions.state_delta
            interesting = {k: v for k, v in delta.items()
                          if "final_answer" in k or "reasoning_output" in k}
            if interesting:
                print(f"  #{event_count} [{author}] STATE: {json.dumps(interesting, default=str)[:300]}", flush=True)

    print(f"\n--- done ({event_count} events) ---", flush=True)
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
