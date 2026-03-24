# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

**IMPORTANT: Before starting any task, read `rlm_adk_docs/UNDERSTAND.md` first.** It is the single entrypoint for understanding this codebase. It provides a progressive disclosure index — identify which branch(es) your task touches, then read only the linked doc(s) for those branches. Do not read unrelated documentation files.

## Why This RLM-ADK Exists

RLM-ADK exists to build a durable, executable world model of a domain rather than merely answer isolated prompts. Its purpose is to turn domain understanding into working code, typed objects, and reusable workflows that accumulate over time. In the current architecture, a reasoning agent writes Python into a sandboxed REPL through the `execute_code` tool; that code can call `llm_query()` to recurse into child agents, and recurring patterns can be abstracted into Python functions and objects that later become available for future tasks through imports into the REPL and skill exposure to reasoning agents through Google ADK skill frontmatter  .

At a vision level, this is a **neuro-symbolic architecture**:

* **Neural side**: reasoning agents use LLM calls to interpret, decompose, retrieve, and synthesize.
* **Symbolic side**: durable Python code, typed outputs, state keys, artifacts, functions, and reusable workflow objects progressively encode what the system has learned about a domain.
* **Bridging mechanism**: repeated useful patterns are moved out of one-off reasoning traces and into reusable code and skills, then surfaced back to future reasoning agents through REPL imports and Google ADK skill frontmatter .

In that sense, RLM-ADK is not just an “agent that answers.” It is an agentic system that **learns a domain by writing executable structure about it**.

---

## Vision: From One-Off Reasoning to Reusable World Models

The long-term vision is that a new domain does not begin with ad hoc prompting. It begins with **benchmark creation**.

The primary initiator into a new domain is the construction of an `understand_<domain>` benchmark suite. That benchmark encodes an initial internal world model of how work in that domain proceeds, then deliberately withholds critical details so the agent is evaluated on whether it can detect missing context, identify gaps, and sequence retrieval correctly rather than bluff its way forward. The existing understand-phase benchmark is explicitly designed to measure **insufficiency detection**, **dependency discovery**, and **retrieval sequencing**, not final-answer accuracy .

This benchmark-first approach matters because a strong agent in a new domain should not merely continue with incomplete context. It should halt, name what is missing, explain where it must come from, and retrieve it in the right order. That is the capability the current understand benchmark is built to score .

So the domain-onboarding loop is:

1. start from a benchmark-builder’s internal world model of the domain,
2. seed it through extensive online context retrieval and document gathering,
3. construct an `understand_<domain>` benchmark directory,
4. embed omissions and dependency gaps into cases,
5. evaluate whether the RLM agents detect the holes,
6. convert successful repeated patterns into code, types, helpers, and skills.

That is the architectural path from **retrieval and diagnosis** to **durable symbolic capability**.

---

## Core Architectural Pattern

RLM-ADK is a recursive language-model system built on Google ADK. The orchestrator delegates to a reasoning agent, the reasoning agent calls `execute_code`, and the REPL becomes the main execution surface. Inside submitted code, calls to `llm_query()` or `llm_query_batched()` are AST-rewritten to async child-dispatch calls, so sync code effectively pauses at those call sites until child agents return values. Then parent execution resumes below that line. The orchestrator delegates to ADK’s native tool loop, and that loop ends when the model emits a valid `set_model_response` tool call matching the output schema   .

### High-level flow

```text
RLMOrchestratorAgent
  -> reasoning_agent.run_async(...)
    -> execute_code
      -> REPL code executes
        -> llm_query() / llm_query_batched()
          -> child orchestrator(s)
          -> child result(s) return
      -> REPL continues
    -> set_model_response
      -> typed response returns to initiator
```

This gives the system three important properties:

* reasoning can become executable,
* execution can recursively spawn deeper reasoning,
* useful structures discovered in execution can later be promoted into reusable symbolic assets.

---

## Tools and Their Directional Flow

### 1. `execute_code`: downward movement into the world model

`execute_code` is the primary actuator. It moves the system **downward** from reasoning-agent context into executable Python inside the REPL. The model uses it to probe state, transform documents, build intermediate representations, call helper functions, and stage child queries. `REPLTool` persists submitted code, expands synthetic skill imports, detects `llm_query` calls, executes code, and returns `stdout`, `stderr`, variables, and metadata about whether nested LLM calls occurred .

Directionally:

* **from**: agent context window
* **to**: REPL runtime and its local symbolic workspace

This is the move where abstract reasoning becomes explicit world-model construction.

### 2. `llm_query()` / `llm_query_batched()`: lateral recursive expansion

Inside REPL code, `llm_query()` and `llm_query_batched()` move the system **laterally** from the current code path into child reasoning agents. These calls are detected in source, rewritten by the AST pass, and executed as async child dispatches. The parent REPL pauses until child result values return .

Directionally:

* **from**: current REPL code line and current symbolic context
* **to**: child agent reasoning context at depth+1
* **back to**: the same paused REPL code line as a returned value

This is how the system widens its world model without abandoning the parent execution path.

### 3. `set_model_response`: upward return to the initiator

`set_model_response` is the **upward** path. It is the mechanism by which the reasoning agent stops using `execute_code`, stops extending the local world model for the current task, and returns a typed response to its initiator. The repo’s `ReasoningOutput` schema exists specifically so the model emits a validated `set_model_response` tool call, and ADK’s native loop terminates when that tool call succeeds  .

