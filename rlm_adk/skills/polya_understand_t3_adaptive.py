"""ADK Skill definition + source-expandable REPL exports: T3 Dimension-Adaptive Round-Trip.

Defines ``POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL`` using ``google.adk.skills.models.Skill``
and provides ``build_polya_understand_t3_adaptive_skill_instruction_block()`` which
returns the XML discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t3_adaptive import run_polya_understand_t3_adaptive``
expands into inline source before the AST rewriter runs.

T3 Architecture (Dimension-Adaptive Round-Trip):

  L0: SELECT (llm_query) -> selects 3-5 relevant Polya dimensions
  L0: PROBE round 1 (llm_query_batched) -> one child per selected dimension
      Each gets: dimension question + context packet
      Returns: DIMENSION/EVIDENCE/GAPS/CONFIDENCE
  L0: GAP ANALYSIS (local Python) -> parse CONFIDENCE, identify low-confidence dims
  L0: RE-PROBE round 2 (llm_query_batched, conditional) -> only gap dimensions
  L0: SYNTHESIZE (llm_query) -> combine round 1 + round 2 results
"""

from __future__ import annotations

import textwrap

from google.adk.skills.models import Frontmatter, Skill
from google.adk.skills.prompt import format_skills_as_xml

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ===========================================================================
# ADK Skill definition (prompt discovery)
# ===========================================================================

POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL = Skill(
    frontmatter=Frontmatter(
        name="polya-understand-t3-adaptive",
        description=(
            "Dimension-adaptive round-trip Polya understand topology. "
            "Selects relevant dimensions, probes them with child LLMs, "
            "identifies low-confidence gaps via local Python analysis, "
            "re-probes only gap dimensions with sharpened questions, "
            "and synthesizes a composite understanding with retrieval plan."
        ),
    ),
    instructions=textwrap.dedent("""\
## polya-understand-t3-adaptive -- Dimension-Adaptive Round-Trip

Use this source-expandable REPL skill when a project is large, messy, or
missing key context. It runs a T3 dimension-adaptive round-trip topology
that selects the most relevant Polya dimensions, probes them with children,
identifies low-confidence gaps via local analysis, re-probes only the gaps,
and synthesizes a composite understanding.

This topology is more efficient than the full iterative loop (T1) because
it selects only relevant dimensions and adaptively re-probes only gaps.

### Usage

```repl
from rlm_repl_skills.polya_understand_t3_adaptive import run_polya_understand_t3_adaptive
result = run_polya_understand_t3_adaptive(
    objective="Understand this project before planning any implementation work.",
    project_context=user_ctx,
    project_name="example-project",
)
print(result)
print(result.retrieval_order)
print(result.gaps_detected)
```

### Parameters

- ``objective`` (str): The concrete objective you are trying to understand.
- ``project_context`` (str | list | dict): The currently available context.
  Can be a packed repo XML string, repomix shards, notes, manifests, or a
  filename-to-content mapping (typically ``user_ctx``).
- ``project_name`` (str, default ``"project"``): Friendly label used in prompts.
- ``num_dimensions`` (int, default 5): How many dimensions to select (3-8).
- ``confidence_threshold`` (str, default ``"MEDIUM"``): Re-probe dimensions
  below this confidence level (LOW, MEDIUM, HIGH).
- ``max_chars_per_packet`` (int, default 12000): Chunk size for large context.
- ``max_packets`` (int, default 10): Caps how many packets are analyzed after
  chunking/merging.
- ``max_retrievals`` (int, default 8): Caps extracted retrieval-order items.
- ``emit_debug`` (bool, default True): Print debug logs to stdout.

### Return Value

``T3AdaptiveResult`` with attributes:
- ``.understanding``: The synthesized understand-phase artifact.
- ``.selected_dimensions``: List of dimension IDs selected by the SELECT phase.
- ``.round1_results``: List of ``T3ProbeResult`` from round 1.
- ``.round2_results``: List of ``T3ProbeResult`` from round 2 (may be empty).
- ``.gaps_detected``: List of dimension IDs that had low confidence.
- ``.retrieval_order``: Ordered list of missing prerequisite artifact names.
- ``.cycles_completed``: Number of probe rounds that ran (1 or 2).
- ``.debug_log``: List of debug messages.

### How It Works

1. **SELECT** -- ``llm_query()`` selects the 3-5 most relevant Polya
   dimensions given the objective and context manifest.

2. **PROBE round 1** -- ``llm_query_batched()`` dispatches one child per
   selected dimension with a context packet.  Each child returns structured
   DIMENSION/EVIDENCE/GAPS/CONFIDENCE.

3. **GAP ANALYSIS** -- Local Python parses CONFIDENCE from each probe
   response and identifies dimensions below the confidence threshold.

4. **RE-PROBE round 2** (conditional) -- ``llm_query_batched()`` re-probes
   only the gap dimensions with different context packets and sharpened
   questions.

5. **SYNTHESIZE** -- ``llm_query()`` combines round 1 + round 2 results
   into a composite understanding with retrieval plan.

### Example: Run Against a Large Repo

```repl
info = probe_repo("/path/to/project")
if info.total_tokens < 125_000:
    project_context = pack_repo("/path/to/project")
else:
    project_context = shard_repo("/path/to/project").chunks

from rlm_repl_skills.polya_understand_t3_adaptive import run_polya_understand_t3_adaptive
result = run_polya_understand_t3_adaptive(
    objective="Validate whether I have enough context to safely modify this codebase.",
    project_context=project_context,
    project_name="project",
    num_dimensions=4,
    confidence_threshold="MEDIUM",
)
print(result.understanding)
print(result.gaps_detected)
print(result.retrieval_order)
```

After receiving the result, either:
- retrieve missing items from the retrieval plan if gaps remain, or
- continue into planning/implementation if the understanding is sufficient.
"""),
)


