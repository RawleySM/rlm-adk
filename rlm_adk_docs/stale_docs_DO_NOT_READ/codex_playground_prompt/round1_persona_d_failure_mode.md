# Persona D: Failure-Mode Strategist (Round 1)

## Top 3 Ranked Tasks
1. **Conflicting Incident Timeline Reconstructor** (Score: 10)
2. **Unknown API Contract Recovery Drill** (Score: 9)
3. **Schema Drift + Backfill Repair Planner** (Score: 9)

## Candidate Tasks

### 1) Conflicting Incident Timeline Reconstructor
1. **Task title:** Conflicting Incident Timeline Reconstructor
2. **Edge-case surface area:** Cross-system clock skew, duplicated event IDs, missing timezone metadata, reordered log shards, partial retries that mimic new incidents.
3. **Expected layer-0 turn budget:** 2-3 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 split by source reliability; L2 normalize timestamp/entity identity; L3+ branch unresolved contradictions into explicit uncertainty nodes.
5. **llm_query/llm_query_batched fold points:** Use `llm_query_batched` for per-source event extraction and confidence tagging; fold to `llm_query` for global chronology arbitration and final recovery plan.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: endless contradiction reconciliation loop. Anti-stall clause: "After 2 reconciliation passes, freeze unresolved conflict as `UNRESOLVED_CONFLICT` and continue forward synthesis." Hang-up: timestamp ambiguity paralysis. Anti-stall clause: "Apply deterministic tie-breakers in order: signed clock confidence, source priority map, lexical timestamp fallback."
7. **Depth-per-layer0-turn score (1-10):** 10

### 2) Unknown API Contract Recovery Drill
1. **Task title:** Unknown API Contract Recovery Drill
2. **Edge-case surface area:** Incomplete OpenAPI fragments, undocumented error payloads on 200 responses, polymorphic fields, version-skewed clients.
3. **Expected layer-0 turn budget:** 2-4 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 infer endpoint-level contract hypotheses; L2 infer field-level invariants; L3+ isolate incompatible hypothesis branches and fallback adapter rules.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for endpoint-by-endpoint schema inference; `llm_query` for cross-endpoint invariant merge and adapter contract finalization.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: hypothesis explosion. Anti-stall clause: "Cap active hypotheses to top 3 by evidence weight per endpoint." Hang-up: deadlock on conflicting captures. Anti-stall clause: "If conflict persists after 1 merge cycle, emit explicit version gate and proceed with dual-path adapter."
7. **Depth-per-layer0-turn score (1-10):** 9

### 3) Schema Drift + Backfill Repair Planner
1. **Task title:** Schema Drift + Backfill Repair Planner
2. **Edge-case surface area:** Silent type coercions, null/empty semantic drift, key dedup ambiguity, historical partition corruption.
3. **Expected layer-0 turn budget:** 3 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 table-family drift scan; L2 column-level drift taxonomy; L3+ exception routing for backfill repair and reconciliation proofs.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for table/column drift classification; `llm_query` for global migration order and rollback-safe backfill strategy.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: migration ordering cycles. Anti-stall clause: "Break cycles using write-path criticality ordering and flag deferred non-critical repairs." Hang-up: incomplete lineage metadata. Anti-stall clause: "Assume conservative lineage, mark confidence level, and continue with reversible transforms only."
7. **Depth-per-layer0-turn score (1-10):** 9

### 4) Policy Stack Contradiction Resolver
1. **Task title:** Policy Stack Contradiction Resolver
2. **Edge-case surface area:** Overlapping allow/deny clauses, exception precedence loops, regional overrides, stale policy fragments.
3. **Expected layer-0 turn budget:** 2-3 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 cluster policies by scope; L2 compute precedence graph; L3+ isolate contradiction SCCs and produce minimal override patches.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for clause extraction and precedence edge inference; `llm_query` for contradiction collapse and patch recommendation.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: circular precedence reasoning. Anti-stall clause: "Collapse SCC into meta-node and require explicit tie-break precedence token." Hang-up: overfitting to one jurisdiction. Anti-stall clause: "Preserve per-region branch until final fold; never overwrite global defaults in branch mode."
7. **Depth-per-layer0-turn score (1-10):** 8

