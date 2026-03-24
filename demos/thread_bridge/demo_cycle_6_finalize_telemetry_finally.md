# Demo: [Cycle 6] `_finalize_telemetry` Fires in All Code Paths

## TDD Cycle Reference
- Cycle: 6
- Tests: `test_thread_bridge.py::TestREPLToolThreadBridge::test_finalize_telemetry_called_on_success`, `test_finalize_telemetry_called_on_exception`, `test_finalize_telemetry_called_on_cancel`
- Assertion: `_finalize_telemetry()` is called in a `finally` block so it fires on success, exception, AND cancellation -- preventing orphaned telemetry rows.

## What This Proves
When `REPLTool.run_async()` crashes or is cancelled mid-execution, telemetry is still finalized. Without the `finally` block, an exception between tool start and tool end would leave an open telemetry row with no completion timestamp, no stdout, and no error classification.

## Reward-Hacking Risk
A test could:
- Mock `_finalize_telemetry` and assert `mock.called` -- this proves the test setup calls it, not that the production code has it in a `finally`
- Only test the success path (where `_finalize_telemetry` was already called before the refactor)
- Patch the exception to not actually raise, making the "exception path" test trivially pass

The demo guards against this by directly inspecting the source code structure to confirm the `finally` block, then proving via an actual exception that telemetry is finalized.

## Prerequisites
- `REPLTool` with `use_thread_bridge` parameter and `_finalize_telemetry` in `finally`
- `.venv` activated

## Demo Steps

### Step 1: Verify the `finally` block exists in source
```bash
.venv/bin/python3 -c "
import inspect
from rlm_adk.tools.repl_tool import REPLTool

source = inspect.getsource(REPLTool.run_async)
lines = source.split('\n')

# Find the finally block and what it contains
in_finally = False
finally_contents = []
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('finally:'):
        in_finally = True
        finally_contents.append(f'  line {i}: {stripped}')
        continue
    if in_finally:
        if stripped and not stripped.startswith('#'):
            finally_contents.append(f'  line {i}: {stripped}')
        if 'finalize' in stripped.lower() or 'telemetry' in stripped.lower():
            break

if finally_contents:
    print('FOUND: finally block in REPLTool.run_async():')
    for line in finally_contents:
        print(line)
else:
    print('FAIL: No finally block found in REPLTool.run_async()')
"
```
**Expected output**: Shows a `finally:` block containing `_finalize_telemetry` or equivalent telemetry finalization call.

**What this proves**: The source code actually has the `finally` block -- not just a test that mocks it.

### Step 2: Run the automated tests for all three paths
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestREPLToolThreadBridge -k "finalize" -x -v 2>&1 | tail -10
```
**Expected output**: All three `finalize_telemetry` tests PASSED (success, exception, cancel)

**What this proves**: The test suite covers all three code paths, and the `finally` block fires in each.

## Verification Checklist
- [ ] Source inspection shows `finally:` block with telemetry finalization
- [ ] Success path test passes
- [ ] Exception path test passes
- [ ] Cancellation path test passes
- [ ] This could NOT pass if `_finalize_telemetry` were in the `try` block (it would be skipped on exception) or in the `except` block (it would be skipped on cancellation)