def build_polya_understand_t3_adaptive_skill_instruction_block() -> str:
    """Return the skill discovery XML + full instructions for prompt injection."""
    discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL.instructions}"


# ===========================================================================
# Source-expandable REPL exports (side-effect registration at import time)
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants: Polya dimension definitions (self-contained copy)
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
# Constants: T3-specific phase instructions
# ---------------------------------------------------------------------------

_T3_SELECT_INSTRUCTIONS_SRC = """\
T3_SELECT_INSTRUCTIONS = (
    "You are executing the SELECT phase of a T3 dimension-adaptive Polya "
    "understand topology. Given the user's objective and a manifest of "
    "available context, select the most relevant Polya dimensions to probe. "
    "You must select between 3 and 8 dimensions. Prefer dimensions that are "
    "most likely to reveal gaps or ambiguities for this specific objective. "
    "Return your selection as a list of SELECTED: lines, one per dimension. "
    "Format: SELECTED: <dimension_id>"
)\
"""

_T3_PROBE_INSTRUCTIONS_SRC = """\
T3_PROBE_INSTRUCTIONS = (
    "You are executing the PROBE phase of a T3 dimension-adaptive Polya "
    "understand topology. You will inspect one chunk of project context and "
    "answer a specific Polya probing question using ONLY evidence found in "
    "the provided context. Do not hallucinate information that is not in the "
    "context. Return a structured response with these headings exactly: "
    "DIMENSION: <dimension_id>\\n"
    "EVIDENCE: <what you found>\\n"
    "GAPS: <what is missing or unclear>\\n"
    "CONFIDENCE: LOW|MEDIUM|HIGH"
)\
"""

# ---------------------------------------------------------------------------
# Result classes
# ---------------------------------------------------------------------------

