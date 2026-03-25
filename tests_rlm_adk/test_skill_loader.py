"""Tests for rlm_adk.skills.loader — skill discovery and REPL-globals collection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Cycle 10 — discover_skill_dirs
# ---------------------------------------------------------------------------

class TestDiscoverSkillDirs:
    """discover_skill_dirs scans the skills directory for valid skill packages."""

    def test_returns_empty_when_no_skill_dirs(self, tmp_path, monkeypatch):
        """An empty skills root yields an empty list."""
        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)
        assert loader.discover_skill_dirs() == []

    def test_skips_obsolete_and_pycache(self, tmp_path, monkeypatch):
        """Directories named obsolete, __pycache__, or starting with '.' are skipped."""
        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        for name in ("obsolete", "__pycache__", ".hidden"):
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text("---\nname: x\n---\n")

        assert loader.discover_skill_dirs() == []

    def test_requires_skill_md(self, tmp_path, monkeypatch):
        """Only directories containing SKILL.md are returned."""
        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        # Has SKILL.md → included
        valid = tmp_path / "good_skill"
        valid.mkdir()
        (valid / "SKILL.md").write_text("---\nname: good-skill\n---\n")

        # Missing SKILL.md → excluded
        invalid = tmp_path / "bad_skill"
        invalid.mkdir()

        result = loader.discover_skill_dirs()
        assert result == [valid]

    def test_filters_by_enabled_skills(self, tmp_path, monkeypatch):
        """When enabled_skills is provided, only matching dir names are returned."""
        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        for name in ("alpha", "beta", "gamma"):
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n")

        result = loader.discover_skill_dirs(enabled_skills={"alpha", "gamma"})
        names = sorted(p.name for p in result)
        assert names == ["alpha", "gamma"]


# ---------------------------------------------------------------------------
# Cycle 11 — _has_llm_query_fn_param / _wrap_with_llm_query_injection
# ---------------------------------------------------------------------------


class TestLlmQueryFnInjection:
    """Injection wrappers detect and inject llm_query_fn into skill functions."""

    def test_has_llm_query_fn_param_detects_param(self):
        """Returns True for functions with llm_query_fn parameter."""
        from rlm_adk.skills.loader import _has_llm_query_fn_param

        def foo(x, *, llm_query_fn=None):
            pass

        assert _has_llm_query_fn_param(foo) is True

    def test_has_llm_query_fn_param_returns_false_without(self):
        """Returns False for functions without llm_query_fn parameter."""
        from rlm_adk.skills.loader import _has_llm_query_fn_param

        def foo(x):
            pass

        assert _has_llm_query_fn_param(foo) is False

    def test_wrapper_injects_from_globals(self):
        """Wrapper reads llm_query from repl_globals and injects as llm_query_fn."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_fn=None):
            captured["fn"] = llm_query_fn
            return llm_query_fn(prompt)

        mock_llm = lambda p: f"echo:{p}"  # noqa: E731
        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        # Populate repl_globals AFTER wrapping (lazy binding)
        repl_globals["llm_query"] = mock_llm

        result = wrapped("hello")
        assert result == "echo:hello"
        assert captured["fn"] is mock_llm

    def test_wrapper_respects_explicit_llm_query_fn(self):
        """If caller passes llm_query_fn explicitly, wrapper does NOT override."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_fn=None):
            captured["fn"] = llm_query_fn

        explicit_fn = lambda p: "explicit"  # noqa: E731
        repl_globals: dict = {"llm_query": lambda p: "from_globals"}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        wrapped("test", llm_query_fn=explicit_fn)
        assert captured["fn"] is explicit_fn

    def test_wrapper_skips_optional_query_when_missing(self):
        """If llm_query not in repl_globals but param is optional, no error."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_fn=None):
            captured["fn"] = llm_query_fn

        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        # Should NOT raise — param is optional, so default None stands
        wrapped("test")
        assert captured["fn"] is None

    def test_wrapper_raises_when_required_query_missing(self):
        """If llm_query not in repl_globals and param is required, raises RuntimeError."""
        import pytest

        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        def skill_fn(prompt, *, llm_query_fn):
            pass

        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        with pytest.raises(RuntimeError, match="llm_query not available"):
            wrapped("test")

    def test_wrapper_preserves_functools_wraps(self):
        """__name__ and __doc__ are preserved on the wrapper."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        def my_skill(prompt, *, llm_query_fn=None):
            """Docstring for my_skill."""

        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(my_skill, repl_globals)

        assert wrapped.__name__ == "my_skill"
        assert wrapped.__doc__ == "Docstring for my_skill."


# ---------------------------------------------------------------------------
# Cycle 12 — collect_skill_repl_globals
# ---------------------------------------------------------------------------


def _make_skill_dir(tmp_path, name, init_src, module_src, skill_md="---\nname: test\n---\n"):
    """Helper: create a skill directory with __init__.py, module, and SKILL.md."""
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(skill_md)
    (d / "__init__.py").write_text(init_src)
    (d / "impl.py").write_text(module_src)
    return d


class TestCollectSkillReplGlobals:
    """collect_skill_repl_globals imports skill modules and collects exports."""

    def test_returns_empty_dict_when_no_skills(self, tmp_path, monkeypatch):
        """Returns {} when no skill dirs exist."""
        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)
        result = loader.collect_skill_repl_globals()
        assert result == {}

    def test_imports_module_and_reads_exports(self, tmp_path, monkeypatch):
        """For a skill dir with valid module and SKILL_EXPORTS, returns exported names."""
        import sys

        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        init_src = (
            'from test_skill_pkg.impl import greet\n'
            'SKILL_EXPORTS = ["greet"]\n'
        )
        module_src = 'def greet(name): return f"hello {name}"\n'
        _make_skill_dir(tmp_path, "test_skill_pkg", init_src, module_src)

        # Add tmp_path parent to sys.path so importlib can find the package
        sys.path.insert(0, str(tmp_path))
        try:
            result = loader.collect_skill_repl_globals()
        finally:
            sys.path.remove(str(tmp_path))
            # Clean up the module from sys.modules
            for key in list(sys.modules):
                if key.startswith("test_skill_pkg"):
                    del sys.modules[key]

        assert "greet" in result
        assert result["greet"]("world") == "hello world"

    def test_wraps_functions_with_llm_query_fn(self, tmp_path, monkeypatch):
        """Functions with llm_query_fn param are wrapped with injection."""
        import sys

        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        init_src = (
            'from test_wrap_pkg.impl import query_skill\n'
            'SKILL_EXPORTS = ["query_skill"]\n'
        )
        module_src = (
            'def query_skill(prompt, *, llm_query_fn=None):\n'
            '    return llm_query_fn(prompt)\n'
        )
        _make_skill_dir(tmp_path, "test_wrap_pkg", init_src, module_src)

        repl_globals: dict = {}
        sys.path.insert(0, str(tmp_path))
        try:
            result = loader.collect_skill_repl_globals(repl_globals=repl_globals)
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules):
                if key.startswith("test_wrap_pkg"):
                    del sys.modules[key]

        # The exported function should be wrapped
        assert "query_skill" in result
        # Lazy binding: inject llm_query after collection
        repl_globals["llm_query"] = lambda p: f"mock:{p}"
        assert result["query_skill"]("test") == "mock:test"

    def test_skips_module_without_skill_exports(self, tmp_path, monkeypatch):
        """Modules without SKILL_EXPORTS attribute are skipped."""
        import sys

        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        # No SKILL_EXPORTS in __init__.py
        init_src = 'def helper(): pass\n'
        module_src = 'x = 1\n'
        _make_skill_dir(tmp_path, "no_exports_pkg", init_src, module_src)

        sys.path.insert(0, str(tmp_path))
        try:
            result = loader.collect_skill_repl_globals()
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules):
                if key.startswith("no_exports_pkg"):
                    del sys.modules[key]

        assert result == {}

    def test_passes_types_unwrapped(self, tmp_path, monkeypatch):
        """Classes/dataclasses pass through without wrapping."""
        import sys

        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        init_src = (
            'from test_type_pkg.impl import MyResult\n'
            'SKILL_EXPORTS = ["MyResult"]\n'
        )
        module_src = (
            'from dataclasses import dataclass\n'
            '@dataclass\n'
            'class MyResult:\n'
            '    value: str\n'
        )
        _make_skill_dir(tmp_path, "test_type_pkg", init_src, module_src)

        sys.path.insert(0, str(tmp_path))
        try:
            result = loader.collect_skill_repl_globals()
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules):
                if key.startswith("test_type_pkg"):
                    del sys.modules[key]

        assert "MyResult" in result
        # Should be the class itself, not wrapped
        obj = result["MyResult"](value="test")
        assert obj.value == "test"


# ---------------------------------------------------------------------------
# GAP-C — llm_query_batched_fn injection
# ---------------------------------------------------------------------------


class TestLlmQueryBatchedFnInjection:
    """Injection wrappers detect and inject llm_query_batched_fn into skill functions."""

    # -- Cycle 1: _has_llm_query_batched_fn_param detection -----------------

    def test_has_llm_query_batched_fn_param_detects_param(self):
        """Returns True for functions with llm_query_batched_fn parameter."""
        from rlm_adk.skills.loader import _has_llm_query_batched_fn_param

        def foo(x, *, llm_query_batched_fn=None):
            pass

        assert _has_llm_query_batched_fn_param(foo) is True

    def test_has_llm_query_batched_fn_param_returns_false_without(self):
        """Returns False for functions without llm_query_batched_fn parameter."""
        from rlm_adk.skills.loader import _has_llm_query_batched_fn_param

        def foo(x, *, llm_query_fn=None):
            pass

        assert _has_llm_query_batched_fn_param(foo) is False

    # -- Cycle 2: wrapper injection -----------------------------------------

    def test_wrapper_injects_batched_from_globals(self):
        """Wrapper reads llm_query_batched from repl_globals and injects both fns."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_fn=None, llm_query_batched_fn=None):
            captured["fn"] = llm_query_fn
            captured["batched_fn"] = llm_query_batched_fn
            return llm_query_batched_fn([prompt])

        mock_llm = lambda p: f"echo:{p}"  # noqa: E731
        mock_batched = lambda prompts: [f"batch:{p}" for p in prompts]  # noqa: E731
        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        # Populate repl_globals AFTER wrapping (lazy binding)
        repl_globals["llm_query"] = mock_llm
        repl_globals["llm_query_batched"] = mock_batched

        result = wrapped("hello")
        assert result == ["batch:hello"]
        assert captured["fn"] is mock_llm
        assert captured["batched_fn"] is mock_batched

    def test_wrapper_injects_only_batched_when_only_batched_declared(self):
        """Function with ONLY llm_query_batched_fn gets it injected."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_batched_fn=None):
            captured["batched_fn"] = llm_query_batched_fn
            return llm_query_batched_fn([prompt])

        mock_batched = lambda prompts: [f"batch:{p}" for p in prompts]  # noqa: E731
        repl_globals: dict = {"llm_query_batched": mock_batched}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        result = wrapped("hello")
        assert result == ["batch:hello"]
        assert captured["batched_fn"] is mock_batched

    def test_wrapper_skips_optional_batched_when_missing(self):
        """If llm_query_batched not in repl_globals but param is optional, no error."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_batched_fn=None):
            captured["batched_fn"] = llm_query_batched_fn

        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        # Should NOT raise — param is optional, so default None stands
        wrapped("test")
        assert captured["batched_fn"] is None

    def test_wrapper_raises_when_required_batched_missing(self):
        """If llm_query_batched not in repl_globals and param is required, raises."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        def skill_fn(prompt, *, llm_query_batched_fn):
            pass

        repl_globals: dict = {}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        with pytest.raises(RuntimeError, match="llm_query_batched not available"):
            wrapped("test")

    def test_wrapper_respects_explicit_batched_fn(self):
        """If caller passes llm_query_batched_fn explicitly, wrapper does NOT override."""
        from rlm_adk.skills.loader import _wrap_with_llm_query_injection

        captured = {}

        def skill_fn(prompt, *, llm_query_batched_fn=None):
            captured["batched_fn"] = llm_query_batched_fn

        explicit_fn = lambda ps: "explicit"  # noqa: E731
        repl_globals: dict = {"llm_query_batched": lambda ps: "from_globals"}
        wrapped = _wrap_with_llm_query_injection(skill_fn, repl_globals)

        wrapped("test", llm_query_batched_fn=explicit_fn)
        assert captured["batched_fn"] is explicit_fn

    # -- Cycle 3: collect_skill_repl_globals wraps batched-only fns ---------

    def test_collect_wraps_fn_with_only_batched_param(self, tmp_path, monkeypatch):
        """collect_skill_repl_globals wraps functions that only have llm_query_batched_fn."""
        import sys

        from rlm_adk.skills import loader

        monkeypatch.setattr(loader, "_SKILLS_DIR", tmp_path)

        init_src = (
            'from test_batched_pkg.impl import batched_skill\n'
            'SKILL_EXPORTS = ["batched_skill"]\n'
        )
        module_src = (
            'def batched_skill(prompts, *, llm_query_batched_fn=None):\n'
            '    return llm_query_batched_fn(prompts)\n'
        )
        _make_skill_dir(tmp_path, "test_batched_pkg", init_src, module_src)

        repl_globals: dict = {}
        sys.path.insert(0, str(tmp_path))
        try:
            result = loader.collect_skill_repl_globals(repl_globals=repl_globals)
        finally:
            sys.path.remove(str(tmp_path))
            for key in list(sys.modules):
                if key.startswith("test_batched_pkg"):
                    del sys.modules[key]

        assert "batched_skill" in result
        # Lazy binding: inject llm_query_batched after collection
        repl_globals["llm_query_batched"] = lambda ps: [f"mock:{p}" for p in ps]
        assert result["batched_skill"](["test"]) == ["mock:test"]

    # -- Cycle 4: test_skill exercises llm_query_batched_fn ------------------

    def test_run_test_skill_invokes_batched_fn(self):
        """run_test_skill calls llm_query_batched_fn when provided and records results."""
        from rlm_adk.skills.test_skill.skill import run_test_skill

        mock_query = lambda p: "child_ok"  # noqa: E731
        batched_calls: list = []

        def mock_batched(prompts):
            batched_calls.append(prompts)
            return [f"batched:{p}" for p in prompts]

        result = run_test_skill(
            emit_debug=False,
            llm_query_fn=mock_query,
            llm_query_batched_fn=mock_batched,
        )

        # llm_query_batched_fn was actually invoked
        assert len(batched_calls) == 1
        assert batched_calls[0] == ["batch_probe_1", "batch_probe_2"]

        # Results recorded in the dataclass
        assert result.batched_probe_results == [
            "batched:batch_probe_1",
            "batched:batch_probe_2",
        ]

    def test_run_test_skill_skips_batched_when_none(self):
        """run_test_skill leaves batched_probe_results as None when batched fn not provided."""
        from rlm_adk.skills.test_skill.skill import run_test_skill

        mock_query = lambda p: "child_ok"  # noqa: E731

        result = run_test_skill(
            emit_debug=False,
            llm_query_fn=mock_query,
            # llm_query_batched_fn intentionally omitted (defaults to None)
        )

        assert result.batched_probe_results is None


# ---------------------------------------------------------------------------
# Cycle 13 — recursive_ping skill
# ---------------------------------------------------------------------------


class TestRecursivePingSkill:
    """The recursive_ping skill directory is discoverable and functional."""

    def test_discover_finds_recursive_ping(self):
        """discover_skill_dirs() finds the recursive_ping directory."""
        from rlm_adk.skills.loader import discover_skill_dirs

        dirs = discover_skill_dirs()
        names = [d.name for d in dirs]
        assert "recursive_ping" in names

    def test_collect_exports_run_recursive_ping(self):
        """collect_skill_repl_globals() returns run_recursive_ping and RecursivePingResult."""
        from rlm_adk.skills.loader import collect_skill_repl_globals

        result = collect_skill_repl_globals()
        assert "run_recursive_ping" in result
        assert "RecursivePingResult" in result

    def test_run_recursive_ping_terminal_layer(self):
        """At terminal layer (starting_layer >= max_layer), returns without calling llm_query_fn."""
        from rlm_adk.skills.recursive_ping.ping import run_recursive_ping

        result = run_recursive_ping("hello", starting_layer=2, max_layer=2)
        assert result.layer == 2
        assert result.prompt == "hello"
        assert "terminal@layer2" in result.response

    def test_run_recursive_ping_raises_without_llm_query_fn(self):
        """Without llm_query_fn, raises RuntimeError at non-terminal layer."""
        import pytest

        from rlm_adk.skills.recursive_ping.ping import run_recursive_ping

        with pytest.raises(RuntimeError, match="llm_query_fn not available"):
            run_recursive_ping("hello", starting_layer=0, max_layer=2)

    def test_run_recursive_ping_with_mock_llm_query(self):
        """With mock llm_query_fn, dispatches and returns RecursivePingResult."""
        from rlm_adk.skills.recursive_ping.ping import run_recursive_ping

        result = run_recursive_ping(
            "ping",
            starting_layer=0,
            max_layer=2,
            llm_query_fn=lambda p: f"pong:{p}",
        )
        assert result.layer == 0
        assert result.prompt == "ping"
        assert result.response == "pong:[layer0] ping"


# ---------------------------------------------------------------------------
# Cycle 14 — Wire skill globals in orchestrator
# ---------------------------------------------------------------------------

async def _collect_orch_events(orch, mock_ctx, max_events=3):
    """Run orchestrator and collect events until max_events or error."""
    events = []
    try:
        async for event in orch._run_async_impl(mock_ctx):
            events.append(event)
            if len(events) >= max_events:
                break
    except Exception:
        pass  # Expected — mock ctx is incomplete for full run
    assert len(events) >= 1, "Orchestrator should emit at least one event during setup"
    return events


def _make_orch(repl, *, enabled_skills=()):
    """Create an RLMOrchestratorAgent with a real reasoning agent."""
    from google.adk.agents import LlmAgent

    from rlm_adk.orchestrator import RLMOrchestratorAgent

    reasoning_agent = LlmAgent(
        name="test_reasoning",
        model="gemini-2.0-flash",
    )
    return RLMOrchestratorAgent(
        name="test_orch",
        reasoning_agent=reasoning_agent,
        sub_agents=[reasoning_agent],
        enabled_skills=enabled_skills,
        repl=repl,
    )


class TestOrchestratorSkillGlobals:
    """Cycle 14: Orchestrator injects skill globals into REPL when enabled_skills is set.

    These tests verify orchestrator setup phase only (skill globals injection,
    state writes). Full end-to-end dispatch is tested in
    test_skill_thread_bridge_e2e.py.
    """

    @pytest.mark.asyncio
    async def test_skill_globals_injected_when_enabled(self) -> None:
        """When enabled_skills=('recursive_ping',), repl.globals has 'run_recursive_ping'."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        orch = _make_orch(repl, enabled_skills=("recursive_ping",))

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        await _collect_orch_events(orch, mock_ctx)

        assert "run_recursive_ping" in repl.globals
        assert callable(repl.globals["run_recursive_ping"])
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_skill_globals_injected_unconditionally(self) -> None:
        """Even with enabled_skills=(), repl.globals contains skill functions.

        Cycle 20 made collect_skill_repl_globals() unconditional so child
        orchestrators (which default to enabled_skills=()) still get skill
        functions in the REPL for thread-bridge calls.  Only SkillToolset
        discovery tools are gated by enabled_skills.
        """
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        orch = _make_orch(repl, enabled_skills=())

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        await _collect_orch_events(orch, mock_ctx)

        assert "run_recursive_ping" in repl.globals
        assert callable(repl.globals["run_recursive_ping"])
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_repl_skill_globals_injected_state_key(self) -> None:
        """REPL_SKILL_GLOBALS_INJECTED is emitted in the initial state delta event."""
        from rlm_adk.repl.local_repl import LocalREPL
        from rlm_adk.state import REPL_SKILL_GLOBALS_INJECTED

        repl = LocalREPL(depth=1)
        orch = _make_orch(repl, enabled_skills=("recursive_ping",))

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test-inv-id"
        mock_ctx.session.state = {}

        events = await _collect_orch_events(orch, mock_ctx)

        # Find the initial state delta event
        state_events = [
            e for e in events
            if hasattr(e, "actions") and e.actions and e.actions.state_delta
        ]
        assert len(state_events) >= 1

        # The first state delta should contain the skill globals key
        initial_delta = state_events[0].actions.state_delta
        assert REPL_SKILL_GLOBALS_INJECTED in initial_delta
        # Value should list the injected skill function names
        assert "run_recursive_ping" in initial_delta[REPL_SKILL_GLOBALS_INJECTED]
        repl.cleanup()
