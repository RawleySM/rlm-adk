"""Shared fixtures for rlm_adk tests."""

import pytest

from rlm_adk.repl.local_repl import LocalREPL


@pytest.fixture
def repl():
    """Provide a fresh LocalREPL and clean it up after the test."""
    r = LocalREPL()
    yield r
    r.cleanup()


@pytest.fixture
def repl_with_context():
    """Provide a LocalREPL pre-loaded with a string context."""
    r = LocalREPL(context_payload="hello world")
    yield r
    r.cleanup()


@pytest.fixture
def repl_with_dict_context():
    """Provide a LocalREPL pre-loaded with a dict context."""
    r = LocalREPL(context_payload={"key": "value", "number": 42})
    yield r
    r.cleanup()


@pytest.fixture
def repl_with_list_context():
    """Provide a LocalREPL pre-loaded with a list context."""
    r = LocalREPL(context_payload=["item1", "item2", "item3"])
    yield r
    r.cleanup()
