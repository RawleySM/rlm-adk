"""Tests for T1 Workflow-First 3-Layer polya_understand topology.

Uses expand_skill_imports() + exec() pattern to test the source-expandable
REPL exports without requiring a live REPL session.
"""

from __future__ import annotations

import ast

import pytest

from rlm_adk.repl.skill_registry import _registry, expand_skill_imports

pytestmark = pytest.mark.provider_fake_contract


# ---------------------------------------------------------------------------
# Helpers: expand + exec the T1 module into a namespace dict
# ---------------------------------------------------------------------------


def _expand_and_exec(*symbol_names: str) -> dict:
    """Expand the given symbols from rlm_repl_skills.polya_understand_t1_workflow
    and exec them into a fresh namespace dict."""
    # Trigger side-effect registration
    import rlm_adk.skills.polya_understand_t1_workflow  # noqa: F401

    import_line = (
        "from rlm_repl_skills.polya_understand_t1_workflow import "
        + ", ".join(symbol_names)
    )
    result = expand_skill_imports(import_line)
    assert result.did_expand, f"expand_skill_imports did not expand: {import_line}"
    ns: dict = {}
    exec(result.expanded_code, ns)  # noqa: S102
    return ns


# ---------------------------------------------------------------------------
# Test: expanded code is valid Python
# ---------------------------------------------------------------------------


class TestExpandedCodeValidity:
    """All source strings must produce valid Python when expanded."""

    def test_all_exports_expand_to_valid_python(self):
        """Expand the main entry point (pulls all deps) and verify it parses."""
        ns = _expand_and_exec("run_polya_understand_t1_workflow")
        assert "run_polya_understand_t1_workflow" in ns

    def test_expanded_code_parses_as_ast(self):
        """The expanded source must parse without SyntaxError."""
        import rlm_adk.skills.polya_understand_t1_workflow  # noqa: F401

        code = (
            "from rlm_repl_skills.polya_understand_t1_workflow import "
            "run_polya_understand_t1_workflow"
        )
        result = expand_skill_imports(code)
        assert result.did_expand
        # Must not raise SyntaxError
        ast.parse(result.expanded_code)


# ---------------------------------------------------------------------------
# Test: parse_workflow_steps
# ---------------------------------------------------------------------------


class TestParseWorkflowSteps:
    """parse_workflow_steps extracts steps from various formats."""

    @pytest.fixture()
    def parse_fn(self):
        ns = _expand_and_exec("parse_workflow_steps")
        return ns["parse_workflow_steps"]

    def test_numbered_steps(self, parse_fn):
        text = "1. Check API docs\n2. Verify schema\n3. Review tests"
        steps = parse_fn(text)
        assert steps == ["Check API docs", "Verify schema", "Review tests"]

    def test_bullet_steps(self, parse_fn):
        text = "- Check API docs\n- Verify schema\n- Review tests"
        steps = parse_fn(text)
        assert steps == ["Check API docs", "Verify schema", "Review tests"]

    def test_plain_lines(self, parse_fn):
        text = "Check API docs\nVerify schema\nReview tests"
        steps = parse_fn(text)
        assert steps == ["Check API docs", "Verify schema", "Review tests"]

    def test_max_steps_clamping(self, parse_fn):
        text = "\n".join(f"{i}. Step {i}" for i in range(1, 20))
        steps = parse_fn(text, max_steps=3)
        assert len(steps) == 3

    def test_empty_input(self, parse_fn):
        assert parse_fn("") == []
        assert parse_fn(None) == []

    def test_blank_lines_skipped(self, parse_fn):
        text = "1. First\n\n2. Second\n\n\n3. Third"
        steps = parse_fn(text)
        assert len(steps) == 3

    def test_parenthesized_numbered(self, parse_fn):
        text = "1) Check API docs\n2) Verify schema"
        steps = parse_fn(text)
        assert steps == ["Check API docs", "Verify schema"]


# ---------------------------------------------------------------------------
# Test: parse_step_assessment
# ---------------------------------------------------------------------------


