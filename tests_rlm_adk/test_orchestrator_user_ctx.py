"""Tests for orchestrator user-context wiring (Path A + Path B).

These tests verify:
- Path A: env-var-based context loading (RLM_USER_CTX_DIR)
- Path B: session-state pre-seeded user_provided_ctx fallback
- Manifest generation from pre-seeded dicts
- Replay fixture loading and validation as BenchmarkCase
- Scoring with mock agent output
"""

import inspect
import json
import os

from rlm_adk.state import (
    DYN_USER_CTX_MANIFEST,
    USER_PROVIDED_CTX,
    USER_PROVIDED_CTX_EXCEEDED,
    USR_PROVIDED_FILES_SERIALIZED,
    USR_PROVIDED_FILES_UNSERIALIZED,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _simulate_orchestrator_wiring(
    monkeypatch, ctx_dir=None, max_chars="500000", pre_seeded_ctx=None
):
    """Simulate the orchestrator's context loading logic (Path A + Path B).

    Mirrors the code block in _run_async_impl.
    """
    if ctx_dir is not None:
        monkeypatch.setenv("RLM_USER_CTX_DIR", str(ctx_dir))
    else:
        monkeypatch.delenv("RLM_USER_CTX_DIR", raising=False)

    monkeypatch.setenv("RLM_USER_CTX_MAX_CHARS", max_chars)

    _ctx_dir = os.getenv("RLM_USER_CTX_DIR")
    initial_state: dict = {}
    repl_globals: dict = {}

    # Simulate session state
    session_state: dict = {}
    if pre_seeded_ctx is not None:
        session_state[USER_PROVIDED_CTX] = pre_seeded_ctx

    # --- Path A: env var ---
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

    # --- Path B: pre-seeded session state ---
    elif session_state.get(USER_PROVIDED_CTX):
        _pre_seeded = session_state[USER_PROVIDED_CTX]
        initial_state[USER_PROVIDED_CTX] = _pre_seeded
        # Build manifest from the pre-seeded dict
        _filenames = sorted(k for k in _pre_seeded if not k.startswith("_"))
        _manifest_lines = [
            "Pre-loaded context variable: user_ctx (dict)",
            'Pre-loaded files (access via user_ctx["<filename>"]):',
        ]
        for _fn in _filenames:
            _content = _pre_seeded[_fn]
            if isinstance(_content, str):
                _chars = len(_content)
            else:
                _chars = len(json.dumps(_content, default=str))
            _manifest_lines.append(f"  - {_fn} ({_chars:,} chars)")
        _manifest_lines.append(f"Total: {len(_filenames)} files, {len(_filenames)} pre-loaded")
        _manifest_str = "\n".join(_manifest_lines)
        initial_state[DYN_USER_CTX_MANIFEST] = _manifest_str
        initial_state[USER_PROVIDED_CTX_EXCEEDED] = session_state.get(
            USER_PROVIDED_CTX_EXCEEDED,
            False,
        )
        initial_state[USR_PROVIDED_FILES_SERIALIZED] = session_state.get(
            USR_PROVIDED_FILES_SERIALIZED,
            _filenames,
        )
        initial_state[USR_PROVIDED_FILES_UNSERIALIZED] = session_state.get(
            USR_PROVIDED_FILES_UNSERIALIZED,
            [],
        )
        repl_globals["user_ctx"] = _pre_seeded

    return initial_state, repl_globals


# ── Test 1: env var not set, no pre-seed ─────────────────────────────────────


def test_env_var_not_set_no_context_loaded(monkeypatch):
    """When RLM_USER_CTX_DIR is not set and no pre-seed, no user context keys."""
    initial_state, repl_globals = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=None)
    assert USER_PROVIDED_CTX not in initial_state
    assert "user_ctx" not in repl_globals


# ── Test 2: env var set with valid dir (Path A) ─────────────────────────────


def test_env_var_set_loads_context(monkeypatch, tmp_path):
    """When RLM_USER_CTX_DIR points to a valid dir with files, ctx dict has both files."""
    (tmp_path / "notes.txt").write_text("meeting notes here")
    (tmp_path / "spec.md").write_text("# Spec\ndetails")

    initial_state, _ = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=tmp_path)

    ctx = initial_state[USER_PROVIDED_CTX]
    assert "notes.txt" in ctx
    assert "spec.md" in ctx
    assert ctx["notes.txt"] == "meeting notes here"


# ── Test 3: env var set to invalid dir ───────────────────────────────────────


