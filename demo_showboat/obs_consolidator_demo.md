# Phases 2+3: ObservabilityPlugin Enhancement + DebugLoggingPlugin Removal

*2026-03-05T18:43:19Z by Showboat 0.6.0*
<!-- showboat-id: b7c4affc-0e88-492b-8dc5-478b70e67e99 -->

## Phase 2: ObservabilityPlugin Enhancement

Enhanced after_run_callback with new summary fields: dispatch latency stats (min/max/mean), batch_dispatches count, answer_len, total_llm_calls from LAST_REPL_RESULT, and artifact stats. Added verbose flag that prints summary to stdout with [RLM] prefix (replaces DebugLoggingPlugin). Added CONTEXT_WINDOW_SNAPSHOT to ephemeral fixed keys and obs:child_summary@ to dynamic prefix scan for re-persist.

## Phase 3: DebugLoggingPlugin Removal

Deleted debug_logging.py (522 lines). Removed DebugLoggingPlugin from plugins/__init__.py, agent.py, and all test files. Removed debug parameter from _default_plugins(), create_rlm_app(), and create_rlm_runner(). Deleted 7 deprecated state.py constants that only existed for debug_logging.py import compatibility.

```bash
echo '--- Phase 2: ObservabilityPlugin verbose flag + new summary fields ---' && grep -n 'verbose' /home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py
```

```output
--- Phase 2: ObservabilityPlugin verbose flag + new summary fields ---
59:    def __init__(self, *, name: str = "observability", verbose: bool = False):
61:        self._verbose = verbose
384:            if self._verbose:
```

```bash
echo '--- Phase 2: Ephemeral re-persist additions ---' && grep -n 'CONTEXT_WINDOW_SNAPSHOT\|obs:child_summary@' /home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py | head -5
```

```output
--- Phase 2: Ephemeral re-persist additions ---
22:    CONTEXT_WINDOW_SNAPSHOT,
93:        CONTEXT_WINDOW_SNAPSHOT,
100:        "obs:child_summary@",
212:            context_snapshot = state.get(CONTEXT_WINDOW_SNAPSHOT)
```

```bash
echo '--- Phase 3: DebugLoggingPlugin deleted ---' && ls /home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py 2>&1 || true && echo '--- plugins/__init__.py has no DebugLoggingPlugin ---' && grep -c DebugLogging /home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py || echo 'count=0 (removed)'
```

```output
--- Phase 3: DebugLoggingPlugin deleted ---
ls: cannot access '/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py': No such file or directory
--- plugins/__init__.py has no DebugLoggingPlugin ---
0
count=0 (removed)
```

```bash
echo '--- Phase 3: debug param removed from _default_plugins ---' && grep -A2 'def _default_plugins' /home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py
```

```output
--- Phase 3: debug param removed from _default_plugins ---
def _default_plugins(
    *,
    langfuse: bool = False,
```

```bash
echo '--- Phase 3: Deprecated constants removed from state.py ---' && grep -c 'WORKER_PROMPT_CHARS\|WORKER_CONTENT_COUNT\|WORKER_INPUT_TOKENS\|WORKER_OUTPUT_TOKENS\|WORKER_DISPATCH_COUNT\|OBS_WORKER_DISPATCH_LATENCY_MS\|OBS_WORKER_TOTAL_DISPATCHES' /home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py || echo 'count=0 (all removed)'
```

```output
--- Phase 3: Deprecated constants removed from state.py ---
0
count=0 (all removed)
```

```bash
echo '--- All 10 consolidation tests pass ---' && .venv/bin/python -m pytest tests_rlm_adk/test_obs_consolidation.py -v 2>&1 | grep -E 'PASSED|FAILED|passed|failed'
```

```output
--- All 10 consolidation tests pass ---
tests_rlm_adk/test_obs_consolidation.py::TestObsAfterRunDispatchLatency::test_after_run_logs_dispatch_latency PASSED [ 10%]
tests_rlm_adk/test_obs_consolidation.py::TestObsAfterRunBatchDispatches::test_after_run_logs_batch_dispatches PASSED [ 20%]
tests_rlm_adk/test_obs_consolidation.py::TestObsAfterRunAnswerLen::test_after_run_logs_answer_len PASSED [ 30%]
tests_rlm_adk/test_obs_consolidation.py::TestObsAfterRunArtifactStats::test_after_run_logs_artifact_stats PASSED [ 40%]
tests_rlm_adk/test_obs_consolidation.py::TestObsChildSummaryRePersist::test_child_summary_prefix_in_ephemeral_repersist PASSED [ 50%]
tests_rlm_adk/test_obs_consolidation.py::TestObsContextWindowRePersist::test_context_window_snapshot_repersisted PASSED [ 60%]
tests_rlm_adk/test_obs_consolidation.py::TestObsVerboseFlag::test_verbose_prints_to_stdout PASSED [ 70%]
tests_rlm_adk/test_obs_consolidation.py::TestDebugLoggingPluginRemoved::test_debug_logging_plugin_not_importable PASSED [ 80%]
tests_rlm_adk/test_obs_consolidation.py::TestDebugLoggingPluginRemoved::test_debug_logging_not_in_plugin_exports PASSED [ 90%]
tests_rlm_adk/test_obs_consolidation.py::TestDefaultPluginsNoDebugParam::test_default_plugins_no_debug_param PASSED [100%]
======================== 10 passed, 1 warning in 0.05s =========================
```

```bash
echo '--- Full test suite: 814 passed, 0 failed ---' && .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -3
```

```output
--- Full test suite: 814 passed, 0 failed ---

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
814 passed, 1 skipped, 1064 warnings in 143.46s (0:02:23)
```
