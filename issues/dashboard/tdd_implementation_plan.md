# Dashboard Gap Closure: TDD Implementation Plan

**Date:** 2026-03-25
**Source reports:** `mismatch_report.md`, `dashboard_data_pipeline_analysis.md`
**Fixture:** `skill_arch_test` (8 model calls, 3 depths, 2 iterations)

---

## Dependency Graph

```
Cycle 1 (per-iteration REPL code from telemetry)
  |
  v
Cycle 2 (per-iteration child summaries)
  |
  v
Cycle 3 (iteration navigation rendering)  <-- depends on Cycles 1+2 for full value
  |
  v
Cycle 4 (child summaries correlation with iteration)  <-- depends on Cycle 2
  |
  +------+------+------+
  |      |      |      |
  v      v      v      v
Cycle 5  Cycle 6  Cycle 7  Cycle 8
(batch   (fanout  (has_    (depth=2
 count)   idx)    errors)  reachability)

Independent tier (no dashboard dependencies):
  Cycle 5: child_total_batch_dispatches (sqlite_tracing.py)
  Cycle 6: fanout_idx metadata consistency (sqlite_tracing.py)
  Cycle 7: has_errors false positive (repl_tool.py)
```

---

## Test Infrastructure

### New test file

**`tests_rlm_adk/test_dashboard_flow_gaps.py`** -- all Cycles 1-4 and 8 tests live here.

### Shared fixtures and helpers

A `conftest.py` helper is NOT needed. The test file will define its own helpers that build synthetic `LiveInvocation`, `LiveInvocationNode`, `LivePane`, and `LiveChildSummary` objects. The existing `test_dashboard_ui_gaps.py` pattern of `_make_invocation` / `_make_node` will be adapted and extended.

Key helper signatures for the new test file:

```python
def _make_invocation(
    *,
    iteration: int = 0,
    repl_submission: str = "",
    child_summaries: list[LiveChildSummary] | None = None,
    repl_stdout: str = "",
    repl_stderr: str = "",
    state_items: list[LiveStateItem] | None = None,
    raw_payload: dict | None = None,
    depth: int = 0,
    fanout_idx: int | None = None,
    invocation_id: str = "inv-0",
) -> LiveInvocation: ...

def _make_node(
    *,
    invocation: LiveInvocation | None = None,
    available_invocations: list[LiveInvocation] | None = None,
    child_nodes: list[LiveInvocationNode] | None = None,
) -> LiveInvocationNode: ...

def _make_child_summary(
    *,
    depth: int = 1,
    fanout_idx: int = 0,
    parent_depth: int = 0,
    event_time: float = 1.0,
    prompt_preview: str = "child prompt",
    result_text: str = "child result",
) -> LiveChildSummary: ...
```

### Non-dashboard test files

- **`tests_rlm_adk/test_sqlite_tracing_gaps.py`** -- Cycles 5 and 6 (sqlite_tracing.py fixes).
- **`tests_rlm_adk/test_repl_tool_warnings.py`** -- Cycle 7 (repl_tool.py has_errors fix).

Both use the existing `run_fixture_contract_instrumented` harness with the `skill_arch_test.json` fixture.

---

## Cycle 1: Per-Iteration REPL Code from Telemetry

**Mismatches addressed:** Mismatch 1 (Turn 1 code invisible), Gap DL-1
**Severity:** Critical
**Layer:** Data loading (live_loader.py)

### Red test

**File:** `tests_rlm_adk/test_dashboard_flow_gaps.py`
**Class:** `TestPerIterationReplCode`
**Method:** `test_invocations_have_distinct_repl_submissions`

```python
class TestPerIterationReplCode:
    """Each LiveInvocation should carry its own iteration's REPL code,
    not the shared latest-state snapshot."""

    def test_invocations_have_distinct_repl_submissions(self):
        """Two invocations at depth=0 with different execute_code tool events
        should have different repl_submission values."""
        # Build SSE rows with two repl_submitted_code writes at different times
        sse_rows = [
            _sse_row("repl_submitted_code", depth=0, seq=3, event_time=10.0,
                     value_text="code_turn_1 = run_test_skill(...)"),
            _sse_row("repl_submitted_code", depth=0, seq=35, event_time=20.0,
                     value_text="code_turn_2 = llm_query_batched(...)"),
        ]
        # Build two tool_call telemetry rows (execute_code) at different times
        tool_rows = [
            _tool_telemetry_row(depth=0, start_time=10.1, iteration=0,
                                result_payload='{"stdout":"ok1","stderr":""}'),
            _tool_telemetry_row(depth=0, start_time=20.1, iteration=1,
                                result_payload='{"stdout":"ok2","stderr":""}'),
        ]
        # Build two snapshot rows at different timestamps
        snapshots = [
            _snapshot_row(agent_name="reasoning_agent", timestamp=10.0, iteration=0),
            _snapshot_row(agent_name="reasoning_agent", timestamp=20.0, iteration=1),
        ]
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        snapshot = loader._build_snapshot("sess-1", _make_cache(
            snapshots=snapshots, sse_rows=sse_rows, telemetry=tool_rows,
        ))
        pane = snapshot.pane_map.get("d0:root")
        assert pane is not None
        assert len(pane.invocations) == 2
        # KEY ASSERTION: each invocation has its own code, not the latest
        assert pane.invocations[0].repl_submission == "code_turn_1 = run_test_skill(...)"
        assert pane.invocations[1].repl_submission == "code_turn_2 = llm_query_batched(...)"
```

