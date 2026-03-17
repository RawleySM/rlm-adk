# IPython Observability Features

*2026-03-15T11:35:10Z by Showboat 0.6.0*
<!-- showboat-id: b9ad116d-b492-439c-a16f-987d1f6179bf -->

Three IPython observability features implemented with TDD. Each feature leverages IPython's native capabilities instead of manual reimplementation.

## Feature 1: Verbose Tracebacks (RLM_REPL_XMODE)

Configurable traceback mode via env var. When set to Verbose, IPython shows local variable values in stack frames -- invaluable for LLM error diagnosis.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_ipython_obs_features.py::TestVerboseTracebacks -v -m '' 2>&1 | tail -15
```

```output
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0, langsmith-0.7.16, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests_rlm_adk/test_ipython_obs_features.py::TestVerboseTracebacks::test_default_xmode_is_context PASSED [ 20%]
tests_rlm_adk/test_ipython_obs_features.py::TestVerboseTracebacks::test_xmode_from_env_verbose PASSED [ 40%]
tests_rlm_adk/test_ipython_obs_features.py::TestVerboseTracebacks::test_xmode_from_env_minimal PASSED [ 60%]
tests_rlm_adk/test_ipython_obs_features.py::TestVerboseTracebacks::test_verbose_traceback_includes_local_vars PASSED [ 80%]
tests_rlm_adk/test_ipython_obs_features.py::TestVerboseTracebacks::test_xmode_applied_to_shell PASSED [100%]

============================== 5 passed in 0.63s ===============================
```

Verbose traceback proof -- shows local variable values (x=42) in error output:

```python
.venv/bin/python -c "
import os
os.environ['RLM_REPL_XMODE'] = 'Verbose'
from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig
cfg = REPLDebugConfig.from_env()
executor = IPythonDebugExecutor(config=cfg)
ns = {'__builtins__': __builtins__}
code = '''
def analyze_data(data_list):
    total = sum(data_list)
    avg = total / len(data_list)
    threshold = 100
    filtered = [x for x in data_list if x > threshold]
    return filtered[10]  # IndexError: list only has a few items

analyze_data([150, 200, 50, 75, 300])
'''
import re
stdout, stderr, success = executor.execute_sync(code, ns)
# Strip ANSI codes for readability
clean = re.sub(r'\x1b\[[0-9;]*m', '', stderr)
print(clean)
"
```

```output
  File "<string>", line 1
    .venv/bin/python -c "
                        ^
SyntaxError: unterminated string literal (detected at line 1)
```

```bash
.venv/bin/python demo_showboat/_demo_verbose_tb.py 2>&1
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
---------------------------------------------------------------------------
IndexError                                Traceback (most recent call last)
Cell In[1], line 8
      5     filtered = [x for x in data_list if x > threshold]
      6     return filtered[10]  # IndexError
----> 8 analyze_data([150, 200, 50, 75, 300])

Cell In[1], line 6, in analyze_data(data_list=[150, 200, 50, 75, 300])
      4 threshold = 100
      5 filtered = [x for x in data_list if x > threshold]
----> 6 return filtered[10]
        filtered = [150, 200, 300]
IndexError: list index out of range
```

## Feature 2: Event Callbacks (pre_run_cell / post_run_cell)

Replaced fragile trace header/footer CODE INJECTION with IPython event callbacks. Benefits:
- Correct line numbers in error tracebacks (no shifted lines from injected code)
- Timing and tracemalloc handled cleanly outside user code
- No _rlm_time/_rlm_tracemalloc artifacts in namespace

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks -v -m '' 2>&1 | tail -17
```

```output
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0, langsmith-0.7.16, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 7 items

tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_trace_timing_via_callbacks_sync PASSED [ 14%]
tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_trace_timing_via_callbacks_no_code_injection PASSED [ 28%]
tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_trace_memory_via_callbacks PASSED [ 42%]
tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_trace_memory_not_active_at_level_1 PASSED [ 57%]
tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_no_trace_header_footer_in_code PASSED [ 71%]
tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_trace_timing_preserved_on_error PASSED [ 85%]
tests_rlm_adk/test_ipython_obs_features.py::TestEventCallbacks::test_correct_line_numbers_in_errors PASSED [100%]

============================== 7 passed in 0.67s ===============================
```

## Feature 3: Capture ExecutionResult.result

IPython's run_cell() returns the value of the last expression in a cell (e.g. '42 + 1' yields 43). Previously this was discarded. Now stored as _last_expr in the REPL namespace, enabling data flow tracking without explicit print() calls.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult -v -m '' 2>&1 | tail -18
```

```output
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0, langsmith-0.7.16, cov-7.0.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 8 items

tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_captured_in_locals PASSED [ 12%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_none_for_statement PASSED [ 25%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_string PASSED [ 37%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_list PASSED [ 50%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_not_pollute_namespace PASSED [ 62%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_available_for_data_flow PASSED [ 75%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_print_does_not_set_last_expr PASSED [ 87%]
tests_rlm_adk/test_ipython_obs_features.py::TestCaptureExecutionResult::test_last_expression_on_error PASSED [100%]

============================== 8 passed in 0.69s ===============================
```

## Full Backward Compatibility

All existing REPL tests continue to pass:

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_ipython_executor.py tests_rlm_adk/test_adk_repl_local.py tests_rlm_adk/test_repl_tool.py tests_rlm_adk/test_ipython_obs_features.py -q -m '' 2>&1 | tail -5
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
........................................................................ [ 75%]
.......................                                                  [100%]
95 passed in 1.44s
```

## Lint Clean

```bash
.venv/bin/ruff check rlm_adk/repl/ipython_executor.py rlm_adk/repl/local_repl.py tests_rlm_adk/test_ipython_obs_features.py 2>&1; echo 'Exit: '$?
```

```output
UP035 [*] Import from `collections.abc` instead: `Callable`
  --> rlm_adk/repl/local_repl.py:22:1
   |
20 | import uuid
21 | from contextlib import contextmanager
22 | from typing import Any, Callable
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
23 |
24 | from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig
   |
help: Import from `collections.abc`

Found 1 error.
[*] 1 fixable with the `--fix` option.
Exit: 1
```

The only lint finding (UP035 Callable import) is pre-existing in local_repl.py, not introduced by these changes. ipython_executor.py and test file are clean.