def test_env_var_set_invalid_dir_skipped(monkeypatch, tmp_path):
    """When RLM_USER_CTX_DIR points to a non-existent path, no crash and no keys."""
    fake_dir = tmp_path / "does_not_exist"
    initial_state, repl_globals = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=str(fake_dir))
    assert USER_PROVIDED_CTX not in initial_state
    assert "user_ctx" not in repl_globals


# ── Test 4: all 5 state keys populated (Path A) ─────────────────────────────


def test_context_populates_all_state_keys(monkeypatch, tmp_path):
    """All 5 state keys are populated when context is loaded via env var."""
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


# ── Test 5: repl globals injection (Path A) ─────────────────────────────────


def test_context_injected_into_repl_globals(monkeypatch, tmp_path):
    """repl.globals['user_ctx'] is set to the ctx dict (Path A)."""
    (tmp_path / "data.txt").write_text("some data")

    initial_state, repl_globals = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=tmp_path)

    assert "user_ctx" in repl_globals
    assert repl_globals["user_ctx"] is initial_state[USER_PROVIDED_CTX]
    assert repl_globals["user_ctx"]["data.txt"] == "some data"


# ── Test 6: max chars env var respected ──────────────────────────────────────


def test_max_chars_env_var_respected(monkeypatch, tmp_path):
    """When RLM_USER_CTX_MAX_CHARS is small, files are evicted."""
    (tmp_path / "small.txt").write_text("hi")  # 2 chars
    (tmp_path / "big.txt").write_text("x" * 100)  # 100 chars

    # Budget of 10 chars: only small.txt fits
    initial_state, _ = _simulate_orchestrator_wiring(monkeypatch, ctx_dir=tmp_path, max_chars="10")

    assert initial_state[USER_PROVIDED_CTX_EXCEEDED] is True
    assert "small.txt" in initial_state[USR_PROVIDED_FILES_SERIALIZED]
    assert "big.txt" in initial_state[USR_PROVIDED_FILES_UNSERIALIZED]
    assert "big.txt" not in initial_state[USER_PROVIDED_CTX]


# ── Test 7: orchestrator source contains the wiring ──────────────────────────


def test_orchestrator_has_user_context_wiring():
    """Verify the orchestrator source code contains the user context wiring block."""
    from rlm_adk.orchestrator import RLMOrchestratorAgent

    source = inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    assert "RLM_USER_CTX_DIR" in source, (
        "orchestrator._run_async_impl must read RLM_USER_CTX_DIR env var"
    )
    assert "load_user_context" in source, "orchestrator._run_async_impl must call load_user_context"
    assert "user_ctx" in source, (
        "orchestrator._run_async_impl must inject user_ctx into REPL globals"
    )


# ── Test 8: orchestrator imports the state constants ─────────────────────────


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
        assert hasattr(orch_mod, const_name), f"orchestrator module must import {const_name}"


# ===========================================================================
# Path B: pre-seeded session state tests
# ===========================================================================


# ── Test 9: pre-seeded user_provided_ctx injects into repl globals ───────────


def test_pre_seeded_ctx_injects_repl_globals(monkeypatch):
    """Path B: pre-seeded user_provided_ctx gets injected into repl.globals['user_ctx']."""
    pre_seeded = {
        "notes.txt": "some notes",
        "data.json": {"key": "value"},
    }
    initial_state, repl_globals = _simulate_orchestrator_wiring(
        monkeypatch,
        pre_seeded_ctx=pre_seeded,
    )

    assert "user_ctx" in repl_globals
    assert repl_globals["user_ctx"] is pre_seeded
    assert repl_globals["user_ctx"]["notes.txt"] == "some notes"


# ── Test 10: pre-seeded ctx populates all 5 state keys ──────────────────────


def test_pre_seeded_ctx_populates_all_state_keys(monkeypatch):
    """Path B: all 5 state keys populated from pre-seeded dict."""
    pre_seeded = {
        "intake.md": "# Intake\nDetails",
        "w2.json": {"box_1": 41500},
    }
    initial_state, _ = _simulate_orchestrator_wiring(
        monkeypatch,
        pre_seeded_ctx=pre_seeded,
    )

    expected_keys = {
        USER_PROVIDED_CTX,
        USER_PROVIDED_CTX_EXCEEDED,
        USR_PROVIDED_FILES_SERIALIZED,
        USR_PROVIDED_FILES_UNSERIALIZED,
        DYN_USER_CTX_MANIFEST,
    }
    assert expected_keys.issubset(initial_state.keys())