**Why it fails now:** `_build_invocation` at line 1040-1087 reads `REPL_SUBMITTED_CODE` from the shared `state_items` dict (which is `_latest_state_by_depth` -- last-write-wins). Both invocations get `"code_turn_2 = llm_query_batched(...)"`.

### Green implementation

**File:** `rlm_adk/dashboard/live_loader.py`
**Function:** `_build_invocation` (line 1009-1108)

**Change:** Instead of reading `repl_submission` from the shared `state_items`, source it from the SSE rows that are temporally closest to this invocation's snapshot timestamp.

1. Add a new parameter `sse_rows: list[dict]` to `_build_invocation`.
2. Build a per-invocation lookup: scan `sse_rows` for `state_key == "repl_submitted_code"` where `key_depth == depth` and `event_time <= snapshot_timestamp + 0.5`, keeping the latest one before the snapshot.
3. Use that value for `repl_submission` instead of `latest_repl.get(REPL_SUBMITTED_CODE)`.
4. Thread `sse_rows` through from `_build_snapshot` at line 723 into `_build_invocation`.

**Specific code change (line 1040-1087):**

Replace:
```python
latest_repl = {
    item.base_key: item
    for item in state_items
    if item.base_key in {REPL_SUBMITTED_CODE}
}
```

With:
```python
# Find the repl_submitted_code SSE event closest to this snapshot's timestamp
repl_code_for_invocation = ""
snapshot_ts = float(snapshot.get("timestamp") or 0.0)
for row in reversed(sse_rows):
    if (row.get("state_key") == REPL_SUBMITTED_CODE
            and _safe_int(row.get("key_depth")) == depth
            and float(row.get("event_time") or 0.0) <= snapshot_ts + 0.5):
        repl_code_for_invocation = row.get("value_text") or ""
        break
```

And at line 1083-1087, replace:
```python
repl_submission=str(
    latest_repl.get(REPL_SUBMITTED_CODE).value
    if latest_repl.get(REPL_SUBMITTED_CODE)
    else ""
),
```
With:
```python
repl_submission=repl_code_for_invocation,
```

**Caller change at `_build_snapshot` line 723:**

Add `sse_rows=sse_rows` to the `_build_invocation` call.

### Refactor

Remove the `latest_repl` dict entirely from `_build_invocation` since it is no longer used. The `state_items` parameter can remain for other state key reads.

### Risk assessment

- **Low risk.** The change only affects how `repl_submission` is sourced. Other fields still use `state_items`. The SSE rows already contain all `repl_submitted_code` events with timestamps.
- **Existing tests:** No existing test asserts on `repl_submission` content in the loader. The `test_dashboard_ui_gaps.py` tests construct invocations directly and do not go through `_build_invocation`.

### Estimated scope

- Files touched: 1 (`live_loader.py`)
- Lines changed: ~20 (function signature + body change)
- New test lines: ~60

---

## Cycle 2: Per-Iteration Child Summaries

**Mismatches addressed:** Mismatch 3 (Turn 1 children invisible), Gap DL-2
**Severity:** Critical
**Layer:** Data loading (live_loader.py)

### Red test

**File:** `tests_rlm_adk/test_dashboard_flow_gaps.py`
**Class:** `TestPerIterationChildSummaries`
**Method:** `test_invocations_have_iteration_specific_children`

```python
class TestPerIterationChildSummaries:
    """Each LiveInvocation should carry only the child summaries
    from its own iteration, not just the latest iteration's children."""

    def test_invocations_have_iteration_specific_children(self):
        """Two invocations at depth=0 with children dispatched at different
        times should carry their own child summaries."""
        # Child summary from iteration 0 (chain child)
        sse_rows = [
            _sse_child_summary_row(depth=1, fanout_idx=0, event_time=11.0, seq=14,
                                   prompt="chain child prompt", result="chain result"),
            # Child summaries from iteration 1 (batch children)
            _sse_child_summary_row(depth=1, fanout_idx=0, event_time=21.0, seq=45,
                                   prompt="batch child A", result="finding_A"),
            _sse_child_summary_row(depth=1, fanout_idx=1, event_time=21.5, seq=46,
                                   prompt="batch child B", result="finding_B"),
        ]
        snapshots = [
            _snapshot_row(agent_name="reasoning_agent", timestamp=10.0, iteration=0),
            _snapshot_row(agent_name="reasoning_agent", timestamp=20.0, iteration=1),
        ]
        loader = LiveDashboardLoader.__new__(LiveDashboardLoader)
        snapshot = loader._build_snapshot("sess-1", _make_cache(
            snapshots=snapshots, sse_rows=sse_rows,
        ))
        pane = snapshot.pane_map.get("d0:root")
        assert pane is not None
        assert len(pane.invocations) == 2
        # Iteration 0 should have 1 child (the chain child)
        inv0 = pane.invocations[0]
        assert len(inv0.child_summaries) == 1
        assert inv0.child_summaries[0].prompt_preview == "chain child prompt"
        # Iteration 1 should have 2 children (the batch children)
        inv1 = pane.invocations[1]
        assert len(inv1.child_summaries) == 2
```

