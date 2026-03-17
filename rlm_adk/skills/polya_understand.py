"""ADK Skill definition + source-expandable REPL exports: Polya understand loop.

Defines ``POLYA_UNDERSTAND_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_polya_understand_skill_instruction_block()`` which returns the
XML discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand import run_polya_understand`` expands
into inline source before the AST rewriter runs.

The loop is designed for large or incomplete project contexts:
  1. INVENTORY: Scan context packets in parallel for givens, assumptions, gaps
  2. UNDERSTAND: Synthesize an operational understanding artifact
  3. VALIDATE: Judge well-posedness and emit ordered missing prerequisites
  4. REFLECT: Critique specificity/ordering and decide COMPLETE or CONTINUE
"""

from __future__ import annotations

import textwrap

from google.adk.skills.models import Frontmatter, Skill
from google.adk.skills.prompt import format_skills_as_xml

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ===========================================================================
# ADK Skill definition (prompt discovery)
# ===========================================================================

POLYA_UNDERSTAND_SKILL = Skill(
    frontmatter=Frontmatter(
        name="polya-understand",
        description=(
            "Iterative Polya understand-loop for large or incomplete project "
            "contexts. Scans context packets, synthesizes the true objective, "
            "identifies missing prerequisites, and emits an ordered "
            "retrieval plan with halt guidance before planning or "
            "implementation."
        ),
    ),
    instructions=textwrap.dedent("""\
## polya-understand — Context Validation and Retrieval Planning

Use this source-expandable REPL skill when a project is large, messy, or
missing key context. It runs a Polya-style understanding loop that inventories
the available context, synthesizes the actual task, checks whether the problem
is well-posed, and emits a concrete retrieval order for missing prerequisites.

This is the preferred skill for **big projects** or **new projects with
uncertain surrounding context**. Use it before planning or implementation.

### Usage

```repl
from rlm_repl_skills.polya_understand import run_polya_understand
result = run_polya_understand(
    objective="Understand this project before planning any implementation work.",
    project_context=context_blob,
    project_name="example-project",
)
print(result)
print(result.retrieval_order)
print(result.halted)
```

### Parameters

- ``objective`` (str): The concrete objective you are trying to understand.
- ``project_context`` (str | list | dict): The currently available context.
  Can be a packed repo XML string, repomix shards, notes, manifests, or a
  filename-to-content mapping.
- ``project_name`` (str, default ``"project"``): Friendly label used in prompts.
- ``max_cycles`` (int, default 2): Maximum inventory-understand-validate-reflect
  cycles.
- ``max_chars_per_packet`` (int, default 12000): Chunk size for large context.
- ``max_packets`` (int, default 10): Caps how many packets are analyzed in one
  cycle after chunking/merging.
- ``max_retrievals`` (int, default 8): Caps extracted retrieval-order items.
- ``emit_debug`` (bool, default True): Print debug logs to stdout.

### Return Value

``PolyaUnderstandResult`` with attributes:
- ``.understanding``: The synthesized understand-phase artifact.
- ``.validation``: The last VALIDATE phase output.
- ``.retrieval_order``: Ordered list of missing prerequisite artifact names.
- ``.halted``: Whether the loop concluded that planning should halt.
- ``.well_posedness``: ``WELL_POSED``, ``AMBIGUOUS``, ``UNDERDETERMINED``, or
  similar marker parsed from the phase output.
- ``.can_continue``: Whether the model judged the task can proceed without more
  retrieval.
- ``.cycles_completed``: Number of cycles that ran.
- ``.phase_results``: List of ``PolyaUnderstandPhaseResult`` objects.
- ``.final_reflection``: The last REFLECT phase output.
- ``.debug_log``: List of debug messages.

### How It Works

Each cycle runs four phases:

1. **INVENTORY** — ``llm_query_batched()`` scans context packets in parallel and
   extracts givens, assumptions, signals, and likely missing prerequisites.
2. **UNDERSTAND** — ``llm_query()`` synthesizes a proper understand artifact:
   restatement, objective, givens, unknowns, relationships, constraints,
   boundaries, and success criteria.
3. **VALIDATE** — ``llm_query()`` decides whether the problem is well-posed,
   whether work must halt, and what ordered retrieval plan is required.
4. **REFLECT** — ``llm_query()`` critiques generic or over-broad retrieval
   requests, repairs sequencing, and returns ``VERDICT: COMPLETE`` or
   ``VERDICT: CONTINUE``.

### Example: Run Against a Large Repo

```repl
info = probe_repo("/path/to/project")
if info.total_tokens < 125_000:
    project_context = pack_repo("/path/to/project")
else:
    project_context = shard_repo("/path/to/project").chunks

from rlm_repl_skills.polya_understand import run_polya_understand
result = run_polya_understand(
    objective="Validate whether I have enough context to safely modify this codebase.",
    project_context=project_context,
    project_name="project",
)
print(result.well_posedness)
print(result.retrieval_order)
```

After receiving the result, either:
- halt and present the retrieval plan if ``result.halted`` is true, or
- continue into planning/implementation if ``result.can_continue`` is true.
"""),
)


