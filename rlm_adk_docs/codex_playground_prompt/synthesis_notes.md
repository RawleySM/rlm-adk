# Synthesis Notes

## Round 1 Task Selection
Selected task: **Autonomous Literature-to-Prototype Research Swarm**.

Why selected:
- Top depth-per-layer0-turn score (10) from Systems Compression proposals.
- Parent trajectory naturally compresses to ~2-3 turns.
- High recursive fanout potential via literature sharding, claim extraction, contradiction verification, and reduce synthesis.
- Strong fit for child-layer deep dives and web/repo context retrieval.

## Round 2 Source Variants Used
- `round2_persona_e_recursive_prompt_architect.md`
- `round2_persona_f_runtime_dispatch.md`
- `round2_persona_g_skill_system.md`
- `round2_persona_h_failure_proofing.md`

## Best-Part Merge Map
- From Persona E:
  - Typed layer contracts (`L0Output`, `L1Output`, `L2Output`) and fold-placement semantics.
  - Layer-0 turn compression target and schema-finalization discipline.
- From Persona F:
  - Concurrency/fanout caps, evidence checkpoints (C0/C1/C2), retry/rollback details.
- From Persona G:
  - Safe mutation protocol for static/dynamic instructions and skill surfaces.
  - Skill-doc/test invariants for non-breaking updates.
- From Persona H:
  - Watchdog state, deterministic anti-stall triggers, contradiction loop caps, forced-stop logic.

## Final Artifact
- `final_synthesized_playground_prompt.md`
