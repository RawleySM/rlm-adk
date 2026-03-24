# DISABLED: skill system reset — all skill registration/catalog tests suspended
#
# This file tested catalog-driven runtime activation: activate_side_effect_modules
# and auto-import. All tests depend on the obsolete catalog skill system
# (catalog.py moved to rlm_adk/skills/obsolete/).

# from __future__ import annotations
#
# import pytest
#
# from rlm_adk.skills.catalog import activate_side_effect_modules
#
# pytestmark = pytest.mark.provider_fake_contract
#
#
# class TestActivateSideEffectModules:
#     """activate_side_effect_modules imports the right modules per enabled skill set."""
#
#     def test_all_skills_imports_without_error(self):
#         imported = activate_side_effect_modules(None)
#         assert isinstance(imported, list)
#         assert "rlm_adk.skills.polya_understand" in imported
#         assert "rlm_adk.skills.polya_narrative_skill" in imported
#         assert "rlm_adk.skills.repl_skills.ping" in imported
#         assert "rlm_adk.skills.repl_skills.repomix" in imported
#
#     def test_repomix_only_imports_repomix_module(self):
#         imported = activate_side_effect_modules(("repomix-repl-helpers",))
#         assert imported == ["rlm_adk.skills.repl_skills.repomix"]
#         assert "rlm_adk.skills.polya_understand" not in imported
#
#     def test_polya_understand_only_imports_its_module(self):
#         imported = activate_side_effect_modules(("polya-understand",))
#         assert imported == ["rlm_adk.skills.polya_understand"]
#
#     def test_ping_only_imports_ping_module(self):
#         imported = activate_side_effect_modules(("ping",))
#         assert imported == ["rlm_adk.skills.repl_skills.ping"]
#
#     def test_restricted_set_excludes_polya(self):
#         imported = activate_side_effect_modules(("repomix-repl-helpers", "ping"))
#         assert "rlm_adk.skills.polya_understand" not in imported
#         assert "rlm_adk.skills.polya_narrative_skill" not in imported
#
#     def test_side_effect_registers_exports(self):
#         from rlm_adk.repl.skill_registry import _registry
#         activate_side_effect_modules(("ping",))
#         assert "rlm_repl_skills.ping" in _registry._exports
#         assert "run_recursive_ping" in _registry._exports["rlm_repl_skills.ping"]
#
#     def test_repomix_side_effect_registers_exports(self):
#         from rlm_adk.repl.skill_registry import _registry
#         activate_side_effect_modules(("repomix-repl-helpers",))
#         assert "rlm_repl_skills.repomix" in _registry._exports
#         assert "probe_repo" in _registry._exports["rlm_repl_skills.repomix"]
#         assert "pack_repo" in _registry._exports["rlm_repl_skills.repomix"]
#         assert "shard_repo" in _registry._exports["rlm_repl_skills.repomix"]
#
#     def test_unknown_skill_raises(self):
#         with pytest.raises(ValueError, match="Unknown skills"):
#             activate_side_effect_modules(("nonexistent-skill",))
#
#
# class TestAutoImportLines:
#     """build_auto_import_lines() returns synthetic imports for registered modules."""
#
#     def test_auto_import_contains_repomix(self):
#         from rlm_adk.repl.skill_registry import build_auto_import_lines
#         activate_side_effect_modules(("repomix-repl-helpers",))
#         lines = build_auto_import_lines()
#         assert "from rlm_repl_skills.repomix import" in lines
#         assert "probe_repo" in lines
#
#     def test_auto_import_contains_all_skills(self):
#         from rlm_adk.repl.skill_registry import build_auto_import_lines
#         activate_side_effect_modules(None)
#         lines = build_auto_import_lines()
#         assert "rlm_repl_skills.repomix" in lines
#         assert "rlm_repl_skills.ping" in lines
#         assert "probe_repo" in lines
#         assert "run_recursive_ping" in lines
