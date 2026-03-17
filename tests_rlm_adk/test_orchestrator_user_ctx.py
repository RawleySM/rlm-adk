"""Tests for orchestrator user-context wiring (Phase 2).

These tests verify the conditional env-var logic and state-delta population
that the orchestrator performs when RLM_USER_CTX_DIR is set.
"""

import inspect
import os

from rlm_adk.state import (
    DYN_USER_CTX_MANIFEST,
    USER_PROVIDED_CTX,
    USER_PROVIDED_CTX_EXCEEDED,
    USR_PROVIDED_FILES_SERIALIZED,
    USR_PROVIDED_FILES_UNSERIALIZED,
)


def _simulate_orchestrator_wiring(monkeypatch, ctx_dir=None, max_chars="500000"):
    """Simulate the orchestrator's context loading logic.

    Mirrors the code block that will be added to _run_async_impl.
    """
    if ctx_dir is not None:
        monkeypatch.setenv("RLM_USER_CTX_DIR", str(ctx_dir))
    else:
        monkeypatch.delenv("RLM_USER_CTX_DIR", raising=False)

    monkeypatch.setenv("RLM_USER_CTX_MAX_CHARS", max_chars)

    _ctx_dir = os.getenv("RLM_USER_CTX_DIR")
    initial_state: dict = {}
    repl_globals: dict = {}

    if _ctx_dir and os.path.isdir(_ctx_dir):
        from rlm_adk.utils.user_context import load_user_context

        _max = int(os.getenv("RLM_USER_CTX_MAX_CHARS", "500000"))
        uctx = load_user_context(_ctx_dir, _max)
        initial_state[USER_PROVIDED_CTX] = uctx.ctx
        initial_state[USER_PROVIDED_CTX_EXCEEDED] = uctx.exceeded
        initial_state[USR_PROVIDED_FILES_SERIALIZED] = uctx.serialized
        initial_state[USR_PROVIDED_FILES_UNSERIALIZED] = uctx.unserialized
        initial_state[DYN_USER_CTX_MANIFEST] = uctx.build_manifest()
        repl_globals["user_ctx"] = uctx.ctx

    return initial_state, repl_globals


# ── Test 1: env var not set ──────────────────────────────────────────────


def test_env_var_not_set_no_context_loaded(monkeypatch):
    """When RLM_USER_CTX_DIR is not set, no user context state keys are added."""
    initial_state, repl_globals = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=None)
    assert USER_PROVIDED_CTX not in initial_state
    assert "user_ctx" not in repl_globals


# ── Test 2: env var set with valid dir ───────────────────────────────────


def test_env_var_set_loads_context(monkeypatch, tmp_path):
    """When RLM_USER_CTX_DIR points to a valid dir with files, ctx dict has both files."""
    (tmp_path / "notes.txt").write_text("meeting notes here")
    (tmp_path / "spec.md").write_text("# Spec\ndetails")

    initial_state, _ = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=tmp_path)

    ctx = initial_state[USER_PROVIDED_CTX]
    assert "notes.txt" in ctx
    assert "spec.md" in ctx
    assert ctx["notes.txt"] == "meeting notes here"


# ── Test 3: env var set to invalid dir ───────────────────────────────────


def test_env_var_set_invalid_dir_skipped(monkeypatch, tmp_path):
    """When RLM_USER_CTX_DIR points to a non-existent path, no crash and no keys."""
    fake_dir = tmp_path / "does_not_exist"
    initial_state, repl_globals = _simulate_orchestrator_wiring(
        monkeypatch, ctx_dir=str(fake_dir)
    )
    assert USER_PROVIDED_CTX not in initial_state
    assert "user_ctx" not in repl_globals


# ── Test 4: all 5 state keys populated ───────────────────────────────────


def test_context_populates_all_state_keys(monkeypatch, tmp_path):
    """All 5 state keys are populated when context is loaded."""
    (tmp_path / "a.txt").write_text("aaa")

    initial_state, _ = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=tmp_path)

    expected_keys = {
        USER_PROVIDED_CTX,
        USER_PROVIDED_CTX_EXCEEDED,
        USR_PROVIDED_FILES_SERIALIZED,
        USR_PROVIDED_FILES_UNSERIALIZED,
        DYN_USER_CTX_MANIFEST,
    }
    assert expected_keys.issubset(initial_state.keys())


# ── Test 5: repl globals injection ───────────────────────────────────────


def test_context_injected_into_repl_globals(monkeypatch, tmp_path):
    """repl.globals['user_ctx'] is set to the ctx dict."""
    (tmp_path / "data.txt").write_text("some data")

    initial_state, repl_globals = _simulate_orchestrator_wiring(
        monkeypatch, ctx_dir=tmp_path
    )

    assert "user_ctx" in repl_globals
    assert repl_globals["user_ctx"] is initial_state[USER_PROVIDED_CTX]
    assert repl_globals["user_ctx"]["data.txt"] == "some data"


# ── Test 6: max chars env var respected ──────────────────────────────────


def test_max_chars_env_var_respected(monkeypatch, tmp_path):
    """When RLM_USER_CTX_MAX_CHARS is small, files are evicted."""
    (tmp_path / "small.txt").write_text("hi")  # 2 chars
    (tmp_path / "big.txt").write_text("x" * 100)  # 100 chars

    # Budget of 10 chars: only small.txt fits
    initial_state, _ = _simulate_orchestrator_wiring(
        monkeypatch, ctx_dir=tmp_path, max_chars="10"
    )

    assert initial_state[USER_PROVIDED_CTX_EXCEEDED] is True
    assert "small.txt" in initial_state[USR_PROVIDED_FILES_SERIALIZED]
    assert "big.txt" in initial_state[USR_PROVIDED_FILES_UNSERIALIZED]
    assert "big.txt" not in initial_state[USER_PROVIDED_CTX]


# ── Test 7: orchestrator source contains the wiring ──────────────────────


def test_orchestrator_has_user_context_wiring():
    """Verify the orchestrator source code contains the user context wiring block."""
    from rlm_adk.orchestrator import RLMOrchestratorAgent

    source = inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    assert "RLM_USER_CTX_DIR" in source, (
        "orchestrator._run_async_impl must read RLM_USER_CTX_DIR env var"
    )
    assert "load_user_context" in source, (
        "orchestrator._run_async_impl must call load_user_context"
    )
    assert "user_ctx" in source, (
        "orchestrator._run_async_impl must inject user_ctx into REPL globals"
    )


# ── Test 8: orchestrator imports the state constants ─────────────────────


def test_orchestrator_imports_state_constants():
    """Verify the orchestrator module imports all required user context state constants."""
    import rlm_adk.orchestrator as orch_mod

    for const_name in (
        "USER_PROVIDED_CTX",
        "USER_PROVIDED_CTX_EXCEEDED",
        "USR_PROVIDED_FILES_SERIALIZED",
        "USR_PROVIDED_FILES_UNSERIALIZED",
        "DYN_USER_CTX_MANIFEST",
    ):
        assert hasattr(orch_mod, const_name), (
            f"orchestrator module must import {const_name}"
        )
