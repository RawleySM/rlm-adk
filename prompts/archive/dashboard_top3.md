# Top Three Dashboard Upgrades for Interactivity

## Summary

The current `/live` dashboard is strong on inspection: recursive invocation blocks, context chips, iteration rails, REPL outputs, and a shared text viewer. It is still mostly read-only. The three highest-leverage upgrades from `ai_docs/NiceGUI_agent_dashboard_ideas.md` are the ones that convert inspection into steering:

1. **Context Steering Panel**
2. **Artifact Workbench**
3. **Checkpoint Compare + Resume**

These are the best fit because they build directly on the existing invocation tree and viewer instead of adding parallel UI concepts that bypass the dashboard.

## Key Updates

### 1. Context Steering Panel

Turn the current context display from passive chips into an editable memory/control surface.

- Add a right-side or slide-over panel for the selected invocation with all active context items grouped as:
  `Included`, `Pinned`, `Suppressed`, `Editable`
- Clicking a context chip should support actions:
  `Inspect`, `Pin to descendants`, `Exclude from next turn`, `Edit value`
- Edited values should stage into a per-invocation draft, not mutate persisted trace history
- Add a clear CTA on each invocation block:
  `Run next turn with staged context`
- Default behavior:
  context edits apply only to the selected invocation and its future descendants, not siblings or ancestors
- Use the existing shared viewer as the editing surface for long text values
- Add visual state to chips:
  pinned, suppressed, edited, inherited

Why this is top-1:

- It uses the dashboard’s strongest existing primitive, the context chip system
- It directly implements the “God mode” and “direct manipulation” ideas from the doc
- It turns the dashboard into a steering console without needing new agent architecture first

### 2. Artifact Workbench

Upgrade REPL/code inspection into an editable, runnable workspace for what the agent is building.

- Replace the current text-only `code/stdout/stderr` popup flow with a dedicated workbench pane for the selected invocation
- The workbench should include:
  `Code editor`, `Rendered preview`, `Stdout`, `Stderr`, `Apply patch to next turn`
- For code-producing invocations, show the parent submitted code in an editor instead of a static popup
- For structured outputs or config-like payloads, auto-render editable forms when the payload is dict-like
- For NiceGUI/UI-producing code, provide a sandbox render area inside the dashboard
- Default behavior:
  user edits do not rewrite source files directly; they become staged inputs for the next `execute_code()` or next invocation turn
- Add explicit actions:
  `Accept as next input`, `Discard edits`, `Re-run subtree from here`

Why this is top-2:

- The doc’s “App within an App” and “Two-way collaborative editing” ideas match your use case closely
- Your dashboard already exposes the code lineage; this makes it manipulable
- It creates a direct loop between generated artifact and user correction

### 3. Checkpoint Compare + Resume

Promote iteration rails from simple navigation into branching checkpoints with compare and resume.

- Extend each invocation’s `|1|2|3|` rail into checkpoint controls:
  `View`, `Compare`, `Resume from here`
- Add compare mode for two checkpoints or sibling branches:
  context diff, code diff, stdout/stderr diff, child subtree diff
- Add a timeline scrubber at the session level to move the whole visible tree to a prior checkpoint window
- Default behavior:
  resuming from a checkpoint creates a new forward branch; it does not overwrite historical trace state
- When a child branch is resumed, only that subtree diverges; ancestors remain fixed
- Add a “ghost preview” mode for sibling branches:
  show 2-3 candidate child branches side-by-side before the user commits to one

Why this is top-3:

- The dashboard already models recursive iterations and subtree-local selection
- This is the cleanest way to add Bret Victor-style “see alternatives, then choose” behavior
- It preserves traceability while making the dashboard operational

## Test Plan

- Loader/controller tests for staged context overlays:
  pinned, suppressed, edited, inherited precedence
- Invocation tree tests for subtree-only effects:
  editing or resuming a child affects only that child and its descendants
- UI tests for workbench behavior:
  opening code in editor, staging edits, discarding edits, switching invocations without stale state bleed
- Compare-mode tests:
  diffing two iterations of the same invocation and two sibling branches
- Acceptance scenarios:
  user suppresses a context key and runs next turn
  user edits parent code and re-runs the subtree
  user compares child iteration 1 vs 2 and resumes from 1 into a new branch

## Assumptions

- The dashboard remains a live orchestration surface on `/live`, not just a post-hoc report
- Historical trace data stays immutable; all user interaction creates staged overlays or new branches
- Existing shared viewer, invocation tree, and session metadata remain the base interaction model
- Token streaming is useful but not top-3 for this goal because it improves observability more than manipulability
