"""Central catalog for prompt-visible RLM skills."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from google.adk.skills.models import Frontmatter, Skill

from rlm_adk.skills.polya_narrative_skill import (
    POLYA_NARRATIVE_SKILL,
    build_polya_skill_instruction_block,
)
from rlm_adk.skills.polya_understand import (
    POLYA_UNDERSTAND_SKILL,
    build_polya_understand_skill_instruction_block,
)
from rlm_adk.skills.polya_understand_t1_workflow import (
    POLYA_UNDERSTAND_T1_WORKFLOW_SKILL,
    build_polya_understand_t1_workflow_skill_instruction_block,
)
from rlm_adk.skills.polya_understand_t2_flat import (
    POLYA_UNDERSTAND_T2_FLAT_SKILL,
    build_polya_understand_t2_flat_skill_instruction_block,
)
from rlm_adk.skills.polya_understand_t3_adaptive import (
    POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL,
    build_polya_understand_t3_adaptive_skill_instruction_block,
)
from rlm_adk.skills.polya_understand_t4_debate import (
    POLYA_UNDERSTAND_T4_DEBATE_SKILL,
    build_polya_understand_t4_debate_skill_instruction_block,
)
from rlm_adk.skills.repomix_skill import (
    REPOMIX_SKILL,
    build_skill_instruction_block,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptSkillRegistration:
    """Prompt-visible skill definition plus instruction-block builder."""

    skill: Skill
    build_instruction_block: Callable[[], str]
    side_effect_modules: tuple[str, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        return self.skill.frontmatter.name

    @property
    def description(self) -> str:
        return self.skill.frontmatter.description


# Minimal Skill object for ping (no instruction block, only side-effect registration)
_PING_SKILL = Skill(
    frontmatter=Frontmatter(
        name="ping",
        description=(
            "Recursive ping skill for testing multi-layer dispatch. "
            "Source-expandable REPL exports only (no prompt instructions)."
        ),
    ),
    instructions="",
)


def _noop_instruction_block() -> str:
    """Ping skill has no prompt instruction block."""
    return ""


PROMPT_SKILL_REGISTRY: dict[str, PromptSkillRegistration] = {
    REPOMIX_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=REPOMIX_SKILL,
        build_instruction_block=build_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.repl_skills.repomix",),
    ),
    POLYA_UNDERSTAND_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_UNDERSTAND_SKILL,
        build_instruction_block=build_polya_understand_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.polya_understand",),
    ),
    POLYA_NARRATIVE_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_NARRATIVE_SKILL,
        build_instruction_block=build_polya_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.polya_narrative_skill",),
    ),
    POLYA_UNDERSTAND_T1_WORKFLOW_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_UNDERSTAND_T1_WORKFLOW_SKILL,
        build_instruction_block=build_polya_understand_t1_workflow_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.polya_understand_t1_workflow",),
    ),
    POLYA_UNDERSTAND_T2_FLAT_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_UNDERSTAND_T2_FLAT_SKILL,
        build_instruction_block=build_polya_understand_t2_flat_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.polya_understand_t2_flat",),
    ),
    POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL,
        build_instruction_block=build_polya_understand_t3_adaptive_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.polya_understand_t3_adaptive",),
    ),
    POLYA_UNDERSTAND_T4_DEBATE_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_UNDERSTAND_T4_DEBATE_SKILL,
        build_instruction_block=build_polya_understand_t4_debate_skill_instruction_block,
        side_effect_modules=("rlm_adk.skills.polya_understand_t4_debate",),
    ),
    _PING_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=_PING_SKILL,
        build_instruction_block=_noop_instruction_block,
        side_effect_modules=("rlm_adk.skills.repl_skills.ping",),
    ),
}

DEFAULT_ENABLED_SKILL_NAMES: tuple[str, ...] = tuple(PROMPT_SKILL_REGISTRY.keys())


def collect_skill_objects(enabled_skills: Iterable[str] | None) -> list[Skill]:
    """Collect ADK Skill objects for enabled skills that have instructions.

    Skills whose ``build_instruction_block()`` returns ``""`` (e.g. ping)
    are filtered out — they have no L2 instructions for ``load_skill`` to return.
    """
    names = normalize_enabled_skill_names(enabled_skills)
    return [
        PROMPT_SKILL_REGISTRY[name].skill
        for name in names
        if PROMPT_SKILL_REGISTRY[name].build_instruction_block() != ""
    ]


def normalize_enabled_skill_names(enabled_skills: Iterable[str] | None) -> tuple[str, ...]:
    """Return validated prompt-visible skill names in registry order."""
    if enabled_skills is None:
        return DEFAULT_ENABLED_SKILL_NAMES

    requested = {name for name in enabled_skills}
    unknown = sorted(requested - PROMPT_SKILL_REGISTRY.keys())
    if unknown:
        raise ValueError(f"Unknown skills requested: {', '.join(unknown)}")

    return tuple(name for name in DEFAULT_ENABLED_SKILL_NAMES if name in requested)


def build_enabled_skill_instruction_blocks(
    enabled_skills: Iterable[str] | None,
) -> list[str]:
    """Build prompt blocks for the selected prompt-visible skills."""
    names = normalize_enabled_skill_names(enabled_skills)
    return [PROMPT_SKILL_REGISTRY[name].build_instruction_block() for name in names]


def selected_skill_summaries(
    enabled_skills: Iterable[str] | None,
) -> list[tuple[str, str]]:
    """Return `(name, description)` tuples for selected prompt-visible skills."""
    return [
        (
            PROMPT_SKILL_REGISTRY[name].name,
            PROMPT_SKILL_REGISTRY[name].description,
        )
        for name in normalize_enabled_skill_names(enabled_skills)
    ]


def activate_side_effect_modules(
    enabled_skills: Iterable[str] | None,
) -> list[str]:
    """Import side-effect modules for enabled skills.

    Each module in ``side_effect_modules`` is imported to trigger
    ``register_skill_export()`` side effects for source-expandable skills.
    Returns the list of imported module paths for logging.
    """
    imported: list[str] = []
    for name in normalize_enabled_skill_names(enabled_skills):
        reg = PROMPT_SKILL_REGISTRY[name]
        for mod_path in reg.side_effect_modules:
            importlib.import_module(mod_path)
            imported.append(mod_path)
    if imported:
        logger.debug("Activated side-effect modules: %s", imported)
    return imported
