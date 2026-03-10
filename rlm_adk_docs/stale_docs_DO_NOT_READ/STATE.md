# Current Architecture Summary

The Python code in `~/dev/rlm-adk/rlm_adk` forms a recursive, self-calling agent system built on Google’s Agentic Development Kit (ADK), powered by a single Gemini model via the Gemini API.

The same Gemini instance serves as both parent and child. There are no separate sub-models.

## Core Loop

1. The agent generates Python code inside a live REPL environment.
2. That code can call:

   * `llm_query()` for a single child
   * `llm_query_batched()` for parallel async children
3. An Abstract Syntax Tree (AST) parser detects the call.
4. The REPL pauses at the exact call site.
5. A child agent spins up its own independent REPL.
6. The child runs to completion.
7. The result is returned to the parent.
8. The parent REPL resumes and stitches the result directly into the continuing execution flow.

## Skills Management and Activation

Skills live in a `skills/` folder.

Each skill file contains YAML front matter describing its short description, arguments, and return type. ADK automatically injects this metadata into every model’s context window.

### Code-Based Skills

Skills backed by a Python script are automatically imported into the REPL environment. This means the module is always available for the agent to call from generated code, whether or not the skill is explicitly activated.

The YAML front matter acts like a lightweight function contract or docstring, defining the basic input and output types.

Activating the skill does not make the function callable. It only provides expanded guidance, such as example usage and richer introspection. If the agent already knows how to use the function—either from prior turns or by inferring from the front matter—it can skip activation and call the function directly in REPL code.

### Scriptless Skills

Skills without an accompanying Python script are not imported as modules.

When the agent activates one of these, the skill expands only as structured guidance derived from its YAML front matter.

### Security and Reusability

The model never sees the raw Python implementation of a skill.

Skills are discoverable through front matter and usage examples, but their core implementation remains hidden and reusable.

## Key Tools

### REPL

Every recursion level gets a full live execution environment with:

* mutable state
* execution history
* live Python execution
* access to large context variables for massive datasets

### Structured Output

The parent can declare an expected JSON shape or schema in the query.

The child must match it. If it does not, an automatic retry loop fires.

## Recursive Layers for Massive Context Handling

This architecture, as demonstrated in the original recursive LLM white paper using equivalent `llm_query` functions, supports long-running multi-turn tasks over REPL-injected context exceeding 10 million tokens, far beyond any single LLM context window.

### How it works

* The parent model never loads the full massive dataset into its own context window.
* Instead, the parent uses generated code to probe the REPL, for example through `grep` or other targeted queries, and identify relevant areas.
* The parent then explicitly constructs a context variable for a specific `llm_query()` or `llm_query_batched()` call.
* Only the selected chunks, files, or text strings are loaded into the child’s REPL environment.
* Those tokens never enter the parent’s context window.

### Child output isolation

A critical design feature is that the child’s standard output (`stdout`) and standard error (`stderr`) do **not** automatically flow into the parent’s context window.

Instead, the parent explicitly decides what it will receive back. By writing targeted `print()` statements directly into the code it submits to the child, the parent defines the exact return payload, such as:

* a specific string
* a dictionary
* another structured Python object

Only those explicitly requested objects are passed back into the parent’s next invocation context.

### Result

This prevents context-window explosion and context rot in the parent, even when child agents process millions of tokens.

The parent stays lightweight and remains fully in control of what it observes.

## Prompting and Instructions (ADK-Specific)

All models, parent and child at every recursion depth, receive the exact same `static_instruction` parameter.

This is a fixed, cacheable block that describes what the model has access to:

* the REPL environment
* the `llm_query()` and `llm_query_batched()` functions
* the available skills

It also points the model to a context variable inside the REPL environment that it can probe at any time.

Large-context problems or massive datasets are uploaded directly into the REPL, never into the model’s token window, and become accessible through that REPL context variable.

### Dynamic instructions

The separate `instructions` parameter, which is the dynamic instruction slot, is currently empty.

This is the fully state-injectable layer. It can receive:

* depth-aware state variables
* task-specific configuration
* user-query-specific instructions
* runtime topology selection

At present, that capability is not yet being used.

## Artifact Service

ADK provides a built-in `FileArtifactService` that persists versioned files to disk under `.adk/artifacts/users/{user}/sessions/{session}/artifacts/`. RLM-ADK wraps this with helper functions in `rlm_adk/artifacts.py` that handle graceful degradation (no artifact service configured), tracking metadata, and consistent naming conventions.

### Active Artifact Pipelines

| Artifact | Naming Convention | Written By | Trigger |
|----------|-------------------|------------|---------|
| Submitted REPL code | `repl_code_iter_{N}_turn_{M}.py` | `REPLTool.run_async()` via `save_repl_code()` | Every `execute_code` tool call |
| Aggregated REPL traces | `repl_traces.json` | `REPLTracingPlugin` | End of run |
| Final answer | `final_answer.md` | Orchestrator via `save_final_answer()` | Final answer detected |

### Wiring

`REPLTool.run_async()` calls `await save_repl_code(tool_context, iteration, turn, code)` immediately after receiving the submitted code, before execution begins. This means the code is persisted even if execution fails, is cancelled, or hits the call limit.

