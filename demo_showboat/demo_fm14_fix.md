# FM-14 Fix: Generic Exception Handler flush_fn + LAST_REPL_RESULT

*2026-03-02T14:17:32Z by Showboat 0.6.0*
<!-- showboat-id: 00ca613e-7eb3-46fe-933d-346213cf3fe2 -->

FM-14 (FMEA RPN=96) identified that the generic `except Exception` handler in `REPLTool.run_async()` did NOT call `flush_fn()` or write `LAST_REPL_RESULT` to `tool_context.state`. When REPL code raises a non-CancelledError exception after dispatching workers, the dispatch accumulators are never flushed — causing accumulator drift in subsequent iterations. The CancelledError handler (FM-13) already had the correct pattern; FM-14 mirrors it for the generic Exception path.

```bash
grep -n "except Exception\|flush_fn\|LAST_REPL_RESULT\|has_errors\|cancelled" rlm_adk/tools/repl_tool.py
```

```output
10:- Flushes dispatch accumulators into ToolContext.state when a flush_fn is provided
25:from rlm_adk.state import ITERATION_COUNT, LAST_REPL_RESULT, WORKER_DISPATCH_COUNT
44:        flush_fn: Optional[Callable[[], dict]] = None,
58:        self._flush_fn = flush_fn
124:            if self._flush_fn is not None:
125:                acc = self._flush_fn()
129:            # Write LAST_REPL_RESULT even on cancellation for observability
130:            tool_context.state[LAST_REPL_RESULT] = {
132:                "has_errors": True,
135:                "cancelled": True,
144:        except Exception as exc:
148:            if self._flush_fn is not None:
149:                acc = self._flush_fn()
153:            # Write LAST_REPL_RESULT even on exception for observability
154:            tool_context.state[LAST_REPL_RESULT] = {
156:                "has_errors": True,
170:        if self._flush_fn is not None:
171:            acc = self._flush_fn()
176:        # Write LAST_REPL_RESULT summary for observability plugins
179:            "has_errors": bool(result.stderr),
185:        tool_context.state[LAST_REPL_RESULT] = last_repl
```

The fix mirrors the CancelledError handler (FM-13, lines 120-143) into the generic Exception handler (FM-14, lines 144-166). Both now: (1) call `flush_fn()` to snapshot and reset dispatch accumulators, (2) write accumulator values into `tool_context.state`, and (3) write a `LAST_REPL_RESULT` dict with `has_errors=True` for observability plugins. The only difference is the CancelledError variant includes `"cancelled": True`.

```bash
sed -n "120,166p" rlm_adk/tools/repl_tool.py
```

```output
        except asyncio.CancelledError as exc:
            # FM-13 fix: flush accumulators before returning so dispatch
            # counts from this iteration are not lost (accumulator drift).
            total_llm_calls = 0
            if self._flush_fn is not None:
                acc = self._flush_fn()
                for k, v in acc.items():
                    tool_context.state[k] = v
                total_llm_calls = acc.get(WORKER_DISPATCH_COUNT, 0)
            # Write LAST_REPL_RESULT even on cancellation for observability
            tool_context.state[LAST_REPL_RESULT] = {
                "code_blocks": 1,
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": total_llm_calls,
                "cancelled": True,
            }
            return {
                "stdout": "",
                "stderr": f"CancelledError: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }
        except Exception as exc:
            # FM-14 fix: flush accumulators before returning so dispatch
            # counts from this iteration are not lost (accumulator drift).
            total_llm_calls = 0
            if self._flush_fn is not None:
                acc = self._flush_fn()
                for k, v in acc.items():
                    tool_context.state[k] = v
                total_llm_calls = acc.get(WORKER_DISPATCH_COUNT, 0)
            # Write LAST_REPL_RESULT even on exception for observability
            tool_context.state[LAST_REPL_RESULT] = {
                "code_blocks": 1,
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": total_llm_calls,
            }
            return {
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplExceptionFlushFn -v 2>&1 | sed "s/ in [0-9.]*s//"
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests_rlm_adk/test_fmea_e2e.py::TestReplExceptionFlushFn::test_flush_fn_called_on_exception PASSED [ 50%]
tests_rlm_adk/test_fmea_e2e.py::TestReplExceptionFlushFn::test_last_repl_result_written_on_exception PASSED [100%]

============================== 2 passed ===============================
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py -v 2>&1 | tail -5 | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion::test_tool_result_shows_error PASSED [ 96%]
tests_rlm_adk/test_fmea_e2e.py::TestReplExceptionFlushFn::test_flush_fn_called_on_exception PASSED [ 98%]
tests_rlm_adk/test_fmea_e2e.py::TestReplExceptionFlushFn::test_last_repl_result_written_on_exception PASSED [100%]

============================= 63 passed ==============================
```

FM-14 resolved: the generic Exception handler in `REPLTool.run_async()` now calls `flush_fn()` and writes `LAST_REPL_RESULT` to `tool_context.state`, eliminating accumulator drift on non-CancelledError REPL exceptions. Two new tests in `TestReplExceptionFlushFn` (test_flush_fn_called_on_exception, test_last_repl_result_written_on_exception) verify the fix. Full FMEA suite passes (63/63) with no regressions. FM-14 RPN residual risk reduced.
