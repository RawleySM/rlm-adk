# Gap Review: Architecture

## Accuracy Check
Status: **Partially correct**.

Correct findings:
- Fixed reasoning output key collision risk is real (`rlm_adk/agent.py:219`, `rlm_adk/orchestrator.py:255-275`).
- Dispatch worker contract is currently leaf-`LlmAgent`-specific (`rlm_adk/dispatch.py:368-380`, `rlm_adk/dispatch.py:433-497`).
- Worker event suppression is real (`rlm_adk/dispatch.py:216-219`).

Missing / under-specified findings:
- The report does not define how child orchestrators get **state-isolated invocation context**; today workers run with shared `ctx` (`rlm_adk/dispatch.py:386-413`).
- Structured-output path for worker calls (`output_schema`) currently depends on leaf-worker tool callbacks (`rlm_adk/dispatch.py:373-380`, `rlm_adk/callbacks/worker_retry.py:74-158`); recursive replacement needs explicit parity design.
- It does not specify how model override (`model=` in `llm_query*`) maps into child orchestrator creation.

## Corrections Needed
- Treat child invocation/state isolation as first-class architecture item, not an implementation detail.
- Define explicit parity for `output_schema` behavior in recursive workers.
- Define model-routing behavior for child orchestrators.

## Required Edits for `recursive_repl.md`
1. Add a "Child Invocation Context Strategy" section.
2. Add a "Structured Output Parity" section for `llm_query(..., output_schema=...)`.
3. Add an explicit "Model Routing" subsection under runtime model.

## Priority Patch Recommendations
1. P0: Define child context isolation contract and merge-back boundary.
2. P0: Define structured-output parity semantics for recursive workers.
3. P1: Define model selection propagation to child orchestrator runtime.
