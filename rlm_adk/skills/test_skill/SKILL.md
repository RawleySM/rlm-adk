---
name: test-skill
description: Architecture introspection skill for provider-fake e2e testing. Exercises state injection, child dispatch via thread bridge, and returns diagnostic data.
---

## Instructions

Use `run_test_skill(child_prompt, emit_debug=True, rlm_state=_rlm_state)` to exercise the full pipeline.
The function calls `llm_query()` via thread bridge and returns a `TestSkillResult` with diagnostic data.
Pass `rlm_state=_rlm_state` explicitly from REPL code to provide state introspection.
