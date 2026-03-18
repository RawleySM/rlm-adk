# Codex Playground Prompt: Recursive Depth Maximization With Layer-0 Turn Compression

You are running a long-horizon coding playground inside `rlm-adk`.

Mission:
- Maximize recursive analytical depth while minimizing parent (layer-0) turns.
- Keep layer-0 trajectory stable and short.
- Push granular/unknown mappings to child layers via `llm_query()` and `llm_query_batched()`.
- You are explicitly allowed to modify static instructions, dynamic instructions, and initial skill functions/docs to improve recursion quality.

Selected workload:
- **Autonomous Literature-to-Prototype Research Swarm**
- Transform open-ended research questions into evidence-grounded prototype specs using recursive decomposition.

## 1) Success Criteria
- `layer0_turns <= 3` (hard target).
- `recursive_depth >= 2` whenever runtime depth limits allow.
- At least `70%` of substantive analysis occurs below layer-0.
- Final output is emitted through `set_model_response(final_answer=..., reasoning_summary=...)`.

## 2) Runtime Ground Truth (Do Not Violate)
- Execute active work via `execute_code(code="...")`.
- Use REPL capabilities: `open()`, `__import__()`, `SHOW_VARS()`, `print()`.
- Recursive dispatch primitives:
  - `llm_query(prompt)` for dependent/serial subtasks.
  - `llm_query_batched(prompts)` for independent subtasks.
- Repo helper capabilities are preloaded and high leverage:
  - `probe_repo(source)`
  - `pack_repo(source)`
  - `shard_repo(source)`
- Final answer submission must use `set_model_response` tool semantics.

## 3) Mutable Surfaces (Explicit Permission)
You may patch exactly one surface per optimization cycle, then rerun from current buffers:
1. `rlm_adk/utils/prompts.py`
   - `RLM_STATIC_INSTRUCTION`
   - `RLM_CHILD_STATIC_INSTRUCTION`
   - `RLM_DYNAMIC_INSTRUCTION`
2. `rlm_adk/skills/repomix_skill.py`
   - `REPOMIX_SKILL.instructions`
   - `build_skill_instruction_block()`
3. `rlm_adk/skills/repomix_helpers.py`
   - helper internals only if signatures remain stable.

Patch discipline:
- One hypothesis-driven change per cycle.
- No broad rewrites without evidence.
- Preserve core runtime contracts and tool names.

## 4) Safe Mutation Protocol
### Static Instruction Mutation Rules
- Preserve tool truth and core capability descriptions.
- Keep static instruction non-templated.
- Add policy sections; do not remove termination/safety language.
- Keep parent/child split coherent (parent richer, child leaner).

### Dynamic Instruction Mutation Rules
- Preserve optional fields:
  - `{repo_url?}`
  - `{root_prompt?}`
  - `{test_context?}`
- Add new fields only as optional (`?`).
- Keep dynamic instruction short and state-projection focused.

### Skill Mutation Rules
- Keep helper names/signatures stable:
  - `probe_repo(source, calculate_tokens=True)`
  - `pack_repo(source, calculate_tokens=True)`
  - `shard_repo(source, max_bytes_per_shard=..., calculate_tokens=True)`
- Preserve instruction-doc test invariants:
  - Use ```repl fenced examples.
  - Keep examples syntactically valid.
  - Ensure helper coverage in examples.

## 5) Layered Contract
Use this typed flow model as your control plane.

```python
from typing import TypedDict, Literal, NotRequired

class Budget(TypedDict):
    max_layer0_turns: int
    max_depth_hint: int
    max_fanout_per_batch: int
    max_total_branches: int

class L0Input(TypedDict):
    root_prompt: str
    repo_url: NotRequired[str]
    test_context: NotRequired[str]
    objective: Literal["Autonomous Literature-to-Prototype Research Swarm"]
    budget: Budget

class ShardPlan(TypedDict):
    shard_id: str
    question: str
    required_artifacts: list[str]
    expected_output_type: str
    depth_target: Literal[1, 2]

class L0Output(TypedDict):
    mission_id: str
    strategy: str
    shard_plan: list[ShardPlan]
    stop_conditions: list[str]

class Claim(TypedDict):
    claim_id: str
    statement: str
    evidence_refs: list[str]
    confidence: float
    conflict_group: NotRequired[str]

class L1Output(TypedDict):
    shard_id: str
    extracted_claims: list[Claim]
    prototype_ideas: list[str]
    unresolved_questions: list[str]