**Why it fails now:** `_build_invocation` at line 1045 filters `child_summaries` by `parent_depth == depth` but does NOT filter by iteration/timestamp. All 3 children get assigned to every invocation at depth=0.

### Green implementation

**File:** `rlm_adk/dashboard/live_loader.py`
**Function:** `_build_snapshot` (line 695) and `_build_invocation` (line 1009)

**Change:** Associate child summaries with the invocation whose timestamp window contains the child's `event_time`.

1. In `_build_snapshot`, instead of passing `child_summaries.get(depth + 1, [])` to every invocation, pass only those child summaries whose `event_time` falls between this snapshot's timestamp and the next snapshot's timestamp at the same depth.

2. Compute per-invocation timestamp windows in `_build_snapshot` before the invocation construction loop (lines 717-737):

```python
# Build timestamp windows per depth for child summary attribution
depth_snapshot_times: dict[int, list[float]] = defaultdict(list)
for snap in snapshots:
    d = _depth_from_agent(snap.get("agent_name", ""))
    depth_snapshot_times[d].append(float(snap.get("timestamp") or 0.0))
for times in depth_snapshot_times.values():
    times.sort()
```

3. In the per-snapshot loop, compute `(lower_ts, upper_ts)` for this snapshot:

```python
snap_ts = float(snapshot.get("timestamp") or 0.0)
times_at_depth = depth_snapshot_times.get(depth, [snap_ts])
snap_idx = times_at_depth.index(snap_ts) if snap_ts in times_at_depth else 0
upper_ts = times_at_depth[snap_idx + 1] if snap_idx + 1 < len(times_at_depth) else float("inf")
iteration_children = [
    child for child in child_summaries.get(depth + 1, [])
    if child.parent_depth == depth and snap_ts <= child.event_time < upper_ts
]
```

4. Pass `iteration_children` to `_build_invocation` as `child_summaries` instead of the full list.

5. Also update `LivePane.child_summaries` at line 795 to use the selected invocation's children rather than `latest.child_summaries`.

### Refactor

Extract the timestamp-window logic into a helper `_children_in_window(all_children, lower_ts, upper_ts, parent_depth)`.

### Risk assessment

- **Medium risk.** Changes the child_summaries association logic. Could affect the tree view and child window drill-down if they relied on seeing ALL children on every invocation. Existing tests do not assert on child_summaries in the loader path.
- The `FlowChildCard` rendering and child window route both read from `inv.child_summaries`, so this change automatically fixes the flow view.

### Estimated scope

- Files touched: 1 (`live_loader.py`)
- Lines changed: ~30
- New test lines: ~50

---

## Cycle 3: Iteration Navigation Rendering

**Mismatches addressed:** Mismatch 2 (no iteration nav), Gap RG-1
**Severity:** High
**Layer:** Rendering (flow_reasoning_pane.py)

### Red test

**File:** `tests_rlm_adk/test_dashboard_flow_gaps.py`
**Class:** `TestIterationNavigation`
**Method:** `test_iteration_nav_rendered_when_multiple_iterations`

```python
class TestIterationNavigation:
    """render_flow_reasoning_pane must render iteration navigation
    when available_iteration_ids has more than 1 entry."""

    def test_iteration_nav_rendered_when_multiple_iterations(self):
        """When FlowAgentCard.available_iteration_ids has 3 entries,
        the renderer must create navigation elements."""
        from rlm_adk.dashboard.components.flow_reasoning_pane import render_flow_reasoning_pane
        from rlm_adk.dashboard.flow_models import FlowAgentCard

        card = FlowAgentCard(
            agent_name="reasoning_agent",
            depth=0,
            iteration=2,
            available_iteration_ids=[(0, "inv-0"), (1, "inv-1"), (2, "inv-2")],
            status="completed",
            pane_id="d0:root",
        )
        captured_labels = []
        with patch("rlm_adk.dashboard.components.flow_reasoning_pane.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label
            mock_label.tooltip.return_value = mock_label

            mock_button = MagicMock()
            mock_ui.button.return_value = mock_button
            mock_button.style.return_value = mock_button
            mock_button.props.return_value = mock_button
            mock_button.on.return_value = mock_button

            render_flow_reasoning_pane(card, on_select_iteration=lambda pid, iid: None)

            # Collect all label text
            for call in mock_ui.label.call_args_list:
                if call.args:
                    captured_labels.append(call.args[0])

        # Must contain iteration indicator labels like "Turn 1", "Turn 2", "Turn 3"
        # or equivalent iteration numbers
        iter_labels = [l for l in captured_labels if "Turn" in str(l) or "Iter" in str(l)]
        assert len(iter_labels) >= 1, (
            f"No iteration navigation labels found. Labels rendered: {captured_labels}"
        )

    def test_no_iteration_nav_when_single_iteration(self):
        """When available_iteration_ids has only 1 entry,
        no iteration navigation should be rendered."""
        from rlm_adk.dashboard.components.flow_reasoning_pane import render_flow_reasoning_pane
        from rlm_adk.dashboard.flow_models import FlowAgentCard

        card = FlowAgentCard(
            agent_name="reasoning_agent",
            depth=0,
            iteration=0,
            available_iteration_ids=[(0, "inv-0")],
            status="completed",
            pane_id="d0:root",
        )
        with patch("rlm_adk.dashboard.components.flow_reasoning_pane.ui") as mock_ui:
            mock_element = MagicMock()
            mock_ui.element.return_value = mock_element
            mock_element.style.return_value = mock_element
            mock_element.__enter__ = MagicMock(return_value=mock_element)
            mock_element.__exit__ = MagicMock(return_value=False)
            mock_element.on.return_value = mock_element

            mock_label = MagicMock()
            mock_ui.label.return_value = mock_label
            mock_label.style.return_value = mock_label
            mock_label.tooltip.return_value = mock_label

            render_flow_reasoning_pane(card, on_select_iteration=lambda pid, iid: None)

            captured_labels = [
                call.args[0] for call in mock_ui.label.call_args_list if call.args
            ]

        iter_labels = [l for l in captured_labels if "Turn" in str(l) or "Iter" in str(l)]
        assert len(iter_labels) == 0, (
            f"Iteration navigation rendered for single iteration: {iter_labels}"
        )
```

