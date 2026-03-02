# NiceGUI Review: Context Window Dashboard v2 Plan

## Summary of Issues Found

13 issues identified across the plan's NiceGUI integration. Severity breakdown:

| Severity | Count | Description |
|----------|-------|-------------|
| **BUG** | 4 | Code will fail or produce wrong output at runtime |
| **ANTI-PATTERN** | 5 | Works but violates NiceGUI best practices or causes subtle problems |
| **IMPROVEMENT** | 4 | Opportunities for better NiceGUI patterns |

---

## Issue 1: ECharts Tooltip `{d}%` Does Not Work for Stacked Bar Charts

**Severity: BUG**

### Original Plan (Section 8.1, line ~708)

```python
"tooltip": {
    "trigger": "item",
    "formatter": "{b}: {c} tokens ({d}%)",
},
```

### What's Wrong

The `{d}` placeholder is an ECharts feature exclusive to **pie charts** where it represents the percentage of a slice relative to the total. For bar charts (including stacked bars), `{d}` resolves to nothing or `undefined`. The tooltip will render as `"reasoning_agent: 1130 tokens ()"` with an empty percentage.

### Corrected Approach

Use a JavaScript formatter function via the NiceGUI `:` prefix convention. The `:` prefix tells `ui.echart` to evaluate the value as a JavaScript expression instead of a string literal.

```python
def build_context_bar_options(window: ContextWindow) -> dict:
    """Build ECharts options for a stacked horizontal bar."""
    series = []
    total_tokens = sum(c.estimated_tokens for c in window.chunks)

    for category in ChunkCategory:
        category_chunks = [c for c in window.chunks if c.category == category]
        if not category_chunks:
            continue
        cat_tokens = sum(c.estimated_tokens for c in category_chunks)
        series.append({
            "name": category.value,
            "type": "bar",
            "stack": "total",
            "data": [cat_tokens],
            "itemStyle": {"color": CATEGORY_COLORS[category]},
            "emphasis": {"itemStyle": {"borderWidth": 2, "borderColor": "#fff"}},
        })

    return {
        "tooltip": {
            "trigger": "item",
            # Use ':formatter' (colon prefix) to pass a JS function
            ":formatter": """(params) => {
                const total = %d;
                const pct = total > 0 ? (params.value / total * 100).toFixed(1) : '0.0';
                return params.seriesName + ': ' + params.value.toLocaleString()
                    + ' tokens (' + pct + '%%' + ')';
            }""" % total_tokens,
        },
        "xAxis": {"type": "value", "show": False},
        "yAxis": {
            "type": "category",
            "data": [window.agent_name],
            "axisLabel": {"show": True},
        },
        "series": series,
        "grid": {"left": 120, "right": 20, "top": 10, "bottom": 10},
    }
```

**Key point**: The `:formatter` key (with colon prefix) is the NiceGUI `ui.echart` convention for embedding JavaScript expressions. Without the colon, NiceGUI treats the value as a plain string and it will not be evaluated as JavaScript.

---

## Issue 2: Keyboard Event Handler Checks `e.key == "ArrowLeft"` -- Wrong API

**Severity: BUG**

### Original Plan (Section 8.4, line ~769)

```python
async def handle_key(e):
    if e.key == "ArrowLeft":
        controller.navigate(-1)
        refresh_all()
```

### What's Wrong

In NiceGUI, `e.key` is a `KeyboardKey` object, not a plain string. Comparing it directly to a string like `"ArrowLeft"` will always be `False`. The `KeyboardKey` object has convenience properties like `e.key.arrow_left`, `e.key.arrow_right`, etc. Additionally, the handler fires on both `keydown` and `keyup` -- without filtering on `e.action.keydown`, every key press triggers navigation **twice**.

### Corrected Approach

```python
from nicegui.events import KeyEventArguments


def setup_keyboard_nav():
    def handle_key(e: KeyEventArguments):
        # Only respond to keydown, not keyup or repeat
        if not e.action.keydown:
            return

        if e.key.arrow_left:
            controller.navigate(-1)
            refresh_all()
        elif e.key.arrow_right:
            controller.navigate(1)
            refresh_all()
        elif e.key.home:
            controller.navigate_to(0)
            refresh_all()
        elif e.key.end:
            controller.navigate_to(len(controller.state.iterations) - 1)
            refresh_all()

    ui.keyboard(on_key=handle_key)
```

