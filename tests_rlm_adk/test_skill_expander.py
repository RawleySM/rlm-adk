"""Unit tests for the skill registry and expansion system."""

from __future__ import annotations

import pytest

from rlm_adk.repl.skill_registry import (
    ExpandedSkillCode,
    ReplSkillExport,
    SkillRegistry,
    _registry,
    expand_skill_imports,
    register_skill_export,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the module-level registry before each test."""
    _registry.clear()
    yield
    _registry.clear()


def _register_test_exports(registry: SkillRegistry | None = None) -> None:
    """Register simple test exports for unit testing."""
    reg = registry or _registry

    reg.register(
        ReplSkillExport(
            module="rlm_repl_skills.demo",
            name="DEMO_CONST",
            source='DEMO_CONST = "hello"',
            requires=[],
            kind="const",
        )
    )
    reg.register(
        ReplSkillExport(
            module="rlm_repl_skills.demo",
            name="DemoClass",
            source="class DemoClass:\n    value = 42",
            requires=[],
            kind="class",
        )
    )
    reg.register(
        ReplSkillExport(
            module="rlm_repl_skills.demo",
            name="demo_helper",
            source="def demo_helper(x):\n    return DEMO_CONST + str(x)",
            requires=["DEMO_CONST"],
            kind="function",
        )
    )
    reg.register(
        ReplSkillExport(
            module="rlm_repl_skills.demo",
            name="demo_query",
            source="def demo_query(prompt):\n    return llm_query(prompt)",
            requires=["demo_helper", "DEMO_CONST"],
            kind="function",
        )
    )


class TestExpandKnownSymbol:
    def test_expand_known_symbol(self):
        _register_test_exports()
        code = "from rlm_repl_skills.demo import DEMO_CONST\nprint(DEMO_CONST)"
        result = expand_skill_imports(code)
        assert result.did_expand is True
        assert "DEMO_CONST" in result.expanded_symbols
        assert 'DEMO_CONST = "hello"' in result.expanded_code
        assert "print(DEMO_CONST)" in result.expanded_code


class TestExpandWithDependencies:
    def test_expand_with_dependencies(self):
        _register_test_exports()
        code = "from rlm_repl_skills.demo import demo_helper\nprint(demo_helper(1))"
        result = expand_skill_imports(code)
        assert result.did_expand is True
        assert "DEMO_CONST" in result.expanded_symbols
        assert "demo_helper" in result.expanded_symbols
        # DEMO_CONST must appear before demo_helper (topo order)
        const_pos = result.expanded_code.index('DEMO_CONST = "hello"')
        helper_pos = result.expanded_code.index("def demo_helper")
        assert const_pos < helper_pos

    def test_transitive_dependencies(self):
        _register_test_exports()
        code = 'from rlm_repl_skills.demo import demo_query\nresult = demo_query("hi")'
        result = expand_skill_imports(code)
        assert result.did_expand is True
        # Should include DEMO_CONST, demo_helper, demo_query
        assert "DEMO_CONST" in result.expanded_symbols
        assert "demo_helper" in result.expanded_symbols
        assert "demo_query" in result.expanded_symbols


class TestExpandDuplicateImport:
    def test_expand_duplicate_import(self):
        _register_test_exports()
        code = (
            "from rlm_repl_skills.demo import DEMO_CONST\n"
            "from rlm_repl_skills.demo import DEMO_CONST\n"
            "print(DEMO_CONST)"
        )
        result = expand_skill_imports(code)
        assert result.did_expand is True
        # Should only inline once
        count = result.expanded_code.count('DEMO_CONST = "hello"')
        assert count == 1


class TestExpandUnknownModuleFails:
    def test_expand_unknown_module_fails(self):
        _register_test_exports()
        code = "from rlm_repl_skills.nonexistent import something\nprint(something)"
        with pytest.raises(RuntimeError, match="Unknown synthetic module"):
            expand_skill_imports(code)


class TestExpandUnknownSymbolFails:
    def test_expand_unknown_symbol_fails(self):
        _register_test_exports()
        code = "from rlm_repl_skills.demo import nonexistent_symbol\nprint(nonexistent_symbol)"
        with pytest.raises(RuntimeError, match="Unknown symbol"):
            expand_skill_imports(code)


class TestExpandNameConflictFails:
    def test_expand_name_conflict_fails(self):
        _register_test_exports()
        code = (
            "from rlm_repl_skills.demo import DEMO_CONST\n"
            'DEMO_CONST = "my_own_value"\n'
            "print(DEMO_CONST)"
        )
        with pytest.raises(RuntimeError, match="Name conflict"):
            expand_skill_imports(code)


class TestNoSyntheticImportsUnchanged:
    def test_no_synthetic_imports_unchanged(self):
        _register_test_exports()
        code = 'import json\nprint(json.dumps({"a": 1}))'
        result = expand_skill_imports(code)
        assert result.did_expand is False
        assert result.expanded_code == code
        assert result.expanded_symbols == []
        assert result.expanded_modules == []


class TestPreservesNormalImports:
    def test_preserves_normal_imports(self):
        _register_test_exports()
        code = (
            "import json\n"
            "from rlm_repl_skills.demo import DEMO_CONST\n"
            "print(json.dumps(DEMO_CONST))"
        )
        result = expand_skill_imports(code)
        assert result.did_expand is True
        assert "import json" in result.expanded_code
        assert 'DEMO_CONST = "hello"' in result.expanded_code
        assert "print(json.dumps(DEMO_CONST))" in result.expanded_code


class TestExpansionMetadata:
    def test_expansion_metadata(self):
        _register_test_exports()
        code = "from rlm_repl_skills.demo import demo_helper\nprint(demo_helper(1))"
        result = expand_skill_imports(code)
        assert isinstance(result, ExpandedSkillCode)
        assert result.original_code == code
        assert result.did_expand is True
        assert "rlm_repl_skills.demo" in result.expanded_modules
        assert "demo_helper" in result.expanded_symbols
        assert "DEMO_CONST" in result.expanded_symbols


class TestExpandEmptyCode:
    def test_expand_empty_code(self):
        result = expand_skill_imports("")
        assert result.did_expand is False
        assert result.expanded_code == ""

    def test_expand_syntax_error_code(self):
        result = expand_skill_imports("def foo(:\n  pass")
        assert result.did_expand is False


class TestRegisterSkillExport:
    def test_module_level_register(self):
        register_skill_export(
            ReplSkillExport(
                module="rlm_repl_skills.test",
                name="test_fn",
                source="def test_fn(): pass",
            )
        )
        code = "from rlm_repl_skills.test import test_fn\ntest_fn()"
        result = expand_skill_imports(code)
        assert result.did_expand is True
        assert "def test_fn(): pass" in result.expanded_code
