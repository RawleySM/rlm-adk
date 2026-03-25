# GAP-OB-002: Dashboard repl_expanded_code is always empty string
**Severity**: MEDIUM
**Category**: observability
**Files**: `rlm_adk/dashboard/live_loader.py`, `rlm_adk/dashboard/live_models.py`, `rlm_adk/dashboard/flow_builder.py`, `rlm_adk/dashboard/live_controller.py`

## Problem

The dashboard's `LiveInvocation` and `LiveRunSnapshot` models include a `repl_expanded_code` field (`live_models.py` lines 198 and 233) that is always set to the empty string `""` in `live_loader.py` line 1071:

```python
repl_expanded_code="",
```

In the old architecture, the AST rewriter would transform submitted code (replacing `llm_query()` calls with async dispatch wrappers) and the expanded version was stored in a `REPL_EXPANDED_CODE` state key. The thread bridge eliminated this rewriting step -- `llm_query()` is now a real sync callable -- so there is no expanded code that differs from the submitted code.

The downstream consumers still reference this field:

1. `flow_builder.py` line 107: `expanded = inv.repl_expanded_code or ""`
2. `flow_code_pane.py` line 81: `code = cell.code or cell.expanded_code`
3. `live_controller.py` lines 573-584: Uses `repl_expanded_code` as a fallback for parent code text in child dispatch views

In all cases the fallback to `repl_submission` works correctly, so no data is lost. But the data model carries a vestigial field that can never be populated, and the `REPL_EXPANDED_CODE` / `REPL_EXPANDED_CODE_HASH` / `REPL_SKILL_EXPANSION_META` / `REPL_DID_EXPAND` constants referenced in `rlm_adk_docs/observability.md` no longer exist in `state.py`.

## Evidence

- `live_loader.py` line 1071: hardcoded `repl_expanded_code=""`
- No `REPL_EXPANDED_CODE` constant exists in `state.py`
- `rlm_adk_docs/observability.md` lines 384-400 still document these keys as active
- Grep for `REPL_EXPANDED_CODE` in `rlm_adk/*.py` returns zero hits (only docs)

## Suggested Fix

1. Remove `repl_expanded_code` from `LiveInvocation`, `LiveRunSnapshot`, and `FlowCodeCell` models.
2. Update `flow_builder.py` and `live_controller.py` to use `repl_submission` directly.
3. Update `rlm_adk_docs/observability.md` to remove the stale REPL_EXPANDED_CODE documentation section.
