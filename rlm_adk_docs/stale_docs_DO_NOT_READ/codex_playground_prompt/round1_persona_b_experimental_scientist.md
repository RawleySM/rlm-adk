# Persona B: Experimental Scientist (Ablation-First)

## Candidate Recursive Playground Workloads

### 1) Counterexample-Guided Program Synthesis Ladder
1. **Task title:** Counterexample-Guided Program Synthesis Ladder
2. **Recursive experiment loop:** `L0: choose synthesis family -> L1: generate N candidate programs -> L2: generate adversarial counterexamples -> L3+: patch local program regions and re-test` until convergence or budget stop.
3. **Expected layer-0 turn budget:** 14-18 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 35% / 40% / 25%.
5. **`llm_query` / `llm_query_batched` fold points:** `llm_query_batched` for candidate generation + counterexample generation; `llm_query` for root-cause narrative and patch strategy decision at each fold.
6. **Unknown input->output structure + recursion handling:** Hidden compositional rules and edge-case semantics; recursion isolates failing subfunctions and performs local repair cycles.
7. **Depth-per-layer0-turn score (1-10):** 10.

### 2) Retrieval Pipeline Ablation Under Distribution Shift
1. **Task title:** Retrieval Pipeline Ablation Under Distribution Shift
2. **Recursive experiment loop:** `L0: pick shift scenario -> L1: ablate retriever/reranker/chunking -> L2: stratify errors by query subtype -> L3+: synthesize hybrid routing policies`, then rerun benchmark.
3. **Expected layer-0 turn budget:** 12-16 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 40% / 35% / 25%.
5. **`llm_query` / `llm_query_batched` fold points:** batched eval across ablations and query slices; single-query folds for causal hypothesis updates and next-ablations planning.
6. **Unknown input->output structure + recursion handling:** Nonlinear interaction between retrieval depth, chunk boundaries, and query intent; recursive stratification discovers latent sub-regimes before policy merge.
7. **Depth-per-layer0-turn score (1-10):** 9.

### 3) Tool-Policy Induction From Failure Traces
1. **Task title:** Tool-Policy Induction From Failure Traces
2. **Recursive experiment loop:** `L0: sample trace batch -> L1: classify failure mode -> L2: induce policy patch candidates -> L3+: replay traces with patched policy and mine new hard cases`.
3. **Expected layer-0 turn budget:** 11-15 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 30% / 45% / 25%.
5. **`llm_query` / `llm_query_batched` fold points:** batched failure tagging and replay scoring; single-query policy synthesis + arbitration when patches conflict.
6. **Unknown input->output structure + recursion handling:** Latent, sparse policy violations only triggered by context combinations; recursive replay expands rare-mode coverage.
7. **Depth-per-layer0-turn score (1-10):** 9.

### 4) Multi-Model Arbitration Frontier Search
1. **Task title:** Multi-Model Arbitration Frontier Search
2. **Recursive experiment loop:** `L0: set cost/latency/quality target -> L1: evaluate model pool on stratified suite -> L2: learn arbitration gates -> L3+: refine gates per failure cluster`.
3. **Expected layer-0 turn budget:** 10-14 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 45% / 35% / 20%.
5. **`llm_query` / `llm_query_batched` fold points:** `llm_query_batched` for parallel model scoring per slice; `llm_query` for gate-rule synthesis and tie-break policy updates.
6. **Unknown input->output structure + recursion handling:** Task complexity manifolds differ across models; recursive clustering and gate refinement learns piecewise routing.
7. **Depth-per-layer0-turn score (1-10):** 8.

### 5) Adversarial Prompt Mutation Tournament
1. **Task title:** Adversarial Prompt Mutation Tournament
2. **Recursive experiment loop:** `L0: pick seed prompts -> L1: mutate prompt families -> L2: evaluate robustness and exploitability -> L3+: mutate strongest attacks/defenses`.
3. **Expected layer-0 turn budget:** 12-17 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 30% / 40% / 30%.
5. **`llm_query` / `llm_query_batched` fold points:** batched mutation generation and tournament scoring; single-query fold for selecting mutation operators and pruning search.
6. **Unknown input->output structure + recursion handling:** Discontinuous jailbreak/robustness thresholds; recursion performs local neighborhood search around emergent breakpoints.
7. **Depth-per-layer0-turn score (1-10):** 9.

