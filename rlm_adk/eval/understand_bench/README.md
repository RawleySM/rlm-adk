# Understand-Phase Benchmark Suite

Evaluates whether an RLM-ADK agent can detect **insufficient context** during the Understand phase and emit a correct `retrieval_order` artifact identifying missing external dependencies.

The benchmark does **not** score final task accuracy. It scores **insufficiency detection**, **dependency discovery**, and **retrieval sequencing**.

## Current State: Corpus Is Not Wired

The `corpus/` directory contains ~459 MB of synthetic documents (37 template generators, per-persona output, bulk output) and 12 real tax documents retrieved from Google Drive. **None of this is loaded by the benchmark.**

All 5 benchmark cases are self-contained JSON fixtures in `cases/`. Each case's `provided_context_dict` contains document content embedded inline as literal JSON values. The loader (`loader.py`) reads the case JSON, validates it, and injects a `_manifest` -- it does not resolve file references or read from the corpus.

To make the corpus useful, one of the following would need to happen:
- Update `loader.py` to resolve file references from `provided_context_dict` into corpus files
- Author new cases that reference corpus documents instead of embedding content inline
- Use the corpus as a haystack/noise layer for harder benchmark variants

Until then, the benchmark runs entirely off the inline content in `cases/{easy,medium,hard}/*.json`.

## Why This Exists

In complex, multi-source tasks (like tax return preparation), agents face a critical decision point: do they have enough information to proceed, or are they missing authoritative documents, credentials, or attestations that cannot be derived from what's provided? A weak agent plows ahead with incomplete information. A strong agent halts, names what's missing, explains where to get it, and sequences the retrieval correctly.

This benchmark measures that capability.

## Missing-Context Taxonomy

Every gap in provided context falls into one of 9 categories:

| Category | What's Missing | Example |
|----------|---------------|---------|
| `DOCUMENT` | An authoritative document is absent | A W-2 from a second employer |
| `CREDENTIAL` | Authentication or identity token needed | Prior-year AGI for e-file verification |
| `AGENT_SKILL` | Agent lacks a processing capability | OCR for a scanned receipt |
| `HISTORICAL_RECORD` | Prior-period data that can't be reconstructed | AMT credit carryforward amount |
| `THIRD_PARTY_RECORD` | Record held by an external institution | IRS payment transcript |
| `USER_ATTESTATION` | A fact only the user can assert | Dependent residency calendar |
| `REGULATORY_REFERENCE` | Current-year statute, rule, or threshold | State-specific apportionment rules |
| `COMPUTATIONAL_PREREQ` | An intermediate result that must be derived first | Adjusted basis after depreciation |
| `CROSS_DOMAIN_LINK` | A reference in one doc reveals a new retrieval surface | A K-1 referencing a trust's Form 1041 |

Each missing artifact also carries a **difficulty modifier**: `direct` (explicitly stated), `inferential` (implied by signals + domain knowledge), or `multi-hop` (one retrieval reveals the next).

## Scoring Rubric

| Component | Weight | Description |
|-----------|--------|-------------|
| **Recall** | 40% | What fraction of gold missing artifacts did the agent identify? Full match = 1.0 credit, category-level match = 0.5 credit. |
| **Precision** | 20% | What fraction of the agent's retrieved artifacts match gold items? Penalizes over-retrieval. |
| **Order Score** | 20% | For multi-hop cases, Kendall tau rank correlation between agent's retrieval order and the gold dependency chain. Non-multi-hop cases get full credit. |
| **Halt Score** | 20% | Did the agent explicitly halt and say it cannot proceed? Binary 0 or 1. |

**Penalties** (deducted from the weighted total):

| Penalty | Points | Trigger |
|---------|--------|---------|
| Hallucinated retrieval | -5 each | Agent names an artifact that doesn't match any gold item (even at category level) |
| Proceeding without retrieval | -20 | Agent didn't halt AND missed >50% of gold items |
| Generic retrieval | -10 | Agent makes vague requests like "need more information" instead of naming specific artifacts |

**Pass threshold:** 60 / 100 points.

## Benchmark Cases

5 cases across 3 difficulty tiers:

### Easy (1 gap each)

| Case | Persona | Gap | Category | Modifier |
|------|---------|-----|----------|----------|
| `case_efile_auth` | First-time e-filer, single W-2 | Prior-year AGI or IP PIN | `CREDENTIAL` | direct |
| `case_estimated_payments` | Side hustler, W-2 + 1099-NEC | IRS estimated tax payment record | `THIRD_PARTY_RECORD` | inferential |

### Medium (2-3 gaps)