_T3_PROBE_RESULT_SRC = """\
class T3ProbeResult:
    def __init__(self, dimension, evidence, gaps, confidence, raw_response):
        self.dimension = dimension
        self.evidence = evidence
        self.gaps = gaps
        self.confidence = confidence
        self.raw_response = raw_response

    def __repr__(self):
        return (
            "T3ProbeResult(dimension=" + repr(self.dimension)
            + ", confidence=" + repr(self.confidence)
            + ", evidence_len=" + str(len(self.evidence))
            + ", gaps_len=" + str(len(self.gaps)) + ")"
        )\
"""

_T3_ADAPTIVE_RESULT_SRC = """\
class T3AdaptiveResult:
    def __init__(
        self,
        understanding,
        selected_dimensions,
        round1_results,
        round2_results,
        gaps_detected,
        retrieval_order,
        cycles_completed,
        debug_log=None,
    ):
        self.understanding = understanding
        self.selected_dimensions = selected_dimensions
        self.round1_results = round1_results
        self.round2_results = round2_results
        self.gaps_detected = gaps_detected
        self.retrieval_order = retrieval_order
        self.cycles_completed = cycles_completed
        self.debug_log = debug_log or []

    def __repr__(self):
        return (
            "T3AdaptiveResult(dims=" + str(len(self.selected_dimensions))
            + ", gaps=" + str(len(self.gaps_detected))
            + ", cycles=" + str(self.cycles_completed)
            + ", retrievals=" + str(len(self.retrieval_order)) + ")"
        )\
"""

# ---------------------------------------------------------------------------
# Helpers: context preparation, manifest building, and extraction
# (self-contained copies from v1 for independence)
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

    The parent sees ONLY this manifest, never raw context.
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

# ---------------------------------------------------------------------------
# T3-specific helpers
# ---------------------------------------------------------------------------

_ASSIGN_PACKETS_TO_DIMENSIONS_SRC = '''\
def assign_packets_to_dimensions(dimensions, packets):
    """Assign context packets to dimensions round-robin.

    Returns a list of (dimension, packet_text, packet_idx) tuples.
    Each dimension gets at least one packet.  If there are more
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
        base = n_pkts // n_dims
        remainder = n_pkts % n_dims
        pkt_idx = 0
        for dim_idx, dim in enumerate(dimensions):
            count = base + (1 if dim_idx < remainder else 0)
            for offset in range(count):
                assignments.append((dim, packets[pkt_idx], pkt_idx))
                pkt_idx += 1
    else:
        for dim_idx, dim in enumerate(dimensions):
            pkt_idx = dim_idx % n_pkts
            assignments.append((dim, packets[pkt_idx], pkt_idx))
    return assignments\
'''

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

_BUILD_SELECT_PROMPT_SRC = '''\
def build_select_prompt(objective, manifest, dimensions, num_dimensions=5):
    """Build the SELECT prompt to choose relevant dimensions.

    The parent sees only the manifest (file list + sizes), never raw context.
    It selects the most relevant Polya dimensions for the given objective.
    """
    parts = [T3_SELECT_INSTRUCTIONS]
    parts.append("\\n\\nOBJECTIVE: " + objective)
    parts.append("\\n\\nCONTEXT_MANIFEST:\\n" + manifest)
    parts.append("\\n\\nAVAILABLE DIMENSIONS:")
    for dim in dimensions:
        parts.append(
            "\\n- " + dim["id"].upper()
            + " (" + dim["label"] + "): "
            + dim["question_template"].format(objective=objective)
        )
    parts.append(
        "\\n\\nSelect " + str(num_dimensions)
        + " dimensions that are most relevant to this objective. "
        "Return one SELECTED: <dimension_id> line per selection."
    )
    return "".join(parts)\
'''

_PARSE_SELECTED_DIMENSIONS_SRC = '''\
def parse_selected_dimensions(select_output, dimensions):
    """Parse SELECTED: lines from SELECT phase output.

    Returns a list of dimension dicts for the selected IDs.
    Falls back to all dimensions if parsing fails or returns empty.
    """
    dim_by_id = {d["id"].lower(): d for d in dimensions}
    selected = []
    seen = set()
    for line in str(select_output or "").split("\\n"):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("SELECTED:"):
            dim_id = stripped.split(":", 1)[1].strip().lower()
            if dim_id in dim_by_id and dim_id not in seen:
                selected.append(dim_by_id[dim_id])
                seen.add(dim_id)
    if not selected:
        return list(dimensions)
    return selected\
'''

