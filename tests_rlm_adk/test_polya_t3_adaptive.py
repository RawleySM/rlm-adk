"""Tests for T3 Dimension-Adaptive Round-Trip polya_understand skill.

Uses _exec_exports() pattern: exec source strings from the skill registry
into a namespace dict, then test the resulting functions/classes.
"""

from __future__ import annotations

import pytest

from rlm_adk.repl.skill_registry import _registry, register_skill_export

pytestmark = pytest.mark.provider_fake_contract

_MODULE = "rlm_repl_skills.polya_understand_t3_adaptive"


def _exec_exports(*names: str) -> dict:
    """Exec source strings from the registry into a namespace and return it."""
    # Ensure the module is imported (triggers registration side-effects)
    import rlm_adk.skills.polya_understand_t3_adaptive  # noqa: F401

    mod_exports = _registry._exports.get(_MODULE)
    assert mod_exports is not None, f"Module {_MODULE} not registered"

    # Collect all requested exports + their transitive deps
    seen: dict[str, object] = {}
    queue = list(names)
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        export = mod_exports.get(name)
        assert export is not None, f"Export {name!r} not found in {_MODULE}"
        seen[name] = export
        for dep in export.requires:
            if dep not in seen:
                queue.append(dep)

    # Topological sort
    ordered = []
    visited: set[str] = set()

    def visit(n: str) -> None:
        if n in visited:
            return
        visited.add(n)
        exp = seen[n]
        for dep in exp.requires:
            if dep in seen:
                visit(dep)
        ordered.append(exp)

    for n in seen:
        visit(n)

    ns: dict = {}
    for exp in ordered:
        exec(exp.source, ns)  # noqa: S102
    return ns


# ---------------------------------------------------------------------------
# parse_selected_dimensions
# ---------------------------------------------------------------------------


class TestParseSelectedDimensions:
    def _parse(self, text, dims=None):
        ns = _exec_exports("parse_selected_dimensions", "POLYA_DIMENSIONS")
        dims = dims or ns["POLYA_DIMENSIONS"]
        return ns["parse_selected_dimensions"](text, dims)

    def test_valid_ids(self):
        text = "SELECTED: restatement\nSELECTED: givens\nSELECTED: unknowns"
        result = self._parse(text)
        ids = [d["id"] for d in result]
        assert ids == ["restatement", "givens", "unknowns"]

    def test_case_insensitive(self):
        text = "SELECTED: RESTATEMENT\nSELECTED: Givens"
        result = self._parse(text)
        ids = [d["id"] for d in result]
        assert "restatement" in ids
        assert "givens" in ids

    def test_dedup(self):
        text = "SELECTED: restatement\nSELECTED: restatement\nSELECTED: givens"
        result = self._parse(text)
        ids = [d["id"] for d in result]
        assert ids == ["restatement", "givens"]

    def test_unknown_ids_ignored(self):
        text = "SELECTED: restatement\nSELECTED: nonexistent_dim\nSELECTED: givens"
        result = self._parse(text)
        ids = [d["id"] for d in result]
        assert "nonexistent_dim" not in ids
        assert ids == ["restatement", "givens"]

    def test_empty_fallback_to_all(self):
        ns = _exec_exports("parse_selected_dimensions", "POLYA_DIMENSIONS")
        dims = ns["POLYA_DIMENSIONS"]
        result = ns["parse_selected_dimensions"]("no valid lines here", dims)
        assert len(result) == len(dims)
        assert result == list(dims)

    def test_none_input_fallback(self):
        ns = _exec_exports("parse_selected_dimensions", "POLYA_DIMENSIONS")
        dims = ns["POLYA_DIMENSIONS"]
        result = ns["parse_selected_dimensions"](None, dims)
        assert len(result) == len(dims)


# ---------------------------------------------------------------------------
# parse_probe_response
# ---------------------------------------------------------------------------


