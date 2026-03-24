# E2E Test Consolidated Implementation Plan

**Date**: 2026-03-24
**Status**: Ready for implementation
**Target**: Post-thread-bridge codebase (after all TDD cycles in `thread_bridge_plan_B_TDD.md`)

---

## Source Documents

This plan resolves conflicts and integration gaps across 4 design documents.
Each remains the authoritative reference for its domain — this doc is the
integration layer.

| # | Document | Domain | Lines |
|---|----------|--------|-------|
| 1 | `test_skill_design.md` | test_skill.py module + fixture JSON | 739 |
| 2 | `instrumented_runner_design.md` | InstrumentationPlugin + runner function | 1023 |
| 3 | `dynamic_instruction_design.md` | User context injection + dynamic instruction | 578 |
| 4 | `assertion_framework_design.md` | StdoutParser + ExpectedLineage + assertions | 2062 |

---

## Files to Create/Modify (Canonical List)

### Create (6 files)

| File | Source Doc | Purpose |
|------|-----------|---------|
| `rlm_adk/skills/test_skill.py` | Doc 1 | Source-expandable REPL skill for architecture introspection |
| `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` | Doc 1 + Doc 3 (MERGED) | Provider-fake fixture with `initial_state` |
| `tests_rlm_adk/provider_fake/instrumented_runner.py` | Doc 2 + Doc 3 (MERGED) | `InstrumentationPlugin` + `run_fixture_contract_instrumented()` |
| `tests_rlm_adk/provider_fake/stdout_parser.py` | Doc 4 | `StdoutParser`, `ParsedLog`, `parse_stdout()` |
| `tests_rlm_adk/provider_fake/expected_lineage.py` | Doc 4 (AMENDED) | `ExpectedLineage`, `build_skill_arch_test_lineage()` |
| `tests_rlm_adk/test_skill_arch_e2e.py` | All 4 docs | Test module wiring everything together |

### Modify (1 file)

| File | Change | Source Doc |
|------|--------|-----------|
| `rlm_adk/state.py` | Extend `EXPOSED_STATE_KEYS` (optional) | Docs 1 + 3 |

---

## Conflict Resolutions

### Resolution A — `iteration_count` value at first model call

**Conflict**: Doc 2 says `iteration_count=0` at first `before_model_callback`. Doc 4 asserts `iteration_count=1`.

**Source of truth**: `orchestrator.py:370` yields `iteration_count: 0` in initial state. `repl_tool.py:140-142` increments `_call_count` then writes it **at the start of `run_async()`**, before code executes.

**Resolution**:
- At `before_model_callback` (call 0): `iteration_count = 0`
- Inside REPL execution (test_skill runs): `iteration_count = 1` (REPLTool incremented it)
- At `before_model_callback` (call 2, after execute_code): `iteration_count = 1`

**Fix in Doc 4** (`expected_lineage.py`):
```python
# STATE expectations — model_call_1 phase
StateKeyExpectation(phase="model_call_1", key="iteration_count",
    operator="eq", expected="0",  # NOT "1" — before first execute_code
    source_hint="orchestrator.py:370 — initial state yields iteration_count=0")

# TEST_SKILL expectations — inside REPL
TestSkillExpectation(key="iteration_count",
    operator="eq", expected="1",  # REPLTool incremented before code runs
    source_hint="repl_tool.py:140-142 — _call_count incremented at start of run_async()")
```

### Resolution B — Fixture JSON merge (Doc 1 + Doc 3)

**Conflict**: Doc 1 has no `initial_state`. Doc 3 adds it. Doc 3 also extends REPL code.

**Resolution**: Use Doc 1's fixture structure as the base. Merge in:
1. Doc 3's `initial_state` block (5 keys: `user_provided_ctx`, `repo_url`, `root_prompt`, `test_context`, `skill_instruction`)
2. Doc 3's `expected_state` block (operator-based assertions)
3. Doc 3's extended REPL code (add `user_ctx` access + `[DYN_INSTR:...]` prints after the `run_test_skill()` call)

The merged `responses[0]` REPL code becomes:
```python
from rlm_repl_skills.test_skill import run_test_skill

result = run_test_skill(
    child_prompt='Reply with exactly: arch_test_ok',
    emit_debug=True,
)
print(f'result={result!r}')

# Dynamic instruction verification (from Doc 3)
if 'user_ctx' in dir():
    print(f'[DYN_INSTR:user_ctx_keys={sorted(user_ctx.keys())}]')
    print(f'[DYN_INSTR:arch_context_preview={user_ctx.get("arch_context.txt", "")[:40]}]')
```

### Resolution C — `DYN_INSTR` expectation key format

**Conflict**: Doc 3 emits `[DYN_INSTR:repo_url=resolved=True]`. Doc 4's regex captures group(1)=`repo_url`, group(2)=`resolved=True`. But Doc 4's `ExpectedLineage` uses key `"repo_url=resolved=True"` which won't match the parsed key `"repo_url"`.