def build_polya_understand_skill_instruction_block() -> str:
    """Return the skill discovery XML + full instructions for prompt injection."""
    discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{POLYA_UNDERSTAND_SKILL.instructions}"


# ===========================================================================
# Source-expandable REPL exports (side-effect registration at import time)
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants: Phase instructions
# ---------------------------------------------------------------------------

_POLYA_INVENTORY_INSTRUCTIONS_SRC = '''\
POLYA_INVENTORY_INSTRUCTIONS = (
    "You are executing the INVENTORY phase of a Polya understand loop. "
    "You will inspect one packet of project context and extract only what the "
    "packet actually supports. Apply Polya steps around givens, unknowns, "
    "assumptions, definitions, constraints, and boundary notes. "
    "Name concrete missing prerequisites only when the packet gives a real "
    "signal that they are required. Do not guess hidden artifacts from priors. "
    "Return a memo with these headings exactly: "
    "GIVENS, SIGNALS, UNKNOWNS, FACTS_VS_ASSUMPTIONS, "
    "CONSTRAINTS, POTENTIAL_GAPS, BOUNDARY_NOTES."
)\
'''

_POLYA_UNDERSTAND_SYNTHESIS_INSTRUCTIONS_SRC = '''\
POLYA_UNDERSTAND_SYNTHESIS_INSTRUCTIONS = (
    "You are executing the UNDERSTAND synthesis phase of a Polya understand "
    "loop. Combine the inventory memos into a single operational "
    "understanding artifact. Restate the problem, define the exact objective, "
    "inventory the givens, identify unknowns and their relationships, "
    "clarify definitions, surface constraints, separate facts from "
    "assumptions, describe a representation of the problem, classify the "
    "problem type, define boundaries, and state the success criteria. "
    "Return headings exactly: RESTATEMENT, OBJECTIVE, GIVENS, UNKNOWNS, "
    "RELATIONSHIPS, DEFINITIONS, CONSTRAINTS, FACTS_VS_ASSUMPTIONS, "
    "REPRESENTATION, PROBLEM_TYPE, BOUNDARIES, SUCCESS_CRITERIA."
)\
'''

_POLYA_VALIDATE_INSTRUCTIONS_SRC = '''\
POLYA_VALIDATE_INSTRUCTIONS = (
    "You are executing the VALIDATE phase of a Polya understand loop. "
    "Judge whether the problem is well-posed using the understanding artifact "
    "and the inventory memos. Focus on insufficiency detection rather than "
    "solving the task. If the available context is missing authoritative, "
    "private, historical, credentialed, or cross-domain prerequisites, you "
    "must halt and emit an ordered retrieval plan. "
    "Use only concrete artifact names grounded in the provided evidence. "
    "Avoid vague requests like more information or additional documents. "
    "Classify each retrieval using one of: DOCUMENT, CREDENTIAL, "
    "AGENT_SKILL, HISTORICAL_RECORD, THIRD_PARTY_RECORD, USER_ATTESTATION, "
    "REGULATORY_REFERENCE, COMPUTATIONAL_PREREQ, CROSS_DOMAIN_LINK. "
    "Return this exact structure: "
    "WELL_POSEDNESS: <value> "
    "CAN_CONTINUE: YES|NO "
    "HALT: YES|NO "
    "RETRIEVAL_ORDER: numbered items in dependency order using the form "
    "'1. artifact | category=... | source=... | signal=... | "
    "why_non_derivable=... | blocks=...' or the word NONE "
    "MISSING_PREREQUISITES: bullet list with the same artifacts and short reasons "
    "NOTES: final explanation."
)\
'''

