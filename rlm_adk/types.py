import json
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, Field

from rlm_adk.utils.parsing import find_final_answer

########################################################
########   Structured Output Schema for Reasoning  #####
########################################################


class ReasoningOutput(BaseModel):
    """Structured output schema for the reasoning agent's final answer.

    Used as ``output_schema`` on the reasoning ``LlmAgent`` so ADK
    emits a ``set_model_response`` tool call that the model fills with
    validated JSON matching this schema.
    """

    final_answer: str = Field(description="Complete final answer to the query.")
    reasoning_summary: str = Field(default="", description="Brief reasoning summary.")


class ReasoningObservability(BaseModel):
    """Persistable reasoning-output observability payload."""

    visible_output_text: str = ""
    thought_text: str = ""
    thoughts_tokens: int = 0
    raw_output: Any = None
    parsed_output: dict[str, Any] | None = None
    final_answer: str = ""
    reasoning_summary: str = ""


def parse_reasoning_output(raw: Any) -> ReasoningObservability:
    """Normalize a reasoning output_key payload for observability storage."""
    payload = ReasoningObservability(raw_output=raw)

    parsed: dict[str, Any] | None = None
    if isinstance(raw, dict):
        parsed = dict(raw)
    elif isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            parsed = decoded

    if parsed is not None:
        payload.parsed_output = parsed
        payload.final_answer = str(parsed.get("final_answer", "") or "")
        payload.reasoning_summary = str(parsed.get("reasoning_summary", "") or "")
        if not payload.final_answer:
            payload.final_answer = str(raw) if isinstance(raw, str) else ""
        return payload

    if isinstance(raw, str):
        payload.final_answer = find_final_answer(raw) or raw
    else:
        payload.final_answer = str(raw) if raw is not None else ""
    return payload


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-serializable representation."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, ModuleType):
        return f"<module '{value.__name__}'>"
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if callable(value):
        return f"<{type(value).__name__} '{getattr(value, '__name__', repr(value))}'>"
    # Try to convert to string for other types
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


########################################################
########    Types for Worker LLM Results       #########
########################################################


class LLMResult(str):
    """String subclass carrying worker call metadata.

    Backward-compatible: passes isinstance(x, str), works in f-strings,
    concatenation, etc. But REPL code can inspect error state:

        result = llm_query("prompt")
        if result.error:
            if result.error_category == "TIMEOUT":
                raise RuntimeError(f"Worker timed out: {result}")
            elif result.error_category == "RATE_LIMIT":
                await asyncio.sleep(5)
                result = llm_query("prompt")  # retry
    """

    error: bool = False
    error_category: str | None = (
        None  # TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, FORMAT, UNKNOWN
    )
    http_status: int | None = None
    finish_reason: str | None = None  # STOP, SAFETY, RECITATION, MAX_TOKENS
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    model: str | None = None
    wall_time_ms: float = 0.0
    visible_text: str | None = None
    thought_text: str | None = None
    raw_output: Any | None = None
    parsed: Any = None  # Validated structured output (any type when output_schema used)

    def __new__(cls, text: str, **kwargs: Any) -> "LLMResult":
        instance = super().__new__(cls, text)
        for k, v in kwargs.items():
            setattr(instance, k, v)
        return instance

    @property
    def thought_tokens(self) -> int:
        """Backward-compatible alias for older telemetry code."""
        return getattr(self, "thoughts_tokens", 0)


########################################################
########    Types for LM Cost Tracking         #########
########################################################


class ModelUsageSummary(BaseModel):
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int

    def to_dict(self):
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ModelUsageSummary":
        return cls.model_validate(data)


class UsageSummary(BaseModel):
    model_usage_summaries: dict[str, ModelUsageSummary]

    def to_dict(self):
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "UsageSummary":
        return cls.model_validate(data)


########################################################
########   Types for REPL and RLM Iterations   #########
########################################################


