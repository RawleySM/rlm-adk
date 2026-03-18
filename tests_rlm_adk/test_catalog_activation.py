"""Tests for catalog-driven runtime activation: collect_repl_globals and activate_side_effect_modules."""

from __future__ import annotations

import pytest

from rlm_adk.skills.catalog import (
    activate_side_effect_modules,
    collect_repl_globals,
)

pytestmark = pytest.mark.provider_fake_contract


class TestCollectReplGlobals:
    """collect_repl_globals returns the right globals per enabled skill set."""

    def test_all_skills_returns_repomix_helpers(self):
        """With all skills enabled (None), repomix globals are present."""
        result = collect_repl_globals(None)
        assert "probe_repo" in result
        assert "pack_repo" in result
        assert "shard_repo" in result
        # All three must be callable
        assert callable(result["probe_repo"])
        assert callable(result["pack_repo"])
        assert callable(result["shard_repo"])

    def test_polya_only_returns_empty(self):
        """polya-understand has no repl_globals_factory → empty dict."""
        result = collect_repl_globals(("polya-understand",))
        assert "probe_repo" not in result
        assert "pack_repo" not in result
        assert "shard_repo" not in result
        assert result == {}

    def test_repomix_only_returns_repomix_helpers(self):
        """repomix-repl-helpers returns exactly 3 globals."""
        result = collect_repl_globals(("repomix-repl-helpers",))
        assert set(result.keys()) == {"probe_repo", "pack_repo", "shard_repo"}

    def test_ping_only_returns_empty(self):
        """ping has no repl_globals_factory → empty dict."""
        result = collect_repl_globals(("ping",))
        assert result == {}

    def test_disabled_skill_does_not_leak_globals(self):
        """When repomix is excluded, its globals must not appear."""
        result = collect_repl_globals(("polya-narrative", "polya-understand", "ping"))
        assert "probe_repo" not in result


class TestActivateSideEffectModules:
    """activate_side_effect_modules imports the right modules per enabled skill set."""

    def test_all_skills_imports_without_error(self):
        """With all skills enabled (None), all side-effect modules import."""
        imported = activate_side_effect_modules(None)
        assert isinstance(imported, list)
        assert "rlm_adk.skills.polya_understand" in imported
        assert "rlm_adk.skills.polya_narrative_skill" in imported
        assert "rlm_adk.skills.repl_skills.ping" in imported

    def test_repomix_only_does_not_import_polya(self):
        """repomix-repl-helpers has no side_effect_modules → empty list."""
        imported = activate_side_effect_modules(("repomix-repl-helpers",))
        assert imported == []

    def test_polya_understand_only_imports_its_module(self):
        imported = activate_side_effect_modules(("polya-understand",))
        assert imported == ["rlm_adk.skills.polya_understand"]

    def test_ping_only_imports_ping_module(self):
        imported = activate_side_effect_modules(("ping",))
        assert imported == ["rlm_adk.skills.repl_skills.ping"]

    def test_restricted_set_excludes_polya(self):
        """repomix + ping must not trigger polya side-effect imports."""
        imported = activate_side_effect_modules(("repomix-repl-helpers", "ping"))
        assert "rlm_adk.skills.polya_understand" not in imported
        assert "rlm_adk.skills.polya_narrative_skill" not in imported

    def test_side_effect_registers_exports(self):
        """After activation, SkillRegistry should have the expected modules."""
        from rlm_adk.repl.skill_registry import _registry

        activate_side_effect_modules(("ping",))
        assert "rlm_repl_skills.ping" in _registry._exports
        assert "run_recursive_ping" in _registry._exports["rlm_repl_skills.ping"]

    def test_unknown_skill_raises(self):
        with pytest.raises(ValueError, match="Unknown skills"):
            activate_side_effect_modules(("nonexistent-skill",))