_POLYA_REFLECT_INSTRUCTIONS_SRC = '''\
POLYA_REFLECT_INSTRUCTIONS = (
    "You are executing the REFLECT phase of a Polya understand loop. "
    "Critique the validation output for three failure modes: "
    "(1) generic retrieval requests, "
    "(2) hallucinated or weakly supported artifacts, and "
    "(3) incorrect ordering when a dependency chain exists. "
    "If the validation output is already specific, evidence-grounded, and "
    "sequenced correctly, return VERDICT: COMPLETE. Otherwise return "
    "VERDICT: CONTINUE and repair the retrieval order. "
    "Preserve the same artifact names when possible. "
    "Return this exact structure: "
    "VERDICT: COMPLETE|CONTINUE "
    "WELL_POSEDNESS: <value> "
    "CAN_CONTINUE: YES|NO "
    "HALT: YES|NO "
    "REVISED_RETRIEVAL_ORDER: numbered items or NONE "
    "REFLECTION: concise critique."
)\
'''

# ---------------------------------------------------------------------------
# Result classes
# ---------------------------------------------------------------------------

_POLYA_UNDERSTAND_PHASE_RESULT_SRC = '''\
class PolyaUnderstandPhaseResult:
    def __init__(self, phase, cycle, content, debug_log=None):
        self.phase = phase
        self.cycle = cycle
        self.content = content
        self.debug_log = debug_log or []

    def __repr__(self):
        return (
            "PolyaUnderstandPhaseResult(phase=" + repr(self.phase)
            + ", cycle=" + str(self.cycle)
            + ", content_len=" + str(len(self.content)) + ")"
        )\
'''

_POLYA_UNDERSTAND_RESULT_SRC = '''\
class PolyaUnderstandResult:
    def __init__(
        self,
        project_name,
        objective,
        understanding,
        validation,
        retrieval_order,
        cycles_completed,
        phase_results,
        final_reflection,
        debug_log=None,
    ):
        self.project_name = project_name
        self.objective = objective
        self.understanding = understanding
        self.validation = validation
        self.retrieval_order = retrieval_order
        self.cycles_completed = cycles_completed
        self.phase_results = phase_results
        self.final_reflection = final_reflection
        self.debug_log = debug_log or []
        self.well_posedness = (
            extract_marker_value(final_reflection, "WELL_POSEDNESS")
            or extract_marker_value(validation, "WELL_POSEDNESS")
        )
        can_continue_value = (
            extract_marker_value(final_reflection, "CAN_CONTINUE")
            or extract_marker_value(validation, "CAN_CONTINUE")
        )
        halt_value = (
            extract_marker_value(final_reflection, "HALT")
            or extract_marker_value(validation, "HALT")
        )
        self.can_continue = can_continue_value.upper() == "YES"
        self.halted = halt_value.upper() == "YES"

    def __repr__(self):
        return (
            "PolyaUnderstandResult(project_name=" + repr(self.project_name)
            + ", cycles=" + str(self.cycles_completed)
            + ", halted=" + str(self.halted)
            + ", retrievals=" + str(len(self.retrieval_order)) + ")"
        )\
'''

# ---------------------------------------------------------------------------
# Helpers: context preparation and extraction
# ---------------------------------------------------------------------------