**Key points**:
- Use `e.key.arrow_left` (boolean property), not `e.key == "ArrowLeft"` (string comparison)
- Filter on `e.action.keydown` to prevent double-firing on keydown+keyup
- Use `e.key.home` and `e.key.end` for Home/End keys
- The handler signature should type-hint `KeyEventArguments` for clarity

---

## Issue 3: `ui.badge` Uses `.props("color=...")` Instead of Constructor Parameter

**Severity: BUG**

### Original Plan (Section 8.2, line ~744)

```python
ui.badge(f"{chunk.char_count:,} chars").props("color=grey-7")
ui.badge(f"~{chunk.estimated_tokens:,} tokens").props("color=primary")
```

### What's Wrong

In NiceGUI, `ui.badge` has `color` and `text_color` as **constructor parameters**, not Quasar props. Using `.props("color=grey-7")` bypasses the NiceGUI element's color management and may not work correctly (the `BackgroundColorElement` base class manages color through its own `color` attribute). While `.props()` might technically pass the value to Quasar, it is an anti-pattern that skips NiceGUI's internal state tracking.

### Corrected Approach

```python
ui.badge(f"{chunk.char_count:,} chars", color="grey-7")
ui.badge(f"~{chunk.estimated_tokens:,} tokens", color="primary")
```

For category-colored badges (e.g., in the color legend):

```python
for category in ChunkCategory:
    hex_color = CATEGORY_COLORS[category]
    text_color = CATEGORY_TEXT_COLORS[category]
    ui.badge(
        category.value.replace("_", " ").title(),
        color=hex_color,
        text_color=text_color,
    )
```

---

## Issue 4: `ui.table` Click Handler Pattern is Incomplete

**Severity: BUG**

### Original Plan (Section 8.6, line ~843)

The plan says "Clickable `ui.table` in right panel. Clicking a row navigates to that iteration" but provides no code for how to wire the click handler.

### What's Wrong

NiceGUI's `ui.table` does not have an `on_row_click` constructor parameter. Row clicks must be registered using the `.on()` method with the Quasar event name `'rowClick'`. The `args` parameter controls which JavaScript event arguments are forwarded to the Python handler. Without this knowledge, the implementer will likely try `.on_click()` or `on_row_click=` and fail.

### Corrected Approach

```python
def build_iteration_breakdown_table(
    iterations: list[IterationData],
    current_iter: int,
    on_row_click: Callable[[int], None],
):
    columns = [
        {"name": "iter", "label": "Iter", "field": "iter", "align": "left"},
        {"name": "input", "label": "Input Tokens", "field": "input", "align": "right"},
        {"name": "output", "label": "Output Tokens", "field": "output", "align": "right"},
        {"name": "workers", "label": "Workers", "field": "workers", "align": "right"},
    ]
    rows = []
    for it in iterations:
        total_in = it.reasoning_input_tokens + it.worker_input_tokens
        total_out = it.reasoning_output_tokens + it.worker_output_tokens
        worker_count = len(it.worker_windows)
        rows.append({
            "iter": it.iteration_index,
            "input": f"{total_in:,}",
            "output": f"{total_out:,}",
            "workers": str(worker_count) if worker_count > 0 else "-",
        })

    table = ui.table(
        columns=columns,
        rows=rows,
        row_key="iter",
        selection="single",
    )

    # Wire row click via Quasar's rowClick event
    # args: [[], ['iter'], None] means:
    #   arg[0] (evt): pass nothing
    #   arg[1] (row): pass only 'iter' field
    #   arg[2] (index): pass everything
    def handle_row_click(e):
        if e.args and len(e.args) >= 2:
            iter_index = e.args[1].get("iter", 0)
            on_row_click(iter_index)

    table.on("rowClick", handle_row_click, [[], ["iter"], None])

    return table
```

**Key point**: The `args` parameter to `.on()` is critical -- it controls which properties of each JavaScript event argument are serialized to Python. Without it, the handler receives the full DOM event which is wasteful and may not contain the row data.

---

## Issue 5: `@ui.refreshable` Defined at Module Level Shares State Across All Clients

**Severity: ANTI-PATTERN**

### Original Plan (Section 8.2, line ~734)