class TestParseStepAssessment:
    """parse_step_assessment extracts STATUS/EVIDENCE/GAPS/L2_DISPATCH."""

    @pytest.fixture()
    def parse_fn(self):
        ns = _expand_and_exec("parse_step_assessment")
        return ns["parse_step_assessment"]

    def test_sufficient(self, parse_fn):
        text = (
            "STATUS: SUFFICIENT\n"
            "EVIDENCE: Found API docs in api.md\n"
            "GAPS: NONE\n"
            "L2_DISPATCH: NO"
        )
        assessment, wants_l2 = parse_fn(text, "Check API docs")
        assert assessment.status == "SUFFICIENT"
        assert assessment.evidence == "Found API docs in api.md"
        assert assessment.gaps == "NONE"
        assert wants_l2 is False
        assert assessment.step_description == "Check API docs"

    def test_partial_with_l2(self, parse_fn):
        text = (
            "STATUS: PARTIAL\n"
            "EVIDENCE: Some coverage found\n"
            "GAPS: Missing auth details\n"
            "L2_DISPATCH: YES"
        )
        assessment, wants_l2 = parse_fn(text, "Verify auth")
        assert assessment.status == "PARTIAL"
        assert wants_l2 is True

    def test_missing_status(self, parse_fn):
        text = (
            "STATUS: MISSING\n"
            "EVIDENCE: No relevant content found\n"
            "GAPS: Everything is missing\n"
            "L2_DISPATCH: NO"
        )
        assessment, wants_l2 = parse_fn(text, "Find schema")
        assert assessment.status == "MISSING"

    def test_missing_markers_defaults(self, parse_fn):
        """When markers are absent, defaults apply."""
        text = "Some unstructured response without markers."
        assessment, wants_l2 = parse_fn(text, "Some step")
        assert assessment.status == "MISSING"  # default
        assert assessment.evidence == ""
        assert assessment.gaps == ""
        assert wants_l2 is False

    def test_raw_response_preserved(self, parse_fn):
        text = "STATUS: SUFFICIENT\nEVIDENCE: ok\nGAPS: NONE\nL2_DISPATCH: NO"
        assessment, _ = parse_fn(text, "step")
        assert assessment.raw_response == text


# ---------------------------------------------------------------------------
# Test: parse_chunk_assessment
# ---------------------------------------------------------------------------


class TestParseChunkAssessment:
    """parse_chunk_assessment extracts CHUNK_STATUS/RELEVANCE/SUMMARY."""

    @pytest.fixture()
    def parse_fn(self):
        ns = _expand_and_exec("parse_chunk_assessment")
        return ns["parse_chunk_assessment"]

    def test_present(self, parse_fn):
        text = (
            "CHUNK_STATUS: PRESENT\n"
            "RELEVANCE: 0.85\n"
            "SUMMARY: Contains API endpoint definitions"
        )
        ca = parse_fn(text, "chunk_1")
        assert ca.status == "PRESENT"
        assert ca.relevance_score == pytest.approx(0.85)
        assert ca.summary == "Contains API endpoint definitions"
        assert ca.chunk_id == "chunk_1"

    def test_absent(self, parse_fn):
        text = (
            "CHUNK_STATUS: ABSENT\n"
            "RELEVANCE: 0.1\n"
            "SUMMARY: NONE"
        )
        ca = parse_fn(text, "chunk_2")
        assert ca.status == "ABSENT"
        assert ca.relevance_score == pytest.approx(0.1)

    def test_missing_markers_defaults(self, parse_fn):
        text = "No relevant markers here."
        ca = parse_fn(text, "chunk_x")
        assert ca.status == "ABSENT"  # default
        assert ca.relevance_score == 0.0
        assert ca.summary == ""

    def test_invalid_relevance_defaults_to_zero(self, parse_fn):
        text = "CHUNK_STATUS: PRESENT\nRELEVANCE: high\nSUMMARY: stuff"
        ca = parse_fn(text, "chunk_3")
        assert ca.relevance_score == 0.0


# ---------------------------------------------------------------------------
# Test: needs_l2_dispatch
# ---------------------------------------------------------------------------


class TestNeedsL2Dispatch:
    """needs_l2_dispatch checks packet count against threshold."""

    @pytest.fixture()
    def needs_fn(self):
        ns = _expand_and_exec("needs_l2_dispatch")
        return ns["needs_l2_dispatch"]

    def test_below_threshold(self, needs_fn):
        assert needs_fn(["a", "b", "c"], threshold=4) is False

    def test_at_threshold(self, needs_fn):
        assert needs_fn(["a", "b", "c", "d"], threshold=4) is False

    def test_above_threshold(self, needs_fn):
        assert needs_fn(["a", "b", "c", "d", "e"], threshold=4) is True

    def test_empty_packets(self, needs_fn):
        assert needs_fn([], threshold=4) is False

    def test_default_threshold(self, needs_fn):
        # Default threshold is 4
        assert needs_fn(["a", "b", "c", "d", "e"]) is True
        assert needs_fn(["a", "b", "c", "d"]) is False