_STRINGIFY_CONTEXT_SRC = '''\
def stringify_context(value, heading="context"):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        pieces = []
        keys = sorted(value.keys(), key=lambda item: str(item))
        for key in keys:
            rendered = stringify_context(value[key], str(key))
            pieces.append("[[" + str(key) + "]]\\n" + rendered)
        return "\\n\\n".join(pieces)
    if isinstance(value, (list, tuple)):
        pieces = []
        for idx, item in enumerate(value):
            rendered = stringify_context(item, heading + "_" + str(idx + 1))
            pieces.append("[[item_" + str(idx + 1) + "]]\\n" + rendered)
        return "\\n\\n".join(pieces)
    return repr(value)\
'''

_CHUNK_TEXT_SRC = '''\
def chunk_text(text, max_chars=12000):
    text = str(text or "")
    if not text:
        return [""]
    if len(text) <= max_chars:
        return [text]
    chunks = []
    cursor = 0
    min_cut = int(max_chars * 0.5)
    while cursor < len(text):
        end = min(len(text), cursor + max_chars)
        cut = end
        if end < len(text):
            split_at = text.rfind("\\n\\n", cursor, end)
            if split_at < cursor + min_cut:
                split_at = text.rfind("\\n", cursor, end)
            if split_at >= cursor + min_cut:
                cut = split_at
        if cut <= cursor:
            cut = end
        piece = text[cursor:cut].strip()
        if piece:
            chunks.append(piece)
        cursor = cut
    return chunks or [text[:max_chars]]\
'''

_CONDENSE_PACKETS_SRC = '''\
def condense_packets(packets, max_packets=10):
    if len(packets) <= max_packets:
        return packets
    group_size = (len(packets) + max_packets - 1) // max_packets
    condensed = []
    for start in range(0, len(packets), group_size):
        group = packets[start:start + group_size]
        header = (
            "[[merged_packets_" + str(start + 1)
            + "_to_" + str(start + len(group)) + "]]"
        )
        condensed.append(header + "\\n" + "\\n\\n-----\\n\\n".join(group))
    return condensed[:max_packets]\
'''

_PREPARE_CONTEXT_PACKETS_SRC = '''\
def prepare_context_packets(project_context, max_chars_per_packet=12000, max_packets=10):
    packets = []
    if isinstance(project_context, dict):
        keys = sorted(project_context.keys(), key=lambda item: str(item))
        for key in keys:
            base = "[[" + str(key) + "]]\\n" + stringify_context(project_context[key], str(key))
            packets.extend(chunk_text(base, max_chars_per_packet))
    elif isinstance(project_context, (list, tuple)):
        for idx, item in enumerate(project_context):
            base = (
                "[[packet_" + str(idx + 1) + "]]\\n"
                + stringify_context(item, "packet_" + str(idx + 1))
            )
            packets.extend(chunk_text(base, max_chars_per_packet))
    else:
        base = stringify_context(project_context, "project_context")
        packets.extend(chunk_text(base, max_chars_per_packet))
    packets = [packet for packet in packets if str(packet).strip()]
    if not packets:
        packets = ["[[empty_context]]"]
    return condense_packets(packets, max_packets)\
'''

_EXTRACT_MARKER_VALUE_SRC = '''\
def extract_marker_value(text, marker):
    prefix = marker.upper() + ":"
    for line in str(text or "").split("\\n"):
        stripped = line.strip()
        if stripped.upper().startswith(prefix):
            return stripped[len(marker) + 1:].strip()
    return ""\
'''

