"""ADK Skill definition + source-expandable REPL exports: Polya narrative loop.

Defines ``POLYA_NARRATIVE_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_polya_skill_instruction_block()`` which returns the XML
discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_narrative import run_polya_narrative`` expands
into inline source before the AST rewriter runs.

The Polya loop orchestrates four phases per cycle:
  1. UNDERSTAND: Assess the narrative, identify gaps and strengths
  2. PLAN: Create work packets for enrichment (parallel-dispatchable)
  3. IMPLEMENT: Execute work packets via llm_query_batched (fanout)
  4. REFLECT: Evaluate quality, recommend CONTINUE or COMPLETE
"""

from __future__ import annotations

import textwrap

from google.adk.skills.models import Frontmatter, Skill
from google.adk.skills.prompt import format_skills_as_xml

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ===========================================================================
# ADK Skill definition (prompt discovery)
# ===========================================================================

POLYA_NARRATIVE_SKILL = Skill(
    frontmatter=Frontmatter(
        name="polya-narrative",
        description=(
            "Iterative George Polya problem-solving loop "
            "(Understand -> Plan -> Implement -> Reflect) for narrative "
            "refinement via recursive child dispatch. Each phase dispatches "
            "child agents through llm_query() and llm_query_batched() to "
            "develop rich, multi-layered content through refinement cycles."
        ),
    ),
    instructions=textwrap.dedent("""\
## polya-narrative — Iterative Refinement via Recursive Dispatch

A source-expandable REPL skill that orchestrates a Polya problem-solving
loop: **Understand -> Plan -> Implement -> Reflect**.  Each phase dispatches
child agents through ``llm_query()`` and ``llm_query_batched()`` for
parallel narrative development.

### Usage

Import the skill entry point and call it with a seed story:

```repl
from rlm_repl_skills.polya_narrative import run_polya_narrative
result = run_polya_narrative(story, max_cycles=2)
print(result)
```

### Parameters

- ``story`` (str): The seed narrative/story to develop and refine.
- ``max_cycles`` (int, default 2): Maximum Understand-Plan-Implement-Reflect
  cycles.  The loop terminates early if the REFLECT phase returns
  ``VERDICT: COMPLETE``.
- ``emit_debug`` (bool, default True): Print debug logs to stdout.

### Return Value

``PolyaNarrativeResult`` with attributes:
- ``.narrative``: The fully refined narrative text.
- ``.cycles_completed``: Number of cycles that ran.
- ``.verdict``: ``"COMPLETE"`` or ``"CONTINUE"``.
- ``.phase_results``: List of ``PolyaPhaseResult`` per phase per cycle.
- ``.final_reflection``: The last REFLECT phase output.
- ``.debug_log``: List of debug messages.

### How It Works

Each cycle runs four phases:

1. **UNDERSTAND** — ``llm_query()`` analyzes the narrative for gaps,
   strengths, and areas needing development.
2. **PLAN** — ``llm_query()`` creates 3-5 parallel work packets from the
   understanding assessment.
3. **IMPLEMENT** — ``llm_query_batched()`` executes all work packets
   concurrently, producing enriched narrative sections.
4. **REFLECT** — ``llm_query()`` evaluates quality and returns
   ``VERDICT: COMPLETE`` (quality >= 8/10) or ``VERDICT: CONTINUE``.

### Example: Full Invocation

```repl
from rlm_repl_skills.polya_narrative import run_polya_narrative
seed = "An AI assistant that helps people navigate unemployment benefits..."
result = run_polya_narrative(seed, max_cycles=2)
print(f"Verdict: {result.verdict}, Cycles: {result.cycles_completed}")
print(f"Narrative length: {len(result.narrative)} chars")
```

After receiving the result, present the refined narrative and verdict via
``set_model_response``.
"""),
)