class RLMChatCompletion(BaseModel):
    """Record of a single LLM call made from within the environment."""

    root_model: str
    prompt: str | dict[str, Any]
    response: str
    usage_summary: UsageSummary
    execution_time: float
    finish_reason: str | None = None
    thoughts_tokens: int = 0
    visible_response: str | None = None
    thought_response: str | None = None
    raw_response: Any | None = None
    parsed_response: dict[str, Any] | None = None

    def to_dict(self):
        return {
            "root_model": self.root_model,
            "prompt": self.prompt,
            "response": self.response,
            "usage_summary": self.usage_summary.to_dict(),
            "execution_time": self.execution_time,
            "finish_reason": self.finish_reason,
            "thoughts_tokens": self.thoughts_tokens,
            "visible_response": self.visible_response,
            "thought_response": self.thought_response,
            "raw_response": _serialize_value(self.raw_response),
            "parsed_response": self.parsed_response,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RLMChatCompletion":
        return cls(
            root_model=data.get("root_model"),
            prompt=data.get("prompt"),
            response=data.get("response"),
            usage_summary=UsageSummary.from_dict(data.get("usage_summary")),
            execution_time=data.get("execution_time"),
            finish_reason=data.get("finish_reason"),
            thoughts_tokens=data.get("thoughts_tokens", 0),
            visible_response=data.get("visible_response"),
            thought_response=data.get("thought_response"),
            raw_response=data.get("raw_response"),
            parsed_response=data.get("parsed_response"),
        )


class REPLResult(BaseModel):
    stdout: str
    stderr: str
    locals: dict
    execution_time: float | None = None
    llm_calls: list[RLMChatCompletion] = Field(default_factory=list)
    trace: dict[str, Any] | None = None

    def __str__(self):
        return f"REPLResult(stdout={self.stdout}, stderr={self.stderr}, locals={self.locals}, execution_time={self.execution_time}, llm_calls={len(self.llm_calls)})"

    def to_dict(self):
        result = {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "locals": {k: _serialize_value(v) for k, v in self.locals.items()},
            "execution_time": self.execution_time,
            "llm_calls": [call.to_dict() for call in self.llm_calls],
        }
        if self.trace is not None:
            result["trace"] = self.trace
        return result


########################################################
########   Completion & Lineage Envelopes      #########
########################################################


class CompletionEnvelope(BaseModel):
    """Canonical in-memory result object per reasoning run."""

    terminal: bool
    mode: Literal["structured", "text", "error"]
    output_schema_name: str | None = None
    validated_output: Any = None
    raw_output: Any = None
    display_text: str = ""
    reasoning_summary: str = ""
    finish_reason: str | None = None
    error: bool = False
    error_category: str | None = None


class LineageEdge(BaseModel):
    """Tree-structure edge: where in the execution graph this decision sits."""

    depth: int
    fanout_idx: int | None = None
    parent_depth: int | None = None
    parent_fanout_idx: int | None = None
    branch: str | None = None
    terminal: bool = False
    decision_mode: Literal[
        "execute_code",
        "set_model_response",
        "load_skill",
        "load_skill_resource",
        "list_skills",
        "run_skill_script",
        "unknown",
    ] = "unknown"
    structured_outcome: Literal[
        "not_applicable",
        "validated",
        "retry_requested",
        "retry_exhausted",
        "incomplete",
        "error",
    ] = "not_applicable"


class ProvenanceRecord(BaseModel):
    """Identity/context: who produced this decision and under what config."""

    version: Literal["v1"] = "v1"
    agent_name: str
    invocation_id: str | None = None
    session_id: str | None = None
    output_schema_name: str | None = None


class LineageEnvelope(BaseModel):
    """Backward-compat composite. Prefer LineageEdge + ProvenanceRecord."""

    version: Literal["v1"] = "v1"
    agent_name: str
    depth: int
    fanout_idx: int | None = None
    parent_depth: int | None = None
    parent_fanout_idx: int | None = None
    branch: str | None = None
    invocation_id: str | None = None
    session_id: str | None = None
    output_schema_name: str | None = None
    decision_mode: Literal[
        "execute_code",
        "set_model_response",
        "load_skill",
        "load_skill_resource",
        "list_skills",
        "run_skill_script",
        "unknown",
    ] = "unknown"
    structured_outcome: Literal[
        "not_applicable",
        "validated",
        "retry_requested",
        "retry_exhausted",
        "incomplete",
        "error",
    ] = "not_applicable"
    terminal: bool = False

    @property
    def lineage(self) -> LineageEdge:
        """Extract the tree-structure edge from this envelope."""
        return LineageEdge(**{f: getattr(self, f) for f in LineageEdge.model_fields})

    @property
    def provenance(self) -> ProvenanceRecord:
        """Extract the identity/context record from this envelope."""
        return ProvenanceRecord(**{f: getattr(self, f) for f in ProvenanceRecord.model_fields})


def render_completion_text(validated_output: Any, fallback_text: str = "") -> str:
    """Deterministic renderer for final user-visible text.

    Priority:
    1. dict with final_answer str -> use it
    2. validated string -> use it
    3. other non-None -> compact JSON
    4. None -> fallback_text
    """
    if isinstance(validated_output, dict):
        fa = validated_output.get("final_answer")
        if isinstance(fa, str) and fa.strip():
            return fa
        return json.dumps(validated_output, sort_keys=True, separators=(",", ":"))
    if isinstance(validated_output, str):
        return validated_output
    if validated_output is not None:
        return json.dumps(
            validated_output,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return fallback_text
