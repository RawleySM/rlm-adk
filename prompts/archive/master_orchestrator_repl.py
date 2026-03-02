"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MASTER ORCHESTRATOR — Neuro-Symbolic REPL Framework                       ║
║  Advanced patterns for llm_query-driven agentic pipelines                  ║
║                                                                            ║
║  Demonstrates:                                                             ║
║    1. Structured Control Planes (Pydantic-routed DAGs)                     ║
║    2. Deterministic Guardrails (hash dedup, substring grounding, retries)  ║
║    3. Boundary & Dependency Management (sliding windows, symbol injection) ║
║    4. Battlefield Report Telemetry (phase-aware stdout formatting)         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    Any,
    Callable,
    Generic,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from pydantic import BaseModel, Field, ValidationError, model_validator


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0 — STUBS (replace with real runtime bindings)
# ══════════════════════════════════════════════════════════════════════════════

def llm_query(prompt: str, context: str = "") -> str:
    """Synchronous call to a single LLM instance."""
    raise NotImplementedError("Bind to your runtime")

def llm_query_batched(prompts: list[str], contexts: list[str]) -> list[str]:
    """Fan-out to N parallel LLM instances."""
    raise NotImplementedError("Bind to your runtime")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — STRUCTURED CONTROL PLANE: Pydantic-Typed Decision Gates
# ══════════════════════════════════════════════════════════════════════════════
#
# Core idea: the LLM never returns free text to the orchestrator.  Every
# llm_query result is parsed into a Pydantic model whose fields become the
# *deterministic routing signal* for the next phase.  If parsing fails, the
# orchestrator enters a self-correction micro-loop (see Section 2).
#

class Disposition(str, Enum):
    """Routing enum — every record lands in exactly one bin."""
    EXACT_MATCH   = "exact_match"
    FUZZY_MATCH   = "fuzzy_match"
    NEEDS_CONTEXT = "needs_context"
    ANOMALY       = "anomaly"
    SKIP          = "skip"


class TriageDecision(BaseModel):
    """Schema the LLM MUST return for each record triage."""
    record_id: str
    disposition: Disposition
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=300)
    matched_entity_id: Optional[str] = None
    missing_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_match_has_entity(self) -> "TriageDecision":
        if self.disposition in (Disposition.EXACT_MATCH, Disposition.FUZZY_MATCH):
            if not self.matched_entity_id:
                raise ValueError(
                    f"disposition={self.disposition.value} requires matched_entity_id"
                )
        return self


class TriageBatch(BaseModel):
    """Wrapper for batch responses — enforces list-level invariants."""
    decisions: list[TriageDecision]
    batch_id: str
    processing_time_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Polymorphic routing: each Disposition maps to a handler function.
# The DAG is just a dict[Disposition, Callable] — no framework needed.
# ---------------------------------------------------------------------------

T = TypeVar("T")

@dataclass
class PhaseResult(Generic[T]):
    """Typed container for phase outputs, carrying forward provenance."""
    phase_name: str
    items: list[T]
    errors: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def build_triage_prompt(record: dict, schema_json: str, global_symbols: str) -> str:
    """
    Constructs the triage prompt.  Note: we inject the JSON schema *and*
    the global symbol table so the LLM is grounded against known entities.
    """
    return f"""You are a record-linkage triage agent.

## TASK
Classify the following record into exactly one disposition category and
return ONLY a JSON object conforming to the schema below.  No markdown
fences, no commentary.

## SCHEMA (Pydantic-generated)
{schema_json}

## GLOBAL SYMBOL TABLE (known entities — use these IDs for matches)
{global_symbols}

## RECORD
{json.dumps(record, indent=2)}

Return the JSON object now."""


