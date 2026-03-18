"""ADK Skill definition + source-expandable REPL exports: Polya T4 adversarial debate.

Defines ``POLYA_UNDERSTAND_T4_DEBATE_SKILL`` using ``google.adk.skills.models.Skill``
and provides ``build_polya_understand_t4_debate_skill_instruction_block()`` which
returns the XML discovery block + usage instructions to append to the reasoning
agent's ``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t4_debate import run_polya_understand_t4_debate``
expands into inline source before the AST rewriter runs.

The T4 topology dispatches 2 advocates (optimist + critic) concurrently via
``llm_query_batched``, then 1 judge via ``llm_query``.  The judge receives
ONLY the advocate arguments, never raw context -- this is the key design
invariant that prevents the judge from anchoring on noisy context artifacts.

Flow:
  1. ADVOCATE phase: ``llm_query_batched([optimist_prompt, critic_prompt])``
  2. JUDGE phase: ``llm_query(judge_prompt)`` -- judge sees only advocate outputs
  3. Parse and return ``T4DebateResult``
"""

from __future__ import annotations

import textwrap

from google.adk.skills.models import Frontmatter, Skill
from google.adk.skills.prompt import format_skills_as_xml

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ===========================================================================
# ADK Skill definition (prompt discovery)
# ===========================================================================

POLYA_UNDERSTAND_T4_DEBATE_SKILL = Skill(
    frontmatter=Frontmatter(
        name="polya-understand-t4-debate",
        description=(
            "Adversarial debate topology for Polya understand. Dispatches an "
            "optimist and critic concurrently via llm_query_batched, then a "
            "judge via llm_query that sees ONLY the advocate arguments -- "
            "never raw context. Returns a T4DebateResult with verdict, "
            "adjudication, retrieval order, and confidence map."
        ),
    ),
    instructions=textwrap.dedent("""\
## polya-understand-t4-debate -- Adversarial Debate Context Validation

Use this source-expandable REPL skill when you need a rigorous adversarial
assessment of whether the available context is sufficient. It dispatches two
advocates (optimist + critic) concurrently, then a judge who sees ONLY their
arguments -- never the raw context -- ensuring an unbiased verdict.

### Usage

```repl
from rlm_repl_skills.polya_understand_t4_debate import run_polya_understand_t4_debate
result = run_polya_understand_t4_debate(
    objective="Determine if we have enough context to safely refactor the auth module.",
    project_context=user_ctx,
)
print(result)
print(result.verdict)
print(result.retrieval_order)
print(result.confidence_map)
```

### Parameters

- ``objective`` (str): The concrete objective you are trying to validate.
- ``project_context`` (str | list | dict): The currently available context.
  Can be a packed repo XML string, repomix shards, notes, manifests, or a
  filename-to-content mapping (typically ``user_ctx``).
- ``emit_debug`` (bool, default True): Print debug logs to stdout.

### Return Value

``T4DebateResult`` with attributes:
- ``.verdict``: ``PROCEED``, ``HALT``, or ``CONDITIONAL``.
- ``.understanding``: The judge's understanding summary.
- ``.retrieval_order``: Ordered list of missing prerequisite artifact names.
- ``.confidence_map``: Dict mapping dimension names to confidence levels.
- ``.adjudication``: The judge's reasoning for the verdict.
- ``.optimist_case``: ``T4OptimistCase`` with the optimist's arguments.
- ``.critic_case``: ``T4CriticCase`` with the critic's arguments.
- ``.debug_log``: List of debug messages.

### How It Works

1. **ADVOCATE phase** -- Two advocates run concurrently via
   ``llm_query_batched([optimist_prompt, critic_prompt])``:
   - The **optimist** argues that the context IS sufficient, identifying
     assets, links, coverage, and readiness.
   - The **critic** argues that the context is NOT sufficient, identifying
     gaps, risks, ambiguities, blockers, and retrieval needs.

2. **JUDGE phase** -- A single judge via ``llm_query(judge_prompt)``
   receives ONLY the advocate outputs (never raw context) and renders:
   - A verdict: PROCEED, HALT, or CONDITIONAL
   - An understanding summary
   - A retrieval order for missing prerequisites
   - A confidence map per dimension
   - An adjudication explaining the reasoning

### Example: Run Against a Large Repo

```repl
info = probe_repo("/path/to/project")
if info.total_tokens < 125_000:
    project_context = pack_repo("/path/to/project")
else:
    project_context = shard_repo("/path/to/project").chunks

from rlm_repl_skills.polya_understand_t4_debate import run_polya_understand_t4_debate
result = run_polya_understand_t4_debate(
    objective="Validate whether I have enough context to safely modify this codebase.",
    project_context=project_context,
)
print(result.verdict)
print(result.retrieval_order)
print(result.confidence_map)
```
"""),
)


