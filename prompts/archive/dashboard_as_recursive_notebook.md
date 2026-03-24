Your task is to redesign the NiceGUI live dashboard in `./rlm_adk/dashboard/` so that it visually explains the actual recursive execution flow of RLM-ADK.

Read first:
- `rlm_adk_docs/UNDERSTAND.md`
- `rlm_adk_docs/core_loop.md`
- `rlm_adk_docs/skills_and_prompts.md`
- `rlm_adk_docs/observability.md`

Then inspect:
- `rlm_adk/dashboard/live_app.py`
- `rlm_adk/dashboard/live_controller.py`
- `rlm_adk/dashboard/live_loader.py`
- `rlm_adk/dashboard/live_models.py`
- `rlm_adk/dashboard/components/live_invocation_tree.py`
- any other dashboard components you need

## Architectural truth to visualize

RLM-ADK is a recursive language-model system in which a reasoning agent issues `execute_code`, dropping into a REPL. Inside the submitted sync code, calls to `llm_query()` or `llm_query_batched()` are AST-rewritten into async child-dispatch points. When runtime reaches one of those calls, sync code execution is effectively paused until the child agent or batched child agents complete and return their structured result values. Then the parent REPL resumes execution below that code line. This recursive pattern may repeat at deeper levels. The orchestrator delegates to ADK’s native tool loop, `execute_code` is the actual REPL actuator, and child recursion is produced when code reaches `llm_query()` / `llm_query_batched()` after AST rewriting :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1}.

The dashboard must make this runtime geometry obvious:

- **Downward motion**: reasoning agent -> `execute_code` -> code pane
- **Rightward motion**: paused code line containing `llm_query()` / `llm_query_batched()` -> child reasoning agent pane
- **Leftward motion**: child completion object returns into the paused code line
- **Resumed downward motion**: parent code continues executing below that line
- **Notebook-style output motion**: code cell emits stdout / stderr / result material below the code block, and the transcript continues downward to the next reasoning-agent step

## Primary design goal

Make the REPL code pane the central execution surface and render the run as a scrollable recursive notebook-style transcript.

A viewer should immediately understand:
- which reasoning agent is active
- what code it submitted through `execute_code`
- which lines have already executed
- which line is currently paused on child dispatch
- which child reasoning agent(s) were spawned from that exact line
- what returned from those child agents
- where code execution resumes after the return
- what stdout / stderr / result state emerged below the code block
- how the next reasoning-agent step follows beneath that output in transcript order

## Primary UX model: Recursive Notebook Flow

Design the main dashboard as a scrollable execution transcript inspired by notebook / REPL environments.

The page should read top-to-bottom like a living recursive notebook history.

### Vertical transcript grammar

Render the run as a sequence of stacked cells/blocks:

1. **Reasoning-agent cell**
   - represents a model invocation frame
   - shows agent name, depth, fanout, iteration, model, status, token usage, dynamic instruction summary

2. **Downward execute_code edge**
   - vertical arrow labeled `execute_code`

3. **Code cell**
   - full code pane for the submitted REPL code
   - line numbers
   - executed-line highlighting
   - paused-line highlighting
   - markers on `llm_query()` / `llm_query_batched()` lines
   - toggle between submitted code / expanded code / diff

4. **Rightward recursive breakout(s) from code lines**
   - child reasoning-agent panes appear to the right of the code cell
   - connectors originate from the exact paused code line
   - `llm_query_batched()` fans out to multiple sibling child panes

5. **Leftward child return(s)**
   - child completion objects return into the same paused code line
   - these are shown as leftward connectors carrying compact return payload previews

6. **Output cell below the code cell**
   - render notebook-style outputs below the code block:
     - STDOUT
     - STDERR
     - Child Returns Summary
     - Post-execution result/state summary

7. **Next reasoning-agent cell below output**
   - the transcript continues downward with the next model/agent step in the same lineage
   - this should appear as a new invocation cell, not as a duplicated copy of the previous one

### Key requirement

The main dashboard should feel like a recursive notebook:
- vertical scrolling shows temporal history
- lateral arrows show recursive child dispatch from paused code lines
- child returns land back in the originating code line
- outputs appear below the code cell in notebook tradition

## Core execution layout for each invocation frame

For each selected invocation frame, render this structure:

### 1. Reasoning-agent pane
A compact card showing:
- agent name
- depth
- fanout
- iteration
- model
- status
- token usage
- finish reason
- prompt preview
- dynamic instruction summary
- enabled skills summary

This pane should represent the model-side reasoning node.

