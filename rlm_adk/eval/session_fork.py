"""Session forking for evaluation agents.

Provides fork_session() which creates a new session from an existing one,
copying events up to a specified invocation point. This enables trajectory
exploration without modifying the original session.

Pattern:
1. Identify divergence point (via eval/queries.py)
2. Fork original session at that point
3. Re-execute agent on the forked session with modified parameters
4. Compare original vs forked trajectories
"""

import logging
from typing import Any, Optional

from google.adk.events import Event, EventActions
from google.adk.sessions.base_session_service import BaseSessionService

logger = logging.getLogger(__name__)


async def fork_session(
    session_service: BaseSessionService,
    *,
    app_name: str,
    user_id: str,
    source_session_id: str,
    fork_before_invocation_id: str,
    new_session_id: Optional[str] = None,
    state_overrides: Optional[dict[str, Any]] = None,
) -> str:
    """Fork a session at a specific invocation point.

    Creates a new session with events copied from the source session up to
    (but not including) the specified invocation. The original session is
    unchanged.

    Args:
        session_service: The session service to use for both reading the
            source and creating the fork.
        app_name: Application name.
        user_id: User ID.
        source_session_id: ID of the session to fork from.
        fork_before_invocation_id: Fork point. Events with this invocation_id
            and later are NOT copied. Events before this point ARE copied.
        new_session_id: Optional explicit ID for the new session. If None,
            the session service generates a UUID.
        state_overrides: Optional dict of state keys to override in the
            forked session's initial state. Applied after copying events.

    Returns:
        The new (forked) session's ID.

    Raises:
        ValueError: If source session not found or invocation_id not found.
    """
    # 1. Load the source session with all events
    source = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=source_session_id,
    )
    if source is None:
        raise ValueError(f"Source session not found: {source_session_id}")

    # 2. Find the fork point
    fork_index = None
    for i, event in enumerate(source.events):
        if event.invocation_id == fork_before_invocation_id:
            fork_index = i
            break

    if fork_index is None:
        raise ValueError(
            f"Invocation ID not found in source session: {fork_before_invocation_id}"
        )

    events_to_copy = source.events[:fork_index]

    # 3. Create new session
    new_session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=new_session_id,
    )

    # 4. Replay events into the new session
    for event in events_to_copy:
        await session_service.append_event(session=new_session, event=event)

    # 5. Apply state overrides if provided
    if state_overrides:
        last_inv_id = (
            new_session.events[-1].invocation_id if new_session.events else "fork_init"
        )
        override_event = Event(
            invocation_id=last_inv_id,
            author="eval_fork",
            actions=EventActions(state_delta=state_overrides),
        )
        await session_service.append_event(session=new_session, event=override_event)

    logger.info(
        "Forked session %s -> %s at invocation %s (%d events copied)",
        source_session_id,
        new_session.id,
        fork_before_invocation_id,
        len(events_to_copy),
    )

    return new_session.id