_EXTRACT_RETRIEVAL_ORDER_SRC = '''\
def extract_retrieval_order(text, max_items=8):
    lines = str(text or "").split("\\n")
    for header in ("REVISED_RETRIEVAL_ORDER", "RETRIEVAL_ORDER"):
        start_idx = None
        inline_value = ""
        for idx, line in enumerate(lines):
            stripped = line.strip()
            upper = stripped.upper()
            if upper == header + ":":
                start_idx = idx + 1
                break
            if upper.startswith(header + ":"):
                start_idx = idx + 1
                inline_value = stripped.split(":", 1)[1].strip()
                break
        items = []
        if inline_value:
            if inline_value.upper() == "NONE":
                return []
            candidate = inline_value.split("|", 1)[0].strip()
            if candidate:
                items.append(candidate)
        if start_idx is None:
            continue
        for line in lines[start_idx:]:
            stripped = line.strip()
            if not stripped:
                if items:
                    break
                continue
            upper = stripped.upper()
            if upper.endswith(":") and (
                stripped.replace("_", "").replace("-", "").replace(":", "").replace(" ", "").isupper()
            ):
                break
            candidate = stripped
            if candidate[:1] in "-*":
                candidate = candidate[1:].strip()
            else:
                pos = 0
                while pos < len(candidate) and candidate[pos].isdigit():
                    pos += 1
                if pos > 0 and pos < len(candidate) and candidate[pos] in ".)":
                    candidate = candidate[pos + 1:].strip()
            if not candidate:
                continue
            if candidate.upper() == "NONE":
                return []
            candidate = candidate.split("|", 1)[0].strip()
            if candidate and candidate not in items:
                items.append(candidate)
            if len(items) >= max_items:
                return items
        if items:
            return items
    return []\
'''

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_BUILD_INVENTORY_PROMPT_SRC = '''\
def build_inventory_prompt(
    objective,
    project_name,
    packet_text,
    cycle_num,
    packet_idx,
    packet_count,
    prior_reflection=None,
):
    parts = [POLYA_INVENTORY_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    parts.append(
        "\\nPACKET: " + str(packet_idx + 1) + "/" + str(packet_count)
    )
    if prior_reflection:
        parts.append("\\n\\nPRIOR_REFLECTION:\\n" + prior_reflection)
    parts.append("\\n\\nPROJECT_CONTEXT_PACKET:\\n" + packet_text)
    parts.append("\\n\\nReturn the packet memo now.")
    return "".join(parts)\
'''

_BUILD_UNDERSTAND_PROMPT_SRC = '''\
def build_understand_prompt(
    objective,
    project_name,
    inventory_memos,
    cycle_num,
    prior_reflection=None,
):
    parts = [POLYA_UNDERSTAND_SYNTHESIS_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    if prior_reflection:
        parts.append("\\n\\nPRIOR_REFLECTION:\\n" + prior_reflection)
    parts.append("\\n\\nINVENTORY_MEMOS:")
    for idx, memo in enumerate(inventory_memos):
        parts.append("\\n\\n[MEMO " + str(idx + 1) + "]:\\n" + memo)
    parts.append("\\n\\nReturn the synthesized understanding artifact now.")
    return "".join(parts)\
'''

_BUILD_VALIDATE_PROMPT_SRC = '''\
def build_validate_prompt(
    objective,
    project_name,
    understanding,
    inventory_memos,
    cycle_num,
):
    parts = [POLYA_VALIDATE_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    parts.append("\\n\\nUNDERSTANDING_ARTIFACT:\\n" + understanding)
    parts.append("\\n\\nSUPPORTING_INVENTORY_MEMOS:")
    for idx, memo in enumerate(inventory_memos):
        parts.append("\\n\\n[MEMO " + str(idx + 1) + "]:\\n" + memo)
    parts.append("\\n\\nReturn the validation artifact now.")
    return "".join(parts)\
'''

_BUILD_REFLECT_PROMPT_SRC = '''\
def build_reflect_prompt(
    objective,
    project_name,
    understanding,
    validation,
    cycle_num,
    prior_reflection=None,
):
    parts = [POLYA_REFLECT_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    if prior_reflection:
        parts.append("\\n\\nPRIOR_REFLECTION:\\n" + prior_reflection)
    parts.append("\\n\\nUNDERSTANDING_ARTIFACT:\\n" + understanding)
    parts.append("\\n\\nVALIDATION_ARTIFACT:\\n" + validation)
    parts.append("\\n\\nReturn the reflection artifact now.")
    return "".join(parts)\
'''

# ---------------------------------------------------------------------------
# Main orchestrator function
# ---------------------------------------------------------------------------