### 2. Downward `execute_code` transition
Below the reasoning-agent pane, render a strong vertical connector:
- downward arrow
- clearly labeled `execute_code`

This connector should terminate at the code pane.

### 3. Full code pane below the agent
This is the most important new surface.

Render the code submitted by the reasoning agent in a full presentation pane below the agent pane.

Requirements:
- show line numbers
- show full code, not just a chip
- support toggle between:
  - submitted code
  - expanded code actually executed
  - optional diff view when expansion occurred
- visually mark lines containing `llm_query()` / `llm_query_batched()`
- visually mark lines already executed
- visually mark the currently paused line
- visually distinguish:
  - executed lines
  - paused line
  - not-yet-executed lines

### 4. Rightward child breakout from paused code line
When a code line contains `llm_query()` or `llm_query_batched()`, render a rightward connector that originates from the exact code line.

That connector should:
- begin at the line itself
- be centered vertically on that line
- be labeled with the call type:
  - `llm_query()`
  - or `llm_query_batched()`
- visually communicate that sync code execution is paused at this point

This connector should lead to one or more child reasoning-agent panes or child chips/cards anchored to that line.

### 5. Child reasoning-agent pane
The child pane should visually mirror the parent pane:
- same general construction
- depth+1
- fanout index if applicable
- prompt preview
- token usage
- finish reason
- status
- output preview
- structured output preview when present

If the child itself issues `execute_code`, it should continue the same recursive visual pattern:
- downward arrow labeled `execute_code`
- code pane below it
- possible rightward child breakout from its own paused code line

### 6. Leftward return path
When a child completes, render a leftward connector back to the exact paused code line that spawned it.

This leftward return should carry a compact representation of the returned value:
- final answer preview
- structured output preview
- error state if any
- token/latency details available via tooltip or expand affordance

The dashboard must make it clear that the child result becomes a value at the paused code site.

### 7. Resumed code execution
After the leftward return lands back on the paused line, parent code execution resumes below that line.

The code pane should visually communicate that continuation:
- paused line resolved
- subsequent lines highlighted as executed as runtime proceeds

## Output cell behavior

Follow notebook / REPL tradition by rendering output below the code cell.

Keep these output surfaces distinct:

### STDOUT
Literal printed output from REPL execution.

### STDERR
Exceptions, warnings, or tool/runtime errors.

### Child Returns Summary
Structured return values from child `llm_query()` / `llm_query_batched()` calls that resumed paused lines.

### Post-execution result/state summary
Useful end-of-cell state such as:
- result preview
- variables snapshot
- tool result metadata
- execution summary

These should appear as sections within the output cell below the code block.

## Batched child calls

For `llm_query_batched()`:
- the paused parent code line emits a rightward fanout
- multiple child reasoning-agent panes or chips/cards appear as siblings
- each child shows its fanout index
- each child returns leftward to the same paused line
- the paused line should visually indicate aggregation of results
- parent code resumes only after all expected child returns are complete

## Lateral capability/context surface

In addition to the code-centric flow, expose the current invocation’s lateral context in a way that supports the runtime model.

This should include:
- prompt-visible skills
- dynamic instruction values such as root prompt, repo URL, skill instruction
- synthetic REPL skill expansion metadata if present
- request chunks grouped by category
- state/context items materially shaping the prompt

This can appear as an expandable context strip or side inspector associated with the reasoning-agent pane and/or code pane.

## Child agent drill-down windows

Add support for child reasoning-agent chips/cards that can open dedicated child transcript pages in separate browser windows or tabs.

### Parent transcript behavior

When a code line spawns child agents via `llm_query()` or `llm_query_batched()`:
- render each child as a clickable chip/card near the rightward breakout
- keep the rightward arrow from the paused code line to the child chip/card
- keep the leftward return edge back into the paused code line

Each child chip/card should show:
- child depth
- child fanout index
- status
- token summary
- short prompt or result preview

### Child chip actions

Support at least:
- inline focus / preview
- open dedicated child window

### Dedicated child route

Add a route pattern such as:
- `/live/session/{session_id}/pane/{pane_id}`
- or `/live/session/{session_id}/invocation/{invocation_id}`

This child page should render the selected child invocation as the root of its own transcript view, using the same Recursive Notebook Flow grammar as the main page.

That means the child window mirrors the parent presentation style for:
- reasoning-agent cell
- downward `execute_code`
- code cell
- rightward `llm_query()` breakouts
- leftward returns
- stdout / stderr / result cells
- deeper recursion to depth+2 and beyond

### Child window header

Each child window should clearly indicate lineage in its header.

