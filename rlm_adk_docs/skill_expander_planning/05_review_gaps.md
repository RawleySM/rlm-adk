# Skill Expander: Review & Gap Report

## Critical Gaps

- [GAP-1] **No e2e provider-fake test** — Spec section "End-to-end provider-fake tests" requires a test that exercises `from rlm_repl_skills.ping import run_recursive_ping` through the full pipeline with FakeGeminiServer. The `test_skill_expander_e2e.py` file was not created. This is the highest priority gap.

- [GAP-2] **No observability e2e verification** — Spec section 6 requires verifying both original and expanded code are persisted in state after a real execution. No test asserts `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, or `REPL_DID_EXPAND` in final session state from a contract run.

## Bug Risks

- [BUG-1] **Expansion runs outside try/except** — In `repl_tool.py:158-169`, `expand_skill_imports(code)` runs before the try block at line 171. If expansion raises RuntimeError (unknown module/symbol/name conflict), the error propagates unhandled through `run_async()`. While the spec says expansion errors should be hard errors, the REPLTool currently wraps execution errors into structured `{stdout, stderr}` dicts. An expansion RuntimeError would bypass this and propagate as a raw exception. Should be caught and returned as `stderr` like other execution errors.

- [BUG-2] **`_node` unused variable** — `skill_registry.py:81`: The loop variable `_node` in the synthetic imports iteration is flagged as unused by Pyright. Cosmetic but should be fixed (`_` convention).

## Missing Tests

- [TEST-1] **E2e expansion through pipeline** — No test exercises expansion → has_llm_calls → rewrite_for_async → execution as a single pipeline (spec: "End-to-end provider-fake tests")
- [TEST-2] **Observability state assertion** — No test verifies REPL_EXPANDED_CODE et al in final state (spec: section 6)
- [TEST-3] **Regression: direct llm_query still works** — No explicit regression test for handwritten `llm_query()` code still working after the expansion pass is inserted (spec: "Regression tests")
- [TEST-4] **Regression: existing repl.globals helpers unchanged** — No explicit test that `probe_repo`/`pack_repo`/`shard_repo` still work (covered by contract tests indirectly but not explicitly)
- [TEST-5] **Expansion introduces llm_query into sync code** — No test for the case where submitted code has no llm_query but expansion introduces one (should switch from sync to async path)

## Minor Issues

- [MINOR-1] **Ping skill `_log` format string** — `ping.py:121`: `f"[ping] prompt: {prompt[:120]}..."` could raise if prompt is None. Not currently possible with `build_recursive_ping_prompt` but defensive coding would guard.
- [MINOR-2] **Registry not thread-safe** — `SkillRegistry._exports` dict is modified at import time and read at expansion time. In asyncio this is fine (GIL + no concurrent writes after startup), but worth noting.
- [MINOR-3] **Pyright diagnostics for imports** — Several Pyright `reportMissingImports` for google.adk, google.genai etc. are pre-existing (not caused by this change) but the new files show warnings for `rlm_adk.skills.repl_skills.ping` import in AST tests.