**Resolution**: Fix the `DynInstrExpectation` keys in `expected_lineage.py` to match parsed output:
```python
# WRONG (Doc 4 original):
DynInstrExpectation(key="repo_url=resolved=True", operator="eq", expected="True")

# CORRECT:
DynInstrExpectation(key="repo_url", operator="contains", expected="resolved=True",
    source_hint="dynamic_instruction_design.md — dyn_instr_capture_hook emits key=resolved=bool")
```

Apply same fix for all 5 `DYN_INSTR` expectations (`repo_url`, `root_prompt`, `test_context`, `skill_instruction`, `user_ctx_manifest`).

### Resolution D — `REPL_TRACE` tag emission

**Conflict**: Doc 4 expects `[REPL_TRACE:key=value]` lines from `REPLTracingPlugin`. No plugin currently emits these.

**Resolution**: Set ALL `ReplTraceExpectation.required = False`. The `REPL_TRACE` assertion group becomes informational (passes with warnings if absent, validates if present). The `REPLTracingPlugin` modification to emit tagged lines is OUT OF SCOPE for the initial implementation.

### Resolution E — Stdout capture thread safety

**Conflict**: Doc 2 uses `contextlib.redirect_stdout(io.StringIO())` which replaces `sys.stdout` process-globally. Post-thread-bridge, REPL code (including test_skill's `print()` calls) runs in a worker thread via `run_in_executor`.

**Resolution**: `LocalREPL._execute_code_threadsafe` already uses `ContextVar`-based stdout capture (lines 127-128 of the Plan B spec). The worker thread's `print()` output lands in the `ContextVar` buffer, which is merged into the `REPLResult.stdout` field. The runner's `redirect_stdout` captures the **plugin/callback** print() calls (which run in the event loop thread). Both outputs are available:
- `repl_stdout`: from `REPLResult.stdout` (worker thread output, via ContextVar)
- `instrumentation_log`: from `redirect_stdout` capture (event loop thread output, from plugin/callback prints)

The runner must concatenate both for `parse_stdout()`:
```python
combined_stdout = result.repl_stdout + "\n" + result.instrumentation_log
log = parse_stdout(combined_stdout)
```

---

## `dyn_instr_capture_hook` Wiring (Gap 1 from Conflict Analysis)

Doc 3's `make_dyn_instr_capture_hook()` must be wired into the instrumented runner.
Add to `instrumented_runner.py` inside `_wire_instrumentation_hooks()`:

```python
# After wiring local model callback on reasoning_agent:
from proposals... import make_dyn_instr_capture_hook  # actual location TBD

# Chain dyn_instr hook AFTER the local instrumentation hook
_existing_model_cb = reasoning_agent.before_model_callback
_dyn_hook = make_dyn_instr_capture_hook()

def _chained_before_model(callback_context, llm_request):
    # 1. Instrumentation hook (writes to log_lines)
    if _existing_model_cb:
        result = _existing_model_cb(callback_context, llm_request)
        if result is not None:
            return result
    # 2. Dynamic instruction capture hook (writes to state + prints DYN_INSTR tags)
    return _dyn_hook(callback_context, llm_request)

object.__setattr__(reasoning_agent, "before_model_callback", _chained_before_model)
```

---

## Future-Focused Corrections (Post-Thread-Bridge)

These corrections apply to Docs 2 and 4 during implementation:

### Doc 2 corrections:
| Line(s) | Change |
|---------|--------|
| 620 | `[TEST_SKILL:execution_mode=async_rewrite]` → `thread_bridge` |
| 634 | `mode=async_rewrite` → `mode=thread_bridge` in summary |
| 745-747 | Remove "current AST-rewriter path" note; document ContextVar-based capture as the active mechanism |

### Doc 4 corrections:
| Line(s) | Change |
|---------|--------|
| 37 | `[REPL_TRACE:execution_mode=async_rewrite]` → `thread_bridge` |
| 53-54 | Update `has_repl_exec_in_globals` description: `False` is the DEFAULT (thread-bridge), `True` is fallback |
| 658 | Change `expected=["async_rewrite", "thread_bridge"]` → `expected="thread_bridge"` (strict) |
| 840 | Update source_hint to reference thread_bridge as default |
| 1843 | Update reward-hacking table to describe inverted detection |

---

## Debug Instrumentation Layer

The runner activates three env vars for richer diagnostics:

```python
os.environ["RLM_REPL_TRACE"] = "2"          # Full tracing: timing + var snapshots + tracemalloc
os.environ["RLM_REPL_XMODE"] = "Verbose"    # IPython local vars in tracebacks on error
os.environ["RLM_REPL_DEBUG"] = "1"           # Debug mode flag on IPythonDebugExecutor
```

These are set/restored via `_set_debug_instrumentation_env()` / `_restore_debug_instrumentation_env()` in the runner (Doc 4, Section 7).

---

## Test Module Wiring (`test_skill_arch_e2e.py`)

No doc specifies the complete test module. Here is the canonical structure:

```python
"""E2E test: Architecture introspection skill via thread bridge.

Exercises: skill expansion + thread-bridge child dispatch + dynamic instruction
resolution + full observability pipeline.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# Side-effect: populates SkillRegistry for source expansion
import rlm_adk.skills.test_skill  # noqa: F401

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.instrumented_runner import (
    run_fixture_contract_instrumented,
)
from tests_rlm_adk.provider_fake.stdout_parser import parse_stdout
from tests_rlm_adk.provider_fake.expected_lineage import (
    build_skill_arch_test_lineage,
    run_all_assertions,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "skill_arch_test.json"


@pytest.fixture
async def run_result(tmp_path: Path):
    """Run the fixture once, reuse across all tests in this module."""
    return await run_fixture_contract_instrumented(
        FIXTURE_PATH,
        traces_db_path=str(tmp_path / "traces.db"),
        tmpdir=str(tmp_path),
    )


class TestContractPasses:
    async def test_contract_passes(self, run_result):
        assert run_result.contract.passed, run_result.contract.diagnostics()


class TestArchitectureLineage:
    async def test_full_lineage(self, run_result):
        combined = run_result.repl_stdout + "\n" + run_result.instrumentation_log
        log = parse_stdout(combined)
        lineage = build_skill_arch_test_lineage()
        report = run_all_assertions(log, lineage)
        if not report.passed:
            # Attach stderr for Verbose xmode traceback context
            extra = ""
            if hasattr(run_result, "repl_stderr") and run_result.repl_stderr:
                extra = f"\n\n--- REPL stderr (Verbose xmode) ---\n{run_result.repl_stderr}"
            pytest.fail(report.format_report() + extra)


class TestDynamicInstruction:
    async def test_no_unresolved_placeholders(self, run_result):
        si = run_result.final_state.get("_captured_system_instruction_0", "")
        assert si, "No system instruction captured by dyn_instr_capture_hook"
        for placeholder in ["{repo_url?}", "{root_prompt?}", "{test_context?}",
                            "{skill_instruction?}", "{user_ctx_manifest?}"]:
            assert placeholder not in si, f"Unresolved placeholder: {placeholder}"

    async def test_resolved_values_present(self, run_result):
        si = run_result.final_state.get("_captured_system_instruction_0", "")
        assert "https://test.example.com/arch-test" in si
        assert "architecture introspection" in si
        assert "arch_context.txt" in si


class TestSqliteTelemetry:
    async def test_traces_completed(self, run_result):
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT status, total_calls FROM traces LIMIT 1"
            ).fetchone()
            assert row and row[0] == "completed"
            assert row[1] >= 2
        finally:
            conn.close()

    async def test_execute_code_telemetry(self, run_result):
        assert run_result.traces_db_path
        conn = sqlite3.connect(run_result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT repl_llm_calls FROM telemetry "
                "WHERE event_type='tool_call' AND tool_name='execute_code' LIMIT 1"
            ).fetchone()
            assert row and row[0] >= 1
        finally:
            conn.close()
```

---

## Implementation Order

1. **`rlm_adk/skills/test_skill.py`** — standalone, no dependencies (Doc 1)
2. **`skill_arch_test.json`** — merged fixture (Doc 1 base + Doc 3 `initial_state`)
3. **`stdout_parser.py`** — standalone parser (Doc 4)
4. **`instrumented_runner.py`** — needs `InstrumentationPlugin` + `dyn_instr_capture_hook` wiring (Doc 2 + Doc 3)
5. **`expected_lineage.py`** — with conflict resolutions applied (Doc 4, amended)
6. **`test_skill_arch_e2e.py`** — wires everything together (this doc)
7. **`state.py`** — optional `EXPOSED_STATE_KEYS` extension (Docs 1 + 3)

---

## What This Test Validates (Post-Thread-Bridge)

| Architecture Layer | What is Tested | Key Assertion |
|---|---|---|
| Skill source expansion | `expand_skill_imports()` detects `rlm_repl_skills.test_skill` | `repl_did_expand == True` |
| Thread-bridge execution | `execute_code_threaded()` runs REPL code in worker thread | `execution_mode == "thread_bridge"` |
| Sync `llm_query()` | `make_sync_llm_query()` bridges to event loop via `run_coroutine_threadsafe` | `child_result_preview` contains `arch_test_ok` |
| Child orchestrator dispatch | `create_child_orchestrator()` at depth+1 | `key_depth > 0` rows in sqlite |
| Dynamic instruction resolution | All 5 `{var?}` placeholders resolved from session state | No raw `{placeholder?}` in systemInstruction |
| User context injection | Path B loads `user_provided_ctx` into REPL globals | `user_ctx_manifest` contains filenames |
| State key lineage | Full lifecycle from `before_agent` through `after_tool` | `STATE:` tags in correct order |
| Observability pipeline | SqliteTracingPlugin records model calls + tool calls | `traces.status == "completed"` |
| REPL tracing | `RLM_REPL_TRACE=2` activates timing + memory tracking | `peak_memory_bytes > 0` (when available) |
