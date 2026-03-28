"""Async bridge: RLM runner invocation -> AgentOutputV2.

Translates a benchmark case into an RLM runner invocation and parses
the structured output back into AgentOutputV2 for scoring.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.adk.runners import Runner
from google.genai import types

from rlm_adk.eval.understand_bench_v2.scoring import AgentOutputV2
from rlm_adk.eval.understand_bench_v2.types import FormatSkill, ProcessingChallenge

_DB_PATH = Path(__file__).resolve().parents[3] / ".adk" / "traces.db"


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def format_benchmark_prompt(
    objective: str,
    manifest: list[dict[str, Any]],
    file_metadata: list[dict[str, Any]],
    processing_challenges: list[ProcessingChallenge],
) -> str:
    """Build the prompt for one benchmark case.

    Includes the broad objective, provided files manifest, file metadata
    with resolved paths, processing challenges, and explicit instructions
    for the ReasoningOutput contract (JSON serialized inside final_answer).
    """
    manifest_json = json.dumps(manifest, indent=2)
    metadata_json = json.dumps(file_metadata, indent=2, default=str)
    challenges_json = json.dumps(
        [
            {
                "file_ref": c.file_ref,
                "required_skill": c.required_skill.value,
                "description": c.description,
                "extraction_target": c.extraction_target,
                "difficulty": c.difficulty,
            }
            for c in processing_challenges
        ],
        indent=2,
    )

    return f"""\
Analyze this tax preparation case. You must:
1. Examine each provided file and identify what processing skills are needed
2. Identify ALL missing documents/context that would be needed to complete the task
3. Determine the correct retrieval order for missing artifacts (dependencies first)
4. Decide whether to halt due to insufficient context

## Broad Objective
{objective}

## Provided Files
{manifest_json}

## File Details
{metadata_json}

## Processing Challenges
{challenges_json}

When done, call set_model_response. Your final_answer field MUST be a JSON string
matching this schema:
{{
  "retrieved_artifacts": ["list of missing artifacts to retrieve, in dependency order"],
  "halted": true/false,
  "identified_skills": ["csv_parse", "json_parse", ...],
  "processing_plan": ["ordered list of files to process"],
  "reasoning": "explanation of your analysis"
}}

IMPORTANT: The set_model_response tool expects a `final_answer` string field.
Serialize the JSON above as the value of `final_answer`. Example:
{{
  "final_answer": "{{\\"retrieved_artifacts\\": [...], \\"halted\\": true, ...}}",
  "reasoning_summary": "Brief summary of analysis approach"
}}"""


# ---------------------------------------------------------------------------
# Telemetry accumulator
# ---------------------------------------------------------------------------

_STUCK_THRESHOLD = 5  # identical code hashes before emitting [RLM:STUCK]
_STALL_SECONDS = 120  # seconds without progress before emitting [RLM:STUCK]


class TelemetryAccumulator:
    """Track running state across runner events and emit [RLM:*] lines."""

    def __init__(self) -> None:
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.iteration_count: int = 0
        self.code_hash_history: list[str] = []
        self.last_progress_time: float = time.time()
        self.error_events: list[str] = []
        self.start_time: float = time.time()

    def process_event(self, event: Any) -> list[str]:
        """Process one runner event, return list of [RLM:*] telemetry lines."""
        lines: list[str] = []

        # Token tracking
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            um = event.usage_metadata
            if hasattr(um, "prompt_token_count") and um.prompt_token_count:
                self.total_input_tokens = um.prompt_token_count
            if hasattr(um, "candidates_token_count") and um.candidates_token_count:
                self.total_output_tokens = um.candidates_token_count

        # State delta tracking
        if event.actions and event.actions.state_delta:
            delta = event.actions.state_delta

            # Iteration progress
            if "iteration_count" in delta:
                new_iter = delta["iteration_count"]
                if new_iter != self.iteration_count:
                    self.iteration_count = new_iter
                    self.last_progress_time = time.time()
                    elapsed = time.time() - self.start_time
                    total = self.total_input_tokens + self.total_output_tokens
                    lines.append(
                        f"[RLM:TOKENS] total={total} "
                        f"input={self.total_input_tokens} "
                        f"output={self.total_output_tokens} "
                        f"elapsed={elapsed:.0f}s"
                    )

            # Code hash loop detection
            if "repl_submitted_code_hash" in delta:
                code_hash = delta["repl_submitted_code_hash"]
                self.code_hash_history.append(str(code_hash))
                # Check for repeated hashes
                if len(self.code_hash_history) >= _STUCK_THRESHOLD:
                    tail = self.code_hash_history[-_STUCK_THRESHOLD:]
                    if len(set(tail)) == 1:
                        lines.append(
                            f"[RLM:STUCK] agent=reasoning_agent "
                            f"iter={self.iteration_count} "
                            f"code_hash_repeats={_STUCK_THRESHOLD}"
                        )

        # Stall detection (time since last iteration progress)
        if (time.time() - self.last_progress_time) > _STALL_SECONDS:
            lines.append(
                f"[RLM:STUCK] agent=reasoning_agent "
                f"iter={self.iteration_count} "
                f"stall_seconds={time.time() - self.last_progress_time:.0f}"
            )
            self.last_progress_time = time.time()  # reset to avoid spamming

        # Error tracking
        if hasattr(event, "error_code") and event.error_code:
            msg = f"[RLM:ERROR] type={event.error_code}"
            if hasattr(event, "error_message") and event.error_message:
                msg += f" message={event.error_message}"
            lines.append(msg)
            self.error_events.append(msg)

        return lines


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

_SKILL_NAMES = {s.value for s in FormatSkill}


def parse_agent_output(raw: str) -> AgentOutputV2:
    """Parse the agent's final_answer string into AgentOutputV2.

    The agent is instructed to serialize benchmark JSON as the value of
    ``final_answer`` in the ReasoningOutput schema. This function:
    1. Tries json.loads(raw) -- expected: the serialized benchmark JSON
    2. If raw is itself a ReasoningOutput-shaped dict with a final_answer key,
       extracts that and json.loads it (double-wrapped case)
    3. Falls back to regex extraction from free text
    """
    if not raw or not raw.strip():
        return AgentOutputV2(
            retrieved_artifacts=[],
            halted=False,
            raw_output=raw or "",
        )

    # Attempt 1: direct JSON parse
    parsed = _try_json_parse(raw)
    if parsed is not None:
        # Check for double-wrapped case: {"final_answer": "{...}"}
        if "final_answer" in parsed and isinstance(parsed["final_answer"], str):
            inner = _try_json_parse(parsed["final_answer"])
            if inner is not None:
                parsed = inner
        return _dict_to_output(parsed, raw)

    # Attempt 2: regex fallback
    return _regex_fallback(raw)


def _try_json_parse(text: str) -> dict[str, Any] | None:
    """Try to parse text as JSON, return None on failure."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting JSON from markdown code blocks
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _dict_to_output(d: dict[str, Any], raw: str) -> AgentOutputV2:
    """Convert a parsed dict to AgentOutputV2."""
    return AgentOutputV2(
        retrieved_artifacts=d.get("retrieved_artifacts", []),
        halted=bool(d.get("halted", False)),
        identified_skills=[str(s) for s in d.get("identified_skills", [])],
        processing_plan=[str(s) for s in d.get("processing_plan", [])],
        raw_output=raw,
    )


