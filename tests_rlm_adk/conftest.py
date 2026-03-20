"""Shared fixtures for rlm_adk tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from rlm_adk.repl.local_repl import LocalREPL


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --repl-capture-json CLI option."""
    parser.addoption(
        "--repl-capture-json",
        action="store",
        default=None,
        metavar="PATH",
        help=(
            "Write REPL execution capture to a JSON file. "
            "Captures submitted/expanded code, stdout/stderr, variables, "
            "and lineage metadata for every execute_code invocation across "
            "all depths. When a directory is given, one file per test is written."
        ),
    )


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


@pytest.fixture
def repl_capture(request: pytest.FixtureRequest):
    """Provide a REPLCapturePlugin when --repl-capture-json is set.

    Yields a ``REPLCapturePlugin`` instance (or ``None`` when capture is
    disabled).  Tests should pass the plugin as ``extra_plugins=[plugin]``
    to ``run_fixture_contract_with_plugins``.

    After the test, the fixture writes the captured JSON if a path was given.
    """
    from rlm_adk.plugins.repl_capture_plugin import REPLCapturePlugin

    capture_path = request.config.getoption("--repl-capture-json")
    if capture_path is None:
        yield None
        return

    plugin = REPLCapturePlugin()
    yield plugin

    # Write output after the test completes
    out = Path(capture_path)
    if out.is_dir() or capture_path.endswith("/"):
        out.mkdir(parents=True, exist_ok=True)
        test_name = request.node.name
        out = out / f"repl_capture_{test_name}.json"

    plugin.write_json(
        out,
        test_name=request.node.name,
        fixture_name=plugin.fixture_name,
        final_state=plugin.final_state,
    )
    print(f"\n  [repl-capture] {len(plugin.executions)} REPL executions -> {out}")