# ---------------------------------------------------------------------------
# Test: build_workflow_prompt
# ---------------------------------------------------------------------------


class TestBuildWorkflowPrompt:
    """build_workflow_prompt assembles L0 prompt correctly."""

    @pytest.fixture()
    def build_fn(self):
        ns = _expand_and_exec("build_workflow_prompt")
        return ns["build_workflow_prompt"]

    def test_contains_objective(self, build_fn):
        prompt = build_fn("Understand the API", "MANIFEST: 3 files", max_steps=5)
        assert "Understand the API" in prompt

    def test_contains_manifest(self, build_fn):
        prompt = build_fn("objective", "MANIFEST: api.py (500 chars)", max_steps=5)
        assert "MANIFEST: api.py (500 chars)" in prompt

    def test_contains_max_steps(self, build_fn):
        prompt = build_fn("objective", "manifest", max_steps=6)
        assert "6" in prompt

    def test_contains_instructions(self, build_fn):
        prompt = build_fn("objective", "manifest")
        # Should contain the T1_WORKFLOW_INSTRUCTIONS content
        assert "WORKFLOW GENERATION" in prompt


# ---------------------------------------------------------------------------
# Test: build_step_assessment_prompt
# ---------------------------------------------------------------------------


class TestBuildStepAssessmentPrompt:
    """build_step_assessment_prompt assembles L1 prompt correctly."""

    @pytest.fixture()
    def build_fn(self):
        ns = _expand_and_exec("build_step_assessment_prompt")
        return ns["build_step_assessment_prompt"]

    def test_contains_step(self, build_fn):
        prompt = build_fn(
            "Check API docs", ["packet1"], "manifest", 0, 3, use_l2=False
        )
        assert "Check API docs" in prompt

    def test_contains_packets(self, build_fn):
        prompt = build_fn(
            "step", ["packet_content_here"], "manifest", 0, 1, use_l2=False
        )
        assert "packet_content_here" in prompt

    def test_with_l2_enabled(self, build_fn):
        prompt = build_fn(
            "step", ["p1"], "manifest", 0, 1, use_l2=True
        )
        assert "L2_DISPATCH" in prompt or "chunk-level" in prompt

    def test_without_l2(self, build_fn):
        prompt = build_fn(
            "step", ["p1"], "manifest", 0, 1, use_l2=False
        )
        # Should still contain the T1_ASSESS_INSTRUCTIONS which mention L2_DISPATCH
        assert "STATUS" in prompt

    def test_step_numbering(self, build_fn):
        prompt = build_fn("step", ["p1"], "manifest", 2, 5)
        assert "3/5" in prompt  # step_idx=2 -> displayed as 3


# ---------------------------------------------------------------------------
# Test: Result class construction
# ---------------------------------------------------------------------------