def _regex_fallback(raw: str) -> AgentOutputV2:
    """Extract AgentOutputV2 fields from free text using heuristics."""
    # Artifacts: lines starting with - after "missing" or "retrieve" headings
    artifacts: list[str] = []
    in_artifact_section = False
    for line in raw.splitlines():
        lower = line.lower().strip()
        if any(kw in lower for kw in ("missing", "retrieve", "artifact", "gap")):
            in_artifact_section = True
            continue
        if in_artifact_section and lower.startswith("-"):
            artifacts.append(line.strip().lstrip("- ").strip())
        elif in_artifact_section and lower and not lower.startswith("-"):
            in_artifact_section = False

    # Halted: presence of halt keyword
    halted = bool(re.search(r"\bhalt(ed)?\b", raw, re.IGNORECASE))

    # Skills: match against FormatSkill enum values
    skills: list[str] = []
    raw_lower = raw.lower()
    for skill_name in _SKILL_NAMES:
        if skill_name in raw_lower:
            skills.append(skill_name)

    return AgentOutputV2(
        retrieved_artifacts=artifacts,
        halted=halted,
        identified_skills=skills,
        raw_output=raw,
    )


# ---------------------------------------------------------------------------
# Core async bridge
# ---------------------------------------------------------------------------


async def run_case_async(
    runner: Runner,
    objective: str,
    manifest: list[dict[str, Any]],
    file_metadata: list[dict[str, Any]],
    provided_files: list[Any],
    processing_challenges: list[ProcessingChallenge],
    skill_name: str = "understand_v1",
    telemetry_cb: Callable[[str], None] | None = None,
) -> tuple[AgentOutputV2, str]:
    """Run one benchmark case through the RLM agent.

    Returns (agent_output, trace_id).

    Args:
        runner: Pre-constructed RLM runner.
        objective: The case's broad_objective.
        manifest: Output of build_manifest(case).
        file_metadata: Per-file metadata with resolved paths.
        provided_files: List of FileRef objects from the case.
        processing_challenges: List of ProcessingChallenge objects.
        skill_name: Used to tag the session's root_prompt state with
                    [BENCH:{skill_name}] so that *completed* benchmark traces
                    are identifiable in traces.db via root_prompt_preview
                    (populated in after_run_callback). NOTE: root_prompt_preview
                    is NOT available on running traces -- the preflight
                    active-session check uses user_id='bench_user' instead.
        telemetry_cb: Optional callback for [RLM:*] telemetry lines.
    """
    # Step 1: Session creation (isolated per case)
    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id="bench_user",
        state={
            "root_prompt": f"[BENCH:{skill_name}] {objective}",
        },
    )

    # Step 2: Prompt construction
    prompt = format_benchmark_prompt(objective, manifest, file_metadata, processing_challenges)

    # Step 3: Event loop with telemetry
    acc = TelemetryAccumulator()
    async for event in runner.run_async(
        user_id="bench_user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        lines = acc.process_event(event)
        for line in lines:
            if telemetry_cb:
                telemetry_cb(line)

    # Step 4: Output extraction
    updated = await runner.session_service.get_session(
        app_name="rlm_adk",
        user_id="bench_user",
        session_id=session.id,
    )
    raw = updated.state.get("final_response_text", "")

    # Step 5: Parse into AgentOutputV2
    agent_output = parse_agent_output(raw)

    # Step 6: Trace ID retrieval
    trace_id = _get_trace_id(session.id)

    return agent_output, trace_id


def _get_trace_id(session_id: str) -> str:
    """Query traces.db for the trace associated with a session."""
    db_path = _DB_PATH
    if not db_path.is_file():
        return f"unknown_{session_id}"
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT trace_id FROM traces WHERE session_id = ? ORDER BY start_time DESC LIMIT 1",
            (session_id,),
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else f"unknown_{session_id}"
    except sqlite3.Error:
        return f"unknown_{session_id}"
