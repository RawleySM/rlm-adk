"""Data models for the Context Window Dashboard.

All dataclasses, enums, color maps, and token estimation used by
the data loader, controller, and visualization components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Chunk categories
# ---------------------------------------------------------------------------


class ChunkCategory(str, Enum):
    STATIC_INSTRUCTION = "static_instruction"
    DYNAMIC_INSTRUCTION = "dynamic_instruction"
    USER_PROMPT = "user_prompt"
    LLM_RESPONSE = "llm_response"
    REPL_CODE = "repl_code"
    REPL_OUTPUT = "repl_output"
    CONTEXT_VAR = "context_var"
    WORKER_PROMPT = "worker_prompt"
    WORKER_RESPONSE = "worker_response"


# ---------------------------------------------------------------------------
# Color palette  (colorblind-safe, WCAG contrast-compliant)
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[ChunkCategory, str] = {
    ChunkCategory.STATIC_INSTRUCTION: "#475569",
    ChunkCategory.DYNAMIC_INSTRUCTION: "#6366F1",
    ChunkCategory.USER_PROMPT: "#10B981",
    ChunkCategory.LLM_RESPONSE: "#F59E0B",
    ChunkCategory.REPL_CODE: "#06B6D4",
    ChunkCategory.REPL_OUTPUT: "#14B8A6",
    ChunkCategory.CONTEXT_VAR: "#8B5CF6",
    ChunkCategory.WORKER_PROMPT: "#F43F5E",
    ChunkCategory.WORKER_RESPONSE: "#EC4899",
}

CATEGORY_TEXT_COLORS: dict[ChunkCategory, str] = {
    ChunkCategory.STATIC_INSTRUCTION: "#ffffff",
    ChunkCategory.DYNAMIC_INSTRUCTION: "#ffffff",
    ChunkCategory.USER_PROMPT: "#ffffff",
    ChunkCategory.LLM_RESPONSE: "#000000",
    ChunkCategory.REPL_CODE: "#000000",
    ChunkCategory.REPL_OUTPUT: "#000000",
    ChunkCategory.CONTEXT_VAR: "#ffffff",
    ChunkCategory.WORKER_PROMPT: "#ffffff",
    ChunkCategory.WORKER_RESPONSE: "#ffffff",
}


# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------


@dataclass
class ContextChunk:
    chunk_id: str
    category: ChunkCategory
    title: str
    char_count: int
    estimated_tokens: int
    iteration_origin: int  # -1 for static content
    text_preview_head: str  # first 5 lines
    text_preview_tail: str  # last 5 lines
    full_text: str


@dataclass
class ContextWindow:
    agent_type: str  # "reasoning" | "worker"
    agent_name: str
    iteration: int
    chunks: list[ContextChunk]
    total_chars: int
    total_tokens: int  # from usage_metadata.prompt_token_count
    output_tokens: int  # from usage_metadata.candidates_token_count
    model: str


@dataclass
class ModelOutput:
    timestamp: float
    session_id: str
    iteration: int
    agent_type: str  # "reasoning" | "worker"
    agent_name: str
    model: str
    model_version: str
    output_text: str
    output_chars: int
    thought_chars: int
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    error: bool = False
    error_message: str | None = None

    @property
    def text_preview_head(self) -> str:
        """First 5 lines of output text."""
        lines = self.output_text.split("\n")
        return "\n".join(lines[:5])

    @property
    def text_preview_tail(self) -> str:
        """Last 5 lines of output text."""
        lines = self.output_text.split("\n")
        if len(lines) > 5:
            return "\n".join(lines[-5:])
        return self.text_preview_head


@dataclass
class IterationData:
    iteration_index: int
    reasoning_window: ContextWindow | None
    worker_windows: list[ContextWindow] = field(default_factory=list)
    reasoning_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    worker_input_tokens: int = 0
    worker_output_tokens: int = 0
    has_workers: bool = False
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0
    reasoning_output: ModelOutput | None = None
    worker_outputs: list[ModelOutput] = field(default_factory=list)


@dataclass
class SessionSummary:
    session_id: str
    app_name: str
    model: str
    total_iterations: int
    total_input_tokens: int
    total_output_tokens: int
    total_calls: int
    reasoning_calls: int
    worker_calls: int
    start_time: float
    end_time: float


# ---------------------------------------------------------------------------
# API Token Reconciliation
# ---------------------------------------------------------------------------


@dataclass
class ModelTokenUsage:
    model: str
    input_tokens: int
    output_tokens: int
    calls: int


@dataclass
class APITokenUsage:
    source: str  # "local" | "gcloud_monitoring"
    total_input_tokens: int
    total_output_tokens: int
    total_calls: int
    per_model: dict[str, ModelTokenUsage] = field(default_factory=dict)


@dataclass
class TokenReconciliation:
    local_input_tokens: int
    local_output_tokens: int
    api_input_tokens: int
    api_output_tokens: int
    input_delta: int
    output_delta: int
    input_match: bool
    output_match: bool
    error_message: str | None


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens_for_chunks(chunks: list[ContextChunk], known_total_tokens: int) -> None:
    """Distribute known total tokens proportionally by character count.

    Mutates ``chunk.estimated_tokens`` in place.  Calibrates to the
    actual Gemini tokenizer output for the specific request (via
    ``usage_metadata``), which is more accurate than a flat chars/4
    heuristic.
    """
    total_chars = sum(c.char_count for c in chunks)
    if total_chars == 0 or known_total_tokens == 0:
        for chunk in chunks:
            chunk.estimated_tokens = 0
        return
    for chunk in chunks:
        chunk.estimated_tokens = round(known_total_tokens * chunk.char_count / total_chars)
