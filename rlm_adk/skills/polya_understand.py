"""ADK Skill definition + source-expandable REPL exports: Polya understand loop.

Defines ``POLYA_UNDERSTAND_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_polya_understand_skill_instruction_block()`` which returns the
XML discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand import run_polya_understand`` expands
into inline source before the AST rewriter runs.

The loop is designed for large or incomplete project contexts.  The parent
(layer 0 reasoning agent) acts as a **reframer** that transforms the user's
objective into structured Polya probing questions dispatched to children:

  1. REFRAME: Transform the objective into Polya-structured probing questions
  2. PROBE: Dispatch probing questions via llm_query_batched() to children
  3. SYNTHESIZE: Collect structured responses and build composite understanding
  4. VALIDATE: Judge whether composite understanding is sufficient to proceed
  5. REFLECT: Critique the validation, repair ordering, decide COMPLETE/CONTINUE
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
            "contexts. Reframes the objective into structured probing questions, "
            "dispatches them to children via llm_query_batched(), synthesizes "
            "a composite understanding, identifies missing prerequisites, and "
            "emits an ordered retrieval plan with halt guidance before planning "
            "or implementation."
        ),
    ),
    instructions=textwrap.dedent("""\
## polya-understand -- Context Validation and Retrieval Planning

Use this source-expandable REPL skill when a project is large, messy, or
missing key context. It runs a Polya-style understanding loop that reframes
the objective into structured probing questions, dispatches them to children,
synthesizes the actual task, checks whether the problem is well-posed, and
emits a concrete retrieval order for missing prerequisites.

This is the preferred skill for **big projects** or **new projects with
uncertain surrounding context**. Use it before planning or implementation.

### Usage

