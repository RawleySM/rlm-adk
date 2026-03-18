# Persona A: Systems Compression Architect

Objective: maximize recursive depth while keeping layer-0 (parent agent) turn count minimal by pushing decomposition, experimentation, retrieval, and synthesis into nested `llm_query()` / `llm_query_batched()` folds.

## Ranked Top 3
1. **Autonomous Literature-to-Prototype Research Swarm** (score: 10/10)
2. **Recursive Vulnerability Reproduction and Patch Synthesis** (score: 10/10)
3. **Cross-Provider Prompt-Robustness Tournament Harness** (score: 9/10)

## Candidate Task 1: Autonomous Literature-to-Prototype Research Swarm
1) **Task title**
- Autonomous Literature-to-Prototype Research Swarm

2) **Why it creates deep recursion**
- Naturally forms map-reduce recursion: topic decomposition -> source retrieval -> per-paper extraction -> claim conflict resolution -> implementation synthesis -> experiment loops.

3) **Expected layer-0 turn budget**
- 2-3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: research plan and shard definitions.
- L2: batched paper/domain deep-dives.
- L3+: per-claim verification, ablation suggestion, code stub generation.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): generate decomposition tree + query packs.
- Fold B (L2, batched): retrieve/analyze each shard in parallel via `llm_query_batched()`.
- Fold C (L3+): for each conflicting claim, spawn verification workers and confidence scoring.
- Fold D (L2): synthesize into architecture + experiment backlog.

6) **Failure/hang-up risks and mitigations**
- Risk: runaway fanout on many papers. Mitigation: hard cap per shard and entropy-based pruning.
- Risk: stale or low-quality sources. Mitigation: enforce source diversity + recency checks.
- Risk: hallucinated citations. Mitigation: require URL/DOI echo and reject unverifiable claims.

7) **Depth-per-layer0-turn score**
- 10/10

## Candidate Task 2: Recursive Vulnerability Reproduction and Patch Synthesis
1) **Task title**
- Recursive Vulnerability Reproduction and Patch Synthesis

2) **Why it creates deep recursion**
- Security work recursively branches by surface area (inputs, code paths, dependency chains), then again by exploit variant and patch candidate validation.

3) **Expected layer-0 turn budget**
- 2-4 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: attack-surface partitioning.
- L2: per-surface exploit hypothesis and PoC attempts.
- L3+: root-cause trace, patch generation, regression proof.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): partition targets and threat models.
- Fold B (L2, batched): generate PoCs by partition.
- Fold C (L3+): for successful PoCs, recurse into minimal reproducer + patch options.
- Fold D (L2): batch-run patch diff risk reviews and test plan synthesis.

6) **Failure/hang-up risks and mitigations**
- Risk: unsafe exploit guidance. Mitigation: constrain to authorized/local test targets and defensive framing.
- Risk: false positives from brittle repros. Mitigation: rerun with randomized seeds and environment snapshots.
- Risk: patch breaks adjacent behavior. Mitigation: auto-generate focused regression suites before finalization.

7) **Depth-per-layer0-turn score**
- 10/10

## Candidate Task 3: Cross-Provider Prompt-Robustness Tournament Harness
1) **Task title**
- Cross-Provider Prompt-Robustness Tournament Harness

2) **Why it creates deep recursion**
- Tournament structure recursively nests: prompt families -> mutation operators -> provider/model runs -> failure clustering -> counter-prompt synthesis.

3) **Expected layer-0 turn budget**
- 2-3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: define evaluation axes and bracket structure.
- L2: batched execution across providers/prompts.
- L3+: recursive mutation and adversarial stress loops.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): create rubric + scenario matrix.
- Fold B (L2, batched): run matrix via `llm_query_batched()`.
- Fold C (L3+): recursively mutate failing prompts until convergence or budget cap.
- Fold D (L2): synthesize robust prompt templates and guardrails.

6) **Failure/hang-up risks and mitigations**
- Risk: evaluation drift. Mitigation: fixed scoring rubric and anchor cases.
- Risk: provider-specific rate limits. Mitigation: adaptive batching/backoff.
- Risk: overfitting to test suite. Mitigation: hold-out scenarios generated in a separate recursive branch.

7) **Depth-per-layer0-turn score**
- 9/10

