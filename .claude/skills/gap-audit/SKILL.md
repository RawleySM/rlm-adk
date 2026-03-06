---
name: gap-audit
description: Manage observability gap registry — status, close, dismiss, defer gaps. Use when asked about gap status, closing gaps, dismissing gaps, or when the stop hook reports pending gaps.
user_invocable: true
---

# Gap Audit Skill

Manages the observability gap registry at `rlm_adk_docs/gap_registry.json`. Every gap must have an explicit disposition — no silent skipping.

## Usage

Parse the user's argument to determine the mode:

- `/gap-audit` or `/gap-audit status` — Show progress
- `/gap-audit close <gap-id>` — Close a gap with evidence
- `/gap-audit dismiss <gap-id>` — Dismiss a gap with reason
- `/gap-audit defer <gap-id>` — Defer a gap with reason

## Status Mode

Read `rlm_adk_docs/gap_registry.json` and print a progress table grouped by disposition:

```
Gap Registry Status (mode: report)
Progress: 28/61 resolved (46%)

PENDING (33):
  CRITICAL: OG-01, OG-02, OG-03, OG-04
  HIGH:     OG-05, OG-06, OG-07, OG-08
  MEDIUM:   OG-09 through OG-21, OG-24
  LOW:      OG-22, OG-23, OG-25 through OG-33

CLOSED (0): none yet

DEFERRED (28): OD-01 through OD-28
```

No writes in status mode.

## Close Mode (`/gap-audit close <gap-id>`)

Preconditions — enforce ALL before writing:

1. Read the gap entry. It must currently be `pending`.
2. Ask the agent (or user) which `evidence_tier` applies:
   - `demo_verified` — For CRITICAL/HIGH gaps. Requires:
     - `demo_path`: path to a showboat demo markdown file
     - Run `uvx showboat verify <demo_path>` — must exit 0
     - `test_paths`: at least one test file path
     - Run `.venv/bin/python -m pytest <test_paths> -v` — must pass
     - `code_paths`: at least one source file path
   - `test_only` — For MEDIUM gaps. Requires:
     - `test_paths`: at least one test file path
     - Run `.venv/bin/python -m pytest <test_paths> -v` — must pass
     - `code_paths`: at least one source file path
   - `code_review` — For LOW gaps only. Requires:
     - `code_paths`: at least one source file path
     - Emit a warning: "code_review tier — consider adding tests for stronger evidence"

3. Update the gap entry in the registry JSON:
   ```json
   {
     "disposition": "closed",
     "disposition_category": null,
     "disposition_reason": null,
     "disposition_date": "YYYY-MM-DD",
     "evidence": {
       "test_paths": ["tests_rlm_adk/test_foo.py"],
       "demo_path": "demo_showboat/demo_foo.md",
       "code_paths": ["rlm_adk/foo.py"],
       "evidence_tier": "demo_verified"
     }
   }
   ```

4. Run `.claude/skills/gap-audit/scripts/gap_guard.py --check-only` to validate the updated registry.

## Dismiss Mode (`/gap-audit dismiss <gap-id>`)

Requirements:

1. Gap must currently be `pending`.
2. Pick a `disposition_category` from this controlled vocabulary:
   - `redundant_with_active` — Covered by another active gap
   - `low_value_detail` — Implementation detail, not worth instrumenting
   - `perf_outside_scope` — Performance telemetry outside current goal
   - `platform_maturity` — Platform/analytics maturity work
   - `by_design_privacy` — Intentionally excluded for privacy/size
   - `by_design_architecture` — Intentionally excluded by architecture
   - `superseded` — Replaced by a different approach
   - `out_of_scope` — Outside current project scope
3. Write a `disposition_reason` of >= 50 characters explaining WHY (not just what).
4. **For CRITICAL/HIGH severity gaps**: Warn the user and require explicit confirmation before writing. These are the most important gaps — dismissing them should be rare and well-justified.
5. Update the gap entry:
   ```json
   {
     "disposition": "dismissed",
     "disposition_category": "by_design_privacy",
     "disposition_reason": "The actual code content is potentially large and contains user data...",
     "disposition_date": "YYYY-MM-DD"
   }
   ```
6. Run `.claude/skills/gap-audit/scripts/gap_guard.py --check-only` to validate.

## Defer Mode (`/gap-audit defer <gap-id>`)

Like dismiss but lighter:

1. Gap must currently be `pending`.
2. Pick a `disposition_category` (same vocabulary as dismiss).
3. Write `disposition_reason` >= 50 chars.
4. Optionally accept an `unblock_condition` describing when this gap should be re-activated.
5. Update the gap entry:
   ```json
   {
     "disposition": "deferred",
     "disposition_category": "perf_outside_scope",
     "disposition_reason": "Performance instrumentation phase not yet started...",
     "disposition_date": "YYYY-MM-DD",
     "unblock_condition": "When performance analysis phase begins"
   }
   ```
6. Run `.claude/skills/gap-audit/scripts/gap_guard.py --check-only` to validate.

## Important Notes

- The registry is the **source of truth**. Do not edit `observability_gaps.md` or `observability_gaps_deferred.md` for disposition changes.
- The Stop hook (`.claude/skills/gap-audit/scripts/gap_guard.py`) runs automatically when Claude Code stops. In `report` mode it reports progress; in `strict` mode it blocks if gaps remain pending.
- To switch modes, edit `meta.mode` in `gap_registry.json` (`"report"` or `"strict"`).
- Gap IDs follow the pattern `OG-NN` (active) or `OD-NN` (deferred).
- Schema is at `rlm_adk_docs/gap_registry.schema.json`.
