"""ADK Skill definition + source-expandable REPL exports: T2 Flat Open-Ended topology.

Defines ``POLYA_UNDERSTAND_T2_FLAT_SKILL`` using ``google.adk.skills.models.Skill`` and provides
``build_polya_understand_t2_flat_skill_instruction_block()`` which returns the XML discovery
block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t2_flat import run_polya_understand_t2_flat``
expands into inline source before the AST rewriter runs.

T2 Flat Open-Ended topology:
  L0 sees FULL context (key departure from v1). Generates open-ended probing
  questions locally (no LLM call), dispatches Q investigation children via
  ``llm_query_batched()``, then 1 synthesis child via ``llm_query()``.
  Total: Q+1 calls, no cycles.
"""

from __future__ import annotations

import textwrap

from google.adk.skills.models import Frontmatter, Skill
from google.adk.skills.prompt import format_skills_as_xml

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ===========================================================================
# ADK Skill definition (prompt discovery)
# ===========================================================================

POLYA_UNDERSTAND_T2_FLAT_SKILL = Skill(
    frontmatter=Frontmatter(
        name="polya-understand-t2-flat",
        description=(
            "T2 Flat Open-Ended Polya understand topology. L0 sees full context, "
            "generates probing questions locally (no LLM call), dispatches Q "
            "investigation children via llm_query_batched(), then 1 synthesis "
            "child via llm_query(). Total: Q+1 calls, no cycles."
        ),
    ),
    instructions=textwrap.dedent("""\
## polya-understand-t2-flat -- Flat Open-Ended Context Validation

Use this source-expandable REPL skill for fast, single-pass context validation.
Unlike the iterative v1 polya-understand loop, T2 Flat uses a single fan-out
of open-ended investigation questions followed by one synthesis pass. L0 sees
the FULL context and generates probing questions locally (no LLM call needed
for question generation).

Best for: medium-sized contexts where a single investigation pass is sufficient
and iterative refinement is not needed.

### Usage

```repl
from rlm_repl_skills.polya_understand_t2_flat import run_polya_understand_t2_flat
result = run_polya_understand_t2_flat(
    objective="Validate whether I have enough context to safely modify this codebase.",
    project_context=user_ctx,
    num_questions=5,
)
print(result.verdict)
print(result.understanding)
print(result.gaps)
```

### Parameters

- ``objective`` (str): The concrete objective you are trying to understand.
- ``project_context`` (str | list | dict): The currently available context.
  Can be a packed repo XML string, repomix shards, notes, manifests, or a
  filename-to-content mapping (typically ``user_ctx``).
- ``num_questions`` (int, default 5): Number of probing questions to generate
  and investigate. Clamped to [1, 10].
- ``emit_debug`` (bool, default True): Print debug logs to stdout.

### Return Value

``T2FlatResult`` with attributes:
- ``.understanding``: The synthesized understanding from the synthesis child.
- ``.coverage_assessment``: Coverage assessment parsed from synthesis output.
- ``.gaps``: List of identified gaps parsed from synthesis output.
- ``.verdict``: ``SUFFICIENT``, ``PARTIAL``, or ``INSUFFICIENT``.
- ``.questions_asked``: List of probing questions that were investigated.
- ``.investigation_responses``: List of investigation child responses.
- ``.debug_log``: List of debug messages.

### How It Works

1. **BUILD CONTEXT** -- ``build_context_string(project_context)`` flattens the
   full context into a single string. L0 sees everything (no manifest-only view).

2. **GENERATE QUESTIONS** -- ``generate_probing_questions(objective, context_string, num_questions)``
   generates open-ended probing questions locally using heuristic templates.
   No LLM call is needed for this step.

3. **INVESTIGATE** -- ``llm_query_batched(prompts)`` dispatches Q investigation
   children, each receiving one question + the full context string.

4. **SYNTHESIZE** -- ``llm_query(prompt)`` dispatches 1 synthesis child that
   receives all Q&A pairs and produces a verdict with understanding.
"""),
)


def build_polya_understand_t2_flat_skill_instruction_block() -> str:
    """Return the skill discovery XML + full instructions for prompt injection."""
    discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_T2_FLAT_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{POLYA_UNDERSTAND_T2_FLAT_SKILL.instructions}"


