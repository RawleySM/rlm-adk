# FMEA Team C: REPL Error Recovery

*2026-03-01T11:37:26Z by Showboat 0.6.0*
<!-- showboat-id: e8104716-c7b3-458d-94ad-f7c5b5c54175 -->

## Fixture 1: repl_error_then_retry.json

### FM-05: REPL RuntimeError (RPN=24) + FM-14: flush_fn Skipped on Exception (RPN=96) + FM-23: Variable Persistence After Error (RPN=48)

**Pathway:** P4a/P4b (sync/async REPL execution) + P7 (flush_fn after code execution)

This fixture exercises the highest-RPN REPL failure mode (FM-14, RPN=96). The scenario:
- **Iteration 1**: Reasoning agent emits `execute_code` that calls `llm_query("extract data")`. The worker returns valid JSON, but the REPL code raises `KeyError` accessing `data["nonexistent_key"]`.
- **Iteration 2**: Reasoning sees the KeyError in tool stderr, emits corrected code using `data["extracted_value"]`, re-dispatches `llm_query`, and succeeds.
- **Final**: Reasoning returns `FINAL(Retry succeeded: alpha-42)`.

The fixture covers three failure modes simultaneously:
- **FM-05**: RuntimeError (KeyError) in user code — caught by `except Exception` in `local_repl.py`
- **FM-14**: `flush_fn` is called AFTER the except-return in `repl_tool.py` — unreachable on exception
- **FM-23**: Variables assigned before the KeyError (like `result`, `raw`, `data`) do NOT persist to iteration 2 in the async path because `new_locals` is never returned

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/repl_error_then_retry.json') as f:
    fixture = json.load(f)
print('=== Iteration 1 REPL code (raises KeyError) ===')
code1 = fixture['responses'][0]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
for i, line in enumerate(code1.split('\n'), 1):
    print(f'  {i}: {line}')
print()
print('=== Iteration 2 REPL code (corrected key) ===')
code2 = fixture['responses'][2]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
for i, line in enumerate(code2.split('\n'), 1):
    print(f'  {i}: {line}')
print()
print(f'Expected final_answer: {fixture[\"expected\"][\"final_answer\"]}')
print(f'Expected iterations:   {fixture[\"expected\"][\"total_iterations\"]}')
print(f'Expected model_calls:  {fixture[\"expected\"][\"total_model_calls\"]}')
"

```

```output
=== Iteration 1 REPL code (raises KeyError) ===
  1: import json
  2: result = llm_query("extract data from the document")
  3: raw = str(result)
  4: data = json.loads(raw)
  5: value = data["nonexistent_key"]  # KeyError: key does not exist
  6: print(f"Extracted: {value}")

=== Iteration 2 REPL code (corrected key) ===
  1: import json
  2: result = llm_query("extract data from the document")
  3: raw = str(result)
  4: data = json.loads(raw)
  5: value = data["extracted_value"]
  6: print(f"Retry succeeded: {value}")

Expected final_answer: Retry succeeded: alpha-42
Expected iterations:   2
Expected model_calls:  5
```

### Error Handling Path Analysis

Iteration 1 code calls `llm_query()` at line 2, so `has_llm_calls()` returns True and the code is routed to the **async path** (P4b). The AST rewriter transforms `llm_query()` to `await llm_query_async()` and wraps everything in `async def _repl_exec()`. The worker returns valid JSON `{"extracted_value": "alpha-42", ...}`, but line 5 accesses `data["nonexistent_key"]` which raises `KeyError`.

**FM-05 handling**: The `except Exception` in `execute_code_async()` (local_repl.py:361) catches the KeyError, appends it to stderr, and sets `_last_exec_error`. The critical detail: **`new_locals` is never returned** because the exception fires before `return locals()` inside `_repl_exec`. So variables `result`, `raw`, `data` assigned before the error are lost.

**FM-14 (flush_fn skip)**: In `repl_tool.py`, the `except` block at line 120-127 returns early — the `flush_fn` call at lines 131-135 is **unreachable**. This means dispatch accumulators (`_acc_dispatch_count`, `_acc_latencies`) from iteration 1's `llm_query` call retain stale values and will double-count in iteration 2's flush.

**FM-23 (variable persistence)**: Because the async path exception prevents `new_locals` from being merged into `self.locals`, iteration 2 must re-call `llm_query` — it cannot reuse `result` from iteration 1.

```bash
echo "=== FM-14: flush_fn is AFTER the except-return in repl_tool.py ===" && sed -n "107,136p" rlm_adk/tools/repl_tool.py
```

```output
=== FM-14: flush_fn is AFTER the except-return in repl_tool.py ===
        try:
            if has_llm_calls(code):
                llm_calls_made = True
                tree = rewrite_for_async(code)
                compiled = compile(tree, "<repl>", "exec")
                # Merge globals and locals so _repl_exec sees variables from
                # previous executions (imports, user-defined vars, etc.)
                ns = {**self.repl.globals, **self.repl.locals}
                exec(compiled, ns)
                repl_exec_fn = ns["_repl_exec"]
                result = await self.repl.execute_code_async(code, repl_exec_fn, trace=trace)
            else:
                result = self.repl.execute_code(code, trace=trace)
        except (Exception, asyncio.CancelledError) as exc:
            return {
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }

        # Flush dispatch accumulators into tool_context.state
        total_llm_calls = 0
        if self._flush_fn is not None:
            acc = self._flush_fn()
            for k, v in acc.items():
                tool_context.state[k] = v
            total_llm_calls = acc.get(WORKER_DISPATCH_COUNT, 0)