| Case | Persona | Gaps | Categories |
|------|---------|------|------------|
| `case_dependent_eligibility` | Blended family, MFJ with nephew | Residency calendar + support attestation | `USER_ATTESTATION` |
| `case_marketplace_insurance` | Gig economy, HOH | 2x Form 1095-A + scholarship breakdown | `DOCUMENT`, `THIRD_PARTY_RECORD` |

### Hard (4 gaps, multi-hop chain)

| Case | Persona | Gaps | Chain |
|------|---------|------|-------|
| `case_k1_multi_hop` | Investor with trust K-1 | Trust 1041 -> QBI worksheet -> UBIA carryforward -> AMT credit | `CROSS_DOMAIN_LINK`, `HISTORICAL_RECORD` |

## Directory Structure

```
understand_bench/
  __init__.py              # Package exports
  types.py                 # MissingContextCategory, MissingContextItem, BenchmarkCase, etc.
  scoring.py               # Scoring rubric implementation
  loader.py                # Case discovery, loading, manifest injection
  runner.py                # BenchmarkRunner + CLI entry point
  workflow.py              # 11-step tax-preparation workflow model
  file_type_registry.py    # 32 document types (IRS forms, third-party, government, user)
  benchmark_build_agent_summary.md  # Build session trace summary

  cases/
    easy/                  # 2 cases (1 gap each)
    medium/                # 2 cases (2-3 gaps)
    hard/                  # 1 case (4 gaps, multi-hop)

  gold/                    # Gold retrieval orders (1 JSON per case)

  personas/                # 8 taxpayer persona profiles (JSON)

  corpus/
    __init__.py
    templates/             # 37 synthetic document generators (see below)
      __init__.py          # Exports all generate_*() functions
    context/
      real_docs/           # 12 real tax documents retrieved from Google Drive (PDFs + HEIC)
      generated/
        <persona>/         # Per-persona docs (8 dirs, ~452K total)
        bulk/ - bulk5/     # 5 bulk batches (~106K docs each, ~459 MB per batch)
        _supplemental/     # Supplemental generated docs
        MANIFEST.json      # Corpus manifest
    generate_corpus.py     # Per-persona generation script
    generate_bulk_corpus.py  # Bulk generator (~106K docs/run at ~6,300 docs/sec)
    generate_missing_types.py  # Gap-fill generator for brokerage + handwritten notes
    images/                # Placeholder for document images
```

**Corpus size:** ~549K files, 2.3 GB total

## Usage

### Dry-Run with Dummy Agent

The runner includes a built-in dummy agent that always halts with no retrievals. Useful for verifying the harness works:

```bash
# Run all cases
python -m rlm_adk.eval.understand_bench.runner

# Filter by difficulty
python -m rlm_adk.eval.understand_bench.runner --difficulty easy

# Run a single case
python -m rlm_adk.eval.understand_bench.runner --case case_k1_multi_hop
```

### Programmatic API

```python
from rlm_adk.eval.understand_bench.runner import BenchmarkRunner
from rlm_adk.eval.understand_bench.scoring import AgentRetrievalOutput

# Define your agent function
def my_agent(broad_objective: str, provided_context: dict) -> AgentRetrievalOutput:
    # Your agent analyzes the objective and context,
    # identifies missing artifacts, and decides whether to halt.
    return AgentRetrievalOutput(
        retrieved_artifacts=["Prior-year AGI or IP PIN"],
        halted=True,
        raw_output="Cannot proceed without e-file authentication credentials.",
    )

# Run the benchmark
runner = BenchmarkRunner(difficulty_filter="easy")

# List available cases
for case in runner.list_cases():
    print(f"  [{case['difficulty']}] {case['case_id']}")

# Run a single case
result = runner.run_case("case_efile_auth", my_agent)
print(f"Score: {result.total_score:.1f} / {result.max_possible_score:.1f}")
print(f"Recall: {result.recall:.2f}, Precision: {result.precision:.2f}")

# Run the full suite
suite = runner.run_all(my_agent)
print(suite.summary)
```

### Loading Cases Directly

```python
from rlm_adk.eval.understand_bench.loader import load_case, load_case_with_gold

# Load a case with injected _manifest
case = load_case("rlm_adk/eval/understand_bench/cases/easy/case_efile_auth.json")
print(case.broad_objective)
print(case.provided_context_dict.keys())  # includes "_manifest"

# Load with gold retrieval order
case, gold = load_case_with_gold("rlm_adk/eval/understand_bench/cases/hard/case_k1_multi_hop.json")
print(gold)  # ["Trust Form 1041", "QBI detail worksheet from trust", ...]
```

### Scoring Standalone