def build_polya_understand_t4_debate_skill_instruction_block() -> str:
    """Return the skill discovery XML + full instructions for prompt injection."""
    discovery_xml = format_skills_as_xml(
        [POLYA_UNDERSTAND_T4_DEBATE_SKILL.frontmatter]
    )
    return f"\n{discovery_xml}\n{POLYA_UNDERSTAND_T4_DEBATE_SKILL.instructions}"


# ===========================================================================
# Source-expandable REPL exports (side-effect registration at import time)
# ===========================================================================

_MODULE = "rlm_repl_skills.polya_understand_t4_debate"

# ---------------------------------------------------------------------------
# Constants: Advocate + Judge instructions
# ---------------------------------------------------------------------------

_T4_OPTIMIST_INSTRUCTIONS_SRC = """\
T4_OPTIMIST_INSTRUCTIONS = (
    "You are the OPTIMIST advocate in an adversarial debate about project "
    "context sufficiency. Your job is to argue that the available context "
    "IS sufficient to proceed with the stated objective. "
    "Examine the context carefully and build the strongest possible case "
    "that the project can move forward. "
    "Identify assets (existing code, docs, configs), links between "
    "components, coverage of the problem domain, and overall readiness. "
    "Be specific -- cite concrete evidence from the context. "
    "Do NOT fabricate evidence that is not in the context. "
    "Return your response with these exact headings: "
    "ASSETS: list of useful artifacts found in context. "
    "LINKS: connections and dependencies between artifacts. "
    "COVERAGE_MAP: which aspects of the objective are covered. "
    "READINESS_CASE: your argument for why the project can proceed."
)\
"""

_T4_CRITIC_INSTRUCTIONS_SRC = """\
T4_CRITIC_INSTRUCTIONS = (
    "You are the CRITIC advocate in an adversarial debate about project "
    "context sufficiency. Your job is to argue that the available context "
    "is NOT sufficient to proceed with the stated objective. "
    "Examine the context carefully and identify every gap, risk, and "
    "ambiguity that could derail implementation. "
    "Be specific -- cite concrete missing artifacts, unclear interfaces, "
    "untested assumptions, and missing documentation. "
    "Do NOT invent problems that have no basis in the context. "
    "Return your response with these exact headings: "
    "GAPS: specific missing information or artifacts. "
    "RISKS: potential failure modes from proceeding without more context. "
    "AMBIGUITIES: unclear or contradictory information in the context. "
    "BLOCKERS: hard blockers that prevent safe implementation. "
    "RETRIEVAL_NEEDS: ordered list of artifacts needed before proceeding."
)\
"""

