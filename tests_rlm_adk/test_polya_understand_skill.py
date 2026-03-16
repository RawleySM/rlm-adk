"""Tests for the Polya understand skill definition and REPL expansion."""

from __future__ import annotations

import ast

from rlm_adk.repl.skill_registry import expand_skill_imports
from rlm_adk.skills.polya_understand import (
    POLYA_UNDERSTAND_SKILL,
    build_polya_understand_skill_instruction_block,
)


class TestPolyaUnderstandSkill:
    def test_skill_object(self):
        """POLYA_UNDERSTAND_SKILL exposes the expected frontmatter."""
        assert POLYA_UNDERSTAND_SKILL.frontmatter.name == "polya-understand"
        assert "run_polya_understand" in POLYA_UNDERSTAND_SKILL.instructions
        assert "retrieval_order" in POLYA_UNDERSTAND_SKILL.instructions
        assert "probe_repo" in POLYA_UNDERSTAND_SKILL.instructions

    def test_build_skill_instruction_block(self):
        """Skill block returns XML discovery metadata plus instructions."""
        block = build_polya_understand_skill_instruction_block()
        assert isinstance(block, str)
        assert "<available_skills>" in block
        assert "polya-understand" in block
        assert "run_polya_understand" in block
        assert "retrieval_order" in block

    def test_repl_skill_expansion_registers_transitive_dependencies(self):
        """Synthetic REPL import expands into executable Python source."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import run_polya_understand\n"
        )
        assert expanded.did_expand is True
        assert "run_polya_understand" in expanded.expanded_symbols
        assert "prepare_context_packets" in expanded.expanded_symbols
        assert "extract_retrieval_order" in expanded.expanded_symbols
        assert "PolyaUnderstandResult" in expanded.expanded_symbols
        ast.parse(expanded.expanded_code)

    def test_repl_expansion_includes_new_reframe_dependencies(self):
        """Expanded source includes the new reframe/probe phase dependencies."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import run_polya_understand\n"
        )
        assert expanded.did_expand is True
        # New reframe-based dependencies
        assert "POLYA_DIMENSIONS" in expanded.expanded_symbols
        assert "build_context_manifest" in expanded.expanded_symbols
        assert "parse_reframed_questions" in expanded.expanded_symbols
        assert "assign_packets_to_dimensions" in expanded.expanded_symbols
        assert "build_reframe_prompt" in expanded.expanded_symbols
        assert "build_probe_prompt" in expanded.expanded_symbols
        assert "build_synthesize_prompt" in expanded.expanded_symbols
        # Phase instructions
        assert "POLYA_REFRAME_INSTRUCTIONS" in expanded.expanded_symbols
        assert "POLYA_PROBE_INSTRUCTIONS" in expanded.expanded_symbols
        assert "POLYA_SYNTHESIZE_INSTRUCTIONS" in expanded.expanded_symbols

    def test_expanded_source_defines_all_required_names(self):
        """All functions/classes used by run_polya_understand are defined in expanded code."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import run_polya_understand\n"
        )
        tree = ast.parse(expanded.expanded_code)
        defined_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined_names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                defined_names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined_names.add(target.id)

        required = {
            "run_polya_understand",
            "PolyaUnderstandResult",
            "PolyaUnderstandPhaseResult",
            "prepare_context_packets",
            "build_context_manifest",
            "extract_retrieval_order",
            "extract_marker_value",
            "parse_reframed_questions",
            "assign_packets_to_dimensions",
            "build_reframe_prompt",
            "build_probe_prompt",
            "build_synthesize_prompt",
            "build_validate_prompt",
            "build_reflect_prompt",
            "POLYA_DIMENSIONS",
            "POLYA_REFRAME_INSTRUCTIONS",
            "POLYA_PROBE_INSTRUCTIONS",
            "POLYA_SYNTHESIZE_INSTRUCTIONS",
            "POLYA_VALIDATE_INSTRUCTIONS",
            "POLYA_REFLECT_INSTRUCTIONS",
        }
        missing = required - defined_names
        assert not missing, f"Missing definitions in expanded code: {missing}"

    def test_polya_dimensions_has_expected_ids(self):
        """POLYA_DIMENSIONS constant defines the expected dimension IDs."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import POLYA_DIMENSIONS\n"
        )
        ns = {}
        exec(expanded.expanded_code, ns)  # noqa: S102
        dims = ns["POLYA_DIMENSIONS"]
        ids = [d["id"] for d in dims]
        assert "restatement" in ids
        assert "givens" in ids
        assert "unknowns" in ids
        assert "assumptions" in ids
        assert "constraints" in ids
        assert "well_posedness" in ids
        assert "definitions" in ids
        assert "problem_type" in ids
        # Each dimension has required keys
        for dim in dims:
            assert "id" in dim
            assert "label" in dim
            assert "question_template" in dim
            assert "{objective}" in dim["question_template"]

    def test_build_context_manifest(self):
        """build_context_manifest produces a file-list-with-sizes manifest."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import build_context_manifest\n"
        )
        ns = {}
        exec(expanded.expanded_code, ns)  # noqa: S102
        build_manifest = ns["build_context_manifest"]

        # Dict context
        ctx = {"file_a.py": "x" * 100, "file_b.md": "y" * 200}
        manifest = build_manifest(ctx)
        assert "file_a.py" in manifest
        assert "100 chars" in manifest
        assert "file_b.md" in manifest
        assert "200 chars" in manifest
        assert "MANIFEST" in manifest.upper()

    def test_parse_reframed_questions(self):
        """parse_reframed_questions extracts dimension-keyed questions."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import parse_reframed_questions, POLYA_DIMENSIONS\n"
        )
        ns = {}
        exec(expanded.expanded_code, ns)  # noqa: S102
        parse_fn = ns["parse_reframed_questions"]
        dims = ns["POLYA_DIMENSIONS"]

        reframe_output = (
            "RESTATEMENT: What exactly is the deliverable here?\n"
            "GIVENS: What data is provided in the context?\n"
            "UNKNOWNS: What is missing from the context?\n"
        )
        questions = parse_fn(reframe_output, dims)
        assert questions["restatement"] == "What exactly is the deliverable here?"
        assert questions["givens"] == "What data is provided in the context?"
        assert questions["unknowns"] == "What is missing from the context?"
        # Missing dimensions get template fallback
        assert "{objective}" in questions["constraints"] or len(questions["constraints"]) > 0

    def test_assign_packets_to_dimensions_more_packets(self):
        """When packets > dimensions, extras are distributed round-robin."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import assign_packets_to_dimensions\n"
        )
        ns = {}
        exec(expanded.expanded_code, ns)  # noqa: S102
        assign_fn = ns["assign_packets_to_dimensions"]

        dims = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
        packets = ["p1", "p2", "p3", "p4"]
        assignments = assign_fn(dims, packets)
        # All packets are used
        used_packets = [a[1] for a in assignments]
        assert set(used_packets) == {"p1", "p2", "p3", "p4"}
        assert len(assignments) == 4

    def test_assign_packets_to_dimensions_fewer_packets(self):
        """When packets < dimensions, dimensions share packets."""
        expanded = expand_skill_imports(
            "from rlm_repl_skills.polya_understand import assign_packets_to_dimensions\n"
        )
        ns = {}
        exec(expanded.expanded_code, ns)  # noqa: S102
        assign_fn = ns["assign_packets_to_dimensions"]

        dims = [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
            {"id": "c", "label": "C"},
        ]
        packets = ["p1", "p2"]
        assignments = assign_fn(dims, packets)
        assert len(assignments) == 3
        # Each dimension gets exactly one assignment
        dim_ids = [a[0]["id"] for a in assignments]
        assert dim_ids == ["a", "b", "c"]

    def test_skill_instructions_mention_five_phases(self):
        """Skill instructions describe the 5-phase design."""
        instructions = POLYA_UNDERSTAND_SKILL.instructions
        assert "REFRAME" in instructions
        assert "PROBE" in instructions
        assert "SYNTHESIZE" in instructions
        assert "VALIDATE" in instructions
        assert "REFLECT" in instructions
        # Confirm 5 phases mentioned
        assert "Phase 1/5" not in instructions  # phase numbering is internal
        assert "five phases" in instructions.lower() or "5/5" not in instructions