class TestParseProbeResponse:
    def _parse(self, text):
        ns = _exec_exports("parse_probe_response")
        return ns["parse_probe_response"](text)

    def test_full_structured(self):
        text = (
            "DIMENSION: restatement\n"
            "EVIDENCE: Found clear objective statement in README.\n"
            "GAPS: Missing deployment requirements.\n"
            "CONFIDENCE: HIGH"
        )
        result = self._parse(text)
        assert result.dimension == "restatement"
        assert "clear objective" in result.evidence
        assert "Missing deployment" in result.gaps
        assert result.confidence == "HIGH"

    def test_missing_confidence_defaults_low(self):
        text = (
            "DIMENSION: givens\n"
            "EVIDENCE: Some evidence here.\n"
            "GAPS: Some gaps here."
        )
        result = self._parse(text)
        assert result.confidence == "LOW"

    def test_empty_response(self):
        result = self._parse("")
        assert result.dimension == ""
        assert result.confidence == "LOW"
        assert result.raw_response == ""

    def test_none_response(self):
        result = self._parse(None)
        assert result.confidence == "LOW"

    def test_invalid_confidence_defaults_low(self):
        text = (
            "DIMENSION: restatement\n"
            "EVIDENCE: some\n"
            "GAPS: none\n"
            "CONFIDENCE: MAYBE"
        )
        result = self._parse(text)
        assert result.confidence == "LOW"


# ---------------------------------------------------------------------------
# identify_gaps
# ---------------------------------------------------------------------------


class TestIdentifyGaps:
    def _make_result(self, dim, confidence):
        ns = _exec_exports("T3ProbeResult")
        return ns["T3ProbeResult"](
            dimension=dim, evidence="e", gaps="g",
            confidence=confidence, raw_response="r",
        )

    def _identify(self, results, threshold):
        ns = _exec_exports("identify_gaps")
        return ns["identify_gaps"](results, threshold)

    def test_medium_threshold_low_is_gap(self):
        results = [
            self._make_result("restatement", "HIGH"),
            self._make_result("givens", "LOW"),
            self._make_result("unknowns", "MEDIUM"),
        ]
        gaps = self._identify(results, "MEDIUM")
        assert "givens" in gaps
        assert "restatement" not in gaps
        assert "unknowns" not in gaps

    def test_high_threshold_low_and_medium_are_gaps(self):
        results = [
            self._make_result("restatement", "HIGH"),
            self._make_result("givens", "LOW"),
            self._make_result("unknowns", "MEDIUM"),
        ]
        gaps = self._identify(results, "HIGH")
        assert "givens" in gaps
        assert "unknowns" in gaps
        assert "restatement" not in gaps

    def test_low_threshold_nothing_is_gap(self):
        results = [
            self._make_result("restatement", "HIGH"),
            self._make_result("givens", "LOW"),
            self._make_result("unknowns", "MEDIUM"),
        ]
        gaps = self._identify(results, "LOW")
        assert gaps == []

    def test_empty_results(self):
        gaps = self._identify([], "MEDIUM")
        assert gaps == []


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------


class TestBuildSelectPrompt:
    def test_contains_objective_and_manifest(self):
        ns = _exec_exports("build_select_prompt", "POLYA_DIMENSIONS")
        dims = ns["POLYA_DIMENSIONS"]
        prompt = ns["build_select_prompt"](
            "Test objective", "MANIFEST:\n  - file.py (100 chars)",
            dims, 4,
        )
        assert "Test objective" in prompt
        assert "MANIFEST" in prompt
        # Should contain dimension IDs
        assert "RESTATEMENT" in prompt
        assert "GIVENS" in prompt

    def test_contains_num_dimensions(self):
        ns = _exec_exports("build_select_prompt", "POLYA_DIMENSIONS")
        dims = ns["POLYA_DIMENSIONS"]
        prompt = ns["build_select_prompt"]("obj", "manifest", dims, 3)
        assert "3" in prompt


class TestBuildProbePrompt:
    def test_contains_dimension_and_context(self):
        ns = _exec_exports("build_probe_prompt")
        dim = {"id": "restatement", "label": "Restatement", "question_template": "Q"}
        prompt = ns["build_probe_prompt"](dim, "What is the goal?", "Some context here.")
        assert "RESTATEMENT" in prompt
        assert "Restatement" in prompt
        assert "What is the goal?" in prompt
        assert "Some context here." in prompt