# ===========================================================================
# Source-expandable REPL exports (side-effect registration at import time)
# ===========================================================================

_MODULE = "rlm_repl_skills.polya_understand_t2_flat"

# ---------------------------------------------------------------------------
# Constants: T2 Flat instructions
# ---------------------------------------------------------------------------

_T2_FLAT_INSTRUCTIONS_SRC = """\
T2_FLAT_INSTRUCTIONS = (
    "You are part of a T2 Flat Open-Ended Polya understand topology. "
    "Your role depends on the phase indicated in the prompt. "
    "INVESTIGATION phase: You receive a probing question and the full project "
    "context. Analyze the context to answer the question thoroughly. Use ONLY "
    "evidence found in the provided context. If the context does not contain "
    "relevant information, explicitly state GAP. Return a structured response "
    "with these headings: QUESTION_ADDRESSED, EVIDENCE, GAPS, CONFIDENCE. "
    "SYNTHESIS phase: You receive all question-answer pairs from the "
    "investigation phase. Produce a composite understanding with these "
    "headings: UNDERSTANDING, COVERAGE_ASSESSMENT, GAPS (bullet list or NONE), "
    "VERDICT (one of: SUFFICIENT, PARTIAL, INSUFFICIENT)."
)\
"""

# ---------------------------------------------------------------------------
# Result class
# ---------------------------------------------------------------------------

_T2_FLAT_RESULT_SRC = """\
class T2FlatResult:
    def __init__(
        self,
        understanding,
        coverage_assessment,
        gaps,
        verdict,
        questions_asked,
        investigation_responses,
        debug_log=None,
    ):
        self.understanding = understanding
        self.coverage_assessment = coverage_assessment
        self.gaps = gaps
        self.verdict = verdict
        self.questions_asked = questions_asked
        self.investigation_responses = investigation_responses
        self.debug_log = debug_log or []

    def __repr__(self):
        return (
            "T2FlatResult(verdict=" + repr(self.verdict)
            + ", gaps=" + str(len(self.gaps))
            + ", questions=" + str(len(self.questions_asked)) + ")"
        )\
"""

# ---------------------------------------------------------------------------
# Helpers: context preparation
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
    text = stringify_context(project_context, "project_context")
    if not text or not text.strip():
        return "[[empty_context]]"
    return text\