Render a header badge such as:
- `Parent: d0:froot → Child: d1:f0`
- or equivalent parent-depth/fanout to child-depth/fanout notation

The child page must visually distinguish itself from the top-level layer-0 transcript.

Also include an arrow or lineage badge in the child header that points back to the parent depth/fanout so it is unmistakably a child window, not a root-layer page.

### Window launching behavior

Use browser-safe behavior:
- launch child page in a new window/tab only from explicit user interaction
- do not auto-open windows during live updates
- preserve session and pane/invocation identity in the URL

### Recommended implementation for child pages

Add controller/loader support for resolving a single invocation/pane as a local transcript root.

Possible additions:
- `select_transcript_root(pane_id | invocation_id)`
- transcript derivation rooted at any node, not only global root
- reusable transcript rendering component shared by main page and child page

## Interaction requirements

- `code`, `expanded code`, `stdout`, `stderr`, model output, and child return values should be accessible through compact controls that open richer viewers.
- Clicking a child pane or child chip should focus that child while preserving breadcrumb context back to its originating paused code line.
- Provide a “follow active recursive lineage” mode.
- Make it easy to detect repeated or identical code submissions across iterations.
- Preserve step-mode usefulness if available.
- Use explicit user actions for opening separate child windows/tabs.

## Data/modeling requirements

Preserve the current telemetry backbone where reasonable:
- traces
- telemetry rows
- session state events
- context snapshots
- model outputs

Derive a flow-oriented model on top of that, such as:
- `FlowAgentFrame`
- `FlowCodeExecution`
- `FlowPauseSite`
- `FlowChildDispatch`
- `FlowReturnValue`
- `FlowOutputCell`
- `FlowTranscriptRoot`

The loader/controller layer should derive enough data to support:
- reasoning agent -> `execute_code`
- submitted code
- expanded code
- pause sites for `llm_query()` / `llm_query_batched()`
- mapping from pause site to child invocation(s)
- mapping from child completion back to originating pause site
- running / paused / resumed / completed / errored state
- transcript roots for both the main session and child-window drill-down pages

Approximate line-level mapping is acceptable if exact runtime line tracing does not yet exist, but structure the implementation so exact mapping can be added later.

## Suggested component additions

Consider adding components such as:
- `flow_reasoning_pane.py`
- `flow_code_pane.py`
- `flow_execute_code_arrow.py`
- `flow_llm_pause_edge.py`
- `flow_child_return_edge.py`
- `flow_batched_fanout.py`
- `flow_output_cell.py`
- `flow_transcript.py`
- `flow_frame_stack.py`
- `frame_inspector.py`
- `child_window_header.py`

The current invocation tree can remain as a secondary debug view, but the main UX should be the recursive notebook transcript.

## Recommended page structure

### Main page
- sticky session/run controls at top
- main scrollable Recursive Notebook Flow transcript
- optional context viewer / inspector
- optional legacy structure view or minimap

### Child page
- child-window lineage header
- transcript rooted at selected child pane/invocation
- same rendering grammar as the main page
- optional button/link back to the main session root

## Visual language

Use a consistent semantic style:
- downward `execute_code` arrows = gold / REPL actuation
- rightward child-dispatch edges = cyan/blue
- leftward return edges = green for success, red/pink for failure
- paused code line = strong highlight
- executed lines = completed highlight
- unexecuted lines = neutral
- active frame = visually dominant
- child-window lineage header should clearly distinguish non-root context

## Deliverables

1. Implement the dashboard redesign in `./rlm_adk/dashboard/`.
2. Keep the dashboard runnable through the existing entrypoint.
3. Add or update dashboard documentation describing the new recursive notebook transcript mental model.
4. Keep a legacy invocation-tree or structure/debug view available as a secondary surface if practical.
5. Ensure the redesign still works against replay/provider-fake traces.
6. Add child-window drill-down routing and rendering for child invocations.

## Acceptance criteria

The redesign is successful if a viewer can immediately see:

- the reasoning agent chose `execute_code`
- code became the active execution surface
- a specific `llm_query()` or `llm_query_batched()` line paused sync execution
- that paused line spawned one or more child reasoning agents to the right
- child completion objects returned into that exact code site
- code then resumed below that line
- stdout / stderr / child return summaries appear below the code cell in notebook fashion
- the transcript continues downward to the next reasoning-agent step
- any child chip can open a dedicated child page/window
- that child page clearly shows parent lineage and renders the same transcript grammar for deeper recursion

When done, provide:
- a concise architecture summary of the new dashboard
- a file-by-file change summary
- any tradeoffs or remaining gaps