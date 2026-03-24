"""Scoring module for the Understand-phase benchmark v2.

Extends v1 scoring with format-processing skill evaluation:
  - Recall 30% (missing-context detection)
  - Precision 15% (false positive penalty)
  - Order Score 15% (retrieval sequencing for multi-hop)
  - Halt Score 15% (did agent halt on gaps?)
  - Skill Score 25% (NEW: did agent identify required processing skills?)
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from rlm_adk.eval.understand_bench_v2.types import (
    BenchmarkCaseV2,
    FormatSkill,
    MissingContextCategory,
)

# ---------------------------------------------------------------------------
# Category keyword map (same as v1)
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[MissingContextCategory, list[str]] = {
    MissingContextCategory.DOCUMENT: [
        "document",
        "form",
        "paperwork",
        "filing",
        "return",
        "statement",
    ],
    MissingContextCategory.CREDENTIAL: [
        "credential",
        "password",
        "login",
        "access",
        "authentication",
        "token",
    ],
    MissingContextCategory.AGENT_SKILL: ["skill", "capability", "tool", "function", "ability"],
    MissingContextCategory.HISTORICAL_RECORD: [
        "historical",
        "prior year",
        "previous year",
        "past",
        "history",
        "prior",
    ],
    MissingContextCategory.THIRD_PARTY_RECORD: [
        "third party",
        "external",
        "payment record",
        "bank",
        "brokerage",
    ],
    MissingContextCategory.USER_ATTESTATION: [
        "attestation",
        "user confirm",
        "declaration",
        "affirm",
        "certif",
    ],
    MissingContextCategory.REGULATORY_REFERENCE: [
        "regulation",
        "regulatory",
        "rule",
        "statute",
        "code section",
    ],
    MissingContextCategory.COMPUTATIONAL_PREREQ: [
        "computation",
        "calculation",
        "prerequisite",
        "intermediate",
        "worksheet",
    ],
    MissingContextCategory.CROSS_DOMAIN_LINK: [
        "cross domain",
        "cross-domain",
        "linked",
        "dependency",
        "upstream",
    ],
}

# Skill keyword map for partial matching
_SKILL_KEYWORDS: dict[FormatSkill, list[str]] = {
    FormatSkill.PDF_TEXT_EXTRACT: ["pdf", "extract text", "read pdf"],
    FormatSkill.PDF_TABLE_EXTRACT: ["pdf table", "extract table", "tabular pdf"],
    FormatSkill.PDF_FORM_FIELD_EXTRACT: ["form field", "pdf form", "fillable"],
    FormatSkill.IMAGE_OCR: ["ocr", "scan", "image", "photo", "picture"],
    FormatSkill.IMAGE_HANDWRITING_OCR: ["handwriting", "handwritten", "ocr"],
    FormatSkill.CSV_PARSE: ["csv", "comma separated", "delimited"],
    FormatSkill.EXCEL_PARSE: ["excel", "xlsx", "spreadsheet", "workbook"],
    FormatSkill.EXCEL_MULTI_SHEET: ["multiple sheets", "multi-sheet", "tabs"],
    FormatSkill.JSON_PARSE: ["json", "structured data"],
    FormatSkill.FINANCIAL_TABLE_INTERPRET: ["financial", "transactions", "statement", "ledger"],
    FormatSkill.FORM_LAYOUT_UNDERSTAND: ["form layout", "box", "field position"],
    FormatSkill.CROSS_REFERENCE: ["cross reference", "cross-reference", "reconcile", "compare"],
    FormatSkill.DATE_NORMALIZATION: ["date format", "date parsing", "date normalization"],
    FormatSkill.CURRENCY_NORMALIZATION: ["currency", "dollar", "amount format"],
}

_GENERIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmore information\b", re.IGNORECASE),
    re.compile(r"\badditional document", re.IGNORECASE),
    re.compile(r"\bmore details?\b", re.IGNORECASE),
    re.compile(r"\bfurther information\b", re.IGNORECASE),
    re.compile(r"\bneed .{0,20}information\b", re.IGNORECASE),
]

# v2 scoring weights (rebalanced for skill assessment)
_WEIGHT_RECALL = 30.0
_WEIGHT_PRECISION = 15.0
_WEIGHT_ORDER = 15.0
_WEIGHT_HALT = 15.0
_WEIGHT_SKILL = 25.0
_MAX_SCORE = 100.0

_PENALTY_HALLUCINATED = -5.0
_PENALTY_PROCEEDING = -20.0
_PENALTY_GENERIC = -10.0
_PENALTY_WRONG_SKILL = -3.0


# ---------------------------------------------------------------------------
# Output / Result models
# ---------------------------------------------------------------------------


class AgentOutputV2(BaseModel):
    """What the agent produced — extends v1 with skill identification."""

    retrieved_artifacts: list[str]
    halted: bool
    identified_skills: list[str] = Field(
        default_factory=list,
        description="Processing skills the agent identified as needed",
    )
    processing_plan: list[str] = Field(
        default_factory=list,
        description="Agent's proposed order for processing provided files",
    )
    raw_output: str = ""


class BenchmarkResultV2(BaseModel):
    """Scored result for a single v2 benchmark case."""

    case_id: str
    recall: float
    precision: float
    order_score: float
    halt_score: float
    skill_score: float  # NEW in v2
    penalties: dict[str, float] = Field(default_factory=dict)
    total_score: float
    max_possible_score: float = _MAX_SCORE
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers (shared with v1)
# ---------------------------------------------------------------------------

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_WHITESPACE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    s = s.lower()
    s = s.replace("_", " ")
    s = _ARTICLES.sub("", s)
    s = _WHITESPACE.sub(" ", s).strip()
    return s


def _fuzzy_match(a: str, b: str) -> bool:
    na = _normalize(a)
    nb = _normalize(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b) >= 0.6


def _category_match(artifact_text: str, category: MissingContextCategory) -> bool:
    normalized = _normalize(artifact_text)
    keywords = _CATEGORY_KEYWORDS.get(category, [])
    return any(kw in normalized for kw in keywords)


def _skill_match(agent_skill_text: str, gold_skill: FormatSkill) -> bool:
    normalized = _normalize(agent_skill_text)
    keywords = _SKILL_KEYWORDS.get(gold_skill, [])
    if any(kw in normalized for kw in keywords):
        return True
    if gold_skill.value.replace("_", " ") in normalized:
        return True
    return False


def _kendall_tau(a: list[str], b: list[str]) -> float:
    shared = set(a) & set(b)
    if len(shared) < 2:
        return 0.0
    order_a = [x for x in a if x in shared]
    order_b = [x for x in b if x in shared]
    rank_b = {item: idx for idx, item in enumerate(order_b)}
    n = len(order_a)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a_diff = i - j
            b_diff = rank_b[order_a[i]] - rank_b[order_a[j]]
            if (a_diff > 0 and b_diff > 0) or (a_diff < 0 and b_diff < 0):
                concordant += 1
            else:
                discordant += 1
    total_pairs = concordant + discordant
    if total_pairs == 0:
        return 0.0
    return (concordant - discordant) / total_pairs


def _is_generic_retrieval(text: str) -> bool:
    return any(pat.search(text) for pat in _GENERIC_PATTERNS)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_result(case: BenchmarkCaseV2, agent_output: AgentOutputV2) -> BenchmarkResultV2:
    """Score an agent's output against a v2 benchmark case."""
    gold_items = case.missing_artifacts
    gold_names = [item.artifact_name for item in gold_items]
    agent_names = agent_output.retrieved_artifacts

    # ----- Match agent artifacts to gold (same as v1) -----
    gold_match_type: dict[str, str] = {}
    matched_agent_indices: set[int] = set()

    for gold_item in gold_items:
        for idx, agent_art in enumerate(agent_names):
            if idx in matched_agent_indices:
                continue
            if _fuzzy_match(agent_art, gold_item.artifact_name):
                gold_match_type[gold_item.artifact_name] = "full"
                matched_agent_indices.add(idx)
                break
        else:
            for idx, agent_art in enumerate(agent_names):
                if idx in matched_agent_indices:
                    continue
                if _category_match(agent_art, gold_item.category):
                    gold_match_type[gold_item.artifact_name] = "category"
                    matched_agent_indices.add(idx)
                    break

    # ----- Recall (30 points) -----
    if not gold_names:
        recall = 1.0
    else:
        credits = sum(
            1.0
            if gold_match_type.get(gi.artifact_name) == "full"
            else 0.5
            if gold_match_type.get(gi.artifact_name) == "category"
            else 0.0
            for gi in gold_items
        )
        recall = credits / len(gold_items)
    recall_points = recall * _WEIGHT_RECALL

    # ----- Precision (15 points) -----
    if not agent_names:
        precision = 1.0 if not gold_names else 0.0
    else:
        precision = len(matched_agent_indices) / len(agent_names)
    precision_points = precision * _WEIGHT_PRECISION

    # ----- Order Score (15 points) -----
    if case.multi_hop_chain is None:
        order_score = 1.0
    else:
        agent_gold_order: list[str] = []
        for i in sorted(matched_agent_indices):
            for gi in gold_items:
                if (
                    _fuzzy_match(agent_names[i], gi.artifact_name)
                    and gold_match_type.get(gi.artifact_name) == "full"
                ):
                    agent_gold_order.append(gi.artifact_name)
                    break
        if len(agent_gold_order) < 2:
            order_score = 0.0
        else:
            tau = _kendall_tau(agent_gold_order, list(case.multi_hop_chain))
            order_score = (tau + 1.0) / 2.0
    order_points = order_score * _WEIGHT_ORDER

    # ----- Halt Score (15 points) -----
    halt_score = 1.0 if agent_output.halted else 0.0
    halt_points = halt_score * _WEIGHT_HALT

    # ----- Skill Score (25 points) — NEW in v2 -----
    gold_skills = set(case.total_skills_required)
    agent_skill_texts = agent_output.identified_skills

    if not gold_skills:
        skill_score = 1.0
    else:
        matched_skills: set[FormatSkill] = set()
        for agent_text in agent_skill_texts:
            for gs in gold_skills:
                if gs not in matched_skills and _skill_match(agent_text, gs):
                    matched_skills.add(gs)
        skill_score = len(matched_skills) / len(gold_skills)
    skill_points = skill_score * _WEIGHT_SKILL

    # ----- Penalties -----
    penalties: dict[str, float] = {}

    unmatched_agent = [
        agent_names[i] for i in range(len(agent_names)) if i not in matched_agent_indices
    ]
    hallucinated = [
        art
        for art in unmatched_agent
        if not any(_category_match(art, gi.category) for gi in gold_items)
    ]
    if hallucinated:
        penalties["hallucinated_retrieval"] = _PENALTY_HALLUCINATED * len(hallucinated)

    if not agent_output.halted and recall < 0.5:
        penalties["proceeding_without_retrieval"] = _PENALTY_PROCEEDING

    generic_hits = [art for art in agent_names if _is_generic_retrieval(art)]
    if generic_hits:
        penalties["generic_retrieval"] = _PENALTY_GENERIC

    penalty_total = sum(penalties.values())

    # ----- Total -----
    raw_total = recall_points + precision_points + order_points + halt_points + skill_points
    total_score = max(0.0, raw_total + penalty_total)

    details: dict[str, Any] = {
        "recall_points": recall_points,
        "precision_points": precision_points,
        "order_points": order_points,
        "halt_points": halt_points,
        "skill_points": skill_points,
        "penalty_total": penalty_total,
        "gold_artifacts": gold_names,
        "agent_artifacts": agent_names,
        "gold_skills": [s.value for s in gold_skills],
        "matched_skills": [s.value for s in matched_skills] if gold_skills else [],
        "gold_match_type": gold_match_type,
        "hallucinated": hallucinated,
        "generic_hits": generic_hits,
    }

    return BenchmarkResultV2(
        case_id=case.case_id,
        recall=recall,
        precision=precision,
        order_score=order_score,
        halt_score=halt_score,
        skill_score=skill_score,
        penalties=penalties,
        total_score=total_score,
        details=details,
    )