```python
@ui.refreshable
def chunk_detail_section():
    chunk = controller.state.selected_chunk
    ...
```

### What's Wrong

If `@ui.refreshable` is defined at module level (global scope), all browser clients share the same refreshable instance. When one user navigates, it refreshes the panel for every connected user. In a dashboard that could have multiple browser tabs open, this creates cross-session interference.

The plan's component hierarchy implies these are top-level functions (`reasoning_chart_section()`, `worker_charts_section()`, `chunk_detail_section()`). If defined at module scope with `@ui.refreshable`, they will be shared.

### Corrected Approach

Define refreshable functions **inside** the `@ui.page` handler or as methods of a per-page class:

```python
@ui.page("/dashboard")
def dashboard_page():
    controller = DashboardController(loader=DashboardDataLoader())

    # Refreshable defined inside page scope -- each client gets its own instance
    @ui.refreshable
    def chunk_detail_section():
        chunk = controller.state.selected_chunk
        if chunk is None:
            ui.label("Click a segment to view details").classes(
                "text-body2 text-grey-7"
            )
            return
        with ui.card().classes("w-full"):
            ui.label(chunk.title).classes("text-h6")
            # ... rest of the component ...

    @ui.refreshable
    def reasoning_chart_section():
        # ... chart rendering ...
        pass

    @ui.refreshable
    def worker_charts_section():
        # ... worker chart rendering ...
        pass

    # Build page layout using the locally-scoped refreshables
    with ui.element("div").style(
        "display: flex; flex-direction: row; width: 100%; gap: 1.5rem"
    ):
        with ui.element("div").style("flex: 7; min-width: 0"):
            reasoning_chart_section()
            worker_charts_section()
            chunk_detail_section()
```

**Alternative**: Use `@ui.refreshable_method` on a class:

```python
class DashboardUI:
    def __init__(self, controller: DashboardController):
        self.controller = controller

    @ui.refreshable_method
    def chunk_detail_section(self):
        chunk = self.controller.state.selected_chunk
        # ... render ...
```

---

## Issue 6: Double `.style()` Chaining is Unnecessary

**Severity: ANTI-PATTERN**

### Original Plan (Section 6.3, line ~619)

```python
with ui.element("div").style(
    "flex: 7; min-width: 0; display: flex; flex-direction: column"
).style("gap: 1rem"):
```

### What's Wrong

While NiceGUI does support chaining multiple `.style()` calls (they merge rather than overwrite), it is unnecessary and reduces readability. Combining all CSS properties into a single `.style()` call is cleaner and avoids the confusion of "will this overwrite?"

### Corrected Approach

```python
# Combine all styles into one .style() call
with ui.element("div").style(
    "flex: 7; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
):
    reasoning_chart_section()
    worker_charts_section()
    chunk_detail_section()
```

This applies throughout the plan. Every instance of chained `.style()` calls should be consolidated.

---

## Issue 7: `ui.code` Used for Large Text Previews -- Wrong Tool

**Severity: ANTI-PATTERN**

### Original Plan (Section 8.2, line ~747)

```python
ui.code(chunk.text_preview_head).classes("w-full")
# ...
with ui.expansion("Show full text").classes("w-full"):
    with ui.scroll_area().style("height: 400px"):
        ui.code(chunk.full_text).classes("w-full")
```

### What's Wrong

`ui.code` renders content through `ui.markdown` with triple-backtick fencing. It is designed for **code snippets**, not arbitrary text. Problems:

1. **Performance**: `ui.code` processes content through markdown rendering. For large text (LLM responses can be 5,000+ chars), this adds unnecessary overhead.
2. **Content corruption**: Text containing markdown-significant characters (backticks, asterisks, brackets, `#` at line starts) will be interpreted as markdown formatting, corrupting the display.
3. **Language detection**: `ui.code` defaults to Python syntax highlighting. LLM responses, REPL output, and user prompts are not Python code.

### Corrected Approach

Use `ui.code` only for actual code (REPL_CODE chunks with `language='python'`). For all other chunk types, use `ui.html` with a `<pre>` tag for faithful rendering, or `ui.textarea` in readonly mode:

```python
@ui.refreshable
def chunk_detail_section():
    chunk = controller.state.selected_chunk
    if chunk is None:
        ui.label("Click a segment to view details").classes(
            "text-body2 text-grey-7"
        )
        return

    # Determine if this is actual code
    is_code = chunk.category in (ChunkCategory.REPL_CODE,)
    language = "python" if is_code else None

    with ui.card().classes("w-full"):
        ui.label(chunk.title).classes("text-h6")
        with ui.row().style("gap: 0.75rem"):
            ui.badge(f"{chunk.char_count:,} chars", color="grey-7")
            ui.badge(f"~{chunk.estimated_tokens:,} tokens", color="primary")
            if controller.state.current_iteration_data:
                total = controller.state.current_iteration_data.reasoning_input_tokens
                if total > 0:
                    pct = chunk.estimated_tokens / total * 100
                    ui.badge(f"{pct:.1f}%", color="blue-grey-7")

        # Preview: head
        if is_code:
            ui.code(chunk.text_preview_head, language="python").classes("w-full")
        else:
            _render_text_preview(chunk.text_preview_head)

        if chunk.text_preview_tail != chunk.text_preview_head:
            ui.label("...").classes("text-center text-grey-6")
            if is_code:
                ui.code(chunk.text_preview_tail, language="python").classes("w-full")
            else:
                _render_text_preview(chunk.text_preview_tail)

        # Full text expansion
        with ui.expansion("Show full text").classes("w-full"):
            with ui.scroll_area().style("height: 400px"):
                if is_code:
                    ui.code(chunk.full_text, language="python").classes("w-full")
                else:
                    _render_text_preview(chunk.full_text)


def _render_text_preview(text: str):
    """Render arbitrary text faithfully without markdown interpretation."""
    import html as html_mod
    escaped = html_mod.escape(text)
    ui.html(
        f'<pre style="white-space: pre-wrap; word-wrap: break-word; '
        f'font-family: monospace; font-size: 0.85rem; padding: 0.75rem; '
        f'background: var(--q-dark-page, #1d1d1d); color: #e0e0e0; '
        f'border-radius: 4px; margin: 0; overflow-x: auto;">'
        f'{escaped}</pre>'
    ).classes("w-full")
```

---

## Issue 8: Cumulative Chart `markLine` at Wrong Nesting Level

**Severity: BUG (silent -- markLine ignored)**

### Original Plan (Section 8.5, line ~834)

```python
return {
    "tooltip": {"trigger": "axis"},
    "xAxis": ...,
    "yAxis": ...,
    "series": [...],
    "markLine": {  # <-- This is at the top level of the options dict
        "data": [{"xAxis": current_iter}],
        "lineStyle": {"type": "dashed", "color": "#9CA3AF"},
    },
}
```

### What's Wrong

In ECharts, `markLine` is a **series-level** property, not a top-level option. Placing it at the top level of the options dict means ECharts silently ignores it -- the vertical "current iteration" indicator line will never render. The plan already correctly places `markLine` inside the "Cumulative Input" series for worker iteration markers, but then incorrectly places the current-iteration marker at the top level.

### Corrected Approach

Move the current-iteration `markLine` into one of the series:

```python
def build_cumulative_chart_options(
    iterations: list[IterationData], current_iter: int
) -> dict:
    cum_input = []
    cum_output = []
    running_in = 0
    running_out = 0
    for it in iterations:
        running_in += it.reasoning_input_tokens + it.worker_input_tokens
        running_out += it.reasoning_output_tokens + it.worker_output_tokens
        cum_input.append(running_in)
        cum_output.append(running_out)

    worker_iters = [i for i, it in enumerate(iterations) if it.has_workers]

    # Combine both markLines (current iter + worker iters) into one series
    mark_line_data = [
        # Current iteration -- solid grey vertical line
        {
            "xAxis": current_iter,
            "lineStyle": {"type": "solid", "color": "#9CA3AF", "width": 2},
            "label": {"formatter": "current", "position": "end"},
        },
    ]
    # Worker iteration markers -- dashed rose lines
    for wi in worker_iters:
        mark_line_data.append({
            "xAxis": wi,
            "lineStyle": {"type": "dashed", "color": "#F43F5E", "width": 1},
            "label": {"show": False},
        })

    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": list(range(len(iterations)))},
        "yAxis": {"type": "value", "name": "Tokens"},
        "series": [
            {
                "name": "Cumulative Input",
                "type": "line",
                "data": cum_input,
                "lineStyle": {"color": "#3B82F6"},
                "itemStyle": {"color": "#3B82F6"},
                "markLine": {
                    "data": mark_line_data,
                    "symbol": "none",
                    "silent": True,
                },
            },
            {
                "name": "Cumulative Output",
                "type": "line",
                "data": cum_output,
                "lineStyle": {"color": "#F97316"},
                "itemStyle": {"color": "#F97316"},
            },
        ],
    }
```

