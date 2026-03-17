# Understand-Phase Benchmark: Implementation Plan

<!-- created: 2026-03-13 -->
<!-- source: prompts/Undertand_Benchmark.md -->
<!-- reference: rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md -->
<!-- reference: rlm_adk_docs/vision/polya_topology_engine.md -->

## 1. Purpose

This document is a DAG-structured implementation plan for building an
**Understand-phase benchmark suite** targeting the tax-return-preparation
domain. The benchmark evaluates whether an RLM-ADK instance can detect
insufficient context during the Understand phase and emit a correct
`retrieval_order` artifact identifying missing external dependencies.

The benchmark does **not** score final tax accuracy. It scores
**insufficiency detection**, **dependency discovery**, and **retrieval
sequencing**.

---

## 2. Missing-Context Taxonomy

Before building benchmark cases, we need a typed classification of how missing
context manifests across long-running, multi-source, multi-step agent tasks.
Each class has distinct detection signatures, retrieval mechanics, and
difficulty characteristics.

### 2.1 Type Hierarchy

```python
from enum import Enum
from pydantic import BaseModel


class MissingContextCategory(str, Enum):
    """Top-level classification of missing context."""

    DOCUMENT = "document"                # An authoritative document is absent
    CREDENTIAL = "credential"            # Authentication or identity artifact missing
    AGENT_SKILL = "agent_skill"          # Agent lacks a processing capability
    HISTORICAL_RECORD = "historical"     # Prior-period or longitudinal data missing
    THIRD_PARTY_RECORD = "third_party"   # Record held by external institution
    USER_ATTESTATION = "user_attestation"  # User must supply a sworn/signed fact
    REGULATORY_REFERENCE = "regulatory"  # Current-year statute, rule, or threshold
    COMPUTATIONAL_PREREQ = "computational"  # An intermediate result must be derived first
    CROSS_DOMAIN_LINK = "cross_domain"   # A reference in one doc unveils a new domain


class MissingContextItem(BaseModel):
    """A single missing-context entry in a benchmark case."""

    category: MissingContextCategory
    artifact_name: str              # e.g. "Prior-year AGI"
    source_authority: str           # e.g. "IRS e-file records"
    why_non_derivable: str          # explanation of non-derivability
    detection_signal: str           # what in the provided context hints at absence
    retrieval_method: str           # how agent should propose to acquire it
    blocks_downstream: list[str]    # which planning/execution steps are blocked
    difficulty_modifier: str        # "direct" | "inferential" | "multi-hop"
```

### 2.2 Category Definitions

| Category | Definition | Tax-Domain Example |
|----------|------------|-------------------|
| **DOCUMENT** | A complete document (form, statement, letter) is missing from the provided packet | W-2 from a second employer the agent can infer exists from bank deposit patterns |
| **CREDENTIAL** | An authentication or identity token required for a system interaction | IP PIN for e-file, prior-year AGI for identity verification |
| **AGENT_SKILL** | The agent lacks a capability needed to process an artifact that *is* present | PDF extraction for a scanned 1098-T, OCR for a photographed receipt |
| **HISTORICAL_RECORD** | A fact from a prior period that cannot be reconstructed from current data | Prior-year elected carryforward of a capital loss, AMT credit carryforward |
| **THIRD_PARTY_RECORD** | A record held by an institution outside the taxpayer's immediate control | IRS payment transcript, state estimated payment ledger, employer EIN confirmation |
| **USER_ATTESTATION** | A fact that only the user can authoritatively assert | Dependent residency calendar, support-percentage attestation, foreign account disclosure |
| **REGULATORY_REFERENCE** | A current-year statute, threshold, or rule the agent must ground in | Current-year standard deduction amount, EITC phase-out thresholds, state-specific credit rules |
| **COMPUTATIONAL_PREREQ** | An intermediate result that must be computed before the main task can proceed | Adjusted basis of a rental property after years of depreciation |
| **CROSS_DOMAIN_LINK** | A reference in one document that reveals an entirely new retrieval surface | A K-1 schedule that references a trust, requiring trust tax return history |

### 2.3 Difficulty Modifiers

Each missing-context item carries a difficulty modifier:

- **Direct**: The provided context explicitly mentions the artifact's absence
  or the need for it (e.g., "attach prior-year AGI").
