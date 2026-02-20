"""BUG-004: REQUEST_ID must be initialized in orchestrator initial state.

Tests that the orchestrator's initial state delta includes a REQUEST_ID
that is a valid non-empty UUID string.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rlm_adk.state import REQUEST_ID


# UUID v4 pattern: 8-4-4-4-12 hex digits
UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _build_orchestrator_and_ctx():
    """Build a minimal RLMOrchestratorAgent + mock ctx for testing."""
    from google.adk.agents import LlmAgent

    from rlm_adk.orchestrator import RLMOrchestratorAgent

    reasoning_agent = LlmAgent(
        name="reasoning",
        model="gemini-2.0-flash",
    )

    orchestrator = RLMOrchestratorAgent(
        name="rlm_orchestrator",
        reasoning_agent=reasoning_agent,
        root_prompt="test prompt",
    )

    ctx = MagicMock()
    ctx.invocation_id = "test-invocation-id"
    ctx.session.state = {}

    return orchestrator, ctx


async def _get_first_event(orchestrator, ctx):
    """Run the orchestrator and collect only the first yielded event.

    Patches LlmAgent.run_async at the class level so Pydantic does not
    interfere with attribute assignment.
    """
    from google.adk.agents import LlmAgent

    async def empty_gen(*args, **kwargs):
        return
        yield  # noqa: makes this an async generator

    with patch.object(LlmAgent, "run_async", side_effect=empty_gen):
        first_event = None
        async for event in orchestrator._run_async_impl(ctx):
            first_event = event
            break
    return first_event


@pytest.mark.asyncio
async def test_initial_state_contains_request_id():
    """The first event yielded by _run_async_impl must include REQUEST_ID in state_delta."""
    orchestrator, ctx = _build_orchestrator_and_ctx()
    first_event = await _get_first_event(orchestrator, ctx)

    assert first_event is not None, "Orchestrator must yield at least one event"
    assert first_event.actions is not None, "First event must have actions"
    assert first_event.actions.state_delta is not None, "First event must have state_delta"

    state_delta = first_event.actions.state_delta
    assert REQUEST_ID in state_delta, (
        f"REQUEST_ID ('{REQUEST_ID}') must be present in initial state_delta. "
        f"Keys found: {list(state_delta.keys())}"
    )


@pytest.mark.asyncio
async def test_request_id_is_valid_uuid():
    """REQUEST_ID in the initial state delta must be a non-empty UUID v4 string."""
    orchestrator, ctx = _build_orchestrator_and_ctx()
    first_event = await _get_first_event(orchestrator, ctx)

    state_delta = first_event.actions.state_delta
    request_id = state_delta[REQUEST_ID]

    assert isinstance(request_id, str), f"REQUEST_ID must be a string, got {type(request_id)}"
    assert len(request_id) > 0, "REQUEST_ID must not be empty"
    assert UUID_V4_RE.match(request_id), (
        f"REQUEST_ID must be a valid UUID v4, got: '{request_id}'"
    )