def build_polya_skill_instruction_block() -> str:
    """Return the skill discovery XML + full instructions for prompt injection.

    Appended to ``static_instruction`` in :func:`create_reasoning_agent`.
    """
    discovery_xml = format_skills_as_xml([POLYA_NARRATIVE_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{POLYA_NARRATIVE_SKILL.instructions}"


# ===========================================================================
# Source-expandable REPL exports (side-effect registration at import time)
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants: Phase instructions
# ---------------------------------------------------------------------------

_POLYA_UNDERSTAND_INSTRUCTIONS_SRC = '''\
POLYA_UNDERSTAND_INSTRUCTIONS = (
    "You are executing the UNDERSTAND phase of a Polya problem-solving cycle. "
    "Your task is to deeply analyze the narrative provided and produce a "
    "world-model assessment. Identify: "
    "(1) What is already strong and well-developed in the narrative, "
    "(2) What is missing, underspecified, or needs research, "
    "(3) What emotional and thematic elements need strengthening, "
    "(4) What technical/product details need grounding in reality, "
    "(5) What user journey gaps exist. "
    "Return a structured assessment as a detailed narrative memo."
)\
'''

_POLYA_PLAN_INSTRUCTIONS_SRC = '''\
POLYA_PLAN_INSTRUCTIONS = (
    "You are executing the PLAN phase of a Polya problem-solving cycle. "
    "Given the narrative and the understanding assessment, create a concrete "
    "plan for enriching and developing the narrative. "
    "Your plan MUST identify 3-5 specific work packets that can be executed "
    "in parallel. Each work packet should specify: "
    "(1) What section or theme to develop, "
    "(2) What specific content to add or revise, "
    "(3) What tone and emotional register to use, "
    "(4) Success criteria for that packet. "
    "Format each work packet with a clear header line starting with "
    "'Work Packet N:' followed by the detailed instructions."
)\
'''

_POLYA_IMPLEMENT_INSTRUCTIONS_SRC = '''\
POLYA_IMPLEMENT_INSTRUCTIONS = (
    "You are executing the IMPLEMENT phase of a Polya problem-solving cycle. "
    "You have been given a specific work packet from the planning phase. "
    "Write rich, vivid, specific narrative content that fulfills the work packet. "
    "Ground the content in real details, authentic emotion, and practical specifics. "
    "Do not be generic or abstract. Write as if you are crafting a chapter of a "
    "compelling story that also serves as a product vision document. "
    "Your output should be polished prose ready to be woven into the larger narrative."
)\
'''

_POLYA_REFLECT_INSTRUCTIONS_SRC = '''\
POLYA_REFLECT_INSTRUCTIONS = (
    "You are executing the REFLECT phase of a Polya problem-solving cycle. "
    "Review the full narrative including all new implementations from this cycle. "
    "Assess: (1) Overall narrative coherence and quality, "
    "(2) Emotional resonance and authenticity, "
    "(3) Technical feasibility and product clarity, "
    "(4) Completeness of the vision, "
    "(5) What still needs work in the next cycle. "
    "Rate the narrative quality on a scale of 1-10. "
    "If quality >= 8, recommend COMPLETE. Otherwise recommend CONTINUE "
    "with specific guidance for the next cycle. "
    "Your response MUST contain exactly one of these verdicts on its own line: "
    "'VERDICT: COMPLETE' or 'VERDICT: CONTINUE'"
)\
'''

# ---------------------------------------------------------------------------
# Result classes
# ---------------------------------------------------------------------------

_POLYA_PHASE_RESULT_SRC = '''\
class PolyaPhaseResult:
    def __init__(self, phase, cycle, content, debug_log=None):
        self.phase = phase
        self.cycle = cycle
        self.content = content
        self.debug_log = debug_log or []

    def __repr__(self):
        return (
            "PolyaPhaseResult(phase=" + repr(self.phase)
            + ", cycle=" + str(self.cycle)
            + ", content_len=" + str(len(self.content)) + ")"
        )\
'''

_POLYA_NARRATIVE_RESULT_SRC = '''\
class PolyaNarrativeResult:
    def __init__(self, narrative, cycles_completed, phase_results,
                 final_reflection, debug_log=None):
        self.narrative = narrative
        self.cycles_completed = cycles_completed
        self.phase_results = phase_results
        self.final_reflection = final_reflection
        self.debug_log = debug_log or []
        self.verdict = (
            "COMPLETE"
            if "VERDICT: COMPLETE" in (final_reflection or "").upper()
            else "CONTINUE"
        )

    def __repr__(self):
        return (
            "PolyaNarrativeResult(cycles=" + str(self.cycles_completed)
            + ", verdict=" + repr(self.verdict)
            + ", narrative_len=" + str(len(self.narrative)) + ")"
        )\
'''

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_BUILD_UNDERSTAND_PROMPT_SRC = '''\
def build_understand_prompt(narrative, cycle_num, prior_reflection=None):
    parts = [POLYA_UNDERSTAND_INSTRUCTIONS]
    parts.append("\\n\\n--- CYCLE " + str(cycle_num) + " ---")
    parts.append("\\n\\nCURRENT NARRATIVE:\\n" + narrative)
    if prior_reflection:
        parts.append("\\n\\nPRIOR CYCLE REFLECTION:\\n" + prior_reflection)
    parts.append("\\n\\nProduce your UNDERSTAND assessment now.")
    return "".join(parts)\
'''

_BUILD_PLAN_PROMPT_SRC = '''\
def build_plan_prompt(narrative, understanding, cycle_num):
    parts = [POLYA_PLAN_INSTRUCTIONS]
    parts.append("\\n\\n--- CYCLE " + str(cycle_num) + " ---")
    parts.append("\\n\\nCURRENT NARRATIVE:\\n" + narrative)
    parts.append("\\n\\nUNDERSTAND ASSESSMENT:\\n" + understanding)
    parts.append("\\n\\nProduce your PLAN with numbered Work Packets now.")
    return "".join(parts)\
'''

_BUILD_IMPLEMENT_PROMPT_SRC = '''\
def build_implement_prompt(narrative, work_packet, cycle_num, packet_idx):
    parts = [POLYA_IMPLEMENT_INSTRUCTIONS]
    parts.append(
        "\\n\\n--- CYCLE " + str(cycle_num)
        + ", WORK PACKET " + str(packet_idx + 1) + " ---"
    )
    parts.append("\\n\\nFULL NARRATIVE CONTEXT (excerpt):\\n" + narrative[:4000])
    parts.append("\\n\\nYOUR WORK PACKET:\\n" + work_packet)
    parts.append(
        "\\n\\nWrite the enriched narrative content for this work packet now."
    )
    return "".join(parts)\
'''

_BUILD_REFLECT_PROMPT_SRC = '''\
def build_reflect_prompt(narrative, implementations, cycle_num):
    parts = [POLYA_REFLECT_INSTRUCTIONS]
    parts.append("\\n\\n--- CYCLE " + str(cycle_num) + " ---")
    parts.append("\\n\\nFULL NARRATIVE WITH IMPLEMENTATIONS:\\n" + narrative)
    parts.append("\\n\\nNEW IMPLEMENTATIONS THIS CYCLE:")
    for i, impl in enumerate(implementations):
        parts.append(
            "\\n\\n[Implementation " + str(i + 1) + "]:\\n" + impl
        )
    parts.append(
        "\\n\\nProduce your REFLECT assessment with VERDICT: COMPLETE "
        "or VERDICT: CONTINUE now."
    )
    return "".join(parts)\
'''

# ---------------------------------------------------------------------------
# Work packet extraction
# ---------------------------------------------------------------------------

_EXTRACT_WORK_PACKETS_SRC = '''\
def extract_work_packets(plan_text):
    """Extract work packets from plan text by splitting on section headers."""
    lines = plan_text.split("\\n")
    packets = []
    current_packet = []
    for line in lines:
        s = line.strip()
        sl = s.lower()
        is_header = False
        if sl.startswith("work packet"):
            is_header = True
        elif sl.startswith("packet "):
            is_header = True
        elif len(s) > 3 and s[0].isdigit() and s[1] in ".)" and len(s) > 30:
            is_header = True
        if is_header and current_packet:
            text = "\\n".join(current_packet).strip()
            if len(text) > 40:
                packets.append(text)
            current_packet = [line]
        else:
            current_packet.append(line)
    if current_packet:
        text = "\\n".join(current_packet).strip()
        if len(text) > 40:
            packets.append(text)
    if len(packets) >= 2:
        return packets[:5]
    return [plan_text]\
'''

# ---------------------------------------------------------------------------
# Main orchestrator function
# ---------------------------------------------------------------------------

_RUN_POLYA_NARRATIVE_SRC = '''\
def run_polya_narrative(
    story,
    max_cycles=2,
    emit_debug=True,
):
    """Run the Polya narrative refinement loop.

    Args:
        story: Seed narrative/story to develop and refine.
        max_cycles: Maximum Understand-Plan-Implement-Reflect cycles.
        emit_debug: Whether to print debug logs.

    Returns:
        PolyaNarrativeResult with the refined narrative and phase artifacts.
    """
    debug_log = []
    phase_results = []
    narrative = story
    prior_reflection = None

    def _log(msg):
        if emit_debug:
            print(msg)
        debug_log.append(msg)

    _log("[polya] Starting Polya narrative loop: max_cycles=" + str(max_cycles))
    _log("[polya] Seed narrative length: " + str(len(story)) + " chars")

    for cycle in range(1, max_cycles + 1):
        sep = "=" * 60
        _log("\\n" + sep)
        _log("[polya] === CYCLE " + str(cycle) + "/" + str(max_cycles) + " ===")
        _log(sep)

        # --- UNDERSTAND PHASE ---
        _log("\\n[polya] Phase 1/4: UNDERSTAND")
        understand_prompt = build_understand_prompt(
            narrative, cycle, prior_reflection
        )
        _log(
            "[polya] Dispatching understand child (prompt_len="
            + str(len(understand_prompt)) + ")"
        )
        understanding = llm_query(understand_prompt)
        understanding_str = str(understanding)
        _log("[polya] Understanding received: " + understanding_str[:200] + "...")
        phase_results.append(
            PolyaPhaseResult("understand", cycle, understanding_str)
        )

        # --- PLAN PHASE ---
        _log("\\n[polya] Phase 2/4: PLAN")
        plan_prompt = build_plan_prompt(narrative, understanding_str, cycle)
        _log(
            "[polya] Dispatching plan child (prompt_len="
            + str(len(plan_prompt)) + ")"
        )
        plan = llm_query(plan_prompt)
        plan_str = str(plan)
        _log("[polya] Plan received: " + plan_str[:200] + "...")
        phase_results.append(PolyaPhaseResult("plan", cycle, plan_str))

        # --- IMPLEMENT PHASE (batched fanout) ---
        _log("\\n[polya] Phase 3/4: IMPLEMENT")
        work_packets = extract_work_packets(plan_str)
        _log(
            "[polya] Extracted " + str(len(work_packets))
            + " work packets from plan"
        )
        impl_prompts = [
            build_implement_prompt(narrative, packet, cycle, i)
            for i, packet in enumerate(work_packets)
        ]
        _log(
            "[polya] Dispatching " + str(len(impl_prompts))
            + " implement children (batched)"
        )
        implementations = llm_query_batched(impl_prompts)
        impl_strs = [str(impl) for impl in implementations]
        for i, impl_str in enumerate(impl_strs):
            _log(
                "[polya] Implementation " + str(i + 1) + " received: "
                + impl_str[:150] + "..."
            )
            phase_results.append(
                PolyaPhaseResult("implement", cycle, impl_str)
            )

        # Merge implementations into narrative
        cycle_header = (
            "\\n\\n--- Cycle " + str(cycle) + " Enrichments ---\\n\\n"
        )
        narrative = narrative + cycle_header + "\\n\\n---\\n\\n".join(impl_strs)

        # --- REFLECT PHASE ---
        _log("\\n[polya] Phase 4/4: REFLECT")
        reflect_prompt = build_reflect_prompt(narrative, impl_strs, cycle)
        _log(
            "[polya] Dispatching reflect child (prompt_len="
            + str(len(reflect_prompt)) + ")"
        )
        reflection = llm_query(reflect_prompt)
        reflection_str = str(reflection)
        _log("[polya] Reflection received: " + reflection_str[:200] + "...")
        phase_results.append(
            PolyaPhaseResult("reflect", cycle, reflection_str)
        )
        prior_reflection = reflection_str

        # Check verdict
        if "VERDICT: COMPLETE" in reflection_str.upper():
            _log(
                "\\n[polya] Reflection verdict: COMPLETE at cycle "
                + str(cycle)
            )
            return PolyaNarrativeResult(
                narrative=narrative,
                cycles_completed=cycle,
                phase_results=phase_results,
                final_reflection=reflection_str,
                debug_log=debug_log,
            )
        else:
            _log(
                "[polya] Reflection verdict: CONTINUE (cycle "
                + str(cycle) + ")"
            )

    _log(
        "\\n[polya] Max cycles (" + str(max_cycles)
        + ") reached, returning current narrative"
    )
    return PolyaNarrativeResult(
        narrative=narrative,
        cycles_completed=max_cycles,
        phase_results=phase_results,
        final_reflection=prior_reflection or "",
        debug_log=debug_log,
    )\
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

# Phase instruction constants
register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="POLYA_UNDERSTAND_INSTRUCTIONS",
        source=_POLYA_UNDERSTAND_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="POLYA_PLAN_INSTRUCTIONS",
        source=_POLYA_PLAN_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="POLYA_IMPLEMENT_INSTRUCTIONS",
        source=_POLYA_IMPLEMENT_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="POLYA_REFLECT_INSTRUCTIONS",
        source=_POLYA_REFLECT_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

# Result classes
register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="PolyaPhaseResult",
        source=_POLYA_PHASE_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="PolyaNarrativeResult",
        source=_POLYA_NARRATIVE_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

# Prompt builders
register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="build_understand_prompt",
        source=_BUILD_UNDERSTAND_PROMPT_SRC,
        requires=["POLYA_UNDERSTAND_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="build_plan_prompt",
        source=_BUILD_PLAN_PROMPT_SRC,
        requires=["POLYA_PLAN_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="build_implement_prompt",
        source=_BUILD_IMPLEMENT_PROMPT_SRC,
        requires=["POLYA_IMPLEMENT_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="build_reflect_prompt",
        source=_BUILD_REFLECT_PROMPT_SRC,
        requires=["POLYA_REFLECT_INSTRUCTIONS"],
        kind="function",
    )
)

# Work packet extractor
register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="extract_work_packets",
        source=_EXTRACT_WORK_PACKETS_SRC,
        requires=[],
        kind="function",
    )
)

# Main orchestrator function
register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_narrative",
        name="run_polya_narrative",
        source=_RUN_POLYA_NARRATIVE_SRC,
        requires=[
            "PolyaPhaseResult",
            "PolyaNarrativeResult",
            "build_understand_prompt",
            "build_plan_prompt",
            "build_implement_prompt",
            "build_reflect_prompt",
            "extract_work_packets",
            "POLYA_UNDERSTAND_INSTRUCTIONS",
            "POLYA_PLAN_INSTRUCTIONS",
            "POLYA_IMPLEMENT_INSTRUCTIONS",
            "POLYA_REFLECT_INSTRUCTIONS",
        ],
        kind="function",
    )
)