## Candidate Task 4: Recursive Codebase Archeology and Refactor Plan Distillation
1) **Task title**
- Recursive Codebase Archeology and Refactor Plan Distillation

2) **Why it creates deep recursion**
- Large repo analysis recursively decomposes by subsystem, then by hotspot files, then by dependency/ownership history and refactor candidate generation.

3) **Expected layer-0 turn budget**
- 2-3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: architecture slice map.
- L2: per-slice deep static analysis.
- L3+: per-hotspot migration strategy and risk simulation.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): generate subsystem shards and KPI targets.
- Fold B (L2, batched): analyze shards with code + docs context.
- Fold C (L3+): recurse on top-N hotspots for stepwise refactor scripts.
- Fold D (L2): unify into phased rollout/rollback plan.

6) **Failure/hang-up risks and mitigations**
- Risk: context overflow in monorepos. Mitigation: strict shard budgets + iterative fetch.
- Risk: inconsistent subsystem assumptions. Mitigation: lineage-scoped assumptions ledger.
- Risk: generic recommendations. Mitigation: force file/line-linked evidence per claim.

7) **Depth-per-layer0-turn score**
- 9/10

## Candidate Task 5: Multi-Hop Policy-to-Implementation Compliance Tracer
1) **Task title**
- Multi-Hop Policy-to-Implementation Compliance Tracer

2) **Why it creates deep recursion**
- Compliance requires recursive mapping from policy clauses -> technical controls -> code/log evidence -> exception analysis.

3) **Expected layer-0 turn budget**
- 3-4 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: clause taxonomy + control mapping skeleton.
- L2: batched clause-level evidence gathering.
- L3+: contradiction resolution and compensating-control analysis.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): decompose policy text into auditable atomic obligations.
- Fold B (L2, batched): map each obligation to control/evidence probes.
- Fold C (L3+): recurse on gaps to generate remediation options and implementation diffs.
- Fold D (L2): assemble traceability matrix and executive summary.

6) **Failure/hang-up risks and mitigations**
- Risk: legal ambiguity propagation. Mitigation: confidence tags + explicit assumption checkpoints.
- Risk: false compliance from missing telemetry. Mitigation: require concrete artifact references.
- Risk: huge matrix size. Mitigation: priority weighting by risk and blast radius.

7) **Depth-per-layer0-turn score**
- 8/10

## Candidate Task 6: Recursive Incident Postmortem Constructor with Counterfactuals
1) **Task title**
- Recursive Incident Postmortem Constructor with Counterfactuals

2) **Why it creates deep recursion**
- Postmortems branch by timeline segment, system component, human/process factors, and counterfactual interventions.

3) **Expected layer-0 turn budget**
- 2-3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: timeline segmentation and incident graph.
- L2: per-segment evidence reconstruction.
- L3+: counterfactual simulation and preventive control scoring.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): produce event DAG and open questions.
- Fold B (L2, batched): reconstruct each segment from logs/tickets/chat notes.
- Fold C (L3+): recurse on high-uncertainty nodes for alternate hypotheses.
- Fold D (L2): synthesize causal narrative + prioritized remediations.

6) **Failure/hang-up risks and mitigations**
- Risk: blame-focused drift. Mitigation: enforce systems-thinking template.
- Risk: noisy evidence conflicts. Mitigation: contradiction table with source precedence rules.
- Risk: endless hypothesis branching. Mitigation: branch cutoff by incremental information gain.

7) **Depth-per-layer0-turn score**
- 9/10

## Candidate Task 7: Autonomous Benchmark Lab for Agentic Toolchain Optimizations
1) **Task title**
- Autonomous Benchmark Lab for Agentic Toolchain Optimizations

2) **Why it creates deep recursion**
- Benchmarking recursively nests scenario generation, harness execution, anomaly triage, and optimization proposal loops.

3) **Expected layer-0 turn budget**
- 3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: benchmark matrix design.
- L2: batched run orchestration and metric collection.
- L3+: root-cause deep-dive on outliers and targeted optimization experiments.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): define workloads, budgets, and success metrics.
- Fold B (L2, batched): run workload shards and summarize telemetry.
- Fold C (L3+): recurse into worst-percentile traces for causal diagnosis.
- Fold D (L2): synthesize optimization roadmap with expected ROI.