---

## Issue 9: ECharts Click Handler Does Not Identify Individual Chunks

**Severity: ANTI-PATTERN**

### Original Plan (Section 8.2, line ~725)

> On ECharts `on_point_click` event:
> 1. Identify which chunk(s) belong to the clicked category for the current window

### What's Wrong

The plan aggregates all chunks of the same category into a single series data point (line ~695: `total_tokens = sum(c.estimated_tokens for c in category_chunks)`). When there are multiple chunks of the same category (e.g., multiple `REPL_CODE` blocks from different iterations), the click handler receives only the category name via `e.series_name` -- it cannot distinguish *which* REPL_CODE block the user intended.

The `EChartPointClickEventArguments` provides: `component_type`, `series_type`, `series_name`, `name`, `data_index`, `data`, `value`. None of these carry chunk-level identity when multiple chunks are merged.

### Corrected Approach

Either (a) create one series per individual chunk (not per category), or (b) accept the limitation and show a list of all chunks in that category when clicked:

**Option A: One series per chunk (recommended for <=20 chunks)**

```python
def build_context_bar_options(window: ContextWindow) -> dict:
    series = []
    for chunk in window.chunks:
        series.append({
            "name": chunk.chunk_id,  # Unique per chunk
            "type": "bar",
            "stack": "total",
            "data": [chunk.estimated_tokens],
            "itemStyle": {"color": CATEGORY_COLORS[chunk.category]},
            "emphasis": {"itemStyle": {"borderWidth": 2, "borderColor": "#fff"}},
        })
    # ... rest of options ...


# In the click handler:
def on_bar_click(e):
    chunk_id = e.series_name  # Now maps to a specific chunk
    chunk = controller.find_chunk_by_id(chunk_id)
    if chunk:
        controller.select_chunk(chunk)
        chunk_detail_section.refresh()
```

**Option B: Show category summary with sub-chunk list**

```python
def on_bar_click(e):
    category_name = e.series_name
    category = ChunkCategory(category_name)
    chunks = controller.get_chunks_for_category(category)
    if len(chunks) == 1:
        controller.select_chunk(chunks[0])
    else:
        controller.select_chunk_group(chunks)  # Show list in detail panel
    chunk_detail_section.refresh()
```

---

## Issue 10: `ui.select` for Session Selector Missing Key Parameters

**Severity: IMPROVEMENT**

### Original Plan (Section 6.2, line ~580)

```
+-- SessionSelector (ui.select dropdown)
```

The plan does not show the actual `ui.select` code for session selection.

### Corrected Approach

The session selector should use `on_change` (not `on_click` or similar), handle the async loading of a new session, and provide user feedback during loading:

```python
def build_session_selector(
    sessions: list[str],
    current_session: str | None,
    on_session_change: Callable[[str], Awaitable[None]],
):
    async def handle_change(e):
        if e.value and e.value != current_session:
            # Show loading state
            selector.disable()
            ui.notify("Loading session...", type="info")
            try:
                await on_session_change(e.value)
            finally:
                selector.enable()

    selector = ui.select(
        options=sessions,
        value=current_session,
        label="Session",
        on_change=handle_change,
        with_input=True,  # Allow filtering when many sessions exist
    ).classes("w-64")

    return selector
```

**Key points**:
- `value=current_session` sets the initial selection
- `on_change=handle_change` is the correct event parameter
- `with_input=True` enables type-to-filter for long session lists
- Disable during async load to prevent double-selection

---

## Issue 11: No `@ui.page` Decorator -- Route Not Specified

**Severity: IMPROVEMENT**

### Original Plan (Section 10, line ~961)

```bash
python -m rlm_adk.dashboard          # NiceGUI at http://localhost:8080/dashboard
```

The plan says the dashboard is at `/dashboard` but never shows the `@ui.page` decorator or route setup.

### Corrected Approach