class TestBuildReprobePrompt:
    def test_contains_round_2_marker_and_gaps(self):
        ns = _exec_exports("build_reprobe_prompt")
        dim = {"id": "givens", "label": "Givens Inventory", "question_template": "Q"}
        prompt = ns["build_reprobe_prompt"](
            dim, "Missing deployment docs.", "New context packet.",
        )
        assert "ROUND 2" in prompt
        assert "Missing deployment docs." in prompt
        assert "New context packet." in prompt
        assert "GIVENS" in prompt


# ---------------------------------------------------------------------------
# T3ProbeResult and T3AdaptiveResult construction
# ---------------------------------------------------------------------------


class TestT3ProbeResult:
    def test_construction(self):
        ns = _exec_exports("T3ProbeResult")
        r = ns["T3ProbeResult"](
            dimension="restatement",
            evidence="Found it.",
            gaps="None.",
            confidence="HIGH",
            raw_response="raw",
        )
        assert r.dimension == "restatement"
        assert r.evidence == "Found it."
        assert r.gaps == "None."
        assert r.confidence == "HIGH"
        assert r.raw_response == "raw"

    def test_repr(self):
        ns = _exec_exports("T3ProbeResult")
        r = ns["T3ProbeResult"](
            dimension="givens", evidence="ev", gaps="ga",
            confidence="MEDIUM", raw_response="rr",
        )
        rep = repr(r)
        assert "T3ProbeResult" in rep
        assert "givens" in rep
        assert "MEDIUM" in rep


class TestT3AdaptiveResult:
    def test_construction(self):
        ns = _exec_exports("T3AdaptiveResult")
        r = ns["T3AdaptiveResult"](
            understanding="The project is about X.",
            selected_dimensions=["restatement", "givens"],
            round1_results=[],
            round2_results=[],
            gaps_detected=["givens"],
            retrieval_order=["deploy.md"],
            cycles_completed=2,
            debug_log=["msg1"],
        )
        assert r.understanding == "The project is about X."
        assert r.selected_dimensions == ["restatement", "givens"]
        assert r.gaps_detected == ["givens"]
        assert r.retrieval_order == ["deploy.md"]
        assert r.cycles_completed == 2
        assert r.debug_log == ["msg1"]

    def test_repr(self):
        ns = _exec_exports("T3AdaptiveResult")
        r = ns["T3AdaptiveResult"](
            understanding="u", selected_dimensions=["a", "b"],
            round1_results=[], round2_results=[],
            gaps_detected=["a"], retrieval_order=["x", "y"],
            cycles_completed=1,
        )
        rep = repr(r)
        assert "T3AdaptiveResult" in rep
        assert "dims=2" in rep
        assert "gaps=1" in rep

    def test_default_debug_log(self):
        ns = _exec_exports("T3AdaptiveResult")
        r = ns["T3AdaptiveResult"](
            understanding="u", selected_dimensions=[],
            round1_results=[], round2_results=[],
            gaps_detected=[], retrieval_order=[],
            cycles_completed=1,
        )
        assert r.debug_log == []


# ---------------------------------------------------------------------------
# extract_retrieval_order
# ---------------------------------------------------------------------------


class TestExtractRetrievalOrder:
    def _extract(self, text, max_items=8):
        ns = _exec_exports("extract_retrieval_order")
        return ns["extract_retrieval_order"](text, max_items)

    def test_numbered_list(self):
        text = (
            "RETRIEVAL_ORDER:\n"
            "1. deploy.md | category=DOCUMENT\n"
            "2. credentials.json | category=CREDENTIAL\n"
        )
        result = self._extract(text)
        assert result == ["deploy.md", "credentials.json"]

    def test_none_value(self):
        text = "RETRIEVAL_ORDER: NONE\n"
        result = self._extract(text)
        assert result == []

    def test_bullet_list(self):
        text = (
            "RETRIEVAL_ORDER:\n"
            "- deploy.md\n"
            "- config.yaml\n"
        )
        result = self._extract(text)
        assert result == ["deploy.md", "config.yaml"]

    def test_max_items_cap(self):
        text = "RETRIEVAL_ORDER:\n"
        for i in range(20):
            text += f"{i + 1}. item_{i}\n"
        result = self._extract(text, max_items=3)
        assert len(result) == 3

    def test_empty_text(self):
        result = self._extract("")
        assert result == []