### 6) Agent Memory Compression Fidelity Sweep
1. **Task title:** Agent Memory Compression Fidelity Sweep
2. **Recursive experiment loop:** `L0: choose compression ratio bands -> L1: compress memory states via multiple schemes -> L2: run downstream tasks and detect semantic drift -> L3+: targeted rehydration and re-compression`.
3. **Expected layer-0 turn budget:** 9-13 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 50% / 35% / 15%.
5. **`llm_query` / `llm_query_batched` fold points:** batched downstream regression tests at each ratio; single-query fold for diagnosing drift causes and adjusting retention heuristics.
6. **Unknown input->output structure + recursion handling:** Critical facts are unevenly distributed and not obvious from token salience; recursion identifies high-impact omissions and reweights memory slots.
7. **Depth-per-layer0-turn score (1-10):** 7.

### 7) Recursive Failure Taxonomy Discovery
1. **Task title:** Recursive Failure Taxonomy Discovery
2. **Recursive experiment loop:** `L0: ingest mixed benchmark logs -> L1: cluster failures coarsely -> L2: split clusters by causal signals -> L3+: induce per-leaf remediation experiments`.
3. **Expected layer-0 turn budget:** 10-15 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 25% / 45% / 30%.
5. **`llm_query` / `llm_query_batched` fold points:** batched labeling and cluster summarization; single-query fold for deciding split criteria and remediation assignment.
6. **Unknown input->output structure + recursion handling:** Failure classes are latent and overlapping; recursion refines taxonomy until intervention efficacy becomes separable.
7. **Depth-per-layer0-turn score (1-10):** 8.

### 8) Latency-Quality Pareto Auto-Tuning Loop
1. **Task title:** Latency-Quality Pareto Auto-Tuning Loop
2. **Recursive experiment loop:** `L0: set SLA bands -> L1: sweep decoding/tool/retrieval parameters -> L2: fit Pareto front -> L3+: local search near knees with micro-ablations`.
3. **Expected layer-0 turn budget:** 9-12 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 55% / 30% / 15%.
5. **`llm_query` / `llm_query_batched` fold points:** batched parameter sweep evaluation; single-query fold for knee-point hypothesis and next-step search direction.
6. **Unknown input->output structure + recursion handling:** Response quality responds non-monotonically to coupled knobs; recursion narrows around frontier discontinuities.
7. **Depth-per-layer0-turn score (1-10):** 7.

### 9) Hierarchical Curriculum Search for Hard-Case Lift
1. **Task title:** Hierarchical Curriculum Search for Hard-Case Lift
2. **Recursive experiment loop:** `L0: define baseline competency map -> L1: construct curriculum buckets by difficulty -> L2: train/eval per bucket sequence -> L3+: regenerate bucket boundaries from residual errors`.
3. **Expected layer-0 turn budget:** 13-18 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 30% / 35% / 35%.
5. **`llm_query` / `llm_query_batched` fold points:** batched scoring of curriculum permutations; single-query fold for re-bucketing rules and transfer-gap diagnosis.
6. **Unknown input->output structure + recursion handling:** Difficulty is not total-order and depends on latent skill prereqs; recursion rebuilds hierarchy from observed transfer failures.
7. **Depth-per-layer0-turn score (1-10):** 8.

### 10) Self-Healing Plan Executor With Branch-and-Bound Retries
1. **Task title:** Self-Healing Plan Executor With Branch-and-Bound Retries
2. **Recursive experiment loop:** `L0: run task plan -> L1: detect failed step -> L2: branch retry strategies (tool swap/order change/context rewrite) -> L3+: bound and prune retry tree by posterior success`.
3. **Expected layer-0 turn budget:** 10-14 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** 35% / 40% / 25%.
5. **`llm_query` / `llm_query_batched` fold points:** batched evaluation of retry branches on replay set; single-query fold for pruning policy and confidence calibration.
6. **Unknown input->output structure + recursion handling:** Error recoverability depends on hidden state/tool interactions; recursion explores branches while preserving stable L0 guardrails.
7. **Depth-per-layer0-turn score (1-10):** 9.

## Top 3 Ranked Tasks
1. **Counterexample-Guided Program Synthesis Ladder** (Score: 10)  
   Highest recursive leverage: each L0 step spawns multiple candidate/counterexample subtrees with direct hypothesis-test closure.
2. **Retrieval Pipeline Ablation Under Distribution Shift** (Score: 9)  
   Strong decomposition under real-world nonstationarity; high experimental density with reusable batched folds.
3. **Adversarial Prompt Mutation Tournament** (Score: 9)  
   Naturally recursive exploit/defense co-evolution that produces deep search trees without destabilizing layer-0 control.

## Layer-0 Stability Notes (applies to all tasks)
- Keep a fixed L0 controller contract: objective, global budget, stop conditions, and acceptance thresholds remain immutable during recursive branches.
- Constrain recursion with branch caps, confidence thresholds, and rollback checkpoints to prevent drift.
- Force every recursive branch to return `(artifact, metric delta, confidence, next action)` so L0 can arbitrate deterministically.