```python
# rlm_adk/dashboard/app.py

from nicegui import ui, app


@ui.page("/dashboard")
async def dashboard_page():
    """Main dashboard page -- each browser tab gets its own instance."""
    loader = DashboardDataLoader()
    controller = DashboardController(loader=loader)

    # Initialize available sessions
    controller.state.available_sessions = loader.list_sessions()
    if controller.state.available_sessions:
        await controller.select_session(controller.state.available_sessions[0])

    # Dark mode toggle
    dark = ui.dark_mode(True)

    # Page title
    ui.page_title("RLM Context Window Dashboard")

    # Define refreshable functions in page scope (Issue 5)
    @ui.refreshable
    def reasoning_chart_section():
        # ...
        pass

    @ui.refreshable
    def worker_charts_section():
        # ...
        pass

    @ui.refreshable
    def chunk_detail_section():
        # ...
        pass

    # Build layout...
    build_header(controller, dark)
    build_summary_bar(controller)
    build_navigator(controller, refresh_all=[
        reasoning_chart_section,
        worker_charts_section,
        chunk_detail_section,
    ])

    # Main 70/30 layout
    with ui.element("div").style(
        "display: flex; flex-direction: row; width: 100%; gap: 1.5rem"
    ):
        with ui.element("div").style(
            "flex: 7; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
        ):
            reasoning_chart_section()
            worker_charts_section()
            chunk_detail_section()

        with ui.element("div").style(
            "flex: 3; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
        ):
            build_api_usage_card(controller)
            build_iteration_breakdown_table(controller)
            build_cumulative_chart(controller)

    build_color_legend()

    # Keyboard nav (must be after all elements are created)
    setup_keyboard_nav(controller, refresh_all=[
        reasoning_chart_section,
        worker_charts_section,
        chunk_detail_section,
    ])


def launch_dashboard(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
):
    """Entry point for launching the dashboard."""
    ui.run(
        host=host,
        port=port,
        title="RLM Context Window Dashboard",
        dark=True,
        reload=reload,
    )
```

**Key points**:
- `@ui.page("/dashboard")` registers the route
- `ui.run()` in the launch function starts the server
- Each browser client gets its own page instance (controller + refreshables in local scope)
- `dark=True` in `ui.run()` sets default dark mode

---

## Issue 12: Scroll Area Inside Expansion Needs Explicit Height Guard

**Severity: ANTI-PATTERN**

### Original Plan (Section 8.2, line ~753)

```python
with ui.expansion("Show full text").classes("w-full"):
    with ui.scroll_area().style("height: 400px"):
        ui.code(chunk.full_text).classes("w-full")
```

### What's Wrong

When `ui.expansion` is closed, its children are still in the DOM but hidden. A `ui.scroll_area` with `height: 400px` inside a closed expansion will still reserve layout calculations. When the expansion opens, the scroll area height is correct. However, if the expansion is inside a parent that itself has constrained height, the 400px scroll area may exceed its container. Additionally, per the NiceGUI skill rules, we must ensure the scroll area is inside an explicitly-heightened parent -- the expansion item's content area does not have an explicit height.

### Corrected Approach

Use `max-height` with a flex layout so the scroll area respects both its own maximum and the parent container:

```python
with ui.expansion("Show full text").classes("w-full"):
    # Use max-height instead of height so it does not force 400px
    # when content is shorter. The expansion content area has no
    # explicit height, but max-height works without a parent height.
    with ui.scroll_area().style("max-height: 400px; min-height: 100px"):
        _render_text_preview(chunk.full_text)
```

**Why `max-height` is safe here**: Unlike `height: 100%` (which requires parent explicit height), `max-height: 400px` is an absolute constraint that does not depend on parent sizing. This avoids the NiceGUI height rule violation.

---

## Issue 13: `refresh_all()` Undefined -- Need Explicit Refresh Coordination

**Severity: IMPROVEMENT**

### Original Plan (Section 8.4, line ~771)

```python
controller.navigate(-1)
refresh_all()
```

### What's Wrong

`refresh_all()` is referenced but never defined. With multiple independent `@ui.refreshable` sections, calling `.refresh()` on each one individually is error-prone. The plan needs an explicit refresh coordination pattern.

### Corrected Approach

