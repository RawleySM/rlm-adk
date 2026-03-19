<!-- validated: 2026-03-09 -->

# Evolution Principles

Core design philosophy guiding RLM-ADK's development. RLM-ADK is Rawley Stanhope's **personal agent** — a recursive, self-improving system that gets better at every task it has done before. It is not a multi-tenant platform. Every design decision optimizes for a single power user.

---

## The agent should get better at tasks it has done before

Every execution produces artifacts (REPL traces, code, structured outputs) that feed back into the skill activation pipeline. The more the agent works, the richer its retrieval context becomes.

See: [dynamic_skill_loading.md](dynamic_skill_loading.md)

## The agent should know what it doesn't know

Gap registries, FMEA matrices, and observability metrics expose blind spots. Autonomous agents should prioritize closing the highest-impact gaps.

See: [autonomous_self_improvement.md](autonomous_self_improvement.md)

## The agent should maintain its own documentation

Stale docs are worse than no docs — they poison agent context. Every coding task that modifies documented behavior must update the corresponding doc. Autonomous staleness checks catch drift that humans miss.

## The agent should optimize its own topology

Polya phase outcomes (did Understanding lead to a good Plan? did the Plan survive Implementation?) provide signal for topology selection. Over time, the agent learns which topology works best for which task types.

See: [polya_topology_engine.md](polya_topology_engine.md)