_T4_JUDGE_INSTRUCTIONS_SRC = """\
T4_JUDGE_INSTRUCTIONS = (
    "You are the JUDGE in an adversarial debate about project context "
    "sufficiency. You will receive arguments from an OPTIMIST (who argues "
    "the context IS sufficient) and a CRITIC (who argues it is NOT). "
    "You do NOT have access to the raw project context -- you see ONLY "
    "the advocate arguments. This is intentional: your verdict must be "
    "based on the quality of the arguments, not on anchoring to raw data. "
    "Weigh both cases fairly. Look for: "
    "(1) unsupported claims by either side, "
    "(2) concrete evidence vs vague assertions, "
    "(3) whether the critic's gaps are actually blocking vs nice-to-have. "
    "Return your response with these exact headings: "
    "VERDICT: PROCEED | HALT | CONDITIONAL "
    "UNDERSTANDING: one-paragraph summary of the project state. "
    "RETRIEVAL_ORDER: numbered list of missing artifacts in dependency "
    "order, or NONE if verdict is PROCEED. "
    "CONFIDENCE_MAP: dimension=level pairs (HIGH/MEDIUM/LOW) for each "
    "assessed dimension. "
    "ADJUDICATION: your reasoning for the verdict, citing specific "
    "arguments from each advocate."
)\
"""

# ---------------------------------------------------------------------------
# Result classes
# ---------------------------------------------------------------------------

_T4_OPTIMIST_CASE_SRC = """\
class T4OptimistCase:
    def __init__(self, assets=None, links=None, coverage_map=None, readiness_case=None, raw=None):
        self.assets = assets or ""
        self.links = links or ""
        self.coverage_map = coverage_map or ""
        self.readiness_case = readiness_case or ""
        self.raw = raw or ""

    def __repr__(self):
        return (
            "T4OptimistCase(assets_len=" + str(len(self.assets))
            + ", links_len=" + str(len(self.links))
            + ", coverage_len=" + str(len(self.coverage_map))
            + ", readiness_len=" + str(len(self.readiness_case)) + ")"
        )\
"""

_T4_CRITIC_CASE_SRC = """\
class T4CriticCase:
    def __init__(self, gaps=None, risks=None, ambiguities=None, blockers=None, retrieval_needs=None, raw=None):
        self.gaps = gaps or ""
        self.risks = risks or ""
        self.ambiguities = ambiguities or ""
        self.blockers = blockers or ""
        self.retrieval_needs = retrieval_needs or ""
        self.raw = raw or ""

    def __repr__(self):
        return (
            "T4CriticCase(gaps_len=" + str(len(self.gaps))
            + ", risks_len=" + str(len(self.risks))
            + ", ambiguities_len=" + str(len(self.ambiguities))
            + ", blockers_len=" + str(len(self.blockers)) + ")"
        )\
"""

_T4_VERDICT_SRC = """\
class T4Verdict:
    PROCEED = "PROCEED"
    HALT = "HALT"
    CONDITIONAL = "CONDITIONAL"
    UNKNOWN = "UNKNOWN"

    def __init__(self, value=None):
        upper = str(value or "").strip().upper()
        if upper == "PROCEED":
            self.value = self.PROCEED
        elif upper == "HALT":
            self.value = self.HALT
        elif upper == "CONDITIONAL":
            self.value = self.CONDITIONAL
        else:
            self.value = self.UNKNOWN

    def __repr__(self):
        return "T4Verdict(" + repr(self.value) + ")"

    def __str__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, T4Verdict):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other.upper()
        return NotImplemented\
"""

_T4_DEBATE_RESULT_SRC = """\
class T4DebateResult:
    def __init__(
        self,
        verdict,
        understanding,
        retrieval_order,
        confidence_map,
        adjudication,
        optimist_case,
        critic_case,
        debug_log=None,
    ):
        self.verdict = verdict
        self.understanding = understanding
        self.retrieval_order = retrieval_order
        self.confidence_map = confidence_map
        self.adjudication = adjudication
        self.optimist_case = optimist_case
        self.critic_case = critic_case
        self.debug_log = debug_log or []

    def __repr__(self):
        return (
            "T4DebateResult(verdict=" + repr(str(self.verdict))
            + ", retrievals=" + str(len(self.retrieval_order))
            + ", confidence_dims=" + str(len(self.confidence_map)) + ")"
        )\
"""

# ---------------------------------------------------------------------------
# Helpers: context preparation and extraction
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

_BUILD_CONTEXT_STRING_SRC = """\
def build_context_string(project_context):
    return stringify_context(project_context, "project_context")\
"""

