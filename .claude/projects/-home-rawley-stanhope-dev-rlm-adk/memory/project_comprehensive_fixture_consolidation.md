---
name: Comprehensive Fixture Consolidation Initiative
description: Top-down fixture consolidation driven by 4-tool x 3-depth coverage matrix, revealing 4 implementation gaps (child SkillToolset, child skill globals, llm_query_batched_fn injection, child dynamic instruction)
type: project
---

## Initiative: Comprehensive E2E Fixture Consolidation

Goal: Replace ~20 run-to-completion provider-fake fixtures with a single `skill_arch_test.json` that exercises all 4 tools (execute_code, set_model_response, list_skills, load_skill) x all REPL functions (llm_query, llm_query_batched, skill_fn wrapping both) x dynamic instruction state key injection at depths 0-2.

**Why:** Fixtures accumulated during drastic architectural changes. Many are redundant, duplicating assertions without adding real value. A single comprehensive fixture designed from first principles replaces bottom-up migration with top-down coverage definition.

**How to apply:** The fixture specification drives implementation — 4 gaps must be closed before the fixture can exercise them. Approach is: implement gaps via TDD → design fixture → consolidate/delete existing fixtures.

### Four Implementation Gaps (2026-03-25)

1. **GAP-A: Children don't get SkillToolset** — `create_child_orchestrator()` has no `enabled_skills` param
2. **GAP-B: Children don't get skill REPL globals** — same root cause as GAP-A
3. **GAP-C: Skill functions can't use `llm_query_batched`** — `_wrap_with_llm_query_injection()` only injects `llm_query_fn`
4. **GAP-D: Children don't get dynamic instruction template** — child reasoning agent omits `dynamic_instruction=` param

### Key Design Decisions

- Depth=2 sufficiency: if it works at depth 2, it works at depth N (induction principle)
- Error-forcing fixtures (assert stop conditions) stay separate
- ~17 fake-provider responses needed for full coverage
- Runtime cap: ~20 seconds
- Looping command: `loop_test_trim.md` with implementation → fixture-design → consolidation phases
- Free-threaded Python (PEP 703): NOT pursued — bottleneck is import time (10.4s) and async I/O, not GIL contention

### Fixture Response Sequence (Target)

T1-T2: list_skills + load_skill at d0
T3: execute_code with skill_fn dispatching through d0→d1→d2, each depth exercising all 4 tools + dynamic instruction
T4: execute_code with skill_fn wrapping llm_query_batched, cross-turn persistence
T5: set_model_response terminal completion