class TestResultClasses:
    """T1StepAssessment, T1ChunkAssessment, T1WorkflowResult construction."""

    @pytest.fixture()
    def classes(self):
        ns = _expand_and_exec(
            "T1StepAssessment", "T1ChunkAssessment", "T1WorkflowResult"
        )
        return ns

    def test_step_assessment_construction(self, classes):
        sa = classes["T1StepAssessment"](
            step_description="Check docs",
            status="SUFFICIENT",
            evidence="Found in README",
            gaps="NONE",
        )
        assert sa.step_description == "Check docs"
        assert sa.status == "SUFFICIENT"
        assert sa.evidence == "Found in README"
        assert sa.gaps == "NONE"
        assert sa.chunk_assessments == []
        assert sa.raw_response == ""

    def test_step_assessment_repr(self, classes):
        sa = classes["T1StepAssessment"](
            step_description="Check docs",
            status="PARTIAL",
            evidence="partial",
            gaps="missing auth section",
        )
        r = repr(sa)
        assert "T1StepAssessment" in r
        assert "PARTIAL" in r

    def test_chunk_assessment_construction(self, classes):
        ca = classes["T1ChunkAssessment"](
            chunk_id="step_1_chunk_3",
            status="PRESENT",
            relevance_score=0.9,
            summary="API docs found",
        )
        assert ca.chunk_id == "step_1_chunk_3"
        assert ca.status == "PRESENT"
        assert ca.relevance_score == 0.9
        assert ca.summary == "API docs found"
        assert ca.raw_response == ""

    def test_chunk_assessment_repr(self, classes):
        ca = classes["T1ChunkAssessment"](
            chunk_id="c1",
            status="ABSENT",
            relevance_score=0.1,
            summary="nothing",
        )
        r = repr(ca)
        assert "T1ChunkAssessment" in r
        assert "ABSENT" in r

    def test_workflow_result_construction(self, classes):
        wr = classes["T1WorkflowResult"](
            understanding="The project is well-documented.",
            workflow_steps=["Check docs", "Verify tests"],
            step_assessments=[],
            chunk_assessments={},
            gap_assessment="No significant gaps.",
            retrieval_order=["missing_auth.md"],
            used_l2=False,
            debug_log=["log1"],
        )
        assert wr.understanding == "The project is well-documented."
        assert len(wr.workflow_steps) == 2
        assert wr.retrieval_order == ["missing_auth.md"]
        assert wr.used_l2 is False
        assert wr.debug_log == ["log1"]

    def test_workflow_result_repr(self, classes):
        wr = classes["T1WorkflowResult"](
            understanding="u",
            workflow_steps=["s1", "s2"],
            step_assessments=[],
            chunk_assessments={},
            gap_assessment="g",
            retrieval_order=["r1"],
            used_l2=True,
        )
        r = repr(wr)
        assert "T1WorkflowResult" in r
        assert "steps=2" in r
        assert "used_l2=True" in r

    def test_workflow_result_default_debug_log(self, classes):
        wr = classes["T1WorkflowResult"](
            understanding="u",
            workflow_steps=[],
            step_assessments=[],
            chunk_assessments={},
            gap_assessment="",
            retrieval_order=[],
            used_l2=False,
        )
        assert wr.debug_log == []


# ---------------------------------------------------------------------------
# Test: catalog registration
# ---------------------------------------------------------------------------


