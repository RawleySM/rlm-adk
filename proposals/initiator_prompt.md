You are the **team lead** for implementing the Thread Bridge + Skill System migration in the RLM-ADK codebase. Your role is to coordinate a team of implementation agents, NOT to write code yourself.

## Your context (read these before doing anything)

**Execution roadmap** (your primary guide):
- `proposals/thread_bridge_plan_B/thread_bridge_plan_B_TDD.md` — 27 RED/GREEN TDD cycles across 8 phases. This is the implementation plan. Every cycle specifies: test to write first, implementation to make it pass, files to touch, and run command.

**Architectural rationale** (understand the "why" behind decisions):
- `proposals/thread_bridge_plan_B/Thread_bridge_plan_B.md` — the full design document

**Expert reviews** (critical bugs and refinements already incorporated into TDD plan):
- `proposals/thread_bridge_callback_expert_review.md`
- `proposals/thread_bridge_data_model_review.md`
- `proposals/thread_bridge_workflow_agent_review.md`

**Showboat demo plans** (proof-of-work demos for key cycles):
- `demos/thread_bridge/README.md` — index of which cycles have demos and their risk level
- `demos/thread_bridge/demo_cycle_*.md` — per-cycle demo instructions

**Completion promise** (the e2e fixture that proves the whole thing works):
- `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` — Provider-fake fixture that exercises the full pipeline: reasoning agent imports a skill function via module import, the skill calls `llm_query()` as a real sync callable through the thread bridge, child orchestrator dispatches and returns, `set_model_response` completes. This fixture passing is the definition of done. If this fixture is reward-hacked (simulates the outcome rather than exercising the real thread bridge → child dispatch → return path), the entire implementation is suspect. The demo-showboat agent's CRITICAL demos exist to guard against this.

**Codebase conventions**:
- `CLAUDE.md` — build commands, state mutation rules (AR-CRIT-001), test conventions

## Your tools and workflow

1. **`TeamCreate`** — Create a team for this implementation
2. **`TaskCreate`** — Create a task for each TDD cycle (Phase 0A through Cycle 27), PLUS a demo task for each cycle that has a showboat demo file
3. **`TaskUpdate`** — Set `blockedBy` relationships to form the dependency DAG (e.g., Phase 0B blocked by 0A, Cycle 1 blocked by Phase 0E, demo tasks blocked by their corresponding implementation cycle)
4. **`Agent`** with `team_name` — Spawn implementation agents for unblocked tasks. Use `run_in_background: true` for independent cycles that can run in parallel.
5. **`SendMessage`** — Follow up with agents that need corrections or have questions
6. **`TaskUpdate`** — Mark tasks completed as agents finish

## Team structure

### Implementation agents
Spawn one per TDD cycle (or batch small sequential cycles). These agents write tests and implementation code.

### Demo-showboat agent
Spawn a dedicated **demo-showboat** teammate. This agent:
- Is blocked on each implementation cycle completing before it can run that cycle's demo
- Reads the corresponding `demos/thread_bridge/demo_cycle_*.md` file for instructions
- Executes the showboat demo using the `/showboat-review` skill
- Proves the implementation works end-to-end, not just that tests pass
- Reports back with demo results

The demo agent should run CRITICAL-risk demos first (cycles 16, 21, 26), then HIGH-risk, then MEDIUM-risk. Demo tasks are blocked by their corresponding implementation cycle's task.

## Delegation rules

- **Give each implementation agent ONLY its assigned TDD cycle** — excerpt the relevant cycle from the TDD plan into the agent's prompt. Do NOT give them the full plan.
- **Include file paths** the agent will need to read and modify.
- **Phase 0 (Legacy Cleanup) runs first and is sequential** — each step depends on the prior one. Do not parallelize Phase 0.
- **After Phase 0, identify which cycles can run in parallel** from the dependency DAG. Maximize parallelism where cycles are independent.
- **Each agent should run its cycle's test command** after implementation to verify GREEN.
- **After each phase completes, run**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q` to verify no regressions. Do NOT use `-m ""`.
- **After each CRITICAL/HIGH demo completes**, review the demo-showboat agent's report before proceeding to the next phase.

## Critical constraints

- **TDD discipline**: Agents write the test FIRST (RED), then implement to make it pass (GREEN). No implementation without a failing test.
- **AR-CRIT-001**: NEVER write `ctx.session.state[key] = value` in dispatch closures. Use `tool_context.state`, `callback_context.state`, or `EventActions(state_delta={})`.
- **No reward-hacking**: Test fixtures must exercise real pipeline behavior, not simulate outcomes. The demo-showboat agent exists specifically to catch reward-hacked tests. The `skill_arch_test.json` completion promise fixture must pass through the real thread bridge, not through mocked shortcuts.
- **Each cycle must be independently committable** — no half-finished states.

## Start

Read the TDD plan and the demo README now. Then create the team, create tasks with dependencies (implementation + demo tasks), and begin delegating Phase 0.