```repl
from rlm_repl_skills.polya_understand import run_polya_understand
result = run_polya_understand(
    objective="Understand this project before planning any implementation work.",
    project_context=user_ctx,
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
  filename-to-content mapping (typically ``user_ctx``).
- ``project_name`` (str, default ``"project"``): Friendly label used in prompts.
- ``max_cycles`` (int, default 2): Maximum reframe-probe-synthesize-validate-
  reflect cycles.
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

Each cycle runs five phases:

1. **REFRAME** -- The parent transforms the user's raw objective into a set
   of Polya-structured probing questions.  Each question targets a specific
   dimension: restatement, givens, unknowns, assumptions, constraints,
   well-posedness, problem type, boundaries, and success criteria.  The
   parent sees only the **manifest** (file list + sizes), never raw context.

2. **PROBE** -- ``llm_query_batched()`` dispatches the probing questions to
   children, where each child receives one probing question plus a relevant
   chunk of the project context and returns a structured response for that
   specific Polya dimension.

3. **SYNTHESIZE** -- ``llm_query()`` collects structured probe responses and
   builds a composite understanding artifact.  Identifies which dimensions
   are well-covered and which have gaps.

4. **VALIDATE** -- ``llm_query()`` judges whether the composite understanding
   is sufficient to proceed to planning, or whether specific retrievals are
   needed.

5. **REFLECT** -- ``llm_query()`` critiques the validation for
   generic/hallucinated retrievals, repairs ordering, and decides
   ``COMPLETE`` or ``CONTINUE``.

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
# Constants: Polya dimension definitions
# ---------------------------------------------------------------------------

_POLYA_DIMENSIONS_SRC = """\
POLYA_DIMENSIONS = [
    {
        "id": "restatement",
        "label": "Restatement",
        "question_template": (
            "Restate the following objective in precise operational terms. "
            "What specific deliverable is being requested? Strip away "
            "ambiguity and produce a one-to-two sentence reformulation "
            "that exposes the core demand. "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "givens",
        "label": "Givens Inventory",
        "question_template": (
            "What documents, data, facts, definitions, conditions, and "
            "constraints are explicitly provided in this context? List each "
            "given with its source location. Separate into categories: "
            "DATA, RULES, CONSTRAINTS, CONTEXT. "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "unknowns",
        "label": "Unknowns & Relationships",
        "question_template": (
            "What information is needed to complete this task that is NOT "
            "present in the provided context? Be specific -- name the "
            "document, credential, data source, or attestation. For each "
            "unknown, describe its relationship to the known givens and "
            "identify any intermediate quantities or chain dependencies. "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "assumptions",
        "label": "Facts vs Assumptions",
        "question_template": (
            "What assumptions are being made that are NOT explicitly stated "
            "in the context? Separate confirmed facts from assumed "
            "conditions. For each assumption, classify it as SAFE (typical "
            "and unlikely to derail) or DANGEROUS (could invalidate the "
            "solution if wrong). "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "constraints",
        "label": "Constraints & Success Criteria",
        "question_template": (
            "What regulatory, procedural, technical, resource, or domain "
            "constraints govern this task? What limits apply? What methods "
            "are forbidden or preferred? What precision is required? What "
            "would make a solution invalid even if it looks correct? Define "
            "concrete pass/fail success criteria. "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "well_posedness",
        "label": "Well-Posedness",
        "question_template": (
            "Is this problem solvable with the available information? Is "
            "there enough information to determine a unique solution? Could "
            "multiple answers satisfy the statement? Is there missing data, "
            "contradictory conditions, or is the problem impossible as "
            "stated? Classify as: WELL_POSED, AMBIGUOUS, UNDERDETERMINED, "
            "INCONSISTENT, or IMPOSSIBLE. If not well-posed, what specific "
            "retrievals are needed and in what dependency order? "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "definitions",
        "label": "Term Clarification",
        "question_template": (
            "Identify all technical terms, overloaded words, and ambiguous "
            "phrases in the objective and context. For each, provide a "
            "precise definition or interpretation. Flag any terms where the "
            "meaning materially affects the solution path. "
            "OBJECTIVE: {objective}"
        ),
    },
    {
        "id": "problem_type",
        "label": "Problem Type & Boundaries",
        "question_template": (
            "What kind of problem is this structurally? Is it a search, "
            "proof, optimization, classification, inversion, diagnosis, "
            "design, or decomposition problem? Does it resemble a known "
            "template? Define what is in scope and what is out of scope. "
            "What is the boundary of the problem? "
            "OBJECTIVE: {objective}"
        ),
    },
]\
"""

# ---------------------------------------------------------------------------
# Constants: Phase instructions
# ---------------------------------------------------------------------------

_POLYA_REFRAME_INSTRUCTIONS_SRC = """\
POLYA_REFRAME_INSTRUCTIONS = (
    "You are executing the REFRAME phase of a Polya understand loop. "
    "You will transform a user objective into structured probing questions. "
    "You receive ONLY a manifest (file list with sizes) -- NOT the raw context. "
    "For each Polya dimension provided, generate a targeted probing question "
    "that a child agent can answer given a chunk of project context. "
    "Each question must be specific to the objective and dimension. "
    "Do not answer the questions yourself. Do not hallucinate file contents. "
    "Return a numbered list with one question per dimension, using the format: "
    "DIMENSION_ID: <question text>"
)\
"""

_POLYA_PROBE_INSTRUCTIONS_SRC = """\
POLYA_PROBE_INSTRUCTIONS = (
    "You are executing the PROBE phase of a Polya understand loop. "
    "You will inspect one chunk of project context and answer a specific "
    "Polya probing question using ONLY evidence found in the provided context. "
    "Do not hallucinate information that is not in the context. "
    "If the context does not contain relevant information for the question, "
    "explicitly state that the dimension has a GAP. "
    "Return a structured response with these headings exactly: "
    "DIMENSION, EVIDENCE, GAPS, CONFIDENCE."
)\
"""

_POLYA_SYNTHESIZE_INSTRUCTIONS_SRC = """\
POLYA_SYNTHESIZE_INSTRUCTIONS = (
    "You are executing the SYNTHESIZE phase of a Polya understand loop. "
    "Combine the structured probe responses into a single composite "
    "understanding artifact. For each Polya dimension, summarize the "
    "evidence collected and note which dimensions are well-covered vs "
    "which have gaps. "
    "Build the operational understanding artifact with headings exactly: "
    "RESTATEMENT, OBJECTIVE, GIVENS, UNKNOWNS, RELATIONSHIPS, "
    "DEFINITIONS, CONSTRAINTS, FACTS_VS_ASSUMPTIONS, REPRESENTATION, "
    "PROBLEM_TYPE, BOUNDARIES, SUCCESS_CRITERIA, COVERAGE_ASSESSMENT."
)\
"""

_POLYA_VALIDATE_INSTRUCTIONS_SRC = """\
POLYA_VALIDATE_INSTRUCTIONS = (
    "You are executing the VALIDATE phase of a Polya understand loop. "
    "Judge whether the problem is well-posed using the understanding artifact "
    "and the probe responses. Focus on insufficiency detection rather than "
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
"""

_POLYA_REFLECT_INSTRUCTIONS_SRC = """\
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
"""

# ---------------------------------------------------------------------------
# Result classes
# ---------------------------------------------------------------------------

_POLYA_UNDERSTAND_PHASE_RESULT_SRC = """\
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
"""

_POLYA_UNDERSTAND_RESULT_SRC = """\
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
"""

# ---------------------------------------------------------------------------
# Helpers: context preparation, manifest building, and extraction
# ---------------------------------------------------------------------------

_STRINGIFY_CONTEXT_SRC = """\
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
"""

_CHUNK_TEXT_SRC = """\
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
"""

_CONDENSE_PACKETS_SRC = """\
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
"""

_PREPARE_CONTEXT_PACKETS_SRC = """\
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
"""

_BUILD_CONTEXT_MANIFEST_SRC = '''\
def build_context_manifest(project_context):
    """Build a lightweight manifest (file list + sizes) from project_context.

    The parent reframer sees ONLY this manifest, never raw context.
    Children see the actual context packets during PROBE.
    """
    lines = []
    if isinstance(project_context, dict):
        keys = sorted(project_context.keys(), key=lambda item: str(item))
        for key in keys:
            content = project_context[key]
            size = len(str(content)) if content else 0
            lines.append("  - " + str(key) + " (" + str(size) + " chars)")
    elif isinstance(project_context, (list, tuple)):
        for idx, item in enumerate(project_context):
            size = len(str(item)) if item else 0
            lines.append("  - packet_" + str(idx + 1) + " (" + str(size) + " chars)")
    else:
        text = str(project_context or "")
        lines.append("  - raw_context (" + str(len(text)) + " chars)")
    header = "PROJECT CONTEXT MANIFEST (" + str(len(lines)) + " items):"
    return header + "\\n" + "\\n".join(lines)\
'''

_EXTRACT_MARKER_VALUE_SRC = """\
def extract_marker_value(text, marker):
    prefix = marker.upper() + ":"
    for line in str(text or "").split("\\n"):
        stripped = line.strip()
        if stripped.upper().startswith(prefix):
            return stripped[len(marker) + 1:].strip()
    return ""\
"""

_EXTRACT_RETRIEVAL_ORDER_SRC = """\
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
"""

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_BUILD_REFRAME_PROMPT_SRC = '''\
def build_reframe_prompt(
    objective,
    project_name,
    manifest,
    dimensions,
    cycle_num,
    prior_reflection=None,
):
    """Build the REFRAME prompt for the parent reframer.

    The parent sees only the manifest (file list + sizes), never raw context.
    It generates targeted probing questions for each Polya dimension.
    """
    parts = [POLYA_REFRAME_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    if prior_reflection:
        parts.append("\\n\\nPRIOR_REFLECTION:\\n" + prior_reflection)
    parts.append("\\n\\nCONTEXT_MANIFEST:\\n" + manifest)
    parts.append("\\n\\nDIMENSIONS TO PROBE:")
    for dim in dimensions:
        parts.append(
            "\\n- " + dim["id"].upper()
            + " (" + dim["label"] + "): "
            + dim["question_template"].format(objective=objective)
        )
    parts.append(
        "\\n\\nGenerate one targeted probing question per dimension. "
        "Format each as: DIMENSION_ID: <question>"
    )
    return "".join(parts)\
'''

_BUILD_PROBE_PROMPT_SRC = '''\
def build_probe_prompt(
    objective,
    project_name,
    probing_question,
    dimension_id,
    dimension_label,
    packet_text,
    cycle_num,
    packet_idx,
    packet_count,
):
    """Build a PROBE prompt for a single child.

    Each child receives one probing question plus one context packet.
    """
    parts = [POLYA_PROBE_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    parts.append(
        "\\nPACKET: " + str(packet_idx + 1) + "/" + str(packet_count)
    )
    parts.append("\\nDIMENSION: " + dimension_id.upper() + " (" + dimension_label + ")")
    parts.append("\\n\\nPROBING_QUESTION:\\n" + probing_question)
    parts.append("\\n\\nPROJECT_CONTEXT_PACKET:\\n" + packet_text)
    parts.append("\\n\\nReturn your structured probe response now.")
    return "".join(parts)\
'''

_BUILD_SYNTHESIZE_PROMPT_SRC = '''\
def build_synthesize_prompt(
    objective,
    project_name,
    probe_responses,
    cycle_num,
    prior_reflection=None,
):
    """Build the SYNTHESIZE prompt to combine probe responses."""
    parts = [POLYA_SYNTHESIZE_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    if prior_reflection:
        parts.append("\\n\\nPRIOR_REFLECTION:\\n" + prior_reflection)
    parts.append("\\n\\nPROBE_RESPONSES:")
    for idx, response in enumerate(probe_responses):
        parts.append("\\n\\n[PROBE " + str(idx + 1) + "]:\\n" + response)
    parts.append("\\n\\nReturn the synthesized understanding artifact now.")
    return "".join(parts)\
'''

_BUILD_VALIDATE_PROMPT_SRC = '''\
def build_validate_prompt(
    objective,
    project_name,
    understanding,
    probe_responses,
    cycle_num,
):
    """Build the VALIDATE prompt."""
    parts = [POLYA_VALIDATE_INSTRUCTIONS]
    parts.append("\\n\\nPROJECT_NAME: " + project_name)
    parts.append("\\nOBJECTIVE: " + objective)
    parts.append("\\nCYCLE: " + str(cycle_num))
    parts.append("\\n\\nUNDERSTANDING_ARTIFACT:\\n" + understanding)
    parts.append("\\n\\nSUPPORTING_PROBE_RESPONSES:")
    for idx, response in enumerate(probe_responses):
        parts.append("\\n\\n[PROBE " + str(idx + 1) + "]:\\n" + response)
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
    """Build the REFLECT prompt."""
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
# Helpers: reframe parsing and probe dispatch assembly
# ---------------------------------------------------------------------------

_PARSE_REFRAMED_QUESTIONS_SRC = '''\
def parse_reframed_questions(reframe_output, dimensions):
    """Parse DIMENSION_ID: <question> lines from reframe output.

    Returns a dict mapping dimension_id -> question text.
    Falls back to the dimension template if a dimension is missing.
    """
    result = {}
    dim_ids = {d["id"].upper(): d for d in dimensions}
    for line in str(reframe_output or "").split("\\n"):
        stripped = line.strip()
        if not stripped:
            continue
        for dim_upper, dim in dim_ids.items():
            prefixes = [dim_upper + ":", dim_upper + " :"]
            for prefix in prefixes:
                if stripped.upper().startswith(prefix):
                    question = stripped[len(prefix):].strip()
                    if question:
                        result[dim["id"]] = question
                    break
    # Fill missing dimensions with templates
    for dim in dimensions:
        if dim["id"] not in result:
            result[dim["id"]] = dim["question_template"]
    return result\
'''

_ASSIGN_PACKETS_TO_DIMENSIONS_SRC = '''\
def assign_packets_to_dimensions(dimensions, packets):
    """Assign context packets to dimensions for probe dispatch.

    Returns a list of (dimension, packet_text, packet_idx) tuples.
    Strategy: each dimension gets at least one packet.  If there are more
    packets than dimensions, extra packets are distributed round-robin.
    If there are more dimensions than packets, dimensions share packets.
    """
    assignments = []
    n_dims = len(dimensions)
    n_pkts = len(packets)
    if n_pkts == 0:
        for dim in dimensions:
            assignments.append((dim, "[[empty_context]]", 0))
        return assignments
    if n_pkts >= n_dims:
        # Each dimension gets at least one packet; extras distributed round-robin
        base = n_pkts // n_dims
        remainder = n_pkts % n_dims
        pkt_idx = 0
        for dim_idx, dim in enumerate(dimensions):
            count = base + (1 if dim_idx < remainder else 0)
            for offset in range(count):
                assignments.append((dim, packets[pkt_idx], pkt_idx))
                pkt_idx += 1
    else:
        # More dimensions than packets; dimensions share packets round-robin
        for dim_idx, dim in enumerate(dimensions):
            pkt_idx = dim_idx % n_pkts
            assignments.append((dim, packets[pkt_idx], pkt_idx))
    return assignments\
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

    The parent acts as a reframer: it sees only the manifest (file list +
    sizes) and transforms the objective into structured Polya probing
    questions.  Children receive the actual context packets and return
    structured probe responses.

    Args:
        objective: Concrete objective to validate before planning/execution.
        project_context: Current context blob, shards, or manifest mapping.
        project_name: Friendly label for prompt context.
        max_cycles: Maximum reframe-probe-synthesize-validate-reflect cycles.
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

    # Prepare context packets (children see these)
    packets = prepare_context_packets(
        project_context,
        max_chars_per_packet=max_chars_per_packet,
        max_packets=max_packets,
    )

    # Build manifest (parent reframer sees only this)
    manifest = build_context_manifest(project_context)

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

        # --- REFRAME PHASE (parent as reframer) ---
        _log("\\n[polya_understand] Phase 1/5: REFRAME")
        reframe_prompt = build_reframe_prompt(
            objective_text,
            project_name,
            manifest,
            POLYA_DIMENSIONS,
            cycle,
            prior_reflection,
        )
        _log(
            "[polya_understand] Dispatching reframe (prompt_len="
            + str(len(reframe_prompt)) + ")"
        )
        reframe_output = llm_query(reframe_prompt)
        reframe_text = str(reframe_output)
        _log(
            "[polya_understand] Reframe received: "
            + reframe_text[:200] + "..."
        )
        phase_results.append(
            PolyaUnderstandPhaseResult("reframe", cycle, reframe_text)
        )

        # Parse the reframed questions
        reframed_questions = parse_reframed_questions(
            reframe_text, POLYA_DIMENSIONS
        )
        _log(
            "[polya_understand] Parsed "
            + str(len(reframed_questions)) + " probing questions"
        )

        # --- PROBE PHASE (batched fanout) ---
        _log("\\n[polya_understand] Phase 2/5: PROBE")
        assignments = assign_packets_to_dimensions(
            POLYA_DIMENSIONS, packets
        )
        probe_prompts = []
        for dim, packet_text, pkt_idx in assignments:
            question = reframed_questions.get(
                dim["id"], dim["question_template"]
            )
            probe_prompts.append(
                build_probe_prompt(
                    objective_text,
                    project_name,
                    question,
                    dim["id"],
                    dim["label"],
                    packet_text,
                    cycle,
                    pkt_idx,
                    len(packets),
                )
            )
        _log(
            "[polya_understand] Dispatching " + str(len(probe_prompts))
            + " probe child(ren)"
        )
        probe_outputs = llm_query_batched(probe_prompts)
        probe_responses = [str(item) for item in probe_outputs]
        for idx, response in enumerate(probe_responses):
            _log(
                "[polya_understand] Probe response "
                + str(idx + 1) + ": " + response[:160] + "..."
            )
            phase_results.append(
                PolyaUnderstandPhaseResult("probe", cycle, response)
            )

        # --- SYNTHESIZE PHASE ---
        _log("\\n[polya_understand] Phase 3/5: SYNTHESIZE")
        synthesize_prompt = build_synthesize_prompt(
            objective_text,
            project_name,
            probe_responses,
            cycle,
            prior_reflection,
        )
        _log(
            "[polya_understand] Dispatching synthesize child (prompt_len="
            + str(len(synthesize_prompt)) + ")"
        )
        understanding = llm_query(synthesize_prompt)
        final_understanding = str(understanding)
        _log(
            "[polya_understand] Understanding received: "
            + final_understanding[:200] + "..."
        )
        phase_results.append(
            PolyaUnderstandPhaseResult("synthesize", cycle, final_understanding)
        )

        # --- VALIDATE PHASE ---
        _log("\\n[polya_understand] Phase 4/5: VALIDATE")
        validate_prompt = build_validate_prompt(
            objective_text,
            project_name,
            final_understanding,
            probe_responses,
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
        _log("\\n[polya_understand] Phase 5/5: REFLECT")
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
        name="POLYA_DIMENSIONS",
        source=_POLYA_DIMENSIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_REFRAME_INSTRUCTIONS",
        source=_POLYA_REFRAME_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_PROBE_INSTRUCTIONS",
        source=_POLYA_PROBE_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="POLYA_SYNTHESIZE_INSTRUCTIONS",
        source=_POLYA_SYNTHESIZE_INSTRUCTIONS_SRC,
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
        name="build_context_manifest",
        source=_BUILD_CONTEXT_MANIFEST_SRC,
        requires=[],
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
        name="parse_reframed_questions",
        source=_PARSE_REFRAMED_QUESTIONS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="assign_packets_to_dimensions",
        source=_ASSIGN_PACKETS_TO_DIMENSIONS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_reframe_prompt",
        source=_BUILD_REFRAME_PROMPT_SRC,
        requires=["POLYA_REFRAME_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_probe_prompt",
        source=_BUILD_PROBE_PROMPT_SRC,
        requires=["POLYA_PROBE_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.polya_understand",
        name="build_synthesize_prompt",
        source=_BUILD_SYNTHESIZE_PROMPT_SRC,
        requires=["POLYA_SYNTHESIZE_INSTRUCTIONS"],
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
            "POLYA_DIMENSIONS",
            "PolyaUnderstandPhaseResult",
            "PolyaUnderstandResult",
            "prepare_context_packets",
            "build_context_manifest",
            "extract_retrieval_order",
            "parse_reframed_questions",
            "assign_packets_to_dimensions",
            "build_reframe_prompt",
            "build_probe_prompt",
            "build_synthesize_prompt",
            "build_validate_prompt",
            "build_reflect_prompt",
        ],
        kind="function",
    )
)
