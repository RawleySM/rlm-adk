"""Tests for StepGate — shared in-process async gate primitive."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def gate():
    from rlm_adk.step_gate import StepGate

    return StepGate()


async def test_advance_releases_blocked_waiter(gate):
    """Toggle on, wait_for_advance blocks, advance() releases it."""
    gate.set_step_mode(True)

    task = asyncio.create_task(gate.wait_for_advance(agent_name="reasoning", depth=0))
    await asyncio.sleep(0.05)
    assert not task.done(), "waiter should be blocked"
    assert gate.waiting is True

    gate.advance()
    await asyncio.sleep(0.05)
    assert task.done(), "waiter should be released after advance()"


async def test_disable_releases_blocked_waiter(gate):
    """Toggle on, block a waiter, toggle off — waiter released immediately."""
    gate.set_step_mode(True)

    task = asyncio.create_task(gate.wait_for_advance(agent_name="reasoning", depth=1))
    await asyncio.sleep(0.05)
    assert not task.done(), "waiter should be blocked"

    gate.set_step_mode(False)
    await asyncio.sleep(0.05)
    assert task.done(), "waiter should be released when step mode disabled"
    assert gate.waiting is False


async def test_step_mode_off_returns_immediately(gate):
    """With step mode off, wait_for_advance() is a no-op."""
    assert gate.step_mode_enabled is False

    # Should return immediately — no blocking
    task = asyncio.create_task(gate.wait_for_advance(agent_name="reasoning", depth=0))
    await asyncio.sleep(0.05)
    assert task.done(), "wait_for_advance should return immediately when step mode is off"
    assert gate.waiting is False


async def test_metadata_set_while_waiting(gate):
    """paused_agent_name and paused_depth reflect the blocked waiter."""
    gate.set_step_mode(True)

    assert gate.paused_agent_name is None
    assert gate.paused_depth is None

    task = asyncio.create_task(gate.wait_for_advance(agent_name="child_worker", depth=2))
    await asyncio.sleep(0.05)

    assert gate.waiting is True
    assert gate.paused_agent_name == "child_worker"
    assert gate.paused_depth == 2

    gate.advance()
    await asyncio.sleep(0.05)
    assert task.done()

    # Metadata cleared after release
    assert gate.waiting is False
    assert gate.paused_agent_name is None
    assert gate.paused_depth is None


async def test_module_singleton_exists():
    """Module-level step_gate singleton is importable."""
    from rlm_adk.step_gate import StepGate, step_gate

    assert isinstance(step_gate, StepGate)


async def test_step_mode_enabled_property(gate):
    """step_mode_enabled reflects current toggle state."""
    assert gate.step_mode_enabled is False
    gate.set_step_mode(True)
    assert gate.step_mode_enabled is True
    gate.set_step_mode(False)
    assert gate.step_mode_enabled is False