_BUILD_PROBE_PROMPT_SRC = '''\
def build_probe_prompt(dimension, question, context_packet):
    """Build a PROBE prompt for a single child.

    Each child receives one dimension question plus one context packet.
    """
    parts = [T3_PROBE_INSTRUCTIONS]
    parts.append("\\n\\nDIMENSION: " + dimension["id"].upper() + " (" + dimension["label"] + ")")
    parts.append("\\n\\nPROBING_QUESTION:\\n" + question)
    parts.append("\\n\\nPROJECT_CONTEXT_PACKET:\\n" + context_packet)
    parts.append("\\n\\nReturn your structured probe response now.")
    return "".join(parts)\
'''

_PARSE_PROBE_RESPONSE_SRC = '''\
def parse_probe_response(response_text):
    """Parse a structured probe response into a T3ProbeResult.

    Expects headings: DIMENSION, EVIDENCE, GAPS, CONFIDENCE.
    Missing CONFIDENCE defaults to LOW.
    """
    text = str(response_text or "")
    sections = {"DIMENSION": "", "EVIDENCE": "", "GAPS": "", "CONFIDENCE": "LOW"}
    current_key = None
    current_lines = []

    for line in text.split("\\n"):
        stripped = line.strip()
        upper = stripped.upper()
        matched = False
        for key in ("DIMENSION", "EVIDENCE", "GAPS", "CONFIDENCE"):
            if upper.startswith(key + ":"):
                if current_key is not None:
                    value = "\\n".join(current_lines).strip()
                    if value:
                        sections[current_key] = value
                current_key = key
                current_lines = [stripped.split(":", 1)[1].strip()]
                matched = True
                break
        if not matched and current_key is not None:
            current_lines.append(stripped)

    if current_key is not None:
        value = "\\n".join(current_lines).strip()
        if value:
            sections[current_key] = value

    confidence = sections["CONFIDENCE"].upper().strip()
    if confidence not in ("LOW", "MEDIUM", "HIGH"):
        confidence = "LOW"

    return T3ProbeResult(
        dimension=sections["DIMENSION"],
        evidence=sections["EVIDENCE"],
        gaps=sections["GAPS"],
        confidence=confidence,
        raw_response=text,
    )\
'''

_IDENTIFY_GAPS_SRC = """\
def identify_gaps(probe_results, confidence_threshold="MEDIUM"):
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    threshold_rank = rank.get(confidence_threshold.upper(), 1)
    gaps = []
    for r in probe_results:
        conf = r.confidence.upper() if hasattr(r, "confidence") else "LOW"
        if rank.get(conf, 0) < threshold_rank:
            gaps.append(r.dimension)
    return gaps\
"""

_BUILD_REPROBE_PROMPT_SRC = '''\
def build_reprobe_prompt(dimension, original_gaps, new_packet):
    """Build a round-2 re-probe prompt for a gap dimension.

    Sharpens the question by including the original gaps found in round 1.
    """
    parts = [T3_PROBE_INSTRUCTIONS]
    parts.append("\\n\\n[ROUND 2 RE-PROBE]")
    parts.append("\\n\\nDIMENSION: " + dimension["id"].upper() + " (" + dimension["label"] + ")")
    parts.append("\\n\\nORIGINAL_GAPS_FROM_ROUND_1:\\n" + original_gaps)
    parts.append(
        "\\n\\nFocus specifically on the gaps identified above. "
        "Search the new context packet for evidence that addresses these gaps."
    )
    parts.append("\\n\\nNEW_CONTEXT_PACKET:\\n" + new_packet)
    parts.append("\\n\\nReturn your structured probe response now.")
    return "".join(parts)\
'''

