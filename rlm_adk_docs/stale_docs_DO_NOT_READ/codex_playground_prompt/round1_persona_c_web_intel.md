# Round 1 - Persona C: Web-Intel Cartographer

## Top 3 Ranked Tasks
1. **T1 - Provider Release Delta Watchtower** (Depth-per-layer0-turn: **10/10**)
2. **T2 - AI Regulation & Compliance Horizon Scanner** (Depth-per-layer0-turn: **9/10**)
3. **T9 - Policy/ToS Change Impact Radar** (Depth-per-layer0-turn: **9/10**)

## Candidate Tasks

### T1) Provider Release Delta Watchtower (Models, APIs, Pricing)
1) **Why web-intensive branches benefit from recursion**  
Provider updates are fragmented across changelogs, docs pages, blog posts, status feeds, and pricing tables; recursive branches let child layers gather per-provider deltas independently, then reconcile contradictions upstream.

2) **Expected layer-0 turn budget**  
5 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 8-12 provider branches; L2: 4-10 artifacts/provider; L3+: targeted deep checks for conflicting claims or ambiguous release dates.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: per-provider retrieval plans + extraction of feature/date/price deltas.  
- `llm_query`: global normalization into a single release-delta ledger with confidence labels.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Silent doc edits: store page snapshots and hash sections for diffing.  
- Inconsistent version labels: normalize into canonical model/API identifiers.  
- Rate limits: stagger batched calls and cache unchanged sources.

6) **Score (depth-per-layer0-turn)**  
**10/10**

### T2) AI Regulation & Compliance Horizon Scanner
1) **Why web-intensive branches benefit from recursion**  
Each jurisdiction has separate regulators, legal bulletins, and enforcement notes; recursion enables one branch per jurisdiction plus deeper branches for statute text, commentary, and implementation guidance.

2) **Expected layer-0 turn budget**  
6 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 10-20 jurisdiction branches; L2: 3-8 official/legal sources/jurisdiction; L3+: dispute-resolution branches for legal ambiguity.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: jurisdiction-level source triage and extraction of obligations/effective dates.  
- `llm_query`: risk-tier synthesis (now/next/monitor) with citations.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Language variance: dual-pass translation + native-source citation retention.  
- Paywalled legal commentary: prioritize primary law and regulator bulletins.  
- Date confusion: enforce absolute date normalization (`YYYY-MM-DD`).

6) **Score (depth-per-layer0-turn)**  
**9/10**

### T3) Agent Framework Competitive Intelligence Matrix
1) **Why web-intensive branches benefit from recursion**  
Framework claims spread across docs, repos, issue trackers, benchmark blogs, and conference talks; recursion lets child branches independently validate capability claims before parent-level comparison.

2) **Expected layer-0 turn budget**  
5 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 6-10 framework branches; L2: docs + GitHub + third-party benchmark branches; L3+: contested benchmark verification.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: parallel claim extraction by framework and evidence-type tagging.  
- `llm_query`: cross-framework scoring rubric synthesis.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Marketing bias: require at least one independent source per major claim.  
- Stale README assertions: weight recent issues/releases higher than old docs.  
- Benchmark non-comparability: enforce test-condition normalization.

6) **Score (depth-per-layer0-turn)**  
**9/10**

### T4) Dependency Vulnerability Cascade Map (ADK Stack)
1) **Why web-intensive branches benefit from recursion**  
Security signals are distributed across CVE feeds, GHSA advisories, vendor pages, exploit PoCs, and patch notes; recursive splitting by dependency and vulnerability family keeps the parent concise.

2) **Expected layer-0 turn budget**  
6 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 8-15 dependency clusters; L2: advisory + exploit + patch branches; L3+: exploitability validation branches.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: fetch CVE/GHSA tuples and map to dependency graph nodes.  
- `llm_query`: exploitability and remediation-priority synthesis.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- CVE alias duplication: normalize with CPE/PURL mapping.  
- False-positive package matches: enforce ecosystem + version constraints.  
- Embargoed details: label uncertainty explicitly and set recheck timers.

6) **Score (depth-per-layer0-turn)**  
**8/10**

### T5) RAG Vendor Cost-Latency-Quality Cartography
1) **Why web-intensive branches benefit from recursion**  
Cost and performance data spans pricing docs, benchmark suites, user reports, and release notes; recursive retrieval allows broad market coverage with localized normalization logic in child nodes.

2) **Expected layer-0 turn budget**  
5 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 8-12 vendor branches; L2: price/latency/quality evidence branches; L3+: apples-to-apples benchmark harmonization.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: parallel extraction of prices, limits, SLA claims, and benchmark figures.  
- `llm_query`: Pareto-front synthesis by use-case profile.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Region-specific pricing drift: normalize by region and timestamp each value.  
- Unit inconsistency: convert to common units (`$/1M tokens`, p95 latency).  
- Synthetic benchmark bias: prioritize reproducible workloads.