# ── Test 11: manifest generation from pre-seeded dict ────────────────────────


def test_pre_seeded_manifest_generation(monkeypatch):
    """Path B: manifest string is well-formed and contains file entries."""
    pre_seeded = {
        "taxpayer_intake.md": "# Taxpayer Intake Notes\nSome content here.",
        "w2_meijer.json": {"box_1_wages": 41500.00},
        "_manifest": [{"filename": "taxpayer_intake.md"}],  # internal key, should be skipped
    }
    initial_state, _ = _simulate_orchestrator_wiring(
        monkeypatch,
        pre_seeded_ctx=pre_seeded,
    )

    manifest = initial_state[DYN_USER_CTX_MANIFEST]
    assert "user_ctx" in manifest
    assert "taxpayer_intake.md" in manifest
    assert "w2_meijer.json" in manifest
    assert "_manifest" not in manifest  # internal keys excluded
    assert "Total: 2 files, 2 pre-loaded" in manifest


# ── Test 12: pre-seeded ctx serialized files list ────────────────────────────


def test_pre_seeded_serialized_files_list(monkeypatch):
    """Path B: USR_PROVIDED_FILES_SERIALIZED contains sorted non-internal keys."""
    pre_seeded = {
        "b_file.txt": "bbb",
        "a_file.txt": "aaa",
        "_manifest": [],
    }
    initial_state, _ = _simulate_orchestrator_wiring(
        monkeypatch,
        pre_seeded_ctx=pre_seeded,
    )

    serialized = initial_state[USR_PROVIDED_FILES_SERIALIZED]
    assert serialized == ["a_file.txt", "b_file.txt"]
    assert initial_state[USR_PROVIDED_FILES_UNSERIALIZED] == []
    assert initial_state[USER_PROVIDED_CTX_EXCEEDED] is False


# ── Test 13: env var takes priority over pre-seeded ──────────────────────────


def test_env_var_takes_priority_over_pre_seeded(monkeypatch, tmp_path):
    """Path A (env var) takes priority when both are present."""
    (tmp_path / "env_file.txt").write_text("from env")

    pre_seeded = {
        "state_file.txt": "from state",
    }
    initial_state, repl_globals = _simulate_orchestrator_wiring(
        monkeypatch,
        ctx_dir=tmp_path,
        pre_seeded_ctx=pre_seeded,
    )

    # Should load from env var (Path A), not from pre-seeded (Path B)
    ctx = initial_state[USER_PROVIDED_CTX]
    assert "env_file.txt" in ctx
    assert "state_file.txt" not in ctx


# ── Test 14: orchestrator source has Path B wiring ───────────────────────────


def test_orchestrator_has_path_b_wiring():
    """Verify the orchestrator source contains Path B fallback wiring."""
    from rlm_adk.orchestrator import RLMOrchestratorAgent

    source = inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    assert "USER_PROVIDED_CTX" in source, (
        "orchestrator._run_async_impl must reference USER_PROVIDED_CTX for Path B"
    )
    assert "ctx.session.state" in source, (
        "orchestrator._run_async_impl must read ctx.session.state for Path B"
    )


# ===========================================================================
# Benchmark case + scoring tests
# ===========================================================================


# ── Test 15: case_efile_auth loads and validates as BenchmarkCase ─────────────


def test_case_efile_auth_loads_as_benchmark_case():
    """case_efile_auth.json loads and validates as a BenchmarkCase."""
    from rlm_adk.eval.understand_bench.loader import load_case
    from rlm_adk.eval.understand_bench.types import BenchmarkCase

    case = load_case(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "rlm_adk",
            "eval",
            "understand_bench",
            "cases",
            "easy",
            "case_efile_auth.json",
        )
    )

    assert isinstance(case, BenchmarkCase)
    assert case.case_id == "case_efile_auth"
    assert case.difficulty == "easy"
    assert "taxpayer_intake.md" in case.provided_context_dict
    assert "w2_meijer.json" in case.provided_context_dict
    assert len(case.missing_artifacts) == 1
    assert case.missing_artifacts[0].artifact_name == "Prior-year AGI or IP PIN"
    assert case.gold_retrieval_order == ["Prior-year AGI or IP PIN"]


# ── Test 16: scoring with perfect agent output ───────────────────────────────