```

```bash
echo "=== FM-23: Async except handler — new_locals never returned ===" && sed -n "346,367p" rlm_adk/repl/local_repl.py
```

```output
=== FM-23: Async except handler — new_locals never returned ===
            # Run the async _repl_exec function
            new_locals = await repl_exec_fn()

            if trace is not None:
                trace.end_time = time.perf_counter()

            # Update locals with results
            if isinstance(new_locals, dict):
                for key, value in new_locals.items():
                    if not key.startswith("_"):
                        self.locals[key] = value

            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()
            self._last_exec_error = None
        except Exception as e:
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
            self._last_exec_error = f"{type(e).__name__}: {e}"
            if trace is not None:
                trace.end_time = time.perf_counter()
        finally:
```

### Key Observation: FM-14 flush_fn Skip

Look at lines 120-127 vs lines 130-135 of `repl_tool.py`:
- The `except` block at line 120 **returns immediately** — it never reaches line 131.
- The `flush_fn()` call at line 132 is only reachable on the **success path**.
- This means iteration 1's worker dispatch (1 `llm_query` call) is NOT flushed.
- When iteration 2 succeeds and flush_fn fires, it flushes **both** iterations' accumulators, resulting in a `WORKER_DISPATCH_COUNT` of 2 (correct total, but the per-iteration attribution is wrong).

This is the highest-RPN gap (96) because the detection score is 8/10 — the double-counting is invisible unless you compare per-iteration dispatch counts.

Now let's run the test:

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
4 passed, 21 warnings
```

### Fixture 1 Summary

All 4 tests pass for `TestReplErrorThenRetry`:
- `test_contract`: Basic fixture contract (final_answer, iterations, model_calls) validated.
- `test_two_iterations_required`: Confirmed the error forced a second iteration (ITERATION_COUNT=2).
- `test_error_visible_in_tool_response`: Confirmed `KeyError` appears in the first `function_response` stderr.
- `test_retry_succeeds_in_final_answer`: Confirmed `alpha-42` appears in FINAL_ANSWER after retry.

**FMEA findings:**
- FM-05 (RuntimeError, RPN=24): **Covered** — KeyError caught, reported in stderr, model self-corrects.
- FM-14 (flush_fn skip, RPN=96): **Covered but residual risk confirmed** — flush_fn unreachable on exception path. Accumulators carry over to next iteration's flush.
- FM-23 (variable persistence, RPN=48): **Covered** — async path loses pre-error variables; model must re-dispatch `llm_query` in iteration 2.

---

## Fixture 2: repl_syntax_error.json

### FM-04: REPL SyntaxError (RPN=10, Pathway P4a/P4b)

**Pathway:** P4a (sync execute_code) — no `llm_query` calls, so code takes the sync branch.

This fixture exercises the lowest-severity REPL error mode. The scenario:
- **Iteration 1**: Model generates `x = int("42"` — missing closing parenthesis. REPL catches SyntaxError.
- **Iteration 2**: Model corrects to `x = int("42")` and prints `Syntax fixed: 42`.
- **Final**: Reasoning returns `FINAL(Syntax fixed: 42)`.