def triage_phase(
    records: list[dict],
    known_entities: list[dict],
    batch_size: int = 25,
) -> PhaseResult[TriageDecision]:
    """
    PHASE 1: Broad Triage & Mapping
    --------------------------------
    Fan-out records in batches to parallel LLM instances.  Each instance
    returns a TriageBatch.  Failed parses enter the retry micro-loop.
    """
    schema_json = TriageDecision.model_json_schema()
    schema_str = json.dumps(schema_json, indent=2)

    # Build a condensed symbol table (ID + canonical name only)
    symbol_table = "\n".join(
        f"  {e['id']}: {e['canonical_name']}" for e in known_entities
    )

    all_decisions: list[TriageDecision] = []
    all_errors: list[dict[str, Any]] = []

    for batch_start in range(0, len(records), batch_size):
        batch = records[batch_start : batch_start + batch_size]
        prompts = [
            build_triage_prompt(r, schema_str, symbol_table) for r in batch
        ]
        contexts = ["" for _ in batch]  # no per-record context yet

        raw_responses = llm_query_batched(prompts, contexts)

        for idx, (record, raw) in enumerate(zip(batch, raw_responses)):
            global_idx = batch_start + idx
            try:
                decision = parse_with_retry(
                    raw_text=raw,
                    model_cls=TriageDecision,
                    record=record,
                    schema_str=schema_str,
                    symbol_table=symbol_table,
                    max_retries=2,
                )
                all_decisions.append(decision)
            except ExhaustedException as exc:
                all_errors.append({
                    "record_idx": global_idx,
                    "record_id": record.get("id", "UNKNOWN"),
                    "error": str(exc),
                    "last_raw": raw[:500],
                })

    return PhaseResult(
        phase_name="triage",
        items=all_decisions,
        errors=all_errors,
        metadata={
            "total_records": len(records),
            "batch_size": batch_size,
            "known_entities_count": len(known_entities),
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — DETERMINISTIC GUARDRAILS
# ══════════════════════════════════════════════════════════════════════════════
#
# The orchestrator never trusts an LLM response blindly.  Every response
# passes through a gauntlet of deterministic checks before it's accepted
# into the pipeline state.
#

class ExhaustedException(Exception):
    """Raised when all retry attempts for a single record are exhausted."""


def parse_with_retry(
    raw_text: str,
    model_cls: type[BaseModel],
    record: dict,
    schema_str: str,
    symbol_table: str,
    max_retries: int = 2,
) -> BaseModel:
    """
    GUARDRAIL 1 — Structured Parse + Self-Healing Retry Loop
    ---------------------------------------------------------
    Attempt to parse raw LLM output into the Pydantic model.
    On failure, feed the ValidationError back to the LLM as a
    correction prompt with the original record context preserved.
    """
    last_error = None
    raw = raw_text

    for attempt in range(1 + max_retries):
        # Strip markdown fences if present (common LLM habit)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            obj = json.loads(cleaned)
            instance = model_cls.model_validate(obj)

            # GUARDRAIL 2 — Substring grounding check
            # If the LLM claims an exact match, the matched entity ID
            # MUST exist in our symbol table.  This prevents hallucinated IDs.
            if hasattr(instance, "matched_entity_id") and instance.matched_entity_id:
                if instance.matched_entity_id not in symbol_table:
                    raise ValueError(
                        f"Hallucinated entity ID: {instance.matched_entity_id} "
                        f"not found in symbol table"
                    )

            return instance

        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            if attempt < max_retries:
                # Self-correction: feed the error back
                correction_prompt = f"""Your previous response failed validation.

## ERROR
{type(exc).__name__}: {exc}

## YOUR PREVIOUS OUTPUT (truncated)
{raw[:800]}

## ORIGINAL RECORD
{json.dumps(record, indent=2)}

## REQUIRED SCHEMA
{schema_str}

Fix the error and return ONLY the corrected JSON object."""

                raw = llm_query(correction_prompt, context=symbol_table)

    raise ExhaustedException(
        f"Failed after {1 + max_retries} attempts. Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# GUARDRAIL 3 — Content-hash deduplication ring
# Prevents duplicate processing across batches and across REPL turns.
# ---------------------------------------------------------------------------

class DeduplicationRing:
    """
    Maintains a set of SHA-256 hashes for records already processed.
    Survives across REPL turns because we serialize to a checkpoint file.
    """

    def __init__(self, checkpoint_path: str = "/tmp/dedup_ring.json"):
        self.checkpoint_path = checkpoint_path
        self._hashes: set[str] = set()
        self._load()

    def _load(self):
        try:
            with open(self.checkpoint_path) as f:
                self._hashes = set(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            self._hashes = set()

    def save(self):
        with open(self.checkpoint_path, "w") as f:
            json.dump(sorted(self._hashes), f)

    def content_hash(self, record: dict) -> str:
        canonical = json.dumps(record, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def is_duplicate(self, record: dict) -> bool:
        h = self.content_hash(record)
        return h in self._hashes

    def mark_processed(self, record: dict):
        self._hashes.add(self.content_hash(record))

    def deduplicate_batch(self, records: list[dict]) -> tuple[list[dict], int]:
        """Returns (unique_records, num_duplicates_skipped)."""
        unique = []
        skipped = 0
        for r in records:
            if self.is_duplicate(r):
                skipped += 1
            else:
                unique.append(r)
        return unique, skipped

    def __len__(self) -> int:
        return len(self._hashes)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — BOUNDARY & DEPENDENCY MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
#
# When datasets are too large for a single LLM context window, we chunk them.
# But naive chunking destroys cross-boundary relationships.  These patterns
# solve that.
#

@dataclass
class SlidingWindow:
    """
    Sliding-window chunker with read-only prefix overlap.

    The `prefix_ratio` controls how much of the previous chunk is re-injected
    as read-only context into the next chunk.  This maintains continuity
    without re-processing.

    Example with window_size=100, prefix_ratio=0.2:
      Chunk 0: records[0:100]
      Chunk 1: records[80:180]  ← records[80:100] are "read-only prefix"
      Chunk 2: records[160:260] ← records[160:180] are "read-only prefix"
    """
    window_size: int = 100
    prefix_ratio: float = 0.2  # 20% overlap

    @property
    def stride(self) -> int:
        return int(self.window_size * (1 - self.prefix_ratio))

    def chunks(self, data: list[Any]) -> list[tuple[list[Any], list[Any]]]:
        """
        Yields (prefix, actionable) tuples.
        - prefix: read-only context from previous window (for continuity)
        - actionable: new records to actually process in this window
        """
        result = []
        overlap = self.window_size - self.stride

        for start in range(0, len(data), self.stride):
            end = min(start + self.window_size, len(data))
            full_window = data[start:end]

            if start == 0:
                prefix = []
                actionable = full_window
            else:
                prefix = full_window[:overlap]
                actionable = full_window[overlap:]

            if actionable:  # don't yield empty final windows
                result.append((prefix, actionable))

        return result


def process_with_sliding_window(
    records: list[dict],
    known_entities: list[dict],
    window: SlidingWindow,
) -> PhaseResult[TriageDecision]:
    """
    Demonstrates sliding-window processing with global symbol injection.
    Each chunk gets:
      1. The global symbol table (known entities) — always available
      2. A read-only prefix of previously-seen records for continuity
      3. The actionable records to actually classify
    """
    schema_json = json.dumps(TriageDecision.model_json_schema(), indent=2)
    symbol_table = "\n".join(
        f"  {e['id']}: {e['canonical_name']}" for e in known_entities
    )

    all_decisions: list[TriageDecision] = []
    all_errors: list[dict] = []
    chunk_telemetry: list[dict] = []

    chunks = window.chunks(records)

    for chunk_idx, (prefix, actionable) in enumerate(chunks):
        prefix_context = ""
        if prefix:
            prefix_context = (
                "## PREVIOUSLY SEEN RECORDS (read-only context — do NOT re-classify)\n"
                + json.dumps(prefix, indent=2)
                + "\n\n"
            )

        # Fan-out the actionable records
        prompts = []
        for record in actionable:
            prompt = f"""{prefix_context}You are a record-linkage triage agent.

## TASK
Classify ONLY the record below.  The "previously seen" records above are
context only — they show what was already classified in the prior window.

## SCHEMA
{schema_json}

## GLOBAL SYMBOL TABLE
{symbol_table}

## RECORD TO CLASSIFY
{json.dumps(record, indent=2)}

Return ONLY the JSON object."""
            prompts.append(prompt)

        contexts = [symbol_table] * len(actionable)
        raw_responses = llm_query_batched(prompts, contexts)

        chunk_ok = 0
        chunk_err = 0

        for record, raw in zip(actionable, raw_responses):
            try:
                decision = parse_with_retry(
                    raw, TriageDecision, record, schema_json, symbol_table
                )
                all_decisions.append(decision)
                chunk_ok += 1
            except ExhaustedException as exc:
                all_errors.append({
                    "chunk_idx": chunk_idx,
                    "record_id": record.get("id"),
                    "error": str(exc),
                })
                chunk_err += 1

        chunk_telemetry.append({
            "chunk": chunk_idx,
            "prefix_size": len(prefix),
            "actionable_size": len(actionable),
            "ok": chunk_ok,
            "errors": chunk_err,
        })

    return PhaseResult(
        phase_name="sliding_window_triage",
        items=all_decisions,
        errors=all_errors,
        metadata={
            "window_size": window.window_size,
            "prefix_ratio": window.prefix_ratio,
            "total_chunks": len(chunks),
            "chunk_telemetry": chunk_telemetry,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — POLYMORPHIC DAG ROUTING
# ══════════════════════════════════════════════════════════════════════════════
#
# After triage, each Disposition routes to a specialized handler.
# This is a dynamic DAG — the shape of the graph is determined at runtime
# by the LLM's triage decisions.
#

def handle_exact_match(decisions: list[TriageDecision]) -> PhaseResult[dict]:
    """Phase 2A: Exact matches — validate and commit directly."""
    committed = []
    for d in decisions:
        committed.append({
            "record_id": d.record_id,
            "matched_to": d.matched_entity_id,
            "confidence": d.confidence,
            "action": "COMMIT",
        })
    return PhaseResult(phase_name="exact_match_commit", items=committed)


def handle_fuzzy_match(decisions: list[TriageDecision]) -> PhaseResult[dict]:
    """
    Phase 2B: Fuzzy matches — fan-out to a deeper comparison agent.
    Each fuzzy match gets a dedicated llm_query to produce a structured
    comparison report before human review.
    """
    prompts = []
    for d in decisions:
        prompts.append(f"""You are a record-comparison agent.

## TASK
The record {d.record_id} was fuzzy-matched to entity {d.matched_entity_id}
with confidence {d.confidence:.2f}.  The triage rationale was:
  "{d.rationale}"

Produce a structured comparison with these exact fields (JSON only):
{{
  "record_id": "...",
  "entity_id": "...",
  "field_agreements": ["field1", "field2"],
  "field_disagreements": [{{"field": "...", "record_val": "...", "entity_val": "..."}}],
  "recommendation": "ACCEPT" | "REJECT" | "HUMAN_REVIEW",
  "revised_confidence": 0.0-1.0
}}""")

    contexts = ["" for _ in prompts]
    raw_responses = llm_query_batched(prompts, contexts)

    results = []
    errors = []
    for d, raw in zip(decisions, raw_responses):
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            obj = json.loads(cleaned)
            results.append(obj)
        except (json.JSONDecodeError, KeyError) as exc:
            errors.append({"record_id": d.record_id, "error": str(exc)})

    return PhaseResult(phase_name="fuzzy_comparison", items=results, errors=errors)


def handle_needs_context(decisions: list[TriageDecision]) -> PhaseResult[dict]:
    """
    Phase 2C: Context-starved records — attempt enrichment via a
    secondary llm_query that receives the full document context.
    This is where you'd inject ERP-specific lookups, external API calls, etc.
    """
    enrichment_requests = []
    for d in decisions:
        enrichment_requests.append({
            "record_id": d.record_id,
            "missing_fields": d.missing_fields,
            "action": "ENQUEUE_FOR_ENRICHMENT",
            "rationale": d.rationale,
        })
    return PhaseResult(
        phase_name="enrichment_queue",
        items=enrichment_requests,
        metadata={"deferred_count": len(enrichment_requests)},
    )


def handle_anomaly(decisions: list[TriageDecision]) -> PhaseResult[dict]:
    """Phase 2D: Anomalies — quarantine for manual review."""
    quarantined = []
    for d in decisions:
        quarantined.append({
            "record_id": d.record_id,
            "disposition": d.disposition.value,
            "confidence": d.confidence,
            "rationale": d.rationale,
            "action": "QUARANTINE",
        })
    return PhaseResult(phase_name="anomaly_quarantine", items=quarantined)


# The DAG router — maps dispositions to handler functions
DISPOSITION_ROUTER: dict[Disposition, Callable] = {
    Disposition.EXACT_MATCH:   handle_exact_match,
    Disposition.FUZZY_MATCH:   handle_fuzzy_match,
    Disposition.NEEDS_CONTEXT: handle_needs_context,
    Disposition.ANOMALY:       handle_anomaly,
    # SKIP disposition intentionally has no handler — those records are dropped
}


def route_triage_results(
    triage_result: PhaseResult[TriageDecision],
) -> dict[str, PhaseResult]:
    """
    PHASE 2: Polymorphic Routing
    ----------------------------
    Bucket triage decisions by disposition, then fan-out to specialized
    handlers.  Returns a dict of phase results keyed by disposition.
    """
    buckets: dict[Disposition, list[TriageDecision]] = defaultdict(list)
    for decision in triage_result.items:
        buckets[decision.disposition].append(decision)

    phase_results: dict[str, PhaseResult] = {}

    for disposition, decisions in buckets.items():
        handler = DISPOSITION_ROUTER.get(disposition)
        if handler:
            phase_results[disposition.value] = handler(decisions)
        # else: SKIP — intentionally dropped

    return phase_results


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — HIERARCHICAL SUMMARIZATION (Map-Reduce over Documents)
# ══════════════════════════════════════════════════════════════════════════════
#
# For truly massive context (e.g., 500-page contracts), we use a two-pass
# map-reduce: first extract per-chunk summaries in parallel, then synthesize
# a global summary from the condensed outputs.
#

def hierarchical_summarize(
    document_chunks: list[str],
    extraction_schema: dict,
    global_question: str,
) -> dict:
    """
    Map-Reduce Summarization with Schema Enforcement
    --------------------------------------------------
    Pass 1 (Map):  Extract structured facts from each chunk in parallel.
    Pass 2 (Reduce): Synthesize all extractions into a single answer.

    The extraction_schema is injected into every Map prompt so all
    sub-agents return homogeneous, mergeable structures.
    """
    schema_str = json.dumps(extraction_schema, indent=2)

    # ── PASS 1: Parallel extraction ──
    map_prompts = []
    for i, chunk in enumerate(document_chunks):
        map_prompts.append(f"""You are a document extraction agent.

## TASK
Extract structured facts from the text below.  Return ONLY a JSON object
matching this schema:
{schema_str}

If a field has no evidence in this chunk, use null.

## CHUNK {i + 1} of {len(document_chunks)}
{chunk}

Return the JSON object now.""")

    map_contexts = ["" for _ in document_chunks]
    map_responses = llm_query_batched(map_prompts, map_contexts)

    # Parse and collect
    extractions = []
    for i, raw in enumerate(map_responses):
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            extractions.append(json.loads(cleaned))
        except json.JSONDecodeError:
            extractions.append({"_parse_error": True, "chunk_idx": i})

    # ── PASS 2: Reduce / Synthesize ──
    reduce_prompt = f"""You are a synthesis agent.

## TASK
You have received {len(extractions)} structured extractions from different
chunks of the same document.  Synthesize them into a single, coherent
answer to the following question:

  "{global_question}"

## EXTRACTIONS
{json.dumps(extractions, indent=2)}

Return a JSON object with these fields:
{{
  "answer": "your synthesized answer",
  "confidence": 0.0-1.0,
  "evidence_chunks": [list of chunk indices that contributed],
  "conflicts": ["any contradictions between chunks"]
}}"""

    reduce_response = llm_query(reduce_prompt)

    try:
        cleaned = reduce_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"_reduce_error": True, "raw": reduce_response[:500]}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — ADAPTIVE CONFIDENCE GATING
# ══════════════════════════════════════════════════════════════════════════════
#
# A meta-pattern: use the LLM's self-reported confidence to dynamically
# adjust batch sizes, retry budgets, and escalation thresholds.
#

@dataclass
class AdaptiveGate:
    """
    Adjusts processing parameters based on rolling confidence metrics.
    Low-confidence batches trigger smaller batch sizes (more LLM attention
    per record) and higher retry budgets.
    """
    high_confidence_threshold: float = 0.85
    low_confidence_threshold: float = 0.50
    min_batch_size: int = 5
    max_batch_size: int = 50
    default_batch_size: int = 25

    # Rolling state
    _recent_confidences: list[float] = field(default_factory=list)
    _window: int = 50

    def record_confidence(self, conf: float):
        self._recent_confidences.append(conf)
        if len(self._recent_confidences) > self._window:
            self._recent_confidences = self._recent_confidences[-self._window:]

    @property
    def rolling_mean(self) -> float:
        if not self._recent_confidences:
            return 0.5
        return sum(self._recent_confidences) / len(self._recent_confidences)

    @property
    def recommended_batch_size(self) -> int:
        mean = self.rolling_mean
        if mean >= self.high_confidence_threshold:
            return self.max_batch_size
        elif mean <= self.low_confidence_threshold:
            return self.min_batch_size
        else:
            # Linear interpolation
            ratio = (mean - self.low_confidence_threshold) / (
                self.high_confidence_threshold - self.low_confidence_threshold
            )
            return int(
                self.min_batch_size
                + ratio * (self.max_batch_size - self.min_batch_size)
            )

    @property
    def recommended_max_retries(self) -> int:
        if self.rolling_mean < self.low_confidence_threshold:
            return 3  # More retries for hard data
        return 1

    def telemetry(self) -> dict:
        return {
            "rolling_mean_confidence": round(self.rolling_mean, 4),
            "sample_size": len(self._recent_confidences),
            "recommended_batch_size": self.recommended_batch_size,
            "recommended_max_retries": self.recommended_max_retries,
        }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — EXEC SANDBOX FOR DYNAMIC CODE GENERATION
# ══════════════════════════════════════════════════════════════════════════════
#
# The most boundary-pushing pattern: ask the LLM to generate a Python
# function, then exec() it in a sandboxed namespace.  The orchestrator
# uses this to dynamically create data-cleaning transforms at runtime.
#

def generate_and_exec_transform(
    sample_records: list[dict],
    transform_description: str,
    allowed_imports: frozenset[str] = frozenset({"re", "json", "datetime"}),
) -> Callable[[dict], dict]:
    """
    Ask the LLM to write a Python transform function, validate it for
    safety, then exec() it into a callable.

    GUARDRAILS:
      - Only whitelisted imports are allowed
      - No __dunder__ access
      - No exec/eval/compile inside the generated code
      - Function must be named `transform` with signature (record: dict) -> dict
    """
    prompt = f"""You are a Python code generation agent.

## TASK
Write a Python function with this EXACT signature:

    def transform(record: dict) -> dict:
        ...

The function should: {transform_description}

## CONSTRAINTS
- You may ONLY import from: {sorted(allowed_imports)}
- Do NOT use exec, eval, compile, __import__, or any __dunder__ attributes
- The function must be pure (no side effects, no I/O)
- Return the modified record dict

## SAMPLE INPUT RECORDS
{json.dumps(sample_records[:3], indent=2)}

Return ONLY the Python code.  No markdown fences, no explanation."""

    raw_code = llm_query(prompt)

    # Strip markdown fences
    code = raw_code.strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # ── SAFETY CHECKS ──
    FORBIDDEN_TOKENS = {"exec(", "eval(", "compile(", "__import__", "os.", "subprocess",
                        "open(", "pathlib", "shutil", "sys.", "importlib"}
    for token in FORBIDDEN_TOKENS:
        if token in code:
            raise SecurityError(f"Generated code contains forbidden token: {token}")

    # Validate imports
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SecurityError(f"Generated code has syntax error: {exc}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in allowed_imports:
                    raise SecurityError(f"Disallowed import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] not in allowed_imports:
                raise SecurityError(f"Disallowed import: {node.module}")

    # ── EXEC IN SANDBOX ──
    sandbox: dict[str, Any] = {}
    exec(code, sandbox)

    if "transform" not in sandbox:
        raise SecurityError("Generated code does not define a 'transform' function")

    transform_fn = sandbox["transform"]

    # Smoke test against sample records
    for record in sample_records[:3]:
        result = transform_fn(record.copy())
        if not isinstance(result, dict):
            raise SecurityError(
                f"transform() returned {type(result).__name__}, expected dict"
            )

    return transform_fn


class SecurityError(Exception):
    """Raised when generated code fails safety validation."""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — BATTLEFIELD REPORT: Telemetry for the Closed Loop
# ══════════════════════════════════════════════════════════════════════════════
#
# Every phase ends by printing a highly condensed "Battlefield Report" to
# stdout.  This is the ONLY thing the Master Orchestrator (future-you)
# sees on the next REPL turn.  It must be high-signal, zero-noise.
#

def battlefield_report(
    phase_name: str,
    results: dict[str, PhaseResult],
    dedup_ring: DeduplicationRing,
    adaptive_gate: AdaptiveGate,
    wall_clock_s: float,
    unresolved_anomalies: list[dict] | None = None,
) -> str:
    """
    Format the Battlefield Report for stdout.
    Designed to be the sensory input for the next REPL turn.
    """
    lines = [
        "",
        "═" * 78,
        f"  BATTLEFIELD REPORT — Phase: {phase_name}",
        f"  Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"  Wall clock: {wall_clock_s:.2f}s",
        "═" * 78,
        "",
        "── DISPOSITION DISTRIBUTION ──",
    ]

    total_items = 0
    total_errors = 0

    for disposition, phase_result in sorted(results.items()):
        n = len(phase_result.items)
        e = len(phase_result.errors)
        total_items += n
        total_errors += e
        lines.append(f"  {disposition:.<30} {n:>5} items, {e:>3} errors")

    lines.extend([
        "",
        f"  TOTAL PROCESSED: {total_items}",
        f"  TOTAL ERRORS:    {total_errors}",
        f"  DEDUP RING SIZE: {len(dedup_ring)}",
        "",
        "── ADAPTIVE GATE STATE ──",
    ])

    gate_state = adaptive_gate.telemetry()
    for k, v in gate_state.items():
        lines.append(f"  {k}: {v}")

    if unresolved_anomalies:
        lines.extend([
            "",
            f"── UNRESOLVED ANOMALIES ({len(unresolved_anomalies)}) ──",
        ])
        for a in unresolved_anomalies[:10]:  # Cap display at 10
            lines.append(f"  • [{a.get('record_id', '?')}] {a.get('error', '')[:80]}")
        if len(unresolved_anomalies) > 10:
            lines.append(f"  ... and {len(unresolved_anomalies) - 10} more")

    lines.extend([
        "",
        "── NEXT ACTION REQUIRED ──",
        f"  Master Orchestrator: {total_errors} errors and "
        f"{len(unresolved_anomalies or [])} anomalies remain.",
    ])

    if total_errors > 0:
        lines.append(
            "  → RECOMMEND: Inspect error payloads, adjust schemas or prompts, "
            "then re-run failed subset."
        )
    if unresolved_anomalies:
        lines.append(
            "  → RECOMMEND: Triage anomalies into sub-categories. Consider "
            "generating a specialized transform via generate_and_exec_transform()."
        )
    if adaptive_gate.rolling_mean < adaptive_gate.low_confidence_threshold:
        lines.append(
            "  → WARNING: Rolling confidence is below threshold. "
            "Batch sizes have been automatically reduced. "
            "Consider enriching the symbol table or refining the triage prompt."
        )
    if total_errors == 0 and not unresolved_anomalies:
        lines.append("  → ALL CLEAR: Phase complete. Proceed to commit/export.")

    lines.extend(["", "═" * 78, ""])

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — FULL PIPELINE ORCHESTRATION (Entry Point)
# ══════════════════════════════════════════════════════════════════════════════
#
# This is what you'd actually run in the REPL.  Each call to `run_pipeline`
# is one "turn" in the closed loop.  The stdout it produces is designed
# to be read by the Master Orchestrator (you) on the next turn.
#

def run_pipeline(
    records: list[dict],
    known_entities: list[dict],
    checkpoint_path: str = "/tmp/dedup_ring.json",
    window_size: int = 100,
    prefix_ratio: float = 0.2,
) -> str:
    """
    Full pipeline execution — one REPL turn.
    Returns the Battlefield Report as a string (also printed to stdout).
    """
    t0 = time.time()

    # ── SETUP ──
    dedup = DeduplicationRing(checkpoint_path)
    gate = AdaptiveGate()
    window = SlidingWindow(window_size=window_size, prefix_ratio=prefix_ratio)

    # ── DEDUP ──
    unique_records, skipped = dedup.deduplicate_batch(records)
    print(f"[DEDUP] {skipped} duplicates skipped, {len(unique_records)} to process")

    # ── PHASE 1: Triage via sliding window ──
    triage_result = process_with_sliding_window(unique_records, known_entities, window)

    # Update adaptive gate with observed confidences
    for d in triage_result.items:
        gate.record_confidence(d.confidence)

    # Mark all processed records in dedup ring
    for record in unique_records:
        dedup.mark_processed(record)
    dedup.save()

    # ── PHASE 2: Route to specialized handlers ──
    routed_results = route_triage_results(triage_result)

    # ── BATTLEFIELD REPORT ──
    report = battlefield_report(
        phase_name="FULL_PIPELINE",
        results=routed_results,
        dedup_ring=dedup,
        adaptive_gate=gate,
        wall_clock_s=time.time() - t0,
        unresolved_anomalies=triage_result.errors,
    )

    print(report)
    return report


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — EXAMPLE REPL SESSION (Simulated Multi-Turn)
# ══════════════════════════════════════════════════════════════════════════════
#
# This shows what the REPL interaction looks like across multiple turns.
# Each block below represents what the Master Orchestrator would type/run
# in the REPL, and what stdout it would receive.
#

EXAMPLE_REPL_SESSION = """
# ─── TURN 1: Initial Load & Triage ───────────────────────────────────────────

>>> import json
>>> records = json.load(open("/data/hospital_vendors_raw.json"))
>>> entities = json.load(open("/data/master_vendor_db.json"))
>>> len(records), len(entities)
(12847, 3200)

>>> from master_orchestrator_repl import run_pipeline
>>> run_pipeline(records, entities, window_size=150, prefix_ratio=0.15)

# stdout →
# [DEDUP] 0 duplicates skipped, 12847 to process
# ══════════════════════════════════════════════════════════════════════════
#   BATTLEFIELD REPORT — Phase: FULL_PIPELINE
#   Timestamp: 2026-02-24 14:32:01 UTC
#   Wall clock: 847.32s
# ══════════════════════════════════════════════════════════════════════════
#
# ── DISPOSITION DISTRIBUTION ──
#   anomaly........................   127 items,   0 errors
#   exact_match....................  8934 items,   0 errors
#   fuzzy_match....................  2841 items,  14 errors
#   needs_context..................   732 items,   0 errors
#
#   TOTAL PROCESSED: 12634
#   TOTAL ERRORS:    14
#   DEDUP RING SIZE: 12847
#
# ── ADAPTIVE GATE STATE ──
#   rolling_mean_confidence: 0.7823
#   sample_size: 50
#   recommended_batch_size: 32
#   recommended_max_retries: 1
#
# ── UNRESOLVED ANOMALIES (213) ──
#   • [VND-4401] Failed after 3 attempts. Last error: ...
#   • [VND-8832] Failed after 3 attempts. Last error: ...
#   ... and 211 more
#
# ── NEXT ACTION REQUIRED ──
#   Master Orchestrator: 14 errors and 213 anomalies remain.
#   → RECOMMEND: Inspect error payloads, adjust schemas or prompts, ...
#   → RECOMMEND: Triage anomalies into sub-categories. Consider ...
# ══════════════════════════════════════════════════════════════════════════

# ─── TURN 2: Orchestrator reasons about telemetry, targets anomalies ─────────
#
# "213 anomalies is 1.7% — acceptable noise floor for first pass.
#  Let me categorize them and generate a specialized transform."

>>> from master_orchestrator_repl import generate_and_exec_transform
>>> import json
>>> anomalies = json.load(open("/tmp/anomaly_quarantine.json"))
>>> sample = anomalies[:5]

# Ask the LLM to create a cleaning function for the anomaly pattern
>>> clean_fn = generate_and_exec_transform(
...     sample_records=sample,
...     transform_description=(
...         "Normalize the 'vendor_name' field by removing legal suffixes "
...         "(LLC, Inc, Corp, Ltd), standardizing whitespace, and converting "
...         "to uppercase.  Also split 'address_line_1' into 'street' and "
...         "'suite' if a suite/unit number is present."
...     ),
... )

>>> # Smoke test
>>> clean_fn(sample[0])
{'vendor_name': 'MEDTRONIC', 'street': '710 MEDTRONIC PKWY', 'suite': 'STE 200', ...}

>>> # Apply to all anomalies and re-run through triage
>>> cleaned = [clean_fn(a) for a in anomalies]
>>> run_pipeline(cleaned, entities)

# stdout →  (second pass report with far fewer anomalies)

# ─── TURN 3: Final reconciliation ────────────────────────────────────────────
# "Only 12 anomalies left — these are genuinely novel vendors not in our
#  master DB.  Route them to the 'new vendor intake' workflow."
#
# >>> ...
"""


if __name__ == "__main__":
    print(__doc__)
    print("\nThis module is designed to be imported into a REPL environment.")
    print("See EXAMPLE_REPL_SESSION for usage patterns.")
    print("\nKey components:")
    print("  • triage_phase()             — Phase 1: Broad record triage")
    print("  • route_triage_results()     — Phase 2: Polymorphic DAG routing")
    print("  • process_with_sliding_window() — Chunked processing with overlap")
    print("  • parse_with_retry()         — Self-healing parse with retries")
    print("  • DeduplicationRing          — SHA-256 content dedup across turns")
    print("  • AdaptiveGate               — Confidence-driven batch tuning")
    print("  • generate_and_exec_transform() — LLM-generated code with sandbox")
    print("  • battlefield_report()       — Structured telemetry for the loop")
    print("  • run_pipeline()             — Full single-turn orchestration")
    print("  • hierarchical_summarize()   — Map-reduce document extraction")