**Why it fails now:** `render_flow_reasoning_pane` (line 38-51) calls `_header_row(card)` and `_context_rows(card, ...)` but neither reads `card.available_iteration_ids`. The function signature does not accept an `on_select_iteration` callback.

### Green implementation

**File:** `rlm_adk/dashboard/components/flow_reasoning_pane.py`

**Change 1:** Add `on_select_iteration` parameter to `render_flow_reasoning_pane`:

```python
def render_flow_reasoning_pane(
    card: FlowAgentCard,
    *,
    on_open_context=None,
    on_select_iteration=None,  # NEW: callback(pane_id, invocation_id)
) -> None:
```

**Change 2:** Add `_iteration_nav_row` function and call it from `render_flow_reasoning_pane` between `_header_row` and `_context_rows`:

```python
def _iteration_nav_row(card: FlowAgentCard, *, on_select_iteration) -> None:
    """Render iteration navigation when multiple iterations are available."""
    if len(card.available_iteration_ids) <= 1:
        return
    with ui.element("div").style(
        "display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; "
        "padding: 0.3rem 0; min-width: 0;"
    ):
        for iter_num, inv_id in card.available_iteration_ids:
            is_active = iter_num == card.iteration
            label = f"Turn {iter_num + 1}"
            bg = "var(--accent-active)" if is_active else "transparent"
            text_color = "var(--bg-0)" if is_active else "var(--text-1)"
            border = "var(--accent-active)" if is_active else "var(--border-1)"
            el = ui.element("div").style(
                f"cursor: pointer; padding: 0.2rem 0.6rem; border-radius: 999px; "
                f"border: 1px solid {border}; background: {bg};"
            )
            if on_select_iteration and not is_active:
                el.on("click", lambda _e, pid=card.pane_id, iid=inv_id: on_select_iteration(pid, iid))
            with el:
                ui.label(label).style(
                    f"color: {text_color}; font-size: 0.76rem; font-weight: 600;"
                )
```

**Change 3:** Wire `on_select_iteration` from the flow transcript renderer and the live_app. In `flow_transcript.py`, pass the callback through to `render_flow_reasoning_pane`. In `live_app.py`, pass `controller.select_iteration` as the callback.

### Refactor

None needed -- the function is clean and isolated.

### Risk assessment

- **Low risk.** Additive change. Existing single-iteration views get no navigation (the guard `len(...) <= 1` prevents rendering). No existing tests break because `on_select_iteration` defaults to `None`.
- The `controller.select_iteration(pane_id, invocation_id)` method already exists and is tested.

### Estimated scope

- Files touched: 3 (`flow_reasoning_pane.py`, `flow_transcript.py` or its caller, `live_app.py`)
- Lines changed: ~50 (new function + wiring)
- New test lines: ~80

---

## Cycle 4: Flow Builder Reads Per-Iteration Data Correctly

**Mismatches addressed:** Mismatch 1 + 3 combined (flow view shows correct code + children per selected iteration)
**Severity:** Critical
**Layer:** Flow building + controller (flow_builder.py, live_controller.py)
**Depends on:** Cycles 1, 2, 3

### Red test

**File:** `tests_rlm_adk/test_dashboard_flow_gaps.py`
**Class:** `TestFlowTranscriptPerIteration`
**Method:** `test_flow_transcript_shows_selected_iteration_code_and_children`