def test_scoring_perfect_agent_output():
    """Perfect agent output scores 100 on the efile_auth case."""
    from rlm_adk.eval.understand_bench.loader import load_case
    from rlm_adk.eval.understand_bench.scoring import AgentRetrievalOutput, score_result

    case = load_case(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "rlm_adk",
            "eval",
            "understand_bench",
            "cases",
            "easy",
            "case_efile_auth.json",
        )
    )

    agent_output = AgentRetrievalOutput(
        retrieved_artifacts=["Prior-year AGI or IP PIN"],
        halted=True,
        raw_output="The agent identified the missing AGI.",
    )

    result = score_result(case, agent_output)
    assert result.recall == 1.0
    assert result.precision == 1.0
    assert result.halt_score == 1.0
    assert result.total_score == 100.0


# ── Test 17: scoring with empty agent output ─────────────────────────────────


def test_scoring_empty_agent_output():
    """Empty agent output with halted=False scores poorly."""
    from rlm_adk.eval.understand_bench.loader import load_case
    from rlm_adk.eval.understand_bench.scoring import AgentRetrievalOutput, score_result

    case = load_case(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "rlm_adk",
            "eval",
            "understand_bench",
            "cases",
            "easy",
            "case_efile_auth.json",
        )
    )

    agent_output = AgentRetrievalOutput(
        retrieved_artifacts=[],
        halted=False,
        raw_output="Proceeded without identifying gaps.",
    )

    result = score_result(case, agent_output)
    assert result.recall == 0.0
    assert result.halt_score == 0.0
    # Should have proceeding_without_retrieval penalty
    assert "proceeding_without_retrieval" in result.penalties
    assert result.total_score == 0.0  # clamped to 0


# ── Test 18: scoring with partial match (category match) ─────────────────────


def test_scoring_partial_category_match():
    """Category-level match gives 50% recall credit."""
    from rlm_adk.eval.understand_bench.loader import load_case
    from rlm_adk.eval.understand_bench.scoring import AgentRetrievalOutput, score_result

    case = load_case(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "rlm_adk",
            "eval",
            "understand_bench",
            "cases",
            "easy",
            "case_efile_auth.json",
        )
    )

    # Use a category-level match: mentions "credential" but not the exact artifact
    agent_output = AgentRetrievalOutput(
        retrieved_artifacts=["Authentication credential for e-file"],
        halted=True,
        raw_output="Need authentication credential.",
    )

    result = score_result(case, agent_output)
    assert result.recall == 0.5  # category match = 50% credit
    assert result.halt_score == 1.0
    assert result.total_score > 0


# ===========================================================================
# Replay fixture tests
# ===========================================================================


# ── Test 19: replay fixture is valid JSON and has required fields ────────────


def test_replay_fixture_bench_case_efile_auth_valid():
    """bench_case_efile_auth.json is valid JSON with required replay fields."""
    fixture_path = os.path.join(
        os.path.dirname(__file__),
        "replay",
        "bench_case_efile_auth.json",
    )
    assert os.path.isfile(fixture_path), f"Replay fixture not found: {fixture_path}"

    with open(fixture_path) as f:
        data = json.load(f)

    # Must have state and queries
    assert "state" in data
    assert "queries" in data

    state = data["state"]
    assert USER_PROVIDED_CTX in state
    assert DYN_USER_CTX_MANIFEST in state
    assert state.get("app:max_iterations", 0) >= 15
    assert state.get("app:max_depth", 0) >= 2

    # user_provided_ctx must contain the case's provided_context_dict
    ctx = state[USER_PROVIDED_CTX]
    assert "taxpayer_intake.md" in ctx
    assert "w2_meijer.json" in ctx


# ── Test 20: pre-seeded dict from fixture generates valid manifest ───────────


def test_fixture_pre_seeded_manifest(monkeypatch):
    """Pre-seeding from the replay fixture's user_provided_ctx produces valid manifest."""
    fixture_path = os.path.join(
        os.path.dirname(__file__),
        "replay",
        "bench_case_efile_auth.json",
    )
    with open(fixture_path) as f:
        data = json.load(f)

    pre_seeded = data["state"][USER_PROVIDED_CTX]
    initial_state, repl_globals = _simulate_orchestrator_wiring(
        monkeypatch,
        pre_seeded_ctx=pre_seeded,
    )

    assert "user_ctx" in repl_globals
    manifest = initial_state[DYN_USER_CTX_MANIFEST]
    assert "taxpayer_intake.md" in manifest
    assert "w2_meijer.json" in manifest
    assert "prior_year_summary.json" in manifest