_RUN_POLYA_UNDERSTAND_SRC = '''\
def run_polya_understand(
    objective,
    project_context,
    project_name="project",
    max_cycles=2,
    max_chars_per_packet=12000,
    max_packets=10,
    max_retrievals=8,
    emit_debug=True,
):
    """Run the Polya understand loop against a project context.

    Args:
        objective: Concrete objective to validate before planning/execution.
        project_context: Current context blob, shards, or manifest mapping.
        project_name: Friendly label for prompt context.
        max_cycles: Maximum inventory-understand-validate-reflect cycles.
        max_chars_per_packet: Packet size for chunking large context.
        max_packets: Maximum packet count after chunking/merging.
        max_retrievals: Maximum retrieval-order items to extract.
        emit_debug: Whether to print debug logs.

    Returns:
        PolyaUnderstandResult with the synthesized understanding and
        ordered missing-context retrieval plan.
    """
    debug_log = []
    phase_results = []
    objective_text = (
        str(objective).strip()
        if str(objective).strip()
        else "Validate whether the current project context is sufficient to proceed."
    )
    packets = prepare_context_packets(
        project_context,
        max_chars_per_packet=max_chars_per_packet,
        max_packets=max_packets,
    )
    prior_reflection = None
    final_understanding = ""
    final_validation = ""
    final_reflection = ""
    final_retrieval_order = []

    def _log(msg):
        if emit_debug:
            print(msg)
        debug_log.append(msg)

    _log(
        "[polya_understand] Starting understand loop for "
        + project_name + " with " + str(len(packets)) + " packet(s)"
    )

    for cycle in range(1, max_cycles + 1):
        sep = "=" * 60
        _log("\\n" + sep)
        _log(
            "[polya_understand] === CYCLE "
            + str(cycle) + "/" + str(max_cycles) + " ==="
        )
        _log(sep)

        # --- INVENTORY PHASE (batched fanout) ---
        _log("\\n[polya_understand] Phase 1/4: INVENTORY")
        inventory_prompts = [
            build_inventory_prompt(
                objective_text,
                project_name,
                packet,
                cycle,
                idx,
                len(packets),
                prior_reflection,
            )
            for idx, packet in enumerate(packets)
        ]
        _log(
            "[polya_understand] Dispatching " + str(len(inventory_prompts))
            + " inventory child(ren)"
        )
        inventory_outputs = llm_query_batched(inventory_prompts)
        inventory_memos = [str(item) for item in inventory_outputs]
        for idx, memo in enumerate(inventory_memos):
            _log(
                "[polya_understand] Inventory memo "
                + str(idx + 1) + ": " + memo[:160] + "..."
            )
            phase_results.append(
                PolyaUnderstandPhaseResult("inventory", cycle, memo)
            )

        # --- UNDERSTAND PHASE ---
        _log("\\n[polya_understand] Phase 2/4: UNDERSTAND")
        understand_prompt = build_understand_prompt(
            objective_text,
            project_name,
            inventory_memos,
            cycle,
            prior_reflection,
        )
        _log(
            "[polya_understand] Dispatching understand child (prompt_len="
            + str(len(understand_prompt)) + ")"
        )
        understanding = llm_query(understand_prompt)
        final_understanding = str(understanding)
        _log(
            "[polya_understand] Understanding received: "
            + final_understanding[:200] + "..."
        )
        phase_results.append(
            PolyaUnderstandPhaseResult("understand", cycle, final_understanding)
        )

        # --- VALIDATE PHASE ---
        _log("\\n[polya_understand] Phase 3/4: VALIDATE")
        validate_prompt = build_validate_prompt(
            objective_text,
            project_name,
            final_understanding,
            inventory_memos,
            cycle,
        )
        _log(
            "[polya_understand] Dispatching validate child (prompt_len="
            + str(len(validate_prompt)) + ")"
        )
        validation = llm_query(validate_prompt)
        final_validation = str(validation)
        final_retrieval_order = extract_retrieval_order(
            final_validation, max_items=max_retrievals
        )
        _log(
            "[polya_understand] Validation received with "
            + str(len(final_retrieval_order)) + " retrieval candidate(s)"
        )
        phase_results.append(
            PolyaUnderstandPhaseResult("validate", cycle, final_validation)
        )

        # --- REFLECT PHASE ---
        _log("\\n[polya_understand] Phase 4/4: REFLECT")
        reflect_prompt = build_reflect_prompt(
            objective_text,
            project_name,
            final_understanding,
            final_validation,
            cycle,
            prior_reflection,
        )
        _log(
            "[polya_understand] Dispatching reflect child (prompt_len="
            + str(len(reflect_prompt)) + ")"
        )
        reflection = llm_query(reflect_prompt)
        final_reflection = str(reflection)
        revised_order = extract_retrieval_order(
            final_reflection, max_items=max_retrievals
        )
        if revised_order:
            final_retrieval_order = revised_order
        _log(
            "[polya_understand] Reflection received: "
            + final_reflection[:200] + "..."
        )
        phase_results.append(
            PolyaUnderstandPhaseResult("reflect", cycle, final_reflection)
        )
        prior_reflection = final_reflection

        if "VERDICT: COMPLETE" in final_reflection.upper():
            _log(
                "[polya_understand] Reflection verdict COMPLETE with "
                + str(len(final_retrieval_order)) + " retrieval candidate(s)"
            )
            return PolyaUnderstandResult(
                project_name=project_name,
                objective=objective_text,
                understanding=final_understanding,
                validation=final_validation,
                retrieval_order=final_retrieval_order,
                cycles_completed=cycle,
                phase_results=phase_results,
                final_reflection=final_reflection,
                debug_log=debug_log,
            )

        _log("[polya_understand] Reflection verdict CONTINUE")

    _log(
        "[polya_understand] Max cycles reached with "
        + str(len(final_retrieval_order)) + " retrieval candidate(s)"
    )
    return PolyaUnderstandResult(
        project_name=project_name,
        objective=objective_text,
        understanding=final_understanding,
        validation=final_validation,
        retrieval_order=final_retrieval_order,
        cycles_completed=max_cycles,
        phase_results=phase_results,
        final_reflection=final_reflection,
        debug_log=debug_log,
    )\
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_INVENTORY_INSTRUCTIONS",
        source=_POLYA_INVENTORY_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_UNDERSTAND_SYNTHESIS_INSTRUCTIONS",
        source=_POLYA_UNDERSTAND_SYNTHESIS_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_VALIDATE_INSTRUCTIONS",
        source=_POLYA_VALIDATE_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_REFLECT_INSTRUCTIONS",
        source=_POLYA_REFLECT_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="PolyaUnderstandPhaseResult",
        source=_POLYA_UNDERSTAND_PHASE_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="stringify_context",
        source=_STRINGIFY_CONTEXT_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="chunk_text",
        source=_CHUNK_TEXT_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="condense_packets",
        source=_CONDENSE_PACKETS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="prepare_context_packets",
        source=_PREPARE_CONTEXT_PACKETS_SRC,
        requires=["stringify_context", "chunk_text", "condense_packets"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="extract_marker_value",
        source=_EXTRACT_MARKER_VALUE_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="extract_retrieval_order",
        source=_EXTRACT_RETRIEVAL_ORDER_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="PolyaUnderstandResult",
        source=_POLYA_UNDERSTAND_RESULT_SRC,
        requires=["extract_marker_value"],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_inventory_prompt",
        source=_BUILD_INVENTORY_PROMPT_SRC,
        requires=["POLYA_INVENTORY_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_understand_prompt",
        source=_BUILD_UNDERSTAND_PROMPT_SRC,
        requires=["POLYA_UNDERSTAND_SYNTHESIS_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_validate_prompt",
        source=_BUILD_VALIDATE_PROMPT_SRC,
        requires=["POLYA_VALIDATE_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_reflect_prompt",
        source=_BUILD_REFLECT_PROMPT_SRC,
        requires=["POLYA_REFLECT_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="run_polya_understand",
        source=_RUN_POLYA_UNDERSTAND_SRC,
        requires=[
            "PolyaUnderstandPhaseResult",
            "PolyaUnderstandResult",
            "prepare_context_packets",
            "extract_retrieval_order",
            "build_inventory_prompt",
            "build_understand_prompt",
            "build_validate_prompt",
            "build_reflect_prompt",
        ],
        kind="function",
    )
)
