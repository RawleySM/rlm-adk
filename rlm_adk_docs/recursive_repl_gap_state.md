# Gap Review: State

## Accuracy Check
Status: **Mostly correct**.

Correct findings:
- `request_id`, `iteration_count`, and `last_repl_result` collision surfaces are real (`rlm_adk/orchestrator.py:174-178`, `rlm_adk/tools/repl_tool.py:81-84`, `rlm_adk/tools/repl_tool.py:130-185`).
- Worker output key collision risk exists in current leaf-worker design (`rlm_adk/dispatch.py:113-125`, `rlm_adk/callbacks/worker.py:134-137`).

Missing / under-specified findings:
- Reasoning callback writes (`REASONING_PROMPT_CHARS`, `REASONING_SYSTEM_CHARS`, `CONTEXT_WINDOW_SNAPSHOT`) are also unsuffixed and can pollute nested attribution (`rlm_adk/callbacks/reasoning.py:101-117`).
- Observability plugin after-agent re-persistence scans dynamic key prefixes across full session state and can blur child/parent scopes (`rlm_adk/plugins/observability.py:106-127`).
- The current synthesis doc does not define whether scoped keys are additive-only or authoritative for reads.

## Corrections Needed
- Include reasoning callback keys in collision-control list.
- Add a strict read/write policy: child scopes read/write scoped keys; only root writes legacy aliases.
- Define root request identity lock semantics and failure mode if child attempts overwrite.

## Required Edits for `recursive_repl.md`
1. Expand mandatory scoped keys to include reasoning callback accounting keys.
2. Add explicit alias policy (scoped as source-of-truth, legacy root alias optional).
3. Add guardrail rule preventing unsuffixed writes in child scope.

## Priority Patch Recommendations
1. P0: Formalize authoritative scoped-key policy.
2. P0: Scope reasoning/observability per-call accounting keys.
3. P1: Add write-guard instrumentation for child-unsuffixed writes.
