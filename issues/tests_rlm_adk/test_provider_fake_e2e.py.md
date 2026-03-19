# `tests_rlm_adk/test_provider_fake_e2e.py`

## Findings
1. Medium: the tracing assertions still prove the old state-derived aggregate path (`traces.total_calls`, `total_input_tokens`, `total_output_tokens`) instead of the new lineage-plane columns. That means the refactor’s main SQLite contract can regress while these tests stay green. Relevant lines: `tests_rlm_adk/test_provider_fake_e2e.py:260-291`, `tests_rlm_adk/test_provider_fake_e2e.py:342-373`.

## Legacy / dead code
1. The file still carries several “observability state” comments that describe the old architecture more than the refactored lineage plane. The most obvious block is `tests_rlm_adk/test_provider_fake_e2e.py:262-267`.
