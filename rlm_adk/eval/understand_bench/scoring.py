"""Scoring module for the Understand-phase benchmark.

Implements the rubric defined in Section 11 of understand_bench_plan.md:
  Recall 40%, Precision 20%, Order Score 20%, Halt Score 20%
  plus penalty deductions for hallucinations, proceeding without retrieval,
  and generic/vague retrievals.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from rlm_adk.eval.understand_bench.types import BenchmarkCase, MissingContextCategory

# ---------------------------------------------------------------------------
# Category keyword map — used by _category_match to award 50% partial credit
# when the agent identifies the *kind* of missing context but not the exact
# artifact name.
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
        "authorization",
        "api key",
        "token",
    ],
    MissingContextCategory.AGENT_SKILL: [
        "skill",
        "capability",
        "tool",
        "function",
        "ability",
    ],
    MissingContextCategory.HISTORICAL_RECORD: [
        "historical",
        "prior year",
        "previous year",
        "past",
        "history",
        "prior",
        "previous",
        "last year",
        "earlier",
    ],
    MissingContextCategory.THIRD_PARTY_RECORD: [
        "third party",
        "external",
        "payment record",
        "bank",
        "brokerage",
        "employer",
        "vendor",
        "provider",
        "institution",
    ],
    MissingContextCategory.USER_ATTESTATION: [
        "attestation",
        "user confirm",
        "user statement",
        "self report",
        "declaration",
        "affirm",
        "certif",
        "acknowledge",
    ],
    MissingContextCategory.REGULATORY_REFERENCE: [
        "regulation",
        "regulatory",
        "rule",
        "statute",
        "code section",
        "irs guidance",
        "publication",
        "pub ",
        "notice",
        "revenue ruling",
    ],
    MissingContextCategory.COMPUTATIONAL_PREREQ: [
        "computation",
        "calculation",
        "prerequisite",
        "intermediate result",
        "derived",
        "computed",
        "worksheet",
    ],
    MissingContextCategory.CROSS_DOMAIN_LINK: [
        "cross domain",
        "cross-domain",
        "linked",
        "related area",
        "dependency",
        "upstream",
        "downstream",
        "connected",
    ],
}

# Patterns that signal a vague / generic retrieval.
_GENERIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmore information\b", re.IGNORECASE),
    re.compile(r"\badditional document", re.IGNORECASE),
    re.compile(r"\badditional info", re.IGNORECASE),
    re.compile(r"\bmore details?\b", re.IGNORECASE),
    re.compile(r"\bmore data\b", re.IGNORECASE),
    re.compile(r"\bfurther information\b", re.IGNORECASE),
    re.compile(r"\bfurther document", re.IGNORECASE),
    re.compile(r"\bneed .{0,20}information\b", re.IGNORECASE),
]

# Scoring constants
_WEIGHT_RECALL = 40.0
_WEIGHT_PRECISION = 20.0
_WEIGHT_ORDER = 20.0
_WEIGHT_HALT = 20.0
_MAX_SCORE = 100.0

_PENALTY_HALLUCINATED = -5.0
_PENALTY_PROCEEDING = -20.0
_PENALTY_GENERIC = -10.0


# ---------------------------------------------------------------------------
# Output / Result models
# ---------------------------------------------------------------------------


class AgentRetrievalOutput(BaseModel):
    """What the agent produced as its retrieval order."""

    retrieved_artifacts: list[str]  # artifact names the agent identified
    halted: bool  # did the agent explicitly say it cannot proceed?
    raw_output: str = ""  # the agent's full text output for debugging


class BenchmarkResult(BaseModel):
    """Scored result for a single benchmark case."""

    case_id: str
    recall: float  # 0.0-1.0
    precision: float  # 0.0-1.0
    order_score: float  # 0.0-1.0, Kendall tau for multi-hop
    halt_score: float  # 0.0 or 1.0
    penalties: dict[str, float] = Field(default_factory=dict)
    total_score: float  # weighted composite
    max_possible_score: float = _MAX_SCORE
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_WHITESPACE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Lowercase, collapse whitespace, strip leading/trailing space, remove articles."""
    s = s.lower()
    s = _ARTICLES.sub("", s)
    s = _WHITESPACE.sub(" ", s).strip()
    return s


