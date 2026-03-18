"""Tests for the T4 adversarial debate polya_understand skill.

Covers:
  1. Skill registration and catalog integration
  2. Result class construction and repr
  3. Context helpers (stringify_context, build_context_string, build_context_manifest)
  4. Extraction helpers (extract_section, extract_retrieval_order, extract_confidence_map)
  5. Prompt builders (optimist, critic, judge -- judge has NO context arg)
  6. Response parsers (parse_optimist_response, parse_critic_response, parse_judge_response)
  7. Skill registry expansion and dependency resolution
"""

from __future__ import annotations

import pytest

import rlm_adk.skills.polya_understand_t4_debate as _skill_mod  # noqa: F401

pytestmark = pytest.mark.provider_fake_contract
from rlm_adk.repl.skill_registry import _registry

_MODULE = "rlm_repl_skills.polya_understand_t4_debate"

# Collect all _SRC variables from the module for exec-based testing
_ALL_SRC_NAMES = [
    "_T4_OPTIMIST_INSTRUCTIONS_SRC",
    "_T4_CRITIC_INSTRUCTIONS_SRC",
    "_T4_JUDGE_INSTRUCTIONS_SRC",
    "_T4_OPTIMIST_CASE_SRC",
    "_T4_CRITIC_CASE_SRC",
    "_T4_VERDICT_SRC",
    "_T4_DEBATE_RESULT_SRC",
    "_STRINGIFY_CONTEXT_SRC",
    "_BUILD_CONTEXT_STRING_SRC",
    "_BUILD_CONTEXT_MANIFEST_SRC",
    "_EXTRACT_SECTION_SRC",
    "_EXTRACT_RETRIEVAL_ORDER_SRC",
    "_EXTRACT_CONFIDENCE_MAP_SRC",
    "_BUILD_OPTIMIST_PROMPT_SRC",
    "_BUILD_CRITIC_PROMPT_SRC",
    "_BUILD_JUDGE_PROMPT_SRC",
    "_PARSE_OPTIMIST_RESPONSE_SRC",
    "_PARSE_CRITIC_RESPONSE_SRC",
    "_PARSE_JUDGE_RESPONSE_SRC",
    "_RUN_POLYA_UNDERSTAND_T4_DEBATE_SRC",
]

_ALL_SRCS = [getattr(_skill_mod, name) for name in _ALL_SRC_NAMES]


def _exec_src(*sources: str) -> dict:
    """Execute source strings into a shared namespace and return it."""
    ns: dict = {}
    for src in sources:
        exec(src, ns)  # noqa: S102
    return ns


# ===========================================================================
# 1. Skill registration
# ===========================================================================


class TestSkillRegistration:
    """Verify module registration, export count, kinds, and catalog entry."""

    def test_module_registered(self):
        exports = _registry._exports.get(_MODULE)
        assert exports is not None, f"Module {_MODULE} not registered"

    def test_export_count(self):
        exports = _registry._exports[_MODULE]
        assert len(exports) == 20, f"Expected 20 exports, got {len(exports)}: {sorted(exports.keys())}"

    def test_constant_kinds(self):
        exports = _registry._exports[_MODULE]
        constants = [
            "T4_OPTIMIST_INSTRUCTIONS",
            "T4_CRITIC_INSTRUCTIONS",
            "T4_JUDGE_INSTRUCTIONS",
        ]
        for name in constants:
            assert name in exports, f"Missing constant export: {name}"
            assert exports[name].kind == "const", f"{name} should be kind='const'"

    def test_class_kinds(self):
        exports = _registry._exports[_MODULE]
        classes = ["T4OptimistCase", "T4CriticCase", "T4Verdict", "T4DebateResult"]
        for name in classes:
            assert name in exports, f"Missing class export: {name}"
            assert exports[name].kind == "class", f"{name} should be kind='class'"

    def test_function_kinds(self):
        exports = _registry._exports[_MODULE]
        functions = [
            "stringify_context",
            "build_context_string",
            "build_context_manifest",
            "extract_section",
            "extract_retrieval_order",
            "extract_confidence_map",
            "build_optimist_prompt",
            "build_critic_prompt",
            "build_judge_prompt",
            "parse_optimist_response",
            "parse_critic_response",
            "parse_judge_response",
            "run_polya_understand_t4_debate",
        ]
        for name in functions:
            assert name in exports, f"Missing function export: {name}"
            assert exports[name].kind == "function", f"{name} should be kind='function'"

    def test_catalog_entry(self):
        from rlm_adk.skills.catalog import PROMPT_SKILL_REGISTRY

        assert "polya-understand-t4-debate" in PROMPT_SKILL_REGISTRY

    def test_init_exports(self):
        from rlm_adk.skills import POLYA_UNDERSTAND_T4_DEBATE_SKILL

        assert POLYA_UNDERSTAND_T4_DEBATE_SKILL.frontmatter.name == "polya-understand-t4-debate"