class TestCatalogRegistration:
    """T1 workflow skill is registered in the catalog and skill registry."""

    def test_skill_in_catalog(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        assert "polya-understand-t1-workflow" in PROMPT_SKILL_REGISTRY

    def test_skill_instruction_block_nonempty(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        reg = PROMPT_SKILL_REGISTRY["polya-understand-t1-workflow"]
        block = reg.build_instruction_block()
        assert len(block) > 0
        assert "polya-understand-t1-workflow" in block

    def test_skill_in_default_enabled(self):
        from rlm_adk.skills.catalog import DEFAULT_ENABLED_SKILL_NAMES

        assert "polya-understand-t1-workflow" in DEFAULT_ENABLED_SKILL_NAMES

    def test_skill_exports_registered(self):
        """Side-effect registration populates _registry."""
        import rlm_adk.skills.polya_understand_t1_workflow  # noqa: F401

        module_name = "rlm_repl_skills.polya_understand_t1_workflow"
        assert module_name in _registry._exports
        exports = _registry._exports[module_name]
        expected_names = [
            "T1_WORKFLOW_INSTRUCTIONS",
            "T1_ASSESS_INSTRUCTIONS",
            "T1StepAssessment",
            "T1ChunkAssessment",
            "T1WorkflowResult",
            "stringify_context",
            "chunk_text",
            "condense_packets",
            "prepare_context_packets",
            "build_context_manifest",
            "extract_retrieval_order",
            "build_workflow_prompt",
            "parse_workflow_steps",
            "build_step_assessment_prompt",
            "build_chunk_assessment_prompt",
            "parse_step_assessment",
            "parse_chunk_assessment",
            "needs_l2_dispatch",
            "build_synthesis_prompt",
            "run_polya_understand_t1_workflow",
        ]
        for name in expected_names:
            assert name in exports, f"Missing export: {name}"

    def test_skill_in_init_all(self):
        from rlm_adk.skills import __all__

        assert "POLYA_UNDERSTAND_T1_WORKFLOW_SKILL" in __all__


# ---------------------------------------------------------------------------
# Test: context helpers (shared with v1, re-registered for T1)
# ---------------------------------------------------------------------------


class TestContextHelpers:
    """Context helpers work correctly when expanded from T1 module."""

    @pytest.fixture()
    def helpers(self):
        return _expand_and_exec(
            "stringify_context",
            "chunk_text",
            "condense_packets",
            "prepare_context_packets",
            "build_context_manifest",
            "extract_retrieval_order",
        )

    def test_stringify_context_string(self, helpers):
        assert helpers["stringify_context"]("hello") == "hello"

    def test_stringify_context_dict(self, helpers):
        result = helpers["stringify_context"]({"a": "val_a", "b": "val_b"})
        assert "[[a]]" in result
        assert "val_a" in result

    def test_stringify_context_none(self, helpers):
        assert helpers["stringify_context"](None) == ""

    def test_chunk_text_small(self, helpers):
        assert helpers["chunk_text"]("short", max_chars=100) == ["short"]

    def test_chunk_text_empty(self, helpers):
        assert helpers["chunk_text"]("") == [""]

    def test_build_context_manifest_dict(self, helpers):
        manifest = helpers["build_context_manifest"]({"a.py": "code", "b.py": "more"})
        assert "PROJECT CONTEXT MANIFEST" in manifest
        assert "a.py" in manifest

    def test_extract_retrieval_order_numbered(self, helpers):
        text = "RETRIEVAL_ORDER:\n1. auth_config.yaml\n2. db_schema.sql"
        items = helpers["extract_retrieval_order"](text)
        assert items == ["auth_config.yaml", "db_schema.sql"]

    def test_extract_retrieval_order_none(self, helpers):
        text = "RETRIEVAL_ORDER: NONE"
        items = helpers["extract_retrieval_order"](text)
        assert items == []

    def test_prepare_context_packets_dict(self, helpers):
        ctx = {"file1.py": "content1", "file2.py": "content2"}
        packets = helpers["prepare_context_packets"](ctx)
        assert len(packets) >= 1
        assert any("file1.py" in p for p in packets)


# ---------------------------------------------------------------------------
# Test: build_synthesis_prompt
# ---------------------------------------------------------------------------


class TestBuildSynthesisPrompt:
    """build_synthesis_prompt assembles final synthesis correctly."""

    @pytest.fixture()
    def build_fn(self):
        ns = _expand_and_exec(
            "build_synthesis_prompt", "T1StepAssessment", "T1ChunkAssessment"
        )
        return ns

    def test_contains_objective(self, build_fn):
        sa = build_fn["T1StepAssessment"](
            step_description="Check docs",
            status="SUFFICIENT",
            evidence="ok",
            gaps="NONE",
        )
        prompt = build_fn["build_synthesis_prompt"](
            "Understand the API",
            ["Check docs"],
            [sa],
            {},
            "manifest",
            False,
        )
        assert "Understand the API" in prompt

    def test_contains_step_assessments(self, build_fn):
        sa = build_fn["T1StepAssessment"](
            step_description="Verify schema",
            status="PARTIAL",
            evidence="Some evidence",
            gaps="Missing foreign keys",
        )
        prompt = build_fn["build_synthesis_prompt"](
            "objective",
            ["Verify schema"],
            [sa],
            {},
            "manifest",
            False,
        )
        assert "PARTIAL" in prompt
        assert "Missing foreign keys" in prompt

    def test_contains_chunk_assessments(self, build_fn):
        ca = build_fn["T1ChunkAssessment"](
            chunk_id="step_1_chunk_1",
            status="PRESENT",
            relevance_score=0.9,
            summary="Found schema defs",
        )
        prompt = build_fn["build_synthesis_prompt"](
            "objective",
            ["step1"],
            [],
            {0: [ca]},
            "manifest",
            True,
        )
        assert "step_1_chunk_1" in prompt
        assert "PRESENT" in prompt

    def test_contains_retrieval_order_marker(self, build_fn):
        prompt = build_fn["build_synthesis_prompt"](
            "obj", ["s1"], [], {}, "manifest", False
        )
        assert "RETRIEVAL_ORDER" in prompt


# ---------------------------------------------------------------------------
# Test: build_chunk_assessment_prompt
# ---------------------------------------------------------------------------


class TestBuildChunkAssessmentPrompt:
    """build_chunk_assessment_prompt assembles L2 prompt correctly."""

    @pytest.fixture()
    def build_fn(self):
        ns = _expand_and_exec("build_chunk_assessment_prompt")
        return ns["build_chunk_assessment_prompt"]

    def test_contains_chunk_and_step(self, build_fn):
        prompt = build_fn("chunk content here", "step desc here", 0, 3)
        assert "chunk content here" in prompt
        assert "step desc here" in prompt

    def test_contains_chunk_numbering(self, build_fn):
        prompt = build_fn("chunk", "step", 2, 5)
        assert "3/5" in prompt