_BUILD_CONTEXT_MANIFEST_SRC = '''\
def build_context_manifest(project_context):
    """Build a lightweight manifest (file list + sizes) from project_context."""
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

_EXTRACT_SECTION_SRC = """\
def extract_section(text, heading):
    text = str(text or "")
    heading_upper = heading.strip().upper()
    lines = text.split("\\n")
    # Check for inline value on the heading line
    for idx, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith(heading_upper + ":"):
            inline_value = stripped[len(heading_upper) + 1:].strip()
            # Check if there's multiline content below
            section_lines = []
            for subsequent in lines[idx + 1:]:
                sub_stripped = subsequent.strip()
                if not sub_stripped:
                    if section_lines:
                        break
                    continue
                sub_upper = sub_stripped.upper()
                # Stop at next heading (all-caps word followed by colon)
                is_heading = (
                    ":" in sub_stripped
                    and sub_stripped.split(":", 1)[0].replace("_", "").replace("-", "").replace(" ", "").isupper()
                    and len(sub_stripped.split(":", 1)[0].strip()) > 1
                )
                if is_heading:
                    break
                section_lines.append(subsequent.rstrip())
            if section_lines:
                if inline_value:
                    return inline_value + "\\n" + "\\n".join(section_lines)
                return "\\n".join(section_lines)
            return inline_value
    return ""\
"""

_EXTRACT_RETRIEVAL_ORDER_SRC = """\
def extract_retrieval_order(text, max_items=8):
    def _is_heading(line_stripped):
        if ":" not in line_stripped:
            return False
        prefix = line_stripped.split(":", 1)[0].strip()
        if len(prefix) < 2:
            return False
        cleaned = prefix.replace("_", "").replace("-", "").replace(" ", "")
        return cleaned.isupper() and cleaned.isalpha()

    lines = str(text or "").split("\\n")
    for header in ("RETRIEVAL_ORDER",):
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
            if _is_heading(stripped):
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

_EXTRACT_CONFIDENCE_MAP_SRC = """\
def extract_confidence_map(text):
    result = {}
    in_section = False
    for line in str(text or "").split("\\n"):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("CONFIDENCE_MAP:"):
            in_section = True
            # Check for inline key=value pairs
            inline = stripped.split(":", 1)[1].strip()
            if inline:
                for pair in inline.split(","):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        result[k.strip()] = v.strip().upper()
            continue
        if in_section:
            if not stripped:
                if result:
                    break
                continue
            if (
                ":" in stripped
                and stripped.split(":", 1)[0].replace("_", "").replace("-", "").replace(" ", "").isupper()
                and not "=" in stripped.split(":", 1)[0]
                and stripped.upper() != "CONFIDENCE_MAP:"
                and len(stripped.split(":", 1)[0].strip()) > 1
            ):
                break
            if "=" in stripped:
                candidate = stripped
                if candidate[:1] in "-*":
                    candidate = candidate[1:].strip()
                else:
                    pos = 0
                    while pos < len(candidate) and candidate[pos].isdigit():
                        pos += 1
                    if pos > 0 and pos < len(candidate) and candidate[pos] in ".)":
                        candidate = candidate[pos + 1:].strip()
                if "=" in candidate:
                    k, v = candidate.split("=", 1)
                    result[k.strip()] = v.strip().upper()
    return result\
"""

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_BUILD_OPTIMIST_PROMPT_SRC = '''\
def build_optimist_prompt(objective, context_string):
    """Build the OPTIMIST advocate prompt.

    The optimist receives the full context and argues it IS sufficient.
    """
    parts = [T4_OPTIMIST_INSTRUCTIONS]
    parts.append("\\n\\nOBJECTIVE: " + str(objective))
    parts.append("\\n\\nPROJECT_CONTEXT:\\n" + str(context_string))
    parts.append("\\n\\nBuild your optimist case now.")
    return "".join(parts)\
