"""Central catalog for prompt-visible RLM skills."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from google.adk.skills.models import Skill

from rlm_adk.skills.polya_narrative_skill import (
    POLYA_NARRATIVE_SKILL,
    build_polya_skill_instruction_block,
)
from rlm_adk.skills.polya_understand import (
    POLYA_UNDERSTAND_SKILL,
    build_polya_understand_skill_instruction_block,
)
from rlm_adk.skills.repomix_skill import (
    REPOMIX_SKILL,
    build_skill_instruction_block,
)


@dataclass(frozen=True)
class PromptSkillRegistration:
    """Prompt-visible skill definition plus instruction-block builder."""

    skill: Skill
    build_instruction_block: Callable[[], str]

    @property
    def name(self) -> str:
        return self.skill.frontmatter.name

    @property
    def description(self) -> str:
        return self.skill.frontmatter.description


PROMPT_SKILL_REGISTRY: dict[str, PromptSkillRegistration] = {
    REPOMIX_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=REPOMIX_SKILL,
        build_instruction_block=build_skill_instruction_block,
    ),
    POLYA_UNDERSTAND_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_UNDERSTAND_SKILL,
        build_instruction_block=build_polya_understand_skill_instruction_block,
    ),
    POLYA_NARRATIVE_SKILL.frontmatter.name: PromptSkillRegistration(
        skill=POLYA_NARRATIVE_SKILL,
        build_instruction_block=build_polya_skill_instruction_block,
    ),
}

DEFAULT_ENABLED_SKILL_NAMES: tuple[str, ...] = tuple(PROMPT_SKILL_REGISTRY.keys())


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
    return [
        PROMPT_SKILL_REGISTRY[name].build_instruction_block()
        for name in names
    ]


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