# ---------------------------------------------------------------------------
# Skill registration and catalog
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    def test_module_registered(self):
        import rlm_adk.skills.polya_understand_t3_adaptive  # noqa: F401

        assert _MODULE in _registry._exports

    def test_all_exports_present(self):
        import rlm_adk.skills.polya_understand_t3_adaptive  # noqa: F401

        mod_exports = _registry._exports[_MODULE]
        expected = [
            # Constants
            "POLYA_DIMENSIONS",
            "T3_SELECT_INSTRUCTIONS",
            "T3_PROBE_INSTRUCTIONS",
            # Classes
            "T3ProbeResult",
            "T3AdaptiveResult",
            # Context helpers
            "stringify_context",
            "chunk_text",
            "condense_packets",
            "prepare_context_packets",
            "build_context_manifest",
            # T3-specific
            "assign_packets_to_dimensions",
            "extract_retrieval_order",
            "build_select_prompt",
            "parse_selected_dimensions",
            "build_probe_prompt",
            "parse_probe_response",
            "identify_gaps",
            "build_reprobe_prompt",
            "build_synthesis_prompt",
            "run_polya_understand_t3_adaptive",
        ]
        for name in expected:
            assert name in mod_exports, f"Missing export: {name}"

    def test_catalog_entry_exists(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        assert "polya-understand-t3-adaptive" in PROMPT_SKILL_REGISTRY
        reg = PROMPT_SKILL_REGISTRY["polya-understand-t3-adaptive"]
        assert reg.skill.frontmatter.name == "polya-understand-t3-adaptive"
        assert "adaptive" in reg.description.lower()

    def test_side_effect_module_path(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        reg = PROMPT_SKILL_REGISTRY["polya-understand-t3-adaptive"]
        assert "rlm_adk.skills.polya_understand_t3_adaptive" in reg.side_effect_modules


class TestTransitiveDeps:
    """Verify that requesting run_polya_understand_t3_adaptive pulls all deps."""

    def test_expansion_includes_transitive_deps(self):
        import rlm_adk.skills.polya_understand_t3_adaptive  # noqa: F401

        mod_exports = _registry._exports[_MODULE]
        run_export = mod_exports["run_polya_understand_t3_adaptive"]

        # Collect all transitive deps
        all_deps: set[str] = set()
        queue = list(run_export.requires)
        while queue:
            dep = queue.pop(0)
            if dep in all_deps:
                continue
            all_deps.add(dep)
            dep_export = mod_exports.get(dep)
            assert dep_export is not None, f"Missing transitive dep: {dep}"
            queue.extend(dep_export.requires)

        # All deps must exist in the module
        for dep in all_deps:
            assert dep in mod_exports, f"Transitive dep {dep!r} not in module"

        # Must include key transitive deps
        assert "stringify_context" in all_deps
        assert "chunk_text" in all_deps
        assert "condense_packets" in all_deps
        assert "T3_SELECT_INSTRUCTIONS" in all_deps
        assert "T3_PROBE_INSTRUCTIONS" in all_deps
        assert "T3ProbeResult" in all_deps

    def test_exec_all_exports_succeeds(self):
        """All source strings must exec without error."""
        ns = _exec_exports("run_polya_understand_t3_adaptive")
        assert "run_polya_understand_t3_adaptive" in ns
        assert "POLYA_DIMENSIONS" in ns
        assert "T3ProbeResult" in ns
        assert "T3AdaptiveResult" in ns
        assert "identify_gaps" in ns
        assert callable(ns["run_polya_understand_t3_adaptive"])