'''

_BUILD_CRITIC_PROMPT_SRC = '''\
def build_critic_prompt(objective, context_string):
    """Build the CRITIC advocate prompt.

    The critic receives the full context and argues it is NOT sufficient.
    """
    parts = [T4_CRITIC_INSTRUCTIONS]
    parts.append("\\n\\nOBJECTIVE: " + str(objective))
    parts.append("\\n\\nPROJECT_CONTEXT:\\n" + str(context_string))
    parts.append("\\n\\nBuild your critic case now.")
    return "".join(parts)\
'''

_BUILD_JUDGE_PROMPT_SRC = '''\
def build_judge_prompt(objective, optimist_response, critic_response):
    """Build the JUDGE prompt.

    KEY INVARIANT: The judge sees ONLY the advocate arguments, never raw
    context. This function takes exactly 3 args -- no context parameter.
    """
    parts = [T4_JUDGE_INSTRUCTIONS]
    parts.append("\\n\\nOBJECTIVE: " + str(objective))
    parts.append("\\n\\nOPTIMIST_CASE:\\n" + str(optimist_response))
    parts.append("\\n\\nCRITIC_CASE:\\n" + str(critic_response))
    parts.append("\\n\\nRender your verdict now.")
    return "".join(parts)\
'''

# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

_PARSE_OPTIMIST_RESPONSE_SRC = """\
def parse_optimist_response(response_text):
    text = str(response_text or "")
    return T4OptimistCase(
        assets=extract_section(text, "ASSETS"),
        links=extract_section(text, "LINKS"),
        coverage_map=extract_section(text, "COVERAGE_MAP"),
        readiness_case=extract_section(text, "READINESS_CASE"),
        raw=text,
    )\
"""

_PARSE_CRITIC_RESPONSE_SRC = """\
def parse_critic_response(response_text):
    text = str(response_text or "")
    return T4CriticCase(
        gaps=extract_section(text, "GAPS"),
        risks=extract_section(text, "RISKS"),
        ambiguities=extract_section(text, "AMBIGUITIES"),
        blockers=extract_section(text, "BLOCKERS"),
        retrieval_needs=extract_section(text, "RETRIEVAL_NEEDS"),
        raw=text,
    )\
"""

_PARSE_JUDGE_RESPONSE_SRC = """\
def parse_judge_response(response_text):
    text = str(response_text or "")
    verdict_str = extract_section(text, "VERDICT")
    verdict = T4Verdict(verdict_str)
    understanding = extract_section(text, "UNDERSTANDING")
    retrieval_order = extract_retrieval_order(text)
    confidence_map = extract_confidence_map(text)
    adjudication = extract_section(text, "ADJUDICATION")
    return verdict, understanding, retrieval_order, confidence_map, adjudication\
"""

# ---------------------------------------------------------------------------
# Main orchestrator function
# ---------------------------------------------------------------------------

_RUN_POLYA_UNDERSTAND_T4_DEBATE_SRC = '''\
def run_polya_understand_t4_debate(
    objective,
    project_context,
    emit_debug=True,
):
    """Run the T4 adversarial debate topology.

    Dispatches 2 advocates (optimist + critic) concurrently via
    llm_query_batched, then 1 judge via llm_query. The judge receives
    ONLY the advocate arguments, never raw context.

    Args:
        objective: Concrete objective to validate.
        project_context: Current context blob, shards, or mapping.
        emit_debug: Whether to print debug logs.

    Returns:
        T4DebateResult with the verdict and structured debate outputs.
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

    # Build context string for advocates
    context_string = build_context_string(project_context)
    _log(
        "[t4_debate] Context string length: " + str(len(context_string))
    )

    # --- ADVOCATE PHASE (batched) ---
    _log("\\n[t4_debate] === ADVOCATE PHASE ===")
    optimist_prompt = build_optimist_prompt(objective_text, context_string)
    critic_prompt = build_critic_prompt(objective_text, context_string)
    _log(
        "[t4_debate] Dispatching optimist ("
        + str(len(optimist_prompt)) + " chars) + critic ("
        + str(len(critic_prompt)) + " chars) via llm_query_batched"
    )
    advocate_outputs = llm_query_batched([optimist_prompt, critic_prompt])
    optimist_raw = str(advocate_outputs[0])
    critic_raw = str(advocate_outputs[1])
    _log("[t4_debate] Optimist response: " + optimist_raw[:200] + "...")
    _log("[t4_debate] Critic response: " + critic_raw[:200] + "...")

    optimist_case = parse_optimist_response(optimist_raw)
    critic_case = parse_critic_response(critic_raw)

    # --- JUDGE PHASE ---
    _log("\\n[t4_debate] === JUDGE PHASE ===")
    judge_prompt = build_judge_prompt(objective_text, optimist_raw, critic_raw)
    _log(
        "[t4_debate] Dispatching judge ("
        + str(len(judge_prompt)) + " chars) via llm_query"
    )
    judge_output = llm_query(judge_prompt)
    judge_raw = str(judge_output)
    _log("[t4_debate] Judge response: " + judge_raw[:200] + "...")

    verdict, understanding, retrieval_order, confidence_map, adjudication = (
        parse_judge_response(judge_raw)
    )
    _log(
        "[t4_debate] Verdict: " + str(verdict)
        + ", retrievals: " + str(len(retrieval_order))
        + ", confidence dims: " + str(len(confidence_map))
    )

    return T4DebateResult(
        verdict=verdict,
        understanding=understanding,
        retrieval_order=retrieval_order,
        confidence_map=confidence_map,
        adjudication=adjudication,
        optimist_case=optimist_case,
        critic_case=critic_case,
        debug_log=debug_log,
    )\
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4_OPTIMIST_INSTRUCTIONS",
        source=_T4_OPTIMIST_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4_CRITIC_INSTRUCTIONS",
        source=_T4_CRITIC_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4_JUDGE_INSTRUCTIONS",
        source=_T4_JUDGE_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4OptimistCase",
        source=_T4_OPTIMIST_CASE_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4CriticCase",
        source=_T4_CRITIC_CASE_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4Verdict",
        source=_T4_VERDICT_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T4DebateResult",
        source=_T4_DEBATE_RESULT_SRC,
        requires=["T4Verdict", "T4OptimistCase", "T4CriticCase"],
        kind="class",
    )
)

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
        name="build_context_string",
        source=_BUILD_CONTEXT_STRING_SRC,
        requires=["stringify_context"],
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

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="extract_section",
        source=_EXTRACT_SECTION_SRC,
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
        name="extract_confidence_map",
        source=_EXTRACT_CONFIDENCE_MAP_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_optimist_prompt",
        source=_BUILD_OPTIMIST_PROMPT_SRC,
        requires=["T4_OPTIMIST_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_critic_prompt",
        source=_BUILD_CRITIC_PROMPT_SRC,
        requires=["T4_CRITIC_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_judge_prompt",
        source=_BUILD_JUDGE_PROMPT_SRC,
        requires=["T4_JUDGE_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="parse_optimist_response",
        source=_PARSE_OPTIMIST_RESPONSE_SRC,
        requires=["T4OptimistCase", "extract_section"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="parse_critic_response",
        source=_PARSE_CRITIC_RESPONSE_SRC,
        requires=["T4CriticCase", "extract_section"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="parse_judge_response",
        source=_PARSE_JUDGE_RESPONSE_SRC,
        requires=[
            "T4Verdict",
            "extract_section",
            "extract_retrieval_order",
            "extract_confidence_map",
        ],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="run_polya_understand_t4_debate",
        source=_RUN_POLYA_UNDERSTAND_T4_DEBATE_SRC,
        requires=[
            "T4DebateResult",
            "build_context_string",
            "build_optimist_prompt",
            "build_critic_prompt",
            "build_judge_prompt",
            "parse_optimist_response",
            "parse_critic_response",
            "parse_judge_response",
        ],
        kind="function",
    )
)
