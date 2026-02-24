# Product Thinking for UI Development

## Product Understanding Before Code

**ALWAYS ask these questions before building UI features:**

1. What is the user trying to accomplish?
2. What is the user's workflow?
3. Where else in the UI does similar data/functionality exist?
4. Should this be a reusable component?

```
BAD: "I need to show a prompt here, let me build a card"
   -> Results in 5 different prompt cards across the codebase

GOOD: "Where else do we show prompts? Library tab, drip editor,
   version history, compare dialog. I should build ONE component."
```

## Component-First Thinking

**When building UI that displays data:**

1. Search for existing similar displays in the codebase
2. If >1 place shows the same data type, CREATE A COMPONENT
3. Design components with modes (e.g., "LIBRARY" vs "REFERENCE")
4. Never copy-paste UI code - extract and reuse

**Warning Signs You're Violating This:**
- Copy-pasting a `ui.card()` structure from another file
- Writing the same tabs (Preview/Raw) in multiple places
- Different button layouts for same actions in different locations

## The "Same Data, Same Face" Rule

**If the same data type appears in multiple places, it MUST:**

1. **Look the same** - Same icon, typography, color coding
2. **Behave predictably** - Expand works the same, copy works the same
3. **Be navigable** - References should link to source
4. **Use ONE component** - With modes for context-specific behavior

**The user should think "oh, that's a prompt" regardless of where they see it.**

## Data Display Component Checklist

**Use this EVERY TIME building UI to display data:**

```markdown
## Data Type: [e.g., Prompt, Drip, Campaign]

### All Display Locations
- [ ] List every place this data appears
- [ ] Include: library views, editors, version history, previews, dropdowns

### User Flow
- [ ] Can user navigate FROM reference TO source?
- [ ] Can user navigate FROM source TO usages?

### Actions by Context
| Location | View | Copy | Edit | Delete | Navigate |
|----------|------|------|------|--------|----------|
| Library  |  Y   |  Y   |  Y   |   Y    |    -     |
| Editor   |  Y   |  Y   |  -   |   -    |    Y     |
| Preview  |  Y   |  -   |  -   |   -    |    -     |

### Component Design
- Name: `[DataType]Reference` or `[DataType]Card`
- Modes: LIBRARY, REFERENCE, PREVIEW, etc.
- Shared visual elements: icon, name style, preview text
- Mode-specific elements: action buttons, navigation
```

## Modal/Dialog Button Docking

**Primary action buttons in modals MUST be always visible:**

1. **Dock to top** - For dialogs where user needs to see content while deciding
2. **Dock to bottom** - For form dialogs where user fills in then submits

**Why:** Users should NEVER scroll to find Save/Cancel buttons.

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
        with ui.row().classes("justify-end"):
            ui.button("Cancel", on_click=dialog.close)
            ui.button("Save", on_click=save_handler)
```

**Modal Checklist:**
- [ ] Can user see Save/Cancel without scrolling?
- [ ] Are action buttons in consistent position?
- [ ] Does content scroll independently of action bar?
- [ ] Is there visual separation (border) between content and actions?

## Case Study: The Prompt Display Disaster

### What Happened
Built THREE different UIs for displaying prompts:
1. `PromptContentCard` - for Library tab
2. Dropdown + expansion - for Drip Editor
3. `_build_prompt_expansion` - for Version History

**Result:** User couldn't:
- Navigate from drip editor to prompt source
- Copy prompt content where they were working
- Recognize "this is a prompt" across contexts

### What Should Have Happened

**Before building the first prompt display:**
```
Q: Where else will prompts appear?
A: Library tab, drip editor, version history, compare dialog, previews

Q: What actions do users need?
A: View content, copy, navigate to source, edit (only in library)

Q: Should this be ONE component with modes?
A: YES - PromptReference(mode=LIBRARY|REFERENCE|PREVIEW)
```

### The Fix
Created unified `PromptReference` component with modes:
- `LIBRARY` - Full card with edit actions
- `REFERENCE` - Compact with navigation to source
- `DEFAULT` - Shows system default with explanation
- `PREVIEW` - Minimal for dropdowns

**One component, consistent everywhere.**