# ===========================================================================
# 2. Result classes
# ===========================================================================


class TestResultClasses:
    """Verify construction and repr of result dataclasses."""

    def test_optimist_case(self):
        ns = _exec_src(*_ALL_SRCS)
        case = ns["T4OptimistCase"](
            assets="file1.py, file2.py",
            links="file1 -> file2",
            coverage_map="auth: covered",
            readiness_case="ready to go",
        )
        assert case.assets == "file1.py, file2.py"
        assert case.links == "file1 -> file2"
        assert "assets_len=" in repr(case)

    def test_optimist_case_defaults(self):
        ns = _exec_src(*_ALL_SRCS)
        case = ns["T4OptimistCase"]()
        assert case.assets == ""
        assert case.raw == ""

    def test_critic_case(self):
        ns = _exec_src(*_ALL_SRCS)
        case = ns["T4CriticCase"](
            gaps="missing auth docs",
            risks="security breach",
            ambiguities="unclear API contract",
            blockers="no credentials",
            retrieval_needs="auth_spec.md",
        )
        assert case.gaps == "missing auth docs"
        assert case.blockers == "no credentials"
        assert "gaps_len=" in repr(case)

    def test_verdict_proceed(self):
        ns = _exec_src(*_ALL_SRCS)
        v = ns["T4Verdict"]("PROCEED")
        assert v.value == "PROCEED"
        assert str(v) == "PROCEED"
        assert v == "PROCEED"

    def test_verdict_halt(self):
        ns = _exec_src(*_ALL_SRCS)
        v = ns["T4Verdict"]("halt")
        assert v.value == "HALT"
        assert v == "HALT"

    def test_verdict_conditional(self):
        ns = _exec_src(*_ALL_SRCS)
        v = ns["T4Verdict"]("Conditional")
        assert v.value == "CONDITIONAL"

    def test_verdict_unknown(self):
        ns = _exec_src(*_ALL_SRCS)
        v = ns["T4Verdict"]("something_else")
        assert v.value == "UNKNOWN"

    def test_verdict_none(self):
        ns = _exec_src(*_ALL_SRCS)
        v = ns["T4Verdict"](None)
        assert v.value == "UNKNOWN"

    def test_verdict_equality(self):
        ns = _exec_src(*_ALL_SRCS)
        v1 = ns["T4Verdict"]("PROCEED")
        v2 = ns["T4Verdict"]("proceed")
        assert v1 == v2

    def test_debate_result(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["T4DebateResult"](
            verdict=ns["T4Verdict"]("PROCEED"),
            understanding="all good",
            retrieval_order=["auth_spec.md"],
            confidence_map={"auth": "HIGH"},
            adjudication="optimist wins",
            optimist_case=ns["T4OptimistCase"](),
            critic_case=ns["T4CriticCase"](),
        )
        assert str(result.verdict) == "PROCEED"
        assert result.retrieval_order == ["auth_spec.md"]
        assert result.confidence_map == {"auth": "HIGH"}
        assert "verdict='PROCEED'" in repr(result)
        assert "retrievals=1" in repr(result)


# ===========================================================================
# 3. Context helpers
# ===========================================================================


class TestContextHelpers:
    """Test stringify_context, build_context_string, build_context_manifest."""

    def test_stringify_context_string(self):
        ns = _exec_src(*_ALL_SRCS)
        assert ns["stringify_context"]("hello") == "hello"

    def test_stringify_context_none(self):
        ns = _exec_src(*_ALL_SRCS)
        assert ns["stringify_context"](None) == ""

    def test_stringify_context_dict(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["stringify_context"]({"b": "val_b", "a": "val_a"})
        assert "[[a]]" in result
        assert "[[b]]" in result
        # Keys should be sorted
        a_pos = result.index("[[a]]")
        b_pos = result.index("[[b]]")
        assert a_pos < b_pos

    def test_stringify_context_list(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["stringify_context"](["x", "y"])
        assert "[[item_1]]" in result
        assert "[[item_2]]" in result

    def test_build_context_string(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["build_context_string"]("raw text here")
        assert result == "raw text here"

    def test_build_context_string_dict(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["build_context_string"]({"file.py": "code"})
        assert "[[file.py]]" in result
        assert "code" in result

    def test_build_context_manifest_dict(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["build_context_manifest"]({"src.py": "x" * 100, "readme.md": "y" * 50})
        assert "PROJECT CONTEXT MANIFEST" in result
        assert "2 items" in result
        assert "readme.md" in result
        assert "src.py" in result
        assert "100 chars" in result

    def test_build_context_manifest_list(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["build_context_manifest"](["chunk1", "chunk2", "chunk3"])
        assert "3 items" in result
        assert "packet_1" in result

    def test_build_context_manifest_string(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["build_context_manifest"]("some raw text")
        assert "1 items" in result
        assert "raw_context" in result


# ===========================================================================
# 4. Extraction helpers
# ===========================================================================


class TestExtractionHelpers:
    """Test extract_section, extract_retrieval_order, extract_confidence_map."""

    def test_extract_section_inline(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "VERDICT: PROCEED\nUNDERSTANDING: looks good"
        assert ns["extract_section"](text, "VERDICT") == "PROCEED"
        assert ns["extract_section"](text, "UNDERSTANDING") == "looks good"

    def test_extract_section_multiline(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "ASSETS:\n- file1.py\n- file2.py\nLINKS: none"
        result = ns["extract_section"](text, "ASSETS")
        assert "file1.py" in result
        assert "file2.py" in result

    def test_extract_section_missing(self):
        ns = _exec_src(*_ALL_SRCS)
        assert ns["extract_section"]("no headings here", "VERDICT") == ""

    def test_extract_section_none_input(self):
        ns = _exec_src(*_ALL_SRCS)
        assert ns["extract_section"](None, "VERDICT") == ""

    def test_extract_retrieval_order_numbered(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "RETRIEVAL_ORDER:\n1. auth_spec.md\n2. api_docs.md\nCONFIDENCE_MAP: x=HIGH"
        result = ns["extract_retrieval_order"](text)
        assert result == ["auth_spec.md", "api_docs.md"]

    def test_extract_retrieval_order_none(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "RETRIEVAL_ORDER: NONE"
        result = ns["extract_retrieval_order"](text)
        assert result == []

    def test_extract_retrieval_order_empty(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "no retrieval order here"
        result = ns["extract_retrieval_order"](text)
        assert result == []

    def test_extract_retrieval_order_with_pipe(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "RETRIEVAL_ORDER:\n1. auth_spec.md | category=DOCUMENT | source=internal"
        result = ns["extract_retrieval_order"](text)
        assert result == ["auth_spec.md"]

    def test_extract_confidence_map_inline(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "CONFIDENCE_MAP: auth=HIGH, testing=MEDIUM, docs=LOW"
        result = ns["extract_confidence_map"](text)
        assert result == {"auth": "HIGH", "testing": "MEDIUM", "docs": "LOW"}

    def test_extract_confidence_map_multiline(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "CONFIDENCE_MAP:\n- auth=HIGH\n- testing=LOW\nADJUDICATION: reasoning here"
        result = ns["extract_confidence_map"](text)
        assert result["auth"] == "HIGH"
        assert result["testing"] == "LOW"

    def test_extract_confidence_map_empty(self):
        ns = _exec_src(*_ALL_SRCS)
        result = ns["extract_confidence_map"]("no confidence map here")
        assert result == {}

    def test_extract_confidence_map_numbered(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "CONFIDENCE_MAP:\n1. auth=HIGH\n2. api=MEDIUM"
        result = ns["extract_confidence_map"](text)
        assert result == {"auth": "HIGH", "api": "MEDIUM"}


# ===========================================================================
# 5. Prompt builders
# ===========================================================================


class TestPromptBuilders:
    """Test prompt builder functions, especially judge context isolation."""

    def test_optimist_prompt_contains_objective_and_context(self):
        ns = _exec_src(*_ALL_SRCS)
        prompt = ns["build_optimist_prompt"]("refactor auth", "here is the code")
        assert "refactor auth" in prompt
        assert "here is the code" in prompt
        assert "OPTIMIST" in ns["T4_OPTIMIST_INSTRUCTIONS"]

    def test_critic_prompt_contains_objective_and_context(self):
        ns = _exec_src(*_ALL_SRCS)
        prompt = ns["build_critic_prompt"]("refactor auth", "here is the code")
        assert "refactor auth" in prompt
        assert "here is the code" in prompt
        assert "CRITIC" in ns["T4_CRITIC_INSTRUCTIONS"]

    def test_judge_prompt_has_no_context_parameter(self):
        """Critical test: build_judge_prompt takes exactly 3 args, no context."""
        ns = _exec_src(*_ALL_SRCS)
        import inspect

        sig = inspect.signature(ns["build_judge_prompt"])
        params = list(sig.parameters.keys())
        assert params == ["objective", "optimist_response", "critic_response"], (
            f"build_judge_prompt should take exactly 3 args, got: {params}"
        )

    def test_judge_prompt_contains_only_advocate_outputs(self):
        ns = _exec_src(*_ALL_SRCS)
        prompt = ns["build_judge_prompt"](
            "refactor auth",
            "optimist says everything is fine",
            "critic says there are gaps",
        )
        assert "refactor auth" in prompt
        assert "optimist says everything is fine" in prompt
        assert "critic says there are gaps" in prompt
        # The judge prompt should NOT contain raw project context
        assert "PROJECT_CONTEXT" not in prompt

    def test_judge_prompt_contains_judge_instructions(self):
        ns = _exec_src(*_ALL_SRCS)
        prompt = ns["build_judge_prompt"]("obj", "opt", "crit")
        assert "JUDGE" in prompt


# ===========================================================================
# 6. Response parsers
# ===========================================================================


class TestResponseParsers:
    """Test parse_optimist_response, parse_critic_response, parse_judge_response."""

    def test_parse_optimist_response(self):
        ns = _exec_src(*_ALL_SRCS)
        text = (
            "ASSETS: file1.py, file2.py\n"
            "LINKS: file1 imports file2\n"
            "COVERAGE_MAP: auth module fully covered\n"
            "READINESS_CASE: all tests pass"
        )
        case = ns["parse_optimist_response"](text)
        assert isinstance(case, ns["T4OptimistCase"].__class__) or hasattr(case, "assets")
        assert "file1.py" in case.assets
        assert "file1 imports file2" in case.links
        assert "auth module" in case.coverage_map
        assert "all tests pass" in case.readiness_case
        assert case.raw == text

    def test_parse_critic_response(self):
        ns = _exec_src(*_ALL_SRCS)
        text = (
            "GAPS: missing auth documentation\n"
            "RISKS: security vulnerability\n"
            "AMBIGUITIES: unclear error handling\n"
            "BLOCKERS: no API keys\n"
            "RETRIEVAL_NEEDS: auth_spec.md"
        )
        case = ns["parse_critic_response"](text)
        assert "missing auth" in case.gaps
        assert "security" in case.risks
        assert "unclear" in case.ambiguities
        assert "no API keys" in case.blockers
        assert "auth_spec" in case.retrieval_needs

    def test_parse_judge_response_proceed(self):
        ns = _exec_src(*_ALL_SRCS)
        text = (
            "VERDICT: PROCEED\n"
            "UNDERSTANDING: The project is well-documented.\n"
            "RETRIEVAL_ORDER: NONE\n"
            "CONFIDENCE_MAP: auth=HIGH, testing=MEDIUM\n"
            "ADJUDICATION: Optimist made a stronger case."
        )
        verdict, understanding, retrieval_order, confidence_map, adjudication = (
            ns["parse_judge_response"](text)
        )
        assert verdict.value == "PROCEED"
        assert "well-documented" in understanding
        assert retrieval_order == []
        assert confidence_map["auth"] == "HIGH"
        assert "Optimist" in adjudication

    def test_parse_judge_response_halt(self):
        ns = _exec_src(*_ALL_SRCS)
        text = (
            "VERDICT: HALT\n"
            "UNDERSTANDING: Too many gaps.\n"
            "RETRIEVAL_ORDER:\n"
            "1. auth_spec.md\n"
            "2. api_docs.md\n"
            "CONFIDENCE_MAP: auth=LOW\n"
            "ADJUDICATION: Critic identified blocking gaps."
        )
        verdict, understanding, retrieval_order, confidence_map, adjudication = (
            ns["parse_judge_response"](text)
        )
        assert verdict.value == "HALT"
        assert retrieval_order == ["auth_spec.md", "api_docs.md"]
        assert confidence_map["auth"] == "LOW"

    def test_parse_judge_response_conditional(self):
        ns = _exec_src(*_ALL_SRCS)
        text = (
            "VERDICT: CONDITIONAL\n"
            "UNDERSTANDING: Partial coverage.\n"
            "RETRIEVAL_ORDER:\n"
            "1. missing_doc.md\n"
            "CONFIDENCE_MAP: code=HIGH, docs=LOW\n"
            "ADJUDICATION: Can proceed with caveats."
        )
        verdict, _, retrieval_order, confidence_map, _ = (
            ns["parse_judge_response"](text)
        )
        assert verdict.value == "CONDITIONAL"
        assert retrieval_order == ["missing_doc.md"]
        assert confidence_map["code"] == "HIGH"
        assert confidence_map["docs"] == "LOW"

    def test_parse_judge_response_unknown_verdict(self):
        ns = _exec_src(*_ALL_SRCS)
        text = "VERDICT: MAYBE\nUNDERSTANDING: unclear"
        verdict, _, _, _, _ = ns["parse_judge_response"](text)
        assert verdict.value == "UNKNOWN"


# ===========================================================================
# 7. Skill registry expansion
# ===========================================================================


class TestSkillRegistryExpansion:
    """Test that synthetic imports expand correctly."""

    def test_expand_single_function(self):
        code = (
            "from rlm_repl_skills.polya_understand_t4_debate import build_context_string\n"
            "result = build_context_string('hello')\n"
        )
        expanded = _registry.expand(code)
        assert expanded.did_expand
        assert "stringify_context" in expanded.expanded_code  # transitive dep
        assert "build_context_string" in expanded.expanded_code

    def test_expand_main_entry_point(self):
        code = (
            "from rlm_repl_skills.polya_understand_t4_debate import run_polya_understand_t4_debate\n"
        )
        expanded = _registry.expand(code)
        assert expanded.did_expand
        # Should pull in all transitive dependencies
        assert "T4DebateResult" in expanded.expanded_code
        assert "T4Verdict" in expanded.expanded_code
        assert "stringify_context" in expanded.expanded_code
        assert "build_judge_prompt" in expanded.expanded_code
        assert "parse_judge_response" in expanded.expanded_code
        assert "extract_confidence_map" in expanded.expanded_code

    def test_expanded_symbols_count(self):
        code = (
            "from rlm_repl_skills.polya_understand_t4_debate import run_polya_understand_t4_debate\n"
        )
        expanded = _registry.expand(code)
        # run_polya_understand_t4_debate + all transitive deps
        # Should be a substantial number of symbols
        assert len(expanded.expanded_symbols) >= 15

    def test_topo_order_deps_before_dependents(self):
        code = (
            "from rlm_repl_skills.polya_understand_t4_debate import parse_judge_response\n"
        )
        expanded = _registry.expand(code)
        symbols = expanded.expanded_symbols
        # T4Verdict must come before parse_judge_response
        assert symbols.index("T4Verdict") < symbols.index("parse_judge_response")
        # extract_section must come before parse_judge_response
        assert symbols.index("extract_section") < symbols.index("parse_judge_response")
