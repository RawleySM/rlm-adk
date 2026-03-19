# `rlm_adk/state.py`

## Findings
1. Low: the file still exports the old reasoning/lineage state constants and a deprecated `FINAL_ANSWER`, even though the refactor’s end state was “working/control state only” and no compatibility retention unless necessary. Relevant lines: `rlm_adk/state.py:23-30`, `rlm_adk/state.py:69-73`.
2. Low: `child_obs_key()` remains even though the refactor removed `obs:child_summary@d{D}f{F}` as a required transport mechanism. Relevant lines: `rlm_adk/state.py:123-125`.

## Legacy / dead code
1. The comments around BUG-13 and cumulative child dispatch keys still talk in the old flush-based observability vocabulary and should be cleaned up with the removed constants. Relevant lines: `rlm_adk/state.py:95-108`.