```python
class TestFlowTranscriptPerIteration:
    """The flow transcript should reflect the selected iteration's
    code and children, not just the latest."""

    def test_flow_transcript_shows_selected_iteration_code_and_children(self):
        """When iteration 0 is selected, flow transcript should show
        iteration 0's code and iteration 0's children."""
        from rlm_adk.dashboard.flow_builder import build_flow_transcript
        from rlm_adk.dashboard.flow_models import FlowCodeCell, FlowChildCard

        chain_child = _make_child_summary(
            depth=1, fanout_idx=0, prompt_preview="chain child prompt",
            result_text="chain_result",
        )
        inv_0 = _make_invocation(
            iteration=0,
            repl_submission="result = run_test_skill(...)\nprint(result)",
            child_summaries=[chain_child],
            invocation_id="inv-0",
            raw_payload={"timestamp": 10.0},
        )
        inv_1 = _make_invocation(
            iteration=1,
            repl_submission="results = llm_query_batched([...])\nprint(results)",
            child_summaries=[
                _make_child_summary(depth=1, fanout_idx=0, prompt_preview="batch A"),
                _make_child_summary(depth=1, fanout_idx=1, prompt_preview="batch B"),
            ],
            invocation_id="inv-1",
            raw_payload={"timestamp": 20.0},
        )
        # Node with iteration 0 SELECTED
        node = _make_node(
            invocation=inv_0,
            available_invocations=[inv_0, inv_1],
        )
        transcript = build_flow_transcript([node])

        code_cells = [b for b in transcript.blocks if isinstance(b, FlowCodeCell)]
        child_cards = [b for b in transcript.blocks if isinstance(b, FlowChildCard)]

        assert len(code_cells) == 1
        assert "run_test_skill" in code_cells[0].code
        assert "llm_query_batched" not in code_cells[0].code
        assert len(child_cards) == 1
        assert child_cards[0].prompt_preview == "chain child prompt"
```

**Why it fails now (after Cycles 1-2):** This test validates that the flow builder correctly uses the *selected* invocation's data. With Cycles 1-2 implemented, each invocation carries its own code and children, so the flow builder should already pass this test. This cycle serves as an integration verification. If it fails, there is a wiring issue between the controller's `_build_invocation_node` (which picks the selected invocation) and `_process_node` in `flow_builder.py`.

### Green implementation

After Cycles 1 and 2, this test should pass without additional code changes. The flow builder already reads `inv.repl_submission` and `inv.child_summaries` from the selected invocation (line 106, 112). The controller's `_build_invocation_node` already selects the correct invocation based on `selected_invocation_id_by_pane` (line 549).

If it does NOT pass, the fix is:
- Ensure `_process_node` reads from `node.invocation` (the selected one), not from any "latest" fallback.
- Currently it does: `inv = node.invocation` at line 79. This is correct.

### Refactor

None needed.

### Risk assessment

- **No risk.** This is a pure verification test. No code change expected.

### Estimated scope

- Files touched: 0
- New test lines: ~40

---

## Cycle 5: Populate `child_total_batch_dispatches` in Traces

**Mismatches addressed:** Mismatch 8 (NULL batch count)
**Severity:** Medium
**Layer:** Non-dashboard (sqlite_tracing.py)

### Red test

**File:** `tests_rlm_adk/test_sqlite_tracing_gaps.py`
**Class:** `TestBatchDispatchCount`
**Method:** `test_child_total_batch_dispatches_populated`

```python
class TestBatchDispatchCount:
    """child_total_batch_dispatches should be non-NULL when batch dispatches occurred."""

    @pytest.mark.provider_fake
    async def test_child_total_batch_dispatches_populated(self, tmp_path):
        """After running skill_arch_test, child_total_batch_dispatches should be >= 1."""
        result = await run_fixture_contract_instrumented(
            FIXTURE_PATH, traces_db_path=str(tmp_path / "traces.db"),
            tmpdir=str(tmp_path),
        )
        assert result.contract.passed

        conn = sqlite3.connect(result.traces_db_path)
        try:
            row = conn.execute(
                "SELECT child_total_batch_dispatches FROM traces LIMIT 1"
            ).fetchone()
            assert row is not None
            assert row[0] is not None, (
                "child_total_batch_dispatches is NULL. "
                "The trace finalization should count batch dispatches."
            )
            assert row[0] >= 1, f"Expected >= 1 batch dispatch, got {row[0]}"
        finally:
            conn.close()
```

**Why it fails now:** Line 877 of `sqlite_tracing.py` hardcodes `None` for `child_total_batch_dispatches`.

### Green implementation

**File:** `rlm_adk/plugins/sqlite_tracing.py`
**Function:** `_build_trace_summary_from_telemetry` (line 697)

**Add after the child dispatch count query (after line 801):**

```python
# Batch dispatch count: count distinct (iteration, depth) groups
# where multiple model_call rows share the same iteration at depth > 0
batch_row = self._conn.execute(
    """SELECT COUNT(*) FROM (
         SELECT iteration, depth
         FROM telemetry
         WHERE trace_id = ?
           AND event_type = 'model_call'
           AND depth > 0
           AND iteration IS NOT NULL
         GROUP BY iteration, depth
         HAVING COUNT(*) > 1
       )""",
    (tid,),
).fetchone()
if batch_row and batch_row[0]:
    summary["child_total_batch_dispatches"] = batch_row[0]
```

**And at line 877, replace:**
```python
None,  # child_total_batch_dispatches
```
**With:**
```python
summary.get("child_total_batch_dispatches"),
```

### Refactor

None needed.

### Risk assessment

- **Low risk.** Only changes the traces table summary row. No downstream readers currently depend on this column (it has always been NULL).

### Estimated scope

- Files touched: 1 (`sqlite_tracing.py`)
- Lines changed: ~15
- New test lines: ~25