_BUILD_SYNTHESIS_PROMPT_SRC = '''\
def build_synthesis_prompt(objective, round1_results, round2_results=None):
    """Build the SYNTHESIZE prompt to combine round 1 + round 2 results.

    Produces a composite understanding with headings:
    RESTATEMENT, OBJECTIVE, GIVENS, UNKNOWNS, RELATIONSHIPS,
    DEFINITIONS, CONSTRAINTS, FACTS_VS_ASSUMPTIONS, REPRESENTATION,
    PROBLEM_TYPE, BOUNDARIES, SUCCESS_CRITERIA, COVERAGE_ASSESSMENT,
    RETRIEVAL_ORDER.
    """
    parts = [
        "You are executing the SYNTHESIZE phase of a T3 dimension-adaptive "
        "Polya understand topology. Combine the structured probe responses "
        "from round 1 (and round 2 if present) into a single composite "
        "understanding artifact."
    ]
    parts.append("\\n\\nOBJECTIVE: " + objective)
    parts.append("\\n\\nROUND 1 PROBE RESULTS:")
    for idx, r in enumerate(round1_results):
        parts.append(
            "\\n\\n[PROBE R1." + str(idx + 1) + " - " + r.dimension + "]:"
            + "\\nEVIDENCE: " + r.evidence
            + "\\nGAPS: " + r.gaps
            + "\\nCONFIDENCE: " + r.confidence
        )
    if round2_results:
        parts.append("\\n\\nROUND 2 RE-PROBE RESULTS (gap dimensions):")
        for idx, r in enumerate(round2_results):
            parts.append(
                "\\n\\n[PROBE R2." + str(idx + 1) + " - " + r.dimension + "]:"
                + "\\nEVIDENCE: " + r.evidence
                + "\\nGAPS: " + r.gaps
                + "\\nCONFIDENCE: " + r.confidence
            )
    parts.append(
        "\\n\\nBuild the composite understanding artifact with these headings: "
        "RESTATEMENT, OBJECTIVE, GIVENS, UNKNOWNS, RELATIONSHIPS, "
        "DEFINITIONS, CONSTRAINTS, FACTS_VS_ASSUMPTIONS, REPRESENTATION, "
        "PROBLEM_TYPE, BOUNDARIES, SUCCESS_CRITERIA, COVERAGE_ASSESSMENT."
    )
    parts.append(
        "\\n\\nFinally, emit a RETRIEVAL_ORDER: section listing any missing "
        "prerequisite artifacts in dependency order, or RETRIEVAL_ORDER: NONE "
        "if the understanding is complete."
    )
    parts.append("\\n\\nReturn the synthesized understanding artifact now.")
    return "".join(parts)\
'''

# ---------------------------------------------------------------------------
# Main orchestrator function
# ---------------------------------------------------------------------------