"""

# ---------------------------------------------------------------------------
# Question generation (local heuristic, no LLM call)
# ---------------------------------------------------------------------------

_GENERATE_PROBING_QUESTIONS_SRC = '''\
def generate_probing_questions(objective, context_string, num_questions=5):
    """Generate open-ended probing questions using heuristic templates.

    Pure local function -- no LLM call. Uses 10 fixed investigative
    question templates parameterized by the objective subject.
    Returns up to num_questions questions (clamped to [1, 10]).
    """
    num_questions = max(1, min(10, num_questions))
    obj = str(objective or "").strip()
    if not obj:
        obj = "the stated objective"

    templates = [
        "What is the core purpose of {obj} and what specific deliverable is being requested?",
        "What are the key components, modules, or subsystems relevant to {obj}?",
        "What constraints, limitations, or requirements govern {obj}?",
        "What are the primary risks or failure modes associated with {obj}?",
        "What dependencies (internal or external) does {obj} rely on?",
        "What unknowns or ambiguities exist in the context related to {obj}?",
        "What would constitute success criteria or acceptance conditions for {obj}?",
        "What implementation patterns, conventions, or prior art in the context are relevant to {obj}?",
        "What testing strategies, validation approaches, or quality gates apply to {obj}?",
        "What trade-offs, alternatives, or design decisions are relevant to {obj}?",
    ]
    questions = []
    for template in templates[:num_questions]:
        questions.append(template.format(obj=obj))
    return questions\
'''

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_BUILD_INVESTIGATION_PROMPT_SRC = '''\
def build_investigation_prompt(question, context_string):
    """Build an investigation prompt for one child.

    Each child receives one probing question + the full context.
    """
    parts = [T2_FLAT_INSTRUCTIONS]
    parts.append("\\n\\nPHASE: INVESTIGATION")
    parts.append("\\n\\nPROBING_QUESTION:\\n" + question)
    parts.append("\\n\\nFULL_PROJECT_CONTEXT:\\n" + context_string)
    parts.append("\\n\\nReturn your structured investigation response now.")
    return "".join(parts)\
'''

_BUILD_SYNTHESIS_PROMPT_SRC = '''\
def build_synthesis_prompt(objective, questions, responses):
    """Build the synthesis prompt from all Q&A pairs.

    The synthesis child receives every question-answer pair and
    produces the final understanding with verdict.
    """
    parts = [T2_FLAT_INSTRUCTIONS]
    parts.append("\\n\\nPHASE: SYNTHESIS")
    parts.append("\\n\\nOBJECTIVE: " + str(objective))
    parts.append("\\n\\nINVESTIGATION_RESULTS:")
    for idx in range(len(questions)):
        parts.append("\\n\\n[Q" + str(idx + 1) + "]: " + questions[idx])
        response = responses[idx] if idx < len(responses) else "(no response)"
        parts.append("\\n[A" + str(idx + 1) + "]: " + str(response))
    parts.append(
        "\\n\\nProduce the composite understanding with headings: "
        "UNDERSTANDING, COVERAGE_ASSESSMENT, GAPS, VERDICT."
    )
    return "".join(parts)\
'''

# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

_EXTRACT_VERDICT_SRC = """\
def extract_verdict(text):
    for line in str(text or "").split("\\n"):
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("VERDICT:"):
            value = stripped[len("VERDICT:"):].strip().upper()
            if value in ("SUFFICIENT", "PARTIAL", "INSUFFICIENT"):
                return value
    return "PARTIAL"\
"""

_EXTRACT_GAPS_SRC = """\
def extract_gaps(text):
    lines = str(text or "").split("\\n")
    in_gaps = False
    gaps = []
    stop_headings = (
        "VERDICT:", "UNDERSTANDING:", "COVERAGE_ASSESSMENT:",
        "CONFIDENCE:", "QUESTION_ADDRESSED:", "EVIDENCE:",
    )
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("GAPS:"):
            inline = stripped[len("GAPS:"):].strip()
            if inline.upper() == "NONE" or inline.upper() == "N/A":
                return []
            if inline:
                gaps.append(inline)
            in_gaps = True
            continue
        if in_gaps:
            if not stripped:
                continue
            is_stop = False
            for sh in stop_headings:
                if upper.startswith(sh):
                    is_stop = True
                    break
            if is_stop:
                break
            if stripped.upper().endswith(":") and (
                stripped.replace("_", "").replace("-", "").replace(":", "").replace(" ", "").isupper()
            ):
                break
            candidate = stripped
            if candidate[:1] in "-*":
                candidate = candidate[1:].strip()
            if candidate and candidate.upper() != "NONE":
                gaps.append(candidate)
    return gaps\
"""

_EXTRACT_COVERAGE_SRC = """\
def extract_coverage(text):
    prefix = "COVERAGE_ASSESSMENT:"
    for line in str(text or "").split("\\n"):
        stripped = line.strip()
        if stripped.upper().startswith(prefix.upper()):
            return stripped[len(prefix):].strip()
    return ""\
"""

_EXTRACT_UNDERSTANDING_SRC = """\
def extract_understanding(text):
    lines = str(text or "").split("\\n")
    in_understanding = False
    parts = []
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("UNDERSTANDING:"):
            inline = stripped[len("UNDERSTANDING:"):].strip()
            if inline:
                parts.append(inline)
            in_understanding = True
            continue
        if in_understanding:
            if stripped.upper().startswith("COVERAGE_ASSESSMENT:"):
                break
            if stripped.upper().startswith("GAPS:"):
                break
            if stripped.upper().startswith("VERDICT:"):
                break
            parts.append(stripped)
    text_out = "\\n".join(parts).strip()
    return text_out if text_out else str(text or "").strip()\