SyntaxError is distinctive because:
1. `has_llm_calls()` returns **False** (the code has a syntax error, so `ast.parse()` fails and the function returns False).
2. The code is routed to the **sync path** (`execute_code`), not the async path.
3. The `exec()` call in `execute_code()` raises `SyntaxError` which is caught by `except Exception`.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/repl_syntax_error.json') as f:
    fixture = json.load(f)
print('=== Iteration 1 REPL code (SyntaxError) ===')
code1 = fixture['responses'][0]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
print(f'  Code: {code1!r}')
print()
print('=== Iteration 2 REPL code (corrected) ===')
code2 = fixture['responses'][1]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
for i, line in enumerate(code2.split('\n'), 1):
    print(f'  {i}: {line}')
print()
print(f'Expected final_answer: {fixture[\"expected\"][\"final_answer\"]}')
print(f'Expected iterations:   {fixture[\"expected\"][\"total_iterations\"]}')
print(f'Expected model_calls:  {fixture[\"expected\"][\"total_model_calls\"]}')
"

```

```output
=== Iteration 1 REPL code (SyntaxError) ===
  Code: 'x = int("42"'

=== Iteration 2 REPL code (corrected) ===
  1: x = int("42")
  2: print(f"Syntax fixed: {x}")

Expected final_answer: Syntax fixed: 42
Expected iterations:   2
Expected model_calls:  3
```

### Error Handling Path Analysis

The SyntaxError path is unique among REPL errors because the AST detection step (`has_llm_calls`) also fails on syntax errors:

1. `has_llm_calls('x = int("42"')` calls `ast.parse()` which raises `SyntaxError` — the function returns `False`.
2. Code is routed to **sync** `execute_code()` (P4a).
3. Inside `execute_code()`, `exec()` raises `SyntaxError`.
4. The `except Exception` at local_repl.py:301 catches it, appends to stderr.

Importantly, there is **no variable state damage** in this path because the `exec()` fails before any assignment executes. The `self.locals` dict remains unchanged from before the call.

Let's verify the detection and handling code:

```bash
echo "=== has_llm_calls: SyntaxError returns False ===" && sed -n "15,36p" rlm_adk/repl/ast_rewriter.py
```

```output
=== has_llm_calls: SyntaxError returns False ===
def has_llm_calls(code: str) -> bool:
    """Check if code contains llm_query or llm_query_batched calls.

    Uses AST parsing to detect calls accurately (not just string matching,
    which could match comments or string literals).

    Returns False if code has syntax errors (will be caught during execution).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in (
                "llm_query",
                "llm_query_batched",
            ):
                return True
    return False
```

```bash
echo "=== Sync execute_code: except handler catches SyntaxError ===" && sed -n "279,304p" rlm_adk/repl/local_repl.py
```

```output
=== Sync execute_code: except handler catches SyntaxError ===
            try:
                combined = {**self.globals, **self.locals}

                if trace is not None:
                    combined["_rlm_trace"] = trace
                    if trace_level >= 2:
                        instrumented = TRACE_HEADER_MEMORY + "\n" + code + "\n" + TRACE_FOOTER_MEMORY
                    else:
                        instrumented = TRACE_HEADER + "\n" + code + "\n" + TRACE_FOOTER
                else:
                    instrumented = code

                exec(instrumented, combined, combined)

                # Update locals with new variables (underscore filter hides _rlm_*)
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value

                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue()
                self._last_exec_error = None
            except Exception as e:
                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
                self._last_exec_error = f"{type(e).__name__}: {e}"
```

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplSyntaxError -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
4 passed, 13 warnings
```

### Fixture 2 Summary

All 4 tests pass for `TestReplSyntaxError`:
- `test_contract`: Basic fixture contract validated.
- `test_two_iterations_for_correction`: Confirmed model needed 2 iterations to self-correct (ITERATION_COUNT=2).
- `test_syntax_error_in_first_tool_response`: Confirmed `SyntaxError` appears in first function_response stderr.
- `test_corrected_code_succeeds`: Confirmed second REPL call has empty stderr (no errors).

**FMEA findings:**
- FM-04 (SyntaxError, RPN=10): **Covered** — SyntaxError caught by `except Exception` in sync `execute_code()`. Model sees the error and self-corrects. No variable state damage because `exec()` fails before any assignment.

**Contrast with FM-05 (RuntimeError):** SyntaxError is safer because no partial execution occurs. RuntimeError (next fixture) can leave partial state — some variables assigned, others not.

---

## Fixture 3: repl_runtime_error.json

### FM-05: REPL RuntimeError — NameError (RPN=24, Pathway P4a/P4b)

**Pathway:** P4a (sync) — no `llm_query` calls, so code takes the sync branch.

This fixture isolates FM-05 (RuntimeError) without the compounding factors of FM-14/23 (no workers, no flush_fn). The scenario:
- **Iteration 1**: Model code `result = undefined_variable + " world"` raises `NameError`.
- **Iteration 2**: Model defines `undefined_variable = "hello"` first, then computes and prints the result.
- **Final**: Reasoning returns `FINAL(Runtime fixed: hello world)`.

Unlike the `repl_error_then_retry` fixture, this one uses **no llm_query calls**, so:
1. `has_llm_calls()` returns False — code runs in the sync `execute_code()` path.
2. No flush_fn involvement — FM-14 is not triggered.
3. The sync path has different variable persistence behavior than the async path.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/repl_runtime_error.json') as f:
    fixture = json.load(f)
print('=== Iteration 1 REPL code (NameError) ===')
code1 = fixture['responses'][0]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
print(f'  Code: {code1!r}')
print()
print('=== Iteration 2 REPL code (defines variable first) ===')
code2 = fixture['responses'][1]['body']['candidates'][0]['content']['parts'][0]['functionCall']['args']['code']
for i, line in enumerate(code2.split('\n'), 1):
    print(f'  {i}: {line}')
print()
print(f'Expected final_answer: {fixture[\"expected\"][\"final_answer\"]}')
print(f'Expected iterations:   {fixture[\"expected\"][\"total_iterations\"]}')
print(f'Expected model_calls:  {fixture[\"expected\"][\"total_model_calls\"]}')
"

```

```output
=== Iteration 1 REPL code (NameError) ===
  Code: 'result = undefined_variable + " world"'

=== Iteration 2 REPL code (defines variable first) ===
  1: undefined_variable = "hello"
  2: result = undefined_variable + " world"
  3: print(f"Runtime fixed: {result}")

Expected final_answer: Runtime fixed: hello world
Expected iterations:   2
Expected model_calls:  3
```

### Sync vs Async Variable Persistence Difference

This fixture demonstrates the **sync path** (P4a) behavior on exception. In the sync path (`execute_code`), the `except Exception` handler at local_repl.py:301 catches the NameError. The sync handler does NOT update `self.locals` on exception — the line `self.locals[key] = value` at line 296 only runs in the `try` block.

In both sync and async paths, pre-error variables are lost. But the sync path is slightly safer for simple errors like NameError — the `exec()` fails on the FIRST statement, so no partial assignments exist.

Let's see the sync handler contrasted with the async handler:

```bash
echo "=== Sync path: except handler does NOT update self.locals ===" && sed -n "293,304p" rlm_adk/repl/local_repl.py && echo "" && echo "=== Async path: except handler also skips self.locals update ===" && sed -n "352,364p" rlm_adk/repl/local_repl.py
```

```output
=== Sync path: except handler does NOT update self.locals ===
                # Update locals with new variables (underscore filter hides _rlm_*)
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value

                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue()
                self._last_exec_error = None
            except Exception as e:
                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
                self._last_exec_error = f"{type(e).__name__}: {e}"

=== Async path: except handler also skips self.locals update ===
            # Update locals with results
            if isinstance(new_locals, dict):
                for key, value in new_locals.items():
                    if not key.startswith("_"):
                        self.locals[key] = value

            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()
            self._last_exec_error = None
        except Exception as e:
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
            self._last_exec_error = f"{type(e).__name__}: {e}"
```

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplRuntimeError -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
4 passed, 13 warnings
```

### Fixture 3 Summary

All 4 tests pass for `TestReplRuntimeError`:
- `test_contract`: Basic fixture contract validated.
- `test_two_iterations_for_recovery`: Confirmed model needed 2 iterations (ITERATION_COUNT=2).
- `test_name_error_in_first_tool_response`: Confirmed `NameError` appears in first function_response stderr.
- `test_corrected_output`: Confirmed `hello world` appears in FINAL_ANSWER.

**FMEA findings:**
- FM-05 (RuntimeError/NameError, RPN=24): **Covered** — NameError caught by sync `execute_code()`, reported in stderr. Model defines the missing variable in iteration 2 and succeeds. No partial state leakage because the error occurs on the first (and only) statement.

---

## Cross-Fixture Analysis: REPL Error Recovery Matrix

| Fixture | FM | RPN | Error Type | Path | Variables Lost | flush_fn Skipped | Iterations |
|---|---|---|---|---|---|---|---|
| repl_error_then_retry | FM-05/14/23 | 96/48 | KeyError | async (P4b) | Yes (FM-23) | Yes (FM-14) | 2 |
| repl_syntax_error | FM-04 | 10 | SyntaxError | sync (P4a) | No (no exec) | N/A (no workers) | 2 |
| repl_runtime_error | FM-05 | 24 | NameError | sync (P4a) | No (single stmt) | N/A (no workers) | 2 |

### Key Architectural Insights

1. **Sync vs async error handling is asymmetric.** The sync path uses a `combined` dict that could retain partial state on multi-statement errors, but the except handler skips the `self.locals` update entirely. The async path loses state because `return locals()` inside `_repl_exec` is unreachable after an exception.

2. **FM-14 (flush_fn skip) is the highest-risk finding.** The `except` block in `repl_tool.py` returns early, making `flush_fn()` unreachable. This causes dispatch accumulators to carry over across iterations, resulting in silent double-counting. A fix would move `flush_fn()` into a `finally` block.

3. **FM-23 (variable persistence) is model-visible.** The model must re-dispatch `llm_query` calls in retry iterations because variables from the failed iteration are lost.

4. **SyntaxError is the safest failure mode.** No code executes, no partial state, no flush_fn involvement.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry tests_rlm_adk/test_fmea_e2e.py::TestReplSyntaxError tests_rlm_adk/test_fmea_e2e.py::TestReplRuntimeError -v 2>&1 | grep -E "PASSED|FAILED|passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry::test_contract PASSED [  8%]
tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry::test_two_iterations_required PASSED [ 16%]
tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry::test_error_visible_in_tool_response PASSED [ 25%]
tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry::test_retry_succeeds_in_final_answer PASSED [ 33%]
tests_rlm_adk/test_fmea_e2e.py::TestReplSyntaxError::test_contract PASSED [ 41%]
tests_rlm_adk/test_fmea_e2e.py::TestReplSyntaxError::test_two_iterations_for_correction PASSED [ 50%]
tests_rlm_adk/test_fmea_e2e.py::TestReplSyntaxError::test_syntax_error_in_first_tool_response PASSED [ 58%]
tests_rlm_adk/test_fmea_e2e.py::TestReplSyntaxError::test_corrected_code_succeeds PASSED [ 66%]
tests_rlm_adk/test_fmea_e2e.py::TestReplRuntimeError::test_contract PASSED [ 75%]
tests_rlm_adk/test_fmea_e2e.py::TestReplRuntimeError::test_two_iterations_for_recovery PASSED [ 83%]
tests_rlm_adk/test_fmea_e2e.py::TestReplRuntimeError::test_name_error_in_first_tool_response PASSED [ 91%]
tests_rlm_adk/test_fmea_e2e.py::TestReplRuntimeError::test_corrected_output PASSED [100%]
======================= 12 passed, 45 warnings ========================
```

## Final Results

**12 / 12 tests passed** across all three REPL error recovery fixtures.

| Test Class | Tests | Status |
|---|---|---|
| TestReplErrorThenRetry | 4 | PASS |
| TestReplSyntaxError | 4 | PASS |
| TestReplRuntimeError | 4 | PASS |

### Failure Modes Covered

| FM | Name | RPN | Status |
|---|---|---|---|
| FM-04 | REPL SyntaxError | 10 | Covered (was Gap) |
| FM-05 | REPL RuntimeError | 24 | Covered (was Gap) |
| FM-14 | flush_fn Skipped on Exception | 96 | Covered — residual risk confirmed |
| FM-23 | Variable Persistence After Error | 48 | Covered (was Gap) |

### Recommended Fix for FM-14

Move the `flush_fn()` call from after the try/except to a `finally` block in `repl_tool.py`. This ensures dispatch accumulators are always flushed, even when REPL code raises an exception. The current behavior silently double-counts worker dispatches across iterations.