The artifact service is independent of the state-based observability path. Both fire on every tool call:

* **State path**: `tool_context.state[REPL_SUBMITTED_CODE_*]` keys flow through `SqliteTracingPlugin` into `session_state_events` in `traces.db`.
* **Artifact path**: `save_repl_code()` writes a `.py` file through ADK's `FileArtifactService` to disk.

### Available but Unwired Helpers

The following helpers in `rlm_adk/artifacts.py` are fully implemented and tested but not yet called from production code paths:

| Helper | Purpose |
|--------|---------|
| `save_repl_output()` | Persist stdout/stderr as `repl_output_iter_{N}.txt` |
| `save_repl_trace()` | Persist per-block trace as `repl_trace_iter_{N}_turn_{M}.json` |
| `save_worker_result()` | Persist worker responses as `worker_{name}_iter_{N}.txt` |
| `save_binary_artifact()` | Generic binary artifact persistence |
| `load_artifact()` | Load artifact by filename and optional version |
| `list_artifacts()` | List all artifact keys in current session scope |
| `delete_artifact()` | Delete artifact and all versions |

### Tracking Metadata

Every `save_*` call updates session state via `_update_save_tracking()`:

* `ARTIFACT_SAVE_COUNT` — incremented per save
* `ARTIFACT_TOTAL_BYTES_SAVED` — cumulative byte count
* `ARTIFACT_LAST_SAVED_FILENAME` — most recent filename
* `ARTIFACT_LAST_SAVED_VERSION` — most recent version number

`load_artifact()` increments `ARTIFACT_LOAD_COUNT`.

### Disk Layout

```
.adk/artifacts/users/{user_id}/sessions/{session_id}/artifacts/
  repl_code_iter_1_turn_0.py/
    versions/0/repl_code_iter_1_turn_0.py
  repl_traces.json/
    versions/0/repl_traces.json
  final_answer.md/
    versions/0/final_answer.md
```

Each artifact is versioned. Subsequent saves to the same filename create new version directories (0, 1, 2, ...).

## Known Limitations and Opportunities

### API rate-limit and concurrency issue

`llm_query_batched()` launches multiple async children against a single Gemini API endpoint. That creates excessive retries and rate-limit errors.

A single-endpoint setup cannot sustain that degree of parallel load.

### Unoptimized prompting

Static instructions are minimal and fixed.

The dynamic instruction channel is unused, so there is currently:

* no runtime state injection
* no task-specific priming
* no topology shaping

### High-leverage future opportunity: dynamic instruction injection

Using ADK callbacks such as:

* `before_agent_callback`
* `before_model_callback`

the system can inspect the incoming user query before it reaches the model.

From there, it can dynamically:

* prime relevant skills
* inject state variables
* assign depth-aware keys
* select runtime topology

The callback mechanism and dynamic instruction slot are neutral tools. They do not force any specific topology, but they make advanced control possible.

## Possible Topologies

Any topology can be implemented through the dynamic `instructions` parameter and callbacks.

The following three patterns are explicitly supported and can be mixed as needed.

### Horizontal

The parent REPL expands sequentially across many turns in its own loop, without increasing recursion depth.

### Vertical / Recursive

The parent minimizes its own turns and delegates phases to one or more LLM query calls, either single or batched, deeper in the recursion tree.

### Hybrid

The parent runs a horizontal loop across multiple iterations per phase, synthesizing results and manipulating the REPL or repo, while also spawning recursive sub-agents vertically at specific nodes for deeper exploration.

Before the parent submits a structured output to move into the next phase, it can—and often should—perform multiple parent turns to integrate, refine, and synthesize everything returned by the recursive layers.

## Guiding Principles for Reflection

### Polya topology reference

Any model reading this architecture should reason through George Polya’s framework from *How to Solve It*:

1. Understanding
2. Planning
3. Implementation
4. Reflection

This should operate as a tight, fast loop with many small cycles.

More cycles strengthen the understanding phase, and that stronger understanding propagates through the rest of the workflow.

### Brett Victor reference: *Inventing on Principle*

Extremely fast feedback on every change is essential for both human users and agents.

That speed helps capture fleeting inventive ideas and makes implementation immediately visible.

This principle should shape the observability framework, either:

* as a dedicated agentic overlay, or
* directly inside Polya’s reflection stage

In the stronger version, reflection covers not only the quality of the problem solution, but also the system’s own responsiveness, visibility, and performance.

---

# Condensed Interpretation

## What this architecture really is

This is a recursive REPL-first agent system where the model writes code, uses code to inspect large external state, and delegates focused subproblems to child agents without polluting the parent’s context window.

## What makes it powerful

* One model can act as both orchestrator and worker.
* Massive context can be processed outside the token window.
* Parent visibility into child work is tightly controlled.
* Skills remain callable without exposing implementation.
* Structured outputs make recursive delegation more reliable.

## What is currently underused

The biggest unused lever is dynamic instruction injection through ADK callbacks and runtime state shaping. That is where topology control, depth-aware behavior, and real task-specific priming can be added.

