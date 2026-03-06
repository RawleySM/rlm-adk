# Gap Review: Timing/Threading

## Accuracy Check
Status: **Mostly correct**.

Correct findings:
- Blocking sync execution and global lock risks are accurate (`rlm_adk/tools/repl_tool.py:118-119`, `rlm_adk/repl/local_repl.py:77-81`, `rlm_adk/repl/local_repl.py:324-339`).
- Timeout cancellation/reuse race concerns are valid in dispatch (`rlm_adk/dispatch.py:386-430`, `rlm_adk/dispatch.py:592-612`).

Missing / under-specified findings:
- Synthesis doc does not require execution-mode decision: keep sync path with stronger isolation vs. migrate all tool execution through async path.
- It does not define maximum in-flight recursive workers as a strict global/session semaphore requirement.
- It does not define teardown timeout behavior when child refuses cancellation.

## Corrections Needed
- Add an explicit concurrency budget and enforcement point.
- Add a deterministic teardown timeout policy (quarantine + hard drop).
- Add event-loop non-blocking requirement for recursive mode.

## Required Edits for `recursive_repl.md`
1. Add global in-flight semaphore design for recursive calls.
2. Add teardown timeout and quarantine fallback mechanics.
3. Add non-blocking execution requirement for recursive mode.

## Priority Patch Recommendations
1. P0: Concurrency budget with hard cap and tests.
2. P0: Teardown/cancel timeout policy with quarantine.
3. P1: Refactor sync path or offload to dedicated executor for event-loop safety.
