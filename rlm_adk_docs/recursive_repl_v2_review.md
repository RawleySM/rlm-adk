# Review: recursive_repl_v2.md

## Findings
- `P1` [rlm_adk_docs/recursive_repl_v2.md, section `## 10) P0/P1 Risk Register and Release Gates`]: `recursion/fanout runaway` is mapped to a single test file (`test_recursive_fanout_budget_limits.py`) while the gate rule asserts three independent controls (depth, per-batch fanout, in-flight semaphore). This is valid but weakly decomposed for debugging failures. Split assertions into dedicated tests or clearly subcase-marked parametrization.
- `P2` [rlm_adk_docs/recursive_repl_v2.md, section `## 10) P0/P1 Risk Register and Release Gates`]: `execution surface/security containment regression` gate currently combines raw-key write protection and containment behavior in one test file (`test_recursive_security_containment.py`). Separation would improve failure localization.
- `P2` [rlm_adk_docs/recursive_repl_v2.md, section `### Release Decision Rule`]: P1 waiver policy is clear for non-production, but the artifact requirement for waiver approval is underspecified (where waiver record is stored and who signs off).

## Open Questions
- Should depth-budget enforcement be validated in a dedicated test file (for example `test_recursive_depth_budget_limits.py`) or kept as a subcase inside `test_recursive_fanout_budget_limits.py`?
- For P1 waivers in non-production, what is the authoritative storage location and approver role for the waiver record?

## Verdict
APPROVE WITH CHANGES

## Required Edits
1. In section `## 10) P0/P1 Risk Register and Release Gates`, update the `recursion/fanout runaway` row so required tests explicitly cover:
   - depth cap enforcement,
   - per-batch fanout cap,
   - in-flight semaphore cap.
   Acceptable implementation: one file with explicit subcases listed in Gate Rule, or split into three files.
2. In the `execution surface/security containment regression` row, separate state-write guard validation from runtime containment validation (either by two files or explicit two-subcase gate text).
3. In `### Release Decision Rule`, add one sentence defining waiver governance fields: required owner, approver, expiry date, and storage path for the waiver record.
