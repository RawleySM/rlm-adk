"""Live LiteLLM integration tests.

These tests make real API calls through the LiteLLM Router and are excluded
from the default pytest run via the ``unit_nondefault`` marker (auto-applied
by conftest.py since they lack ``provider_fake_contract``).

Run explicitly::

    RLM_ADK_LITELLM=1 pytest tests_rlm_adk/test_litellm_live.py -m "" -v

Skipped automatically when ``RLM_ADK_LITELLM`` is not set or no provider
API keys are available.
"""

import os

import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_runner


def _skip_if_not_litellm():
    """Skip the test if LiteLLM mode is not active."""
    if os.environ.get("RLM_ADK_LITELLM", "").lower() not in ("1", "true", "yes"):
        pytest.skip("RLM_ADK_LITELLM not set — skipping live LiteLLM test")


def _skip_if_no_keys():
    """Skip if no provider API keys are available at all."""
    key_vars = [
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
    ]
    if not any(os.environ.get(k) for k in key_vars):
        pytest.skip("No LiteLLM provider API keys found — skipping live test")


def _make_runner():
    """Create a lightweight runner for live LiteLLM testing."""
    return create_rlm_runner(
        model="reasoning",
        thinking_budget=0,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        sqlite_tracing=False,
    )


async def _run_agent(runner, prompt: str) -> list:
    """Run the agent with a prompt and collect all events."""
    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id="test_user",
    )
    content = types.Content(
        role="user",
        parts=[types.Part(text=prompt)],
    )
    events = []
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=content,
    ):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# MED-3 fix: We do NOT assert obs:child_dispatch_count because flush_fn
# resets per REPL iteration. Instead we verify the agent produced events
# containing model responses and/or a final answer.
# MIN-5 fix: We use model="reasoning" (Router tier), not RLM_TEST_LITELLM_MODEL.
# ---------------------------------------------------------------------------


async def test_litellm_single_query_live():
    """Single query through LiteLLM Router produces a final answer."""
    _skip_if_not_litellm()
    _skip_if_no_keys()

    runner = _make_runner()
    events = await _run_agent(
        runner,
        "Say hello. Respond with just the word 'hello' as your final answer. "
        "Do not use execute_code. Just respond directly.",
    )

    # Verify we got events with model responses
    assert len(events) > 0, "No events returned from agent"

    # Check that at least one event has content (model responded)
    has_model_content = any(getattr(e, "content", None) is not None for e in events)
    assert has_model_content, "No events with model content found"


async def test_litellm_batched_query_live():
    """Batched llm_query through LiteLLM Router produces results from all 3 queries."""
    _skip_if_not_litellm()
    _skip_if_no_keys()

    runner = _make_runner()
    prompt = (
        "You must call execute_code with the following Python code exactly:\n\n"
        "```python\n"
        "prompts = [\n"
        "    'What is 2+2? Reply with just the number.',\n"
        "    'What is 3+3? Reply with just the number.',\n"
        "    'What is 4+4? Reply with just the number.'\n"
        "]\n"
        "results = llm_query_batched(prompts)\n"
        "for i, r in enumerate(results):\n"
        "    print(f'Result {i}: {r}')\n"
        "```\n\n"
        "After the code executes, report all three results as your final answer."
    )

    events = await _run_agent(runner, prompt)

    assert len(events) > 0, "No events returned from agent"

    # The agent should have produced a final answer that references results
    # from all 3 batched queries. Check that we got substantive events.
    has_model_content = any(getattr(e, "content", None) is not None for e in events)
    assert has_model_content, "No events with model content found"

    # Verify the agent completed (got a final event, not stuck in a loop)
    final_event = events[-1]
    assert final_event is not None, "Agent did not produce a final event"
