# REPLTrace Wiring into REPLTool

*2026-02-28T14:58:47Z by Showboat 0.6.0*
<!-- showboat-id: cd02ff7b-c5b9-4b22-91bd-906bbcbf2f1c -->

## Bug: REPLTrace was never wired into REPLTool

`RLM_REPL_TRACE=1|2` was a no-op. The orchestrator created `trace_holder = [None]` and passed it to REPLTool, but `run_async()` never created a `REPLTrace` instance or passed it to `execute_code`. Result: `trace_holder[0]` stayed None, dispatch closures skipped trace recording, `LAST_REPL_RESULT` never included `trace_summary`, and `REPLTracingPlugin` saved no artifacts.

## Fix: Three changes in repl_tool.py

```bash
sed -n "24p" rlm_adk/tools/repl_tool.py
```

```output
from rlm_adk.repl.trace import REPLTrace
```

### 1. Create REPLTrace before execution and set trace_holder[0]

```bash
sed -n "95,106p" rlm_adk/tools/repl_tool.py
```

```output
        # Create a REPLTrace when trace_holder is provided so dispatch
        # closures and LocalREPL can record timing/LLM-call data.
        trace: REPLTrace | None = None
        if self.trace_holder is not None:
            trace = REPLTrace()
            # Orchestrator passes [None]; set [0] so dispatch closures see
            # the live trace.  Empty lists (e.g. from tests) get an append.
            if self.trace_holder:
                self.trace_holder[0] = trace
            else:
                self.trace_holder.append(trace)

```

### 2. Pass trace to execute_code and execute_code_async

```bash
grep -n "trace=trace" rlm_adk/tools/repl_tool.py
```

```output
117:                result = await self.repl.execute_code_async(code, repl_exec_fn, trace=trace)
119:                result = self.repl.execute_code(code, trace=trace)
```

### 3. Enrich LAST_REPL_RESULT with trace_summary

```bash
sed -n "137,146p" rlm_adk/tools/repl_tool.py
```

```output
        # Write LAST_REPL_RESULT summary for observability plugins
        last_repl: dict[str, Any] = {
            "code_blocks": 1,
            "has_errors": bool(result.stderr),
            "has_output": bool(result.stdout),
            "total_llm_calls": total_llm_calls,
        }
        if trace is not None:
            last_repl["trace_summary"] = trace.summary()
        tool_context.state[LAST_REPL_RESULT] = last_repl
```

## Test fixes

Fixed key-name mismatches in test_tracing_e2e_demo.py (`total_wall_time_ms` -> `wall_time_ms`, `total_llm_calls_traced` -> `llm_call_count`) and added hard assertions for trace_summary presence in both e2e test files.

```bash
grep -n "wall_time_ms\|llm_call_count" tests_rlm_adk/test_tracing_e2e_demo.py
```

```output
158:                print(f"    trace_summary: wall_time_ms={ts.get('wall_time_ms', '?'):.1f} "
159:                      f"llm_call_count={ts.get('llm_call_count', '?')} "
171:            assert ts["wall_time_ms"] >= 0, (
172:                f"snapshot[{i}] wall_time_ms should be >= 0, got {ts['wall_time_ms']}"
174:            assert ts["llm_call_count"] >= 0, (
175:                f"snapshot[{i}] llm_call_count should be >= 0, got {ts['llm_call_count']}"
```

## Proof: trace_summary is now populated in LAST_REPL_RESULT

Run the tracing e2e demo and extract the LAST_REPL_RESULT section:

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 RLM_REPL_TRACE=1 .venv/bin/python -m tests_rlm_adk.test_tracing_e2e_demo 2>/dev/null | grep -c "has_trace_summary=True" | xargs -I{} echo "Snapshots with trace_summary: {}"
```

```output
Snapshots with trace_summary: 1
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 RLM_REPL_TRACE=1 .venv/bin/python -m tests_rlm_adk.test_tracing_e2e_demo 2>/dev/null | grep -c "repl_traces.json" | xargs -I{} echo "repl_traces.json artifact references: {}"
```

```output
repl_traces.json artifact references: 2
```

## Test verification

### Structured output e2e tests (includes trace_summary assertions)

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 RLM_REPL_TRACE=1 .venv/bin/python -m pytest tests_rlm_adk/test_structured_output_e2e.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
12 passed
```

### Full regression suite

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
557 passed, 1 skipped
```

## Summary

Three changes wire REPLTrace end-to-end:
1. **repl_tool.py**: Create `REPLTrace()`, set `trace_holder[0]`, pass `trace=` to execute methods, write `trace_summary` to `LAST_REPL_RESULT`
2. **test_tracing_e2e_demo.py**: Fix key names (`wall_time_ms`, `llm_call_count`), add hard assertions for trace presence + artifact
3. **test_structured_output_e2e.py**: Assert `trace_summary` present with valid `wall_time_ms` in both happy path and retry tests

Zero regressions. `RLM_REPL_TRACE=1` now produces live trace data all the way through to saved artifacts.
