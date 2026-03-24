"""RLMSkillToolset — hybrid prompt-injection + tool-use skill discovery.

Implements the ADK SkillToolset pattern locally (upstream doesn't ship one yet):
- L1 discovery: ``process_llm_request`` appends lightweight XML to system_instruction
- L2 on-demand: ``load_skill`` tool call returns full markdown instructions
- State tracking: writes skill activation keys via ``tool_context.state`` (AR-CRIT-001)

Lineage is automatic: sqlite_tracing's ``before_tool_callback`` captures depth,
fanout_idx, branch, invocation_id for all tool calls including ``load_skill``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from google.adk.skills.prompt import format_skills_as_xml
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.skills.catalog import collect_skill_objects

logger = logging.getLogger(__name__)


class RLMSkillToolset(BaseTool):
    """Hybrid skill discovery tool.

    On each LLM request:
      1. Injects L1 XML (``<available_skills>`` block) into ``system_instruction``
      2. Registers a ``load_skill`` function declaration

    When the model calls ``load_skill(skill_name=...)``:
      1. Returns ``{skill_name, instructions, frontmatter}``
      2. Writes ``skill_last_loaded``, ``skill_load_count``, ``skill_loaded_names``
         to ``tool_context.state`` (AR-CRIT-001 compliant)
    """

    def __init__(self, *, enabled_skills: Iterable[str] | None = None):
        skills = collect_skill_objects(enabled_skills)
        self._skills = {s.name: s for s in skills}
        super().__init__(
            name="load_skill",
            description=(
                "Load the full instructions for a specific skill. "
                "Call this when you want to use a skill listed in available_skills."
            ),
        )

    def _get_declaration(self) -> types.FunctionDeclaration | None:
        """OpenAPI spec for the load_skill tool."""
        return types.FunctionDeclaration(
            name="load_skill",
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "skill_name": types.Schema(
                        type=types.Type.STRING,
                        description="The name of the skill to load.",
                    ),
                },
                required=["skill_name"],
            ),
        )

    async def process_llm_request(
        self,
        *,
        tool_context: ToolContext,
        llm_request: Any,
    ) -> None:
        """Inject L1 XML into system_instruction, then register the tool."""
        # L1: lightweight frontmatter XML for skill discovery
        frontmatters = [s.frontmatter for s in self._skills.values()]
        if frontmatters:
            xml = format_skills_as_xml(frontmatters)
            llm_request.append_instructions([xml])

        # Register load_skill function declaration via BaseTool default
        await super().process_llm_request(tool_context=tool_context, llm_request=llm_request)

    async def run_async(
        self,
        *,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        """Load L2 instructions for the requested skill."""
        skill_name = args.get("skill_name", "")
        skill = self._skills.get(skill_name)

        if skill is None:
            available = sorted(self._skills.keys())
            return {
                "error": f"Unknown skill: {skill_name!r}",
                "available_skills": available,
            }

        # AR-CRIT-001: all state writes via tool_context.state
        tool_context.state["skill_last_loaded"] = skill_name
        current_count = tool_context.state.get("skill_load_count", 0) or 0
        tool_context.state["skill_load_count"] = current_count + 1
        current_names = tool_context.state.get("skill_loaded_names") or []
        tool_context.state["skill_loaded_names"] = list(current_names) + [skill_name]

        logger.info("Loaded skill %r (%d chars)", skill_name, len(skill.instructions))

        return {
            "skill_name": skill_name,
            "instructions": skill.instructions,
            "frontmatter": skill.frontmatter.model_dump(),
        }
