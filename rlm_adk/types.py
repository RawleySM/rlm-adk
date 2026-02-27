from dataclasses import dataclass
from types import ModuleType
from typing import Any, Literal

ClientBackend = Literal[
    "openai",
    "portkey",
    "openrouter",
    "vercel",
    "vllm",
    "litellm",
    "anthropic",
    "azure_openai",
    "gemini",
]
EnvironmentType = Literal["local", "docker", "modal", "prime", "daytona", "e2b"]


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
    error_category: str | None = None  # TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, FORMAT, UNKNOWN
    http_status: int | None = None
    finish_reason: str | None = None  # STOP, SAFETY, RECITATION, MAX_TOKENS
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    wall_time_ms: float = 0.0
    parsed: dict | None = None  # Validated structured output (set when output_schema used)

    def __new__(cls, text: str, **kwargs: Any) -> "LLMResult":
        instance = super().__new__(cls, text)
        for k, v in kwargs.items():
            setattr(instance, k, v)
        return instance


########################################################
########    Types for LM Cost Tracking         #########
########################################################


@dataclass
class ModelUsageSummary:
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int

    def to_dict(self):
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelUsageSummary":
        return cls(
            total_calls=data.get("total_calls"),
            total_input_tokens=data.get("total_input_tokens"),
            total_output_tokens=data.get("total_output_tokens"),
        )


@dataclass
class UsageSummary:
    model_usage_summaries: dict[str, ModelUsageSummary]

    def to_dict(self):
        return {
            "model_usage_summaries": {
                model: usage_summary.to_dict()
                for model, usage_summary in self.model_usage_summaries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UsageSummary":
        return cls(
            model_usage_summaries={
                model: ModelUsageSummary.from_dict(usage_summary)
                for model, usage_summary in data.get("model_usage_summaries", {}).items()
            },
        )


########################################################
########   Types for REPL and RLM Iterations   #########
########################################################
@dataclass
class RLMChatCompletion:
    """Record of a single LLM call made from within the environment."""

    root_model: str
    prompt: str | dict[str, Any]
    response: str
    usage_summary: UsageSummary
    execution_time: float

    def to_dict(self):
        return {
            "root_model": self.root_model,
            "prompt": self.prompt,
            "response": self.response,
            "usage_summary": self.usage_summary.to_dict(),
            "execution_time": self.execution_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RLMChatCompletion":
        return cls(
            root_model=data.get("root_model"),
            prompt=data.get("prompt"),
            response=data.get("response"),
            usage_summary=UsageSummary.from_dict(data.get("usage_summary")),
            execution_time=data.get("execution_time"),
        )


@dataclass
class REPLResult:
    stdout: str
    stderr: str
    locals: dict
    execution_time: float | None
    llm_calls: list["RLMChatCompletion"]
    trace: dict[str, Any] | None

    def __init__(
        self,
        stdout: str,
        stderr: str,
        locals: dict,
        execution_time: float | None = None,
        llm_calls: list["RLMChatCompletion"] | None = None,
        trace: dict[str, Any] | None = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.locals = locals
        self.execution_time = execution_time
        self.llm_calls = llm_calls or []
        self.trace = trace

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


@dataclass
class CodeBlock:
    code: str
    result: REPLResult

    def to_dict(self):
        return {"code": self.code, "result": self.result.to_dict()}


@dataclass
class RLMIteration:
    prompt: str | dict[str, Any]
    response: str
    code_blocks: list[CodeBlock]
    final_answer: str | None = None
    iteration_time: float | None = None

    def to_dict(self):
        return {
            "prompt": self.prompt,
            "response": self.response,
            "code_blocks": [code_block.to_dict() for code_block in self.code_blocks],
            "final_answer": self.final_answer,
            "iteration_time": self.iteration_time,
        }


########################################################
########   Types for RLM Metadata   #########
########################################################


@dataclass
class RLMMetadata:
    """Metadata about the RLM configuration."""

    root_model: str
    max_depth: int
    max_iterations: int
    backend: str
    backend_kwargs: dict[str, Any]
    environment_type: str
    environment_kwargs: dict[str, Any]
    other_backends: list[str] | None = None

    def to_dict(self):
        return {
            "root_model": self.root_model,
            "max_depth": self.max_depth,
            "max_iterations": self.max_iterations,
            "backend": self.backend,
            "backend_kwargs": {k: _serialize_value(v) for k, v in self.backend_kwargs.items()},
            "environment_type": self.environment_type,
            "environment_kwargs": {
                k: _serialize_value(v) for k, v in self.environment_kwargs.items()
            },
            "other_backends": self.other_backends,
        }