---

## Cycle 6: Fanout Index Metadata Consistency

**Mismatches addressed:** Mismatch 4 (fanout_idx column vs custom_metadata_json swap)
**Severity:** Medium
**Layer:** Non-dashboard (sqlite_tracing.py)

### Red test

**File:** `tests_rlm_adk/test_sqlite_tracing_gaps.py`
**Class:** `TestFanoutIdxConsistency`
**Method:** `test_fanout_idx_column_matches_metadata_json`

```python
class TestFanoutIdxConsistency:
    """The fanout_idx column should match the fanout_idx in custom_metadata_json."""

    @pytest.mark.provider_fake
    async def test_fanout_idx_column_matches_metadata_json(self, tmp_path):
        """For every model_call row, if custom_metadata_json contains fanout_idx,
        it must match the fanout_idx column value."""
        result = await run_fixture_contract_instrumented(
            FIXTURE_PATH, traces_db_path=str(tmp_path / "traces.db"),
            tmpdir=str(tmp_path),
        )
        assert result.contract.passed

        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT fanout_idx, custom_metadata_json, agent_name, call_number "
                "FROM telemetry WHERE event_type='model_call' AND custom_metadata_json IS NOT NULL"
            ).fetchall()
            for col_fanout, meta_json, agent, call_num in rows:
                meta = json.loads(meta_json)
                meta_fanout = meta.get("fanout_idx")
                assert col_fanout == meta_fanout, (
                    f"Fanout mismatch for {agent} call_number={call_num}: "
                    f"column={col_fanout}, metadata={meta_fanout}"
                )
        finally:
            conn.close()
```

**Why it fails now:** In `after_model_callback` (line 1074-1085), `custom_metadata_json` reads `fanout_idx` from `agent._rlm_fanout_idx` which can differ from what was written to the column in `before_model_callback` (line 948). During batched dispatch, the agent's `_rlm_fanout_idx` attribute may be mutated between the before/after callbacks for different batch members.

### Green implementation

**File:** `rlm_adk/plugins/sqlite_tracing.py`
**Function:** `after_model_callback` (line 1019)

**Change:** Instead of re-reading `agent._rlm_fanout_idx` in the after callback, store the fanout_idx in `_pending_model_telemetry` alongside `(telemetry_id, start_time)` and use the stored value when building `custom_metadata_json`.

1. At line 1008, change the pending store to include `fanout_idx`:
```python
self._pending_model_telemetry[self._pending_key(callback_context)] = (
    telemetry_id,
    start_time,
    fanout_idx,  # NEW: capture at before_model time
)
```

2. At line 1028-1033, unpack the stored fanout_idx:
```python
pending = self._pending_model_telemetry.pop(
    self._pending_key(callback_context),
    None,
)
stored_fanout_idx = None
if pending is None and self._pending_model_telemetry:
    _, pending = self._pending_model_telemetry.popitem()
if pending:
    telemetry_id, start_time, stored_fanout_idx = pending
```

3. At line 1078, use `stored_fanout_idx` instead of the live agent attr:
```python
"fanout_idx": stored_fanout_idx if stored_fanout_idx is not None else getattr(agent, "_rlm_fanout_idx", None),
```

### Refactor

Type the pending tuple as a `NamedTuple` for clarity:
```python
_PendingModel = namedtuple("_PendingModel", ["telemetry_id", "start_time", "fanout_idx"])
```

### Risk assessment

- **Medium risk.** Changes the pending model telemetry tuple structure. All consumers of `_pending_model_telemetry` must unpack the new 3-tuple. There is only one consumer (`after_model_callback`) and one writer (`before_model_callback`), plus the fallback `popitem()` path.
- The `popitem()` fallback also needs to handle the 3-tuple. If old entries are still 2-tuples (from a mixed-version run), this could fail. Add a guard: `if len(pending) == 3: ... else: fallback`.

### Estimated scope

- Files touched: 1 (`sqlite_tracing.py`)
- Lines changed: ~15
- New test lines: ~30

---

## Cycle 7: Distinguish Warnings from Errors in `has_errors`

**Mismatches addressed:** Mismatch 5 (`has_errors=true` for benign UserWarning)
**Severity:** Low
**Layer:** Non-dashboard (repl_tool.py)

### Red test

**File:** `tests_rlm_adk/test_repl_tool_warnings.py`
**Class:** `TestHasErrorsWarningDistinction`
**Method:** `test_has_errors_false_for_python_warnings`