Directionally:

* **from**: reasoning agent after enough information has been extracted from the world model
* **to**: the initiator of that reasoning run, whether an `RLMOrchestratorAgent` parent, a root orchestration call, or a benchmark harness

This is the path by which the current run’s answer moves upward out of the working world model.

---

## Context Variable: REPL Context vs Agent Context Window

A central architectural distinction in RLM-ADK is the difference between:

1. the **agent context window**, and
2. the **REPL-local symbolic context**.

### Agent context window

The agent context window is what the reasoning agent sees at model invocation time. It is composed from:

* static instruction,
* dynamic instruction,
* skill frontmatter and skill instructions,
* prior tool history,
* prompt-visible chunks and state-derived context that ADK includes in the model request  .

This is the neural planning surface.

### REPL-local symbolic context

The REPL context is a persistent Python namespace with globals, locals, helpers, imported skills, and intermediate variables. It is where domain objects, partial computations, typed results, and executable transformations actually live while a turn is running. `LocalREPL` maintains this namespace; `execute_code` runs inside it; and code may inspect variables, call helpers, and manipulate representations directly .

This is the symbolic working memory.

### Relationship between the two

The agent does not reason over raw domain complexity forever. Instead:

* the **agent context window** decides what code to write,
* the code executes in the **REPL context**,
* the REPL context builds symbolic structure,
* `stdout`, returned values, and selected summaries are surfaced back to the **agent context window**,
* the reasoning agent uses those results to decide whether to call `execute_code` again or finally answer upward through `set_model_response`.

So the context variable effectively oscillates between:

* **neural compression** in the model context window,
* **symbolic expansion** in the REPL,
* **upward typed return** once enough of the world model has been extracted for the current task.

That oscillation is one of the core neuro-symbolic design principles of the system.

---

## Skills and Reusable Abstractions: Where They Actually Belong

Skills are not the upward path.

Skills belong **inside the downward/lateral world-model-building loop**. They are symbolic compressions of recurring patterns that the reasoning agent can invoke while working inside or alongside `execute_code`. They make the REPL stronger, reduce reinvention, and let future runs build on prior abstractions. But they are still part of the mechanism by which the agent explores and manipulates the domain before it answers upward .

RLM-ADK already supports:

* ADK skills with frontmatter and instruction blocks,
* source-expandable REPL skills,
* helper functions injected into the REPL,
* typed result models and structured outputs  .

The intended evolution is:

1. a reasoning agent solves a task by writing code,
2. repeated workflow patterns are recognized,
3. the pattern is abstracted into Python functions, typed objects, or REPL skills,
4. those abstractions become importable in the REPL,
5. their descriptions are shown to future reasoning agents through ADK skill frontmatter,
6. future tasks begin with stronger symbolic machinery available during `execute_code`.

That is the mechanism by which the world model becomes denser, cleaner, and more reusable over time.

---

## Benchmark-First Entry Into New Domains

The preferred entry into a new domain is not “ask the agent a few questions.” It is to build an **understand-phase benchmark** that encodes domain structure and domain omissions.

The existing understand benchmark already follows this pattern:

* it defines a broad objective,
* provides tempting but incomplete context,
* encodes missing artifacts and dependency chains,
* scores whether the agent halts, detects gaps, and sequences retrieval correctly .

Generalized to new domains, the intended pattern is:

```text
benchmark_builder internal world model
  -> broad workflow sketch for domain
  -> extensive online/context retrieval seeding
  -> benchmark case construction
  -> omission of key details / hidden holes
  -> evaluation of agent gap detection
  -> workflow abstraction into reusable code + skills
```

The resulting `understand_<domain>` directory is therefore not just a test set. It is the first scaffold of the domain world model.

---

## Directional Summary

### Downward

**Reasoning Agent -> `execute_code` -> REPL**

* planning becomes code
* code builds symbolic structure
* domain understanding becomes executable

### Lateral

**Paused REPL code -> `llm_query()` / `llm_query_batched()` -> child agents -> returned values**

* unresolved subproblems branch outward
* child agents reason over narrower scopes
* returned results re-enter the parent code path

### Upward

**Reasoning Agent -> `set_model_response` -> initiator**

* enough has been extracted from the current world model
* the agent stops extending the current `execute_code` chain
* a typed response is returned upward to the parent orchestrator, root run, or benchmark harness

---

## In One Sentence

RLM-ADK is a recursive neuro-symbolic agent architecture whose purpose is to enter domains through benchmark-built world models, expand those models through code-writing and retrieval-aware recursive reasoning, compress repeated patterns into reusable symbolic tools for future `execute_code` runs, and ultimately return typed answers upward through `set_model_response` once enough structure has been extracted for the task at hand.


## Build & Run

```bash
# Install dependencies
uv sync

# Run the agent (ADK CLI)
.venv/bin/adk run rlm_adk

# Run with replay fixture
.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk

# Lint
ruff check rlm_adk/ tests_rlm_adk/
ruff format --check rlm_adk/ tests_rlm_adk/
```

## State Mutation Rules (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

Dispatch closures use **local accumulators** + `flush_fn()` to snapshot into `tool_context.state` after each REPL execution.
