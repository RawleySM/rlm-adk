"""Tests for session forking (Rec 8).

TDD: RED phase - defines expected behavior of fork_session.
Uses InMemorySessionService for speed (no SQLite or Postgres needed).
"""

import pytest
from google.adk.events import Event, EventActions
from google.adk.sessions.in_memory_session_service import InMemorySessionService


@pytest.fixture
async def populated_session():
    """Create an InMemorySessionService with a session containing 3 invocations."""
    service = InMemorySessionService()
    session = await service.create_session(
        app_name="test_app",
        user_id="user_1",
    )
    # Add events for 3 invocations
    for inv_idx in range(3):
        inv_id = f"inv_{inv_idx}"
        event = Event(
            invocation_id=inv_id,
            author="orchestrator",
            actions=EventActions(state_delta={"iteration_count": inv_idx}),
        )
        await service.append_event(session=session, event=event)
    return service, session


# --- RED Tests ---


@pytest.mark.asyncio
async def test_fork_session_creates_new_session(populated_session):
    """fork_session creates a new session with a different ID."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    assert new_id != session.id
    new_session = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id=new_id,
    )
    assert new_session is not None


@pytest.mark.asyncio
async def test_fork_session_copies_events_before_fork_point(populated_session):
    """Forked session contains only events before the fork invocation."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    new_session = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id=new_id,
    )
    # Should have events from inv_0 and inv_1 only (2 events)
    assert len(new_session.events) == 2
    inv_ids = {e.invocation_id for e in new_session.events}
    assert "inv_0" in inv_ids
    assert "inv_1" in inv_ids
    assert "inv_2" not in inv_ids


@pytest.mark.asyncio
async def test_fork_session_preserves_event_ordering(populated_session):
    """Events in the forked session are in the same order as the original."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    new_session = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id=new_id,
    )
    inv_ids = [e.invocation_id for e in new_session.events]
    assert inv_ids == ["inv_0", "inv_1"]


@pytest.mark.asyncio
async def test_fork_session_preserves_original(populated_session):
    """Forking does not modify the original session."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    original_event_count = len(session.events)
    await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    # Reload original
    reloaded = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id=session.id,
    )
    assert len(reloaded.events) == original_event_count


@pytest.mark.asyncio
async def test_fork_session_with_state_overrides(populated_session):
    """State overrides are applied to the forked session."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
        state_overrides={"custom_param": "modified"},
    )
    new_session = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id=new_id,
    )
    assert new_session.state.get("custom_param") == "modified"


@pytest.mark.asyncio
async def test_fork_session_at_first_invocation(populated_session):
    """Forking at the first invocation yields an empty session."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_0",
    )
    new_session = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id=new_id,
    )
    assert len(new_session.events) == 0


@pytest.mark.asyncio
async def test_fork_session_raises_on_missing_source():
    """fork_session raises ValueError for a non-existent source session."""
    from rlm_adk.eval.session_fork import fork_session

    service = InMemorySessionService()
    with pytest.raises(ValueError, match="Source session not found"):
        await fork_session(
            service,
            app_name="test_app",
            user_id="user_1",
            source_session_id="nonexistent",
            fork_before_invocation_id="inv_0",
        )


@pytest.mark.asyncio
async def test_fork_session_raises_on_missing_invocation(populated_session):
    """fork_session raises ValueError for a non-existent invocation ID."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    with pytest.raises(ValueError, match="Invocation ID not found"):
        await fork_session(
            service,
            app_name="test_app",
            user_id="user_1",
            source_session_id=session.id,
            fork_before_invocation_id="inv_999",
        )


@pytest.mark.asyncio
async def test_fork_session_with_explicit_session_id(populated_session):
    """fork_session accepts an explicit new_session_id."""
    from rlm_adk.eval.session_fork import fork_session

    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
        new_session_id="my_custom_fork_id",
    )
    assert new_id == "my_custom_fork_id"
    new_session = await service.get_session(
        app_name="test_app",
        user_id="user_1",
        session_id="my_custom_fork_id",
    )
    assert new_session is not None