### 5) Tool-Chain Partial Outage Self-Healing Orchestrator
1. **Task title:** Tool-Chain Partial Outage Self-Healing Orchestrator
2. **Edge-case surface area:** Timeouts, malformed JSON, stale cache echoes, non-idempotent retries, partial side effects.
3. **Expected layer-0 turn budget:** 3 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 classify failure mode per tool; L2 map retry/fallback strategy; L3+ synthesize compensation steps for partially applied side effects.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for parallel tool health diagnostics; `llm_query` for single recovery DAG and stop conditions.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: infinite retry loops. Anti-stall clause: "Max 2 retries per class, then forced degrade path." Hang-up: uncertain side-effect state. Anti-stall clause: "Insert read-after-write verification gate before every compensation action."
7. **Depth-per-layer0-turn score (1-10):** 8

### 6) Flaky Test Root-Cause Decision Tree Builder
1. **Task title:** Flaky Test Root-Cause Decision Tree Builder
2. **Edge-case surface area:** Seed sensitivity, race conditions, environment drift, hidden test order coupling.
3. **Expected layer-0 turn budget:** 2-3 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 split by failure signature; L2 correlate with infra/runtime variables; L3+ derive minimal deterministic reproducer branches.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for test-run cluster analysis; `llm_query` for unified decision tree and remediation ordering.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: noisy false clusters. Anti-stall clause: "Require minimum cluster support threshold before branch creation." Hang-up: no repro found. Anti-stall clause: "Emit quarantine recommendation plus targeted instrumentation plan after one failed repro sweep."
7. **Depth-per-layer0-turn score (1-10):** 8

### 7) RAG Evidence Collision Synthesizer
1. **Task title:** RAG Evidence Collision Synthesizer
2. **Edge-case surface area:** Contradictory citations, document staleness, hidden duplicates, semantic drift across versions.
3. **Expected layer-0 turn budget:** 2-3 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 segment claims by topic; L2 align claims to evidence graph; L3+ generate collision-aware answer branches with confidence and abstain gates.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for claim-evidence linking per chunk set; `llm_query` for final contradiction-aware synthesis.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: citation ping-pong. Anti-stall clause: "After 1 contradiction pass, lock evidence graph snapshot and stop re-linking." Hang-up: overconfident merges. Anti-stall clause: "Require dual-source support or downgrade to qualified uncertainty statement."
7. **Depth-per-layer0-turn score (1-10):** 8

### 8) Legacy Config Merger with Shadow Defaults
1. **Task title:** Legacy Config Merger with Shadow Defaults
2. **Edge-case surface area:** YAML/ENV/CLI precedence collisions, implicit defaults, type coercion traps (`"0"` vs `0` vs false), deprecated key aliases.
3. **Expected layer-0 turn budget:** 2 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 parse and normalize source layers; L2 resolve precedence and aliases; L3+ branch on ambiguous coercions and propose safe canonicalization.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for per-source normalization and key mapping; `llm_query` for merged config plus explicit conflict ledger.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: unresolved key synonym chains. Anti-stall clause: "Limit alias chase to depth 2, then mark unresolved alias for manual review." Hang-up: coercion ambiguity. Anti-stall clause: "Default to string-preserving mode unless destination schema certainty >= 0.8."
7. **Depth-per-layer0-turn score (1-10):** 7

### 9) Ambiguous User Story Defensive Decomposer
1. **Task title:** Ambiguous User Story Defensive Decomposer
2. **Edge-case surface area:** Missing acceptance criteria, conflicting stakeholder intents, hidden non-functional constraints, overloaded domain terms.
3. **Expected layer-0 turn budget:** 1-2 turns.
4. **Expected recursion depth profile (L1/L2/L3+):** L1 extract candidate intent branches; L2 attach assumptions and risk gates; L3+ build testable substory variants with fail-closed defaults.
5. **llm_query/llm_query_batched fold points:** `llm_query_batched` for intent branch generation and assumption tagging; `llm_query` for converged low-turn execution path with explicit unknowns.
6. **Likely hang-ups and specific anti-stall instruction clauses:** Hang-up: branch sprawl from open-ended ambiguity. Anti-stall clause: "Retain max 3 intent branches ranked by expected business impact and reversibility." Hang-up: premature commitment. Anti-stall clause: "Carry unresolved assumptions as contract clauses; do not silently decide missing requirements."
7. **Depth-per-layer0-turn score (1-10):** 7

## Ranking Rationale (Compact)
- **#1** Timeline reconstruction concentrates contradiction resolution, uncertainty handling, and recovery in one low-turn loop.
- **#2** Unknown API recovery forces recursive hypothesis testing with high practical failure-mode coverage.
- **#3** Schema drift repair combines latent-structure discovery and rollback-safe decomposition with strong defensive recursion.