_RUN_POLYA_UNDERSTAND_T3_ADAPTIVE_SRC = '''\
def run_polya_understand_t3_adaptive(
    objective,
    project_context,
    project_name="project",
    num_dimensions=5,
    confidence_threshold="MEDIUM",
    max_chars_per_packet=12000,
    max_packets=10,
    max_retrievals=8,
    emit_debug=True,
):
    """Run the T3 dimension-adaptive round-trip Polya understand topology.

    Args:
        objective: Concrete objective to validate before planning/execution.
        project_context: Current context blob, shards, or manifest mapping.
        project_name: Friendly label for prompt context.
        num_dimensions: How many dimensions to select (3-8).
        confidence_threshold: Re-probe dimensions below this level.
        max_chars_per_packet: Packet size for chunking large context.
        max_packets: Maximum packet count after chunking/merging.
        max_retrievals: Maximum retrieval-order items to extract.
        emit_debug: Whether to print debug logs.

    Returns:
        T3AdaptiveResult with the synthesized understanding and
        ordered missing-context retrieval plan.
    """
    debug_log = []
    objective_text = (
        str(objective).strip()
        if str(objective).strip()
        else "Validate whether the current project context is sufficient to proceed."
    )

    def _log(msg):
        if emit_debug:
            print(msg)
        debug_log.append(msg)

    # Prepare context packets (children see these)
    packets = prepare_context_packets(
        project_context,
        max_chars_per_packet=max_chars_per_packet,
        max_packets=max_packets,
    )

    # Build manifest (SELECT phase sees only this)
    manifest = build_context_manifest(project_context)

    _log(
        "[t3_adaptive] Starting T3 adaptive understand for "
        + project_name + " with " + str(len(packets)) + " packet(s)"
    )

    # --- SELECT PHASE ---
    _log("\\n[t3_adaptive] Phase 1: SELECT dimensions")
    select_prompt = build_select_prompt(
        objective_text, manifest, POLYA_DIMENSIONS, num_dimensions
    )
    _log(
        "[t3_adaptive] Dispatching SELECT (prompt_len="
        + str(len(select_prompt)) + ")"
    )
    select_output = llm_query(select_prompt)
    selected = parse_selected_dimensions(str(select_output), POLYA_DIMENSIONS)
    selected_ids = [d["id"] for d in selected]
    _log(
        "[t3_adaptive] Selected " + str(len(selected))
        + " dimensions: " + str(selected_ids)
    )

    # --- PROBE ROUND 1 ---
    _log("\\n[t3_adaptive] Phase 2: PROBE round 1")
    assignments = assign_packets_to_dimensions(selected, packets)
    probe_prompts = []
    for dim, packet_text, pkt_idx in assignments:
        question = dim["question_template"].format(objective=objective_text)
        probe_prompts.append(
            build_probe_prompt(dim, question, packet_text)
        )
    _log(
        "[t3_adaptive] Dispatching " + str(len(probe_prompts))
        + " round-1 probe(s)"
    )
    probe_outputs = llm_query_batched(probe_prompts)
    round1_results = []
    for output in probe_outputs:
        result = parse_probe_response(str(output))
        round1_results.append(result)
        _log(
            "[t3_adaptive] R1 probe: dim=" + result.dimension
            + " confidence=" + result.confidence
        )

    # --- GAP ANALYSIS (local Python, no LLM) ---
    _log("\\n[t3_adaptive] Phase 3: GAP ANALYSIS (local)")
    gaps = identify_gaps(round1_results, confidence_threshold)
    _log("[t3_adaptive] Gaps detected: " + str(gaps))
    cycles_completed = 1

    # --- RE-PROBE ROUND 2 (conditional) ---
    round2_results = []
    if gaps:
        _log("\\n[t3_adaptive] Phase 4: RE-PROBE round 2 for " + str(len(gaps)) + " gap(s)")
        cycles_completed = 2
        dim_by_id = {d["id"].lower(): d for d in POLYA_DIMENSIONS}
        gap_dims = [dim_by_id[g.lower()] for g in gaps if g.lower() in dim_by_id]
        if not gap_dims:
            gap_dims = selected

        # Build round-1 gap text per dimension for sharpened re-probing
        r1_gaps_by_dim = {}
        for r in round1_results:
            dim_key = r.dimension.lower().strip()
            if dim_key not in r1_gaps_by_dim:
                r1_gaps_by_dim[dim_key] = r.gaps

        # Assign different packets for round 2 where possible
        r2_assignments = assign_packets_to_dimensions(gap_dims, packets)
        reprobe_prompts = []
        for dim, packet_text, pkt_idx in r2_assignments:
            original_gaps = r1_gaps_by_dim.get(dim["id"].lower(), "No specific gaps recorded.")
            reprobe_prompts.append(
                build_reprobe_prompt(dim, original_gaps, packet_text)
            )
        _log(
            "[t3_adaptive] Dispatching " + str(len(reprobe_prompts))
            + " round-2 re-probe(s)"
        )
        r2_outputs = llm_query_batched(reprobe_prompts)
        for output in r2_outputs:
            result = parse_probe_response(str(output))
            round2_results.append(result)
            _log(
                "[t3_adaptive] R2 probe: dim=" + result.dimension
                + " confidence=" + result.confidence
            )
    else:
        _log("[t3_adaptive] No gaps -- skipping round 2")

    # --- SYNTHESIZE ---
    _log("\\n[t3_adaptive] Phase 5: SYNTHESIZE")
    synth_prompt = build_synthesis_prompt(
        objective_text,
        round1_results,
        round2_results if round2_results else None,
    )
    _log(
        "[t3_adaptive] Dispatching SYNTHESIZE (prompt_len="
        + str(len(synth_prompt)) + ")"
    )
    understanding = str(llm_query(synth_prompt))
    _log(
        "[t3_adaptive] Understanding received: "
        + understanding[:200] + "..."
    )

    retrieval_order = extract_retrieval_order(understanding, max_items=max_retrievals)
    _log(
        "[t3_adaptive] Retrieval order: " + str(len(retrieval_order))
        + " item(s)"
    )

    return T3AdaptiveResult(
        understanding=understanding,
        selected_dimensions=selected_ids,
        round1_results=round1_results,
        round2_results=round2_results,
        gaps_detected=gaps,
        retrieval_order=retrieval_order,
        cycles_completed=cycles_completed,
        debug_log=debug_log,
    )\
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

_MODULE = "rlm_repl_skills.polya_understand_t3_adaptive"

# --- Constants ---

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="POLYA_DIMENSIONS",
        source=_POLYA_DIMENSIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T3_SELECT_INSTRUCTIONS",
        source=_T3_SELECT_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T3_PROBE_INSTRUCTIONS",
        source=_T3_PROBE_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

# --- Classes ---

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T3ProbeResult",
        source=_T3_PROBE_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T3AdaptiveResult",
        source=_T3_ADAPTIVE_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

# --- Context helpers ---

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="stringify_context",
        source=_STRINGIFY_CONTEXT_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="chunk_text",
        source=_CHUNK_TEXT_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="condense_packets",
        source=_CONDENSE_PACKETS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="prepare_context_packets",
        source=_PREPARE_CONTEXT_PACKETS_SRC,
        requires=["stringify_context", "chunk_text", "condense_packets"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_context_manifest",
        source=_BUILD_CONTEXT_MANIFEST_SRC,
        requires=[],
        kind="function",
    )
)

# --- T3-specific functions ---

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="assign_packets_to_dimensions",
        source=_ASSIGN_PACKETS_TO_DIMENSIONS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="extract_retrieval_order",
        source=_EXTRACT_RETRIEVAL_ORDER_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_select_prompt",
        source=_BUILD_SELECT_PROMPT_SRC,
        requires=["T3_SELECT_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="parse_selected_dimensions",
        source=_PARSE_SELECTED_DIMENSIONS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_probe_prompt",
        source=_BUILD_PROBE_PROMPT_SRC,
        requires=["T3_PROBE_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="parse_probe_response",
        source=_PARSE_PROBE_RESPONSE_SRC,
        requires=["T3ProbeResult"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="identify_gaps",
        source=_IDENTIFY_GAPS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_reprobe_prompt",
        source=_BUILD_REPROBE_PROMPT_SRC,
        requires=["T3_PROBE_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_synthesis_prompt",
        source=_BUILD_SYNTHESIS_PROMPT_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="run_polya_understand_t3_adaptive",
        source=_RUN_POLYA_UNDERSTAND_T3_ADAPTIVE_SRC,
        requires=[
            "POLYA_DIMENSIONS",
            "T3AdaptiveResult",
            "T3ProbeResult",
            "prepare_context_packets",
            "build_context_manifest",
            "extract_retrieval_order",
            "assign_packets_to_dimensions",
            "build_select_prompt",
            "parse_selected_dimensions",
            "build_probe_prompt",
            "parse_probe_response",
            "identify_gaps",
            "build_reprobe_prompt",
            "build_synthesis_prompt",
        ],
        kind="function",
    )
)
