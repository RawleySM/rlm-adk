"""Shared in-process async gate primitive for step-mode execution."""

from __future__ import annotations

import asyncio


class StepGate:
    """Async gate that blocks agent execution until the user advances."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._step_mode = False
        self._waiting = False
        self._paused_agent_name: str | None = None
        self._paused_depth: int | None = None

    async def wait_for_advance(self, *, agent_name: str = "", depth: int = 0) -> None:
        """Block until the user advances. No-op if step mode is off."""
        if not self._step_mode:
            return
        self._event.clear()
        self._waiting = True
        self._paused_agent_name = agent_name
        self._paused_depth = depth
        await self._event.wait()
        self._waiting = False
        self._paused_agent_name = None
        self._paused_depth = None

    def set_step_mode(self, enabled: bool) -> None:
        """Toggle step mode on/off. If disabling while a waiter is blocked, release it."""
        self._step_mode = enabled
        if not enabled:
            self._event.set()

    def advance(self) -> None:
        """Signal the gate to release one blocked waiter."""
        self._event.set()

    @property
    def step_mode_enabled(self) -> bool:
        return self._step_mode

    @property
    def waiting(self) -> bool:
        """True if the gate is currently blocked (plugin is paused)."""
        return self._waiting

    @property
    def paused_agent_name(self) -> str | None:
        """Name of the agent currently blocked at the gate."""
        return self._paused_agent_name

    @property
    def paused_depth(self) -> int | None:
        """Depth of the agent currently blocked at the gate."""
        return self._paused_depth


step_gate = StepGate()