```python
class DashboardUI:
    """Coordinates UI refresh across multiple refreshable sections."""

    def __init__(self, controller: DashboardController):
        self.controller = controller
        self._refreshables: list[ui.refreshable] = []

    def register(self, refreshable_fn: ui.refreshable):
        """Register a refreshable for coordinated refresh."""
        self._refreshables.append(refreshable_fn)

    def refresh_all(self):
        """Refresh all registered UI sections."""
        for r in self._refreshables:
            r.refresh()


# Usage inside @ui.page:
@ui.page("/dashboard")
async def dashboard_page():
    controller = DashboardController(loader=DashboardDataLoader())
    dashboard_ui = DashboardUI(controller)

    @ui.refreshable
    def reasoning_chart_section():
        # ...
        pass

    @ui.refreshable
    def chunk_detail_section():
        # ...
        pass

    # Register all refreshables
    dashboard_ui.register(reasoning_chart_section)
    dashboard_ui.register(chunk_detail_section)

    # Now keyboard nav has a concrete refresh_all:
    def handle_key(e: KeyEventArguments):
        if not e.action.keydown:
            return
        if e.key.arrow_left:
            controller.navigate(-1)
            dashboard_ui.refresh_all()
        elif e.key.arrow_right:
            controller.navigate(1)
            dashboard_ui.refresh_all()

    ui.keyboard(on_key=handle_key)
```

---

## Issue 14 (Bonus): ECharts `on_point_click` Handler Signature

**Severity: IMPROVEMENT**

### Original Plan

The plan says "On ECharts `on_point_click` event" but does not show the actual `ui.echart` instantiation with the handler wired up.

### Corrected Approach

```python
from nicegui.events import EChartPointClickEventArguments


def build_reasoning_chart(window: ContextWindow, on_click: Callable):
    options = build_context_bar_options(window)

    def handle_point_click(e: EChartPointClickEventArguments):
        # e.series_name is the chunk_id (if using one-series-per-chunk)
        # e.value is the token count
        # e.data_index is the index in the data array
        on_click(e.series_name)

    chart = ui.echart(options, on_point_click=handle_point_click)
    chart.classes("w-full").style("height: 80px")
    return chart
```

**Key points**:
- `on_point_click` is a constructor parameter of `ui.echart`
- The handler receives `EChartPointClickEventArguments` with fields: `series_name`, `name`, `value`, `data_index`, `data`, `component_type`, `series_type`
- Set an explicit `height` on the echart or it may collapse to 0

---

## Consolidated Pattern Reference

### NiceGUI Patterns the Implementation Team MUST Follow

```python
# 1. Gap spacing -- ALWAYS inline, NEVER Tailwind gap-*
with ui.row().style("gap: 0.75rem"):  # CORRECT
with ui.row().classes("gap-3"):        # WRONG (bug #2171)

# 2. Side-by-side charts -- explicit flexbox with min-width: 0
with ui.element("div").style(
    "display: flex; flex-direction: row; width: 100%; gap: 1.5rem"
):
    with ui.element("div").style(
        "flex: 7; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
    ):
        pass  # left panel
    with ui.element("div").style(
        "flex: 3; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
    ):
        pass  # right panel

# 3. ECharts JavaScript expressions -- use ':' prefix on key names
options = {
    "tooltip": {
        ":formatter": "params => params.value + ' tokens'",
    }
}

# 4. Keyboard events -- use property access, filter keydown
def handle_key(e: KeyEventArguments):
    if not e.action.keydown:
        return
    if e.key.arrow_left:
        pass  # handle

# 5. Badge colors -- constructor parameter, not .props()
ui.badge("text", color="primary", text_color="white")

# 6. Table row click -- use .on() with Quasar event name
table.on("rowClick", handler, [[], ["field_name"], None])

# 7. Refreshable scope -- define INSIDE @ui.page, not at module level
@ui.page("/dashboard")
def page():
    @ui.refreshable
    def my_section():
        pass

# 8. ui.code -- only for actual code; use ui.html(<pre>) for text
ui.code("print('hello')", language="python")  # code
ui.html('<pre style="...">plain text here</pre>')  # not code

# 9. Scroll area -- never height:100% in max-height parent
with ui.scroll_area().style("max-height: 400px"):  # safe
    pass

# 10. Style chaining -- combine into single .style() call
ui.element("div").style("flex: 1; min-width: 0; gap: 1rem")  # one call
```
