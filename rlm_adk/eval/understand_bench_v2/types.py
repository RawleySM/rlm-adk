"""Type system for the Understand-phase benchmark v2.

Extends v1 types with:
  - FileRef: references to real files on disk (not inline JSON)
  - FormatSkill: processing capabilities needed per file format
  - ProcessingChallenge: format-specific obstacles the agent must overcome
  - BenchmarkCaseV2: cases built from file references, not inline dicts
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Missing-Context Taxonomy (same as v1, imported for consistency)
# ---------------------------------------------------------------------------


class MissingContextCategory(str, Enum):
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
# v2-specific: Format-Processing Skills
# ---------------------------------------------------------------------------


class FormatSkill(str, Enum):
    """Processing capabilities an agent needs to handle diverse file formats."""

    PDF_TEXT_EXTRACT = "pdf_text_extract"
    PDF_TABLE_EXTRACT = "pdf_table_extract"
    PDF_FORM_FIELD_EXTRACT = "pdf_form_field_extract"
    IMAGE_OCR = "image_ocr"
    IMAGE_HANDWRITING_OCR = "image_handwriting_ocr"
    CSV_PARSE = "csv_parse"
    EXCEL_PARSE = "excel_parse"
    EXCEL_MULTI_SHEET = "excel_multi_sheet"
    JSON_PARSE = "json_parse"
    XML_PARSE = "xml_parse"
    MARKDOWN_PARSE = "markdown_parse"
    PLAIN_TEXT_PARSE = "plain_text_parse"
    HTML_PARSE = "html_parse"
    FINANCIAL_TABLE_INTERPRET = "financial_table_interpret"
    FORM_LAYOUT_UNDERSTAND = "form_layout_understand"
    CROSS_REFERENCE = "cross_reference"
    DATE_NORMALIZATION = "date_normalization"
    CURRENCY_NORMALIZATION = "currency_normalization"


class ProcessingChallenge(BaseModel):
    """A format-specific obstacle the agent must overcome to extract information."""

    file_ref: str = Field(..., description="Which FileRef this challenge applies to")
    required_skill: FormatSkill
    description: str = Field(..., description="What makes this file hard to process")
    extraction_target: str = Field(..., description="What specific information must be extracted")
    difficulty: Literal["routine", "moderate", "hard"] = "routine"


# ---------------------------------------------------------------------------
# v2-specific: File References
# ---------------------------------------------------------------------------


class FileRef(BaseModel):
    """A reference to a real file in the corpus directory."""

    ref_id: str = Field(..., description='Unique ID within the case, e.g. "w2_employer1"')
    filename: str = Field(..., description="Filename relative to corpus/")
    display_name: str = Field(..., description="Human-readable name shown to agent")
    format: str = Field(
        ..., description="File format: pdf, csv, xlsx, json, png, jpg, txt, md, html, xml"
    )
    mime_type: str = Field(default="", description="MIME type if known")
    size_bytes: int = Field(default=0, description="File size in bytes")
    doc_type: str = Field(
        default="unknown",
        description='Document type from registry, e.g. "w2", "bank_statement"',
    )
    description: str = Field(default="", description="Brief description of contents")
    provenance: str = Field(
        default="",
        description='Source: "irs_example", "vita_training", "textbook", "synthetic", "real"',
    )
    skills_required: list[FormatSkill] = Field(
        default_factory=list,
        description="Processing skills needed to extract information from this file",
    )
    key_fields: list[str] = Field(
        default_factory=list,
        description="Important data fields contained in this file",
    )


# ---------------------------------------------------------------------------
# Benchmark Case v2
# ---------------------------------------------------------------------------


class BenchmarkCaseV2(BaseModel):
    """A single understand-phase benchmark case (v2, file-based)."""

    case_id: str
    task_name: str
    difficulty: Literal["easy", "medium", "hard"]
    persona_id: str

    broad_objective: str

    # v2: references to real files instead of inline content
    provided_files: list[FileRef] = Field(
        ..., description="Files provided to the agent as the client document packet"
    )

    # Processing challenges specific to the file formats in this case
    processing_challenges: list[ProcessingChallenge] = Field(
        default_factory=list,
        description="Format-specific obstacles the agent must overcome",
    )

    # Same gap-detection fields as v1
    missing_artifacts: list[MissingContextItem]
    gold_retrieval_order: list[str] = Field(
        ..., description="Ordered list of missing artifact names"
    )

    why_context_tempts_premature_progress: str = ""
    what_bad_model_does: str = ""
    what_good_model_does: str = ""

    scoring_notes: str = ""
    multi_hop_chain: list[str] | None = None

    # v2: aggregate skill requirements
    total_skills_required: list[FormatSkill] = Field(
        default_factory=list,
        description="Union of all skills needed across all provided files",
    )

    # v2: expected processing pipeline
    expected_processing_order: list[str] = Field(
        default_factory=list,
        description="Suggested order to process files for efficiency",
    )
