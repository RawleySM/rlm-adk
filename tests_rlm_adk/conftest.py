"""Shared fixtures for rlm_adk tests."""

import pytest

from rlm_adk.repl.local_repl import LocalREPL


@pytest.fixture
def repl():
    """Provide a fresh LocalREPL and clean it up after the test."""
    r = LocalREPL()
    yield r
    r.cleanup()