```python
class TestHasErrorsWarningDistinction:
    """has_errors should be False when stderr contains only Python warnings."""

    def test_has_errors_false_for_python_warnings(self):
        """Stderr containing only UserWarning lines should NOT set has_errors=True."""
        from rlm_adk.tools.repl_tool import _is_real_error  # NEW function

        warning_stderr = (
            "/path/to/worker_retry.py:89: UserWarning: [EXPERIMENTAL] "
            "ReflectAndRetryToolPlugin: This feature is experimental.\n"
            "  super().__init__(max_retries=max_retries)\n"
        )
        assert _is_real_error(warning_stderr) is False

    def test_has_errors_true_for_real_traceback(self):
        """Stderr containing a real traceback should set has_errors=True."""
        from rlm_adk.tools.repl_tool import _is_real_error

        traceback_stderr = (
            "Traceback (most recent call last):\n"
            "  File \"test.py\", line 1, in <module>\n"
            "    raise ValueError('bad')\n"
            "ValueError: bad\n"
        )
        assert _is_real_error(traceback_stderr) is True

    def test_has_errors_true_for_mixed_warning_and_error(self):
        """Stderr with both warnings and a real error should be has_errors=True."""
        from rlm_adk.tools.repl_tool import _is_real_error

        mixed_stderr = (
            "/path/to/file.py:10: UserWarning: benign\n"
            "  warnings.warn('benign')\n"
            "Traceback (most recent call last):\n"
            "  File \"test.py\", line 1\n"
            "NameError: name 'x' is not defined\n"
        )
        assert _is_real_error(mixed_stderr) is True

    def test_has_errors_false_for_empty_stderr(self):
        """Empty stderr is not an error."""
        from rlm_adk.tools.repl_tool import _is_real_error

        assert _is_real_error("") is False
        assert _is_real_error("   \n  ") is False

    def test_has_errors_true_for_syntax_error(self):
        """SyntaxError in stderr should be has_errors=True."""
        from rlm_adk.tools.repl_tool import _is_real_error

        syntax_stderr = "SyntaxError: invalid syntax\n"
        assert _is_real_error(syntax_stderr) is True
```

**Why it fails now:** `_is_real_error` does not exist. REPLTool uses `bool(result.stderr)` at line 271.

### Green implementation

**File:** `rlm_adk/tools/repl_tool.py`

**Change 1:** Add a module-level function:

```python
import re

# Patterns indicating real errors (not just warnings)
_ERROR_PATTERNS = re.compile(
    r"(Traceback \(most recent call last\)|"
    r"^\w*Error:|"
    r"^\w*Exception:|"
    r"^SyntaxError:)",
    re.MULTILINE,
)

# Pattern for Python warning lines (e.g., "file.py:10: UserWarning: ...")
_WARNING_LINE_RE = re.compile(r"^.+:\d+: \w*Warning: ", re.MULTILINE)


def _is_real_error(stderr: str) -> bool:
    """Return True if stderr contains actual errors, not just Python warnings."""
    if not stderr or not stderr.strip():
        return False
    if _ERROR_PATTERNS.search(stderr):
        return True
    # If ALL non-empty lines match the warning pattern or its continuation
    # (indented lines following a warning), it's not a real error.
    lines = stderr.strip().splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Warning continuation lines are indented
        if line.startswith((" ", "\t")):
            continue
        # Warning header lines match the pattern
        if _WARNING_LINE_RE.match(line):
            continue
        # Unrecognized non-empty, non-indented line -- treat as error
        return True
    return False
```

**Change 2:** At line 271, replace:
```python
"has_errors": bool(result.stderr),
```
With:
```python
"has_errors": _is_real_error(result.stderr),
```

**Also update the same pattern at lines 207 and 240** (error path returns in `run_async`):
Those lines are error paths where stderr contains actual exceptions, so `_is_real_error` would correctly return True. But for safety, keep those as-is since they are guaranteed error paths.

### Refactor

None needed.

### Risk assessment

- **Low risk.** The change makes `has_errors` more accurate. Any code that currently reads `has_errors=true` and takes action (like showing error styling) will now correctly skip warning-only cases.
- **Backwards-compatible:** Stderr with real errors still sets `has_errors=true`. Only warning-only stderr is reclassified.

### Estimated scope

- Files touched: 1 (`repl_tool.py`)
- Lines changed: ~30 (new function + one-line change)
- New test lines: ~50

---

## Cycle 8: Depth=2 Chain Reachability from Flow View

**Mismatches addressed:** Mismatch 7 (depth=2 data unreachable), Gap RG-2
**Severity:** High
**Layer:** Rendering (flow view integration)
**Depends on:** Cycles 2, 3

### Red test

**File:** `tests_rlm_adk/test_dashboard_flow_gaps.py`
**Class:** `TestDepth2Reachability`
**Method:** `test_turn1_child_card_has_pane_id_for_drilldown`

```python
class TestDepth2Reachability:
    """After iteration navigation to Turn 1, the chain child at depth=1
    should have a pane_id enabling drill-down to depth=2."""

    def test_turn1_child_card_has_pane_id_for_drilldown(self):
        """FlowChildCard for the chain child should have a non-None pane_id
        that enables the 'Open window' button for drill-down."""
        from rlm_adk.dashboard.flow_builder import build_flow_transcript
        from rlm_adk.dashboard.flow_models import FlowChildCard

        chain_child = _make_child_summary(
            depth=1, fanout_idx=0, prompt_preview="chain child",
            result_text="chain_result",
        )
        inv_0 = _make_invocation(
            iteration=0,
            repl_submission="result = run_test_skill(...)\nchild_result = llm_query('dispatch')",
            child_summaries=[chain_child],
            invocation_id="inv-0",
            raw_payload={"timestamp": 10.0},
        )
        # Child node representing the depth=1 pane
        child_inv = _make_invocation(
            depth=1, fanout_idx=0, iteration=0,
            invocation_id="child-inv-0",
            repl_submission="grandchild = llm_query('go deeper')",
        )
        child_node = _make_node(
            invocation=child_inv,
            pane_id="d1:f0",
        )
        node = _make_node(
            invocation=inv_0,
            available_invocations=[inv_0],
            child_nodes=[child_node],
        )
        transcript = build_flow_transcript([node])

        child_cards = [b for b in transcript.blocks if isinstance(b, FlowChildCard)]
        assert len(child_cards) == 1
        assert child_cards[0].pane_id == "d1:f0", (
            f"Child card pane_id should be 'd1:f0' for drill-down, got {child_cards[0].pane_id}"
        )
```

