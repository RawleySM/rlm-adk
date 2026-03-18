"""Tests for polya_understand_t2_flat skill: source expansion, extraction, and catalog."""

from __future__ import annotations

import ast

import pytest

from rlm_adk.repl.skill_registry import expand_skill_imports

pytestmark = pytest.mark.provider_fake_contract


# ---------------------------------------------------------------------------
# Helper: expand + exec a synthetic import to get testable functions/classes
# ---------------------------------------------------------------------------

def _expand_and_exec(import_line: str) -> dict:
    """Expand a synthetic import and exec the expanded code, returning the namespace."""
    # Ensure the side-effect module is imported so exports are registered
    import rlm_adk.skills.polya_understand_t2_flat  # noqa: F401

    result = expand_skill_imports(import_line)
    assert result.did_expand, f"Expansion failed for: {import_line!r}"
    ns: dict = {}
    exec(result.expanded_code, ns)  # noqa: S102
    return ns


def _get_all_exports() -> dict:
    """Expand all T2 flat exports into a single namespace."""
    code = (
        "from rlm_repl_skills.polya_understand_t2_flat import (\n"
        "    T2_FLAT_INSTRUCTIONS,\n"
        "    T2FlatResult,\n"
        "    stringify_context,\n"
        "    build_context_string,\n"
        "    generate_probing_questions,\n"
        "    build_investigation_prompt,\n"
        "    build_synthesis_prompt,\n"
        "    extract_verdict,\n"
        "    extract_gaps,\n"
        "    extract_coverage,\n"
        "    extract_understanding,\n"
        "    run_polya_understand_t2_flat,\n"
        ")\n"
    )
    return _expand_and_exec(code)


# ---------------------------------------------------------------------------
# Fixture: shared namespace with all expanded exports
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ns():
    return _get_all_exports()


# ===========================================================================
# Test: expanded code is valid Python
# ===========================================================================

class TestExpandedCodeValidity:
    def test_ast_parse(self, ns):
        """All expanded source blocks must be parseable Python."""
        import rlm_adk.skills.polya_understand_t2_flat  # noqa: F401

        code = (
            "from rlm_repl_skills.polya_understand_t2_flat import "
            "run_polya_understand_t2_flat"
        )
        result = expand_skill_imports(code)
        assert result.did_expand
        # Must not raise SyntaxError
        tree = ast.parse(result.expanded_code)
        assert isinstance(tree, ast.Module)


# ===========================================================================
# Test: stringify_context
# ===========================================================================

class TestStringifyContext:
    def test_string_passthrough(self, ns):
        fn = ns["stringify_context"]
        assert fn("hello") == "hello"

    def test_none_returns_empty(self, ns):
        fn = ns["stringify_context"]
        assert fn(None) == ""

    def test_dict_sorted_keys(self, ns):
        fn = ns["stringify_context"]
        result = fn({"b": "val_b", "a": "val_a"})
        assert "[[a]]" in result
        assert "[[b]]" in result
        # a should appear before b (sorted)
        assert result.index("[[a]]") < result.index("[[b]]")

    def test_list(self, ns):
        fn = ns["stringify_context"]
        result = fn(["first", "second"])
        assert "[[item_1]]" in result
        assert "[[item_2]]" in result

    def test_other_type_uses_repr(self, ns):
        fn = ns["stringify_context"]
        result = fn(42)
        assert result == "42"


# ===========================================================================
# Test: build_context_string
# ===========================================================================

class TestBuildContextString:
    def test_string_context(self, ns):
        fn = ns["build_context_string"]
        assert fn("some context") == "some context"

    def test_none_returns_empty_marker(self, ns):
        fn = ns["build_context_string"]
        assert fn(None) == "[[empty_context]]"

    def test_empty_string_returns_empty_marker(self, ns):
        fn = ns["build_context_string"]
        assert fn("") == "[[empty_context]]"

    def test_dict_context(self, ns):
        fn = ns["build_context_string"]
        result = fn({"file.py": "contents"})
        assert "[[file.py]]" in result
        assert "contents" in result


# ===========================================================================
# Test: generate_probing_questions
# ===========================================================================