6) **Failure/hang-up risks and mitigations**
- Risk: non-deterministic benchmark noise. Mitigation: repeated runs + confidence intervals.
- Risk: metric gaming. Mitigation: multi-objective scoring (latency, quality, cost).
- Risk: expensive experiment explosion. Mitigation: adaptive stopping and marginal-gain thresholds.

7) **Depth-per-layer0-turn score**
- 8/10

## Candidate Task 8: Recursive Market Intelligence and Product Direction Synthesizer
1) **Task title**
- Recursive Market Intelligence and Product Direction Synthesizer

2) **Why it creates deep recursion**
- Requires multi-hop online retrieval and recursive synthesis across competitors, user segments, pricing, technical differentiation, and trend forecasting.

3) **Expected layer-0 turn budget**
- 2-3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: market segmentation + hypothesis framing.
- L2: batched competitor/segment retrieval and extraction.
- L3+: contradiction resolution, forecast stress tests, and scenario planning.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): create hypothesis tree and retrieval plan.
- Fold B (L2, batched): parallel evidence pulls by competitor/segment.
- Fold C (L3+): recurse on uncertain trends with alternative scenarios.
- Fold D (L2): produce strategy memo and experiment queue.

6) **Failure/hang-up risks and mitigations**
- Risk: stale market inputs. Mitigation: strict recency filters and timestamped evidence.
- Risk: source bias. Mitigation: triangulate across independent source types.
- Risk: speculative overreach. Mitigation: separate evidence-backed claims from hypotheses.

7) **Depth-per-layer0-turn score**
- 9/10

## Candidate Task 9: Recursive Data-Quality Forensics and Repair Pipeline
1) **Task title**
- Recursive Data-Quality Forensics and Repair Pipeline

2) **Why it creates deep recursion**
- Data issues recurse from top-level anomalies to column/entity lineage to upstream transformation and contract drift.

3) **Expected layer-0 turn budget**
- 2-4 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: anomaly class decomposition.
- L2: batched per-domain diagnostics.
- L3+: upstream root-cause backtracking and patch proposal validation.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): define anomaly taxonomy and sampling strategy.
- Fold B (L2, batched): diagnose anomalies per domain/table.
- Fold C (L3+): recurse along lineage to find first-bad transformation.
- Fold D (L2): generate repair scripts + monitoring guardrails.

6) **Failure/hang-up risks and mitigations**
- Risk: false causality in lineage. Mitigation: require reproducible replay snapshots.
- Risk: repair introduces schema drift. Mitigation: contract tests before apply.
- Risk: giant data scan costs. Mitigation: progressive sampling then targeted full scans.

7) **Depth-per-layer0-turn score**
- 8/10

## Candidate Task 10: Recursive Test Generation and Flake Eradication Campaign
1) **Task title**
- Recursive Test Generation and Flake Eradication Campaign

2) **Why it creates deep recursion**
- Recursively branches by module, then by behavioral contract, then by flaky signal triage and deterministic harness redesign.

3) **Expected layer-0 turn budget**
- 2-3 turns.

4) **Expected recursion depth profile (L1/L2/L3+)**
- L1: module prioritization and risk scoring.
- L2: batched contract extraction + test synthesis.
- L3+: flake root-cause recursion and stabilization patches.

5) **Where to place llm_query folds in trajectory**
- Fold A (L1): derive high-value module queue.
- Fold B (L2, batched): synthesize tests per module/contract.
- Fold C (L3+): recurse into flaky failures for timing/state isolation.
- Fold D (L2): build stabilized suite and CI gating proposal.

6) **Failure/hang-up risks and mitigations**
- Risk: brittle generated tests. Mitigation: mutation testing + refactor-resistant assertions.
- Risk: overproduction of low-value tests. Mitigation: enforce coverage-to-maintenance ratio threshold.
- Risk: CI slowdown. Mitigation: shard and tier tests by criticality.

7) **Depth-per-layer0-turn score**
- 9/10

## Compression Pattern (applies to all tasks)
- Keep layer-0 as mission controller only: objective, constraints, acceptance criteria.
- Push all decomposition/execution/synthesis to nested workers.
- Prefer `llm_query_batched()` at L2 for shard parallelism; reserve `llm_query()` at L3+ for serial dependency chains.
- Enforce recursion guards: `max_depth`, `max_fanout`, `budget_remaining`, and explicit termination predicates.
