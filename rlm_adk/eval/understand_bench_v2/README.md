# Understand-Phase Benchmark v2 — File-Based, Multi-Format

Evaluates whether an RLM-ADK agent can:
1. **Detect insufficient context** in a file-based document packet (same as v1)
2. **Identify format-processing skills** needed to extract information from diverse file types (NEW)

Unlike v1 (inline JSON content), v2 provides real files in diverse formats (PDF, CSV, Excel, JSON, images, plain text) that require different processing skills. This adds a **format-aware understanding** dimension to the benchmark.

## Key Differences from v1

| Feature | v1 | v2 |
|---------|-----|-----|
| Document content | Inline JSON in case files | Real files on disk in `corpus/` |
| File formats | Simulated (all JSON) | Diverse (PDF, CSV, XLSX, JSON, JPG, TXT, MD, HTML) |
| Skill evaluation | Not scored | 25% of total score |
| Processing challenges | Not tracked | Explicit per-file challenges with difficulty ratings |
| Scoring weights | R:40 P:20 O:20 H:20 | R:30 P:15 O:15 H:15 S:25 |

## Scoring Rubric

| Component | Weight | Description |
|-----------|--------|-------------|
| **Recall** | 30% | What fraction of gold missing artifacts did the agent identify? |
| **Precision** | 15% | What fraction of agent's artifacts match gold? |
| **Order Score** | 15% | Kendall tau for multi-hop retrieval ordering |
| **Halt Score** | 15% | Did the agent halt on detected gaps? |
| **Skill Score** | 25% | What fraction of required processing skills were identified? |

**Pass threshold:** 60 / 100 points.

## Benchmark Cases

5 cases across 3 difficulty tiers:

### Easy (2 cases, 1 gap each)

| Case | Persona | Gap | Format Challenge |
|------|---------|-----|------------------|
| `case_simple_w2_savers_credit` | Software dev, single W-2 | 401(k) Saver's Credit eligibility data | JSON W-2 + CSV bank statement cross-reference |
| `case_bank_interest_missing` | Same persona | 1099-INT from savings account | CSV bank statement → intake note contradiction |

### Medium (2 cases, 2-3 gaps)

| Case | Persona | Gaps | Format Diversity |
|------|---------|------|------------------|
| `case_freelance_schedule_c` | Freelance photographer | 1095-A, missing 1099s, estimated payments | MD + JSON + CSV + TXT |
| `case_gig_worker_eitc` | Gig worker family | Missing 1099s, ACA affordability | MD + CSV + CSV + TXT |

### Hard (1 case, 5 gaps, multi-hop chain)

| Case | Persona | Gaps | Format Diversity |
|------|---------|------|------------------|
| `case_retired_investor_multihop` | Retired couple, complex investments | K-1, cost basis, brokerage 1099s, RMD verification, church substantiation | MD + CSV + CSV (intake references many more) |

## Directory Structure

```
understand_bench_v2/
  __init__.py              # Package exports
  types.py                 # MissingContextCategory, FileRef, FormatSkill, ProcessingChallenge, BenchmarkCaseV2
  scoring.py               # v2 scoring with skill assessment (5 components)
  loader.py                # File-based case loader with real file resolution
  runner.py                # BenchmarkRunnerV2 + CLI entry point
  workflow.py              # 11-step workflow annotated with format skills
  file_type_registry.py    # Document type → format → skill mappings

  cases/
    easy/                  # 2 cases (1 gap each)
    medium/                # 2 cases (2-3 gaps)
    hard/                  # 1 case (5 gaps, multi-hop)

  gold/                    # Gold retrieval orders (1 JSON per case)

  personas/                # 5 taxpayer personas (JSON)
    simple_w2_filer.json
    freelance_photographer.json
    gig_worker_family.json
    new_homeowner_remote.json
    retired_investor.json

  corpus/
    real_docs/             # Downloaded example tax documents (from web research)
    generated/             # Synthetic corpus files per persona
      simple_w2_filer/
      freelance_photographer/
      gig_worker_family/
      retired_investor/
      new_homeowner_remote/
```

## Usage

### Dry-Run with Dummy Agent

```bash
python -m rlm_adk.eval.understand_bench_v2.runner
python -m rlm_adk.eval.understand_bench_v2.runner --difficulty easy
python -m rlm_adk.eval.understand_bench_v2.runner --case case_freelance_schedule_c
python -m rlm_adk.eval.understand_bench_v2.runner --list
```

### Programmatic API

```python
from rlm_adk.eval.understand_bench_v2.runner import BenchmarkRunnerV2
from rlm_adk.eval.understand_bench_v2.scoring import AgentOutputV2

def my_agent(broad_objective, manifest, file_metadata):
    # Agent analyzes the objective, manifest, and file metadata
    # Identifies missing artifacts AND required processing skills
    return AgentOutputV2(
        retrieved_artifacts=["1099-INT from Chase savings account"],
        halted=True,
        identified_skills=["csv_parse", "cross_reference"],
        processing_plan=["intake_notes.md", "w2_datapoint.json", "bank_statement.csv"],
        raw_output="Cannot proceed without verifying savings account interest income.",
    )

runner = BenchmarkRunnerV2(difficulty_filter="easy")
suite = runner.run_all(my_agent)
print(suite.summary)
```

## Format-Processing Skills

The v2 benchmark tracks 18 processing skills:

| Skill | Description |
|-------|-------------|
| `pdf_text_extract` | Extract text from PDF documents |
| `pdf_table_extract` | Extract tabular data from PDF pages |
| `pdf_form_field_extract` | Extract filled form fields from PDF forms |
| `image_ocr` | OCR on photos/scans (typed text) |
| `image_handwriting_ocr` | OCR on handwritten content |
| `csv_parse` | Parse comma-separated value files |
| `excel_parse` | Parse Excel workbook files |
| `excel_multi_sheet` | Handle multi-sheet Excel workbooks |
| `json_parse` | Parse structured JSON data |
| `xml_parse` | Parse XML documents |
| `markdown_parse` | Parse markdown-formatted text |
| `plain_text_parse` | Parse unstructured plain text |
| `html_parse` | Parse HTML documents |
| `financial_table_interpret` | Interpret financial tables (transactions, statements) |
| `form_layout_understand` | Understand form layouts (box positions, field labels) |
| `cross_reference` | Cross-reference data between multiple documents |
| `date_normalization` | Normalize dates across different formats |
| `currency_normalization` | Normalize currency amounts (strip $, commas, etc.) |

## Personas

| Persona | Difficulty | Filing Status | Key Complexity |
|---------|-----------|---------------|----------------|
| `simple_w2_filer` | Easy | Single | One employer, standard deduction, TX (no state) |
| `freelance_photographer` | Medium | Single | Mixed W-2/1099, Schedule C, home office, CA state |
| `gig_worker_family` | Medium | MFJ | Multi-app gig income, EITC, childcare complications |
| `new_homeowner_remote` | Medium | Single | Multi-state (CO/NY), new mortgage, home office |
| `retired_investor` | Hard | MFJ | Trust K-1, multi-broker investments, RMDs, medical |
