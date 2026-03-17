"""Type system for the Understand-phase benchmark.

Defines the missing-context taxonomy (MissingContextCategory),
individual missing-context items (MissingContextItem), and the
benchmark case schema (BenchmarkCase).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# N0: Missing-Context Taxonomy
# ---------------------------------------------------------------------------


class MissingContextCategory(str, Enum):
    """Top-level classification of missing context."""

    DOCUMENT = "document"
    CREDENTIAL = "credential"
    AGENT_SKILL = "agent_skill"
    HISTORICAL_RECORD = "historical"
    THIRD_PARTY_RECORD = "third_party"
    USER_ATTESTATION = "user_attestation"
    REGULATORY_REFERENCE = "regulatory"
    COMPUTATIONAL_PREREQ = "computational"
    CROSS_DOMAIN_LINK = "cross_domain"


class MissingContextItem(BaseModel):
    """A single missing-context entry in a benchmark case."""

    category: MissingContextCategory
    artifact_name: str = Field(..., description='Human-readable name, e.g. "Prior-year AGI"')
    source_authority: str = Field(
        ..., description='Where the artifact lives, e.g. "IRS e-file records"'
    )
    why_non_derivable: str = Field(
        ..., description="Explanation of why the agent cannot derive this"
    )
    detection_signal: str = Field(
        ..., description="What in the provided context hints at the absence"
    )
    retrieval_method: str = Field(
        ..., description="How the agent should propose to acquire the artifact"
    )
    blocks_downstream: list[str] = Field(
        default_factory=list,
        description="Which planning/execution steps are blocked",
    )
    difficulty_modifier: Literal["direct", "inferential", "multi-hop"] = "direct"


# ---------------------------------------------------------------------------
# N4: File Type Registry
# ---------------------------------------------------------------------------


class FileTypeCategory(str, Enum):
    """Top-level classification of document types."""

    IRS_FORM = "irs_form"
    THIRD_PARTY = "third_party"
    GOVERNMENT = "government"
    USER_GENERATED = "user_generated"


class FileTypeEntry(BaseModel):
    """A single entry in the file type registry."""

    type_id: str = Field(..., description='e.g. "w2", "1099_nec"')
    display_name: str = Field(..., description='e.g. "W-2 (Wage and Tax Statement)"')
    category: FileTypeCategory
    formats: list[str] = Field(
        default_factory=lambda: ["json"],
        description='Supported formats: "json", "pdf", "csv", "image", "text"',
    )
    role_in_workflow: str = ""
    common_gap_pattern: str = ""


# The registry is a flat list; see file_type_registry.py for the populated instance.


# ---------------------------------------------------------------------------
# Benchmark Case schema
# ---------------------------------------------------------------------------


class BenchmarkCase(BaseModel):
    """A single understand-phase benchmark case."""

    case_id: str
    task_name: str
    difficulty: Literal["easy", "medium", "hard"]
    persona_id: str

    broad_objective: str
    provided_context_dict: dict[str, Any] = Field(
        default_factory=dict,
        description="filename → content mapping loaded at runtime",
    )

    missing_artifacts: list[MissingContextItem]
    gold_retrieval_order: list[str] = Field(
        ..., description="Ordered list of missing artifact names"
    )

    why_context_tempts_premature_progress: str = ""
    what_bad_model_does: str = ""
    what_good_model_does: str = ""

    scoring_notes: str = ""
    multi_hop_chain: list[str] | None = None


# ---------------------------------------------------------------------------
# Workflow Step model (N2)
# ---------------------------------------------------------------------------


class WorkflowStep(BaseModel):
    """A single step in the tax-preparation workflow."""

    step_number: int
    name: str
    description: str = ""
    dependencies: list[str] = Field(default_factory=list, description="What this step needs")
    potential_gaps: list[str] = Field(
        default_factory=list,
        description="Missing-context categories that may surface here",
    )
    depends_on_steps: list[int] = Field(
        default_factory=list,
        description="Step numbers that must complete first",
    )