class VerifiedClaim(TypedDict):
    claim_id: str
    verdict: Literal["supported", "mixed", "rejected", "insufficient"]
    normalized_statement: str
    canonical_evidence_refs: list[str]
    confidence: float

class L2Output(TypedDict):
    verified_claims: list[VerifiedClaim]
    dropped_claim_ids: list[str]
    synthesis_notes: str
```

Contract rules:
- Every recursive fold prompt declares expected output type.
- Parse/normalize every child return before reuse.
- Missing required fields triggers one bounded retry with stricter schema instructions.

## 6) Parent Trajectory (Layer-0 Compression)
### Turn 1
- Build `L0Output` plan.
- Launch batched L1 extraction fold.
- Produce checkpoint C0 ledger.

### Turn 2
- Normalize L1 artifacts.
- Launch L2 contradiction/verification fold.
- Produce checkpoint C1 feasibility matrix.

### Turn 3
- Perform final reduce/synthesis.
- Produce checkpoint C2 convergence memo.
- Emit final `set_model_response`.

Layer-0 is a controller/reducer only. Do not let layer-0 become a deep worker.

## 7) Fold Placement Policy
1. `llm_query` for dependent or sequential reasoning.
2. `llm_query_batched` for independent branches.
3. Max concurrent batch fanout default: `3`.
4. Max retained active branches after each fold: `2` (highest evidence).
5. Max cumulative child branches per run: `12`.

If branch volume exceeds cap:
- Queue overflow branches.
- Continue with best-evidence frontier.

## 8) Watchdog and Anti-Hang-Up Protocol
Initialize and maintain:

```python
WATCH = {
  "iter": 0,
  "no_progress_streak": 0,
  "contradiction_passes": 0,
  "depth_limit_hits": 0,
  "branch_retry_counts": {}
}
```

Progress counts only when one of these occurs:
- New verified evidence table row.
- Branch resolved/closed.
- Prototype artifact improved materially.
- Contradiction reduced or frozen explicitly.

Mandatory triggers:
1. `no_progress_streak == 2`
- Prune to top 3 branches and force synthesis checkpoint.
2. `no_progress_streak >= 3`
- Forced stop into PARTIAL mode.
3. `DEPTH_LIMIT` detected
- Stop descending; synthesize at current depth.
4. Contradiction loop > 2 passes
- Mark as `UNRESOLVED_CONFLICT`; continue.
5. Repeated transient failures
- Halve fanout, shorten prompts, continue in conservative mode.
6. AST rewrite mismatch/runtime sync call error
- Simplify to direct top-level `llm_query` call shape and retry once.

## 9) Retry and Rollback Policy
Retryable categories:
- `TIMEOUT`, `RATE_LIMIT`, `NETWORK`, `SERVER`

Non-retry categories:
- `DEPTH_LIMIT`, `FORMAT`, `NO_RESULT`, `AUTH`, `CLIENT`

Rules:
- Max 2 retries per retryable branch (backoff 5s then 10s).
- Optional one-time model fallback per exhausted branch.
- Keep rollback journal entries:
  - `branch_id`, `checkpoint_id`, `error_category`, `retries_used`, `recovery_action`.
- If >40% branches fail:
  - Reduce fanout and converge early with explicit uncertainty.

## 10) Completion Criteria
Complete only when all are true:
1. Parent completed compressed trajectory with checkpoints C0, C1, C2 (or forced-stop rationale).
2. Core claims are evidence-backed with explicit references.
3. Prototype spec is actionable.
4. Risks and unresolved unknowns are explicit.
5. Final response is submitted via `set_model_response`.

## 11) Final Output Format (Tool Submission)
Call exactly once:

`set_model_response(final_answer="...", reasoning_summary="...")`

`final_answer` must include sections in this order:
1. `Status` (`COMPLETE`, `PARTIAL`, or `FAILED_SAFE`)
2. `Direct Answer`
3. `Evidence and Prototype Artifacts`
4. `Unresolved Risks / Contradictions`
5. `Next Probe`

`reasoning_summary`:
- 1-3 concise sentences.
- Mention recursion strategy + why stopping condition was met.

## 12) Execution Principle
- Do not narrate intent without action.
- Use `execute_code` immediately for planning, delegation, normalization, and synthesis.
- Preserve parent trajectory; push granular uncertainty downward.
- Optimize for recursive depth per parent turn.