**Why it fails now (pre Cycle 2):** Before Cycle 2, iteration 0's child summaries are lost. After Cycle 2, this test should pass because the chain child is correctly associated with iteration 0, and `_find_child_pane_id` (flow_builder.py line 220-230) looks up the child node by `(depth, fanout_idx)`.

### Green implementation

After Cycles 2 and 3, this test verifies the end-to-end path: selecting Turn 1 via iteration navigation -> Turn 1's chain child appears as a FlowChildCard with a valid `pane_id` -> user can click "Open window" -> child window shows depth=1 content (which itself shows the depth=2 grandchild dispatch).

No additional code change needed beyond Cycles 2 and 3. This cycle is a verification test.

If it fails, the fix would be in `_find_child_pane_id` (flow_builder.py line 220-230) -- ensure it searches `node.child_nodes` correctly for the matching `(depth, fanout_idx)`.

### Refactor

None needed.

### Risk assessment

- **No risk.** Pure verification test.

### Estimated scope

- Files touched: 0
- New test lines: ~35

---

## Summary

### Files touched (ordered by change count)

| File | Cycles | Change type | Lines changed (est.) |
|------|--------|-------------|---------------------|
| `rlm_adk/dashboard/live_loader.py` | 1, 2 | Data loading fixes | ~50 |
| `rlm_adk/dashboard/components/flow_reasoning_pane.py` | 3 | New iteration nav | ~50 |
| `rlm_adk/plugins/sqlite_tracing.py` | 5, 6 | Trace summary + fanout fix | ~30 |
| `rlm_adk/tools/repl_tool.py` | 7 | Warning distinction | ~30 |
| `rlm_adk/dashboard/components/flow_transcript.py` (or caller) | 3 | Callback wiring | ~5 |
| `rlm_adk/dashboard/live_app.py` | 3 | Callback wiring | ~5 |

### New test files

| File | Cycles | Test count (est.) |
|------|--------|-------------------|
| `tests_rlm_adk/test_dashboard_flow_gaps.py` | 1, 2, 3, 4, 8 | ~8 tests |
| `tests_rlm_adk/test_sqlite_tracing_gaps.py` | 5, 6 | ~2 tests |
| `tests_rlm_adk/test_repl_tool_warnings.py` | 7 | ~5 tests |

### Total estimated scope

- **New test files:** 3
- **Production files modified:** 6
- **Total new test methods:** ~15
- **Total production lines changed:** ~170
- **Total test lines:** ~370

---

## Deferred Items (Not in Scope)

These items from the mismatch report are classified as feature requests or by-design decisions, not bugs:

| Item | Report Reference | Reason for Deferral |
|------|-----------------|---------------------|
| Inline child expansion (MU-2) | Section 4, MU-2 | Significant UI rework. Current drill-down via child window is functional. |
| Multi-iteration timeline (MU-1) | Section 4, MU-1 | New feature. Iteration navigation (Cycle 3) provides the core capability. |
| Batch dispatch grouping (MU-3) | Section 4, MU-3 | Visual enhancement. Children are shown individually which is correct. |
| REPL code diff (MU-4) | Section 4, MU-4 | New feature. Per-iteration code (Cycle 1) enables future diffing. |
| Mismatch 6 (stdout length diff) | Section 3, Mismatch 6 | Informational. The fixture runtime captures extra plugin instrumentation that is not the dashboard's responsibility. |
| `_depth_from_agent` naming dependency (Gap 4) | Pipeline analysis, Gap 4 | Architectural constraint. All agents currently follow the `_d(\d+)` naming convention. |
| Model events 10ms timestamp window (Gap 6) | Pipeline analysis, Gap 6 | Edge case on slow machines. Not reproducible in provider-fake tests. |

---

## Execution Order

```
1. Cycle 7  (has_errors fix -- fully independent, easy win)
2. Cycle 5  (batch dispatch count -- fully independent, easy win)
3. Cycle 6  (fanout_idx consistency -- fully independent)
4. Cycle 1  (per-iteration REPL code -- critical data fix)
5. Cycle 2  (per-iteration child summaries -- critical data fix)
6. Cycle 4  (integration verification -- validates Cycles 1+2)
7. Cycle 3  (iteration navigation rendering -- unlocks UI)
8. Cycle 8  (depth=2 reachability verification -- validates Cycles 2+3)
```

This ordering starts with independent, low-risk fixes (Cycles 5, 6, 7), then addresses the critical data-layer gaps (Cycles 1, 2), verifies integration (Cycle 4), adds the UI (Cycle 3), and validates end-to-end reachability (Cycle 8).