class TestGenerateProbingQuestions:
    def test_default_count(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn("build a widget", "some context")
        assert len(questions) == 5

    def test_custom_count(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn("build a widget", "some context", num_questions=3)
        assert len(questions) == 3

    def test_clamp_min(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn("build a widget", "some context", num_questions=0)
        assert len(questions) == 1

    def test_clamp_max(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn("build a widget", "some context", num_questions=20)
        assert len(questions) == 10

    def test_objective_in_questions(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn("deploy the service", "ctx", num_questions=3)
        for q in questions:
            assert "deploy the service" in q

    def test_empty_objective_fallback(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn("", "ctx", num_questions=2)
        for q in questions:
            assert "the stated objective" in q

    def test_none_objective_fallback(self, ns):
        fn = ns["generate_probing_questions"]
        questions = fn(None, "ctx", num_questions=2)
        for q in questions:
            assert "the stated objective" in q


# ===========================================================================
# Test: extract_verdict
# ===========================================================================

class TestExtractVerdict:
    def test_sufficient(self, ns):
        fn = ns["extract_verdict"]
        assert fn("VERDICT: SUFFICIENT") == "SUFFICIENT"

    def test_partial(self, ns):
        fn = ns["extract_verdict"]
        assert fn("VERDICT: PARTIAL") == "PARTIAL"

    def test_insufficient(self, ns):
        fn = ns["extract_verdict"]
        assert fn("VERDICT: INSUFFICIENT") == "INSUFFICIENT"

    def test_case_insensitive(self, ns):
        fn = ns["extract_verdict"]
        assert fn("verdict: sufficient") == "SUFFICIENT"

    def test_absent_defaults_partial(self, ns):
        fn = ns["extract_verdict"]
        assert fn("no verdict here") == "PARTIAL"

    def test_none_defaults_partial(self, ns):
        fn = ns["extract_verdict"]
        assert fn(None) == "PARTIAL"

    def test_multiline(self, ns):
        fn = ns["extract_verdict"]
        text = "UNDERSTANDING: blah\nCOVERAGE: ok\nVERDICT: INSUFFICIENT\nGAPS: none"
        assert fn(text) == "INSUFFICIENT"


# ===========================================================================
# Test: extract_gaps
# ===========================================================================

class TestExtractGaps:
    def test_bullet_list(self, ns):
        fn = ns["extract_gaps"]
        text = "GAPS:\n- Missing API docs\n- No test coverage\n\nVERDICT: PARTIAL"
        gaps = fn(text)
        assert len(gaps) == 2
        assert "Missing API docs" in gaps
        assert "No test coverage" in gaps

    def test_none_keyword(self, ns):
        fn = ns["extract_gaps"]
        text = "GAPS: NONE\nVERDICT: SUFFICIENT"
        assert fn(text) == []

    def test_absent(self, ns):
        fn = ns["extract_gaps"]
        assert fn("no gaps section here") == []

    def test_none_input(self, ns):
        fn = ns["extract_gaps"]
        assert fn(None) == []

    def test_inline_gap(self, ns):
        fn = ns["extract_gaps"]
        text = "GAPS: Missing deployment config\nVERDICT: PARTIAL"
        gaps = fn(text)
        assert len(gaps) == 1
        assert "Missing deployment config" in gaps

    def test_na_keyword(self, ns):
        fn = ns["extract_gaps"]
        text = "GAPS: N/A\nVERDICT: SUFFICIENT"
        assert fn(text) == []


# ===========================================================================
# Test: extract_coverage
# ===========================================================================

class TestExtractCoverage:
    def test_extracts_value(self, ns):
        fn = ns["extract_coverage"]
        text = "COVERAGE_ASSESSMENT: Good coverage across all dimensions"
        assert fn(text) == "Good coverage across all dimensions"

    def test_absent(self, ns):
        fn = ns["extract_coverage"]
        assert fn("no coverage here") == ""

    def test_none_input(self, ns):
        fn = ns["extract_coverage"]
        assert fn(None) == ""

    def test_case_insensitive(self, ns):
        fn = ns["extract_coverage"]
        text = "coverage_assessment: Partial"
        assert fn(text) == "Partial"


# ===========================================================================
# Test: extract_understanding
# ===========================================================================

class TestExtractUnderstanding:
    def test_extracts_block(self, ns):
        fn = ns["extract_understanding"]
        text = (
            "UNDERSTANDING: This is the understanding.\n"
            "More details here.\n"
            "COVERAGE_ASSESSMENT: Good"
        )
        result = fn(text)
        assert "This is the understanding." in result
        assert "More details here." in result
        assert "COVERAGE_ASSESSMENT" not in result

    def test_stops_at_gaps(self, ns):
        fn = ns["extract_understanding"]
        text = "UNDERSTANDING: Brief.\nGAPS: Missing stuff"
        result = fn(text)
        assert "Brief." in result
        assert "GAPS" not in result

    def test_stops_at_verdict(self, ns):
        fn = ns["extract_understanding"]
        text = "UNDERSTANDING: Brief.\nVERDICT: SUFFICIENT"
        result = fn(text)
        assert "Brief." in result
        assert "VERDICT" not in result

    def test_no_marker_returns_full_text(self, ns):
        fn = ns["extract_understanding"]
        text = "Just plain text with no markers"
        assert fn(text) == text

    def test_none_returns_empty(self, ns):
        fn = ns["extract_understanding"]
        assert fn(None) == ""


# ===========================================================================
# Test: T2FlatResult
# ===========================================================================

class TestT2FlatResult:
    def test_construction(self, ns):
        cls = ns["T2FlatResult"]
        result = cls(
            understanding="test understanding",
            coverage_assessment="good",
            gaps=["gap1", "gap2"],
            verdict="SUFFICIENT",
            questions_asked=["q1", "q2"],
            investigation_responses=["r1", "r2"],
            debug_log=["log1"],
        )
        assert result.understanding == "test understanding"
        assert result.coverage_assessment == "good"
        assert result.gaps == ["gap1", "gap2"]
        assert result.verdict == "SUFFICIENT"
        assert result.questions_asked == ["q1", "q2"]
        assert result.investigation_responses == ["r1", "r2"]
        assert result.debug_log == ["log1"]

    def test_default_debug_log(self, ns):
        cls = ns["T2FlatResult"]
        result = cls(
            understanding="u",
            coverage_assessment="c",
            gaps=[],
            verdict="PARTIAL",
            questions_asked=[],
            investigation_responses=[],
        )
        assert result.debug_log == []

    def test_repr(self, ns):
        cls = ns["T2FlatResult"]
        result = cls(
            understanding="u",
            coverage_assessment="c",
            gaps=["g1"],
            verdict="PARTIAL",
            questions_asked=["q1", "q2"],
            investigation_responses=["r1", "r2"],
        )
        r = repr(result)
        assert "T2FlatResult" in r
        assert "PARTIAL" in r
        assert "gaps=1" in r
        assert "questions=2" in r


# ===========================================================================
# Test: prompt builders
# ===========================================================================

class TestBuildInvestigationPrompt:
    def test_contains_question_and_context(self, ns):
        fn = ns["build_investigation_prompt"]
        prompt = fn("What is the purpose?", "full context here")
        assert "What is the purpose?" in prompt
        assert "full context here" in prompt
        assert "INVESTIGATION" in prompt

    def test_contains_instructions(self, ns):
        fn = ns["build_investigation_prompt"]
        prompt = fn("question", "context")
        # Must contain the T2_FLAT_INSTRUCTIONS content
        assert "T2 Flat Open-Ended Polya" in prompt


class TestBuildSynthesisPrompt:
    def test_contains_qa_pairs(self, ns):
        fn = ns["build_synthesis_prompt"]
        prompt = fn("my objective", ["q1", "q2"], ["r1", "r2"])
        assert "my objective" in prompt
        assert "[Q1]" in prompt
        assert "[Q2]" in prompt
        assert "[A1]" in prompt
        assert "[A2]" in prompt
        assert "q1" in prompt
        assert "r2" in prompt
        assert "SYNTHESIS" in prompt


# ===========================================================================
# Test: catalog registration
# ===========================================================================

class TestCatalogRegistration:
    def test_t2_flat_in_registry(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        assert "polya-understand-t2-flat" in PROMPT_SKILL_REGISTRY

    def test_t2_flat_instruction_block(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        reg = PROMPT_SKILL_REGISTRY["polya-understand-t2-flat"]
        block = reg.build_instruction_block()
        assert "polya-understand-t2-flat" in block
        assert "T2 Flat" in block

    def test_t2_flat_skill_object(self):
        from rlm_adk.skills.polya_understand_t2_flat import POLYA_UNDERSTAND_T2_FLAT_SKILL

        assert POLYA_UNDERSTAND_T2_FLAT_SKILL.frontmatter.name == "polya-understand-t2-flat"
        assert "T2 Flat" in POLYA_UNDERSTAND_T2_FLAT_SKILL.frontmatter.description

    def test_t2_flat_in_init_exports(self):
        from rlm_adk.skills import POLYA_UNDERSTAND_T2_FLAT_SKILL  # noqa: F811

        assert POLYA_UNDERSTAND_T2_FLAT_SKILL.frontmatter.name == "polya-understand-t2-flat"

    def test_skill_registry_has_t2_module(self):
        """After import, the skill registry should have T2 flat exports."""
        import rlm_adk.skills.polya_understand_t2_flat  # noqa: F401
        from rlm_adk.repl.skill_registry import _registry

        assert "rlm_repl_skills.polya_understand_t2_flat" in _registry._exports
        exports = _registry._exports["rlm_repl_skills.polya_understand_t2_flat"]
        expected_names = {
            "T2_FLAT_INSTRUCTIONS",
            "T2FlatResult",
            "stringify_context",
            "build_context_string",
            "generate_probing_questions",
            "build_investigation_prompt",
            "build_synthesis_prompt",
            "extract_verdict",
            "extract_gaps",
            "extract_coverage",
            "extract_understanding",
            "run_polya_understand_t2_flat",
        }
        assert expected_names == set(exports.keys())


# ===========================================================================
# Test: T2_FLAT_INSTRUCTIONS constant
# ===========================================================================

class TestT2FlatInstructions:
    def test_is_string(self, ns):
        assert isinstance(ns["T2_FLAT_INSTRUCTIONS"], str)

    def test_contains_key_phrases(self, ns):
        instructions = ns["T2_FLAT_INSTRUCTIONS"]
        assert "INVESTIGATION" in instructions
        assert "SYNTHESIS" in instructions
        assert "T2 Flat Open-Ended Polya" in instructions