6) **Score (depth-per-layer0-turn)**  
**8/10**

### T6) Evidence Credibility Graph for Domain Sources
1) **Why web-intensive branches benefit from recursion**  
Credibility assessment requires many weak signals (authorship, provenance, citations, corrections, funding); recursive branches can score signals independently before parent-layer evidence fusion.

2) **Expected layer-0 turn budget**  
4 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 12-30 source clusters; L2: provenance + citation-chain + reputation branches; L3+: conflict-resolution branches.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: per-source credibility feature extraction.  
- `llm_query`: weighted evidence-score synthesis into trust tiers.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Circular citations: run backlink tracing to origin source.  
- Dead links: use web archives and mirror fallback.  
- Hidden sponsorship: detect disclosures and penalize undisclosed conflicts.

6) **Score (depth-per-layer0-turn)**  
**8/10**

### T7) Benchmark Drift & Leaderboard Integrity Monitor
1) **Why web-intensive branches benefit from recursion**  
Leaderboard claims evolve quickly and often rely on changing datasets; recursion supports per-benchmark monitoring with deeper branches for methodology and data-version integrity checks.

2) **Expected layer-0 turn budget**  
5 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 6-12 benchmark families; L2: leaderboard + paper + code branches; L3+: methodological audit branches.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: collect scores + version metadata + evaluation setup.  
- `llm_query`: drift scoring and comparability synthesis.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Dataset version drift: pin and report exact benchmark versions.  
- Prompt leakage or contamination: tag suspect runs with lowered confidence.  
- Missing reproducibility artifacts: penalize unverifiable claims.

6) **Score (depth-per-layer0-turn)**  
**8/10**

### T8) Provider Outage & Incident Correlation Digest
1) **Why web-intensive branches benefit from recursion**  
Incident signals come from status pages, social posts, issue trackers, and user telemetry; recursive branches can collect each signal class in parallel and synthesize only corroborated events.

2) **Expected layer-0 turn budget**  
4 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 5-10 provider/time-window branches; L2: status/social/community branches; L3+: root-cause corroboration branches.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: parallel event extraction with timestamp normalization.  
- `llm_query`: incident timeline + confidence synthesis.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Social noise spikes: require quorum from independent source types.  
- Timezone mismatch: convert all timestamps to UTC and keep source-local copy.  
- Partial incident disclosure: maintain provisional hypotheses with confidence decay.

6) **Score (depth-per-layer0-turn)**  
**7/10**

### T9) Policy/ToS Change Impact Radar
1) **Why web-intensive branches benefit from recursion**  
Policy drift happens through subtle wording edits across many vendor pages; recursion enables child branches to monitor and diff each document while parent layer emits a stable risk-impact summary.

2) **Expected layer-0 turn budget**  
5 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 8-15 policy-document branches; L2: historical snapshot + semantic diff branches; L3+: legal-interpretation conflict branches.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: extract diff chunks and classify changed obligations/permissions.  
- `llm_query`: impact synthesis by severity tier and affected workflows.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- No explicit changelogs: schedule periodic snapshots and structural HTML diffs.  
- Ambiguous legal language: attach confidence intervals and escalation flags.  
- Fragmented policy pages: canonicalize doc sets per vendor.

6) **Score (depth-per-layer0-turn)**  
**9/10**

### T10) Vertical Opportunity Scanner (Evidence-Backed)
1) **Why web-intensive branches benefit from recursion**  
Opportunity detection depends on heterogeneous sources (market reports, job postings, open-source activity, user complaints); recursion lets each vertical branch gather and score evidence independently before parent-level prioritization.

2) **Expected layer-0 turn budget**  
6 turns

3) **Expected recursion depth profile (L1/L2/L3+)**  
L1: 8-20 vertical branches; L2: demand/supply/pain-signal branches; L3+: contradiction and novelty validation branches.

4) **`llm_query`/`llm_query_batched` fold points**  
- `llm_query_batched`: per-vertical evidence retrieval and signal scoring.  
- `llm_query`: final opportunity ranking and synthesis.

5) **Retrieval bottlenecks/hang-ups and mitigation instructions**  
- Hype bias: apply source-quality weights and recency decay.  
- Forecast contradictions: run contradiction detection and confidence penalties.  
- Low-signal niches: enforce minimum evidence threshold before ranking.

6) **Score (depth-per-layer0-turn)**  
**7/10**

## Notes on Layer-0 Stability Pattern
- Keep layer-0 output fixed-schema: `{task_id, confidence, top_findings, unresolved_questions, next_branches}`.
- Push all broad retrieval, triage, scoring, and contradiction checks to child layers.
- Reserve layer-0 turns for orchestration and final synthesis only.
