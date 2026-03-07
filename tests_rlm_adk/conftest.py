"""Shared fixtures for rlm_adk tests."""

import pytest

from rlm_adk.repl.local_repl import LocalREPL


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag tests into default, extended provider-fake, and non-default suites."""
    unit_nondefault = pytest.mark.unit_nondefault
    provider_fake_extended = pytest.mark.provider_fake_extended
    for item in items:
        if "provider_fake" not in item.keywords:
            item.add_marker(unit_nondefault)
            continue
        if "provider_fake_contract" not in item.keywords:
            item.add_marker(provider_fake_extended)


@pytest.fixture
def repl():
    """Provide a fresh LocalREPL and clean it up after the test."""
    r = LocalREPL()
    yield r
    r.cleanup()