def _fuzzy_match(a: str, b: str) -> bool:
    """Check whether two artifact descriptions are similar enough.

    Considers a match when either:
    - One normalized string is a substring of the other, OR
    - The token-level overlap (Jaccard) is >= 0.6.
    """
    na = _normalize(a)
    nb = _normalize(b)

    if not na or not nb:
        return False

    # Substring containment (either direction).
    if na in nb or nb in na:
        return True

    # Token-level Jaccard similarity.
    tokens_a = set(na.split())
    tokens_b = set(nb.split())
    if not tokens_a or not tokens_b:
        return False
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) >= 0.6


def _category_match(artifact_text: str, category: MissingContextCategory) -> bool:
    """Return True if *artifact_text* implies *category* via keyword overlap."""
    normalized = _normalize(artifact_text)
    keywords = _CATEGORY_KEYWORDS.get(category, [])
    return any(kw in normalized for kw in keywords)


def _kendall_tau(a: list[str], b: list[str]) -> float:
    """Compute Kendall tau rank correlation between two orderings.

    Both lists must contain the same set of elements (only the shared
    intersection is considered).  Returns a value in [-1, 1].
    """
    # Restrict to shared elements, preserving order within each list.
    shared = set(a) & set(b)
    if len(shared) < 2:
        # Need at least 2 items to compute a ranking correlation.
        return 0.0

    order_a = [x for x in a if x in shared]
    order_b = [x for x in b if x in shared]

    # Build rank map from order_b.
    rank_b = {item: idx for idx, item in enumerate(order_b)}

    # Count concordant and discordant pairs.
    n = len(order_a)
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            # Compare the pair (order_a[i], order_a[j]) in both orderings.
            a_diff = i - j  # always negative since i < j
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
    """Return True if *text* looks like a vague/generic retrieval request."""
    return any(pat.search(text) for pat in _GENERIC_PATTERNS)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def score_result(case: BenchmarkCase, agent_output: AgentRetrievalOutput) -> BenchmarkResult:
    """Score an agent's retrieval output against a benchmark case's gold set.

    Returns a :class:`BenchmarkResult` with point breakdowns.
    """
    gold_names: list[str] = [item.artifact_name for item in case.missing_artifacts]
    gold_items = case.missing_artifacts
    agent_names: list[str] = agent_output.retrieved_artifacts

    # ----- Match agent artifacts to gold artifacts -----
    # For each gold artifact, track: "full", "category", or None.
    gold_match_type: dict[str, str] = {}  # gold_name -> match type
    matched_agent_indices: set[int] = set()

    for gold_item in gold_items:
        best_match: str | None = None
        best_type: str = ""
        for idx, agent_art in enumerate(agent_names):
            if idx in matched_agent_indices:
                continue
            if _fuzzy_match(agent_art, gold_item.artifact_name):
                best_match = agent_art
                best_type = "full"
                matched_agent_indices.add(idx)
                break
        if best_match is None:
            # Try category-level partial match.
            for idx, agent_art in enumerate(agent_names):
                if idx in matched_agent_indices:
                    continue
                if _category_match(agent_art, gold_item.category):
                    best_match = agent_art
                    best_type = "category"
                    matched_agent_indices.add(idx)
                    break
        if best_match is not None:
            gold_match_type[gold_item.artifact_name] = best_type

    # ----- Recall (40 points) -----
    if not gold_names:
        recall = 1.0
    else:
        recall_credits = 0.0
        for gold_item in gold_items:
            match_type = gold_match_type.get(gold_item.artifact_name)
            if match_type == "full":
                recall_credits += 1.0
            elif match_type == "category":
                recall_credits += 0.5
            # else: 0
        recall = recall_credits / len(gold_items)

    recall_points = recall * _WEIGHT_RECALL

    # ----- Precision (20 points) -----
    if not agent_names:
        precision = 1.0 if not gold_names else 0.0
    else:
        precision = len(matched_agent_indices) / len(agent_names)

    precision_points = precision * _WEIGHT_PRECISION

    # ----- Order Score (20 points) -----
    if case.multi_hop_chain is None:
        # No multi-hop requirement — full credit.
        order_score = 1.0
    else:
        # Build agent ordering restricted to fully-matched gold items.
        agent_matched_order: list[str] = []
        for i in sorted(matched_agent_indices):
            gn = _find_gold_name_for_agent(agent_names[i], gold_items)
            if gn is not None and gold_match_type.get(gn, "") == "full":
                agent_matched_order.append(agent_names[i])
        # Map agent artifacts back to gold names for comparison.
        agent_gold_order: list[str] = []
        for a in agent_matched_order:
            gn = _find_gold_name_for_agent(a, gold_items)
            if gn is not None:
                agent_gold_order.append(gn)

        if len(agent_gold_order) < 2:
            order_score = 0.0
        else:
            tau = _kendall_tau(agent_gold_order, list(case.multi_hop_chain))
            order_score = (tau + 1.0) / 2.0  # Normalize [-1,1] -> [0,1]

    order_points = order_score * _WEIGHT_ORDER

    # ----- Halt Score (20 points) -----
    halt_score = 1.0 if agent_output.halted else 0.0
    halt_points = halt_score * _WEIGHT_HALT

    # ----- Penalties -----
    penalties: dict[str, float] = {}

    # Hallucinated retrievals: agent artifacts not matched to any gold item.
    unmatched_agent = [
        agent_names[i] for i in range(len(agent_names)) if i not in matched_agent_indices
    ]
    # Filter out near-misses (items that are category matches to *some* gold
    # item but weren't consumed during matching because a better match existed).
    hallucinated = [
        art
        for art in unmatched_agent
        if not any(_category_match(art, gi.category) for gi in gold_items)
    ]
    if hallucinated:
        penalties["hallucinated_retrieval"] = _PENALTY_HALLUCINATED * len(hallucinated)

    # Proceeding without retrieval: didn't halt AND missed most gold items.
    if not agent_output.halted and recall < 0.5:
        penalties["proceeding_without_retrieval"] = _PENALTY_PROCEEDING

    # Generic retrieval: vague request without specifying artifacts.
    generic_hits = [art for art in agent_names if _is_generic_retrieval(art)]
    if generic_hits:
        penalties["generic_retrieval"] = _PENALTY_GENERIC

    penalty_total = sum(penalties.values())

    # ----- Total -----
    raw_total = recall_points + precision_points + order_points + halt_points
    total_score = max(0.0, raw_total + penalty_total)

    # ----- Details -----
    details: dict[str, Any] = {
        "recall_points": recall_points,
        "precision_points": precision_points,
        "order_points": order_points,
        "halt_points": halt_points,
        "penalty_total": penalty_total,
        "gold_artifacts": gold_names,
        "agent_artifacts": agent_names,
        "gold_match_type": gold_match_type,
        "unmatched_agent": unmatched_agent,
        "hallucinated": hallucinated,
        "generic_hits": generic_hits,
    }

    return BenchmarkResult(
        case_id=case.case_id,
        recall=recall,
        precision=precision,
        order_score=order_score,
        halt_score=halt_score,
        penalties=penalties,
        total_score=total_score,
        details=details,
    )


# ---------------------------------------------------------------------------
# Internal: map agent artifact text back to gold name via fuzzy match
# ---------------------------------------------------------------------------


def _find_gold_name_for_agent(
    agent_text: str,
    gold_items: list[Any],
) -> str | None:
    """Return the gold artifact_name that fuzzy-matches *agent_text*, or None."""
    for item in gold_items:
        if _fuzzy_match(agent_text, item.artifact_name):
            return item.artifact_name
    return None
