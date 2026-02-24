---
name: pythonista-nicegui
description: NiceGUI development best practices for Python web UIs. Use when building UI components, fixing layout issues, or working with NiceGUI/Quasar/Tailwind. Triggers on "nicegui", "quasar", "tailwind", "ui.row", "ui.column", "ui.card", "ui.dialog", "gap", "spacing", "layout", "modal", "component", "styling", "flexbox", "chart", or when creating/editing UI code.
---

# NiceGUI Development Best Practices

## Core Philosophy

**Understand the user workflow before building. Same data MUST look the same everywhere. Extract business logic from UI into testable controllers.**

## Critical Rules - Gap Spacing

**NEVER use Tailwind `gap-*` classes in NiceGUI. ALWAYS use inline styles.**

```python
# CORRECT - inline style for gap
with ui.row().classes("items-center").style("gap: 0.75rem"):
    ui.icon("info")
    ui.label("Message")

# WRONG - breaks on Ubuntu (NiceGUI bug #2171)
with ui.row().classes("items-center gap-3"):
    ui.icon("info")
    ui.label("Message")
```

### Gap Conversion Table

| Tailwind | Inline Style | Use Case |
|----------|--------------|----------|
| `gap-1` | `style("gap: 0.25rem")` | Minimal (icon + label) |
| `gap-2` | `style("gap: 0.5rem")` | Small (within groups) |
| `gap-3` | `style("gap: 0.75rem")` | Medium (between elements) |
| `gap-4` | `style("gap: 1rem")` | Large (between sections) |
| `gap-6` | `style("gap: 1.5rem")` | Extra large |

## Critical Rules - Height Issues

**NEVER use `height: 100%` inside a container with only `max-height`.**

```python
# WRONG - causes collapse to 0 height
with ui.card().style("max-height: 80vh"):
    with ui.scroll_area().style("height: 100%"):  # Collapses!
        ui.label("Content")

# CORRECT - use explicit height
with ui.card().style("height: 80vh"):
    with ui.scroll_area().style("height: 100%"):
        ui.label("Content")
```

## Critical Rules - Side-by-Side Layouts

**Use `min-width: 0` on flex children when using charts or wide content.**

```python
# WRONG - panels stack vertically
with ui.row().classes("w-full"):
    with ui.column().classes("flex-1"):
        ui.highchart(options)  # Forces expansion
    with ui.column().classes("flex-1"):
        ui.highchart(options)  # Wraps to next line

# CORRECT - explicit flexbox with min-width: 0
with ui.element("div").style("display: flex; width: 100%; gap: 24px"):
    with ui.element("div").style("flex: 1; min-width: 0"):
        ui.highchart(options)  # Shrinks to fit
    with ui.element("div").style("flex: 1; min-width: 0"):
        ui.highchart(options)  # Side by side
```

## Modal/Dialog Button Docking

**Primary action buttons MUST be always visible - dock to bottom.**

```python
with ui.dialog() as dialog, ui.card().style(
    "height: 85vh; display: flex; flex-direction: column;"
):
    # Scrollable content
    with ui.scroll_area().style("flex: 1; overflow-y: auto;"):
        # ... form content ...

    # Sticky bottom action bar
    with ui.element("div").style(
        "position: sticky; bottom: 0; padding: 1rem; "
        "border-top: 1px solid var(--border-color);"
    ):
        with ui.row().classes("justify-end").style("gap: 0.5rem"):
            ui.button("Cancel", on_click=dialog.close)
            ui.button("Save", on_click=save_handler)
```

## Product Thinking - Component Design

**Before building UI that displays data:**

1. Where else does this data type appear?
2. Should this be ONE component with modes?
3. Can user navigate from reference to source?

```python
# CORRECT - Create reusable component with modes
class PromptReference:
    def __init__(self, prompt, mode: Literal["LIBRARY", "REFERENCE", "PREVIEW"]):
        if mode == "LIBRARY":
            # Full card with edit actions
        elif mode == "REFERENCE":
            # Compact with navigation to source

# WRONG - Copy-paste UI code
# If same data in 2+ places, extract component
```

## UI Architecture - Extract Controllers

**Extract business logic from UI handlers into testable controllers.**

```python
# CORRECT - Controller handles business logic
class PageController:
    async def handle_task_change(self, new_task: str) -> PageUpdate:
        data = await self.fetcher.fetch_data(new_task)
        return PageUpdate.refresh_all(data)

# UI layer is thin
async def on_task_change(e):
    logger.info(f"User selected task: {e.value}")
    update = await controller.handle_task_change(e.value)
    apply_ui_update(update)

# WRONG - Business logic in UI handlers
async def on_task_change(e):
    overview = await service.get_overview()  # Fetching in UI!
    if overview.tasks:
        selected = overview.tasks[0]  # Logic in UI!
    chart.refresh(...)  # All mixed together
```

## Safe Quasar/Tailwind Classes

**These work correctly - no inline style needed:**

- Padding: `q-pa-md`, `q-pa-lg`, `q-pa-sm`
- Margin: `q-mb-md`, `q-mt-md`
- Width: `w-full`, `w-1/2`, `w-auto`
- Flexbox: `items-center`, `justify-between`, `flex-row`
- Colors: `bg-grey-9`, `text-positive`
- Typography: `text-h5`, `text-body1`, `font-bold`

**Requires inline style:**
- Gap spacing: `gap-*` -> `style("gap: Xrem")`

## Checklists

### NiceGUI Styling Checklist

- [ ] No `gap-*` Tailwind classes (use inline style)
- [ ] No `height: 100%` inside `max-height` container
- [ ] Side-by-side layouts use `min-width: 0` on flex children
- [ ] Modal buttons are docked (always visible)

### Data Display Component Checklist

- [ ] Listed ALL locations where this data appears
- [ ] Designed component with modes for each context
- [ ] User can navigate from reference to source
- [ ] Same icon, typography, color coding everywhere

### UI Architecture Checklist

- [ ] Business logic in controller, not UI handlers
- [ ] Data fetching returns Pydantic models
- [ ] All user actions logged at start of handlers
- [ ] UI feedback when actions deferred/blocked

## Reference Files

For detailed patterns:
- [references/nicegui-styling.md](references/nicegui-styling.md) - Gap, height, flexbox patterns
- [references/product-thinking.md](references/product-thinking.md) - Component design, data display
- [references/ui-architecture.md](references/ui-architecture.md) - Controllers, state management

## Related Skills

- For testing UI code, see `/pythonista-testing`
- For type safety, see `/pythonista-typing`
- For pattern discovery, see `/pythonista-patterning`