```python
from rlm_adk.eval.understand_bench.scoring import score_result, AgentRetrievalOutput
from rlm_adk.eval.understand_bench.loader import load_case

case = load_case("rlm_adk/eval/understand_bench/cases/easy/case_efile_auth.json")

# Perfect agent
perfect = AgentRetrievalOutput(
    retrieved_artifacts=["Prior-year AGI or IP PIN"],
    halted=True,
)
result = score_result(case, perfect)
assert result.total_score == 100.0

# Agent that proceeds without identifying gaps
bad = AgentRetrievalOutput(
    retrieved_artifacts=[],
    halted=False,
)
result = score_result(case, bad)
assert result.total_score == 0.0  # 0 recall, 0 halt, -20 penalty
```

## Document Corpus

The benchmark ships with a 2.3 GB corpus covering all 37 document types from the plan's Section 9 File Type Registry. The corpus includes both synthetic generated documents and real tax documents retrieved from Google Drive.

### Real Documents (12 files, ~15 MB)

Retrieved from the taxpayer's Google Drive via Chrome browser automation:

- Federal tax returns: 2009, 2021, 2022 (x2), 2023 (x2), 2024
- W-2 forms: 2021 (PDF + HEIC photo)
- Payslips: Stryker payslips
- Pension statements: 2024-2025

Located in `corpus/context/real_docs/`.

### Synthetic Document Templates (37 generators)

All templates follow the same pattern: a `generate_*()` function returning a dict (or CSV/markdown string for some types).

**IRS Forms (14):** W-2, 1099-INT, 1099-DIV, 1099-NEC, 1099-MISC, 1099-B, 1099-R, 1099-G, K-1, 1098, 1098-T, 1098-E, 1095-A, 5498

**Third-Party Documents (10):** Bank statement, brokerage statement, mortgage closing disclosure, property tax bill, childcare receipt, charitable receipt, medical expense summary, insurance payout letter, FEMA assistance letter, employer relocation record

**Government/Regulatory (6):** IRS transcript, IP PIN letter, prior-year return, state tax summary, IRS notice, state nexus determination

**User-Generated (7):** Intake notes, email correspondence, mileage log, home office measurements, residency calendar, support attestation, handwritten notes

```python
from rlm_adk.eval.understand_bench.corpus.templates import (
    generate_w2,
    generate_1099_nec,
    generate_1099_b,
    generate_k1,
    generate_1098,
    generate_1095_a,
    generate_bank_statement,       # returns CSV string
    generate_brokerage_statement,  # returns CSV string
    generate_intake_notes,         # returns markdown string
    # ... 28 more generators
)

w2 = generate_w2()       # dict with W-2 fields
nec = generate_1099_nec() # dict with 1099-NEC fields
```

### Generating the Corpus

```bash
# Per-persona generation (99 docs, ~452K)
python rlm_adk/eval/understand_bench/corpus/generate_corpus.py

# Bulk generation (~106K docs per run, ~459 MB)
python rlm_adk/eval/understand_bench/corpus/generate_bulk_corpus.py

# Gap-fill for brokerage + handwritten notes
python rlm_adk/eval/understand_bench/corpus/generate_missing_types.py
```

## How Cases Are Constructed

Each benchmark case is a JSON file containing:

- **`broad_objective`** -- what the agent is asked to accomplish
- **`provided_context_dict`** -- a filename-to-content mapping simulating an uploaded document packet (with an injected `_manifest` listing all documents)
- **`missing_artifacts`** -- the gold-standard list of missing context items with category, source authority, detection signals, and retrieval methods
- **`gold_retrieval_order`** -- the correct sequence for retrieving missing artifacts
- **`why_context_tempts_premature_progress`** -- explains why a weak agent might skip the gap
- **`what_bad_model_does`** / **`what_good_model_does`** -- behavioral descriptions for calibration
- **`multi_hop_chain`** -- (hard cases only) the dependency chain where one retrieval reveals the next

Cases are designed so the provided context is **just complete enough to tempt** an agent into proceeding, while containing detectable signals that a careful agent will identify as gaps.

## Personas

8 taxpayer personas provide realistic filing scenarios across varying complexity:

| Persona | Difficulty Target | Filing Status | Key Complexity |
|---------|-------------------|---------------|----------------|
| `first_time_efiler` | Easy | Single | One W-2, never e-filed |
| `side_hustler` | Easy | Single | W-2 + 1099-NEC freelance |
| `blended_family` | Medium | MFJ | Nephew dependency claim |
| `new_homeowner` | Medium | MFJ | Rental conversion |
| `disaster_survivor` | Medium | MFJ | FEMA disaster losses |
| `gig_economy` | Hard | HOH | Multiple 1099s, marketplace insurance |
| `investor_trust` | Hard | Single | K-1 pass-through, AMT history |
| `multi_state` | Hard | Single | Multi-state 1099-NEC |

## Design Reference

See `understand_bench_plan.md` for the full implementation plan, including the connection to the Polya Understand methodology, the benchmark construction DAG, and the detailed category definitions.