- **Inferential**: The provided context contains signals that, combined with
  domain knowledge, imply the artifact is needed (e.g., a note about "quarterly
  payments" implies estimated payment records).
- **Multi-hop**: Retrieving one artifact reveals the need for another (e.g.,
  retrieving a K-1 reveals a trust, which requires the trust's Form 1041).

---

## 3. Polya Understand Phase → Benchmark Connection

The Polya Understand methodology
(`rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md`) defines
14 steps. Not all steps are equally relevant to insufficiency detection. Below
we map each step to its role in the benchmark evaluation and show how it
connects to the agent-under-evaluation logically identifying a missing piece of
context.

### 3.1 Polya Step → Benchmark Relevance Map

| # | Polya Step | Benchmark Role | How It Surfaces Missing Context |
|---|-----------|----------------|-------------------------------|
| 1 | **Restate the problem** | Establishes the task scope | Restating "prepare and submit" forces the agent to recognize that submission has authentication prerequisites beyond preparation |
| 2 | **Identify the objective** | Defines the deliverable | Precision here reveals whether the agent distinguishes "compute liability" from "file electronically" — each has different context requirements |
| 3 | **Inventory the givens** | Core benchmark mechanic | The systematic cataloging of provided documents is where gaps first become visible. A document inventory that finds 3 W-2s when bank records suggest 4 income sources detects a DOCUMENT gap |
| 4 | **Identify unknowns and relationships** | Dependency chain construction | This step builds the chain from knowns to unknowns. It exposes COMPUTATIONAL_PREREQ gaps (e.g., "I need adjusted basis but only have purchase price") and CROSS_DOMAIN_LINK gaps (e.g., "this K-1 references a trust I have no records for") |
| 5 | **Clarify terms** | Detects REGULATORY_REFERENCE gaps | When the agent encounters a term like "qualified business income deduction" it must verify it has the current-year rules, not just general knowledge |
| 6 | **Diagram/externalize structure** | Reveals structural gaps | Drawing a dependency graph of the return exposes orphan nodes — income sources with no supporting documents, credits claimed with no eligibility proof |
| 7 | **Separate facts from assumptions** | Critical benchmark discriminator | This is the step where a good agent says "I am *assuming* the dependent lived here >6 months, but I have no residency record" — directly producing USER_ATTESTATION gaps |
| 8 | **Check completeness** | Primary scoring target | The well-posedness judgment IS the `retrieval_order` output. A problem judged "underdetermined" with specific missing items maps directly to the benchmark's gold standard |
| 9 | **Establish constraints** | Surfaces CREDENTIAL gaps | Constraints like "must e-file" or "must file by deadline" surface authentication and procedural prerequisites |
| 10 | **Identify problem type** | Classifies task complexity | Recognizing "this is a multi-state filing with pass-through income" reclassifies the task and expands the evidence surface |
| 11 | **Generate small examples** | Detects HISTORICAL_RECORD gaps | Testing a toy case ("if quarterly payments were $5000 each...") forces the agent to realize it needs actual payment amounts |
| 12 | **Canonical Pólya questions** | Structured gap detection | "Is the condition sufficient?" directly asks whether the provided context is enough |
| 13 | **Define boundaries** | Scopes the retrieval order | Prevents over-retrieval by bounding what is in scope |
| 14 | **Reformulate operationally** | Final gap synthesis | The operational reformulation must include all prerequisites; any remaining unknowns become the `retrieval_order` |

### 3.2 Key Insight: Cross-Domain Link Discovery

One document can unveil an entirely new exploration surface. This is the most
interesting benchmark pattern because it tests multi-hop reasoning:

**Example chain:**
1. Provided context includes a brokerage statement showing a K-1 distribution
2. Agent retrieves the K-1 (first retrieval)
3. K-1 Box 20 contains a code for "Section 199A information"
4. Agent realizes it needs the entity's QBI worksheet (second retrieval)
5. QBI worksheet references a prior-year UBIA carryforward (third retrieval)

Each retrieval changes the agent's understanding of what it still doesn't know.
This maps directly to the Polya topology engine's concept of
**topology invalidation** — where missing-information discovery invalidates the
current understanding and forces reclassification
(`rlm_adk_docs/vision/polya_topology_engine.md`, "Retrieval-Aware Understand"
section).

### 3.3 Connection to UnderstandArtifact Schema

The Polya topology engine (`rlm_adk_docs/vision/polya_topology_engine.md`)
defines an `UnderstandArtifact` schema with fields:

- `understanding_status`: maps to benchmark pass/fail — `blocked` or `partial`
  is the *correct* status for benchmark cases
- `missing_prerequisites`: maps directly to the scored `retrieval_order`
- `prerequisite_scope`: maps to our `MissingContextCategory`
- `can_continue_without_it`: should be `False` for well-designed benchmark cases
- `retrieval_candidates`: the ordered retrieval list we score against

The benchmark therefore serves as a **validation suite for the
UnderstandArtifact emission pipeline**. A system that passes the benchmark is
one that correctly populates this artifact.

---

## 4. Benchmark Construction DAG

The following DAG defines the phases of benchmark construction. Each node is a
phase; edges represent dependencies. Phases without dependencies on each other
can be executed in parallel.

```
                    ┌──────────────────────┐
                    │  N0: Define Taxonomy  │
                    │  (Missing-Context     │
                    │   Type System)        │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  N1: Design Persona   │
                    │  Profiles             │
                    │  (Taxpayer archetypes)│
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                 │
   ┌──────────▼─────┐  ┌──────▼───────┐  ┌─────▼──────────┐
   │ N2: Decompose  │  │ N3: Build    │  │ N4: Define     │
   │ Tax Workflow   │  │ Context      │  │ File Type      │
   │ into Steps     │  │ Document     │  │ Registry       │
   │                │  │ Corpus       │  │                │
   └───────┬────────┘  └──────┬───────┘  └──────┬─────────┘
           │                  │                  │
           └──────────────────┼──────────────────┘
                              │
                   ┌──────────▼───────────┐
                   │  N5: Author Benchmark│
                   │  Cases               │
                   │  (12+ tasks across   │
                   │   difficulty ladder)  │
                   └──────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
   ┌──────────▼─────┐ ┌──────▼──────┐ ┌──────▼──────────┐
   │ N6: Build      │ │ N7: Define  │ │ N8: Build       │
   │ Gold Retrieval │ │ Scoring     │ │ provided_context│
   │ Orders         │ │ Rubric      │ │ _dict Loader    │
   └───────┬────────┘ └──────┬──────┘ └──────┬──────────┘
           │                 │               │
           └─────────────────┼───────────────┘
                             │
                  ┌──────────▼───────────┐
                  │  N9: Assemble        │
                  │  Benchmark Suite     │
                  │  (JSON fixtures +    │
                  │   runner integration)│
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │  N10: Validation     │
                  │  (Dry-run against    │
                  │   known-good and     │
                  │   known-bad agents)  │
                  └──────────────────────┘
```

### 4.1 Node Descriptions

#### N0: Define Taxonomy (Missing-Context Type System)
**Inputs:** Domain analysis, Polya methodology review
**Outputs:** `MissingContextCategory` enum, `MissingContextItem` model
**Status:** Defined in Section 2 of this document

#### N1: Design Persona Profiles
**Inputs:** N0 (taxonomy)
**Outputs:** 6–10 taxpayer persona archetypes with varying complexity
**Details:**
- Each persona defines a household structure, income profile, life events, and
  filing complexity
- Personas are designed to exercise different missing-context categories
- See Section 6 for persona specifications

#### N2: Decompose Tax Workflow into Steps
**Inputs:** N1 (personas)
**Outputs:** Step-by-step task decomposition for tax preparation and submission
**Details:**
- Break the broad "prepare and submit" objective into discrete steps
- Identify which steps have external dependencies
- Map steps to missing-context categories
- See Section 7 for workflow decomposition

#### N3: Build Context Document Corpus
**Inputs:** N1 (personas), N4 (file types)
**Outputs:** Synthetic documents (W-2s, 1099s, receipts, letters, etc.)
**Details:**
- Generate realistic but synthetic context documents for each persona
- Intentionally omit specific critical documents
- See Section 8 for context construction methodology

#### N4: Define File Type Registry
**Inputs:** N0 (taxonomy)
**Outputs:** Catalog of all file types expected in tax workflows
**Details:**
- Enumerate document types, their formats, and their roles
- See Section 9 for the file type registry

#### N5: Author Benchmark Cases
**Inputs:** N2 (workflow steps), N3 (document corpus), N4 (file types)
**Outputs:** 12+ benchmark task definitions with difficulty ladder
**Details:**
- Each case pairs a broad objective with a rich `provided_context_dict`
- Each case has intentionally missing artifacts
- Cases span easy / medium / hard difficulty
- See Section 10 for case authoring guidelines

#### N6: Build Gold Retrieval Orders
**Inputs:** N5 (benchmark cases)
**Outputs:** Scored `retrieval_order` gold standard for each case
**Details:**
- Define the correct ordered list of missing artifacts per case
- Include partial-credit scoring for subset matches
- Define sequencing requirements for multi-hop cases

#### N7: Define Scoring Rubric
**Inputs:** N5 (benchmark cases), N6 (gold retrieval orders)
**Outputs:** Scoring functions and metrics
**Details:**
- Precision/recall on retrieved artifact set
- Order-sensitivity scoring for dependency chains
- Penalty for hallucinated or unnecessary retrievals
- Partial credit rules

#### N8: Build `provided_context_dict` Loader
**Inputs:** N3 (document corpus), N4 (file types)
**Outputs:** REPL-loadable context variable builder
**Details:**
- Loader that assembles documents into the `provided_context_dict` structure
- Supports multiple file formats (see Section 9)
- Integrates with RLM-ADK's REPL session context

#### N9: Assemble Benchmark Suite
**Inputs:** N6, N7, N8
**Outputs:** Complete benchmark fixture files (JSON), runner configuration
**Details:**
- Package cases, gold standards, and scoring into a runnable suite
- Integrate with existing `rlm_adk/eval/` infrastructure

#### N10: Validation
**Inputs:** N9 (assembled suite)
**Outputs:** Validation report
**Details:**
- Dry-run with a "known-good" agent (expected to detect gaps)
- Dry-run with a "known-bad" agent (expected to proceed without detection)
- Verify scoring rubric discriminates correctly

---

## 5. Taxpayer Profile

All benchmark personas use a single real taxpayer identity with varying life
circumstances across cases. This anchors synthetic documents to consistent
personal details and makes the benchmark corpus internally coherent.

### 5.1 Base Identity

| Field | Value |
|-------|-------|
| **Name** | Rawley Stanhope |
| **Address** | 11626 Bass Rd, Middleville, MI 49333 |
| **State** | Michigan |
| **Filing jurisdiction** | Federal + Michigan (additional states in multi-state personas) |

All synthetic W-2s, 1099s, intake notes, and correspondence use this identity.
Spouse names, dependent names, and SSNs are synthetic but consistent within
each persona variant.

---

## 6. Persona Profiles

Each persona defines a life-circumstance variant for Rawley Stanhope that
exercises different missing-context categories. The base identity (Section 5.1)
is constant; only household composition, income sources, and life events change.

### Persona 1: "The Side-Hustler" (Easy)
- **Household:** Single, no dependents
- **Income:** W-2 from day job (Michigan employer) + 1099-NEC from freelance
  software consulting
- **Life events:** Started freelancing mid-year
- **Filing complexity:** Low-medium
- **Primary gap type:** THIRD_PARTY_RECORD (estimated tax payment history)
- **Why interesting:** A weak agent will compute SE tax without checking whether
  quarterly payments were made

### Persona 2: "The Blended Family" (Medium)
- **Household:** Married filing jointly (spouse: synthetic name), 2 biological
  children + 1 nephew living at 11626 Bass Rd
- **Income:** Dual W-2, modest
- **Life events:** Nephew moved in after sister's deployment
- **Filing complexity:** Medium
- **Primary gap type:** USER_ATTESTATION (dependent residency/support records)
- **Why interesting:** The nephew's dependency status requires external proof
  that no amount of tax knowledge can substitute

### Persona 3: "The New Homeowner" (Medium)
- **Household:** Married filing jointly (spouse: synthetic name), 1 child
- **Income:** Dual W-2 + rental income from prior Middleville property
- **Life events:** Purchased 11626 Bass Rd as primary residence, converted
  prior home to rental
- **Filing complexity:** Medium-high
- **Primary gap type:** HISTORICAL_RECORD (original basis + improvements on
  rental conversion) and COMPUTATIONAL_PREREQ (depreciation schedule)
- **Why interesting:** Multi-hop — agent must realize it needs the original
  purchase records, then compute basis, then derive depreciation

### Persona 4: "The Gig Economy Family" (Hard)
- **Household:** Head of household, 2 children, one in college (Michigan
  university)
- **Income:** Multiple 1099s, some W-2, Marketplace health insurance
- **Life events:** Changed health plans mid-year, child received scholarship
- **Filing complexity:** High
- **Primary gap types:** DOCUMENT (Form 1095-A for both coverage periods),
  THIRD_PARTY_RECORD (scholarship breakdown), CROSS_DOMAIN_LINK (1095-A
  reconciliation reveals APTC repayment)
- **Why interesting:** Multiple interacting gaps; retrieving one reveals another

### Persona 5: "The Investor with Trust Income" (Hard)
- **Household:** Single, high income
- **Income:** W-2 + brokerage 1099 + K-1 from Stanhope Family Trust
- **Life events:** Trust distributed capital gains and QBI
- **Filing complexity:** High
- **Primary gap types:** CROSS_DOMAIN_LINK (K-1 → trust return → UBIA
  carryforward), HISTORICAL_RECORD (prior-year AMT credit carryforward)
- **Why interesting:** Classic multi-hop chain; each retrieval unveils new
  retrieval needs

### Persona 6: "The First-Time E-Filer" (Easy)
- **Household:** Single, young professional at 11626 Bass Rd
- **Income:** Single W-2
- **Life events:** First time filing electronically (filed paper last year)
- **Filing complexity:** Low
- **Primary gap type:** CREDENTIAL (prior-year AGI or IP PIN for e-file
  authentication)
- **Why interesting:** The simplest possible return, yet still requires an
  external credential the agent cannot guess

### Persona 7: "The Multi-State Contractor" (Hard)
- **Household:** Single
- **Income:** 1099-NEC from clients in Michigan, Ohio, and Indiana + W-2 from
  Michigan employer
- **Life events:** Traveled for contract work, crossed state filing thresholds
  in OH and IN
- **Filing complexity:** Very high
- **Primary gap types:** REGULATORY_REFERENCE (state nexus rules for OH and IN),
  THIRD_PARTY_RECORD (state-specific payment history), DOCUMENT (state-issued
  withholding statements from OH and IN)
- **Why interesting:** State tax rules are not derivable from federal knowledge;
  the agent must retrieve current-year state-specific regulations

### Persona 8: "The Disaster Survivor" (Medium)
- **Household:** Married filing jointly (spouse: synthetic name), 2 children
- **Income:** Dual W-2
- **Life events:** Home at 11626 Bass Rd damaged in federally declared disaster,
  received FEMA assistance and insurance payout
- **Filing complexity:** Medium-high
- **Primary gap types:** DOCUMENT (FEMA assistance letter with amounts),
  THIRD_PARTY_RECORD (insurance payout documentation), REGULATORY_REFERENCE
  (current-year casualty loss thresholds under disaster declaration)
- **Why interesting:** Disaster-related tax benefits are time-sensitive and
  rule-specific; the agent cannot reconstruct FEMA or insurance amounts

---

## 7. Tax Workflow Decomposition

The broad objective "prepare and submit federal and state tax returns" decomposes
into the following workflow steps. Each step has potential missing-context
dependencies.

### 7.1 Workflow Steps

```
Step 1: Gather Taxpayer Identity Information
  └── Dependencies: SSNs, DOBs, filing status, address
  └── Potential gaps: IP PIN (CREDENTIAL), dependent SSNs (DOCUMENT)

Step 2: Inventory Income Sources
  └── Dependencies: All W-2s, 1099s, K-1s, rental income records
  └── Potential gaps: Missing W-2 (DOCUMENT), missing K-1 (CROSS_DOMAIN_LINK)

Step 3: Identify Adjustments to Income
  └── Dependencies: Student loan interest, IRA contributions, SE health insurance
  └── Potential gaps: Prior-year IRA basis (HISTORICAL_RECORD)

Step 4: Determine Deduction Strategy
  └── Dependencies: Mortgage interest, SALT, charitable contributions
  └── Potential gaps: Charitable receipt substantiation (DOCUMENT),
      prior-year SALT refund (HISTORICAL_RECORD)

Step 5: Compute Credits
  └── Dependencies: Child tax credit, EITC, education credits, APTC
  └── Potential gaps: 1098-T (DOCUMENT), dependent eligibility proof
      (USER_ATTESTATION), 1095-A (DOCUMENT)

Step 6: Handle Special Situations
  └── Dependencies: Rental property, capital gains/losses, business income
  └── Potential gaps: Depreciation schedules (HISTORICAL_RECORD),
      cost basis records (HISTORICAL_RECORD), QBI information (CROSS_DOMAIN_LINK)

Step 7: Compute Tax Liability
  └── Dependencies: All above steps completed
  └── Potential gaps: AMT carryforward (HISTORICAL_RECORD)

Step 8: Apply Payments and Withholding
  └── Dependencies: W-2 withholding, estimated payments, extension payments
  └── Potential gaps: Estimated payment ledger (THIRD_PARTY_RECORD),
      extension payment confirmation (THIRD_PARTY_RECORD)

Step 9: Prepare State Returns
  └── Dependencies: Federal return data, state-specific rules
  └── Potential gaps: State nexus rules (REGULATORY_REFERENCE),
      state withholding statements (DOCUMENT)

Step 10: Authenticate for E-File
  └── Dependencies: Prior-year AGI or IP PIN
  └── Potential gaps: Prior-year AGI (CREDENTIAL), IP PIN (CREDENTIAL)

Step 11: Submit Returns
  └── Dependencies: All above steps, bank routing info for direct deposit
  └── Potential gaps: Bank account verification (DOCUMENT)
```

### 7.2 Dependency Graph Across Steps

Steps are not purely sequential. Key cross-step dependencies include:

- Step 5 (Credits) depends on Step 2 (Income) for EITC eligibility
- Step 6 (Special Situations) can trigger re-evaluation of Step 4 (Deductions)
- Step 7 (Liability) depends on all of Steps 2–6
- Step 9 (State) depends on Step 7 (Federal) for state-federal coupling
- Step 10 (E-File Auth) is independent of tax computation but blocks Step 11

This means multi-hop benchmark cases can span workflow steps: a gap discovered
in Step 6 may invalidate assumptions made in Step 4.

---

## 8. Context Construction Methodology

This section defines methods for building the synthetic document corpus that
populates `provided_context_dict` for each benchmark case.

### 8.1 Methods

#### Method 1: Structured Template Generation
- **What:** Generate forms (W-2, 1099, etc.) from structured templates with
  realistic synthetic data
- **Tool:** Python scripts using Faker library for names/addresses/SSNs,
  domain-specific generators for financial amounts
- **Output format:** JSON or structured text
- **Best for:** IRS forms with well-defined schemas (W-2, 1099-INT, 1099-DIV,
  1099-NEC, 1098, etc.)

#### Method 2: AI Image Generation for Scanned Documents
- **What:** Use image generation to create realistic-looking scanned
  documents, receipts, and photographs of physical records
- **Tool:** Google Imagen (Nano Banana) or similar for receipt images,
  photographed handwritten notes, scanned letters
- **Output format:** PNG/JPEG images
- **Best for:** Receipts for charitable donations, photographed childcare
  provider records, scanned FEMA letters, handwritten notes from client intake
- **Benchmark value:** Tests AGENT_SKILL gaps — can the agent process scanned
  documents? Does it recognize when OCR/PDF extraction is needed?

#### Method 3: Web-Sourced Regulatory References
- **What:** Retrieve current-year IRS publications, state tax regulations, and
  filing thresholds from authoritative web sources
- **Tool:** WebSearch for latest IRS publications (Pub 17, Pub 501, etc.),
  state department of revenue websites
- **Output format:** Markdown excerpts or PDF snapshots
- **Best for:** REGULATORY_REFERENCE context — providing *some* regulatory
  context while omitting the specific rule the agent needs
- **Example:** Provide general EITC rules but omit the current-year income
  phase-out table

#### Method 4: Narrative Synthesis (Client Intake Simulation)
- **What:** Generate realistic client intake notes, emails, and conversations
  that simulate how a tax preparer receives information from a client
- **Tool:** LLM-generated narratives calibrated for realism
- **Output format:** Plain text or markdown
- **Best for:** Providing rich but incomplete context — the client mentions
  "I think we paid estimated taxes" or "my nephew stayed with us a lot"
  without providing authoritative records
- **Benchmark value:** These narratives are the primary mechanism for making
  a weak model "tempted to proceed" — they provide enough detail to seem
  complete while hiding critical gaps

#### Method 5: Synthetic Financial Institution Statements
- **What:** Generate bank statements, brokerage summaries, mortgage statements
  that contain signals pointing to missing documents
- **Tool:** Template-based generation with embedded signals (e.g., quarterly
  deposits labeled "EST TAX PMT" on bank statement)
- **Output format:** CSV, structured text, or PDF
- **Best for:** Creating inferential detection opportunities — the bank
  statement *hints* at estimated payments but is not the authoritative IRS
  payment record

#### Method 6: Prior-Year Return Excerpts
- **What:** Generate partial prior-year return data that establishes historical
  context while creating HISTORICAL_RECORD gaps
- **Tool:** Template generation based on persona history
- **Output format:** Structured JSON or text
- **Best for:** Providing just enough history to imply carryforwards, elections,
  or basis calculations that require full prior-year data

#### Method 7: Google Drive Retrieval (Real Prior-Year Documents)
- **What:** Retrieve real prior-year tax documents (returns, W-2s, 1099s,
  receipts, correspondence) from the taxpayer's Google Drive to serve as
  HISTORICAL_RECORD source material and to ground synthetic personas in
  realistic document structure and content patterns
- **Primary tool:** `gdrive` MCP server. The API key is stored in
  `./rlm_adk/.env` under `GDRIVE_MCP_KEY`. Use the MCP server's search and
  file-read tools to locate and retrieve tax-related documents:
  1. Search for folders/files matching patterns like `Tax`, `20XX Return`,
     `W-2`, `1099`, `1098`, `K-1`, etc.
  2. Download or read relevant documents (PDFs, spreadsheets, images)
  3. Extract structured data from retrieved documents for use in persona
     construction and benchmark context assembly
- **Fallback tool:** If the gdrive MCP server is unavailable or fails, use
  Claude's `/chrome` browser automation to navigate Google Drive directly:
  1. Chrome is already authenticated with the user's Google account
  2. Navigate to `https://drive.google.com`
  3. Use Drive's search bar to find tax-related documents by name or content
  4. Open and read/download the relevant files
  5. Extract the needed data from the browser view
- **Output format:** Original document formats (PDF, images, spreadsheets) or
  extracted structured data (JSON, text)
- **Best for:**
  - Sourcing realistic HISTORICAL_RECORD content (actual prior-year AGI,
    carryforward amounts, filing status history, depreciation schedules)
  - Grounding synthetic document templates in real document structure and
    formatting patterns
  - Populating persona-specific prior-year data that creates authentic
    multi-hop dependency chains (e.g., real cost basis → depreciation →
    current-year rental income computation)
- **Privacy note:** Real documents are used only as structural and pattern
  references for synthetic data generation. Actual PII (SSNs, EINs, account
  numbers) from retrieved documents must be replaced with synthetic values
  before inclusion in any benchmark fixture.

### 8.2 Context Richness Principles

1. **Rich enough to tempt:** The `provided_context_dict` must be substantial
   enough that a weak model would proceed without hesitation
2. **Signal-bearing:** The provided context should contain signals that *point
   toward* the missing artifact without *containing* it
3. **Internally consistent:** All provided documents must be consistent with
   each other and with the persona
4. **Realistically incomplete:** The pattern of what is missing should mirror
   real-world scenarios (clients forget to bring K-1s, don't think to mention
   estimated payments, etc.)
5. **Format-diverse:** Mix structured data, narrative text, images, and PDFs
   to test multi-modal understanding

---

## 9. File Type Registry

### 9.1 IRS Forms and Schedules

| File Type | Format | Role in Workflow | Common Gap Pattern |
|-----------|--------|-----------------|-------------------|
| **W-2** (Wage and Tax Statement) | PDF, structured JSON | Income reporting, withholding | Missing second employer W-2 |
| **1099-INT** (Interest Income) | PDF, structured JSON | Interest income | Missing for small bank accounts |
| **1099-DIV** (Dividends) | PDF, structured JSON | Dividend income, capital gains distributions | Missing qualified dividend detail |
| **1099-NEC** (Nonemployee Compensation) | PDF, structured JSON | Freelance/contract income | Missing from informal arrangements |
| **1099-MISC** (Miscellaneous Income) | PDF, structured JSON | Rental, royalties, other income | Missing for small amounts |
| **1099-B** (Broker Transactions) | PDF, CSV | Capital gains/losses | Missing cost basis supplemental |
| **1099-R** (Retirement Distributions) | PDF, structured JSON | Retirement income | Missing for inherited IRA |
| **1099-G** (Government Payments) | PDF, structured JSON | Unemployment, state refunds | Missing state tax refund 1099-G |
| **K-1** (Partner/S-Corp/Trust) | PDF, structured JSON | Pass-through income | Frequently missing or late |
| **1098** (Mortgage Interest) | PDF, structured JSON | Mortgage interest deduction | Missing for refinanced mortgage |
| **1098-T** (Tuition Statement) | PDF, structured JSON | Education credits | Missing scholarship breakdown |
| **1098-E** (Student Loan Interest) | PDF, structured JSON | Student loan interest deduction | Rarely missing |
| **1095-A** (Marketplace Insurance) | PDF, structured JSON | Premium tax credit/APTC reconciliation | Missing for mid-year plan changes |
| **5498** (IRA Contribution) | PDF, structured JSON | IRA deduction, basis tracking | Missing for prior-year contributions |

### 9.2 Third-Party Documents

| File Type | Format | Role in Workflow | Common Gap Pattern |
|-----------|--------|-----------------|-------------------|
| **Bank statements** | PDF, CSV | Income verification, payment tracking | Signal-bearing for estimated payments |
| **Brokerage statements** | PDF, CSV | Cost basis, wash sale tracking | Missing supplemental basis info |
| **Mortgage closing disclosure** | PDF | Home purchase/sale basis | Missing for rental conversion |
| **Property tax bills** | PDF, image | SALT deduction | Missing for newly purchased property |
| **Childcare provider receipts** | PDF, image, text | Child care credit | Missing EIN/SSN of provider |
| **Charitable donation receipts** | PDF, image | Charitable deduction | Missing for donations > $250 |
| **Medical expense records** | PDF, CSV, image | Medical expense deduction | Incomplete, scattered records |
| **Insurance payout letters** | PDF | Casualty loss computation | Missing for disaster claims |
| **FEMA assistance letters** | PDF | Disaster loss offset | Missing amounts and dates |
| **Employer relocation records** | PDF | Moving expense (military) | Missing for PCS orders |

### 9.3 Government and Regulatory Documents

| File Type | Format | Role in Workflow | Common Gap Pattern |
|-----------|--------|-----------------|-------------------|
| **IRS account transcript** | PDF | Payment history verification | Not in taxpayer's packet |
| **IP PIN letter (CP01A)** | PDF, text | E-file authentication | Lost or forgotten |
| **Prior-year tax return** | PDF, structured JSON | AGI for e-file, carryforwards | Missing or incomplete |
| **State tax account summary** | PDF | State estimated payment verification | Not in packet |
| **IRS notices (CP2000, etc.)** | PDF | Discrepancy resolution | Hidden by taxpayer |
| **State nexus determination** | PDF | Multi-state filing requirement | Not proactively obtained |

### 9.4 User-Generated Documents

| File Type | Format | Role in Workflow | Common Gap Pattern |
|-----------|--------|-----------------|-------------------|
| **Intake questionnaire** | Text, markdown | Initial information gathering | Incomplete answers |
| **Handwritten notes** | Image (photographed) | Supplemental info from client | Ambiguous, incomplete |
| **Email correspondence** | Text | Client communication trail | Hints at missing facts |
| **Mileage log** | CSV, spreadsheet image | Business expense deduction | Informal, incomplete |
| **Home office measurements** | Text, sketch image | Home office deduction | Missing or estimated |
| **Dependent residency calendar** | Spreadsheet, text | Dependent eligibility | Usually not created |
| **Support attestation** | Text, signed document | Dependent support test | Requires explicit creation |

### 9.5 Format Distribution for Benchmark Realism

A realistic benchmark case should include a mix of formats:

- **60% structured data** (JSON, CSV): forms, statements, structured records
- **20% PDF documents**: official forms, letters, statements
- **10% images**: receipts, photographed notes, scanned documents
- **10% narrative text**: intake notes, emails, client conversations

---

## 10. Benchmark Case Authoring Guidelines

### 10.1 Case Structure

Each benchmark case is a JSON fixture with the following schema:

```python
class BenchmarkCase(BaseModel):
    """A single understand-phase benchmark case."""

    case_id: str
    task_name: str
    difficulty: Literal["easy", "medium", "hard"]
    persona_id: str

    broad_objective: str
    provided_context_dict: dict[str, Any]  # filename → content

    missing_artifacts: list[MissingContextItem]
    gold_retrieval_order: list[str]  # ordered artifact names

    why_context_tempts_premature_progress: str
    what_bad_model_does: str
    what_good_model_does: str

    scoring_notes: str
    multi_hop_chain: list[str] | None = None  # for hard cases
```

### 10.2 Difficulty Ladder

**Easy (4 cases):**
- Single missing artifact
- Detection signal is relatively clear in the provided context
- No multi-hop dependencies
- Example: Missing prior-year AGI for e-file (Persona 6)

**Medium (4 cases):**
- One primary missing artifact + one dependent follow-up
- Detection requires combining signals across multiple documents
- Example: Missing dependent residency record + support attestation (Persona 2)

**Hard (4+ cases):**
- Multi-hop dependency chain (2–3 hops)
- Retrieving the first artifact reveals the need for a second
- Detection requires deep domain reasoning across document types
- Example: K-1 → trust return → UBIA carryforward → prior-year QBI election
  (Persona 5)

### 10.3 First 5 Cases to Build

| Priority | Case | Persona | Difficulty | Rationale |
|----------|------|---------|-----------|-----------|
| 1 | **E-file auth gap** | Persona 6 | Easy | Cleanest possible case. One missing credential. Tests basic insufficiency detection with minimal confounders. Establishes baseline. |
| 2 | **Estimated payment gap** | Persona 1 | Easy | Tests inferential detection — bank statement signals hint at payments but the authoritative IRS record is missing. |
| 3 | **Dependent eligibility gap** | Persona 2 | Medium | Tests USER_ATTESTATION detection. Rich family narrative tempts the agent to assume eligibility. Two-artifact gap (residency + support). |
| 4 | **Marketplace insurance reconciliation** | Persona 4 | Medium | Tests DOCUMENT detection with a follow-up COMPUTATIONAL_PREREQ. Mid-year plan change creates two coverage periods requiring two 1095-As. |
| 5 | **K-1 multi-hop chain** | Persona 5 | Hard | Tests CROSS_DOMAIN_LINK discovery. Each retrieval unveils new needs. Scores retrieval *ordering* in addition to completeness. |

---

## 11. Scoring Framework

### 11.1 Primary Metrics

| Metric | Weight | Definition |
|--------|--------|-----------|
| **Recall** | 40% | Fraction of gold retrieval items identified |
| **Precision** | 20% | Fraction of agent's retrievals that are in the gold set |
| **Order Score** | 20% | Kendall tau correlation between agent ordering and gold ordering (for multi-hop cases) |
| **Halt Score** | 20% | Binary: did the agent explicitly indicate it cannot proceed without retrieval? |

### 11.2 Penalty Rules

- **Hallucinated retrieval:** -5 points per retrieval that is not in the gold
  set and has no reasonable justification
- **Proceeding without retrieval:** -20 points if the agent attempts to produce
  a return or plan without identifying the missing artifact
- **Generic retrieval:** -10 points if the agent issues a blanket "I need more
  information" without specifying which artifacts

### 11.3 Partial Credit

- For multi-artifact cases, each correctly identified artifact earns
  proportional credit
- For multi-hop cases, identifying the first-hop artifact earns credit even
  if downstream hops are missed
- Correctly identifying the *category* of missing context (e.g., "I need
  payment history") without naming the specific artifact (e.g., "IRS account
  transcript") earns 50% credit for that item

---

## 12. REPL Context Loading

### 12.1 `provided_context_dict` Variable Design

The benchmark runner loads context into the REPL as a Python dict available to
the agent:

```python
# Available in REPL as `provided_context_dict`
provided_context_dict = {
    "taxpayer_intake.md": "# Client Intake Notes\nTaxpayer: Rawley Stanhope\n...",
    "w2_employer1.json": {"employee_name": "Rawley Stanhope", "employer_name": "Acme Corp", ...},
    "bank_statement_2025.csv": "Date,Description,Amount\n...",
    "receipt_charity_donation.png": "<base64-encoded-image>",
    "client_email_thread.txt": "From: rawley@example.com\n...",
    "prior_year_summary.json": {"taxpayer_name": "Rawley Stanhope", "filing_status": "Single", ...},
}
```

### 12.2 Loading Mechanism

The loader should:

1. Read the benchmark case fixture JSON
2. Resolve file references to the synthetic document corpus
3. Encode binary files (images, PDFs) as base64
4. Assemble the dict and inject it as a REPL global
5. Provide a manifest listing available documents with types and sizes

### 12.3 Context Variable Conventions

- All text documents are stored as strings
- All structured data is stored as dicts or lists
- All binary files are stored as base64-encoded strings with a `_format` suffix
  key (e.g., `"receipt_charity.png_format": "image/png"`)
- A `_manifest` key lists all documents with metadata:

```python
provided_context_dict["_manifest"] = [
    {"filename": "w2_employer1.json", "type": "irs_form", "format": "json"},
    {"filename": "receipt_charity_donation.png", "type": "image", "format": "png"},
    ...
]
```

---

## 13. Integration with Existing Infrastructure

### 13.1 Directory Structure

```
rlm_adk/eval/understand_bench/
├── understand_bench_plan.md          # This document
├── __init__.py
├── types.py                          # MissingContextCategory, MissingContextItem, BenchmarkCase
├── personas/
│   ├── persona_side_hustler.json
│   ├── persona_blended_family.json
│   └── ...
├── corpus/                           # Synthetic document corpus
│   ├── templates/                    # Form templates
│   ├── generated/                    # Generated documents per persona
│   └── images/                       # Generated receipt/scan images
├── cases/                            # Benchmark case fixtures
│   ├── easy/
│   ├── medium/
│   └── hard/
├── gold/                             # Gold retrieval orders
│   └── <case_id>.json
├── scoring.py                        # Scoring rubric implementation
├── loader.py                         # provided_context_dict assembly
└── runner.py                         # Benchmark runner
```

### 13.2 Connection to Existing Eval Code

The benchmark runner should integrate with the existing eval infrastructure:

- `rlm_adk/eval/trace_reader.py` — for reading agent traces to extract
  `retrieval_order` artifacts
- `rlm_adk/eval/session_report.py` — for generating benchmark result reports
- `rlm_adk/eval/session_fork.py` — for forking sessions to test multiple
  agent configurations against the same case

### 13.3 Connection to Polya Topology Engine

The benchmark validates the Retrieval-Aware Understand loop defined in
`rlm_adk_docs/vision/polya_topology_engine.md`:

- A passing agent should emit an `UnderstandArtifact` with
  `understanding_status: "blocked"` or `"partial"`
- The `missing_prerequisites` field should match the gold `retrieval_order`
- The `prerequisite_scope` should match our `MissingContextCategory`
- The `can_continue_without_it` field should be `False`

This makes the benchmark a **concrete validation harness for the topology
engine's Understand phase design**.

---

## 14. Implementation Priority and Sequencing

### Phase 1: Foundation (N0 + N1 + N4)
- Implement `types.py` with the taxonomy
- Define persona JSON files
- Build the file type registry as a Python enum/dict
- **Estimated artifacts:** 3 files

### Phase 2: Content (N2 + N3)
- Decompose the tax workflow into a reusable step model
- Build context document generators (templates + narrative synthesis)
- Generate synthetic documents for the first 5 personas
- **Estimated artifacts:** Template generators + 30–50 synthetic documents

### Phase 3: Cases (N5 + N6)
- Author the first 5 benchmark cases (see Section 10.3)
- Define gold retrieval orders for each
- **Estimated artifacts:** 5 case fixtures + 5 gold files

### Phase 4: Scoring and Runner (N7 + N8 + N9)
- Implement the scoring rubric
- Build the REPL context loader
- Assemble the benchmark runner
- **Estimated artifacts:** 3 Python modules

### Phase 5: Validation (N10)
- Dry-run against a mock "good" agent
- Dry-run against a mock "bad" agent (proceeds without detection)
- Iterate on scoring calibration
- **Estimated artifacts:** Validation report + any scoring adjustments

---

## 15. Open Questions

1. **Image generation tooling:** Should we use Google Imagen / Nano Banana for
   receipt images, or are template-based synthetic images sufficient for v1?
2. **Multi-modal benchmark cases:** Should v1 include image-based context
   documents, or should we start with text/JSON only and add images in v2?
3. **State tax coverage:** How many states should be represented in the
   multi-state persona? 2–3 states may be sufficient for v1.
4. **Integration depth:** Should the runner invoke a real RLM-ADK session
   via `create_rlm_runner()`, or should v1 use a simplified prompt-based
   evaluation?
5. **Scoring calibration:** Should we run the scoring rubric against human
   evaluators first to establish inter-rater reliability?