"""

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_RUN_POLYA_UNDERSTAND_T2_FLAT_SRC = '''\
def run_polya_understand_t2_flat(
    objective,
    project_context,
    num_questions=5,
    emit_debug=True,
):
    """Run the T2 Flat Open-Ended Polya understand topology.

    L0 sees FULL context. Generates open-ended probing questions locally
    (no LLM call), dispatches Q investigation children via llm_query_batched(),
    then 1 synthesis child via llm_query(). Total: Q+1 calls, no cycles.

    Args:
        objective: Concrete objective to validate.
        project_context: Current context blob (str | list | dict).
        num_questions: Number of probing questions (clamped to [1, 10]).
        emit_debug: Whether to print debug logs.

    Returns:
        T2FlatResult with understanding, coverage, gaps, and verdict.
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

    # Step 1: Build full context string (L0 sees everything)
    _log("[t2_flat] Building full context string")
    context_string = build_context_string(project_context)
    _log("[t2_flat] Context string length: " + str(len(context_string)))

    # Step 2: Generate probing questions locally (no LLM call)
    _log("[t2_flat] Generating probing questions")
    questions = generate_probing_questions(
        objective_text, context_string, num_questions
    )
    _log("[t2_flat] Generated " + str(len(questions)) + " questions")

    # Step 3: Dispatch investigation children via llm_query_batched
    _log("[t2_flat] Dispatching " + str(len(questions)) + " investigation children")
    investigation_prompts = [
        build_investigation_prompt(q, context_string) for q in questions
    ]
    investigation_outputs = llm_query_batched(investigation_prompts)
    investigation_responses = [str(item) for item in investigation_outputs]
    for idx, response in enumerate(investigation_responses):
        _log(
            "[t2_flat] Investigation " + str(idx + 1) + ": "
            + response[:160] + "..."
        )

    # Step 4: Dispatch synthesis child via llm_query
    _log("[t2_flat] Dispatching synthesis child")
    synthesis_prompt = build_synthesis_prompt(
        objective_text, questions, investigation_responses
    )
    synthesis_output = llm_query(synthesis_prompt)
    synthesis_text = str(synthesis_output)
    _log("[t2_flat] Synthesis received: " + synthesis_text[:200] + "...")

    # Step 5: Parse synthesis output
    understanding = extract_understanding(synthesis_text)
    coverage = extract_coverage(synthesis_text)
    gaps = extract_gaps(synthesis_text)
    verdict = extract_verdict(synthesis_text)
    _log(
        "[t2_flat] Verdict=" + verdict
        + ", gaps=" + str(len(gaps))
        + ", coverage=" + (coverage[:80] if coverage else "(none)")
    )

    return T2FlatResult(
        understanding=understanding,
        coverage_assessment=coverage,
        gaps=gaps,
        verdict=verdict,
        questions_asked=questions,
        investigation_responses=investigation_responses,
        debug_log=debug_log,
    )\
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T2_FLAT_INSTRUCTIONS",
        source=_T2_FLAT_INSTRUCTIONS_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="T2FlatResult",
        source=_T2_FLAT_RESULT_SRC,
        requires=[],
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
        name="generate_probing_questions",
        source=_GENERATE_PROBING_QUESTIONS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_investigation_prompt",
        source=_BUILD_INVESTIGATION_PROMPT_SRC,
        requires=["T2_FLAT_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="build_synthesis_prompt",
        source=_BUILD_SYNTHESIS_PROMPT_SRC,
        requires=["T2_FLAT_INSTRUCTIONS"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="extract_verdict",
        source=_EXTRACT_VERDICT_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="extract_gaps",
        source=_EXTRACT_GAPS_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="extract_coverage",
        source=_EXTRACT_COVERAGE_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="extract_understanding",
        source=_EXTRACT_UNDERSTANDING_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="run_polya_understand_t2_flat",
        source=_RUN_POLYA_UNDERSTAND_T2_FLAT_SRC,
        requires=[
            "T2FlatResult",
            "build_context_string",
            "generate_probing_questions",
            "build_investigation_prompt",
            "build_synthesis_prompt",
            "extract_understanding",
            "extract_coverage",
            "extract_gaps",
            "extract_verdict",
        ],
        kind="function",
    )
)
