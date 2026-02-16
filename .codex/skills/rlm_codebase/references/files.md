# Files

## File: prompts/rebuild_rlm_codebase_with_adk.md
````markdown
Below is a **drop-in master prompt** you can give to a documentation-drafting LLM/agent to produce a rebuild guide for `alexzhang13/rlm` on top of **google-adk (adk-python)**, with heavy emphasis on **callbacks, plugins, and `session.state` key-value design**.

---

## MASTER PROMPT: “Rebuild `rlm` on Google-ADK”

You are a **software documentation agent**. Your job is to draft **rebuild-grade software documentation** for porting an existing GitHub codebase to a new core dependency.

### 0) Inputs (read these first)

* Codebase: `alexzhang13/rlm` (Recursive Language Models inference library) ([GitHub][1])
* New core dependency: Google **Agent Development Kit (ADK) for Python** docs:

  * Callbacks design patterns & best practices ([Google GitHub][2])
  * Plugins + plugin callback hooks ([Google GitHub][3])
  * Sessions / State (`session.state`) ([Google GitHub][4])
  * Types of callbacks (before/after agent/model/tool) ([Google GitHub][5])

### 1) Your deliverable

Produce a **single, cohesive “Port & Rebuild Guide”** that would allow an engineering team to:

1. Understand the current `rlm` architecture and its execution lifecycle
2. Design an ADK-native architecture that preserves core behavior
3. Implement the rebuild with **ADK callbacks + plugin callbacks + state key-value pairs** as the primary control/observability surface
4. Validate parity (functional + behavioral + performance) and provide migration steps

Write as if this is the canonical doc in the repo: **clear, prescriptive, and complete**.

---

## 2) Ground-truth summary of the current `rlm` system (you must base on repo facts)

Explain the existing architecture at a level sufficient to port it:

### 2.1 Core concepts to capture

* RLM replaces `llm.completion(...)` with `rlm.completion(...)` and offloads context into a REPL environment; the LM can recursively call itself via the environment. ([GitHub][1])
* Default environment is a **local REPL** (same process, `exec`, shares host venv) and there are **isolated environments** (e.g., cloud sandboxes) with different comms patterns. ([GitHub][1])
* The repo’s “environment ↔ LM handler communication” includes a host `LMHandler` TCP server, length-prefixed JSON requests, and an HTTP broker pattern for isolated sandboxes. ([GitHub][6])
* Clients and environments are extensible via base classes (`BaseLM`, `NonIsolatedEnv`, `IsolatedEnv`) and registry patterns. ([GitHub][6])
* Dependencies indicate multi-provider LLM backends (OpenAI, Anthropic, Google GenAI, etc.). ([GitHub][7])

### 2.2 What NOT to do

Do not invent modules/classes that are not in the repo. If you’re unsure, say “unspecified in source” and proceed with an assumption clearly labeled.

---

## 3) Target architecture: ADK-first rebuild (this is the heart of the doc)

Your documentation must propose an ADK-native design that emphasizes:

### 3.1 A callback-driven control plane

Use ADK callback patterns explicitly:

* Guardrails & policy enforcement via `before_model_callback` / `before_tool_callback` that can block or short-circuit. ([Google GitHub][2])
* Dynamic state management via `callback_context.state` / `tool_context.state` with changes tracked into `Event.actions.state_delta` and persisted by `SessionService`. ([Google GitHub][2])
* Logging/monitoring and caching patterns as first-class callback responsibilities. ([Google GitHub][2])
* Conditional skipping of steps (show how this replaces ad-hoc branching). ([Google GitHub][2])

### 3.2 Plugins vs local callbacks (you must delineate crisply)

Explain and enforce the hierarchy:

**Plugins (global, Runner-registered):**

* Apply globally to every agent/tool/model in a Runner. ([Google GitHub][3])
* Execute **before** object-level callbacks; plugin return values can short-circuit and skip downstream callbacks. ([Google GitHub][3])
* Support modes: observe (no return), intervene (return value short-circuits), amend (mutate context). ([Google GitHub][3])

**Agent/Model/Tool callbacks (local, instance-configured):**

* Apply only to that specific instance. ([Google GitHub][3])

### 3.3 State as the backbone (`session.state`)

Your guide must include a **state taxonomy** and rules:

* State is a key-value scratchpad per session; keys are strings; values must be serializable; persistence depends on the SessionService. ([Google GitHub][4])
* Use prefix scoping conventions and explain why:

  * `user:` cross-session per user
  * `app:` global per app
  * `temp:` invocation-scoped (discarded after invocation) ([Google GitHub][4])
* Explicitly warn against modifying `session.state` outside callback/tool contexts; prefer context-based state updates or `EventActions.state_delta`. ([Google GitHub][4])

---

## 4) Required documentation sections (write them all)

Your output MUST contain these sections, in this order:

### A. Executive intent

* What behavior is preserved from `rlm`
* What changes because ADK becomes the execution substrate
* What “done” means (parity criteria)

### B. Current system map (from `rlm`)

* Lifecycle: prompt → REPL load → code exec → subcalls → final response
* Environment types (non-isolated vs isolated) and comms models (TCP vs broker) ([GitHub][6])
* Extensibility points: LM clients, environments, registries ([GitHub][6])

### C. ADK rebuild architecture

* Component diagram in text (no images required)
* Runner + SessionService choices and what they imply for persistence ([Google GitHub][4])
* How RLM recursion maps onto ADK agent composition (e.g., parent agent orchestrating sub-agent calls); explain invocation scoping for `temp:` keys when sub-agents are used. ([Google GitHub][4])

### D. Callback & Plugin plan (the “porting contract”)

Provide:

1. A **Plugin suite** (global cross-cutting concerns)
2. A **Local callback suite** (per-agent/tool specifics)

For each item include:

* Name
* Trigger points (before/after agent/model/tool; plugin hooks)
* What it reads/writes in `state`
* What it logs/exports (observability)
* Failure behavior (short-circuit vs escalate)

Use ADK’s callback timing definitions (before/after agent and what they’re “for”). ([Google GitHub][5])

### E. State schema: key naming + ownership + lifecycle

Produce a table-like spec (markdown is fine) that includes:

* Key prefix and why
* Which module “owns” writing it (plugin vs local callback vs tool)
* When it is valid (invocation/session/user/app)
* Serialization constraints
* Example values

You MUST include keys for:

* Flow control (e.g., skip flags, recursion depth, stopping conditions)
* Caching (request fingerprints, hit/miss counters)
* Observability (timings, token usage, tool invocation summaries)
* Type validation outcomes (schema pass/fail, error summaries)
* API/messaging integration (request IDs, idempotency keys, last successful call IDs)

### F. Porting the RLM “REPL + LMHandler” concept into ADK

Explain how to express these in ADK terms:

* REPL execution as Tools or tool-like modules
* The LM handler / subcall mechanism as ADK Model calls (and how recursion is represented)
* Where the old TCP/broker patterns fit (if they remain) vs what ADK replaces outright
  Tie each decision to **plugins/callbacks/state** rather than “just code”.

### G. Caching strategy (must be callback-first)

Describe:

* Global cache plugin design that can short-circuit model calls (plugin “intervene” pattern). ([Google GitHub][3])
* Local caches for tool outputs where appropriate
* Cache key design, invalidation, storage backend options
* Telemetry keys in `state` for cache observability

### H. Observability & audit trail

Define:

* Event model: how state changes become `state_delta` and persist via SessionService ([Google GitHub][2])
* What gets logged at plugin level vs local level
* How to trace a single user invocation end-to-end via IDs stored in state

### I. Type validation & safety

Document:

* What must be validated at boundaries (tool args, tool outputs, model I/O envelopes)
* How validation failures are recorded in state and escalated
* “Fail fast, fail loud” guidance compatible with the repo’s culture ([GitHub][6])

### J. API/messaging integration

Specify:

* Where inbound/outbound messaging occurs (Runner input, tool calls, event hooks)
* How to store idempotency keys and request IDs in state
* How plugins enforce auth/policy before tool execution ([Google GitHub][2])

### K. Migration plan

Include:

* Incremental port strategy (thin slice first)
* Parity test plan
* Rollback strategy
* “Definition of done” checklist

---

## 5) Hard constraints (follow these)

* Keep the doc rebuild-grade: someone should be able to implement from it.
* Prefer ADK mechanisms (plugins/callbacks/state) over ad-hoc control flow.
* Do not recommend direct `session.state` mutation outside context-managed lifecycles; explicitly call out the ADK warning. ([Google GitHub][4])
* Every cross-cutting concern must be assigned to **a plugin** unless there’s a strong reason it must be local. ([Google GitHub][3])
* Make a clear distinction between:

  * **Global plugin callback hooks** (Runner registered, precedence) ([Google GitHub][3])
  * **Local callbacks** (agent/model/tool instance) ([Google GitHub][5])
* Do not include implementation code unless explicitly requested; this deliverable is documentation, architecture, and specs.

---

## 6) Output format requirements

* Use Markdown headings and tight, readable structure.
* Include at least:

  * 1 architecture “map” section (text diagram)
  * 1 state schema section (table-like)
  * 1 callback/plugin catalog section (bullet spec or table-like)
  * 1 migration checklist section

End with a short “Next actions” list (max 10 bullets) describing the immediate engineering steps.

---

[1]: https://github.com/alexzhang13/rlm "GitHub - alexzhang13/rlm: General plug-and-play inference library for Recursive Language Models (RLMs), supporting various sandboxes."
[2]: https://google.github.io/adk-docs/callbacks/design-patterns-and-best-practices/ "Callback patterns - Agent Development Kit"
[3]: https://google.github.io/adk-docs/plugins/ "Plugins - Agent Development Kit"
[4]: https://google.github.io/adk-docs/sessions/state/ "State - Agent Development Kit"
[5]: https://google.github.io/adk-docs/callbacks/types-of-callbacks/ "Types of callbacks - Agent Development Kit"
[6]: https://raw.githubusercontent.com/alexzhang13/rlm/main/AGENTS.md "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/alexzhang13/rlm/main/pyproject.toml "raw.githubusercontent.com"
````

## File: .github/workflows/publish.yml
````yaml
name: Publish to PyPI

on:
  release:
    types: [published]

permissions:
  id-token: write

jobs:
  publish:
    name: Build and publish to PyPI
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/project/rlms/
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build dependencies
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
````

## File: .github/workflows/README.md
````markdown
# GitHub Actions Workflows

This directory contains automated workflows for the RLM (Recursive Language Models) project.

## Workflows

### 1. Style (`style.yaml`)
**Purpose**: Code style checking using ruff.

**Triggers**:
- Pull requests (opened, synchronized, reopened)
- Pushes to `main` branch

**What it does**:
- Runs ruff for linting and formatting checks
- Uses configuration from `pyproject.toml`

### 2. Test (`test.yml`)
**Purpose**: Run tests with coverage.

**Triggers**:
- Pull requests
- Pushes to `main` branch

**What it does**:
- Runs tests on multiple Python versions (3.11, 3.12)
- Generates coverage report (terminal output)

**Note**: Tests that require external services (Modal, API keys) are excluded from CI runs. The following test files are skipped:
- `tests/repl/test_modal_repl.py` - Requires Modal authentication
- `tests/clients/` - Requires API keys for external LLM providers

## Setting Up

### Branch Protection
It's recommended to set up branch protection rules for your main branch:
1. Go to Settings → Branches
2. Add a rule for your main branch
3. Enable "Require status checks to pass before merging"
4. Select the CI jobs you want to require (e.g., `lint`, `test`)

## Running Tests Locally

To run tests locally the same way they run in CI:

```bash
# Install dependencies
uv pip install -e .
uv pip install pytest pytest-asyncio pytest-cov

# Run tests (excluding Modal and API-dependent tests)
python -m pytest tests/ -v \
    --ignore=tests/repl/test_modal_repl.py \
    --ignore=tests/clients/

# Run tests with coverage
python -m pytest tests/ -v \
    --ignore=tests/repl/test_modal_repl.py \
    --ignore=tests/clients/ \
    --cov=rlm \
    --cov-report=html
```

## Running Style Checks Locally

```bash
# Install ruff
uv pip install ruff

# Run linting
ruff check .

# Run formatting check
ruff format --check .

# Auto-fix linting issues
ruff check --fix .

# Auto-format code
ruff format .
```

## Customization

### Adding New Python Versions
Edit the `matrix.python-version` in `test.yml` to test on additional Python versions.

### Changing Trigger Conditions
Modify the `on:` section in the workflow files to change when workflows run.

### Adding More Checks
You can extend the workflows to include:
- Type checking with mypy or ty
- Security scanning
- Documentation building
- Package building and publishing
````

## File: .github/workflows/style.yml
````yaml
name: Style

on:
  push:
    branches: [main]
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: |
          uv pip install --system ruff==0.14.10 ty==0.0.1a21

      - name: Run ruff linting
        run: ruff check --config=pyproject.toml .

      - name: Run ruff formatting check
        run: ruff format --check --config=pyproject.toml .

      - name: Run ty type checking
        run: ty check --exit-zero --output-format=concise
````

## File: .github/workflows/test.yml
````yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: |
          uv pip install --system -e .
          uv pip install --system pytest pytest-asyncio pytest-cov

      - name: Run tests
        run: |
          python -m pytest tests/ -v \
            --ignore=tests/repl/test_modal_repl.py \
            --ignore=tests/clients/ \
            --cov=rlm \
            --cov-report=term-missing
````

## File: docs/api/rlm.md
````markdown
---
layout: default
title: RLM Class
parent: API Reference
nav_order: 1
---

# RLM Class Reference
{: .no_toc }

Complete API documentation for the core RLM class.
{: .fs-6 .fw-300 }

## Table of Contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Overview

The `RLM` class is the main entry point for Recursive Language Model completions. It wraps an LM client and execution environment to enable iterative, code-augmented reasoning.

```python
from rlm import RLM

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5"},
)
```

---

## Constructor

```python
RLM(
    backend: str = "openai",
    backend_kwargs: dict | None = None,
    environment: str = "local",
    environment_kwargs: dict | None = None,
    depth: int = 0,
    max_depth: int = 1,
    max_iterations: int = 30,
    custom_system_prompt: str | None = None,
    other_backends: list[str] | None = None,
    other_backend_kwargs: list[dict] | None = None,
    logger: RLMLogger | None = None,
    verbose: bool = False,
)
```

### Parameters

#### `backend`
{: .no_toc }

**Type:** `Literal["openai", "portkey", "openrouter", "vllm", "litellm", "anthropic"]`  
**Default:** `"openai"`

The LM provider backend to use for the root model.

```python
# OpenAI
rlm = RLM(backend="openai", ...)

# Anthropic
rlm = RLM(backend="anthropic", ...)

# Local vLLM server
rlm = RLM(backend="vllm", ...)
```

---

#### `backend_kwargs`
{: .no_toc }

**Type:** `dict[str, Any] | None`  
**Default:** `None`

Configuration passed to the LM client. Required fields vary by backend:

| Backend | Required | Optional |
|:--------|:---------|:---------|
| `openai` | `model_name` | `api_key`, `base_url` |
| `anthropic` | `model_name` | `api_key` |
| `portkey` | `model_name`, `api_key` | `base_url` |
| `openrouter` | `model_name` | `api_key` |
| `vllm` | `model_name`, `base_url` | — |
| `litellm` | `model_name` | varies by provider |

```python
backend_kwargs = {
    "api_key": "sk-...",
    "model_name": "gpt-4o",
    "base_url": "https://api.openai.com/v1",  # Optional
}
```

---

#### `environment`
{: .no_toc }

**Type:** `Literal["local", "modal", "docker"]`  
**Default:** `"local"`

The execution environment for running generated code.

| Environment | Description |
|:------------|:------------|
| `local` | Same-process execution with sandboxed builtins |
| `docker` | Containerized execution in Docker |
| `modal` | Cloud sandbox via Modal |

---

#### `environment_kwargs`
{: .no_toc }

**Type:** `dict[str, Any] | None`  
**Default:** `None`

Configuration for the execution environment:

**Local:**
```python
environment_kwargs = {
    "setup_code": "import numpy as np",  # Run before each completion
}
```

**Docker:**
```python
environment_kwargs = {
    "image": "python:3.11-slim",  # Docker image
}
```

**Modal:**
```python
environment_kwargs = {
    "app_name": "my-rlm-app",  # Modal app name
    "timeout": 600,            # Sandbox timeout in seconds
    "image": modal.Image...,   # Custom Modal image (optional)
}
```

---

#### `max_depth`
{: .no_toc }

**Type:** `int`  
**Default:** `1`

Maximum recursion depth for nested RLM calls. Currently only depth 1 is fully supported.

When `depth >= max_depth`, the RLM falls back to a regular LM completion.

---

#### `max_iterations`
{: .no_toc }

**Type:** `int`  
**Default:** `30`

Maximum number of REPL iterations before forcing a final answer.

Each iteration consists of:
1. LM generates response (potentially with code blocks)
2. Code blocks are executed
3. Results are appended to conversation history

```python
# For complex tasks, allow more iterations
rlm = RLM(
    ...,
    max_iterations=50,
)
```

---

#### `custom_system_prompt`
{: .no_toc }

**Type:** `str | None`  
**Default:** `None`

Override the default RLM system prompt. The default prompt instructs the LM on:
- How to use the `context` variable
- How to call `llm_query()` and `llm_query_batched()`
- How to signal completion with `FINAL()`

```python
custom_prompt = """You are a data analysis expert.
Use the REPL to analyze the context variable.
When done, output FINAL(your answer)."""

rlm = RLM(
    ...,
    custom_system_prompt=custom_prompt,
)
```

---

#### `other_backends` / `other_backend_kwargs`
{: .no_toc }

**Type:** `list[str] | None` / `list[dict] | None`  
**Default:** `None`

Register additional LM backends available for sub-calls via `llm_query()`.

```python
rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    other_backends=["anthropic", "openai"],
    other_backend_kwargs=[
        {"model_name": "claude-sonnet-4-20250514"},
        {"model_name": "gpt-4o-mini"},
    ],
)

# Inside REPL, code can call:
# llm_query(prompt)  # Uses default (gpt-4o)
# llm_query(prompt, model="claude-sonnet-4-20250514")  # Uses Claude
# llm_query(prompt, model="gpt-4o-mini")  # Uses GPT-4o-mini
```

---

#### `logger`
{: .no_toc }

**Type:** `RLMLogger | None`  
**Default:** `None`

Logger for saving iteration trajectories to disk.

```python
from rlm.logger import RLMLogger

logger = RLMLogger(log_dir="./logs")
rlm = RLM(..., logger=logger)
```

---

#### `verbose`
{: .no_toc }

**Type:** `bool`  
**Default:** `False`

Enable rich console output showing:
- Metadata at startup
- Each iteration's response
- Code execution results
- Final answer and statistics

---

## Methods

### `completion()`

Main entry point for RLM completions.

```python
def completion(
    self,
    prompt: str | dict[str, Any],
    root_prompt: str | None = None,
) -> RLMChatCompletion
```

#### Parameters

**`prompt`**
{: .no_toc }

The context/input to process. Becomes the `context` variable in the REPL.

```python
# String input
result = rlm.completion("Analyze this text...")

# Structured input (serialized to JSON)
result = rlm.completion({
    "documents": [...],
    "query": "Find relevant sections",
})

# List input
result = rlm.completion(["doc1", "doc2", "doc3"])
```

**`root_prompt`**
{: .no_toc }

Optional short prompt shown to the root LM. Useful for Q&A tasks where the question should be visible throughout.

```python
# The context is the document, but the LM sees the question
result = rlm.completion(
    prompt=long_document,
    root_prompt="What is the main theme of this document?"
)
```

#### Returns

`RLMChatCompletion` dataclass:

```python
@dataclass
class RLMChatCompletion:
    root_model: str           # Model name used
    prompt: str | dict        # Original input
    response: str             # Final answer
    usage_summary: UsageSummary  # Token usage
    execution_time: float     # Total seconds
```

#### Example

```python
result = rlm.completion(
    "Calculate the factorial of 100 and return the number of digits."
)

print(result.response)          # "158"
print(result.execution_time)    # 12.34
print(result.usage_summary.to_dict())
# {'model_usage_summaries': {'gpt-4o': {'total_calls': 5, ...}}}
```

---

## Response Types

### `RLMChatCompletion`

```python
from rlm.core.types import RLMChatCompletion

result: RLMChatCompletion = rlm.completion(...)

result.root_model      # "gpt-4o"
result.prompt          # Original input
result.response        # Final answer string
result.execution_time  # Total time in seconds
result.usage_summary   # UsageSummary object
```

### `UsageSummary`

```python
from rlm.core.types import UsageSummary

usage: UsageSummary = result.usage_summary
usage.to_dict()
# {
#     "model_usage_summaries": {
#         "gpt-4o": {
#             "total_calls": 5,
#             "total_input_tokens": 15000,
#             "total_output_tokens": 2000
#         }
#     }
# }
```

---

## Error Handling

RLM follows a "fail fast" philosophy:

```python
# Missing required argument
rlm = RLM(
    backend="vllm",
    backend_kwargs={"model_name": "llama"},
)
# Raises: AssertionError: base_url is required for vLLM

# Unknown backend
rlm = RLM(backend="unknown")
# Raises: ValueError: Unknown backend: unknown
```

If the RLM exhausts `max_iterations` without finding a `FINAL()` answer, it prompts the LM one more time to provide a final answer based on the conversation history.

---

## Thread Safety

Each `completion()` call:
1. Spawns its own `LMHandler` socket server
2. Creates a fresh environment instance
3. Cleans up both when done

This makes `completion()` calls independent, but the `RLM` instance itself should not be shared across threads without external synchronization.

---

## Example: Full Configuration

```python
import os
from rlm import RLM
from rlm.logger import RLMLogger

logger = RLMLogger(log_dir="./logs", file_name="analysis")

rlm = RLM(
    # Primary model
    backend="anthropic",
    backend_kwargs={
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "model_name": "claude-sonnet-4-20250514",
    },
    
    # Execution environment
    environment="docker",
    environment_kwargs={
        "image": "python:3.11-slim",
    },
    
    # Additional models for sub-calls
    other_backends=["openai"],
    other_backend_kwargs=[{
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-4o-mini",
    }],
    
    # Behavior
    max_iterations=40,
    max_depth=1,
    
    # Debugging
    logger=logger,
    verbose=True,
)

result = rlm.completion(
    prompt=massive_document,
    root_prompt="Summarize the key findings"
)
```
````

## File: docs/src/app/api/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function APIPage() {
  return (
    <div className="max-w-4xl">
      {/* Hero Section */}
      <div className="mb-12">
        <h1 className="text-5xl font-bold mb-4 tracking-tight">Using the RLM Client</h1>
        <p className="text-xl text-muted-foreground leading-relaxed">
          The main class for recursive language model completions. Enables LMs to programmatically 
          examine, decompose, and recursively call themselves over their input.
        </p>
      </div>

      {/* Quick Example */}
      <div className="mb-12 p-6 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl">
        <h2 className="text-lg font-semibold mb-3 text-foreground">Quick Example</h2>
        <CodeBlock code={`from rlm import RLM

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
)
result = rlm.completion("Your prompt here")
print(result.response)`} />
      </div>

      {/* Constructor */}
      <div className="mb-16">
        <h2 className="text-3xl font-bold mb-6">Constructor</h2>

        <CodeBlock code={`RLM(
    backend: str = "openai",
    backend_kwargs: dict | None = None,
    environment: str = "local",
    environment_kwargs: dict | None = None,
    depth: int = 0,
    max_depth: int = 1,
    max_iterations: int = 30,
    custom_system_prompt: str | None = None,
    other_backends: list[str] | None = None,
    other_backend_kwargs: list[dict] | None = None,
    logger: RLMLogger | None = None,
    verbose: bool = False,
)`} />

        <div className="mt-8 space-y-10">
          {/* backend */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">backend</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">str</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: "openai"</span>
            </div>
            <p className="text-muted-foreground mb-4">LM provider to use for completions.</p>
            <Table 
              headers={["Value", "Provider"]}
              rows={[
                [<code key="1" className="text-sm">"openai"</code>, "OpenAI API"],
                [<code key="2" className="text-sm">"anthropic"</code>, "Anthropic API"],
                [<code key="3" className="text-sm">"portkey"</code>, "Portkey AI gateway"],
                [<code key="4" className="text-sm">"openrouter"</code>, "OpenRouter"],
                [<code key="5" className="text-sm">"litellm"</code>, "LiteLLM (multi-provider)"],
                [<code key="6" className="text-sm">"vllm"</code>, "Local vLLM server"],
              ]}
            />
          </div>

          {/* backend_kwargs */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">backend_kwargs</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">dict | None</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: None</span>
            </div>
            <p className="text-muted-foreground mb-4">Provider-specific configuration (API keys, model names, etc.).</p>
            <CodeBlock code={`# OpenAI / Anthropic
backend_kwargs={
    "api_key": "...",
    "model_name": "gpt-5-mini",
}

# vLLM (local)
backend_kwargs={
    "base_url": "http://localhost:8000/v1",
    "model_name": "meta-llama/Llama-3-70b",
}

# Portkey
backend_kwargs={
    "api_key": "...",
    "model_name": "@openai/gpt-5-mini",
}`} />
          </div>

          {/* environment */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">environment</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">str</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: "local"</span>
            </div>
            <p className="text-muted-foreground mb-4">Code execution environment for REPL interactions.</p>
            <Table 
              headers={["Value", "Description"]}
              rows={[
                [<code key="1" className="text-sm">"local"</code>, "Same-process with sandboxed builtins"],
                [<code key="2" className="text-sm">"docker"</code>, "Docker container"],
                [<code key="3" className="text-sm">"modal"</code>, "Modal cloud sandbox"],
              ]}
            />
          </div>

          {/* environment_kwargs */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">environment_kwargs</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">dict | None</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: None</span>
            </div>
            <p className="text-muted-foreground mb-4">Environment-specific configuration.</p>
            <CodeBlock code={`# Docker
environment_kwargs={"image": "python:3.11-slim"}

# Modal
environment_kwargs={
    "app_name": "my-app",
    "timeout": 600,
}

# Local
environment_kwargs={"setup_code": "import numpy as np"}`} />
          </div>

          {/* max_iterations */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">max_iterations</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">int</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: 30</span>
            </div>
            <p className="text-muted-foreground">Maximum REPL iterations before forcing a final answer.</p>
          </div>

          {/* max_depth */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">max_depth</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">int</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: 1</span>
            </div>
            <div className="mb-2 p-3 bg-amber-50 border border-amber-200 rounded-md">
              <p className="text-sm text-amber-800">
                <strong>Note:</strong> This is a TODO. Only <code className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-900 text-xs font-semibold">max_depth=1</code> is currently supported.
              </p>
            </div>
            <p className="text-muted-foreground">
              Maximum recursion depth. When <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm">depth {">="} max_depth</code>, falls back to regular LM completion.
            </p>
          </div>

          {/* custom_system_prompt */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">custom_system_prompt</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">str | None</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: None</span>
            </div>
            <p className="text-muted-foreground">Override the default RLM system prompt.</p>
          </div>

          {/* other_backends */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">other_backends</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">list[str] | None</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: None</span>
            </div>
            <p className="text-muted-foreground mb-4">Additional backends available for sub-LM calls within the REPL.</p>
            <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    other_backends=["anthropic"],
    other_backend_kwargs=[{"model_name": "claude-sonnet-4-20250514"}],
)`} />
          </div>

          {/* other_backend_kwargs */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">other_backend_kwargs</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">list[dict] | None</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: None</span>
            </div>
            <p className="text-muted-foreground">Configurations for <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm">other_backends</code> (must match order).</p>
          </div>

          {/* logger */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">logger</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">RLMLogger | None</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: None</span>
            </div>
            <p className="text-muted-foreground mb-4">Logger for saving RLM execution trajectories to JSON-lines files.</p>
            <CodeBlock code={`from rlm.logger import RLMLogger

logger = RLMLogger(log_dir="./logs")
rlm = RLM(..., logger=logger)`} />
          </div>

          {/* verbose */}
          <div className="border-l-4 border-blue-500 pl-6">
            <div className="flex items-baseline gap-3 mb-2">
              <code className="text-lg font-semibold text-foreground">verbose</code>
              <span className="text-xs px-2 py-1 rounded-md bg-muted text-muted-foreground font-mono">bool</span>
              <span className="text-xs px-2 py-1 rounded-md bg-blue-100 text-blue-700 font-mono">default: False</span>
            </div>
            <p className="text-muted-foreground">Enable rich console output showing iterations, code execution, and results.</p>
          </div>
        </div>
      </div>

      {/* completion method */}
      <div className="mb-16">
        <h2 className="text-3xl font-bold mb-6">Methods</h2>

        <div className="border-l-4 border-indigo-500 pl-6 mb-8">
          <div className="flex items-baseline gap-3 mb-4">
            <code className="text-2xl font-semibold text-foreground">completion()</code>
          </div>
          <p className="text-muted-foreground mb-4 text-lg">Main method for RLM completions. Executes the recursive loop and returns the final result.</p>
          
          <p className="text-muted-foreground mb-6 leading-relaxed">
            The method returns an <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">RLMChatCompletion</code> object 
            containing the final response, execution metadata, and usage statistics. This object provides access to the RLM&apos;s output and performance metrics.
          </p>
          
          <CodeBlock code={`result = rlm.completion(
    prompt: str | dict,
    root_prompt: str | None = None,
)`} />

          <div className="mt-8">
            <h3 className="text-lg font-semibold mb-4 text-foreground">Arguments</h3>
            <Table 
              headers={["Name", "Type", "Description"]}
              rows={[
                [
                  <code key="1" className="text-sm font-semibold">prompt</code>, 
                  <code key="2" className="text-sm">str | dict</code>, 
                  <span key="5">Input context (becomes <code className="text-xs px-1 py-0.5 rounded bg-muted text-foreground">context</code> variable in REPL)</span>
                ],
                [
                  <code key="3" className="text-sm font-semibold">root_prompt</code>, 
                  <code key="4" className="text-sm">str | None</code>, 
                  "Optional hint visible only to the root LM call"
                ],
              ]}
            />
          </div>

          <div className="mt-8">
            <h3 className="text-lg font-semibold mb-4 text-foreground">Returns</h3>
            <p className="text-muted-foreground mb-4"><code className="px-2 py-1 rounded bg-muted text-foreground text-sm font-semibold">RLMChatCompletion</code> object with:</p>
            <Table 
              headers={["Attribute", "Type", "Description"]}
              rows={[
                [<code key="1" className="text-sm font-semibold">response</code>, <code key="2" className="text-sm">str</code>, "Final answer from the RLM"],
                [<code key="3" className="text-sm font-semibold">execution_time</code>, <code key="4" className="text-sm">float</code>, "Total execution time in seconds"],
                [<code key="5" className="text-sm font-semibold">usage_summary</code>, <code key="6" className="text-sm">UsageSummary</code>, "Aggregated token usage across all LM calls"],
                [<code key="7" className="text-sm font-semibold">root_model</code>, <code key="8" className="text-sm">str</code>, "Model name used for root completion"],
              ]}
            />
          </div>
        </div>
      </div>

    </div>
  );
}
````

## File: docs/src/app/backends/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";

export default function BackendsPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4">Backends</h1>
      
      <p className="text-muted-foreground mb-6">
        <p>
          RLMs natively support a wide range of language model providers, including <code>OpenAI</code>, <code>Anthropic</code>, <code>Portkey</code>, <code>OpenRouter</code>, and <code>LiteLLM</code>. Additional providers can be supported with minimal effort. The <code>backend_kwargs</code> are named arguments passed directly to the backend client.
        </p>
      </p>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">OpenAI</h2>
      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),  # or set OPENAI_API_KEY env
        "model_name": "gpt-5-mini",
        "base_url": "https://api.openai.com/v1",  # optional
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Anthropic</h2>
      <CodeBlock code={`rlm = RLM(
    backend="anthropic",
    backend_kwargs={
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "model_name": "claude-sonnet-4-20250514",
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Portkey</h2>
      <p className="text-muted-foreground mb-4">
        <a href="https://portkey.ai/docs/api-reference/sdk/python" className="text-primary underline font-medium" target="_blank" rel="noopener noreferrer">Portkey</a> is a client for routing to hundreds of different open and closed frontier models.
      </p>
      <CodeBlock code={`rlm = RLM(
    backend="portkey",
    backend_kwargs={
        "api_key": os.getenv("PORTKEY_API_KEY"),
        "model_name": "@openai/gpt-5-mini",  # Portkey format: @provider/model
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">OpenRouter</h2>
      <p className="text-muted-foreground mb-4">
        <a href="https://openrouter.ai/docs" className="text-primary underline font-medium" target="_blank" rel="noopener noreferrer">OpenRouter</a> is a multi-provider gateway for accessing a wide range of models from different providers through one API.
      </p>
      <CodeBlock code={`rlm = RLM(
    backend="openrouter",
    backend_kwargs={
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "model_name": "openai/gpt-5-mini",  # Format: provider/model
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">LiteLLM</h2>
      <p className="text-muted-foreground mb-4">
        <a href="https://docs.litellm.ai/docs/" className="text-primary underline font-medium" target="_blank" rel="noopener noreferrer">LiteLLM</a> is a universal interface for 100+ model providers, with support for local models and custom endpoints.
      </p>
      <CodeBlock code={`rlm = RLM(
    backend="litellm",
    backend_kwargs={
        "model_name": "gpt-5-mini",
    },
)
# Set provider API keys in environment`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">vLLM (Local)</h2>
      <p className="text-muted-foreground mb-4">Local model serving.</p>
      <CodeBlock language="bash" code={`# Start vLLM server
python -m vllm.entrypoints.openai.api_server \\
    --model meta-llama/Llama-3-70b \\
    --port 8000`} />
      <CodeBlock code={`rlm = RLM(
    backend="vllm",
    backend_kwargs={
        "base_url": "http://localhost:8000/v1",  # Required
        "model_name": "meta-llama/Llama-3-70b",
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Multiple Backends (Experimental)</h2>
      <p className="text-muted-foreground mb-4">
        <strong>Experimental:</strong> This feature allows you to specify <em>ordered</em> lists of backends and model kwargs, so that RLMs can sub-call different language models from within execution code. 
        The order of <code>other_backends</code> and <code>other_backend_kwargs</code> must match: e.g., the 0th element of <code>other_backends</code> is used with the 0th dict in <code>other_backend_kwargs</code>.
        <br />
        <br />
        <span className="font-medium">
          This functionality is for advanced use and is currently experimental.
        </span>
        It will become more useful as RLMs get the ability to orchestrate and delegate between different LMs within a workflow.
      </p>
      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    other_backends=["anthropic", "openai"],  # ORDER MATTERS!
    other_backend_kwargs=[
        {"model_name": "claude-sonnet-4-20250514"},
        {"model_name": "gpt-4o-mini"},
    ],  # ORDER MATCHES other_backends
)`} />
      <p className="text-muted-foreground mt-4">Inside REPL (future releases):</p>
      <CodeBlock code={`llm_query("prompt")  # Uses default (gpt-5-mini)
llm_query("prompt", model="claude-sonnet-4-20250514")  # Uses Claude 
llm_query("prompt", model="gpt-4o-mini")  # Uses GPT-4o-mini`} />
    </div>
  );
}
````

## File: docs/src/app/environments/docker/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function DockerPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4 flex items-center gap-3">
        DockerREPL
        <img 
          src="https://github.com/docker.png" 
          alt="Docker" 
          height="24" 
          className="inline-block"
          style={{ height: '24px', verticalAlign: 'middle' }}
        />
      </h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        <strong className="text-foreground">DockerREPL</strong> executes Python code in a <strong className="text-foreground">Docker container</strong> 
        running on the same host machine as the RLM process. Each code execution runs in an isolated container environment 
        with its own filesystem, network namespace, and process tree, providing better security and reproducibility than 
        LocalREPL. The container requests LM calls from the host&apos;s LM Handler when code executes <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">llm_query()</code>. 
        This environment is ideal for CI/CD pipelines, reproducible execution environments, and scenarios requiring stronger 
        isolation than LocalREPL while maintaining the convenience of local execution. For more information on Docker, see the{" "}
        <a href="https://docs.docker.com/" className="text-primary hover:underline font-medium">Docker documentation</a>.
      </p>

      <p className="text-muted-foreground mb-4">
        <strong>Prerequisite:</strong> Docker must be installed and running.
      </p>

      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="docker",
    environment_kwargs={
        "image": "python:3.11-slim",
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Arguments</h2>
      <Table 
        headers={["Argument", "Type", "Default", "Description"]}
        rows={[
          [<code key="1">image</code>, <code key="2">str</code>, <code key="3">&quot;python:3.11-slim&quot;</code>, "Docker image to use"],
          [<code key="4">setup_code</code>, <code key="5">str</code>, <code key="6">None</code>, "Code to run at initialization"],
          [<code key="7">context_payload</code>, <code key="8">str | dict | list</code>, "Auto", "Initial context (set by RLM)"],
          [<code key="9">lm_handler_address</code>, <code key="10">tuple</code>, "Auto", "Socket address (set by RLM)"],
        ]}
      />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">How It Works</h2>
      <ol className="list-decimal list-inside text-muted-foreground space-y-1 mb-6">
        <li>Starts Docker container with volume mount to temp directory</li>
        <li>Installs <code>dill</code> and <code>requests</code> in container</li>
        <li>Host runs HTTP proxy server on random port</li>
        <li>Container calls proxy via <code>host.docker.internal</code></li>
        <li>Proxy forwards <code>llm_query()</code> to LM Handler via socket</li>
        <li>State persisted via <code>dill</code> to <code>/workspace/state.dill</code></li>
      </ol>

      <pre className="text-sm">{`┌────────────────────────────────────────┐
│ Host                                   │
│  ┌────────────┐ Socket ┌────────────┐ │
│  │ HTTP Proxy │◄──────►│ LM Handler │ │
│  └─────┬──────┘        └────────────┘ │
└────────┼───────────────────────────────┘
         │ HTTP
┌────────┼───────────────────────────────┐
│ Docker │ Container                     │
│  ┌─────▼──────┐                        │
│  │   Python   │ llm_query() → proxy    │
│  │   exec()   │                        │
│  └────────────┘                        │
└────────────────────────────────────────┘`}</pre>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Custom Image</h2>
      <p className="text-muted-foreground mb-4">
        You can use your own custom Docker images or update the given image. Pre-install dependencies:
      </p>
      <CodeBlock language="bash" code={`FROM python:3.11-slim
RUN pip install numpy pandas dill requests`} />
      <CodeBlock code={`environment_kwargs={"image": "my-rlm-image"}`} />
    </div>
  );
}
````

## File: docs/src/app/environments/local/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function LocalPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4">LocalREPL</h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        <strong className="text-foreground">LocalREPL</strong> is the default execution environment for RLM. 
        It runs Python code in the <strong className="text-foreground">same process</strong> as the RLM host application, 
        using Python&apos;s built-in <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">exec()</code> function 
        with a sandboxed namespace. The REPL shares the same virtual environment and memory space as the host process, 
        but restricts access to dangerous builtins like <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">eval</code>, 
        <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">exec</code>, and 
        <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">compile</code>. 
        This provides fast execution with minimal overhead, making it ideal for development and trusted code execution, 
        but offers no process-level isolation from the host system.
      </p>

      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="local",  # Default
    environment_kwargs={
        "setup_code": "import json",  # Optional
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Arguments</h2>
      <Table 
        headers={["Argument", "Type", "Default", "Description"]}
        rows={[
          [<code key="1">setup_code</code>, <code key="2">str</code>, <code key="3">None</code>, "Code to run at initialization"],
          [<code key="4">context_payload</code>, <code key="5">str | dict | list</code>, "Auto", "Initial context (set by RLM)"],
          [<code key="6">lm_handler_address</code>, <code key="7">tuple</code>, "Auto", "Socket address (set by RLM)"],
        ]}
      />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">How It Works</h2>
      <ol className="list-decimal list-inside text-muted-foreground space-y-1">
        <li>Creates sandboxed <code>globals</code> with restricted <code>__builtins__</code></li>
        <li>Injects <code>context</code>, <code>llm_query()</code>, <code>llm_query_batched()</code>, <code>FINAL_VAR()</code></li>
        <li>Executes each code block via <code>exec()</code></li>
        <li><code>llm_query()</code> sends TCP requests to LM Handler</li>
        <li>Variables persist across code blocks in <code>locals</code></li>
      </ol>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Sandboxed Builtins</h2>
      <p className="text-muted-foreground mb-2">
        <strong>Allowed:</strong> <code>print</code>, <code>len</code>, <code>range</code>, <code>str</code>, <code>int</code>, <code>float</code>, <code>list</code>, <code>dict</code>, <code>set</code>, <code>tuple</code>, <code>open</code>, <code>min</code>, <code>max</code>, <code>sum</code>, <code>sorted</code>, <code>enumerate</code>, <code>zip</code>, <code>map</code>, <code>filter</code>, standard exceptions
      </p>
      <p className="text-muted-foreground">
        <strong>Blocked:</strong> <code>eval</code>, <code>exec</code>, <code>compile</code>, <code>input</code>, <code>globals</code>, <code>locals</code>
      </p>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Limitations</h2>
      <ul className="list-disc list-inside text-muted-foreground space-y-1">
        <li>Shares process memory with host</li>
        <li>No network isolation</li>
        <li>Dependencies must be installed in host virtualenv</li>
      </ul>
    </div>
  );
}
````

## File: docs/src/app/environments/modal/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";
import { Table } from "@/components/Table";

export default function ModalPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4 flex items-center gap-3">
        ModalREPL
        <img 
          src="https://github.com/modal-labs.png" 
          alt="Modal" 
          height="24" 
          className="inline-block"
          style={{ height: '24px', verticalAlign: 'middle' }}
        />
      </h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        <strong className="text-foreground">ModalREPL</strong> executes Python code in <strong className="text-foreground">Modal cloud sandboxes</strong>, 
        which are ephemeral cloud VMs that run completely isolated from the host machine. Each sandbox is a fresh, 
        isolated environment with its own filesystem, network, and compute resources, providing the highest level of 
        security and isolation available in RLM. The sandbox requests LM calls from the host&apos;s LM Handler when code 
        executes <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">llm_query()</code>. 
        This environment is production-ready and essential for executing untrusted LM-generated code or handling sensitive data. 
        For more information on Modal sandboxes, see the{" "}
        <a href="https://modal.com/docs/guide/sandbox" className="text-primary hover:underline font-medium">Modal sandboxes documentation</a>.
      </p>

      <p className="text-muted-foreground mb-2"><strong>Prerequisites:</strong></p>
      <CodeBlock language="bash" code={`uv pip install -e . --extra modal
# Or with regular pip:
# pip install -e ".[modal]"

modal setup  # Authenticate`} />

      <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="modal",
    environment_kwargs={
        "app_name": "my-rlm-app",
        "timeout": 600,
    },
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Arguments</h2>
      <Table 
        headers={["Argument", "Type", "Default", "Description"]}
        rows={[
          [<code key="1">app_name</code>, <code key="2">str</code>, <code key="3">&quot;rlm-sandbox&quot;</code>, "Modal app name"],
          [<code key="4">timeout</code>, <code key="5">int</code>, <code key="6">600</code>, "Sandbox timeout in seconds"],
          [<code key="7">image</code>, <code key="8">modal.Image</code>, "Auto", "Custom Modal image"],
          [<code key="9">setup_code</code>, <code key="10">str</code>, <code key="11">None</code>, "Code to run at initialization"],
          [<code key="12">context_payload</code>, <code key="13">str | dict | list</code>, "Auto", "Initial context (set by RLM)"],
          [<code key="14">lm_handler_address</code>, <code key="15">tuple</code>, "Auto", "Socket address (set by RLM)"],
        ]}
      />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">How It Works</h2>
      <p className="text-muted-foreground mb-4">
        Modal sandboxes can&apos;t connect directly to the host. Uses HTTP broker pattern:
      </p>
      <ol className="list-decimal list-inside text-muted-foreground space-y-1 mb-6">
        <li>Sandbox starts Flask broker server on port 8080</li>
        <li>Port exposed via Modal&apos;s <code>encrypted_ports</code> tunnel</li>
        <li><code>llm_query()</code> POSTs to local broker, blocks waiting</li>
        <li>Host polls <code>{"{tunnel}/pending"}</code> every 100ms</li>
        <li>Host forwards requests to LM Handler, POSTs responses back</li>
        <li>Broker unblocks and returns response</li>
      </ol>

      <pre className="text-sm">{`Host polls /pending ────────────────┐
                                    │
┌───────────────────────────────────┼──┐
│ Modal Sandbox                     ▼  │
│  ┌──────────────┐   ┌──────────────┐ │
│  │ Broker Flask │◄─►│ Code Exec    │ │
│  │  /enqueue    │   │ llm_query()  │ │
│  │  /pending    │   └──────────────┘ │
│  │  /respond    │                    │
│  └──────────────┘                    │
└──────────────────────────────────────┘`}</pre>

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Custom Image</h2>
      <p className="text-muted-foreground mb-4">
        You can use your own custom Modal images or update the given image:
      </p>
      <CodeBlock code={`import modal

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "numpy", "pandas", "dill", "requests", "flask"
)

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="modal",
    environment_kwargs={"image": image},
)`} />

      <hr className="my-8 border-border" />

      <h2 className="text-2xl font-semibold mb-4">Default Image</h2>
      <p className="text-muted-foreground">
        Includes: <code>numpy</code>, <code>pandas</code>, <code>scipy</code>, <code>sympy</code>, <code>requests</code>, <code>httpx</code>, <code>flask</code>, <code>pyyaml</code>, <code>tqdm</code>, <code>dill</code>
      </p>
    </div>
  );
}
````

## File: docs/src/app/environments/page.tsx
````typescript
import { Table } from "@/components/Table";
import { CodeBlock } from "@/components/CodeBlock";
import Link from "next/link";

export default function EnvironmentsPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-4">REPL Environments</h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        REPL environments are sandboxed Python execution contexts where the LM can write and execute code 
        to analyze the input context. These environments provide the LM with programmatic access to 
        computation, data processing, and the ability to make sub-LM calls.
      </p>

      <p className="text-muted-foreground mb-8 leading-relaxed">
        When you call <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">rlm.completion(prompt)</code>, 
        your prompt becomes the <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">context</code> variable 
        in a Python REPL. The LM can then write Python code to examine this context, decompose complex tasks, 
        and recursively call itself via <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">llm_query()</code> 
        to handle sub-problems.
      </p>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Isolation Levels</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          RLM supports two types of environments based on their isolation level:
        </p>

        <div className="grid md:grid-cols-2 gap-6 mb-8">
          <div className="bg-gradient-to-br from-slate-50 to-slate-100/50 rounded-xl p-6 border border-slate-200 shadow-sm">
            <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500"></div>
              Non-Isolated Environments
            </h3>
            <p className="text-sm text-muted-foreground mb-3">
              Run code on the same machine as the RLM process (or in a container on the same host).
            </p>
            <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1.5 ml-2">
              <li><strong className="text-foreground">Faster execution</strong> — No network overhead</li>
              <li><strong className="text-foreground">Shared resources</strong> — Access to host filesystem, network, and memory</li>
              <li><strong className="text-foreground">Lower security</strong> — Code runs with host process privileges</li>
              <li><strong className="text-foreground">Use cases:</strong> Development, testing, trusted code</li>
            </ul>
          </div>

          <div className="bg-gradient-to-br from-emerald-50 to-teal-50/50 rounded-xl p-6 border border-emerald-200 shadow-sm">
            <h3 className="font-semibold text-foreground mb-3 flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
              Isolated Environments
            </h3>
            <p className="text-sm text-muted-foreground mb-3">
              Run code on completely separate machines (cloud VMs), guaranteeing full isolation.
            </p>
            <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1.5 ml-2">
              <li><strong className="text-foreground">Full isolation</strong> — No access to host resources</li>
              <li><strong className="text-foreground">Higher security</strong> — Code cannot affect host system</li>
              <li><strong className="text-foreground">Network overhead</strong> — Communication via HTTP tunnels</li>
              <li><strong className="text-foreground">Use cases:</strong> Production, untrusted code, sensitive data</li>
            </ul>
          </div>
        </div>

        <p className="text-muted-foreground leading-relaxed">
          <strong className="text-foreground">Why this matters:</strong> The isolation level determines the security 
          and trust model of your RLM application. Non-isolated environments are faster and simpler, but code execution 
          shares the host&apos;s resources and privileges. Isolated environments provide complete separation, making them 
          essential for production deployments or when executing untrusted LM-generated code.
        </p>
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Available Environments</h2>
        <Table 
          headers={["Environment", "Isolation", "Best For"]}
          rows={[
            [<Link key="1" href="/environments/local" className="text-primary hover:underline"><code>local</code></Link>, "Non-isolated", "Development"],
            [<Link key="2" href="/environments/docker" className="text-primary hover:underline"><code>docker</code></Link>, "Non-isolated", "CI/CD, reproducibility"],
            [<Link key="3" href="/environments/modal" className="text-primary hover:underline"><code>modal</code></Link>, "Isolated", "Production"],
          ]}
        />
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">REPL Globals</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          These variables and functions are available inside code executed in the REPL environment:
        </p>

        <div className="bg-gradient-to-br from-slate-50 to-blue-50 border-2 border-slate-200 rounded-xl p-6 mb-6">
          <Table 
            headers={["Name", "Description"]}
            rows={[
              [
                <code key="1" className="text-sm font-semibold">context</code>, 
                "Your input prompt, available as a variable in the REPL"
              ],
              [
                <code key="2" className="text-sm font-semibold">llm_query(prompt, model=None)</code>, 
                "Query a sub-LM from within the REPL. Returns the completion string."
              ],
              [
                <code key="3" className="text-sm font-semibold">llm_query_batched(prompts, model=None)</code>, 
                "Concurrent sub-LM queries. Returns a list of completion strings."
              ],
              [
                <code key="4" className="text-sm font-semibold">FINAL_VAR(var_name)</code>, 
                "Mark a variable as the final answer to return from the RLM"
              ],
            ]}
          />
        </div>

        <CodeBlock code={`# Example usage in REPL
context = "Your input here"

# Query a sub-LM
result = llm_query("Summarize the context", model="gpt-5-mini")

# Process the result
summary = process(result)

# Return final answer
FINAL_VAR(summary)`} />
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Architecture</h2>

      <h3 className="text-lg font-medium mt-6 mb-2">Non-Isolated (local, docker)</h3>
      <p className="text-muted-foreground mb-4">Direct TCP socket communication:</p>
      <pre className="text-sm">{`┌────────────┐   Socket   ┌────────────┐
│ Environment│◄──────────►│ LM Handler │
│ llm_query()│            │            │
└────────────┘            └────────────┘`}</pre>

      <h3 className="text-lg font-medium mt-6 mb-2">Isolated (modal)</h3>
      <p className="text-muted-foreground mb-4">HTTP broker pattern for cloud sandboxes:</p>
      <pre className="text-sm">{`┌─────────────────────────────────────┐
│ Host                                │
│  ┌──────────┐       ┌────────────┐ │
│  │ ModalREPL│◄─────►│ LM Handler │ │
│  │ (polls)  │Socket └────────────┘ │
│  └────┬─────┘                      │
│       │ HTTP                       │
└───────┼────────────────────────────┘
        ▼
┌───────────────────────────────────────┐
│ Modal Sandbox                         │
│  ┌────────────┐     ┌──────────────┐ │
│  │   Broker   │◄───►│ Code Exec    │ │
│  │  (Flask)   │     │ llm_query()  │ │
│  └────────────┘     └──────────────┘ │
└───────────────────────────────────────┘`}</pre>

      <p className="text-muted-foreground mt-4">
        The broker queues <code>llm_query()</code> requests, host polls for pending requests, 
        forwards them to the LM Handler, and posts responses back.
      </p>
      </div>
    </div>
  );
}
````

## File: docs/src/app/trajectories/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";

export default function TrajectoriesPage() {
  return (
    <div className="max-w-4xl">
      <h1 className="text-3xl font-bold mb-4">Visualizing RLM Trajectories</h1>
      
      <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
        RLM provides built-in logging capabilities to save execution trajectories, enabling you to 
        analyze how the LM decomposes tasks, executes code, and makes recursive calls.
      </p>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Setting Up the Logger</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          To log RLM execution trajectories, initialize an <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">RLMLogger</code> 
          and pass it to the RLM constructor:
        </p>

        <CodeBlock code={`from rlm import RLM
from rlm.logger import RLMLogger

# Initialize logger with output directory
logger = RLMLogger(log_dir="./logs")

# Pass logger to RLM
rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    logger=logger,  # Enable trajectory logging
    verbose=False,  # print to logs
)

# Run completion - trajectories are automatically saved
result = rlm.completion("Your prompt here")`} />
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Accessing Logged Trajectories</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          Trajectories are saved as JSON-lines files in the specified log directory. Each line contains 
          a complete snapshot of one RLM iteration, including:
        </p>

        <ul className="list-disc list-inside text-muted-foreground space-y-2 mb-6 ml-2">
          <li><strong className="text-foreground">LM prompts and responses</strong> — All prompts sent to the LM and their completions</li>
          <li><strong className="text-foreground">Generated code</strong> — Python code written by the LM</li>
          <li><strong className="text-foreground">Code execution results</strong> — stdout, stderr, and return values</li>
          <li><strong className="text-foreground">Sub-LM calls</strong> — All <code className="px-1 py-0.5 rounded bg-muted text-foreground text-xs font-semibold">llm_query()</code> invocations and their results</li>
          <li><strong className="text-foreground">Metadata</strong> — Timestamps, model names, token usage, execution times</li>
        </ul>

        <CodeBlock code={`import json

# Read trajectory file
with open("./logs/trajectory_20250101_123456.jsonl", "r") as f:
    for line in f:
        iteration = json.loads(line)
        print(f"Iteration {iteration['iteration']}")
        print(f"Prompt: {iteration['prompt'][:100]}...")
        print(f"Code: {iteration.get('code', 'N/A')}")
        print(f"Result: {iteration.get('result', {}).get('stdout', 'N/A')}")
        print("---")`} />
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Visualization Example</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed">
          The logged trajectories can be visualized to understand the RLM&apos;s decision-making process. 
          Below is an example visualization showing how the LM decomposes a complex task:
        </p>

        <div className="bg-gradient-to-br from-slate-50 to-blue-50 border-2 border-slate-200 rounded-xl p-6 mb-6">
          <img 
            src="/rlm/visualizer.png" 
            alt="RLM Trajectory Visualization" 
            className="rounded-lg shadow-sm w-full h-auto"
          />
        </div>

        <p className="text-muted-foreground leading-relaxed">
          This visualization shows the recursive structure of RLM execution, with each node representing 
          an LM call and edges showing the flow of context and sub-problem decomposition. The logger 
          captures all this information, enabling detailed analysis of the RLM&apos;s reasoning process.
        </p>
      </div>

      <div className="my-12">
        <h2 className="text-2xl font-bold mb-4">Log File Structure</h2>
        
        <p className="text-muted-foreground mb-4 leading-relaxed">
          Each log file contains one JSON object per line (JSON-lines format). The structure includes:
        </p>

        <CodeBlock code={`{
  "iteration": 0,
  "timestamp": "2025-01-01T12:34:56.789Z",
  "prompt": "...",
  "response": "...",
  "code": "...",
  "result": {
    "stdout": "...",
    "stderr": "",
    "return_value": null
  },
  "sub_calls": [
    {
      "prompt": "...",
      "response": "...",
      "model": "gpt-5-mini"
    }
  ],
  "usage": {
    "input_tokens": 150,
    "output_tokens": 75
  },
  "execution_time": 1.23
}`} />
      </div>
    </div>
  );
}
````

## File: docs/src/app/globals.css
````css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --background: 0 0% 100%;
  --foreground: 240 10% 3.9%;
  --card: 0 0% 100%;
  --card-foreground: 240 10% 3.9%;
  --popover: 0 0% 100%;
  --popover-foreground: 240 10% 3.9%;
  --primary: 240 5.9% 10%;
  --primary-foreground: 0 0% 98%;
  --secondary: 240 4.8% 95.9%;
  --secondary-foreground: 240 5.9% 10%;
  --muted: 240 4.8% 95.9%;
  --muted-foreground: 240 3.8% 46.1%;
  --accent: 240 4.8% 95.9%;
  --accent-foreground: 240 5.9% 10%;
  --destructive: 0 84.2% 60.2%;
  --destructive-foreground: 0 0% 98%;
  --border: 240 5.9% 90%;
  --input: 240 5.9% 90%;
  --ring: 240 5.9% 10%;
  --radius: 0.5rem;
}


body {
  font-family: "Inter", system-ui, sans-serif;
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  @apply antialiased;
}

pre, code {
  font-family: "JetBrains Mono", monospace;
}

/* Code block styling */
pre {
  background: hsl(240 5% 97%);
  border: 1px solid hsl(var(--border));
  border-radius: calc(var(--radius) + 2px);
  padding: 1.25rem;
  overflow-x: auto;
  font-size: 0.875rem;
  line-height: 1.75;
  @apply shadow-sm;
}

code {
  background: hsl(240 5% 97%);
  padding: 0.2rem 0.4rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
  @apply font-medium;
}

pre code {
  background: none;
  padding: 0;
  font-size: inherit;
}

/* Syntax highlighting */
.token-keyword { color: #d73a49; font-weight: 500; }
.token-string { color: #032f62; }
.token-comment { color: #6a737d; font-style: italic; }
.token-function { color: #6f42c1; }
.token-number { color: #005cc5; }
.token-operator { color: #d73a49; }
.token-class { color: #6f42c1; }
````

## File: docs/src/app/layout.tsx
````typescript
import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Recursive Language Models",
  description: "A task-agnostic inference paradigm for near-infinite context handling",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 overflow-auto bg-background">
            <div className="max-w-4xl mx-auto px-8 py-16">
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}
````

## File: docs/src/app/page.tsx
````typescript
import { CodeBlock } from "@/components/CodeBlock";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/Tabs";
import { Button } from "@/components/Button";
import Link from "next/link";

export default function Home() {
  return (
    <div>
      {/* WIP Warning */}
      <div className="mb-8 p-4 bg-amber-50 border-2 border-amber-200 rounded-lg">
        <p className="text-sm text-amber-800">
          <strong>⚠️ Work in Progress:</strong> These documentation are highly WIP and subject to large changes. 
          It is helpful for minimally getting started, but will be updated as we go.
        </p>
      </div>

      {/* Hero Section */}
      <div className="mb-16">
        <h1 className="text-4xl md:text-5xl font-bold mb-8 tracking-tight text-foreground">
          Recursive Language Models
        </h1>
        
        <div className="flex flex-wrap gap-4 mb-12">
          <Button href="https://arxiv.org/abs/2512.24601" variant="default" external>
            Paper
          </Button>
          <Button href="https://github.com/alexzhang13/rlm" variant="outline" external>
            GitHub
          </Button>
        </div>
        
        <div className="max-w-4xl">
          <p className="text-xl text-muted-foreground mb-6 leading-relaxed">
            <strong className="text-foreground">Recursive Language Models (RLMs)</strong> are a task-agnostic inference paradigm for 
            language models to handle near-infinite length contexts by enabling the LM to{" "}
            <em className="text-foreground/90">programmatically</em> examine, decompose, and recursively call itself over its input.
          </p>

          <p className="text-lg text-muted-foreground leading-relaxed">
            RLMs replace the canonical <code className="px-1.5 py-0.5 rounded bg-muted text-foreground font-semibold text-base">llm.completion(prompt, model)</code> call with a{" "}
            <code className="px-1.5 py-0.5 rounded bg-muted text-foreground font-semibold text-base">rlm.completion(prompt, model)</code> call. RLMs offload the context as a variable in a 
            REPL environment that the LM can interact with and launch sub-LM calls inside of.
          </p>
        </div>
      </div>

      <div className="my-12">
        <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-2xl p-8 shadow-lg">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-md">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </div>
            <div>
              <h2 className="text-2xl font-bold text-foreground">Installation</h2>
              <p className="text-sm text-muted-foreground">We use uv, but any virtual environment works.</p>
            </div>
          </div>
          
          <p className="text-muted-foreground mb-6 leading-relaxed">
            We use <code className="px-2 py-1 rounded-md bg-white border border-blue-200 text-foreground font-semibold">uv</code> for developing RLM. Install it first:
          </p>
          
          <CodeBlock language="bash" code={`# Install uv (first time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup project
uv init && uv venv --python 3.12
source .venv/bin/activate

# Install RLM in editable mode
uv pip install -e .

# For Modal sandbox support
uv pip install -e . --extra modal`} />
        </div>
        
        <p className="text-muted-foreground mt-6 leading-relaxed">
          Once installed, you can import and use RLM in your Python code. See the{" "}
          <Link href="/api" className="text-primary hover:underline font-medium">Using the RLM Client</Link>{" "}
          section for detailed API documentation and examples.
        </p>
      </div>

      <div className="my-16">
        <h2 className="text-3xl font-bold mb-4">Quick Start</h2>
        <p className="text-muted-foreground mb-6 leading-relaxed">
          These examples show how to initialize RLM with different LM providers. The RLM will automatically 
          execute Python code in a REPL environment to solve the task. For more details on configuration options, 
          see the <Link href="/api" className="text-primary hover:underline font-medium">Using the RLM Client</Link>{" "}
          documentation.
        </p>
      
      <Tabs defaultValue="openai">
        <TabsList>
          <TabsTrigger value="openai">OpenAI</TabsTrigger>
          <TabsTrigger value="anthropic">Anthropic</TabsTrigger>
          <TabsTrigger value="portkey">Portkey</TabsTrigger>
        </TabsList>
        <TabsContent value="openai">
          <CodeBlock code={`import os
from rlm import RLM

rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-5-mini",
    },
    verbose=False,  # print to logs
)

result = rlm.completion("Calculate 2^(2^(2^2)) using Python.")
print(result.response)`} />
        </TabsContent>
        <TabsContent value="anthropic">
          <CodeBlock code={`import os
from rlm import RLM

rlm = RLM(
    backend="anthropic",
    backend_kwargs={
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "model_name": "claude-sonnet-4-20250514",
    },
    verbose=False,  # print to logs
)

result = rlm.completion("Calculate 2^(2^(2^2)) using Python.")
print(result.response)`} />
        </TabsContent>
        <TabsContent value="portkey">
          <CodeBlock code={`import os
from rlm import RLM

rlm = RLM(
    backend="portkey",
    backend_kwargs={
        "api_key": os.getenv("PORTKEY_API_KEY"),
        "model_name": "@openai/gpt-5-mini",
    },
    verbose=False,  # print to logs
)

result = rlm.completion("Calculate 2^(2^(2^2)) using Python.")
print(result.response)`} />
        </TabsContent>
      </Tabs>
      </div>

      <div className="my-16">
        <h2 className="text-3xl font-bold mb-4">REPL Environments</h2>
        <p className="text-lg text-muted-foreground mb-8 leading-relaxed max-w-3xl">
          RLMs execute LM-generated Python code in a sandboxed REPL environment. We support two types 
          of environments: <strong className="text-foreground">non-isolated</strong> and <strong className="text-foreground">isolated</strong>.
        </p>

        <div className="grid md:grid-cols-2 gap-4 mb-6">
          <div className="bg-gradient-to-br from-slate-50 to-slate-100/50 rounded-xl p-6 border border-slate-200 shadow-sm">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full bg-blue-500"></div>
              <h3 className="font-semibold text-foreground">Non-isolated environments</h3>
            </div>
            <p className="text-sm text-muted-foreground mb-3">
              Run code on the same machine as the RLM process:
            </p>
            <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1.5 ml-2">
              <li><code className="px-1.5 py-0.5 rounded bg-white/80 text-foreground font-semibold">local</code> (default) — Same-process execution with sandboxed builtins. Fast but shares memory with host.</li>
              <li><code className="px-1.5 py-0.5 rounded bg-white/80 text-foreground font-semibold">docker</code> — Containerized execution in Docker. Better isolation, reproducible environments.</li>
            </ul>
          </div>

          <div className="bg-gradient-to-br from-emerald-50 to-teal-50/50 rounded-xl p-6 border border-emerald-200 shadow-sm">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
              <h3 className="font-semibold text-foreground">Isolated environments</h3>
            </div>
            <p className="text-sm text-muted-foreground mb-3">
              Run code on completely separate machines, guaranteeing full isolation:
            </p>
            <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1.5 ml-2">
              <li><code className="px-1.5 py-0.5 rounded bg-white/80 text-foreground font-semibold">modal</code> — Cloud sandboxes via <a href="https://modal.com" className="text-primary hover:underline font-medium">Modal</a>. Production-ready, fully isolated from host.</li>
            </ul>
          </div>
        </div>

      <Tabs defaultValue="local">
        <TabsList>
          <TabsTrigger value="local">Local (Default)</TabsTrigger>
          <TabsTrigger value="docker">
            Docker
            <img 
              src="https://github.com/docker.png" 
              alt="Docker" 
              height="16" 
              className="ml-2 inline-block"
              style={{ height: '16px', verticalAlign: 'middle' }}
            />
          </TabsTrigger>
          <TabsTrigger value="modal">
            Modal
            <img 
              src="https://github.com/modal-labs.png" 
              alt="Modal" 
              height="16" 
              className="ml-2 inline-block"
              style={{ height: '16px', verticalAlign: 'middle' }}
            />
          </TabsTrigger>
        </TabsList>
        <TabsContent value="local">
          <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="local",
)`} />
        </TabsContent>
        <TabsContent value="docker">
          <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="docker",
    environment_kwargs={
        "image": "python:3.11-slim",
    },
)`} />
        </TabsContent>
        <TabsContent value="modal">
          <CodeBlock code={`rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-mini"},
    environment="modal",
    environment_kwargs={
        "app_name": "my-rlm-app",
        "timeout": 600,
    },
)`} />
        </TabsContent>
      </Tabs>

        <p className="text-muted-foreground mt-6">
          See <Link href="/environments" className="text-primary hover:underline">Environments</Link> for 
          details on each environment&apos;s architecture and configuration.
        </p>
      </div>

      <div className="my-16">
        <h2 className="text-3xl font-bold mb-6">Core Components</h2>
        
        <p className="text-muted-foreground mb-6 leading-relaxed text-lg max-w-4xl">
          RLMs indirectly handle contexts by storing them in a persistent REPL environment, where an LM can view and 
          run code inside of. It also has the ability to sub-query (R)LMs (i.e. with <code className="px-1.5 py-0.5 rounded bg-muted text-foreground text-sm font-semibold">llm_query</code> calls) 
          and produce a final answer based on this). This design generally requires the following components:
        </p>

        <div className="bg-gradient-to-br from-purple-50 to-pink-50/30 rounded-xl p-8 border border-purple-200/50 shadow-sm mb-6">
          <ol className="list-decimal list-inside text-muted-foreground space-y-3 text-lg max-w-2xl">
            <li>Set up a REPL environment, where state is persisted across code execution turns.</li>
            <li>Put the prompt (or context) into a programmatic variable.</li>
            <li>Allow the model to write code that peeks into and decomposes the variable, and observes any side effects.</li>
            <li>Encourage the model, in its code, to recurse over shorter, programmatically constructed prompts.</li>
          </ol>
        </div>

        <div className="bg-gradient-to-br from-slate-50 to-blue-50 border-2 border-slate-200 rounded-xl p-6">
          <img 
            src="/rlm/teaser.png" 
            alt="RLM Core Components Architecture" 
            className="rounded-lg shadow-sm w-full h-auto"
          />
        </div>
      </div>

      <div className="my-16">
        <h2 className="text-3xl font-bold mb-6">Citation</h2>
        <div className="bg-gradient-to-br from-amber-50 to-orange-50/30 rounded-xl p-6 border border-amber-200/50 shadow-sm">
          <pre className="text-sm font-mono leading-relaxed text-foreground">{`@misc{zhang2025recursivelanguagemodels,
      title={Recursive Language Models}, 
      author={Alex L. Zhang and Tim Kraska and Omar Khattab},
      year={2025},
      eprint={2512.24601},
      archivePrefix={arXiv},
}`}</pre>
        </div>
      </div>
    </div>
  );
}
````

## File: docs/src/components/Button.tsx
````typescript
import { cn } from "@/lib/utils";
import Link from "next/link";

interface ButtonProps {
  children: React.ReactNode;
  href?: string;
  variant?: "default" | "outline" | "ghost";
  className?: string;
  external?: boolean;
}

export function Button({ 
  children, 
  href, 
  variant = "default", 
  className,
  external = false 
}: ButtonProps) {
  const baseClasses = "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 px-4 py-2.5";
  
  const variants = {
    default: "bg-blue-600 text-white hover:bg-blue-700 shadow-md hover:shadow-lg",
    outline: "border-2 border-slate-300 bg-white hover:bg-slate-50 hover:border-slate-400 text-slate-700",
    ghost: "hover:bg-slate-100 text-slate-700",
  };

  const classes = cn(baseClasses, variants[variant], className);

  if (href) {
    if (external) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className={classes}>
          {children}
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      );
    }
    return (
      <Link href={href} className={classes}>
        {children}
      </Link>
    );
  }

  return <button className={classes}>{children}</button>;
}
````

## File: docs/src/components/CodeBlock.tsx
````typescript
"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Check, Copy } from "lucide-react";

interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
}

function highlightBash(code: string): string {
  // Escape HTML
  let result = code
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Highlight comments - simple and safe
  return result.replace(/#.*$/gm, (match) => {
    return '<span class="token-comment">' + match + '</span>';
  });
}

function highlightPython(code: string): string {
  // Escape HTML first
  let result = code
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Use a simple approach: process in order and use unique markers
  // to avoid matching our own HTML
  
  // Step 1: Protect strings by replacing with markers
  const stringMarkers: string[] = [];
  result = result.replace(/(["'])((?:\\.|(?!\1)[^\\])*?)\1/g, (match) => {
    const marker = `__STRING_MARKER_${stringMarkers.length}__`;
    stringMarkers.push(match);
    return marker;
  });
  
  // Step 2: Highlight keywords
  const keywords = /\b(from|import|def|class|return|if|else|elif|for|while|with|as|try|except|finally|raise|yield|lambda|and|or|not|in|is|None|True|False|async|await)\b/g;
  result = result.replace(keywords, '<span class="token-keyword">$&</span>');
  
  // Step 3: Highlight functions
  result = result.replace(/\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\()/g, '<span class="token-function">$1</span>');
  
  // Step 4: Highlight numbers
  result = result.replace(/\b\d+\.?\d*\b/g, '<span class="token-number">$&</span>');
  
  // Step 5: Highlight comments
  result = result.replace(/#.*$/gm, '<span class="token-comment">$&</span>');
  
  // Step 6: Restore strings with highlighting
  stringMarkers.forEach((str, i) => {
    result = result.replace(`__STRING_MARKER_${i}__`, '<span class="token-string">' + str + '</span>');
  });
  
  return result;
}

export function CodeBlock({ code, language = "python", filename }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const highlighted = language === "bash" ? highlightBash(code) : highlightPython(code);

  return (
    <div className="relative group my-6">
      {filename && (
        <div className="bg-muted px-4 py-2.5 text-sm text-muted-foreground border border-b-0 border-border rounded-t-lg font-mono font-medium">
          {filename}
        </div>
      )}
      <pre className={cn("relative shadow-sm overflow-x-auto", filename && "rounded-t-none rounded-b-lg", !filename && "rounded-lg")}>
        <button
          onClick={handleCopy}
          className="absolute top-3 right-3 p-2 rounded-md bg-background/90 hover:bg-background border border-border shadow-sm opacity-0 group-hover:opacity-100 transition-all hover:scale-105 z-10"
          aria-label="Copy code"
        >
          {copied ? (
            <Check className="h-4 w-4 text-green-600" />
          ) : (
            <Copy className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          )}
        </button>
        <code 
          className="block font-mono text-sm leading-relaxed whitespace-pre" 
          dangerouslySetInnerHTML={{ __html: highlighted }} 
        />
      </pre>
    </div>
  );
}
````

## File: docs/src/components/Table.tsx
````typescript
interface TableProps {
  headers: string[];
  rows: (string | React.ReactNode)[][];
}

export function Table({ headers, rows }: TableProps) {
  return (
    <div className="my-6 overflow-x-auto rounded-lg border border-border shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            {headers.map((header, i) => (
              <th key={i} className="text-left py-3.5 px-4 font-semibold text-foreground">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border last:border-0 hover:bg-muted/20 transition-colors">
              {row.map((cell, j) => (
                <td key={j} className="py-3.5 px-4 text-muted-foreground">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
````

## File: docs/src/components/Tabs.tsx
````typescript
"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export function Tabs({ children, defaultValue, className }: { 
  children: React.ReactNode; 
  defaultValue: string;
  className?: string;
}) {
  return (
    <TabsPrimitive.Root defaultValue={defaultValue} className={cn("my-4", className)}>
      {children}
    </TabsPrimitive.Root>
  );
}

export function TabsList({ children }: { children: React.ReactNode }) {
  return (
    <TabsPrimitive.List className="flex border-b border-border mb-0">
      {children}
    </TabsPrimitive.List>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      className="px-5 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground data-[state=active]:text-foreground data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:font-semibold -mb-px transition-all"
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <TabsPrimitive.Content value={value} className="mt-0">
      {children}
    </TabsPrimitive.Content>
  );
}
````

## File: docs/src/lib/utils.ts
````typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
````

## File: docs/.gitignore
````
# dependencies
node_modules/
/.pnp
.pnp.js

# testing
/coverage

# next.js
/.next/
/out/

# production
/build

# misc
.DS_Store
*.pem

# debug
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# local env files
.env*.local
.env

# vercel
.vercel

# typescript
*.tsbuildinfo
next-env.d.ts
````

## File: docs/getting-started.md
````markdown
---
layout: default
title: Getting Started
nav_order: 2
---

# Getting Started
{: .no_toc }

A complete guide to installing and configuring RLM for your projects.
{: .fs-6 .fw-300 }

## Table of Contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Installation

### Prerequisites

- Python 3.11 or higher
- An API key from a supported LLM provider (OpenAI, Anthropic, etc.)

### Using uv (Recommended)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create and activate virtual environment
uv init && uv venv --python 3.12
source .venv/bin/activate

# Install RLM in editable mode
uv pip install -e .
```

### Optional: Modal Support

For cloud-based sandboxed execution:

```bash
# Install Modal extra
uv pip install -e ".[modal]"

# Authenticate Modal
modal setup
```

### Optional: Docker Support

For containerized execution, ensure Docker is installed and running:

```bash
# Verify Docker is available
docker --version
```

---

## Your First RLM Call

### Step 1: Set Up API Keys

Create a `.env` file in your project root:

```bash
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
PORTKEY_API_KEY=...
```

### Step 2: Basic Usage

```python
import os
from dotenv import load_dotenv
from rlm import RLM

load_dotenv()

# Create RLM instance
rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-4o",
    },
)

# Make a completion call
result = rlm.completion("Calculate the 50th Fibonacci number using Python.")
print(result.response)
```

### Step 3: Enable Verbose Output

See what the RLM is doing step by step:

```python
rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-4o",
    },
    verbose=True,  # Enable rich console output
)
```

This will display:
- Each iteration's LM response
- Code blocks being executed
- Stdout/stderr from execution
- Final answer when reached

---

## Understanding the RLM Class

### Constructor Arguments

| Argument | Type | Default | Description |
|:---------|:-----|:--------|:------------|
| `backend` | `str` | `"openai"` | LM provider backend |
| `backend_kwargs` | `dict` | `None` | Backend-specific configuration |
| `environment` | `str` | `"local"` | Execution environment type |
| `environment_kwargs` | `dict` | `None` | Environment configuration |
| `max_depth` | `int` | `1` | Maximum recursion depth |
| `max_iterations` | `int` | `30` | Max REPL iterations per call |
| `custom_system_prompt` | `str` | `None` | Override default system prompt |
| `other_backends` | `list` | `None` | Additional backends for sub-calls |
| `other_backend_kwargs` | `list` | `None` | Configs for additional backends |
| `logger` | `RLMLogger` | `None` | Logger for trajectory tracking |
| `verbose` | `bool` | `False` | Enable console output |

### The `completion()` Method

```python
result = rlm.completion(
    prompt="Your input text or context",
    root_prompt="Optional: A short prompt visible to the root LM"
)
```

**Parameters:**
- `prompt`: The main context/input (string or dict). This becomes the `context` variable in the REPL.
- `root_prompt`: Optional hint shown to the root LM (useful for Q&A tasks).

**Returns:** `RLMChatCompletion` with:
- `response`: The final answer string
- `usage_summary`: Token usage statistics
- `execution_time`: Total time in seconds
- `root_model`: Model name used
- `prompt`: Original input

---

## Choosing an Environment

RLM supports three execution environments:

### Local (Default)

Code runs in the same Python process with sandboxed builtins.

```python
rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    environment="local",
)
```

**Pros:** Fast, no setup required  
**Cons:** Less isolation from host process

### Docker

Code runs in a Docker container with full isolation.

```python
rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    environment="docker",
    environment_kwargs={
        "image": "python:3.11-slim",  # Custom image
    },
)
```

**Pros:** Containerized isolation, reproducible  
**Cons:** Requires Docker, slower startup

### Modal

Code runs in Modal's cloud sandboxes for full isolation.

```python
rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    environment="modal",
    environment_kwargs={
        "app_name": "my-rlm-app",
        "timeout": 600,
    },
)
```

**Pros:** Cloud-native, scalable, fully isolated  
**Cons:** Requires Modal account, network latency

---

## Choosing a Backend

### OpenAI

```python
rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-4o",
        # Optional: custom base URL
        # "base_url": "https://api.openai.com/v1",
    },
)
```

### Anthropic

```python
rlm = RLM(
    backend="anthropic",
    backend_kwargs={
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "model_name": "claude-sonnet-4-20250514",
    },
)
```

### Portkey (Router)

```python
rlm = RLM(
    backend="portkey",
    backend_kwargs={
        "api_key": os.getenv("PORTKEY_API_KEY"),
        "model_name": "@openai/gpt-5-nano",  # Portkey model format
    },
)
```

### OpenRouter

```python
rlm = RLM(
    backend="openrouter",
    backend_kwargs={
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "model_name": "openai/gpt-4o",
    },
)
```

### vLLM (Local)

```python
rlm = RLM(
    backend="vllm",
    backend_kwargs={
        "base_url": "http://localhost:8000/v1",  # Required
        "model_name": "meta-llama/Llama-3-70b",
    },
)
```

---

## Logging and Debugging

### Enable Logging

```python
from rlm import RLM
from rlm.logger import RLMLogger

# Create logger
logger = RLMLogger(log_dir="./logs")

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-4o"},
    logger=logger,
    verbose=True,
)

result = rlm.completion("...")
# Logs saved to ./logs/rlm_TIMESTAMP_UUID.jsonl
```

### Log File Format

Logs are JSON-lines files with:

```json
{"type": "metadata", "root_model": "gpt-4o", "max_iterations": 30, ...}
{"type": "iteration", "iteration": 1, "response": "...", "code_blocks": [...]}
{"type": "iteration", "iteration": 2, "response": "...", "final_answer": "..."}
```

### Visualizer

Use the included visualizer to explore trajectories:

```bash
cd visualizer/
npm install
npm run dev  # Opens at localhost:3001
```

Upload `.jsonl` log files to visualize:
- Iteration timeline
- Code execution results
- Sub-LM call traces
- Token usage

---

## Next Steps

- [API Reference](api/rlm.md) - Complete RLM class documentation
- [Environments](environments/) - Deep dive into each environment
- [Backends](backends.md) - Detailed backend configuration
````

## File: docs/package.json
````json
{
  "name": "rlm-docs",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.0.0",
    "tailwind-merge": "^2.0.0",
    "lucide-react": "^0.294.0",
    "@radix-ui/react-scroll-area": "^1.0.5",
    "@radix-ui/react-tabs": "^1.0.4"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "autoprefixer": "^10.4.16",
    "postcss": "^8.4.31",
    "tailwindcss": "^3.3.5",
    "typescript": "^5.0.0"
  }
}
````

## File: docs/postcss.config.js
````javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
````

## File: docs/tailwind.config.ts
````typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
````

## File: docs/tsconfig.json
````json
{
  "compilerOptions": {
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
````

## File: examples/daytona_repl_example.py
````python
"""
Example usage of Daytona REPL with code execution and LLM queries.

Run with: python -m examples.daytona_repl_example
"""

from rlm.clients.base_lm import BaseLM
from rlm.core.lm_handler import LMHandler
from rlm.core.types import ModelUsageSummary, UsageSummary
from rlm.environments.daytona_repl import DaytonaREPL


class MockLM(BaseLM):
    """Simple mock LM that echoes prompts."""

    def __init__(self):
        super().__init__(model_name="mock-model")

    def completion(self, prompt):
        return f"Mock response to: {prompt[:50]}"

    async def acompletion(self, prompt):
        return self.completion(prompt)

    def get_usage_summary(self):
        return UsageSummary(
            model_usage_summaries={
                "mock-model": ModelUsageSummary(
                    total_calls=1, total_input_tokens=10, total_output_tokens=10
                )
            }
        )

    def get_last_usage(self):
        return self.get_usage_summary()


def main():
    print("=" * 60)
    print("Daytona REPL Example")
    print("=" * 60)

    # Note: Requires DAYTONA_API_KEY environment variable to be set
    # or passed explicitly to DaytonaREPL(api_key="...")

    # Example 1: Basic code execution
    print("\n[1] Basic code execution (no LLM handler)")
    print("-" * 40)

    try:
        with DaytonaREPL(name="rlm-example") as repl:
            print(f"Daytona sandbox started with ID: {repl.sandbox.id}")
            result = repl.execute_code("x = 1 + 2")
            print("Executed: x = 1 + 2")
            print(f"Locals: {result.locals}")

            result = repl.execute_code("print(x * 2)")
            print("Executed: print(x * 2)")
            print(f"Stdout: {result.stdout.strip()}")

            result = repl.execute_code("answer = 42")
            result = repl.execute_code('print(FINAL_VAR("answer"))')
            print(f"FINAL_VAR('answer'): {result.stdout.strip()}")

        # Example 2: With LLM handler
        print("\n[2] Code execution with LLM handler")
        print("-" * 40)

        mock_client = MockLM()

        with LMHandler(client=mock_client) as handler:
            print(f"LM Handler started at {handler.address}")

            with DaytonaREPL(
                name="rlm-example-handler",
                lm_handler_address=handler.address,
            ) as repl:
                print(f"Daytona sandbox started with ID: {repl.sandbox.id}")
                print(f"Broker URL: {repl.broker_url}")

                # Single LLM query
                result = repl.execute_code('response = llm_query("What is 2+2?")')
                print("Executed: response = llm_query('What is 2+2?')")
                if result.stderr:
                    print(f"Stderr: {result.stderr}")

                result = repl.execute_code("print(response)")
                print(f"Response: {result.stdout.strip()}")

                # Batched LLM query
                result = repl.execute_code(
                    'responses = llm_query_batched(["Question 1", "Question 2", "Question 3"])'
                )
                print("\nExecuted: responses = llm_query_batched([...])")

                result = repl.execute_code("print(f'Got {len(responses)} responses')")
                print(f"Result: {result.stdout.strip()}")

                result = repl.execute_code("print(responses[0])")
                print(f"First response: {result.stdout.strip()}")

    except Exception as e:
        print(f"Error: {e}")
        print("\nMake sure Daytona is configured correctly and DAYTONA_API_KEY is set.")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
````

## File: examples/docker_repl_example.py
````python
"""
Docker REPL example with code execution and LLM queries.

Setup:
    1. Ensure Docker is running
    2. Run: python -m examples.docker_repl_example

The default image (python:3.11-slim) will be pulled automatically.
"""

from rlm.clients.base_lm import BaseLM
from rlm.core.lm_handler import LMHandler
from rlm.core.types import ModelUsageSummary, UsageSummary
from rlm.environments.docker_repl import DockerREPL


class MockLM(BaseLM):
    def __init__(self):
        super().__init__(model_name="mock")

    def completion(self, prompt):
        return f"Mock: {str(prompt)[:50]}"

    async def acompletion(self, prompt):
        return self.completion(prompt)

    def get_usage_summary(self):
        return UsageSummary({"mock": ModelUsageSummary(1, 10, 10)})

    def get_last_usage(self):
        return self.get_usage_summary()


def main():
    print("=" * 50)
    print("Docker REPL Example")
    print("=" * 50)

    # Basic execution (no LLM)
    print("\n[1] Basic code execution")
    with DockerREPL() as repl:
        result = repl.execute_code("x = 1 + 2")
        print(f"  x = 1 + 2 → locals: {result.locals}")

        result = repl.execute_code("print(x * 2)")
        print(f"  print(x * 2) → {result.stdout.strip()}")

    # With LLM handler
    print("\n[2] With LLM handler")
    with LMHandler(client=MockLM()) as handler:
        print(f"  Handler at {handler.address}")

        with DockerREPL(lm_handler_address=handler.address) as repl:
            result = repl.execute_code('r = llm_query("Hello!")')
            print(f"  llm_query → stderr: {result.stderr or '(none)'}")

            result = repl.execute_code("print(r)")
            print(f"  Response: {result.stdout.strip()}")

            result = repl.execute_code('rs = llm_query_batched(["Q1", "Q2"])')
            result = repl.execute_code("print(len(rs))")
            print(f"  Batched count: {result.stdout.strip()}")

    print("\n" + "=" * 50)
    print("Done!")


if __name__ == "__main__":
    main()
````

## File: examples/e2b_repl_example.py
````python
import os

from dotenv import load_dotenv

from rlm import RLM
from rlm.logger import RLMLogger

load_dotenv()

logger = RLMLogger(log_dir="./logs")

rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-5-nano",
    },
    environment="e2b",
    environment_kwargs={
        "timeout": 300,
    },
    max_depth=1,
    logger=logger,
    verbose=True,
)

result = rlm.completion("Using your code, solve 2^(2^(2^(2))). Show your work in Python.")
print(result.response)
````

## File: examples/lm_in_prime_repl.py
````python
"""
Example: Using llm_query() from within a Prime Intellect Sandbox.

This demonstrates the LM Handler + PrimeREPL integration where code
running in a cloud sandbox can query the LLM via the HTTP broker pattern.
"""

import os

from dotenv import load_dotenv

from rlm.clients.portkey import PortkeyClient
from rlm.core.lm_handler import LMHandler
from rlm.environments.prime_repl import PrimeREPL

load_dotenv()

setup_code = """
secret = "1424424"
"""

context_payload = """
This is a test context. It should print out, revealing the magic number to be 4.
"""

code = """
response = llm_query("What is 2 + 2? Reply with just the number.")
print(response)
print(type(response))
print(context)
print("Secret from setup code: ", secret)
"""


def main():
    api_key = os.environ.get("PORTKEY_API_KEY")
    if not api_key:
        print("Error: PORTKEY_API_KEY not set")
        return
    print(f"PORTKEY_API_KEY: {api_key[:8]}...")

    client = PortkeyClient(api_key=api_key, model_name="@openai/gpt-5-nano")
    print("Created Portkey client with model: @openai/gpt-5-nano")

    # Start LM Handler
    with LMHandler(client=client) as handler:
        print(f"LM Handler started at {handler.address}")

        # Create Prime REPL with handler connection
        print("\nCreating Prime sandbox...")
        with PrimeREPL(
            name="rlm-lm-demo",
            docker_image="python:3.11-slim",
            timeout_minutes=30,
            lm_handler_address=handler.address,
            context_payload=context_payload,
            setup_code=setup_code,
        ) as repl:
            print(f"PrimeREPL created, sandbox ID: {repl.sandbox_id}")
            print(f"Broker URL: {repl.broker_url}\n")

            # Run code that uses llm_query
            print(f"Executing: {code}")

            result = repl.execute_code(code)

            print(f"stdout: {result.stdout!r}")
            print(f"stderr: {result.stderr!r}")
            print(f"response variable: {result.locals.get('response')!r}")
            print(f"locals: {result.locals!r}")
            print(f"execution time: {result.execution_time:.3f}s")
            print(f"rlm_calls made: {len(result.rlm_calls)}")


if __name__ == "__main__":
    main()
````

## File: examples/prime_repl_example.py
````python
import os

from dotenv import load_dotenv

from rlm import RLM
from rlm.logger import RLMLogger

load_dotenv()

logger = RLMLogger(log_dir="./logs")

rlm = RLM(
    backend="openai",
    backend_kwargs={
        "api_key": os.getenv("OPENAI_API_KEY"),
        "model_name": "gpt-5-nano",
    },
    environment="prime",
    environment_kwargs={
        "name": "rlm-prime-demo",
        "docker_image": "python:3.11-slim",
        "timeout_minutes": 30,
    },
    max_depth=1,
    logger=logger,
    verbose=True,
)

result = rlm.completion("Using your code, solve 2^(2^(2^(2))). Show your work in Python.")
print(result.response)
````

## File: rlm/clients/gemini.py
````python
import os
from collections import defaultdict
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary

load_dotenv()

DEFAULT_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


class GeminiClient(BaseLM):
    """
    LM Client for running models with the Google Gemini API.
    Uses the official google-genai SDK.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = "gemini-2.5-flash",
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)

        if api_key is None:
            api_key = DEFAULT_GEMINI_API_KEY

        if api_key is None:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY env var or pass api_key."
            )

        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

        # Per-model usage tracking
        self.model_call_counts: dict[str, int] = defaultdict(int)
        self.model_input_tokens: dict[str, int] = defaultdict(int)
        self.model_output_tokens: dict[str, int] = defaultdict(int)
        self.model_total_tokens: dict[str, int] = defaultdict(int)

        # Last call tracking
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0

    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        contents, system_instruction = self._prepare_contents(prompt)

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Gemini client.")

        config = None
        if system_instruction:
            config = types.GenerateContentConfig(system_instruction=system_instruction)

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        self._track_cost(response, model)
        return response.text

    async def acompletion(
        self, prompt: str | list[dict[str, Any]], model: str | None = None
    ) -> str:
        contents, system_instruction = self._prepare_contents(prompt)

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Gemini client.")

        config = None
        if system_instruction:
            config = types.GenerateContentConfig(system_instruction=system_instruction)

        # google-genai SDK supports async via aio interface
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        self._track_cost(response, model)
        return response.text

    def _prepare_contents(
        self, prompt: str | list[dict[str, Any]]
    ) -> tuple[list[types.Content] | str, str | None]:
        """Prepare contents and extract system instruction for Gemini API."""
        system_instruction = None

        if isinstance(prompt, str):
            return prompt, None

        if isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            # Convert OpenAI-style messages to Gemini format
            contents = []
            for msg in prompt:
                role = msg.get("role")
                content = msg.get("content", "")

                if role == "system":
                    # Gemini handles system instruction separately
                    system_instruction = content
                elif role == "user":
                    contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
                elif role == "assistant":
                    # Gemini uses "model" instead of "assistant"
                    contents.append(types.Content(role="model", parts=[types.Part(text=content)]))
                else:
                    # Default to user role for unknown roles
                    contents.append(types.Content(role="user", parts=[types.Part(text=content)]))

            return contents, system_instruction

        raise ValueError(f"Invalid prompt type: {type(prompt)}")

    def _track_cost(self, response: types.GenerateContentResponse, model: str):
        self.model_call_counts[model] += 1

        # Extract token usage from response
        usage = response.usage_metadata
        if usage:
            input_tokens = usage.prompt_token_count or 0
            output_tokens = usage.candidates_token_count or 0

            self.model_input_tokens[model] += input_tokens
            self.model_output_tokens[model] += output_tokens
            self.model_total_tokens[model] += input_tokens + output_tokens

            # Track last call for handler to read
            self.last_prompt_tokens = input_tokens
            self.last_completion_tokens = output_tokens
        else:
            self.last_prompt_tokens = 0
            self.last_completion_tokens = 0

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model in self.model_call_counts:
            model_summaries[model] = ModelUsageSummary(
                total_calls=self.model_call_counts[model],
                total_input_tokens=self.model_input_tokens[model],
                total_output_tokens=self.model_output_tokens[model],
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self.last_prompt_tokens,
            total_output_tokens=self.last_completion_tokens,
        )
````

## File: rlm/core/__init__.py
````python

````

## File: rlm/environments/constants.py
````python
# Default packages for isolated REPL environments (Modal, Prime, etc.)

APT_PACKAGES = [
    "build-essential",
    "git",
    "curl",
    "wget",
    "libopenblas-dev",
    "liblapack-dev",
]

PIP_PACKAGES = [
    # Data science essentials
    "numpy>=1.26.0",
    "pandas>=2.1.0",
    "scipy>=1.11.0",
    # Math & symbolic computation
    "sympy>=1.12",
    # HTTP & APIs
    "requests>=2.31.0",
    "httpx>=0.25.0",
    "flask>=3.0.0",
    # Data formats
    "pyyaml>=6.0",
    "toml>=0.10.2",
    # Utilities
    "tqdm>=4.66.0",
    "python-dateutil>=2.8.2",
    "regex>=2023.0.0",
    # For state serialization
    "dill>=0.3.7",
]
````

## File: rlm/environments/e2b_repl.py
````python
"""
E2B REPL environment that runs Python code in E2B sandboxes.

Uses the E2B Code Interpreter SDK (https://e2b.dev/docs) for sandbox management.
Follows the same HTTP broker pattern as ModalREPL for LLM communication.
"""

import base64
import json
import textwrap
import threading
import time
from typing import Any

import requests
from e2b_code_interpreter import Sandbox

from rlm.core.comms_utils import LMRequest, send_lm_request, send_lm_request_batched
from rlm.core.types import REPLResult, RLMChatCompletion
from rlm.environments.base_env import IsolatedEnv

# =============================================================================
# Broker Server Script (runs inside sandbox, handles LLM request queue)
# =============================================================================

_BROKER_SCRIPT = textwrap.dedent(
    '''
import json
import threading
import uuid
from flask import Flask, request, jsonify

app = Flask(__name__)

# Request queue: {request_id: {"request": {...}, "response": None, "event": Event}}
pending_requests = {}
lock = threading.Lock()

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/enqueue", methods=["POST"])
def enqueue():
    """Called by sandbox code to submit an LLM request and wait for response."""
    data = request.json
    request_id = str(uuid.uuid4())
    event = threading.Event()

    with lock:
        pending_requests[request_id] = {
            "request": data,
            "response": None,
            "event": event,
        }

    # Wait for response (with timeout)
    event.wait(timeout=300)

    with lock:
        entry = pending_requests.pop(request_id, None)

    if entry and entry["response"] is not None:
        return jsonify(entry["response"])
    else:
        return jsonify({"error": "Request timed out"}), 504

@app.route("/pending")
def get_pending():
    """Called by E2BREPL to get pending requests."""
    with lock:
        pending = [
            {"id": rid, "request": entry["request"]}
            for rid, entry in pending_requests.items()
            if entry["response"] is None
        ]
    return jsonify({"pending": pending})

@app.route("/respond", methods=["POST"])
def respond():
    """Called by E2BREPL to submit a response."""
    data = request.json
    request_id = data.get("id")
    response = data.get("response")

    with lock:
        if request_id in pending_requests:
            pending_requests[request_id]["response"] = response
            pending_requests[request_id]["event"].set()
            return jsonify({"status": "ok"})

    return jsonify({"error": "Request not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8889, threaded=True)
'''
)


# =============================================================================
# Execution Script (runs inside the sandbox for each code block)
# =============================================================================


def _build_exec_script(code: str, broker_port: int = 8888) -> str:
    """
    Build a script that executes code with state persistence.
    LLM queries go through the local broker server.
    """
    code_b64 = base64.b64encode(code.encode()).decode()

    return textwrap.dedent(
        f'''
import sys
import io
import json
import base64
import traceback
import os
import requests

try:
    import dill
except ImportError:
    import pickle as dill

# =============================================================================
# LLM Query Functions (via local broker)
# =============================================================================

BROKER_URL = "http://127.0.0.1:{broker_port}"

def llm_query(prompt, model=None):
    """Query the LM via the broker."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "single", "prompt": prompt, "model": model}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return f"Error: {{data['error']}}"
        return data.get("response", "Error: No response")
    except Exception as e:
        return f"Error: LM query failed - {{e}}"


def llm_query_batched(prompts, model=None):
    """Query the LM with multiple prompts."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "batched", "prompts": prompts, "model": model}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return [f"Error: {{data['error']}}"] * len(prompts)
        return data.get("responses", ["Error: No response"] * len(prompts))
    except Exception as e:
        return [f"Error: LM query failed - {{e}}"] * len(prompts)


# =============================================================================
# State Management
# =============================================================================

STATE_FILE = "/tmp/rlm_state.dill"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return dill.load(f)
        except:
            pass
    return {{}}

def save_state(state):
    clean_state = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            dill.dumps(v)
            clean_state[k] = v
        except:
            pass
    with open(STATE_FILE, "wb") as f:
        dill.dump(clean_state, f)

def serialize_locals(state):
    result = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            result[k] = repr(v)
        except:
            result[k] = f"<{{type(v).__name__}}>"
    return result

# =============================================================================
# Execution
# =============================================================================

_locals = load_state()

def FINAL_VAR(variable_name):
    variable_name = variable_name.strip().strip("\\"\\'")
    if variable_name in _locals:
        return str(_locals[variable_name])
    return f"Error: Variable '{{variable_name}}' not found"

_globals = {{
    "__builtins__": __builtins__,
    "__name__": "__main__",
    "llm_query": llm_query,
    "llm_query_batched": llm_query_batched,
    "FINAL_VAR": FINAL_VAR,
}}

code = base64.b64decode("{code_b64}").decode()

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
old_stdout, old_stderr = sys.stdout, sys.stderr

try:
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    combined = {{**_globals, **_locals}}
    exec(code, combined, combined)
    for key, value in combined.items():
        if key not in _globals and not key.startswith("_"):
            _locals[key] = value
except Exception as e:
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout = old_stdout
    sys.stderr = old_stderr

save_state(_locals)

result = {{
    "stdout": stdout_buf.getvalue(),
    "stderr": stderr_buf.getvalue(),
    "locals": serialize_locals(_locals),
}}
print(json.dumps(result))
'''
    )


class E2BREPL(IsolatedEnv):
    """
    E2B REPL environment that runs Python code in E2B sandboxes.

    Uses E2B's public URL feature for LLM communication:
    - Sandbox runs a broker server exposed via get_host()
    - E2BREPL polls the broker for pending LLM requests
    - E2BREPL forwards requests to the LM handler and posts responses back
    """

    BROKER_PORT = 8889  # Use 8889 since E2B Code Interpreter uses 8888 for Jupyter

    def __init__(
        self,
        timeout: int = 300,  # 5 minutes default (E2B uses seconds)
        lm_handler_address: tuple[str, int] | None = None,
        context_payload: dict | list | str | None = None,
        setup_code: str | None = None,
        persistent: bool = False,
        **kwargs: Any,
    ):
        if persistent:
            raise NotImplementedError(
                "Persistent REPLs are currently not supported for environment: E2BREPL"
            )
        super().__init__(persistent=persistent, **kwargs)

        self.timeout = timeout
        self.lm_handler_address = lm_handler_address

        # Sandbox state
        self.sandbox: Sandbox | None = None
        self.sandbox_id: str | None = None
        self.broker_url: str | None = None
        self.broker_process = None

        # Polling thread for LLM requests
        self.poller_thread: threading.Thread | None = None
        self.poller_stop = threading.Event()
        self.pending_llm_calls: list[RLMChatCompletion] = []
        self._calls_lock = threading.Lock()

        self.setup()

        if context_payload is not None:
            self.load_context(context_payload)

        if setup_code:
            self.execute_code(setup_code)

    def setup(self):
        """Create the E2B sandbox, broker, and start polling."""
        # Create the sandbox using the recommended Sandbox.create() API
        self.sandbox = Sandbox.create(timeout=self.timeout)
        self.sandbox_id = self.sandbox.sandbox_id

        # Install dependencies for the broker
        self.sandbox.commands.run("pip install flask requests dill")

        # Write the broker script to the sandbox
        self.sandbox.files.write("/tmp/broker.py", _BROKER_SCRIPT)

        # Start the broker as a background process
        self.broker_process = self.sandbox.commands.run(
            "python /tmp/broker.py",
            background=True,
        )

        # Wait for broker to be ready
        self._wait_for_broker()

        # Get the public URL for the broker port
        host = self.sandbox.get_host(self.BROKER_PORT)
        self.broker_url = f"https://{host}"

        # Start polling thread if we have an LM handler
        if self.lm_handler_address and self.broker_url:
            self.poller_stop.clear()
            self.poller_thread = threading.Thread(target=self._poll_broker, daemon=True)
            self.poller_thread.start()

    def _wait_for_broker(self, max_attempts: int = 30):
        """Wait for the broker to be ready by checking health endpoint."""
        health_check_cmd = (
            f'python -c "import requests; '
            f"r = requests.get('http://127.0.0.1:{self.BROKER_PORT}/health', timeout=2); "
            f'print(r.text)"'
        )

        for _ in range(max_attempts):
            time.sleep(1)
            try:
                result = self.sandbox.commands.run(health_check_cmd)
                if result.stdout and "ok" in result.stdout.lower():
                    return
            except Exception:
                pass

        raise RuntimeError("Broker failed to start within timeout")

    def _poll_broker(self):
        """Poll the broker for pending LLM requests and handle them."""
        while not self.poller_stop.is_set():
            try:
                # Get pending requests
                resp = requests.get(
                    f"{self.broker_url}/pending",
                    timeout=5,
                )
                pending = resp.json().get("pending", [])

                for item in pending:
                    request_id = item["id"]
                    req_data = item["request"]

                    # Handle the request
                    response = self._handle_llm_request(req_data)

                    # Send response back
                    requests.post(
                        f"{self.broker_url}/respond",
                        json={"id": request_id, "response": response},
                        timeout=10,
                    )

            except requests.exceptions.RequestException:
                pass
            except Exception:
                pass

            time.sleep(0.1)

    def _handle_llm_request(self, req_data: dict) -> dict:
        """Handle an LLM request from the sandbox."""
        req_type = req_data.get("type")
        model = req_data.get("model")

        if req_type == "single":
            prompt = req_data.get("prompt")
            request = LMRequest(prompt=prompt, model=model)
            response = send_lm_request(self.lm_handler_address, request)

            if not response.success:
                return {"error": response.error}

            # Track the call
            with self._calls_lock:
                self.pending_llm_calls.append(response.chat_completion)

            return {"response": response.chat_completion.response}

        elif req_type == "batched":
            prompts = req_data.get("prompts", [])
            responses = send_lm_request_batched(self.lm_handler_address, prompts, model=model)

            results = []
            for resp in responses:
                if not resp.success:
                    results.append(f"Error: {resp.error}")
                else:
                    with self._calls_lock:
                        self.pending_llm_calls.append(resp.chat_completion)
                    results.append(resp.chat_completion.response)

            return {"responses": results}

        return {"error": "Unknown request type"}

    def load_context(self, context_payload: dict | list | str):
        """Load context into the sandbox environment."""
        if isinstance(context_payload, str):
            escaped = context_payload.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            context_code = f'context = """{escaped}"""'
        else:
            context_json = json.dumps(context_payload)
            escaped_json = context_json.replace("\\", "\\\\").replace("'", "\\'")
            context_code = f"import json; context = json.loads('{escaped_json}')"

        self.execute_code(context_code)

    def execute_code(self, code: str) -> REPLResult:
        """Execute code in the E2B sandbox and return result."""
        start_time = time.perf_counter()

        # Clear pending LLM calls
        with self._calls_lock:
            self.pending_llm_calls.clear()

        # Build and write the script to sandbox
        script = _build_exec_script(code, self.BROKER_PORT)
        self.sandbox.files.write("/tmp/run_script.py", script)

        # Run the script
        result = self.sandbox.commands.run("python /tmp/run_script.py", timeout=600)
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Collect LLM calls made during this execution
        with self._calls_lock:
            pending_calls = self.pending_llm_calls.copy()
            self.pending_llm_calls.clear()

        execution_time = time.perf_counter() - start_time

        # Parse the JSON result
        try:
            lines = stdout.strip().split("\n")
            result_json = lines[-1] if lines else "{}"
            parsed = json.loads(result_json)

            return REPLResult(
                stdout=parsed.get("stdout", ""),
                stderr=parsed.get("stderr", "") + stderr,
                locals=parsed.get("locals", {}),
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )
        except json.JSONDecodeError:
            return REPLResult(
                stdout=stdout,
                stderr=stderr or "Failed to parse execution result",
                locals={},
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )

    def cleanup(self):
        """Terminate the sandbox and stop polling."""
        # Stop the poller thread
        if self.poller_thread is not None:
            self.poller_stop.set()
            self.poller_thread.join(timeout=2)
            self.poller_thread = None

        # Kill the sandbox
        if self.sandbox is not None:
            try:
                self.sandbox.kill()
            except Exception:
                pass
            self.sandbox = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
````

## File: rlm/utils/__init__.py
````python

````

## File: tests/clients/test_gemini.py
````python
"""Tests for the Gemini client."""

import os
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv

from rlm.clients.gemini import GeminiClient
from rlm.core.types import ModelUsageSummary, UsageSummary

load_dotenv()


class TestGeminiClientUnit:
    """Unit tests that don't require API calls."""

    def test_init_with_api_key(self):
        """Test client initialization with explicit API key."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key", model_name="gemini-2.5-flash")
            assert client.model_name == "gemini-2.5-flash"

    def test_init_default_model(self):
        """Test client uses default model name."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            assert client.model_name == "gemini-2.5-flash"

    def test_init_requires_api_key(self):
        """Test client raises error when no API key provided."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("rlm.clients.gemini.DEFAULT_GEMINI_API_KEY", None):
                with pytest.raises(ValueError, match="Gemini API key is required"):
                    GeminiClient(api_key=None)

    def test_usage_tracking_initialization(self):
        """Test that usage tracking is properly initialized."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            assert client.model_call_counts == {}
            assert client.model_input_tokens == {}
            assert client.model_output_tokens == {}
            assert client.last_prompt_tokens == 0
            assert client.last_completion_tokens == 0

    def test_get_usage_summary_empty(self):
        """Test usage summary when no calls have been made."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            summary = client.get_usage_summary()
            assert isinstance(summary, UsageSummary)
            assert summary.model_usage_summaries == {}

    def test_get_last_usage(self):
        """Test last usage returns correct format."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            client.last_prompt_tokens = 100
            client.last_completion_tokens = 50
            usage = client.get_last_usage()
            assert isinstance(usage, ModelUsageSummary)
            assert usage.total_calls == 1
            assert usage.total_input_tokens == 100
            assert usage.total_output_tokens == 50

    def test_prepare_contents_string(self):
        """Test _prepare_contents with string input."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            contents, system = client._prepare_contents("Hello world")
            assert contents == "Hello world"
            assert system is None

    def test_prepare_contents_messages_with_system(self):
        """Test _prepare_contents extracts system message."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            messages = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ]
            contents, system = client._prepare_contents(messages)
            assert system == "You are helpful"
            assert len(contents) == 1
            assert contents[0].role == "user"

    def test_prepare_contents_role_mapping(self):
        """Test _prepare_contents maps assistant to model."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
                {"role": "user", "content": "How are you?"},
            ]
            contents, system = client._prepare_contents(messages)
            assert system is None
            assert len(contents) == 3
            assert contents[0].role == "user"
            assert contents[1].role == "model"  # assistant -> model
            assert contents[2].role == "user"

    def test_prepare_contents_invalid_type(self):
        """Test _prepare_contents raises on invalid input."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key")
            with pytest.raises(ValueError, match="Invalid prompt type"):
                client._prepare_contents(12345)

    def test_completion_requires_model(self):
        """Test completion raises when no model specified."""
        with patch("rlm.clients.gemini.genai.Client"):
            client = GeminiClient(api_key="test-key", model_name=None)
            with pytest.raises(ValueError, match="Model name is required"):
                client.completion("Hello")

    def test_completion_with_mocked_response(self):
        """Test completion with mocked API response."""
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini!"
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5

        with patch("rlm.clients.gemini.genai.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_class.return_value = mock_client

            client = GeminiClient(api_key="test-key", model_name="gemini-2.5-flash")
            result = client.completion("Hello")

            assert result == "Hello from Gemini!"
            assert client.model_call_counts["gemini-2.5-flash"] == 1
            assert client.model_input_tokens["gemini-2.5-flash"] == 10
            assert client.model_output_tokens["gemini-2.5-flash"] == 5


class TestGeminiClientIntegration:
    """Integration tests that require a real API key."""

    @pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    )
    def test_simple_completion(self):
        """Test a simple completion with real API."""
        client = GeminiClient(model_name="gemini-2.5-flash")
        result = client.completion("What is 2+2? Reply with just the number.")
        assert "4" in result

        # Verify usage was tracked
        usage = client.get_usage_summary()
        assert "gemini-2.5-flash" in usage.model_usage_summaries
        assert usage.model_usage_summaries["gemini-2.5-flash"].total_calls == 1

    @pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    )
    def test_message_list_completion(self):
        """Test completion with message list format."""
        client = GeminiClient(model_name="gemini-2.5-flash")
        messages = [
            {"role": "system", "content": "You are a helpful math tutor."},
            {"role": "user", "content": "What is 5 * 5? Reply with just the number."},
        ]
        result = client.completion(messages)
        assert "25" in result

    @pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set",
    )
    async def test_async_completion(self):
        """Test async completion."""
        client = GeminiClient(model_name="gemini-2.5-flash")
        result = await client.acompletion("What is 3+3? Reply with just the number.")
        assert "6" in result


if __name__ == "__main__":
    # Run integration tests directly
    test = TestGeminiClientIntegration()
    print("Testing simple completion...")
    test.test_simple_completion()
    print("Testing message list completion...")
    test.test_message_list_completion()
    print("All integration tests passed!")
````

## File: tests/__init__.py
````python

````

## File: tests/mock_lm.py
````python
from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class MockLM(BaseLM):
    """Simple mock LM that echoes prompts."""

    def __init__(self):
        super().__init__(model_name="mock-model")

    def completion(self, prompt):
        return f"Mock response to: {prompt[:50]}"

    async def acompletion(self, prompt):
        return self.completion(prompt)

    def get_usage_summary(self):
        return UsageSummary(
            model_usage_summaries={
                "mock-model": ModelUsageSummary(
                    total_calls=1, total_input_tokens=10, total_output_tokens=10
                )
            }
        )

    def get_last_usage(self):
        return self.get_usage_summary()
````

## File: tests/test_local_repl_persistent.py
````python
"""Tests for LocalREPL persistence features.

These tests verify LocalREPL's multi-context and multi-history capabilities
which support the persistent=True mode in RLM for multi-turn conversations.
"""

from rlm.environments.local_repl import LocalREPL


class TestLocalREPLMultiContext:
    """Tests for multi-context support in persistent mode."""

    def test_add_context_versioning(self):
        """Test that add_context creates versioned variables."""
        repl = LocalREPL()
        repl.add_context("First", 0)
        repl.add_context("Second", 1)
        assert repl.locals["context_0"] == "First"
        assert repl.locals["context_1"] == "Second"
        assert repl.locals["context"] == "First"
        assert repl.get_context_count() == 2
        repl.cleanup()

    def test_update_handler_address(self):
        """Test handler address can be updated."""
        repl = LocalREPL(lm_handler_address=("127.0.0.1", 5000))
        repl.update_handler_address(("127.0.0.1", 6000))
        assert repl.lm_handler_address == ("127.0.0.1", 6000)
        repl.cleanup()

    def test_add_context_auto_increment(self):
        """Test that add_context auto-increments when no index provided."""
        repl = LocalREPL()
        idx1 = repl.add_context("First")
        idx2 = repl.add_context("Second")
        assert idx1 == 0
        assert idx2 == 1
        assert repl.locals["context_0"] == "First"
        assert repl.locals["context_1"] == "Second"
        assert repl.get_context_count() == 2
        repl.cleanup()

    def test_contexts_accessible_in_code(self):
        """Test that multiple contexts can be accessed in code execution."""
        repl = LocalREPL()
        repl.add_context("Document A content")
        repl.add_context("Document B content")

        result = repl.execute_code("combined = f'{context_0} + {context_1}'")
        assert result.stderr == ""
        assert repl.locals["combined"] == "Document A content + Document B content"
        repl.cleanup()

    def test_context_alias_points_to_first(self):
        """Test that 'context' always aliases context_0."""
        repl = LocalREPL()
        repl.add_context("First")
        repl.add_context("Second")
        repl.add_context("Third")

        result = repl.execute_code("is_first = context == context_0")
        assert result.stderr == ""
        assert repl.locals["is_first"] is True
        repl.cleanup()


class TestLocalREPLHistory:
    """Tests for message history storage in LocalREPL for persistent sessions."""

    def test_add_history_basic(self):
        """Test that add_history stores message history correctly."""
        repl = LocalREPL()

        history = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        index = repl.add_history(history)

        assert index == 0
        assert "history_0" in repl.locals
        assert "history" in repl.locals  # alias
        assert repl.locals["history_0"] == history
        assert repl.locals["history"] == history
        assert repl.get_history_count() == 1

        repl.cleanup()

    def test_add_multiple_histories(self):
        """Test adding multiple conversation histories."""
        repl = LocalREPL()

        history1 = [{"role": "user", "content": "First conversation"}]
        history2 = [{"role": "user", "content": "Second conversation"}]

        repl.add_history(history1)
        repl.add_history(history2)

        assert repl.get_history_count() == 2
        assert repl.locals["history_0"] == history1
        assert repl.locals["history_1"] == history2
        assert repl.locals["history"] == history1  # alias stays on first

        repl.cleanup()

    def test_history_accessible_via_code(self):
        """Test that stored history is accessible via code execution."""
        repl = LocalREPL()

        history = [{"role": "user", "content": "Test message"}]
        repl.add_history(history)

        result = repl.execute_code("msg = history[0]['content']")
        assert result.stderr == ""
        assert repl.locals["msg"] == "Test message"

        repl.cleanup()

    def test_history_is_copy(self):
        """Test that stored history is a copy, not a reference."""
        repl = LocalREPL()

        history = [{"role": "user", "content": "Original"}]
        repl.add_history(history)

        history[0]["content"] = "Modified"

        assert repl.locals["history_0"][0]["content"] == "Original"

        repl.cleanup()

    def test_can_iterate_histories_in_code(self):
        """Test iterating through multiple histories in code."""
        repl = LocalREPL()

        repl.add_history([{"role": "user", "content": "Query 1"}])
        repl.add_history([{"role": "user", "content": "Query 2"}])
        repl.add_history([{"role": "user", "content": "Query 3"}])

        code = """
all_contents = [
    history_0[0]['content'],
    history_1[0]['content'],
    history_2[0]['content'],
]
"""
        result = repl.execute_code(code)
        assert result.stderr == ""
        assert repl.locals["all_contents"] == ["Query 1", "Query 2", "Query 3"]

        repl.cleanup()


class TestLocalREPLPersistentState:
    """Tests for state persistence across multiple operations in a single REPL instance."""

    def test_variables_persist_with_contexts(self):
        """Variables and contexts should coexist."""
        repl = LocalREPL()

        repl.add_context("My context data")
        repl.execute_code("summary = context.upper()")
        assert repl.locals["summary"] == "MY CONTEXT DATA"

        repl.add_context("New context")

        assert repl.locals["summary"] == "MY CONTEXT DATA"
        assert repl.locals["context_1"] == "New context"

        repl.cleanup()

    def test_variables_persist_with_histories(self):
        """Variables and histories should coexist."""
        repl = LocalREPL()

        repl.add_history([{"role": "user", "content": "Hello"}])
        repl.execute_code("extracted = history[0]['content']")
        assert repl.locals["extracted"] == "Hello"

        repl.add_history([{"role": "user", "content": "World"}])

        assert repl.locals["extracted"] == "Hello"
        assert repl.locals["history_1"][0]["content"] == "World"

        repl.cleanup()

    def test_full_persistent_session_simulation(self):
        """Simulate a multi-turn persistent session."""
        repl = LocalREPL()

        repl.add_context("Document: Sales were $1000")
        repl.execute_code("sales = 1000")

        repl.add_context("Document: Costs were $400")
        result = repl.execute_code("profit = sales - 400")
        assert result.stderr == ""
        assert repl.locals["profit"] == 600

        repl.add_history(
            [
                {"role": "user", "content": "What were the sales?"},
                {"role": "assistant", "content": "Sales were $1000"},
            ]
        )

        code = """
summary = f"Sales: {context_0}, Costs: {context_1}, Profit: {profit}"
prev_question = history_0[0]['content']
"""
        result = repl.execute_code(code)
        assert result.stderr == ""
        assert "Profit: 600" in repl.locals["summary"]
        assert repl.locals["prev_question"] == "What were the sales?"

        assert repl.get_context_count() == 2
        assert repl.get_history_count() == 1

        repl.cleanup()
````

## File: tests/test_multi_turn_integration.py
````python
"""Integration tests for multi-turn persistent REPL sessions.

Tests that multiple LM completion calls in one RLM session:
1. Share the same environment
2. Accumulate contexts (context_0, context_1, ...)
3. Accumulate histories (history_0, history_1, ...)
4. Preserve variables across calls
5. Properly inform the model about available contexts/histories
"""

from unittest.mock import Mock, patch

import pytest

import rlm.core.rlm as rlm_module
from rlm import RLM
from rlm.core.types import ModelUsageSummary, UsageSummary


def create_mock_lm(responses: list[str]) -> Mock:
    """Create a mock LM that returns responses in order."""
    mock = Mock()
    mock.completion.side_effect = list(responses)
    mock.get_usage_summary.return_value = UsageSummary(
        model_usage_summaries={
            "mock": ModelUsageSummary(total_calls=1, total_input_tokens=100, total_output_tokens=50)
        }
    )
    mock.get_last_usage.return_value = mock.get_usage_summary.return_value
    return mock


class TestMultiTurnPersistentEnvironment:
    """Tests for environment persistence across completion calls."""

    def test_environment_reused_in_persistent_mode(self):
        """Verify the same environment instance is reused across completion calls."""
        responses = ["FINAL(answer from call)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("First context")
                first_env = rlm._persistent_env

                mock_lm.completion.side_effect = list(responses)

                rlm.completion("Second context")
                second_env = rlm._persistent_env

                assert first_env is second_env
                assert first_env is not None

    def test_context_accumulation_across_calls(self):
        """Verify contexts accumulate: context_0, context_1, etc."""
        responses = ["FINAL(got it)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("First document")
                mock_lm.completion.side_effect = list(responses)
                rlm.completion("Second document")
                mock_lm.completion.side_effect = list(responses)
                rlm.completion("Third document")

                env = rlm._persistent_env
                assert env.get_context_count() == 3
                assert env.locals["context_0"] == "First document"
                assert env.locals["context_1"] == "Second document"
                assert env.locals["context_2"] == "Third document"
                assert env.locals["context"] == "First document"

    def test_history_accumulation_across_calls(self):
        """Verify message histories accumulate: history_0, history_1, etc."""
        responses = ["FINAL(done)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("Context A")
                mock_lm.completion.side_effect = list(responses)
                rlm.completion("Context B")
                mock_lm.completion.side_effect = list(responses)
                rlm.completion("Context C")

                env = rlm._persistent_env
                assert env.get_history_count() == 3
                assert "history_0" in env.locals
                assert "history_1" in env.locals
                assert "history_2" in env.locals
                assert isinstance(env.locals["history_0"], list)
                assert len(env.locals["history_0"]) > 0
                assert env.locals["history"] == env.locals["history_0"]

    def test_variable_persistence_across_completions(self):
        """Variables computed in one completion should be available in subsequent ones."""
        first_responses = [
            "Let me compute something\n```repl\ncomputed_value = 42 * 2\nprint(computed_value)\n```",
            "FINAL(84)",
        ]
        second_responses = [
            "```repl\nresult = computed_value + 10\nprint(result)\n```",
            "FINAL(94)",
        ]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(first_responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("Compute 42 * 2")
                assert rlm._persistent_env.locals.get("computed_value") == 84

                mock_lm.completion.side_effect = list(second_responses)
                rlm.completion("Add 10 to the previous result")

                assert rlm._persistent_env.locals.get("computed_value") == 84
                assert rlm._persistent_env.locals.get("result") == 94


class TestMultiTurnPromptAwareness:
    """Tests that prompts correctly inform the model about contexts/histories."""

    def test_prompt_includes_context_count(self):
        """Model should be informed about available contexts."""
        responses = ["FINAL(ok)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("First")
                mock_lm.completion.side_effect = list(responses)
                rlm.completion("Second")

                last_prompt = mock_lm.completion.call_args[0][0]
                user_messages = [m for m in last_prompt if m.get("role") == "user"]
                user_content = " ".join(m.get("content", "") for m in user_messages)

                assert "2 contexts" in user_content or "context_0" in user_content

    def test_prompt_includes_history_count(self):
        """Model should be informed about available histories."""
        responses = ["FINAL(ok)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("First task")
                mock_lm.completion.side_effect = list(responses)
                rlm.completion("Second task")

                last_prompt = mock_lm.completion.call_args[0][0]
                user_messages = [m for m in last_prompt if m.get("role") == "user"]
                user_content = " ".join(m.get("content", "") for m in user_messages)

                assert "history" in user_content.lower()


class TestMultiTurnCodeExecution:
    """Tests for code execution in multi-turn sessions."""

    def test_can_access_previous_context_in_code(self):
        """Code should be able to reference earlier contexts."""
        first_responses = ["FINAL(first done)"]
        second_responses = [
            "```repl\nprint(f'First: {context_0}, Second: {context_1}')\n```",
            "FINAL(printed both)",
        ]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(first_responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("Document A")

                mock_lm.completion.side_effect = list(second_responses)
                rlm.completion("Document B")

                env = rlm._persistent_env
                assert env.locals["context_0"] == "Document A"
                assert env.locals["context_1"] == "Document B"

    def test_can_access_history_in_code(self):
        """Code should be able to reference stored histories."""
        first_responses = ["FINAL(first)"]
        second_responses = [
            "```repl\nprint(f'History entries: {len(history)}')\n```",
            "FINAL(accessed history)",
        ]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(first_responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("First query")

                mock_lm.completion.side_effect = list(second_responses)
                rlm.completion("Second query")

                env = rlm._persistent_env
                assert "history" in env.locals
                assert isinstance(env.locals["history"], list)


class TestNonPersistentMode:
    """Tests to ensure non-persistent mode still works correctly."""

    def test_non_persistent_creates_fresh_environment(self):
        """Non-persistent mode should create new environment each call."""
        responses = ["FINAL(done)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            rlm = RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=False,
            )

            rlm.completion("First")
            assert rlm._persistent_env is None

            mock_lm.completion.side_effect = list(responses)
            rlm.completion("Second")
            assert rlm._persistent_env is None

    def test_default_is_non_persistent(self):
        """Default behavior should be non-persistent."""
        rlm = RLM(
            backend="openai",
            backend_kwargs={"model_name": "test"},
        )
        assert rlm.persistent is False


class TestPersistentModeResourceManagement:
    """Tests for proper resource cleanup in persistent mode."""

    def test_context_manager_cleanup(self):
        """Environment should be cleaned up when exiting context manager."""
        responses = ["FINAL(done)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                rlm.completion("Test")
                assert rlm._persistent_env is not None

            assert rlm._persistent_env is None

    def test_explicit_close(self):
        """Calling close() should clean up persistent environment."""
        responses = ["FINAL(done)"]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(responses)
            mock_get_client.return_value = mock_lm

            rlm = RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            )
            rlm.completion("Test")
            assert rlm._persistent_env is not None

            rlm.close()
            assert rlm._persistent_env is None


class TestPersistentModeValidation:
    """Tests for persistent mode validation."""

    def test_unsupported_environment_raises_error(self):
        """Persistent mode should raise error for unsupported environments."""
        with pytest.raises(ValueError, match="persistent=True is not supported"):
            RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                environment="docker",  # Not supported for persistent
                persistent=True,
            )

    def test_local_environment_supported(self):
        """Local environment should support persistent mode."""
        # Should not raise
        rlm = RLM(
            backend="openai",
            backend_kwargs={"model_name": "test"},
            environment="local",
            persistent=True,
        )
        assert rlm.persistent is True


class TestMultiTurnEndToEnd:
    """End-to-end tests simulating realistic multi-turn usage."""

    def test_three_turn_conversation(self):
        """Simulate a 3-turn conversation with context accumulation."""
        turn1_responses = [
            "Looking at the first document\n```repl\ndoc1_summary = 'Has info about cats'\nprint(doc1_summary)\n```",
            "FINAL(Summarized first doc)",
        ]
        turn2_responses = [
            "Looking at second document and comparing\n```repl\ndoc2_summary = 'Has info about dogs'\nprint(f'Doc1: {doc1_summary}, Doc2: {doc2_summary}')\n```",
            "FINAL(Compared both docs)",
        ]
        turn3_responses = [
            "Final synthesis\n```repl\nfinal = f'Combined: {doc1_summary} and {doc2_summary} from context_2'\nprint(final)\n```",
            "FINAL(synthesized all)",
        ]

        with patch.object(rlm_module, "get_client") as mock_get_client:
            mock_lm = create_mock_lm(turn1_responses)
            mock_get_client.return_value = mock_lm

            with RLM(
                backend="openai",
                backend_kwargs={"model_name": "test"},
                persistent=True,
            ) as rlm:
                result1 = rlm.completion("First document about cats")
                assert "Summarized" in result1.response

                mock_lm.completion.side_effect = list(turn2_responses)
                result2 = rlm.completion("Second document about dogs")
                assert "Compared" in result2.response

                mock_lm.completion.side_effect = list(turn3_responses)
                result3 = rlm.completion("Synthesize everything")
                assert "synthesized" in result3.response

                env = rlm._persistent_env
                assert env.get_context_count() == 3
                assert env.get_history_count() == 3
                assert env.locals.get("doc1_summary") == "Has info about cats"
                assert env.locals.get("doc2_summary") == "Has info about dogs"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
````

## File: tests/test_types.py
````python
"""Tests for core types."""

from rlm.core.types import (
    CodeBlock,
    ModelUsageSummary,
    QueryMetadata,
    REPLResult,
    RLMIteration,
    RLMMetadata,
    UsageSummary,
    _serialize_value,
)


class TestSerializeValue:
    """Tests for _serialize_value helper."""

    def test_primitives(self):
        assert _serialize_value(None) is None
        assert _serialize_value(True) is True
        assert _serialize_value(42) == 42
        assert _serialize_value(3.14) == 3.14
        assert _serialize_value("hello") == "hello"

    def test_list(self):
        result = _serialize_value([1, 2, "three"])
        assert result == [1, 2, "three"]

    def test_dict(self):
        result = _serialize_value({"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_callable(self):
        def my_func():
            pass

        result = _serialize_value(my_func)
        assert "function" in result.lower()
        assert "my_func" in result


class TestModelUsageSummary:
    """Tests for ModelUsageSummary."""

    def test_to_dict(self):
        summary = ModelUsageSummary(
            total_calls=10, total_input_tokens=1000, total_output_tokens=500
        )
        d = summary.to_dict()
        assert d["total_calls"] == 10
        assert d["total_input_tokens"] == 1000
        assert d["total_output_tokens"] == 500

    def test_from_dict(self):
        data = {
            "total_calls": 5,
            "total_input_tokens": 200,
            "total_output_tokens": 100,
        }
        summary = ModelUsageSummary.from_dict(data)
        assert summary.total_calls == 5
        assert summary.total_input_tokens == 200
        assert summary.total_output_tokens == 100


class TestUsageSummary:
    """Tests for UsageSummary."""

    def test_to_dict(self):
        model_summary = ModelUsageSummary(
            total_calls=1, total_input_tokens=10, total_output_tokens=5
        )
        summary = UsageSummary(model_usage_summaries={"gpt-4": model_summary})
        d = summary.to_dict()
        assert "gpt-4" in d["model_usage_summaries"]

    def test_from_dict(self):
        data = {
            "model_usage_summaries": {
                "gpt-4": {
                    "total_calls": 2,
                    "total_input_tokens": 50,
                    "total_output_tokens": 25,
                }
            }
        }
        summary = UsageSummary.from_dict(data)
        assert "gpt-4" in summary.model_usage_summaries
        assert summary.model_usage_summaries["gpt-4"].total_calls == 2


class TestREPLResult:
    """Tests for REPLResult."""

    def test_basic_creation(self):
        result = REPLResult(stdout="output", stderr="", locals={"x": 1})
        assert result.stdout == "output"
        assert result.stderr == ""
        assert result.locals == {"x": 1}

    def test_to_dict(self):
        result = REPLResult(stdout="hello", stderr="", locals={"num": 42}, execution_time=0.5)
        d = result.to_dict()
        assert d["stdout"] == "hello"
        assert d["locals"]["num"] == 42
        assert d["execution_time"] == 0.5

    def test_str_representation(self):
        result = REPLResult(stdout="test", stderr="", locals={})
        s = str(result)
        assert "REPLResult" in s
        assert "stdout=test" in s


class TestCodeBlock:
    """Tests for CodeBlock."""

    def test_to_dict(self):
        result = REPLResult(stdout="3", stderr="", locals={"x": 3})
        block = CodeBlock(code="x = 1 + 2", result=result)
        d = block.to_dict()
        assert d["code"] == "x = 1 + 2"
        assert d["result"]["stdout"] == "3"


class TestRLMIteration:
    """Tests for RLMIteration."""

    def test_basic_creation(self):
        iteration = RLMIteration(prompt="test prompt", response="test response", code_blocks=[])
        assert iteration.prompt == "test prompt"
        assert iteration.final_answer is None

    def test_with_final_answer(self):
        iteration = RLMIteration(
            prompt="test",
            response="FINAL(42)",
            code_blocks=[],
            final_answer=("FINAL", "42"),
        )
        assert iteration.final_answer == ("FINAL", "42")

    def test_to_dict(self):
        result = REPLResult(stdout="", stderr="", locals={})
        block = CodeBlock(code="pass", result=result)
        iteration = RLMIteration(
            prompt="p",
            response="r",
            code_blocks=[block],
            iteration_time=1.5,
        )
        d = iteration.to_dict()
        assert d["prompt"] == "p"
        assert d["response"] == "r"
        assert len(d["code_blocks"]) == 1
        assert d["iteration_time"] == 1.5


class TestQueryMetadata:
    """Tests for QueryMetadata."""

    def test_string_prompt(self):
        meta = QueryMetadata("Hello, world!")
        assert meta.context_type == "str"
        assert meta.context_total_length == 13
        assert meta.context_lengths == [13]


class TestRLMMetadata:
    """Tests for RLMMetadata."""

    def test_to_dict(self):
        meta = RLMMetadata(
            root_model="gpt-4",
            max_depth=2,
            max_iterations=10,
            backend="openai",
            backend_kwargs={"api_key": "secret"},
            environment_type="local",
            environment_kwargs={},
        )
        d = meta.to_dict()
        assert d["root_model"] == "gpt-4"
        assert d["max_depth"] == 2
        assert d["backend"] == "openai"
````

## File: visualizer/public/file.svg
````xml
<svg fill="none" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M14.5 13.5V5.41a1 1 0 0 0-.3-.7L9.8.29A1 1 0 0 0 9.08 0H1.5v13.5A2.5 2.5 0 0 0 4 16h8a2.5 2.5 0 0 0 2.5-2.5m-1.5 0v-7H8v-5H3v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1M9.5 5V2.12L12.38 5zM5.13 5h-.62v1.25h2.12V5zm-.62 3h7.12v1.25H4.5zm.62 3h-.62v1.25h7.12V11z" clip-rule="evenodd" fill="#666" fill-rule="evenodd"/></svg>
````

## File: visualizer/public/globe.svg
````xml
<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><g clip-path="url(#a)"><path fill-rule="evenodd" clip-rule="evenodd" d="M10.27 14.1a6.5 6.5 0 0 0 3.67-3.45q-1.24.21-2.7.34-.31 1.83-.97 3.1M8 16A8 8 0 1 0 8 0a8 8 0 0 0 0 16m.48-1.52a7 7 0 0 1-.96 0H7.5a4 4 0 0 1-.84-1.32q-.38-.89-.63-2.08a40 40 0 0 0 3.92 0q-.25 1.2-.63 2.08a4 4 0 0 1-.84 1.31zm2.94-4.76q1.66-.15 2.95-.43a7 7 0 0 0 0-2.58q-1.3-.27-2.95-.43a18 18 0 0 1 0 3.44m-1.27-3.54a17 17 0 0 1 0 3.64 39 39 0 0 1-4.3 0 17 17 0 0 1 0-3.64 39 39 0 0 1 4.3 0m1.1-1.17q1.45.13 2.69.34a6.5 6.5 0 0 0-3.67-3.44q.65 1.26.98 3.1M8.48 1.5l.01.02q.41.37.84 1.31.38.89.63 2.08a40 40 0 0 0-3.92 0q.25-1.2.63-2.08a4 4 0 0 1 .85-1.32 7 7 0 0 1 .96 0m-2.75.4a6.5 6.5 0 0 0-3.67 3.44 29 29 0 0 1 2.7-.34q.31-1.83.97-3.1M4.58 6.28q-1.66.16-2.95.43a7 7 0 0 0 0 2.58q1.3.27 2.95.43a18 18 0 0 1 0-3.44m.17 4.71q-1.45-.12-2.69-.34a6.5 6.5 0 0 0 3.67 3.44q-.65-1.27-.98-3.1" fill="#666"/></g><defs><clipPath id="a"><path fill="#fff" d="M0 0h16v16H0z"/></clipPath></defs></svg>
````

## File: visualizer/public/next.svg
````xml
<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 394 80"><path fill="#000" d="M262 0h68.5v12.7h-27.2v66.6h-13.6V12.7H262V0ZM149 0v12.7H94v20.4h44.3v12.6H94v21h55v12.6H80.5V0h68.7zm34.3 0h-17.8l63.8 79.4h17.9l-32-39.7 32-39.6h-17.9l-23 28.6-23-28.6zm18.3 56.7-9-11-27.1 33.7h17.8l18.3-22.7z"/><path fill="#000" d="M81 79.3 17 0H0v79.3h13.6V17l50.2 62.3H81Zm252.6-.4c-1 0-1.8-.4-2.5-1s-1.1-1.6-1.1-2.6.3-1.8 1-2.5 1.6-1 2.6-1 1.8.3 2.5 1a3.4 3.4 0 0 1 .6 4.3 3.7 3.7 0 0 1-3 1.8zm23.2-33.5h6v23.3c0 2.1-.4 4-1.3 5.5a9.1 9.1 0 0 1-3.8 3.5c-1.6.8-3.5 1.3-5.7 1.3-2 0-3.7-.4-5.3-1s-2.8-1.8-3.7-3.2c-.9-1.3-1.4-3-1.4-5h6c.1.8.3 1.6.7 2.2s1 1.2 1.6 1.5c.7.4 1.5.5 2.4.5 1 0 1.8-.2 2.4-.6a4 4 0 0 0 1.6-1.8c.3-.8.5-1.8.5-3V45.5zm30.9 9.1a4.4 4.4 0 0 0-2-3.3 7.5 7.5 0 0 0-4.3-1.1c-1.3 0-2.4.2-3.3.5-.9.4-1.6 1-2 1.6a3.5 3.5 0 0 0-.3 4c.3.5.7.9 1.3 1.2l1.8 1 2 .5 3.2.8c1.3.3 2.5.7 3.7 1.2a13 13 0 0 1 3.2 1.8 8.1 8.1 0 0 1 3 6.5c0 2-.5 3.7-1.5 5.1a10 10 0 0 1-4.4 3.5c-1.8.8-4.1 1.2-6.8 1.2-2.6 0-4.9-.4-6.8-1.2-2-.8-3.4-2-4.5-3.5a10 10 0 0 1-1.7-5.6h6a5 5 0 0 0 3.5 4.6c1 .4 2.2.6 3.4.6 1.3 0 2.5-.2 3.5-.6 1-.4 1.8-1 2.4-1.7a4 4 0 0 0 .8-2.4c0-.9-.2-1.6-.7-2.2a11 11 0 0 0-2.1-1.4l-3.2-1-3.8-1c-2.8-.7-5-1.7-6.6-3.2a7.2 7.2 0 0 1-2.4-5.7 8 8 0 0 1 1.7-5 10 10 0 0 1 4.3-3.5c2-.8 4-1.2 6.4-1.2 2.3 0 4.4.4 6.2 1.2 1.8.8 3.2 2 4.3 3.4 1 1.4 1.5 3 1.5 5h-5.8z"/></svg>
````

## File: visualizer/public/vercel.svg
````xml
<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1155 1000"><path d="m577.3 0 577.4 1000H0z" fill="#fff"/></svg>
````

## File: visualizer/public/window.svg
````xml
<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill-rule="evenodd" clip-rule="evenodd" d="M1.5 2.5h13v10a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1zM0 1h16v11.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 0 12.5zm3.75 4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5M7 4.75a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0m1.75.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5" fill="#666"/></svg>
````

## File: visualizer/src/app/page.tsx
````typescript
import { Dashboard } from '@/components/Dashboard';

export default function Home() {
  return <Dashboard />;
}
````

## File: visualizer/src/components/ui/accordion.tsx
````typescript
"use client"

import * as React from "react"
import * as AccordionPrimitive from "@radix-ui/react-accordion"
import { ChevronDownIcon } from "lucide-react"

import { cn } from "@/lib/utils"

function Accordion({
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Root>) {
  return <AccordionPrimitive.Root data-slot="accordion" {...props} />
}

function AccordionItem({
  className,
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Item>) {
  return (
    <AccordionPrimitive.Item
      data-slot="accordion-item"
      className={cn("border-b last:border-b-0", className)}
      {...props}
    />
  )
}

function AccordionTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Trigger>) {
  return (
    <AccordionPrimitive.Header className="flex">
      <AccordionPrimitive.Trigger
        data-slot="accordion-trigger"
        className={cn(
          "focus-visible:border-ring focus-visible:ring-ring/50 flex flex-1 items-start justify-between gap-4 rounded-md py-4 text-left text-sm font-medium transition-all outline-none hover:underline focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50 [&[data-state=open]>svg]:rotate-180",
          className
        )}
        {...props}
      >
        {children}
        <ChevronDownIcon className="text-muted-foreground pointer-events-none size-4 shrink-0 translate-y-0.5 transition-transform duration-200" />
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  )
}

function AccordionContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof AccordionPrimitive.Content>) {
  return (
    <AccordionPrimitive.Content
      data-slot="accordion-content"
      className="data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down overflow-hidden text-sm"
      {...props}
    >
      <div className={cn("pt-0 pb-4", className)}>{children}</div>
    </AccordionPrimitive.Content>
  )
}

export { Accordion, AccordionItem, AccordionTrigger, AccordionContent }
````

## File: visualizer/src/components/ui/badge.tsx
````typescript
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-full border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive transition-[color,box-shadow] overflow-hidden",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90",
        destructive:
          "border-transparent bg-destructive text-white [a&]:hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "span"

  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
````

## File: visualizer/src/components/ui/button.tsx
````typescript
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost:
          "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
````

## File: visualizer/src/components/ui/card.tsx
````typescript
import * as React from "react"

import { cn } from "@/lib/utils"

function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn(
        "bg-card text-card-foreground flex flex-col gap-6 rounded-xl border py-6 shadow-sm",
        className
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-2 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn("leading-none font-semibold", className)}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-6", className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center px-6 [.border-t]:pt-6", className)}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
````

## File: visualizer/src/components/ui/collapsible.tsx
````typescript
"use client"

import * as CollapsiblePrimitive from "@radix-ui/react-collapsible"

function Collapsible({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.Root>) {
  return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />
}

function CollapsibleTrigger({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleTrigger>) {
  return (
    <CollapsiblePrimitive.CollapsibleTrigger
      data-slot="collapsible-trigger"
      {...props}
    />
  )
}

function CollapsibleContent({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleContent>) {
  return (
    <CollapsiblePrimitive.CollapsibleContent
      data-slot="collapsible-content"
      {...props}
    />
  )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
````

## File: visualizer/src/components/ui/dropdown-menu.tsx
````typescript
"use client"

import * as React from "react"
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu"
import { CheckIcon, ChevronRightIcon, CircleIcon } from "lucide-react"

import { cn } from "@/lib/utils"

function DropdownMenu({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Root>) {
  return <DropdownMenuPrimitive.Root data-slot="dropdown-menu" {...props} />
}

function DropdownMenuPortal({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Portal>) {
  return (
    <DropdownMenuPrimitive.Portal data-slot="dropdown-menu-portal" {...props} />
  )
}

function DropdownMenuTrigger({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Trigger>) {
  return (
    <DropdownMenuPrimitive.Trigger
      data-slot="dropdown-menu-trigger"
      {...props}
    />
  )
}

function DropdownMenuContent({
  className,
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Content>) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        className={cn(
          "bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 max-h-(--radix-dropdown-menu-content-available-height) min-w-[8rem] origin-(--radix-dropdown-menu-content-transform-origin) overflow-x-hidden overflow-y-auto rounded-md border p-1 shadow-md",
          className
        )}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  )
}

function DropdownMenuGroup({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Group>) {
  return (
    <DropdownMenuPrimitive.Group data-slot="dropdown-menu-group" {...props} />
  )
}

function DropdownMenuItem({
  className,
  inset,
  variant = "default",
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Item> & {
  inset?: boolean
  variant?: "default" | "destructive"
}) {
  return (
    <DropdownMenuPrimitive.Item
      data-slot="dropdown-menu-item"
      data-inset={inset}
      data-variant={variant}
      className={cn(
        "focus:bg-accent focus:text-accent-foreground data-[variant=destructive]:text-destructive data-[variant=destructive]:focus:bg-destructive/10 dark:data-[variant=destructive]:focus:bg-destructive/20 data-[variant=destructive]:focus:text-destructive data-[variant=destructive]:*:[svg]:!text-destructive [&_svg:not([class*='text-'])]:text-muted-foreground relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[inset]:pl-8 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuCheckboxItem({
  className,
  children,
  checked,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.CheckboxItem>) {
  return (
    <DropdownMenuPrimitive.CheckboxItem
      data-slot="dropdown-menu-checkbox-item"
      className={cn(
        "focus:bg-accent focus:text-accent-foreground relative flex cursor-default items-center gap-2 rounded-sm py-1.5 pr-2 pl-8 text-sm outline-hidden select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      checked={checked}
      {...props}
    >
      <span className="pointer-events-none absolute left-2 flex size-3.5 items-center justify-center">
        <DropdownMenuPrimitive.ItemIndicator>
          <CheckIcon className="size-4" />
        </DropdownMenuPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownMenuPrimitive.CheckboxItem>
  )
}

function DropdownMenuRadioGroup({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.RadioGroup>) {
  return (
    <DropdownMenuPrimitive.RadioGroup
      data-slot="dropdown-menu-radio-group"
      {...props}
    />
  )
}

function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.RadioItem>) {
  return (
    <DropdownMenuPrimitive.RadioItem
      data-slot="dropdown-menu-radio-item"
      className={cn(
        "focus:bg-accent focus:text-accent-foreground relative flex cursor-default items-center gap-2 rounded-sm py-1.5 pr-2 pl-8 text-sm outline-hidden select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <span className="pointer-events-none absolute left-2 flex size-3.5 items-center justify-center">
        <DropdownMenuPrimitive.ItemIndicator>
          <CircleIcon className="size-2 fill-current" />
        </DropdownMenuPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownMenuPrimitive.RadioItem>
  )
}

function DropdownMenuLabel({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Label> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.Label
      data-slot="dropdown-menu-label"
      data-inset={inset}
      className={cn(
        "px-2 py-1.5 text-sm font-medium data-[inset]:pl-8",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuSeparator({
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>) {
  return (
    <DropdownMenuPrimitive.Separator
      data-slot="dropdown-menu-separator"
      className={cn("bg-border -mx-1 my-1 h-px", className)}
      {...props}
    />
  )
}

function DropdownMenuShortcut({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="dropdown-menu-shortcut"
      className={cn(
        "text-muted-foreground ml-auto text-xs tracking-widest",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuSub({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Sub>) {
  return <DropdownMenuPrimitive.Sub data-slot="dropdown-menu-sub" {...props} />
}

function DropdownMenuSubTrigger({
  className,
  inset,
  children,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.SubTrigger> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.SubTrigger
      data-slot="dropdown-menu-sub-trigger"
      data-inset={inset}
      className={cn(
        "focus:bg-accent focus:text-accent-foreground data-[state=open]:bg-accent data-[state=open]:text-accent-foreground [&_svg:not([class*='text-'])]:text-muted-foreground flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-[inset]:pl-8 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children}
      <ChevronRightIcon className="ml-auto size-4" />
    </DropdownMenuPrimitive.SubTrigger>
  )
}

function DropdownMenuSubContent({
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.SubContent>) {
  return (
    <DropdownMenuPrimitive.SubContent
      data-slot="dropdown-menu-sub-content"
      className={cn(
        "bg-popover text-popover-foreground data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 min-w-[8rem] origin-(--radix-dropdown-menu-content-transform-origin) overflow-hidden rounded-md border p-1 shadow-lg",
        className
      )}
      {...props}
    />
  )
}

export {
  DropdownMenu,
  DropdownMenuPortal,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
}
````

## File: visualizer/src/components/ui/resizable.tsx
````typescript
"use client"

import * as React from "react"
import { GripVerticalIcon } from "lucide-react"
import { Group, Panel, Separator } from "react-resizable-panels"

import { cn } from "@/lib/utils"

function ResizablePanelGroup({
  className,
  ...props
}: React.ComponentProps<typeof Group>) {
  return (
    <Group
      data-slot="resizable-panel-group"
      className={cn(
        "flex h-full w-full data-[panel-group-direction=vertical]:flex-col",
        className
      )}
      {...props}
    />
  )
}

function ResizablePanel({
  ...props
}: React.ComponentProps<typeof Panel>) {
  return <Panel data-slot="resizable-panel" {...props} />
}

function ResizableHandle({
  withHandle,
  className,
  ...props
}: React.ComponentProps<typeof Separator> & {
  withHandle?: boolean
}) {
  return (
    <Separator
      data-slot="resizable-handle"
      className={cn(
        "bg-border focus-visible:ring-ring relative flex w-px items-center justify-center after:absolute after:inset-y-0 after:left-1/2 after:w-1 after:-translate-x-1/2 focus-visible:ring-1 focus-visible:ring-offset-1 focus-visible:outline-hidden data-[panel-group-direction=vertical]:h-px data-[panel-group-direction=vertical]:w-full data-[panel-group-direction=vertical]:after:left-0 data-[panel-group-direction=vertical]:after:h-1 data-[panel-group-direction=vertical]:after:w-full data-[panel-group-direction=vertical]:after:translate-x-0 data-[panel-group-direction=vertical]:after:-translate-y-1/2 [&[data-panel-group-direction=vertical]>div]:rotate-90",
        className
      )}
      {...props}
    >
      {withHandle && (
        <div className="bg-border z-10 flex h-4 w-3 items-center justify-center rounded-xs border">
          <GripVerticalIcon className="size-2.5" />
        </div>
      )}
    </Separator>
  )
}

export { ResizablePanelGroup, ResizablePanel, ResizableHandle }
````

## File: visualizer/src/components/ui/scroll-area.tsx
````typescript
"use client"

import * as React from "react"
import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area"

import { cn } from "@/lib/utils"

function ScrollArea({
  className,
  children,
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.Root>) {
  return (
    <ScrollAreaPrimitive.Root
      data-slot="scroll-area"
      className={cn("relative", className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        data-slot="scroll-area-viewport"
        className="focus-visible:ring-ring/50 size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:outline-1"
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollBar />
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

function ScrollBar({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>) {
  return (
    <ScrollAreaPrimitive.ScrollAreaScrollbar
      data-slot="scroll-area-scrollbar"
      orientation={orientation}
      className={cn(
        "flex touch-none p-px transition-colors select-none",
        orientation === "vertical" &&
          "h-full w-2.5 border-l border-l-transparent",
        orientation === "horizontal" &&
          "h-2.5 flex-col border-t border-t-transparent",
        className
      )}
      {...props}
    >
      <ScrollAreaPrimitive.ScrollAreaThumb
        data-slot="scroll-area-thumb"
        className="bg-border relative flex-1 rounded-full"
      />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
  )
}

export { ScrollArea, ScrollBar }
````

## File: visualizer/src/components/ui/separator.tsx
````typescript
"use client"

import * as React from "react"
import * as SeparatorPrimitive from "@radix-ui/react-separator"

import { cn } from "@/lib/utils"

function Separator({
  className,
  orientation = "horizontal",
  decorative = true,
  ...props
}: React.ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      data-slot="separator"
      decorative={decorative}
      orientation={orientation}
      className={cn(
        "bg-border shrink-0 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
````

## File: visualizer/src/components/ui/tabs.tsx
````typescript
"use client"

import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"

import { cn } from "@/lib/utils"

function Tabs({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    />
  )
}

function TabsList({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        "bg-muted text-muted-foreground inline-flex h-9 w-fit items-center justify-center rounded-lg p-[3px]",
        className
      )}
      {...props}
    />
  )
}

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "data-[state=active]:bg-background dark:data-[state=active]:text-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:outline-ring dark:data-[state=active]:border-input dark:data-[state=active]:bg-input/30 text-foreground dark:text-muted-foreground inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:ring-[3px] focus-visible:outline-1 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:shadow-sm [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("flex-1 outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
````

## File: visualizer/src/components/ui/tooltip.tsx
````typescript
"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"

import { cn } from "@/lib/utils"

function TooltipProvider({
  delayDuration = 0,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot="tooltip-provider"
      delayDuration={delayDuration}
      {...props}
    />
  )
}

function Tooltip({
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return (
    <TooltipProvider>
      <TooltipPrimitive.Root data-slot="tooltip" {...props} />
    </TooltipProvider>
  )
}

function TooltipTrigger({
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

function TooltipContent({
  className,
  sideOffset = 0,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        className={cn(
          "bg-foreground text-background animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 w-fit origin-(--radix-tooltip-content-transform-origin) rounded-md px-3 py-1.5 text-xs text-balance",
          className
        )}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow className="bg-foreground fill-foreground z-50 size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px]" />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
````

## File: visualizer/src/components/CodeWithLineNumbers.tsx
````typescript
'use client';

import { SyntaxHighlight } from './SyntaxHighlight';

interface CodeWithLineNumbersProps {
  code: string;
  language?: 'python' | 'text';
  startLine?: number;
}

export function CodeWithLineNumbers({ 
  code, 
  language = 'python',
  startLine = 1 
}: CodeWithLineNumbersProps) {
  const lines = code.split('\n');
  const lineNumberWidth = Math.max(2, String(lines.length + startLine - 1).length);
  
  return (
    <div className="flex">
      {/* Line numbers */}
      <div className="flex-shrink-0 pr-4 border-r border-border/30 select-none">
        {lines.map((_, idx) => (
          <div 
            key={idx} 
            className="text-right text-muted-foreground/50 text-xs leading-relaxed"
            style={{ width: `${lineNumberWidth}ch` }}
          >
            {idx + startLine}
          </div>
        ))}
      </div>
      
      {/* Code */}
      <div className="flex-1 pl-4 overflow-x-auto">
        <SyntaxHighlight code={code} language={language} />
      </div>
    </div>
  );
}
````

## File: visualizer/src/components/FileUploader.tsx
````typescript
'use client';

import { useCallback, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface FileUploaderProps {
  onFileLoaded: (fileName: string, content: string) => void;
}

export function FileUploader({ onFileLoaded }: FileUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.jsonl')) {
      alert('Please upload a .jsonl file');
      return;
    }

    setIsLoading(true);
    try {
      const content = await file.text();
      onFileLoaded(file.name, content);
    } catch (error) {
      console.error('Error reading file:', error);
      alert('Failed to read file');
    } finally {
      setIsLoading(false);
    }
  }, [onFileLoaded]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    const file = e.dataTransfer.files[0];
    if (file) {
      handleFile(file);
    }
  }, [handleFile]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFile(file);
    }
  }, [handleFile]);

  return (
    <Card 
      className={cn(
        'border-2 border-dashed transition-all duration-200',
        isDragging 
          ? 'border-[oklch(0.65_0.18_145)] bg-[oklch(0.65_0.18_145/0.05)] scale-[1.01]' 
          : 'border-[oklch(0.25_0.03_145)] hover:border-[oklch(0.5_0.12_145)]'
      )}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <CardContent className="p-8 text-center">
        <div className={cn(
          'w-14 h-14 mx-auto mb-4 rounded-xl flex items-center justify-center transition-all border',
          isDragging 
            ? 'bg-[oklch(0.65_0.18_145/0.15)] border-[oklch(0.65_0.18_145/0.3)] scale-105' 
            : 'bg-muted/20 border-[oklch(0.25_0.03_145)]'
        )}>
          <span className={cn(
            'text-2xl transition-colors font-mono',
            isDragging ? 'text-[oklch(0.65_0.18_145)]' : 'text-muted-foreground'
          )}>
            {isLoading ? '...' : '↑'}
          </span>
        </div>
        
        <h3 className="text-sm font-medium mb-1">
          {isDragging ? 'Drop here' : 'Upload .jsonl'}
        </h3>
        <p className="text-muted-foreground text-xs mb-4">
          Drag & drop or click to browse
        </p>
        
        <input
          type="file"
          id="file-upload"
          accept=".jsonl"
          onChange={handleFileSelect}
          className="hidden"
        />
        <Button 
          asChild 
          size="sm"
          className="bg-[oklch(0.55_0.15_145)] hover:bg-[oklch(0.6_0.17_145)] text-white"
        >
          <label htmlFor="file-upload" className="cursor-pointer">
            {isLoading ? 'Loading...' : 'Choose File'}
          </label>
        </Button>
      </CardContent>
    </Card>
  );
}
````

## File: visualizer/src/components/SyntaxHighlight.tsx
````typescript
'use client';

import { useMemo } from 'react';

interface SyntaxHighlightProps {
  code: string;
  language?: 'python' | 'text';
}

// Simple Python syntax highlighting
function highlightPython(code: string): React.ReactNode[] {
  const keywords = [
    'def', 'class', 'if', 'elif', 'else', 'for', 'while', 'try', 'except', 
    'finally', 'with', 'as', 'import', 'from', 'return', 'yield', 'raise',
    'pass', 'break', 'continue', 'and', 'or', 'not', 'in', 'is', 'None',
    'True', 'False', 'lambda', 'async', 'await', 'global', 'nonlocal'
  ];
  
  const builtins = [
    'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set',
    'tuple', 'type', 'isinstance', 'enumerate', 'zip', 'map', 'filter',
    'sorted', 'reversed', 'sum', 'min', 'max', 'abs', 'open', 'input'
  ];
  
  const lines = code.split('\n');
  const result: React.ReactNode[] = [];
  
  lines.forEach((line, lineIdx) => {
    let remaining = line;
    const lineElements: React.ReactNode[] = [];
    let charIdx = 0;
    
    while (remaining.length > 0) {
      // Comments
      if (remaining.startsWith('#')) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-comment`} className="text-[oklch(0.55_0.05_260)]">
            {remaining}
          </span>
        );
        remaining = '';
        continue;
      }
      
      // Strings (single and double quotes, including f-strings)
      const stringMatch = remaining.match(/^(f?r?)(["'])(?:(?!\2)[^\\]|\\.)*\2/);
      if (stringMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-string`} className="text-[oklch(0.75_0.15_145)]">
            {stringMatch[0]}
          </span>
        );
        remaining = remaining.slice(stringMatch[0].length);
        charIdx += stringMatch[0].length;
        continue;
      }
      
      // Triple-quoted strings
      const tripleStringMatch = remaining.match(/^(["']{3})[\s\S]*?\1/);
      if (tripleStringMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-triplestring`} className="text-[oklch(0.75_0.15_145)]">
            {tripleStringMatch[0]}
          </span>
        );
        remaining = remaining.slice(tripleStringMatch[0].length);
        charIdx += tripleStringMatch[0].length;
        continue;
      }
      
      // Numbers
      const numberMatch = remaining.match(/^\b\d+\.?\d*\b/);
      if (numberMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-number`} className="text-[oklch(0.85_0.15_45)]">
            {numberMatch[0]}
          </span>
        );
        remaining = remaining.slice(numberMatch[0].length);
        charIdx += numberMatch[0].length;
        continue;
      }
      
      // Keywords
      const keywordMatch = remaining.match(new RegExp(`^\\b(${keywords.join('|')})\\b`));
      if (keywordMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-keyword`} className="text-[oklch(0.7_0.2_320)]">
            {keywordMatch[0]}
          </span>
        );
        remaining = remaining.slice(keywordMatch[0].length);
        charIdx += keywordMatch[0].length;
        continue;
      }
      
      // Builtins
      const builtinMatch = remaining.match(new RegExp(`^\\b(${builtins.join('|')})\\b`));
      if (builtinMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-builtin`} className="text-[oklch(0.8_0.15_195)]">
            {builtinMatch[0]}
          </span>
        );
        remaining = remaining.slice(builtinMatch[0].length);
        charIdx += builtinMatch[0].length;
        continue;
      }
      
      // Function definitions
      const funcMatch = remaining.match(/^(\w+)(?=\()/);
      if (funcMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-func`} className="text-[oklch(0.85_0.12_220)]">
            {funcMatch[0]}
          </span>
        );
        remaining = remaining.slice(funcMatch[0].length);
        charIdx += funcMatch[0].length;
        continue;
      }
      
      // Operators and punctuation
      const operatorMatch = remaining.match(/^[+\-*/%=<>!&|^~@:.,;()\[\]{}]+/);
      if (operatorMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-operator`} className="text-[oklch(0.7_0.1_260)]">
            {operatorMatch[0]}
          </span>
        );
        remaining = remaining.slice(operatorMatch[0].length);
        charIdx += operatorMatch[0].length;
        continue;
      }
      
      // Regular text/identifiers
      const textMatch = remaining.match(/^[^\s+\-*/%=<>!&|^~@:.,;()\[\]{}#"']+/);
      if (textMatch) {
        lineElements.push(
          <span key={`${lineIdx}-${charIdx}-text`} className="text-foreground/90">
            {textMatch[0]}
          </span>
        );
        remaining = remaining.slice(textMatch[0].length);
        charIdx += textMatch[0].length;
        continue;
      }
      
      // Whitespace
      const wsMatch = remaining.match(/^\s+/);
      if (wsMatch) {
        lineElements.push(wsMatch[0]);
        remaining = remaining.slice(wsMatch[0].length);
        charIdx += wsMatch[0].length;
        continue;
      }
      
      // Fallback: consume one character
      lineElements.push(remaining[0]);
      remaining = remaining.slice(1);
      charIdx++;
    }
    
    result.push(
      <div key={`line-${lineIdx}`} className="whitespace-pre">
        {lineElements}
      </div>
    );
  });
  
  return result;
}

export function SyntaxHighlight({ code, language = 'python' }: SyntaxHighlightProps) {
  const highlighted = useMemo(() => {
    if (language === 'python') {
      return highlightPython(code);
    }
    return <span className="text-foreground/90">{code}</span>;
  }, [code, language]);
  
  return <>{highlighted}</>;
}
````

## File: visualizer/src/components/ThemeProvider.tsx
````typescript
'use client';

import * as React from 'react';
import { ThemeProvider as NextThemesProvider } from 'next-themes';

type ThemeProviderProps = React.ComponentProps<typeof NextThemesProvider>;

export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
````

## File: visualizer/src/components/ThemeToggle.tsx
````typescript
'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

export function ThemeToggle() {
  const { setTheme, theme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <Button variant="ghost" size="sm" className="w-8 h-8 p-0">
        <span className="sr-only">Toggle theme</span>
      </Button>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button 
          variant="ghost" 
          size="sm" 
          className="w-8 h-8 p-0 hover:bg-primary/10"
        >
          {theme === 'light' ? (
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-amber-500"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2" />
              <path d="M12 20v2" />
              <path d="m4.93 4.93 1.41 1.41" />
              <path d="m17.66 17.66 1.41 1.41" />
              <path d="M2 12h2" />
              <path d="M20 12h2" />
              <path d="m6.34 17.66-1.41 1.41" />
              <path d="m19.07 4.93-1.41 1.41" />
            </svg>
          ) : (
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-primary"
            >
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
            </svg>
          )}
          <span className="sr-only">Toggle theme</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[120px]">
        <DropdownMenuItem 
          onClick={() => setTheme('light')}
          className="flex items-center gap-2 cursor-pointer"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2" />
            <path d="M12 20v2" />
            <path d="m4.93 4.93 1.41 1.41" />
            <path d="m17.66 17.66 1.41 1.41" />
            <path d="M2 12h2" />
            <path d="M20 12h2" />
            <path d="m6.34 17.66-1.41 1.41" />
            <path d="m19.07 4.93-1.41 1.41" />
          </svg>
          Light
        </DropdownMenuItem>
        <DropdownMenuItem 
          onClick={() => setTheme('dark')}
          className="flex items-center gap-2 cursor-pointer"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
          </svg>
          Dark
        </DropdownMenuItem>
        <DropdownMenuItem 
          onClick={() => setTheme('system')}
          className="flex items-center gap-2 cursor-pointer"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect width="20" height="14" x="2" y="3" rx="2" />
            <line x1="8" x2="16" y1="21" y2="21" />
            <line x1="12" x2="12" y1="17" y2="21" />
          </svg>
          System
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
````

## File: visualizer/src/lib/parse-logs.ts
````typescript
import { RLMIteration, RLMLogFile, LogMetadata, RLMConfigMetadata, extractFinalAnswer } from './types';

// Extract the context variable from code block locals
export function extractContextVariable(iterations: RLMIteration[]): string | null {
  for (const iter of iterations) {
    for (const block of iter.code_blocks) {
      if (block.result?.locals?.context) {
        const ctx = block.result.locals.context;
        if (typeof ctx === 'string') {
          return ctx;
        }
      }
    }
  }
  return null;
}

// Default config when metadata is not present (backwards compatibility)
function getDefaultConfig(): RLMConfigMetadata {
  return {
    root_model: null,
    max_depth: null,
    max_iterations: null,
    backend: null,
    backend_kwargs: null,
    environment_type: null,
    environment_kwargs: null,
    other_backends: null,
  };
}

export interface ParsedJSONL {
  iterations: RLMIteration[];
  config: RLMConfigMetadata;
}

export function parseJSONL(content: string): ParsedJSONL {
  const lines = content.trim().split('\n').filter(line => line.trim());
  const iterations: RLMIteration[] = [];
  let config: RLMConfigMetadata = getDefaultConfig();
  
  for (const line of lines) {
    try {
      const parsed = JSON.parse(line);
      
      // Check if this is a metadata entry
      if (parsed.type === 'metadata') {
        config = {
          root_model: parsed.root_model ?? null,
          max_depth: parsed.max_depth ?? null,
          max_iterations: parsed.max_iterations ?? null,
          backend: parsed.backend ?? null,
          backend_kwargs: parsed.backend_kwargs ?? null,
          environment_type: parsed.environment_type ?? null,
          environment_kwargs: parsed.environment_kwargs ?? null,
          other_backends: parsed.other_backends ?? null,
        };
      } else {
        // This is an iteration entry
        iterations.push(parsed as RLMIteration);
      }
    } catch (e) {
      console.error('Failed to parse line:', line, e);
    }
  }
  
  return { iterations, config };
}

export function extractContextQuestion(iterations: RLMIteration[]): string {
  if (iterations.length === 0) return 'No context found';
  
  const firstIteration = iterations[0];
  const prompt = firstIteration.prompt;
  
  // Look for user message that contains the actual question
  for (const msg of prompt) {
    if (msg.role === 'user' && msg.content) {
      // Try to extract quoted query
      const queryMatch = msg.content.match(/original query: "([^"]+)"/);
      if (queryMatch) {
        return queryMatch[1];
      }
      
      // Check if it contains the actual query pattern
      if (msg.content.includes('answer the prompt')) {
        continue;
      }
      
      // Take first substantial user message
      if (msg.content.length > 50 && msg.content.length < 500) {
        return msg.content.slice(0, 200) + (msg.content.length > 200 ? '...' : '');
      }
    }
  }
  
  // Fallback: look in system prompt for context info
  const systemMsg = prompt.find(m => m.role === 'system');
  if (systemMsg?.content) {
    const contextMatch = systemMsg.content.match(/context variable.*?:(.*?)(?:\n|$)/i);
    if (contextMatch) {
      return contextMatch[1].trim().slice(0, 200);
    }
  }
  
  // Check code block output for actual context
  for (const iter of iterations) {
    for (const block of iter.code_blocks) {
      if (block.result?.locals?.context) {
        const ctx = block.result.locals.context;
        if (typeof ctx === 'string' && ctx.length < 500) {
          return ctx;
        }
      }
    }
  }
  
  return 'Context available in REPL environment';
}

export function computeMetadata(iterations: RLMIteration[]): LogMetadata {
  let totalCodeBlocks = 0;
  let totalSubLMCalls = 0;
  let totalExecutionTime = 0;
  let hasErrors = false;
  let finalAnswer: string | null = null;
  
  for (const iter of iterations) {
    totalCodeBlocks += iter.code_blocks.length;
    
    // Use iteration_time if available, otherwise sum code block times
    if (iter.iteration_time != null) {
      totalExecutionTime += iter.iteration_time;
    } else {
      for (const block of iter.code_blocks) {
        if (block.result) {
          totalExecutionTime += block.result.execution_time || 0;
        }
      }
    }
    
    for (const block of iter.code_blocks) {
      if (block.result) {
        if (block.result.stderr) {
          hasErrors = true;
        }
        if (block.result.rlm_calls) {
          totalSubLMCalls += block.result.rlm_calls.length;
        }
      }
    }
    
    if (iter.final_answer) {
      finalAnswer = extractFinalAnswer(iter.final_answer);
    }
  }
  
  return {
    totalIterations: iterations.length,
    totalCodeBlocks,
    totalSubLMCalls,
    contextQuestion: extractContextQuestion(iterations),
    finalAnswer,
    totalExecutionTime,
    hasErrors,
  };
}

export function parseLogFile(fileName: string, content: string): RLMLogFile {
  const { iterations, config } = parseJSONL(content);
  const metadata = computeMetadata(iterations);
  
  return {
    fileName,
    filePath: fileName,
    iterations,
    metadata,
    config,
  };
}
````

## File: visualizer/src/lib/types.ts
````typescript
// Types matching the RLM log format

export interface RLMChatCompletion {
  prompt: string | Record<string, unknown>;
  response: string;
  prompt_tokens: number;
  completion_tokens: number;
  execution_time: number;
}

export interface REPLResult {
  stdout: string;
  stderr: string;
  locals: Record<string, unknown>;
  execution_time: number;
  rlm_calls: RLMChatCompletion[];
}

export interface CodeBlock {
  code: string;
  result: REPLResult;
}

export interface RLMIteration {
  type?: string;
  iteration: number;
  timestamp: string;
  prompt: Array<{ role: string; content: string }>;
  response: string;
  code_blocks: CodeBlock[];
  final_answer: string | [string, string] | null;
  iteration_time: number | null;
}

// Metadata saved at the start of a log file about RLM configuration
export interface RLMConfigMetadata {
  root_model: string | null;
  max_depth: number | null;
  max_iterations: number | null;
  backend: string | null;
  backend_kwargs: Record<string, unknown> | null;
  environment_type: string | null;
  environment_kwargs: Record<string, unknown> | null;
  other_backends: string[] | null;
}

export interface RLMLogFile {
  fileName: string;
  filePath: string;
  iterations: RLMIteration[];
  metadata: LogMetadata;
  config: RLMConfigMetadata;
}

export interface LogMetadata {
  totalIterations: number;
  totalCodeBlocks: number;
  totalSubLMCalls: number;
  contextQuestion: string;
  finalAnswer: string | null;
  totalExecutionTime: number;
  hasErrors: boolean;
}

export function extractFinalAnswer(answer: string | [string, string] | null): string | null {
  if (!answer) return null;
  if (Array.isArray(answer)) {
    return answer[1];
  }
  return answer;
}
````

## File: visualizer/src/lib/utils.ts
````typescript
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
````

## File: visualizer/.gitignore
````
# See https://help.github.com/articles/ignoring-files/ for more about ignoring files.

# dependencies
/node_modules
/.pnp
.pnp.*
.yarn/*
!.yarn/patches
!.yarn/plugins
!.yarn/releases
!.yarn/versions

# testing
/coverage

# next.js
/.next/
/out/

# production
/build

# misc
.DS_Store
*.pem

# debug
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.pnpm-debug.log*

# env files (can opt-in for committing if needed)
.env*

# vercel
.vercel

# typescript
*.tsbuildinfo
next-env.d.ts
````

## File: visualizer/components.json
````json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/app/globals.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  },
  "registries": {}
}
````

## File: visualizer/eslint.config.mjs
````javascript
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
````

## File: visualizer/next.config.ts
````typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
````

## File: visualizer/postcss.config.mjs
````javascript
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
````

## File: visualizer/README.md
````markdown
Vibe-coded visualizer with [shadcn](https://ui.shadcn.com) for viewing RLM trajectories.

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
````

## File: visualizer/tsconfig.json
````json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": [
    "next-env.d.ts",
    "**/*.ts",
    "**/*.tsx",
    ".next/types/**/*.ts",
    ".next/dev/types/**/*.ts",
    "**/*.mts"
  ],
  "exclude": ["node_modules"]
}
````

## File: .gitattributes
````
visualizer/** linguist-vendored
````

## File: .python-version
````
3.11
````

## File: CONTRIBUTING.md
````markdown
I'm too lazy to write up a stricter set of rules for PRs, but generally I just ask that you avoid touching `core/` files unless necessary. I'd like to keep the repo as minimal as possible for as long as possible so it's still easy for users to read the entire repo in a short sitting.

Generally though, I'll outline the things we 1) need to implement; 2) want to implement; 3) can dream about implementing. The state of this repo is that it should be fully functional for most use cases, but it isn't super fast or anything.

There are likely more things we'll want to do, but here are some things I've been meaning to tackle. 

## Urgent TODOs
- [ ] **Additional Sandboxes**. Any more interesting, commonly used sandboxes (e.g. Prime Sandboxes are WIP atm).
- [ ] **Persistent REPL across the client.** Currently, the REPL is only persistent across an RLM completion call, but for multi-turn settings we may want a `flag` to handle persistence. There's some trickiness here though, which is that after every turn, the input context will change / be added onto. I haven't decided yet (open to suggestions), but we could add `context_{x}` and tell the model that it has a new context or something in the next completion step.
- [ ] **Finding interesting benchmarks / examples we can provide to get started**.
- [ ] **Improve documentation**. See `docs/`.

Low-hanging fruit of the urgent TODOs:
- [ ] **Add better unit tests.** I have a Mock LM class inspired by `verifiers`, but we need more comprehensive unit tests. Generally these should be made with most PRs.
- [ ] **Do more comprehensive bug finding**: Just find bugs and report them, we'll try to squash them all

## Would-be-nice TODOs
- [ ] **Multi-modal / arbitrary input support.** As it stands, we just support `str` / standard LM dict messages, but we should generally support any type of picklable-inputs. We might want to think of clever ways to do this lazily as well.
- [ ] **File-system based environments**. Beyond REPLs, we can also think about supporting filesystem + bash as a new type of environment. There seems to be a lot of interest in this.
- [ ] **Improved UI for visualization**.
- [ ] **Improvements to what data gets stored, useful for training and statistics about RLMs**/

## "If you can tackle these, thanks LOL" TODOs
- [ ] **Pipelining / asynchrony of LM calls**. This could be a paper of its own IMO, but how we deal with LM calls and how we actually implement these recursive calls can have big implications. I suspect this might happen when the repo has a massive overhaul, but something to think about.
- [ ] **Efficient prefix caching**. Another "would be nice" thing, but requires restructuring a lot of the core logic. Could also be a paper / entire research project of its own.
- [ ] **Training models to work as RLMs**. See the `verifiers` [rlm_env](https://github.com/PrimeIntellect-ai/verifiers/blob/main/verifiers/envs/experimental/rlm_env.py) as a starting point.
````

## File: LICENSE
````
MIT License

Copyright (c) 2025 Alex Zhang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
````

## File: Makefile
````makefile
.PHONY: help install install-dev install-modal run-all \
        quickstart docker-repl lm-repl modal-repl \
        lint format test check

help:
	@echo "RLM Examples Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make install        - Install base dependencies with uv"
	@echo "  make install-dev    - Install dev dependencies with uv"
	@echo "  make install-modal  - Install modal dependencies with uv"
	@echo "  make run-all        - Run all examples (requires all deps and API keys)"
	@echo ""
	@echo "Examples:"
	@echo "  make quickstart     - Run quickstart.py (needs OPENAI_API_KEY)"
	@echo "  make docker-repl    - Run docker_repl_example.py (needs Docker)"
	@echo "  make lm-repl        - Run lm_in_repl.py (needs PORTKEY_API_KEY)"
	@echo "  make modal-repl     - Run modal_repl_example.py (needs Modal)"
	@echo ""
	@echo "Development:"
	@echo "  make lint           - Run ruff linter"
	@echo "  make format         - Run ruff formatter"
	@echo "  make test           - Run tests"
	@echo "  make check          - Run lint + format + tests"

install:
	uv sync

install-dev:
	uv sync --group dev --group test

install-modal:
	uv pip install -e ".[modal]"

run-all: quickstart docker-repl lm-repl modal-repl

quickstart: install
	uv run python -m examples.quickstart

docker-repl: install
	uv run python -m examples.docker_repl_example

lm-repl: install
	uv run python -m examples.lm_in_repl

modal-repl: install-modal
	uv run python -m examples.modal_repl_example

lint: install-dev
	uv run ruff check .

format: install-dev
	uv run ruff format .

test: install-dev
	uv run pytest

check: lint format test
````

## File: docs/src/components/Sidebar.tsx
````typescript
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";
import { useState } from "react";

const navigation = [
  { name: "Recursive Language Models", href: "/" },
  { name: "Using the RLM Client", href: "/api" },
  { name: "LM Backends", href: "/backends" },
  {
    name: "REPL Environments",
    children: [
      { name: "Overview", href: "/environments" },
      { name: "LocalREPL", href: "/environments/local" },
      { name: "DockerREPL", href: "/environments/docker" },
      { name: "ModalREPL", href: "/environments/modal" },
    ],
  },
  { name: "Visualizing RLM Trajectories", href: "/trajectories" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [expandedSections, setExpandedSections] = useState<string[]>(["REPL Environments"]);

  const toggleSection = (name: string) => {
    setExpandedSections((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  };

  return (
    <aside className="w-64 border-r border-border bg-card/50 backdrop-blur-sm min-h-screen sticky top-0">
      <div className="p-6 border-b border-border">
        <Link href="/" className="block">
          <h1 className="font-bold text-xl text-foreground tracking-tight">
            RLM
          </h1>
        </Link>
      </div>
      <nav className="px-4 pb-8 pt-4">
        <ul className="space-y-0.5">
          {navigation.map((item) => {
            if ("children" in item) {
              const isExpanded = expandedSections.includes(item.name);
              return (
                <li key={item.name}>
                  <button
                    onClick={() => toggleSection(item.name)}
                    className="flex items-center justify-between w-full px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-md hover:bg-accent transition-colors"
                  >
                    {item.name}
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 transition-transform",
                        isExpanded && "rotate-180"
                      )}
                    />
                  </button>
                  {isExpanded && item.children && (
                    <ul className="mt-1 ml-3 space-y-1 border-l border-border pl-3">
                      {item.children.map((child) => (
                        <li key={child.href}>
                          <Link
                            href={child.href}
                            className={cn(
                              "block px-3 py-1.5 text-sm rounded-md transition-colors",
                              pathname === child.href
                                ? "text-foreground font-semibold bg-accent"
                                : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                            )}
                          >
                            {child.name}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            }
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "block px-3 py-2 text-sm rounded-md transition-colors",
                    pathname === item.href
                      ? "text-foreground font-semibold bg-accent"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                  )}
                >
                  {item.name}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="absolute bottom-4 left-4 right-4">
        <a
          href="https://github.com/alexzhang13/rlm"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground rounded-md hover:bg-accent"
        >
          <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
          </svg>
          GitHub
        </a>
      </div>
    </aside>
  );
}
````

## File: docs/next.config.js
````javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath: '/rlm',
  trailingSlash: true,
  images: { unoptimized: true },
};

module.exports = nextConfig;
````

## File: examples/modal_repl_example.py
````python
"""
Example usage of Modal REPL with code execution and LLM queries.

Run with: python -m examples.modal_repl_example
"""

from rlm.clients.base_lm import BaseLM
from rlm.core.lm_handler import LMHandler
from rlm.core.types import ModelUsageSummary, UsageSummary
from rlm.environments.modal_repl import ModalREPL


class MockLM(BaseLM):
    """Simple mock LM that echoes prompts."""

    def __init__(self):
        super().__init__(model_name="mock-model")

    def completion(self, prompt):
        return f"Mock response to: {prompt[:50]}"

    async def acompletion(self, prompt):
        return self.completion(prompt)

    def get_usage_summary(self):
        return UsageSummary(
            model_usage_summaries={
                "mock-model": ModelUsageSummary(
                    total_calls=1, total_input_tokens=10, total_output_tokens=10
                )
            }
        )

    def get_last_usage(self):
        return self.get_usage_summary()


def main():
    print("=" * 60)
    print("Modal REPL Example")
    print("=" * 60)

    # Example 1: Basic code execution
    print("\n[1] Basic code execution (no LLM handler)")
    print("-" * 40)

    with ModalREPL(app_name="rlm-example") as repl:
        result = repl.execute_code("x = 1 + 2")
        print("Executed: x = 1 + 2")
        print(f"Locals: {result.locals}")

        result = repl.execute_code("print(x * 2)")
        print("Executed: print(x * 2)")
        print(f"Stdout: {result.stdout.strip()}")

        result = repl.execute_code("answer = 42")
        result = repl.execute_code('print(FINAL_VAR("answer"))')
        print(f"FINAL_VAR('answer'): {result.stdout.strip()}")

    # Example 2: With LLM handler
    print("\n[2] Code execution with LLM handler")
    print("-" * 40)

    mock_client = MockLM()

    with LMHandler(client=mock_client) as handler:
        print(f"LM Handler started at {handler.address}")

        with ModalREPL(
            app_name="rlm-example-handler",
            lm_handler_address=handler.address,
        ) as repl:
            # Single LLM query
            result = repl.execute_code('response = llm_query("What is 2+2?")')
            print("Executed: response = llm_query('What is 2+2?')")
            print(f"Stderr: {result.stderr or '(none)'}")

            result = repl.execute_code("print(response)")
            print(f"Response: {result.stdout.strip()}")

            # Batched LLM query
            result = repl.execute_code(
                'responses = llm_query_batched(["Question 1", "Question 2", "Question 3"])'
            )
            print("\nExecuted: responses = llm_query_batched([...])")

            result = repl.execute_code("print(f'Got {len(responses)} responses')")
            print(f"Result: {result.stdout.strip()}")

            result = repl.execute_code("print(responses[0])")
            print(f"First response: {result.stdout.strip()}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
````

## File: rlm/clients/anthropic.py
````python
from collections import defaultdict
from typing import Any

import anthropic

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class AnthropicClient(BaseLM):
    """
    LM Client for running models with the Anthropic API.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str | None = None,
        max_tokens: int = 32768,
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.async_client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model_name = model_name
        self.max_tokens = max_tokens

        # Per-model usage tracking
        self.model_call_counts: dict[str, int] = defaultdict(int)
        self.model_input_tokens: dict[str, int] = defaultdict(int)
        self.model_output_tokens: dict[str, int] = defaultdict(int)
        self.model_total_tokens: dict[str, int] = defaultdict(int)

    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        messages, system = self._prepare_messages(prompt)

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Anthropic client.")

        kwargs = {"model": model, "max_tokens": self.max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        self._track_cost(response, model)
        return response.content[0].text

    async def acompletion(
        self, prompt: str | list[dict[str, Any]], model: str | None = None
    ) -> str:
        messages, system = self._prepare_messages(prompt)

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Anthropic client.")

        kwargs = {"model": model, "max_tokens": self.max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system

        response = await self.async_client.messages.create(**kwargs)
        self._track_cost(response, model)
        return response.content[0].text

    def _prepare_messages(
        self, prompt: str | list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Prepare messages and extract system prompt for Anthropic API."""
        system = None

        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            # Extract system message if present (Anthropic handles system separately)
            messages = []
            for msg in prompt:
                if msg.get("role") == "system":
                    system = msg.get("content")
                else:
                    messages.append(msg)
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        return messages, system

    def _track_cost(self, response: anthropic.types.Message, model: str):
        self.model_call_counts[model] += 1
        self.model_input_tokens[model] += response.usage.input_tokens
        self.model_output_tokens[model] += response.usage.output_tokens
        self.model_total_tokens[model] += response.usage.input_tokens + response.usage.output_tokens

        # Track last call for handler to read
        self.last_prompt_tokens = response.usage.input_tokens
        self.last_completion_tokens = response.usage.output_tokens

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model in self.model_call_counts:
            model_summaries[model] = ModelUsageSummary(
                total_calls=self.model_call_counts[model],
                total_input_tokens=self.model_input_tokens[model],
                total_output_tokens=self.model_output_tokens[model],
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self.last_prompt_tokens,
            total_output_tokens=self.last_completion_tokens,
        )
````

## File: rlm/clients/litellm.py
````python
from collections import defaultdict
from typing import Any

import litellm

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class LiteLLMClient(BaseLM):
    """
    LM Client for running models with LiteLLM.
    LiteLLM provides a unified interface to 100+ LLM providers.
    """

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)
        self.model_name = model_name
        self.api_key = api_key
        self.api_base = api_base

        # Per-model usage tracking
        self.model_call_counts: dict[str, int] = defaultdict(int)
        self.model_input_tokens: dict[str, int] = defaultdict(int)
        self.model_output_tokens: dict[str, int] = defaultdict(int)
        self.model_total_tokens: dict[str, int] = defaultdict(int)

    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for LiteLLM client.")

        kwargs = {"model": model, "messages": messages}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        response = litellm.completion(**kwargs)
        self._track_cost(response, model)
        return response.choices[0].message.content

    async def acompletion(
        self, prompt: str | list[dict[str, Any]], model: str | None = None
    ) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for LiteLLM client.")

        kwargs = {"model": model, "messages": messages}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        response = await litellm.acompletion(**kwargs)
        self._track_cost(response, model)
        return response.choices[0].message.content

    def _track_cost(self, response, model: str):
        self.model_call_counts[model] += 1
        self.model_input_tokens[model] += response.usage.prompt_tokens
        self.model_output_tokens[model] += response.usage.completion_tokens
        self.model_total_tokens[model] += response.usage.total_tokens

        # Track last call for handler to read
        self.last_prompt_tokens = response.usage.prompt_tokens
        self.last_completion_tokens = response.usage.completion_tokens

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model in self.model_call_counts:
            model_summaries[model] = ModelUsageSummary(
                total_calls=self.model_call_counts[model],
                total_input_tokens=self.model_input_tokens[model],
                total_output_tokens=self.model_output_tokens[model],
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self.last_prompt_tokens,
            total_output_tokens=self.last_completion_tokens,
        )
````

## File: rlm/logger/__init__.py
````python
from rlm.logger.rlm_logger import RLMLogger
from rlm.logger.verbose import VerbosePrinter

__all__ = ["RLMLogger", "VerbosePrinter"]
````

## File: rlm/logger/verbose.py
````python
"""
Verbose printing for RLM using rich. Modify this however you please :)
I was mainly using this for debugging, and a lot of it is vibe-coded.

Provides console output for debugging and understanding RLM execution.
Uses a "Tokyo Night" inspired color theme.
"""

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from rlm.core.types import CodeBlock, RLMIteration, RLMMetadata

# ============================================================================
# Tokyo Night Color Theme
# ============================================================================
COLORS = {
    "primary": "#7AA2F7",  # Soft blue - headers, titles
    "secondary": "#BB9AF7",  # Soft purple - emphasis
    "success": "#9ECE6A",  # Soft green - success, code
    "warning": "#E0AF68",  # Soft amber - warnings
    "error": "#F7768E",  # Soft red/pink - errors
    "text": "#A9B1D6",  # Soft gray-blue - regular text
    "muted": "#565F89",  # Muted gray - less important
    "accent": "#7DCFFF",  # Bright cyan - accents
    "bg_subtle": "#1A1B26",  # Dark background
    "border": "#3B4261",  # Border color
    "code_bg": "#24283B",  # Code background
}

# Rich styles
STYLE_PRIMARY = Style(color=COLORS["primary"], bold=True)
STYLE_SECONDARY = Style(color=COLORS["secondary"])
STYLE_SUCCESS = Style(color=COLORS["success"])
STYLE_WARNING = Style(color=COLORS["warning"])
STYLE_ERROR = Style(color=COLORS["error"])
STYLE_TEXT = Style(color=COLORS["text"])
STYLE_MUTED = Style(color=COLORS["muted"])
STYLE_ACCENT = Style(color=COLORS["accent"], bold=True)


def _to_str(value: Any) -> str:
    """Convert any value to string safely."""
    if isinstance(value, str):
        return value
    return str(value)


class VerbosePrinter:
    """
    Rich console printer for RLM verbose output.

    Displays beautiful, structured output showing the RLM's execution:
    - Initial configuration panel
    - Each iteration with response summaries
    - Code execution with results
    - Sub-calls to other models
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize the verbose printer.

        Args:
            enabled: Whether verbose printing is enabled. If False, all methods are no-ops.
        """
        self.enabled = enabled
        self.console = Console() if enabled else None
        self._iteration_count = 0

    def print_header(
        self,
        backend: str,
        model: str,
        environment: str,
        max_iterations: int,
        max_depth: int,
        other_backends: list[str] | None = None,
    ) -> None:
        """Print the initial RLM configuration header."""
        if not self.enabled:
            return

        # Main title
        title = Text()
        title.append("◆ ", style=STYLE_ACCENT)
        title.append("RLM", style=Style(color=COLORS["primary"], bold=True))
        title.append(" ━ Recursive Language Model", style=STYLE_MUTED)

        # Configuration table
        config_table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 2),
            expand=True,
        )
        config_table.add_column("key", style=STYLE_MUTED, width=16)
        config_table.add_column("value", style=STYLE_TEXT)
        config_table.add_column("key2", style=STYLE_MUTED, width=16)
        config_table.add_column("value2", style=STYLE_TEXT)

        config_table.add_row(
            "Backend",
            Text(backend, style=STYLE_SECONDARY),
            "Environment",
            Text(environment, style=STYLE_SECONDARY),
        )
        config_table.add_row(
            "Model",
            Text(model, style=STYLE_ACCENT),
            "Max Iterations",
            Text(str(max_iterations), style=STYLE_WARNING),
        )

        if other_backends:
            backends_text = Text(", ".join(other_backends), style=STYLE_SECONDARY)
            config_table.add_row(
                "Sub-models",
                backends_text,
                "Max Depth",
                Text(str(max_depth), style=STYLE_WARNING),
            )
        else:
            config_table.add_row(
                "Max Depth",
                Text(str(max_depth), style=STYLE_WARNING),
                "",
                "",
            )

        # Wrap in panel
        panel = Panel(
            config_table,
            title=title,
            title_align="left",
            border_style=COLORS["border"],
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)
        self.console.print()

    def print_metadata(self, metadata: RLMMetadata) -> None:
        """Print RLM metadata as header."""
        if not self.enabled:
            return

        model = metadata.backend_kwargs.get("model_name", "unknown")
        other = list(metadata.other_backends) if metadata.other_backends else None

        self.print_header(
            backend=metadata.backend,
            model=model,
            environment=metadata.environment_type,
            max_iterations=metadata.max_iterations,
            max_depth=metadata.max_depth,
            other_backends=other,
        )

    def print_iteration_start(self, iteration: int) -> None:
        """Print the start of a new iteration."""
        if not self.enabled:
            return

        self._iteration_count = iteration

        rule = Rule(
            Text(f" Iteration {iteration} ", style=STYLE_PRIMARY),
            style=COLORS["border"],
            characters="─",
        )
        self.console.print(rule)

    def print_completion(self, response: Any, iteration_time: float | None = None) -> None:
        """Print a completion response."""
        if not self.enabled:
            return

        # Header with timing
        header = Text()
        header.append("◇ ", style=STYLE_ACCENT)
        header.append("LLM Response", style=STYLE_PRIMARY)
        if iteration_time:
            header.append(f"  ({iteration_time:.2f}s)", style=STYLE_MUTED)

        # Response content
        response_str = _to_str(response)
        response_text = Text(response_str, style=STYLE_TEXT)

        # Count words roughly
        word_count = len(response_str.split())
        footer = Text(f"~{word_count} words", style=STYLE_MUTED)

        panel = Panel(
            Group(response_text, Text(), footer),
            title=header,
            title_align="left",
            border_style=COLORS["muted"],
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_code_execution(self, code_block: CodeBlock) -> None:
        """Print code execution details."""
        if not self.enabled:
            return

        result = code_block.result

        # Header
        header = Text()
        header.append("▸ ", style=STYLE_SUCCESS)
        header.append("Code Execution", style=Style(color=COLORS["success"], bold=True))
        if result.execution_time:
            header.append(f"  ({result.execution_time:.3f}s)", style=STYLE_MUTED)

        # Build content
        content_parts = []

        # Code snippet
        code_text = Text()
        code_text.append("Code:\n", style=STYLE_MUTED)
        code_text.append(_to_str(code_block.code), style=STYLE_TEXT)
        content_parts.append(code_text)

        # Stdout if present
        stdout_str = _to_str(result.stdout) if result.stdout else ""
        if stdout_str.strip():
            stdout_text = Text()
            stdout_text.append("\nOutput:\n", style=STYLE_MUTED)
            stdout_text.append(stdout_str, style=STYLE_SUCCESS)
            content_parts.append(stdout_text)

        # Stderr if present (error)
        stderr_str = _to_str(result.stderr) if result.stderr else ""
        if stderr_str.strip():
            stderr_text = Text()
            stderr_text.append("\nError:\n", style=STYLE_MUTED)
            stderr_text.append(stderr_str, style=STYLE_ERROR)
            content_parts.append(stderr_text)

        # Sub-calls summary
        if result.rlm_calls:
            calls_text = Text()
            calls_text.append(f"\n↳ {len(result.rlm_calls)} sub-call(s)", style=STYLE_SECONDARY)
            content_parts.append(calls_text)

        panel = Panel(
            Group(*content_parts),
            title=header,
            title_align="left",
            border_style=COLORS["success"],
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_subcall(
        self,
        model: str,
        prompt_preview: str,
        response_preview: str,
        execution_time: float | None = None,
    ) -> None:
        """Print a sub-call to another model."""
        if not self.enabled:
            return

        # Header
        header = Text()
        header.append("  ↳ ", style=STYLE_SECONDARY)
        header.append("Sub-call: ", style=STYLE_SECONDARY)
        header.append(_to_str(model), style=STYLE_ACCENT)
        if execution_time:
            header.append(f"  ({execution_time:.2f}s)", style=STYLE_MUTED)

        # Content
        content = Text()
        content.append("Prompt: ", style=STYLE_MUTED)
        content.append(_to_str(prompt_preview), style=STYLE_TEXT)
        content.append("\nResponse: ", style=STYLE_MUTED)
        content.append(_to_str(response_preview), style=STYLE_TEXT)

        panel = Panel(
            content,
            title=header,
            title_align="left",
            border_style=COLORS["secondary"],
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_iteration(self, iteration: RLMIteration, iteration_num: int) -> None:
        """
        Print a complete iteration including response and code executions.
        This is the main entry point for printing an iteration.
        """
        if not self.enabled:
            return

        # Print iteration header
        self.print_iteration_start(iteration_num)

        # Print the LLM response
        self.print_completion(iteration.response, iteration.iteration_time)

        # Print each code block execution
        for code_block in iteration.code_blocks:
            self.print_code_execution(code_block)

            # Print any sub-calls made during this code block
            for call in code_block.result.rlm_calls:
                self.print_subcall(
                    model=call.root_model,
                    prompt_preview=_to_str(call.prompt) if call.prompt else "",
                    response_preview=_to_str(call.response) if call.response else "",
                    execution_time=call.execution_time,
                )

    def print_final_answer(self, answer: Any) -> None:
        """Print the final answer."""
        if not self.enabled:
            return

        # Title
        title = Text()
        title.append("★ ", style=STYLE_WARNING)
        title.append("Final Answer", style=Style(color=COLORS["warning"], bold=True))

        # Answer content
        answer_text = Text(_to_str(answer), style=STYLE_TEXT)

        panel = Panel(
            answer_text,
            title=title,
            title_align="left",
            border_style=COLORS["warning"],
            padding=(1, 2),
        )

        self.console.print()
        self.console.print(panel)
        self.console.print()

    def print_summary(
        self,
        total_iterations: int,
        total_time: float,
        usage_summary: dict[str, Any] | None = None,
    ) -> None:
        """Print a summary at the end of execution."""
        if not self.enabled:
            return

        # Summary table
        summary_table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 2),
        )
        summary_table.add_column("metric", style=STYLE_MUTED)
        summary_table.add_column("value", style=STYLE_ACCENT)

        summary_table.add_row("Iterations", str(total_iterations))
        summary_table.add_row("Total Time", f"{total_time:.2f}s")

        if usage_summary:
            total_input = sum(
                m.get("total_input_tokens", 0)
                for m in usage_summary.get("model_usage_summaries", {}).values()
            )
            total_output = sum(
                m.get("total_output_tokens", 0)
                for m in usage_summary.get("model_usage_summaries", {}).values()
            )
            if total_input or total_output:
                summary_table.add_row("Input Tokens", f"{total_input:,}")
                summary_table.add_row("Output Tokens", f"{total_output:,}")

        # Wrap in rule
        self.console.print()
        self.console.print(Rule(style=COLORS["border"], characters="═"))
        self.console.print(summary_table, justify="center")
        self.console.print(Rule(style=COLORS["border"], characters="═"))
        self.console.print()
````

## File: rlm/utils/rlm_utils.py
````python
from typing import Any


def filter_sensitive_keys(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter out sensitive keys like API keys from kwargs."""
    filtered = {}
    for key, value in kwargs.items():
        key_lower = key.lower()
        if "api" in key_lower and "key" in key_lower:
            continue
        filtered[key] = value
    return filtered
````

## File: rlm/__init__.py
````python
from rlm.core.rlm import RLM

__all__ = ["RLM"]
````

## File: tests/clients/portkey.py
````python
from dotenv import load_dotenv

from rlm.clients.portkey import PortkeyClient

load_dotenv()


def test_portkey_one_word_go():
    import os

    api_key = os.environ.get("PORTKEY_API_KEY", "sk-test")  # use a dummy or your test key
    model_name = "@openai/gpt-5-nano"  # or any Portkey-compatible model

    client = PortkeyClient(api_key=api_key, model_name=model_name)
    prompt = "One word, go"
    try:
        result = client.completion(prompt)
        print("Portkey response:", result)
    except Exception as e:
        print("PortkeyClient error:", e)


if __name__ == "__main__":
    test_portkey_one_word_go()
````

## File: tests/repl/test_local_repl.py
````python
from rlm.environments.local_repl import LocalREPL


def test_persistent_execution():
    """Test that variables persist across multiple code executions."""
    repl = LocalREPL()

    # Set a variable
    result1 = repl.execute_code("x = 42")
    assert result1.stderr == ""
    assert "x" in repl.locals
    assert repl.locals["x"] == 42

    # Use the variable in a subsequent execution
    result2 = repl.execute_code("y = x + 8")
    assert result2.stderr == ""
    assert repl.locals["y"] == 50

    # Print the variable
    result3 = repl.execute_code("print(y)")
    assert "50" in result3.stdout

    repl.cleanup()
````

## File: tests/README.md
````markdown
Unit tests for making sure the whole system is not broken -- mainly for local execution / non-isolated environments.
````

## File: tests/test_imports.py
````python
"""Tests to verify all imports are correct and non-conflicting."""

import importlib
import sys
from collections import defaultdict

import pytest


class TestTopLevelImports:
    """Test top-level package imports."""

    def test_rlm_import(self):
        """Test that main rlm package can be imported."""
        import rlm

        assert hasattr(rlm, "RLM")
        assert "RLM" in rlm.__all__

    def test_rlm_rlm_import(self):
        """Test that RLM class can be imported from rlm."""
        from rlm import RLM

        assert RLM is not None

    def test_rlm_core_rlm_import(self):
        """Test that RLM can be imported from rlm.core.rlm."""
        from rlm.core.rlm import RLM

        assert RLM is not None


class TestClientImports:
    """Test client module imports."""

    def test_clients_module_import(self):
        """Test that clients module can be imported."""
        import rlm.clients

        assert hasattr(rlm.clients, "get_client")
        assert hasattr(rlm.clients, "BaseLM")

    def test_base_lm_import(self):
        """Test BaseLM import."""
        from rlm.clients.base_lm import BaseLM

        assert BaseLM is not None

    def test_openai_client_import(self):
        """Test OpenAIClient import."""
        pytest.importorskip("openai")
        from rlm.clients.openai import OpenAIClient

        assert OpenAIClient is not None

    def test_anthropic_client_import(self):
        """Test AnthropicClient import."""
        pytest.importorskip("anthropic")
        from rlm.clients.anthropic import AnthropicClient

        assert AnthropicClient is not None

    def test_portkey_client_import(self):
        """Test PortkeyClient import."""
        pytest.importorskip("portkey_ai")
        from rlm.clients.portkey import PortkeyClient

        assert PortkeyClient is not None

    def test_litellm_client_import(self):
        """Test LiteLLMClient import."""
        pytest.importorskip("litellm")
        from rlm.clients.litellm import LiteLLMClient

        assert LiteLLMClient is not None

    def test_get_client_function(self):
        """Test get_client function import."""
        from rlm.clients import get_client

        assert callable(get_client)


class TestCoreImports:
    """Test core module imports."""

    def test_core_types_import(self):
        """Test core types imports."""
        from rlm.core.types import (
            ClientBackend,
            CodeBlock,
            ModelUsageSummary,
            QueryMetadata,
            REPLResult,
            RLMIteration,
            RLMMetadata,
            UsageSummary,
        )

        assert ClientBackend is not None
        assert CodeBlock is not None
        assert ModelUsageSummary is not None
        assert QueryMetadata is not None
        assert REPLResult is not None
        assert RLMIteration is not None
        assert RLMMetadata is not None
        assert UsageSummary is not None

    def test_core_rlm_import(self):
        """Test core RLM import."""
        from rlm.core.rlm import RLM

        assert RLM is not None

    def test_core_lm_handler_import(self):
        """Test LMHandler import."""
        from rlm.core.lm_handler import LMHandler

        assert LMHandler is not None

    def test_core_comms_utils_import(self):
        """Test comms_utils imports."""
        from rlm.core.comms_utils import (
            LMRequest,
            LMResponse,
            send_lm_request,
            send_lm_request_batched,
            socket_recv,
            socket_send,
        )

        assert LMRequest is not None
        assert LMResponse is not None
        assert callable(send_lm_request)
        assert callable(send_lm_request_batched)
        assert callable(socket_recv)
        assert callable(socket_send)


class TestEnvironmentImports:
    """Test environment module imports."""

    def test_environments_module_import(self):
        """Test that environments module can be imported."""
        import rlm.environments

        assert hasattr(rlm.environments, "get_environment")
        assert hasattr(rlm.environments, "BaseEnv")
        assert hasattr(rlm.environments, "LocalREPL")

    def test_base_env_import(self):
        """Test BaseEnv import."""
        from rlm.environments.base_env import BaseEnv, IsolatedEnv, NonIsolatedEnv

        assert BaseEnv is not None
        assert IsolatedEnv is not None
        assert NonIsolatedEnv is not None

    def test_local_repl_import(self):
        """Test LocalREPL import."""
        from rlm.environments.local_repl import LocalREPL

        assert LocalREPL is not None

    def test_modal_repl_import(self):
        """Test ModalREPL import."""
        pytest.importorskip("modal")
        from rlm.environments.modal_repl import ModalREPL

        assert ModalREPL is not None

    def test_docker_repl_import(self):
        """Test DockerREPL import."""
        from rlm.environments.docker_repl import DockerREPL

        assert DockerREPL is not None

    def test_prime_repl_import(self):
        """Test PrimeREPL import."""
        pytest.importorskip("prime_sandboxes")
        from rlm.environments.prime_repl import PrimeREPL

        assert PrimeREPL is not None

    def test_get_environment_function(self):
        """Test get_environment function import."""
        from rlm.environments import get_environment

        assert callable(get_environment)


class TestLoggerImports:
    """Test logger module imports."""

    def test_logger_module_import(self):
        """Test that logger module can be imported."""
        import rlm.logger

        assert hasattr(rlm.logger, "RLMLogger")
        assert hasattr(rlm.logger, "VerbosePrinter")
        assert "RLMLogger" in rlm.logger.__all__
        assert "VerbosePrinter" in rlm.logger.__all__

    def test_rlm_logger_import(self):
        """Test RLMLogger import."""
        from rlm.logger.rlm_logger import RLMLogger

        assert RLMLogger is not None

    def test_verbose_import(self):
        """Test VerbosePrinter import."""
        from rlm.logger.verbose import VerbosePrinter

        assert VerbosePrinter is not None


class TestUtilsImports:
    """Test utils module imports."""

    def test_parsing_import(self):
        """Test parsing module import."""
        from rlm.utils.parsing import (
            find_code_blocks,
            find_final_answer,
            format_execution_result,
            format_iteration,
        )

        assert callable(find_code_blocks)
        assert callable(find_final_answer)
        assert callable(format_iteration)
        assert callable(format_execution_result)

    def test_prompts_import(self):
        """Test prompts module import."""
        from rlm.utils.prompts import (
            RLM_SYSTEM_PROMPT,
            USER_PROMPT,
            build_rlm_system_prompt,
            build_user_prompt,
        )

        assert RLM_SYSTEM_PROMPT is not None
        assert USER_PROMPT is not None
        assert callable(build_rlm_system_prompt)
        assert callable(build_user_prompt)

    def test_rlm_utils_import(self):
        """Test rlm_utils module import."""
        from rlm.utils.rlm_utils import filter_sensitive_keys

        assert callable(filter_sensitive_keys)


class TestImportConflicts:
    """Test for import conflicts and naming issues."""

    def test_no_duplicate_names_in_rlm_all(self):
        """Test that __all__ in rlm.__init__ has no duplicates."""
        import rlm

        if hasattr(rlm, "__all__"):
            all_items = rlm.__all__
            assert len(all_items) == len(set(all_items)), (
                f"Duplicate items in rlm.__all__: {all_items}"
            )

    def test_no_duplicate_names_in_logger_all(self):
        """Test that __all__ in rlm.logger.__init__ has no duplicates."""
        import rlm.logger

        if hasattr(rlm.logger, "__all__"):
            all_items = rlm.logger.__all__
            assert len(all_items) == len(set(all_items)), (
                f"Duplicate items in rlm.logger.__all__: {all_items}"
            )

    def test_all_declarations_match_exports(self):
        """Test that __all__ declarations match actual exports."""
        import rlm
        import rlm.logger

        # Test rlm.__all__
        if hasattr(rlm, "__all__"):
            for name in rlm.__all__:
                assert hasattr(rlm, name), f"rlm.__all__ declares '{name}' but it's not exported"

        # Test rlm.logger.__all__
        if hasattr(rlm.logger, "__all__"):
            for name in rlm.logger.__all__:
                assert hasattr(rlm.logger, name), (
                    f"rlm.logger.__all__ declares '{name}' but it's not exported"
                )

    def test_no_circular_imports(self):
        """Test that modules can be imported without circular import errors."""
        # Core modules that should always be importable
        core_modules = [
            "rlm",
            "rlm.clients",
            "rlm.clients.base_lm",
            "rlm.core",
            "rlm.core.types",
            "rlm.core.rlm",
            "rlm.core.lm_handler",
            "rlm.core.comms_utils",
            "rlm.environments",
            "rlm.environments.base_env",
            "rlm.environments.local_repl",
            "rlm.environments.docker_repl",
            "rlm.logger",
            "rlm.logger.rlm_logger",
            "rlm.logger.verbose",
            "rlm.utils",
            "rlm.utils.parsing",
            "rlm.utils.prompts",
            "rlm.utils.rlm_utils",
        ]

        # Optional modules that may not be available
        optional_modules = [
            ("rlm.clients.openai", "openai"),
            ("rlm.clients.anthropic", "anthropic"),
            ("rlm.clients.portkey", "portkey_ai"),
            ("rlm.clients.litellm", "litellm"),
            ("rlm.environments.modal_repl", "modal"),
            ("rlm.environments.prime_repl", "prime_sandboxes"),
        ]

        # Test core modules
        for module_name in core_modules:
            # Remove from sys.modules if present to test fresh import
            if module_name in sys.modules:
                del sys.modules[module_name]
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

        # Test optional modules (skip if dependency not available)
        for module_name, dependency in optional_modules:
            # Check if dependency is available
            try:
                importlib.import_module(dependency)
            except ImportError:
                continue  # Skip this module if dependency not available

            # If dependency is available, test the module import
            if module_name in sys.modules:
                del sys.modules[module_name]
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_no_naming_conflicts_across_modules(self):
        """Test that there are no naming conflicts across different modules."""
        # Collect all public names from each module
        module_exports: dict[str, set[str]] = {}

        # Check main modules
        import rlm
        import rlm.clients
        import rlm.environments
        import rlm.logger

        if hasattr(rlm, "__all__"):
            module_exports["rlm"] = set(rlm.__all__)
        else:
            module_exports["rlm"] = {name for name in dir(rlm) if not name.startswith("_")}

        if hasattr(rlm.clients, "__all__"):
            module_exports["rlm.clients"] = set(rlm.clients.__all__)
        else:
            module_exports["rlm.clients"] = {
                name for name in dir(rlm.clients) if not name.startswith("_")
            }

        if hasattr(rlm.environments, "__all__"):
            module_exports["rlm.environments"] = set(rlm.environments.__all__)
        else:
            module_exports["rlm.environments"] = {
                name for name in dir(rlm.environments) if not name.startswith("_")
            }

        if hasattr(rlm.logger, "__all__"):
            module_exports["rlm.logger"] = set(rlm.logger.__all__)
        else:
            module_exports["rlm.logger"] = {
                name for name in dir(rlm.logger) if not name.startswith("_")
            }

        # Check for conflicts (same name in multiple modules)
        name_to_modules: dict[str, list[str]] = defaultdict(list)
        for module_name, exports in module_exports.items():
            for export_name in exports:
                name_to_modules[export_name].append(module_name)

        conflicts = {name: modules for name, modules in name_to_modules.items() if len(modules) > 1}
        # Filter out common Python builtins/dunders and typing imports that are expected
        expected_duplicates = {
            "__file__",
            "__name__",
            "__package__",
            "__path__",
            "__doc__",
            "__loader__",
            "__spec__",
            "__cached__",
            "Any",  # Common typing import
            "Literal",  # Common typing import
            "Optional",  # Common typing import
            "Union",  # Common typing import
            "Dict",  # Common typing import
            "List",  # Common typing import
            "Tuple",  # Common typing import
            "Callable",  # Common typing import
        }
        conflicts = {
            name: modules for name, modules in conflicts.items() if name not in expected_duplicates
        }

        if conflicts:
            conflict_msg = "\n".join(
                f"  '{name}' exported from: {', '.join(modules)}"
                for name, modules in conflicts.items()
            )
            pytest.fail(f"Found naming conflicts across modules:\n{conflict_msg}")


class TestImportCompleteness:
    """Test that all expected imports are available."""

    def test_all_client_classes_importable(self):
        """Test that all client classes can be imported."""
        from rlm.clients.base_lm import BaseLM

        # Verify BaseLM is a class
        assert isinstance(BaseLM, type)

        # Test optional client classes
        try:
            pytest.importorskip("openai")
            from rlm.clients.openai import OpenAIClient

            assert isinstance(OpenAIClient, type)
        except Exception:
            pass

        try:
            pytest.importorskip("anthropic")
            from rlm.clients.anthropic import AnthropicClient

            assert isinstance(AnthropicClient, type)
        except Exception:
            pass

        try:
            pytest.importorskip("portkey_ai")
            from rlm.clients.portkey import PortkeyClient

            assert isinstance(PortkeyClient, type)
        except Exception:
            pass

        try:
            pytest.importorskip("litellm")
            from rlm.clients.litellm import LiteLLMClient

            assert isinstance(LiteLLMClient, type)
        except Exception:
            pass

    def test_all_environment_classes_importable(self):
        """Test that all environment classes can be imported."""
        from rlm.environments.base_env import BaseEnv, IsolatedEnv, NonIsolatedEnv
        from rlm.environments.docker_repl import DockerREPL
        from rlm.environments.local_repl import LocalREPL

        # Verify they're all classes
        assert isinstance(BaseEnv, type)
        assert isinstance(IsolatedEnv, type)
        assert isinstance(NonIsolatedEnv, type)
        assert isinstance(LocalREPL, type)
        assert isinstance(DockerREPL, type)

        # Test optional ModalREPL
        try:
            pytest.importorskip("modal")
            from rlm.environments.modal_repl import ModalREPL

            assert isinstance(ModalREPL, type)
        except Exception:
            pass

        # Test optional PrimeREPL
        try:
            pytest.importorskip("prime_sandboxes")
            from rlm.environments.prime_repl import PrimeREPL

            assert isinstance(PrimeREPL, type)
        except Exception:
            pass
````

## File: visualizer/src/app/globals.css
````css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);
  --color-sidebar-ring: var(--sidebar-ring);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar: var(--sidebar);
  --color-chart-5: var(--chart-5);
  --color-chart-4: var(--chart-4);
  --color-chart-3: var(--chart-3);
  --color-chart-2: var(--chart-2);
  --color-chart-1: var(--chart-1);
  --color-ring: var(--ring);
  --color-input: var(--input);
  --color-border: var(--border);
  --color-destructive: var(--destructive);
  --color-accent-foreground: var(--accent-foreground);
  --color-accent: var(--accent);
  --color-muted-foreground: var(--muted-foreground);
  --color-muted: var(--muted);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-secondary: var(--secondary);
  --color-primary-foreground: var(--primary-foreground);
  --color-primary: var(--primary);
  --color-popover-foreground: var(--popover-foreground);
  --color-popover: var(--popover);
  --color-card-foreground: var(--card-foreground);
  --color-card: var(--card);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --radius-2xl: calc(var(--radius) + 8px);
  --radius-3xl: calc(var(--radius) + 12px);
  --radius-4xl: calc(var(--radius) + 16px);
}

/* Light mode - clean green theme */
:root {
  --radius: 0.5rem;
  --background: oklch(0.985 0.005 145);
  --foreground: oklch(0.15 0.02 145);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.15 0.02 145);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.15 0.02 145);
  --primary: oklch(0.45 0.16 145);
  --primary-foreground: oklch(0.98 0.005 145);
  --secondary: oklch(0.96 0.01 145);
  --secondary-foreground: oklch(0.2 0.02 145);
  --muted: oklch(0.96 0.01 145);
  --muted-foreground: oklch(0.45 0.02 145);
  --accent: oklch(0.92 0.03 145);
  --accent-foreground: oklch(0.2 0.02 145);
  --destructive: oklch(0.55 0.22 25);
  --border: oklch(0.9 0.01 145);
  --input: oklch(0.92 0.01 145);
  --ring: oklch(0.45 0.16 145);
  --chart-1: oklch(0.5 0.18 145);
  --chart-2: oklch(0.55 0.15 200);
  --chart-3: oklch(0.6 0.15 90);
  --chart-4: oklch(0.55 0.18 320);
  --chart-5: oklch(0.5 0.2 25);
  --sidebar: oklch(0.98 0.005 145);
  --sidebar-foreground: oklch(0.15 0.02 145);
  --sidebar-primary: oklch(0.45 0.16 145);
  --sidebar-primary-foreground: oklch(0.98 0.005 145);
  --sidebar-accent: oklch(0.94 0.015 145);
  --sidebar-accent-foreground: oklch(0.15 0.02 145);
  --sidebar-border: oklch(0.9 0.01 145);
  --sidebar-ring: oklch(0.45 0.16 145);
}

/* Dark mode - rich green theme */
.dark {
  --background: oklch(0.09 0.01 145);
  --foreground: oklch(0.92 0.02 145);
  --card: oklch(0.11 0.015 145);
  --card-foreground: oklch(0.92 0.02 145);
  --popover: oklch(0.11 0.015 145);
  --popover-foreground: oklch(0.92 0.02 145);
  --primary: oklch(0.65 0.18 145);
  --primary-foreground: oklch(0.1 0.02 145);
  --secondary: oklch(0.16 0.02 145);
  --secondary-foreground: oklch(0.92 0.02 145);
  --muted: oklch(0.16 0.015 145);
  --muted-foreground: oklch(0.6 0.03 145);
  --accent: oklch(0.55 0.12 145);
  --accent-foreground: oklch(0.1 0.02 145);
  --destructive: oklch(0.6 0.22 25);
  --border: oklch(0.22 0.02 145);
  --input: oklch(0.18 0.02 145);
  --ring: oklch(0.65 0.18 145);
  --chart-1: oklch(0.65 0.18 145);
  --chart-2: oklch(0.6 0.15 200);
  --chart-3: oklch(0.75 0.15 90);
  --chart-4: oklch(0.6 0.18 320);
  --chart-5: oklch(0.55 0.2 25);
  --sidebar: oklch(0.1 0.015 145);
  --sidebar-foreground: oklch(0.92 0.02 145);
  --sidebar-primary: oklch(0.65 0.18 145);
  --sidebar-primary-foreground: oklch(0.1 0.02 145);
  --sidebar-accent: oklch(0.16 0.02 145);
  --sidebar-accent-foreground: oklch(0.92 0.02 145);
  --sidebar-border: oklch(0.22 0.02 145);
  --sidebar-ring: oklch(0.65 0.18 145);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  body {
    @apply bg-background text-foreground;
  }
}

/* Custom scrollbar - adapts to theme */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--muted);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--muted-foreground);
}

/* Code block styling */
.code-block {
  font-family: var(--font-geist-mono), 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.6;
  tab-size: 2;
}

/* Gradient text - adapts to theme */
.gradient-text {
  background: linear-gradient(135deg, var(--primary), var(--accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* Grid pattern background - light mode */
.grid-pattern {
  background-image: 
    linear-gradient(oklch(0.85 0.02 145 / 0.5) 1px, transparent 1px),
    linear-gradient(90deg, oklch(0.85 0.02 145 / 0.5) 1px, transparent 1px);
  background-size: 50px 50px;
}

.dark .grid-pattern {
  background-image: 
    linear-gradient(oklch(0.2 0.02 145 / 0.4) 1px, transparent 1px),
    linear-gradient(90deg, oklch(0.2 0.02 145 / 0.4) 1px, transparent 1px);
  background-size: 50px 50px;
}

/* Terminal styling */
.terminal-prompt::before {
  content: '❯ ';
  color: var(--primary);
}

/* Message bubble styling for trajectory */
.message-bubble {
  position: relative;
  border-radius: 12px;
  padding: 1rem 1.25rem;
}

.message-bubble-system {
  background: oklch(0.95 0.02 280 / 0.5);
  border-left: 3px solid oklch(0.6 0.15 280);
}

.message-bubble-user {
  background: oklch(0.94 0.02 145 / 0.5);
  border-left: 3px solid oklch(0.5 0.15 145);
}

.message-bubble-assistant {
  background: oklch(0.94 0.02 200 / 0.5);
  border-left: 3px solid oklch(0.55 0.12 200);
}

.dark .message-bubble-system {
  background: oklch(0.18 0.02 280 / 0.3);
  border-left: 3px solid oklch(0.6 0.15 280);
}

.dark .message-bubble-user {
  background: oklch(0.15 0.02 145 / 0.4);
  border-left: 3px solid oklch(0.6 0.18 145);
}

.dark .message-bubble-assistant {
  background: oklch(0.15 0.02 200 / 0.3);
  border-left: 3px solid oklch(0.65 0.12 200);
}

/* Prose styling for readability */
.prose-trajectory {
  font-size: 14px;
  line-height: 1.7;
  letter-spacing: -0.01em;
}

.prose-trajectory p {
  margin-bottom: 0.75rem;
}

.prose-trajectory pre {
  background: var(--muted);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  overflow-x: auto;
  font-size: 13px;
  margin: 0.75rem 0;
}

.prose-trajectory code {
  background: var(--muted);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.9em;
}

.prose-trajectory pre code {
  background: transparent;
  padding: 0;
}
````

## File: visualizer/src/app/layout.tsx
````typescript
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/ThemeProvider";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RLM Visualizer",
  description: "Visualize and debug Recursive Language Model execution traces",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <TooltipProvider>
            {children}
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
````

## File: visualizer/src/components/Dashboard.tsx
````typescript
'use client';

import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { FileUploader } from './FileUploader';
import { LogViewer } from './LogViewer';
import { AsciiRLM } from './AsciiGlobe';
import { ThemeToggle } from './ThemeToggle';
import { parseLogFile, extractContextVariable } from '@/lib/parse-logs';
import { RLMLogFile } from '@/lib/types';
import { cn } from '@/lib/utils';

interface DemoLogInfo {
  fileName: string;
  contextPreview: string | null;
  hasFinalAnswer: boolean;
  iterations: number;
}

export function Dashboard() {
  const [logFiles, setLogFiles] = useState<RLMLogFile[]>([]);
  const [selectedLog, setSelectedLog] = useState<RLMLogFile | null>(null);
  const [demoLogs, setDemoLogs] = useState<DemoLogInfo[]>([]);
  const [loadingDemos, setLoadingDemos] = useState(true);

  // Load demo log previews on mount - fetches latest 10 from API
  useEffect(() => {
    async function loadDemoPreviews() {
      try {
        // Fetch list of log files from API
        const listResponse = await fetch('/api/logs');
        if (!listResponse.ok) {
          throw new Error('Failed to fetch log list');
        }
        const { files } = await listResponse.json();
        
        const previews: DemoLogInfo[] = [];
        
        for (const fileName of files) {
          try {
            const response = await fetch(`/logs/${fileName}`);
            if (!response.ok) continue;
            const content = await response.text();
            const parsed = parseLogFile(fileName, content);
            const contextVar = extractContextVariable(parsed.iterations);
            
            previews.push({
              fileName,
              contextPreview: contextVar,
              hasFinalAnswer: !!parsed.metadata.finalAnswer,
              iterations: parsed.metadata.totalIterations,
            });
          } catch (e) {
            console.error('Failed to load demo preview:', fileName, e);
          }
        }
        
        setDemoLogs(previews);
      } catch (e) {
        console.error('Failed to load demo logs:', e);
      } finally {
        setLoadingDemos(false);
      }
    }
    
    loadDemoPreviews();
  }, []);

  const handleFileLoaded = useCallback((fileName: string, content: string) => {
    const parsed = parseLogFile(fileName, content);
    setLogFiles(prev => {
      if (prev.some(f => f.fileName === fileName)) {
        return prev.map(f => f.fileName === fileName ? parsed : f);
      }
      return [...prev, parsed];
    });
    setSelectedLog(parsed);
  }, []);

  const loadDemoLog = useCallback(async (fileName: string) => {
    try {
      const response = await fetch(`/logs/${fileName}`);
      if (!response.ok) throw new Error('Failed to load demo log');
      const content = await response.text();
      handleFileLoaded(fileName, content);
    } catch (error) {
      console.error('Error loading demo log:', error);
      alert('Failed to load demo log. Make sure the log files are in the public/logs folder.');
    }
  }, [handleFileLoaded]);

  if (selectedLog) {
    return (
      <LogViewer 
        logFile={selectedLog} 
        onBack={() => setSelectedLog(null)} 
      />
    );
  }

  return (
    <div className="min-h-screen bg-background relative overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0 grid-pattern opacity-30 dark:opacity-15" />
      <div className="absolute top-0 left-1/3 w-[500px] h-[500px] bg-primary/5 rounded-full blur-3xl" />
      <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-primary/3 rounded-full blur-3xl" />
      
      <div className="relative z-10">
        {/* Header */}
        <header className="border-b border-border">
          <div className="max-w-7xl mx-auto px-6 py-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold tracking-tight">
                  <span className="text-primary">RLM</span>
                  <span className="text-muted-foreground ml-2 font-normal">Visualizer</span>
                </h1>
                <p className="text-sm text-muted-foreground mt-1">
                  Debug recursive language model execution traces
                </p>
              </div>
              <div className="flex items-center gap-4">
                <ThemeToggle />
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-mono">
                  <span className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                    READY
                  </span>
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-6 py-8">
          <div className="grid lg:grid-cols-2 gap-10">
            {/* Left Column - Upload & ASCII Art */}
            <div className="space-y-8">
              {/* Upload Section */}
              <div>
                <h2 className="text-sm font-medium mb-3 flex items-center gap-2 text-muted-foreground">
                  <span className="text-primary font-mono">01</span>
                  Upload Log File
                </h2>
                <FileUploader onFileLoaded={handleFileLoaded} />
              </div>
              
              {/* ASCII Architecture Diagram */}
              <div className="hidden lg:block">
                <h2 className="text-sm font-medium mb-3 flex items-center gap-2 text-muted-foreground">
                  <span className="text-primary font-mono">◈</span>
                  RLM Architecture
                </h2>
                <div className="bg-muted/50 border border-border rounded-lg p-4 overflow-x-auto">
                  <AsciiRLM />
                </div>
              </div>
            </div>

            {/* Right Column - Demo Logs & Loaded Files */}
            <div className="space-y-8">
              {/* Demo Logs Section */}
              <div>
                <h2 className="text-sm font-medium mb-3 flex items-center gap-2 text-muted-foreground">
                  <span className="text-primary font-mono">02</span>
                  Recent Traces
                  <span className="text-[10px] text-muted-foreground/60 ml-1">(latest 10)</span>
                </h2>
                
                {loadingDemos ? (
                  <Card>
                    <CardContent className="p-6 text-center">
                      <div className="animate-pulse flex items-center justify-center gap-2 text-muted-foreground text-sm">
                        Loading traces...
                      </div>
                    </CardContent>
                  </Card>
                ) : demoLogs.length === 0 ? (
                  <Card className="border-dashed">
                    <CardContent className="p-6 text-center text-muted-foreground text-sm">
                      No log files found in /public/logs/
                    </CardContent>
                  </Card>
                ) : (
                  <ScrollArea className="h-[320px]">
                    <div className="space-y-2 pr-4">
                      {demoLogs.map((demo) => (
                        <Card
                          key={demo.fileName}
                          onClick={() => loadDemoLog(demo.fileName)}
                          className={cn(
                            'cursor-pointer transition-all hover:scale-[1.01]',
                            'hover:border-primary/50 hover:bg-primary/5'
                          )}
                        >
                          <CardContent className="p-3">
                            <div className="flex items-center gap-3">
                              {/* Status indicator */}
                              <div className="relative flex-shrink-0">
                                <div className={cn(
                                  'w-2.5 h-2.5 rounded-full',
                                  demo.hasFinalAnswer 
                                    ? 'bg-primary' 
                                    : 'bg-muted-foreground/30'
                                )} />
                                {demo.hasFinalAnswer && (
                                  <div className="absolute inset-0 w-2.5 h-2.5 rounded-full bg-primary animate-ping opacity-50" />
                                )}
                              </div>
                              
                              {/* Content */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="font-mono text-xs text-foreground/80">
                                    {demo.fileName}
                                  </span>
                                  <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4">
                                    {demo.iterations} iter
                                  </Badge>
                                </div>
                                {demo.contextPreview && (
                                  <p className="text-[11px] font-mono text-muted-foreground truncate">
                                    {demo.contextPreview.length > 80 
                                      ? demo.contextPreview.slice(0, 80) + '...'
                                      : demo.contextPreview}
                                  </p>
                                )}
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </div>

              {/* Loaded Files Section */}
              {logFiles.length > 0 && (
                <div>
                  <h2 className="text-sm font-medium mb-3 flex items-center gap-2 text-muted-foreground">
                    <span className="text-primary font-mono">03</span>
                    Loaded Files
                  </h2>
                  <ScrollArea className="h-[200px]">
                    <div className="space-y-2 pr-4">
                      {logFiles.map((log) => (
                        <Card
                          key={log.fileName}
                          className={cn(
                            'cursor-pointer transition-all hover:scale-[1.01]',
                            'hover:border-primary/50 hover:bg-primary/5'
                          )}
                          onClick={() => setSelectedLog(log)}
                        >
                          <CardContent className="p-3">
                            <div className="flex items-center gap-3">
                              <div className="relative flex-shrink-0">
                                <div className={cn(
                                  'w-2.5 h-2.5 rounded-full',
                                  log.metadata.finalAnswer 
                                    ? 'bg-primary' 
                                    : 'bg-muted-foreground/30'
                                )} />
                                {log.metadata.finalAnswer && (
                                  <div className="absolute inset-0 w-2.5 h-2.5 rounded-full bg-primary animate-ping opacity-50" />
                                )}
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="font-mono text-xs truncate text-foreground/80">
                                    {log.fileName}
                                  </span>
                                  <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4">
                                    {log.metadata.totalIterations} iter
                                  </Badge>
                                </div>
                                <p className="text-[11px] text-muted-foreground truncate">
                                  {log.metadata.contextQuestion}
                                </p>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </ScrollArea>
                </div>
              )}
            </div>
          </div>
        </main>

        {/* Footer */}
        <footer className="border-t border-border mt-8">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
            <p className="text-[10px] text-muted-foreground font-mono">
              RLM Visualizer • Recursive Language Models
            </p>
            <p className="text-[10px] text-muted-foreground font-mono">
              Prompt → [LM ↔ REPL] → Answer
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
````

## File: visualizer/src/components/StatsCard.tsx
````typescript
'use client';

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface StatsCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  variant?: 'cyan' | 'magenta' | 'yellow' | 'green' | 'red';
  subtext?: string;
}

const variantStyles = {
  cyan: 'border-sky-500/30 bg-sky-500/5 dark:border-sky-400/30 dark:bg-sky-400/5',
  magenta: 'border-fuchsia-500/30 bg-fuchsia-500/5 dark:border-fuchsia-400/30 dark:bg-fuchsia-400/5',
  yellow: 'border-amber-500/30 bg-amber-500/5 dark:border-amber-400/30 dark:bg-amber-400/5',
  green: 'border-emerald-500/30 bg-emerald-500/5 dark:border-emerald-400/30 dark:bg-emerald-400/5',
  red: 'border-red-500/30 bg-red-500/5 dark:border-red-400/30 dark:bg-red-400/5',
};

const textStyles = {
  cyan: 'text-sky-600 dark:text-sky-400',
  magenta: 'text-fuchsia-600 dark:text-fuchsia-400',
  yellow: 'text-amber-600 dark:text-amber-400',
  green: 'text-emerald-600 dark:text-emerald-400',
  red: 'text-red-600 dark:text-red-400',
};

export function StatsCard({ label, value, icon, variant = 'cyan', subtext }: StatsCardProps) {
  return (
    <Card className={cn(
      'border transition-all duration-300 hover:scale-[1.02]',
      variantStyles[variant]
    )}>
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div className={cn('text-2xl', textStyles[variant])}>
            {icon}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs uppercase tracking-wider text-muted-foreground font-medium">
              {label}
            </p>
            <p className={cn('text-2xl font-bold tracking-tight', textStyles[variant])}>
              {value}
            </p>
            {subtext && (
              <p className="text-xs text-muted-foreground mt-0.5 truncate">
                {subtext}
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
````

## File: visualizer/package.json
````json
{
  "name": "visualizer",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint"
  },
  "dependencies": {
    "@radix-ui/react-accordion": "^1.2.12",
    "@radix-ui/react-collapsible": "^1.1.12",
    "@radix-ui/react-dropdown-menu": "^2.1.16",
    "@radix-ui/react-scroll-area": "^1.2.10",
    "@radix-ui/react-separator": "^1.1.8",
    "@radix-ui/react-slot": "^1.2.4",
    "@radix-ui/react-tabs": "^1.1.13",
    "@radix-ui/react-tooltip": "^1.2.8",
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "lucide-react": "^0.562.0",
    "next": "16.1.1",
    "next-themes": "^0.4.6",
    "react": "19.2.3",
    "react-dom": "19.2.3",
    "react-resizable-panels": "^4.0.15",
    "tailwind-merge": "^3.4.0"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4",
    "@types/node": "^20",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "eslint": "^9",
    "eslint-config-next": "16.1.1",
    "tailwindcss": "^4",
    "tw-animate-css": "^1.4.0",
    "typescript": "^5"
  }
}
````

## File: .pre-commit-config.yaml
````yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.14.10
    hooks:
      # Run the linter.
      - id: ruff
        args: [--fix, --config=pyproject.toml]

      # Run the formatter.
      - id: ruff-format
        args: [--config=pyproject.toml]

  - repo: local
    hooks:
      - id: ty
        name: ty
        entry: ty
        args:
          - check
          - --exit-zero
          - --output-format=concise
        language: python
        additional_dependencies:
          - ty==0.0.1a21
        types_or: [python, pyi]
````

## File: AGENTS.md
````markdown
# AGENTS.md

This guide covers best practices for contributing to the core Recursive Language Models `rlm` library and developing new environments (in `rlm/environments/`) and LM clients (in `rlm/clients/`).

## Setup

We use `uv` for developing `rlm`.
```bash
# Install uv (first time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup blank project if needed
uv init && uv venv --python 3.12
source .venv/bin/activate

# Install in editable mode
uv pip install -e .

# For Modal sandbox support
uv pip install -e ".[modal]"

# For Prime sandbox support
uv pip install -e ".[prime]"
```

## General Guidelines

### Code Style & Typing
- **Formatting**: Strict `ruff` enforcement. All PRs must pass `ruff check --fix .`
- **Typing**: Explicit types preferred
  - **OK**: `cast(...)`, `assert ...` for type narrowing
  - **SOMETIMES OK**: Untyped args for simple cases (e.g., prompt handlers)
  - **NOT OK**: `# type: ignore` without strong justification

### Naming Conventions
- **Methods**: snake_case
- **Classes**: PascalCase (e.g., `LocalREPL`, `PortkeyClient`)
- **Variables**: snake_case
- **Constants**: UPPER_CASE (e.g., `_SAFE_BUILTINS`, `RLM_SYSTEM_PROMPT`)

Do NOT use `_` prefix for private methods unless explicitly requested.

### Error Handling Philosophy
- **Fail fast, fail loud** - No defensive programming or silent fallbacks
- **Minimize branching** - Prefer single code paths; every `if`/`try` needs justification
- **Example**: Missing API key → immediate `ValueError`, not graceful fallback

## Core Repository Development

For PRs to `rlm` core:
```bash
git clone https://github.com/alexzhang13/rlm.git
cd rlm

# Standard development:
uv sync

# Install dev + test dependencies:
uv sync --group dev --group test

# Install pre-commit hooks:
uv run pre-commit install
```

### Dependencies
- Avoid new core dependencies
- Use optional extras for non-essential features (e.g., `modal` extra)
- Exception: tiny deps that simplify widely-used code

### Testing
- `uv run pytest` with discovery under `tests/`
- Write simple, deterministic unit tests
- Update tests when changing functionality
- For isolated environments, mock external services

### Documentation
- Keep concise and actionable
- Update README when behavior changes
- Avoid content duplication

### Scope
- Small, focused diffs
- One change per PR
- Backward compatibility is only desirable if it can be done without introducing excessive maintenance burden
- Delete dead code (don't guard it)

### Checklist

Before a PR:

```bash
# Run style + lint checks:
uv run ruff check --fix .
uv run ruff format .
uv run pre-commit run --all-files

# Run tests:
uv run pytest
```

Ensure docs and tests are updated if necessary, and dead code is deleted. Strive for minimal, surgical diffs.

## Developing LM Clients

LM client implementations live in `rlm/clients/`. All clients must inherit from `BaseLM`.

### Client Pattern

| Base Class | When to Use | Key Methods |
|------------|-------------|-------------|
| `BaseLM` | All LM integrations | `completion`, `acompletion`, `get_usage_summary`, `get_last_usage` |

### Requirements
- Inherit from `BaseLM` in `rlm/clients/base_lm.py`
- Implement all abstract methods: `completion`, `acompletion`, `get_usage_summary`, `get_last_usage`
- Track per-model usage (calls, input/output tokens)
- Handle both string and message list prompts
- Register client in `rlm/clients/__init__.py`

### Example Structure
```python
from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary

class MyClient(BaseLM):
    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(model_name=model_name, **kwargs)
        # Initialize your client
        
    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        # Handle both str and message list formats
        # Track usage with _track_cost()
        # Return response string
        
    def get_usage_summary(self) -> UsageSummary:
        # Return aggregated usage across all calls
```

### Configuration Guidelines
- **Environment variables**: ONLY for API keys (document in README)
- **Hardcode**: Default base URLs, reasonable defaults
- **Arguments**: Essential customization via `__init__()`

## Developing Environments

Environment implementations live in `rlm/environments/`. Choose the appropriate base class.

### Environment Pattern

| Pattern | Base Class | When to Use | Key Methods |
|---------|------------|-------------|-------------|
| **Non-isolated** | `NonIsolatedEnv` | Local execution, same machine | `setup`, `load_context`, `execute_code` |
| **Isolated** | `IsolatedEnv` | Cloud sandboxes (Modal, Prime) | `setup`, `load_context`, `execute_code` |

### Requirements
- Inherit from `NonIsolatedEnv` or `IsolatedEnv` in `rlm/environments/base_env.py`
- Implement all abstract methods: `setup`, `load_context`, `execute_code`
- Return `REPLResult` from `execute_code`
- Handle `lm_handler_address` for sub-LM calls via `llm_query()`
- Implement `cleanup()` for resource management
- Register environment in `rlm/environments/__init__.py`

### Key Implementation Details
- `setup()`: Initialize globals, locals, and helper functions
- `load_context()`: Make context available as `context` variable
- `execute_code()`: Execute code, capture stdout/stderr, return `REPLResult`
- Always provide `llm_query` and `llm_query_batched` functions in environment globals

### State Management
Environments must provide these globals to executed code:
- `context`: The loaded context payload
- `llm_query(prompt, model=None)`: For sub-LM calls
- `llm_query_batched(prompts, model=None)`: For batched sub-LM calls
- `FINAL_VAR(variable_name)`: For returning final answers

### Example Structure
```python
from rlm.environments.base_env import NonIsolatedEnv
from rlm.core.types import REPLResult

class MyEnvironment(NonIsolatedEnv):
    def __init__(self, lm_handler_address: tuple[str, int] | None = None, 
                 context_payload: dict | list | str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.lm_handler_address = lm_handler_address
        self.setup()
        if context_payload:
            self.load_context(context_payload)
            
    def setup(self):
        # Initialize execution namespace
        
    def load_context(self, context_payload: dict | list | str):
        # Make context available to executed code
        
    def execute_code(self, code: str) -> REPLResult:
        # Execute code and return REPLResult
        
    def cleanup(self):
        # Clean up resources
```

### Checklist
- Guidelines here are followed
- Environment works with basic RLM completion calls
- `cleanup()` properly releases all resources
- Sub-LM calls work via `llm_query()`

## Architecture: Environment ↔ LM Handler Communication

Understanding how environments communicate with the LM Handler is essential for developing new environments.

### Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Host Machine                                                       │
│  ┌─────────────┐       Socket (TCP)        ┌──────────────────────┐ │
│  │   RLM       │◄──────────────────────────►  LMHandler           │ │
│  │  (main)     │                           │  (ThreadingTCPServer)│ │
│  └─────────────┘                           └──────────────────────┘ │
│        │                                            ▲               │
│        ▼                                            │               │
│  ┌─────────────┐       Socket (TCP)                 │               │
│  │ LocalREPL   │────────────────────────────────────┘               │
│  │ (exec code) │  llm_query() → send_lm_request()                   │
│  └─────────────┘                                                    │
└─────────────────────────────────────────────────────────────────────┘
```

### Socket Protocol (Non-Isolated Environments)

Non-isolated environments like `LocalREPL` communicate directly with the `LMHandler` via TCP sockets using a length-prefixed JSON protocol:

**Protocol Format**: `4-byte big-endian length prefix + UTF-8 JSON payload`

```python
# Sending a message (from rlm/core/comms_utils.py)
def socket_send(sock: socket.socket, data: dict) -> None:
    payload = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(payload)) + payload)
```

**Request Flow**:
1. Environment's `llm_query(prompt)` is called during code execution
2. Creates `LMRequest` dataclass and calls `send_lm_request(address, request)`
3. Opens TCP connection to `LMHandler` at `(host, port)`
4. Sends length-prefixed JSON request
5. `LMHandler` processes via `LMRequestHandler.handle()`
6. Returns `LMResponse` with `RLMChatCompletion` or error

**Key Components**:
- `LMHandler` (`rlm/core/lm_handler.py`): Multi-threaded TCP server wrapping LM clients
- `LMRequest` / `LMResponse` (`rlm/core/comms_utils.py`): Typed request/response dataclasses
- `send_lm_request()` / `send_lm_request_batched()`: Helper functions for socket communication

### HTTP Broker Pattern (Isolated Environments)

Isolated environments (Modal, Prime) cannot directly connect to the host's socket server. They use an HTTP broker pattern:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Host Machine                                                               │
│  ┌─────────┐    Socket    ┌────────────┐    HTTP Poll    ┌────────────────┐ │
│  │   RLM   │◄────────────►│  LMHandler │◄────────────────│   ModalREPL    │ │
│  └─────────┘              └────────────┘                 │  (poller)      │ │
│                                                          └────────────────┘ │
│                                                                  │          │
│                                                          HTTP (tunnel)      │
│                                                                  │          │
└──────────────────────────────────────────────────────────────────┼──────────┘
                                                                   │
┌──────────────────────────────────────────────────────────────────┼──────────┐
│  Cloud Sandbox (Modal/Prime)                                     ▼          │
│  ┌─────────────┐     HTTP (localhost)     ┌─────────────────────────────┐   │
│  │ Exec Script │◄────────────────────────►│   Broker Server (Flask)     │   │
│  │ (exec code) │     /enqueue, etc.       │   - /enqueue (submit req)   │   │
│  └─────────────┘                          │   - /pending (poll reqs)    │   │
│                                           │   - /respond (return resp)  │   │
│                                           └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**How It Works**:

1. **Sandbox Setup**: Environment creates a cloud sandbox with an HTTP broker server running inside
2. **Tunnel Exposure**: Broker server is exposed via encrypted tunnel (e.g., Modal's `encrypted_ports`)
3. **Code Execution**: When `llm_query()` is called inside sandbox, it POSTs to `http://localhost:8080/enqueue`
4. **Request Queuing**: Broker queues the request and blocks waiting for response
5. **Host Polling**: `ModalREPL` on host polls `{tunnel_url}/pending` for new requests
6. **LM Forwarding**: Host forwards requests to `LMHandler` via socket, gets response
7. **Response Delivery**: Host POSTs response to `{tunnel_url}/respond`
8. **Unblocking**: Broker unblocks the original `/enqueue` call with the response

**Broker Endpoints**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/enqueue` | POST | Submit LLM request from sandbox code (blocks until response) |
| `/pending` | GET | Get list of pending requests (called by host poller) |
| `/respond` | POST | Submit response for a request ID (called by host poller) |
| `/health` | GET | Health check |

**Key Implementation Details**:
- Broker runs as a Flask server inside the sandbox
- Uses `threading.Event` for request/response synchronization
- Poller thread on host runs in background with 100ms polling interval
- State persistence via `dill` serialization to `/tmp/rlm_state.dill`

### Implementing a New Isolated Environment

When building a new isolated environment (e.g., for a new cloud provider):

1. **Create broker server** - Flask/HTTP server with `/enqueue`, `/pending`, `/respond` endpoints
2. **Expose tunnel** - Use provider's tunnel/port forwarding to expose broker to host
3. **Implement poller** - Background thread on host to poll and forward requests
4. **Build exec script** - Script that runs inside sandbox with `llm_query()` calling broker
5. **Handle state** - Serialize/deserialize execution state between code blocks

See `rlm/environments/modal_repl.py` as the canonical reference implementation.
````

## File: MANIFEST.IN
````
include README.md
include LICENSE
include pyproject.toml
recursive-include rlm *.py
global-exclude *.pyc
global-exclude __pycache__
global-exclude .DS_Store
global-exclude *.egg-info
````

## File: examples/lm_in_repl.py
````python
"""
Example: Using llm_query() from within a Local REPL environment.

This demonstrates the LM Handler + LocalREPL integration where code
running in the REPL can query the LLM via socket connection.
"""

import os

from dotenv import load_dotenv

from rlm.clients.portkey import PortkeyClient
from rlm.core.lm_handler import LMHandler
from rlm.environments.local_repl import LocalREPL

load_dotenv()

setup_code = """
secret = "1424424"
"""

context_payload = """
This is a test context. It should print out, revealing the magic number to be 4.
"""

code = """
response = llm_query("What is 2 + 2? Reply with just the number.")
print(response)
print(type(response))
print(context)
print("Secret from setup code: ", secret)
"""


def main():
    api_key = os.environ.get("PORTKEY_API_KEY")
    if not api_key:
        print("Error: PORTKEY_API_KEY not set")
        return
    print(f"PORTKEY_API_KEY: {api_key}")

    client = PortkeyClient(api_key=api_key, model_name="@openai/gpt-5-nano")
    print("Created Portkey client with model: @openai/gpt-5-nano")

    # Start LM Handler
    with LMHandler(client=client) as handler:
        print(f"LM Handler started at {handler.address}")

        # Create REPL with handler connection
        with LocalREPL(
            lm_handler_address=handler.address,
            context_payload=context_payload,
            setup_code=setup_code,
        ) as repl:
            print("LocalREPL created, connected to handler\n")

            # Run code that uses llm_query
            print(f"Executing: {code}")

            result = repl.execute_code(code)

            print(f"stdout: {result.stdout!r}")
            print(f"stderr: {result.stderr!r}")
            print(f"response variable: {repl.locals.get('response')!r}")
            print(f"locals: {repl.locals!r}")
            print(f"execution time: {result.execution_time:.3f}s")


if __name__ == "__main__":
    main()
````

## File: examples/quickstart.py
````python
import os

from dotenv import load_dotenv

from rlm import RLM
from rlm.logger import RLMLogger

load_dotenv()

logger = RLMLogger(log_dir="./logs")

rlm = RLM(
    backend="openai",  # or "portkey", etc.
    backend_kwargs={
        "model_name": "gpt-5-nano",
        "api_key": os.getenv("OPENAI_API_KEY"),
    },
    environment="docker",
    environment_kwargs={},
    max_depth=1,
    logger=logger,
    verbose=True,  # For printing to console with rich, disabled by default.
)

result = rlm.completion("Print me the first 5 powers of two, each on a newline.")

print(result)
````

## File: rlm/clients/azure_openai.py
````python
import os
from collections import defaultdict
from typing import Any

import openai
from dotenv import load_dotenv

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary

load_dotenv()

# Load API key from environment variable
DEFAULT_AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")


class AzureOpenAIClient(BaseLM):
    """
    LM Client for running models with the Azure OpenAI API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        azure_endpoint: str | None = None,
        api_version: str | None = None,
        azure_deployment: str | None = None,
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)

        if api_key is None:
            api_key = DEFAULT_AZURE_OPENAI_API_KEY

        if azure_endpoint is None:
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

        if api_version is None:
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

        if azure_deployment is None:
            azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

        if azure_endpoint is None:
            raise ValueError(
                "azure_endpoint is required for Azure OpenAI client. "
                "Set it via argument or AZURE_OPENAI_ENDPOINT environment variable."
            )

        self.client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            azure_deployment=azure_deployment,
        )
        self.async_client = openai.AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            azure_deployment=azure_deployment,
        )
        self.model_name = model_name
        self.azure_deployment = azure_deployment

        # Per-model usage tracking
        self.model_call_counts: dict[str, int] = defaultdict(int)
        self.model_input_tokens: dict[str, int] = defaultdict(int)
        self.model_output_tokens: dict[str, int] = defaultdict(int)
        self.model_total_tokens: dict[str, int] = defaultdict(int)

    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Azure OpenAI client.")

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
        )
        self._track_cost(response, model)
        return response.choices[0].message.content

    async def acompletion(
        self, prompt: str | list[dict[str, Any]], model: str | None = None
    ) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Azure OpenAI client.")

        response = await self.async_client.chat.completions.create(
            model=model,
            messages=messages,
        )
        self._track_cost(response, model)
        return response.choices[0].message.content

    def _track_cost(self, response: openai.ChatCompletion, model: str):
        self.model_call_counts[model] += 1

        usage = getattr(response, "usage", None)
        if usage is None:
            raise ValueError("No usage data received. Tracking tokens not possible.")

        self.model_input_tokens[model] += usage.prompt_tokens
        self.model_output_tokens[model] += usage.completion_tokens
        self.model_total_tokens[model] += usage.total_tokens

        # Track last call for handler to read
        self.last_prompt_tokens = usage.prompt_tokens
        self.last_completion_tokens = usage.completion_tokens

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model in self.model_call_counts:
            model_summaries[model] = ModelUsageSummary(
                total_calls=self.model_call_counts[model],
                total_input_tokens=self.model_input_tokens[model],
                total_output_tokens=self.model_output_tokens[model],
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self.last_prompt_tokens,
            total_output_tokens=self.last_completion_tokens,
        )
````

## File: rlm/environments/daytona_repl.py
````python
"""
Daytona REPL environment that runs Python code in Daytona sandboxes.

Uses the Daytona API (https://daytona.io/docs) for sandbox management.
"""

import base64
import json
import os
import textwrap
import threading
import time

import requests
from daytona import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
    Image,
    Resources,
    SessionExecuteRequest,
)

from rlm.core.comms_utils import LMRequest, send_lm_request, send_lm_request_batched
from rlm.core.types import REPLResult, RLMChatCompletion
from rlm.environments.base_env import IsolatedEnv

# =============================================================================
# Default Daytona Image
# =============================================================================


def get_default_image() -> Image:
    """
    Build a default Daytona image with common libraries for data science,
    math, and general Python work.
    """
    return (
        Image.debian_slim("3.11")
        .run_commands(
            "apt-get update && apt-get install -y build-essential \
                 git \
                 curl \
                 wget \
                 libopenblas-dev \
                 liblapack-dev",
        )
        .pip_install(
            # Data science essentials
            "numpy>=1.26.0",
            "pandas>=2.1.0",
            "scipy>=1.11.0",
            # Math & symbolic computation
            "sympy>=1.12",
            # HTTP & APIs
            "requests>=2.31.0",
            "httpx>=0.25.0",
            "flask>=3.0.0",
            # Data formats
            "pyyaml>=6.0",
            "toml>=0.10.2",
            # Utilities
            "tqdm>=4.66.0",
            "python-dateutil>=2.8.2",
            "regex>=2023.0.0",
            # For state serialization
            "dill>=0.3.7",
        )
    )


# =============================================================================
# Broker Server Script (runs inside sandbox, handles LLM request queue)
# =============================================================================

_BROKER_SCRIPT = textwrap.dedent(
    '''
import json
import threading
import uuid
from flask import Flask, request, jsonify

app = Flask(__name__)

# Request queue: {request_id: {"request": {...}, "response": None, "event": Event}}
pending_requests = {}
lock = threading.Lock()

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/enqueue", methods=["POST"])
def enqueue():
    """Called by sandbox code to submit an LLM request and wait for response."""
    data = request.json
    request_id = str(uuid.uuid4())
    event = threading.Event()

    with lock:
        pending_requests[request_id] = {
            "request": data,
            "response": None,
            "event": event,
        }

    # Wait for response (with timeout)
    event.wait(timeout=300)

    with lock:
        entry = pending_requests.pop(request_id, None)

    if entry and entry["response"] is not None:
        return jsonify(entry["response"])
    else:
        return jsonify({"error": "Request timed out"}), 504

@app.route("/pending")
def get_pending():
    """Called by DaytonaREPL to get pending requests."""
    with lock:
        pending = [
            {"id": rid, "request": entry["request"]}
            for rid, entry in pending_requests.items()
            if entry["response"] is None
        ]
    return jsonify({"pending": pending})

@app.route("/respond", methods=["POST"])
def respond():
    """Called by DaytonaREPL to submit a response."""
    data = request.json
    request_id = data.get("id")
    response = data.get("response")

    with lock:
        if request_id in pending_requests:
            pending_requests[request_id]["response"] = response
            pending_requests[request_id]["event"].set()
            return jsonify({"status": "ok"})

    return jsonify({"error": "Request not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
'''
)


# =============================================================================
# Execution Script (runs inside the sandbox for each code block)
# =============================================================================


def _build_exec_script(code: str, broker_port: int = 8080, depth: int = 1) -> str:
    """
    Build a script that executes code with state persistence.
    LLM queries go through the local broker server.
    """
    code_b64 = base64.b64encode(code.encode()).decode()

    return textwrap.dedent(
        f'''
import sys
import io
import json
import base64
import traceback
import os
import requests

try:
    import dill
except ImportError:
    import pickle as dill

# =============================================================================
# LLM Query Functions (via local broker)
# =============================================================================

BROKER_URL = "http://127.0.0.1:{broker_port}"

def llm_query(prompt, model=None):
    """Query the LM via the broker."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "single", "prompt": prompt, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return f"Error: {{data['error']}}"
        return data.get("response", "Error: No response")
    except Exception as e:
        return f"Error: LM query failed - {{e}}"


def llm_query_batched(prompts, model=None):
    """Query the LM with multiple prompts."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "batched", "prompts": prompts, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return [f"Error: {{data['error']}}"] * len(prompts)
        return data.get("responses", ["Error: No response"] * len(prompts))
    except Exception as e:
        return [f"Error: LM query failed - {{e}}"] * len(prompts)


# =============================================================================
# State Management
# =============================================================================

STATE_FILE = "/tmp/rlm_state.dill"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return dill.load(f)
        except:
            pass
    return {{}}

def save_state(state):
    clean_state = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            dill.dumps(v)
            clean_state[k] = v
        except:
            pass
    with open(STATE_FILE, "wb") as f:
        dill.dump(clean_state, f)

def serialize_locals(state):
    result = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            result[k] = repr(v)
        except:
            result[k] = f"<{{type(v).__name__}}>"
    return result

# =============================================================================
# Execution
# =============================================================================

_locals = load_state()

def FINAL_VAR(variable_name):
    variable_name = variable_name.strip().strip("\\"\\'")
    if variable_name in _locals:
        return str(_locals[variable_name])
    available = [k for k in _locals.keys() if not k.startswith("_")]
    if available:
        return f"Error: Variable '{{variable_name}}' not found. Available variables: {{available}}. You must create and assign a variable BEFORE calling FINAL_VAR on it."
    return f"Error: Variable '{{variable_name}}' not found. No variables have been created yet. You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."

def SHOW_VARS():
    available = {{k: type(v).__name__ for k, v in _locals.items() if not k.startswith("_")}}
    if not available:
        return "No variables created yet. Use ```repl``` blocks to create variables."
    return f"Available variables: {{available}}"

_globals = {{
    "__builtins__": __builtins__,
    "__name__": "__main__",
    "llm_query": llm_query,
    "llm_query_batched": llm_query_batched,
    "FINAL_VAR": FINAL_VAR,
    "SHOW_VARS": SHOW_VARS,
}}

code = base64.b64decode("{code_b64}").decode()

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
old_stdout, old_stderr = sys.stdout, sys.stderr

try:
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    combined = {{**_globals, **_locals}}
    exec(code, combined, combined)
    for key, value in combined.items():
        if key not in _globals and not key.startswith("_"):
            _locals[key] = value
except Exception as e:
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout = old_stdout
    sys.stderr = old_stderr

save_state(_locals)

result = {{
    "stdout": stdout_buf.getvalue(),
    "stderr": stderr_buf.getvalue(),
    "locals": serialize_locals(_locals),
}}
print(json.dumps(result))
'''
    )


class DaytonaREPL(IsolatedEnv):
    """
    Daytona REPL environment that runs Python code in a Daytona Sandbox.

    Uses Daytona preview URLs for LLM communication:
    - Sandbox runs a broker server exposed via preview URL (port 8080)
    - DaytonaREPL polls the broker for pending LLM requests
    - DaytonaREPL forwards requests to the LM handler and posts responses back
    """

    BROKER_PORT = 8080

    def __init__(
        self,
        api_key: str | None = None,
        target: str = "us",
        name: str = "rlm-sandbox",
        timeout: int = 600,
        cpu: int = 1,
        memory: int = 2,
        disk: int = 5,
        auto_stop_interval: int = 0,
        image: Image | None = None,
        lm_handler_address: tuple[str, int] | None = None,
        context_payload: dict | list | str | None = None,
        setup_code: str | None = None,
        persistent: bool = False,
        depth: int = 1,
        **kwargs,
    ):
        """
        Initialize a Daytona REPL environment.

        Args:
            api_key: Daytona API key. If None, uses DAYTONA_API_KEY env var.
            target: Daytona target region (e.g., "us", "eu").
            name: Unique identifier for the sandbox.
            timeout: Sandbox timeout in seconds.
            cpu: Number of CPU cores for the sandbox.
            memory: Memory in GB for the sandbox.
            disk: Disk space in GB for the sandbox.
            auto_stop_interval: Minutes of inactivity before auto-stop. 0 = run indefinitely.
            image: Daytona Image object for declarative building. If None, uses default image.
            lm_handler_address: (host, port) tuple for LM Handler server.
            context_payload: Initial context to load into the environment.
            setup_code: Optional code to run during setup.
            persistent: Whether to persist state across calls (not yet supported).
            depth: Depth level for LLM request routing (used by LMHandler).
            **kwargs: Additional arguments passed to base class.
        """
        if persistent:
            raise NotImplementedError(
                "Persistent REPLs are currently not supported for environment: DaytonaREPL"
            )
        super().__init__(persistent=persistent, depth=depth, **kwargs)

        self.api_key = api_key or os.getenv("DAYTONA_API_KEY")
        self.target = target
        self.name = name
        self.timeout = timeout
        self.cpu = cpu
        self.memory = memory
        self.disk = disk
        self.auto_stop_interval = auto_stop_interval
        self.image = image or get_default_image()
        self.lm_handler_address = lm_handler_address

        self.daytona = None
        self.sandbox = None
        self.broker_session_id: str = "rlm-broker-session"
        self.broker_url: str | None = None
        self.poller_thread: threading.Thread | None = None
        self.poller_stop = threading.Event()
        self.pending_llm_calls: list[RLMChatCompletion] = []
        self._calls_lock = threading.Lock()

        self.setup()

        if context_payload is not None:
            self.load_context(context_payload)

        if setup_code:
            self.execute_code(setup_code)

    def setup(self):
        """Create the Daytona sandbox, broker, and start polling."""
        # Initialize Daytona client
        config_kwargs = {"target": self.target}
        if self.api_key:
            config_kwargs["api_key"] = self.api_key

        config = DaytonaConfig(**config_kwargs)
        self.daytona = Daytona(config)

        # Create sandbox with specified resources
        resources = Resources(
            cpu=self.cpu,
            memory=self.memory,
            disk=self.disk,
        )

        params = CreateSandboxFromImageParams(
            name=self.name,
            image=self.image,
            resources=resources,
            auto_stop_interval=self.auto_stop_interval,
        )

        self.sandbox = self.daytona.create(params)

        # Upload the broker script
        self.sandbox.fs.upload_file(
            _BROKER_SCRIPT.encode("utf-8"),
            "broker_server.py",
        )

        # Create a session for the broker server
        self.sandbox.process.create_session(self.broker_session_id)

        # Start the broker server in the session (async execution)
        self.sandbox.process.execute_session_command(
            self.broker_session_id,
            SessionExecuteRequest(
                command="python broker_server.py",
                var_async=True,
            ),
        )

        # Wait for broker to be ready
        time.sleep(3)

        # Get the preview URL for the broker port
        try:
            preview_info = self.sandbox.get_preview_link(self.BROKER_PORT)
            self.broker_url = preview_info.url
            self._preview_token = preview_info.token
        except Exception:
            self.broker_url = None
            self._preview_token = None

        # Start polling thread if we have an LM handler
        if self.lm_handler_address and self.broker_url:
            self.poller_stop.clear()
            self.poller_thread = threading.Thread(target=self._poll_broker, daemon=True)
            self.poller_thread.start()

    def _get_headers(self) -> dict:
        """Get headers for broker requests including auth token."""
        headers = {"Content-Type": "application/json"}
        if hasattr(self, "_preview_token") and self._preview_token:
            headers["x-daytona-preview-token"] = self._preview_token
        return headers

    def _poll_broker(self):
        """Poll the broker for pending LLM requests and handle them."""
        while not self.poller_stop.is_set():
            try:
                # Get pending requests
                resp = requests.get(
                    f"{self.broker_url}/pending",
                    headers=self._get_headers(),
                    timeout=5,
                )
                pending = resp.json().get("pending", [])

                for item in pending:
                    request_id = item["id"]
                    req_data = item["request"]

                    # Handle the request
                    response = self._handle_llm_request(req_data)

                    # Send response back
                    requests.post(
                        f"{self.broker_url}/respond",
                        headers=self._get_headers(),
                        json={"id": request_id, "response": response},
                        timeout=10,
                    )

            except requests.exceptions.RequestException:
                pass
            except Exception:
                pass

            time.sleep(0.1)

    def _handle_llm_request(self, req_data: dict) -> dict:
        """Handle an LLM request from the sandbox."""
        req_type = req_data.get("type")
        model = req_data.get("model")

        if req_type == "single":
            prompt = req_data.get("prompt")
            request = LMRequest(prompt=prompt, model=model, depth=self.depth)
            response = send_lm_request(self.lm_handler_address, request)

            if not response.success:
                return {"error": response.error}

            # Track the call
            with self._calls_lock:
                self.pending_llm_calls.append(response.chat_completion)

            return {"response": response.chat_completion.response}

        elif req_type == "batched":
            prompts = req_data.get("prompts", [])
            responses = send_lm_request_batched(
                self.lm_handler_address, prompts, model=model, depth=self.depth
            )

            results = []
            for resp in responses:
                if not resp.success:
                    results.append(f"Error: {resp.error}")
                else:
                    with self._calls_lock:
                        self.pending_llm_calls.append(resp.chat_completion)
                    results.append(resp.chat_completion.response)

            return {"responses": results}

        return {"error": "Unknown request type"}

    def load_context(self, context_payload: dict | list | str):
        """Load context into the sandbox environment."""
        if isinstance(context_payload, str):
            escaped = context_payload.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            context_code = f'context = """{escaped}"""'
        else:
            context_json = json.dumps(context_payload)
            escaped_json = context_json.replace("\\", "\\\\").replace("'", "\\'")
            context_code = f"import json; context = json.loads('{escaped_json}')"

        self.execute_code(context_code)

    def execute_code(self, code: str) -> REPLResult:
        """Execute code in the Daytona sandbox and return result."""
        start_time = time.perf_counter()

        # Clear pending LLM calls
        with self._calls_lock:
            self.pending_llm_calls.clear()

        # Build and execute the script
        script = _build_exec_script(code, self.BROKER_PORT, self.depth)

        # Upload the script as a temporary file
        script_path = "/tmp/rlm_exec_script.py"
        self.sandbox.fs.upload_file(
            script.encode("utf-8"),
            script_path,
        )

        # Execute the script
        response = self.sandbox.process.exec(f"python {script_path}", timeout=self.timeout)

        # Read output
        stdout = response.result if response.exit_code == 0 else ""
        stderr = response.result if response.exit_code != 0 else ""

        # Collect LLM calls made during this execution
        with self._calls_lock:
            pending_calls = self.pending_llm_calls.copy()
            self.pending_llm_calls.clear()

        execution_time = time.perf_counter() - start_time

        # Parse the JSON result
        try:
            lines = stdout.strip().split("\n")
            result_json = lines[-1] if lines else "{}"
            result = json.loads(result_json)

            return REPLResult(
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", "") + stderr,
                locals=result.get("locals", {}),
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )
        except json.JSONDecodeError:
            return REPLResult(
                stdout=stdout,
                stderr=stderr or "Failed to parse execution result",
                locals={},
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )

    def cleanup(self):
        """Terminate the sandbox and stop polling."""
        # Stop the poller thread
        if self.poller_thread is not None:
            self.poller_stop.set()
            self.poller_thread.join(timeout=2)
            self.poller_thread = None

        # Delete the broker session
        if self.sandbox is not None:
            try:
                self.sandbox.process.delete_session(self.broker_session_id)
            except Exception:
                pass

            # Delete the sandbox
            try:
                self.sandbox.delete()
            except Exception:
                pass
            self.sandbox = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
````

## File: rlm/logger/rlm_logger.py
````python
"""
Logger for RLM iterations.

Writes RLMIteration data to JSON-lines files for analysis and debugging.
"""

import json
import os
import uuid
from datetime import datetime

from rlm.core.types import RLMIteration, RLMMetadata


class RLMLogger:
    """Logger that writes RLMIteration data to a JSON-lines file."""

    def __init__(self, log_dir: str, file_name: str = "rlm"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = str(uuid.uuid4())[:8]
        self.log_file_path = os.path.join(log_dir, f"{file_name}_{timestamp}_{run_id}.jsonl")

        self._iteration_count = 0
        self._metadata_logged = False

    def log_metadata(self, metadata: RLMMetadata):
        """Log RLM metadata as the first entry in the file."""
        if self._metadata_logged:
            return

        entry = {
            "type": "metadata",
            "timestamp": datetime.now().isoformat(),
            **metadata.to_dict(),
        }

        with open(self.log_file_path, "a") as f:
            json.dump(entry, f)
            f.write("\n")

        self._metadata_logged = True

    def log(self, iteration: RLMIteration):
        """Log an RLMIteration to the file."""
        self._iteration_count += 1

        entry = {
            "type": "iteration",
            "iteration": self._iteration_count,
            "timestamp": datetime.now().isoformat(),
            **iteration.to_dict(),
        }

        with open(self.log_file_path, "a") as f:
            json.dump(entry, f)
            f.write("\n")

    @property
    def iteration_count(self) -> int:
        return self._iteration_count
````

## File: tests/test_local_repl.py
````python
"""Comprehensive tests for LocalREPL environment."""

import os

from rlm.environments.local_repl import LocalREPL


class TestLocalREPLBasic:
    """Basic functionality tests for LocalREPL."""

    def test_simple_execution(self):
        """Test basic code execution."""
        repl = LocalREPL()
        result = repl.execute_code("x = 1 + 2")
        assert result.stderr == ""
        assert repl.locals["x"] == 3
        repl.cleanup()

    def test_print_output(self):
        """Test that print statements are captured."""
        repl = LocalREPL()
        result = repl.execute_code("print('Hello, World!')")
        assert "Hello, World!" in result.stdout
        repl.cleanup()

    def test_error_handling(self):
        """Test that errors are captured in stderr."""
        repl = LocalREPL()
        result = repl.execute_code("1 / 0")
        assert "ZeroDivisionError" in result.stderr
        repl.cleanup()

    def test_syntax_error(self):
        """Test syntax error handling."""
        repl = LocalREPL()
        result = repl.execute_code("def broken(")
        assert "SyntaxError" in result.stderr
        repl.cleanup()


class TestLocalREPLPersistence:
    """Tests for state persistence across executions."""

    def test_variable_persistence(self):
        """Test that variables persist across multiple code executions."""
        repl = LocalREPL()

        result1 = repl.execute_code("x = 42")
        assert result1.stderr == ""
        assert repl.locals["x"] == 42

        result2 = repl.execute_code("y = x + 8")
        assert result2.stderr == ""
        assert repl.locals["y"] == 50

        result3 = repl.execute_code("print(y)")
        assert "50" in result3.stdout

        repl.cleanup()

    def test_function_persistence(self):
        """Test that defined functions persist."""
        repl = LocalREPL()

        repl.execute_code(
            """
def greet(name):
    return f"Hello, {name}!"
"""
        )

        result = repl.execute_code("print(greet('World'))")
        assert "Hello, World!" in result.stdout
        repl.cleanup()

    def test_list_comprehension(self):
        """Test that list comprehensions work."""
        repl = LocalREPL()

        repl.execute_code("squares = [x**2 for x in range(5)]")
        assert repl.locals["squares"] == [0, 1, 4, 9, 16]

        result = repl.execute_code("print(sum(squares))")
        assert "30" in result.stdout
        repl.cleanup()


class TestLocalREPLBuiltins:
    """Tests for safe builtins and blocked functions."""

    def test_safe_builtins_available(self):
        """Test that safe builtins are available."""
        repl = LocalREPL()

        # Test various safe builtins
        _ = repl.execute_code("x = len([1, 2, 3])")
        assert repl.locals["x"] == 3

        _ = repl.execute_code("y = sum([1, 2, 3, 4])")
        assert repl.locals["y"] == 10

        _ = repl.execute_code("z = sorted([3, 1, 2])")
        assert repl.locals["z"] == [1, 2, 3]

        repl.cleanup()

    def test_imports_work(self):
        """Test that imports work."""
        repl = LocalREPL()
        result = repl.execute_code("import math\nx = math.pi")
        assert result.stderr == ""
        assert abs(repl.locals["x"] - 3.14159) < 0.001
        repl.cleanup()


class TestLocalREPLContextManager:
    """Tests for context manager usage."""

    def test_context_manager(self):
        """Test using LocalREPL as context manager."""
        with LocalREPL() as repl:
            _ = repl.execute_code("x = 100")
            assert repl.locals["x"] == 100


class TestLocalREPLHelpers:
    """Tests for helper functions (FINAL_VAR, etc.)."""

    def test_final_var_existing(self):
        """Test FINAL_VAR with existing variable."""
        repl = LocalREPL()
        repl.execute_code("answer = 42")
        _ = repl.execute_code("result = FINAL_VAR('answer')")
        assert repl.locals["result"] == "42"
        repl.cleanup()

    def test_final_var_missing(self):
        """Test FINAL_VAR with non-existent variable."""
        repl = LocalREPL()
        _ = repl.execute_code("result = FINAL_VAR('nonexistent')")
        assert "Error" in repl.locals["result"]
        repl.cleanup()

    def test_llm_query_no_handler(self):
        """Test llm_query without handler configured."""
        repl = LocalREPL()
        _ = repl.execute_code("response = llm_query('test')")
        assert "Error" in repl.locals["response"]
        repl.cleanup()


class TestLocalREPLContext:
    """Tests for context loading."""

    def test_string_context(self):
        """Test loading string context."""
        repl = LocalREPL(context_payload="This is the context data.")
        assert "context" in repl.locals
        assert repl.locals["context"] == "This is the context data."
        repl.cleanup()

    def test_dict_context(self):
        """Test loading dict context."""
        repl = LocalREPL(context_payload={"key": "value", "number": 42})
        assert "context" in repl.locals
        assert repl.locals["context"]["key"] == "value"
        assert repl.locals["context"]["number"] == 42
        repl.cleanup()

    def test_list_context(self):
        """Test loading list context."""
        repl = LocalREPL(context_payload=[1, 2, 3, "four"])
        assert "context" in repl.locals
        assert repl.locals["context"] == [1, 2, 3, "four"]
        repl.cleanup()


class TestLocalREPLCleanup:
    """Tests for cleanup behavior."""

    def test_cleanup_clears_state(self):
        """Test that cleanup clears the namespace."""
        repl = LocalREPL()
        repl.execute_code("x = 42")
        assert "x" in repl.locals
        repl.cleanup()
        assert len(repl.locals) == 0

    def test_temp_dir_created_and_cleaned(self):
        """Test that temp directory is created and cleaned up."""
        repl = LocalREPL()
        temp_dir = repl.temp_dir
        assert os.path.exists(temp_dir)
        repl.cleanup()
        assert not os.path.exists(temp_dir)


class TestLocalREPLSimulatingRLMNoPersistence:
    """
    Tests simulating RLM's non-persistent completion behavior.

    When RLM is configured without persistent=True (the default), each
    get_completion() call spawns a fresh environment and destroys it after.
    This test suite simulates that behavior to prove variables don't survive
    across RLM completions.

    Why this matters: This is NOT just testing that two Python objects don't
    share state (trivially true). This simulates the actual RLM workflow where
    environments are created and destroyed per completion.
    """

    def test_simulated_rlm_completions_reset_environment(self):
        """
        Simulates 2 RLM completions to show env resets between calls.

        Without persistent=True, RLM creates a fresh environment for each
        completion, so state doesn't carry over.
        """
        completion_1_env = LocalREPL()
        completion_1_env.execute_code("important_result = 42")
        assert completion_1_env.locals["important_result"] == 42
        completion_1_env.cleanup()

        completion_2_env = LocalREPL()
        result = completion_2_env.execute_code("print(important_result)")

        assert "NameError" in result.stderr
        assert "important_result" in result.stderr
        completion_2_env.cleanup()

    def test_simulated_rlm_completions_functions_not_preserved(self):
        """
        Simulates 2 RLM completions to show functions don't persist.
        """
        completion_1_env = LocalREPL()
        completion_1_env.execute_code("def my_helper(): return 'useful'")
        assert completion_1_env.execute_code("print(my_helper())").stdout.strip() == "useful"
        completion_1_env.cleanup()

        completion_2_env = LocalREPL()
        result = completion_2_env.execute_code("my_helper()")

        assert "NameError" in result.stderr
        assert "my_helper" in result.stderr
        completion_2_env.cleanup()
````

## File: tests/test_parsing.py
````python
"""Tests for parsing utilities."""

from unittest.mock import Mock

from rlm.core.types import CodeBlock, REPLResult, RLMIteration
from rlm.environments.local_repl import LocalREPL
from rlm.utils.parsing import (
    convert_context_for_repl,
    find_code_blocks,
    find_final_answer,
    format_execution_result,
    format_iteration,
)


class TestFindCodeBlocks:
    """Tests for find_code_blocks function."""

    def test_single_code_block(self):
        text = """Here's some code:
```repl
x = 1 + 2
print(x)
```
Done."""
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert "x = 1 + 2" in blocks[0]
        assert "print(x)" in blocks[0]

    def test_multiple_code_blocks(self):
        text = """First block:
```repl
a = 1
```
Second block:
```repl
b = 2
```
End."""
        blocks = find_code_blocks(text)
        assert len(blocks) == 2
        assert "a = 1" in blocks[0]
        assert "b = 2" in blocks[1]

    def test_no_code_blocks(self):
        text = "Just plain text without any code blocks."
        blocks = find_code_blocks(text)
        assert blocks == []

    def test_non_repl_code_blocks_ignored(self):
        text = """Python block:
```python
x = 1
```
REPL block:
```repl
y = 2
```
"""
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert "y = 2" in blocks[0]

    def test_multiline_code_block(self):
        text = """```repl
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
print(result)
```"""
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert "def factorial(n):" in blocks[0]
        assert "return n * factorial(n - 1)" in blocks[0]


class TestFindFinalAnswer:
    """Tests for find_final_answer function."""

    def test_final_answer(self):
        text = "The answer is:\nFINAL(42)"
        result = find_final_answer(text)
        assert result == "42"

    def test_final_var_answer(self):
        text = "Check the variable:\nFINAL_VAR(result)"
        # Create a mock environment that returns the variable value
        mock_env = Mock()
        mock_env.execute_code.return_value = REPLResult(stdout="42", stderr="", locals={})
        result = find_final_answer(text, environment=mock_env)
        assert result == "42"
        # Verify execute_code was called with the correct code
        mock_env.execute_code.assert_called_once()
        call_args = mock_env.execute_code.call_args[0][0]
        assert "FINAL_VAR('result')" in call_args or 'FINAL_VAR("result")' in call_args

    def test_final_var_without_environment(self):
        text = "Check the variable:\nFINAL_VAR(result)"
        # Without environment, FINAL_VAR should return None
        result = find_final_answer(text)
        assert result is None

    def test_no_final_answer(self):
        text = "Still working on the problem..."
        result = find_final_answer(text)
        assert result is None

    def test_final_with_multiline_content(self):
        text = """FINAL(This is a
multiline answer)"""
        result = find_final_answer(text)
        assert result is not None
        assert "multiline" in result
        assert "This is a" in result

    def test_final_must_be_at_start_of_line(self):
        # FINAL not at start of line should not match
        text = "The result is FINAL(42)"
        result = find_final_answer(text)
        assert result is None

    def test_final_with_whitespace(self):
        text = "   FINAL(answer with spaces)"
        result = find_final_answer(text)
        assert result == "answer with spaces"

    def test_final_with_nested_parentheses_greedy_matching(self):
        """Test that greedy matching captures content with nested parentheses correctly.
        Greedy matching (.*) matches to the last closing parenthesis, correctly handling
        nested parentheses in FINAL() content. Non-greedy (.*?) would incorrectly stop
        at the first closing parenthesis, breaking functions, tuples, and nested structures.
        """
        # Function call with nested parentheses
        text = "FINAL(func(arg1, arg2))"
        result = find_final_answer(text)
        assert result == "func(arg1, arg2)"

        # List and tuple with multiple closing parentheses
        text = "FINAL([1, 2, 3], (4, 5))"
        result = find_final_answer(text)
        assert result == "[1, 2, 3], (4, 5)"

        # Complex nested dictionary
        text = "FINAL({'key': 'value', 'nested': {'a': 1, 'b': 2}})"
        result = find_final_answer(text)
        assert "'key': 'value'" in result
        assert "'nested':" in result

        # Multiple function calls with nested parentheses
        text = "FINAL(calculate(10, 20) + process(data))"
        result = find_final_answer(text)
        assert result == "calculate(10, 20) + process(data)"

    def test_final_and_final_var_parsing(self):
        """Test that both FINAL and FINAL_VAR patterns are parsed correctly."""
        # Test FINAL with various content types
        test_cases_final = [
            ("FINAL(42)", "42"),
            ("FINAL('hello world')", "'hello world'"),
            ('FINAL("test")', '"test"'),
            ("FINAL(123.45)", "123.45"),
            ("FINAL([1, 2, 3])", "[1, 2, 3]"),
        ]

        for text, expected in test_cases_final:
            result = find_final_answer(text)
            assert result == expected, f"Failed for text: {text}"

        # Test FINAL_VAR with environment
        mock_env = Mock()
        mock_env.execute_code.return_value = REPLResult(
            stdout="computed_result", stderr="", locals={}
        )

        test_cases_final_var = [
            ("FINAL_VAR(result)", "result"),
            ("FINAL_VAR('my_var')", "my_var"),
            ('FINAL_VAR("another_var")', "another_var"),
            ("FINAL_VAR(answer)", "answer"),
        ]

        for text, var_name in test_cases_final_var:
            result = find_final_answer(text, environment=mock_env)
            assert result == "computed_result", f"Failed for text: {text}"
            # Verify the variable name was extracted correctly
            call_args = mock_env.execute_code.call_args[0][0]
            assert (
                var_name in call_args
                or f"'{var_name}'" in call_args
                or f'"{var_name}"' in call_args
            )

    def test_final_var_takes_precedence_over_final(self):
        """Test that FINAL_VAR is checked first and takes precedence over FINAL."""
        mock_env = Mock()
        mock_env.execute_code.return_value = REPLResult(stdout="var_value", stderr="", locals={})

        # If both appear, FINAL_VAR should be found first (checked first in the function)
        text = "FINAL_VAR(result)\nFINAL(direct_answer)"
        result = find_final_answer(text, environment=mock_env)
        assert result == "var_value"  # FINAL_VAR should be returned

        # Without environment, FINAL_VAR pattern is found but returns None (no fallback to FINAL)
        # This is expected behavior - FINAL_VAR takes precedence when found
        result = find_final_answer(text)
        assert result is None  # FINAL_VAR found but no environment, so returns None

        # Test that FINAL alone works when FINAL_VAR is not present
        text_final_only = "FINAL(direct_answer)"
        result = find_final_answer(text_final_only)
        assert result == "direct_answer"

    def test_final_var_retrieves_actual_variables_from_environment(self):
        """Test that FINAL_VAR actually retrieves variables from a real code environment."""
        # Create a real LocalREPL environment
        env = LocalREPL()

        try:
            # Execute code to create variables with different types
            env.execute_code("x = 42")
            env.execute_code("result = 'hello world'")
            env.execute_code("answer = [1, 2, 3, 4, 5]")
            env.execute_code("computed = 10 * 5 + 2")
            env.execute_code("nested = {'key': 'value', 'num': 123}")

            # Test retrieving integer variable
            text = "FINAL_VAR(x)"
            result = find_final_answer(text, environment=env)
            assert result == "42", f"Expected '42', got '{result}'"

            # Test retrieving string variable
            text = "FINAL_VAR(result)"
            result = find_final_answer(text, environment=env)
            assert result == "hello world", f"Expected 'hello world', got '{result}'"

            # Test retrieving list variable
            text = "FINAL_VAR(answer)"
            result = find_final_answer(text, environment=env)
            assert result == "[1, 2, 3, 4, 5]", f"Expected '[1, 2, 3, 4, 5]', got '{result}'"

            # Test retrieving computed variable
            text = "FINAL_VAR(computed)"
            result = find_final_answer(text, environment=env)
            assert result == "52", f"Expected '52', got '{result}'"

            # Test retrieving dictionary variable
            text = "FINAL_VAR(nested)"
            result = find_final_answer(text, environment=env)
            assert "'key': 'value'" in result or '"key": "value"' in result
            assert "'num': 123" in result or '"num": 123' in result

            # Test that variable updates are reflected
            env.execute_code("x = 100")
            text = "FINAL_VAR(x)"
            result = find_final_answer(text, environment=env)
            assert result == "100", f"Expected '100', got '{result}'"

            # Test that non-existent variable returns error message
            text = "FINAL_VAR(nonexistent)"
            result = find_final_answer(text, environment=env)
            assert "Error" in result or "not found" in result.lower()
        finally:
            env.cleanup()


class TestFormatExecutionResult:
    """Tests for format_execution_result function."""

    def test_stdout_only(self):
        result = REPLResult(stdout="Hello, World!", stderr="", locals={})
        formatted = format_execution_result(result)
        assert "Hello, World!" in formatted

    def test_stderr_only(self):
        result = REPLResult(stdout="", stderr="Error occurred", locals={})
        formatted = format_execution_result(result)
        assert "Error occurred" in formatted

    def test_with_locals(self):
        result = REPLResult(stdout="", stderr="", locals={"x": 42, "name": "test"})
        formatted = format_execution_result(result)
        assert "x" in formatted
        assert "name" in formatted

    def test_excludes_private_vars(self):
        result = REPLResult(stdout="", stderr="", locals={"_private": 1, "public": 2})
        formatted = format_execution_result(result)
        assert "public" in formatted
        # Private vars should be excluded
        assert "_private" not in formatted

    def test_empty_result(self):
        result = REPLResult(stdout="", stderr="", locals={})
        formatted = format_execution_result(result)
        assert formatted == "No output"


class TestFormatIteration:
    """Tests for format_iteration function."""

    def test_iteration_with_code_blocks(self):
        code_result = REPLResult(stdout="3", stderr="", locals={"x": 3})
        iteration = RLMIteration(
            prompt="Calculate 1+2",
            response="Let me calculate that.",
            code_blocks=[CodeBlock(code="x = 1 + 2\nprint(x)", result=code_result)],
        )
        messages = format_iteration(iteration)
        assert len(messages) == 2
        assert messages[0]["role"] == "assistant"
        assert messages[1]["role"] == "user"
        assert "x = 1 + 2" in messages[1]["content"]

    def test_iteration_without_code_blocks(self):
        iteration = RLMIteration(
            prompt="Just thinking",
            response="I'm considering the options.",
            code_blocks=[],
        )
        messages = format_iteration(iteration)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"

    def test_truncates_long_results(self):
        long_output = "x" * 30000
        code_result = REPLResult(stdout=long_output, stderr="", locals={})
        iteration = RLMIteration(
            prompt="Test",
            response="Running...",
            code_blocks=[CodeBlock(code="print('x' * 30000)", result=code_result)],
        )
        messages = format_iteration(iteration, max_character_length=100)
        # Result should be truncated
        assert len(messages[1]["content"]) < 30000


class TestConvertContextForRepl:
    """Tests for convert_context_for_repl function."""

    def test_string_context(self):
        context_data, context_str = convert_context_for_repl("Hello world")
        assert context_data is None
        assert context_str == "Hello world"

    def test_dict_context(self):
        context_data, context_str = convert_context_for_repl({"key": "value"})
        assert context_data == {"key": "value"}
        assert context_str is None

    def test_list_of_strings(self):
        context_data, context_str = convert_context_for_repl(["a", "b", "c"])
        assert context_data == ["a", "b", "c"]
        assert context_str is None

    def test_list_of_message_dicts(self):
        messages = [
            {"content": "Hello"},
            {"content": "World"},
        ]
        context_data, context_str = convert_context_for_repl(messages)
        assert context_data == ["Hello", "World"]
        assert context_str is None
````

## File: visualizer/src/components/AsciiGlobe.tsx
````typescript
'use client';

import { useEffect, useState } from 'react';

// RLM Architecture ASCII art inspired by the diagram
const RLM_SIMPLE = `
                    ╔══════════════════════════════════════════╗
  ┌──────────┐      ║            RLM (depth=0)                 ║      ┌──────────┐
  │  Prompt  │      ║  ┌────────────────────────────────────┐  ║      │  Answer  │
  │──────────│ ───► ║  │        Language Model (LM)         │  ║ ───► │──────────│
  │ context  │      ║  └─────────────────┬──────────────────┘  ║      │  FINAL() │
  └──────────┘      ║                   ↓ ↑                    ║      └──────────┘
                    ║  ┌─────────────────▼──────────────────┐  ║
                    ║  │       Environment (REPL)           │  ║
                    ║  │     context · llm_query()          │  ║
                    ║  └──────────┬────────────┬────────────┘  ║
                    ╚═════════════│════════════│═══════════════╝
                                  │            │
                         ┌────────▼────┐  ┌────▼────────┐
                         │ llm_query() │  │ llm_query() │
                         └────────┬────┘  └────┬────────┘
                                  │            │
                         ╔════════▼════╗  ╔════▼════════╗
                         ║ RLM (d=1)   ║  ║ RLM (d=1)   ║
                         ║  LM ↔ REPL  ║  ║  LM ↔ REPL  ║
                         ╚═════════════╝  ╚═════════════╝
`;

export function AsciiRLM() {
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setPulse(p => (p + 1) % 4);
    }, 600);
    return () => clearInterval(interval);
  }, []);

  // Colorize the ASCII art
  const colorize = (text: string) => {
    return text.split('\n').map((line, lineIdx) => (
      <div key={lineIdx} className="whitespace-pre">
        {line.split('').map((char, charIdx) => {
          const key = `${lineIdx}-${charIdx}`;
          
          // Box drawing characters - dim
          if ('┌┐└┘├┤┬┴┼─│╔╗╚╝║═'.includes(char)) {
            return <span key={key} className="text-muted-foreground/50">{char}</span>;
          }
          // Arrows - primary color
          if ('▼▲↓↑→←'.includes(char)) {
            const isPulsing = (lineIdx + charIdx + pulse) % 4 === 0;
            return (
              <span 
                key={key} 
                className={isPulsing ? 'text-primary' : 'text-primary/60'}
              >
                {char}
              </span>
            );
          }
          // Keywords
          if (line.includes('RLM') && char !== ' ') {
            if ('RLM'.includes(char)) {
              return <span key={key} className="text-primary font-bold">{char}</span>;
            }
          }
          if (line.includes('Prompt') || line.includes('Response') || line.includes('Answer')) {
            if (!'[]│─'.includes(char) && char !== ' ') {
              return <span key={key} className="text-amber-600 dark:text-amber-400">{char}</span>;
            }
          }
          if (line.includes('Language Model') || line.includes('LM')) {
            if (!'[]│─┌┐└┘'.includes(char) && char !== ' ') {
              return <span key={key} className="text-sky-600 dark:text-sky-400">{char}</span>;
            }
          }
          if (line.includes('REPL') || line.includes('Environment') || line.includes('context') || line.includes('llm_query')) {
            if (!'[]│─┌┐└┘'.includes(char) && char !== ' ') {
              return <span key={key} className="text-emerald-600 dark:text-emerald-400">{char}</span>;
            }
          }
          if (line.includes('depth=')) {
            if (!'()'.includes(char) && char !== ' ') {
              return <span key={key} className="text-muted-foreground">{char}</span>;
            }
          }
          // Default
          return <span key={key} className="text-muted-foreground/70">{char}</span>;
        })}
      </div>
    ));
  };

  return (
    <div className="font-mono text-[10px] leading-[1.3] select-none">
      <pre>{colorize(RLM_SIMPLE)}</pre>
    </div>
  );
}

// Compact inline diagram for header
export function AsciiRLMInline() {
  return (
    <div className="font-mono text-[9px] leading-tight select-none text-muted-foreground">
      <span className="text-primary">Prompt</span>
      <span> → </span>
      <span className="text-emerald-600 dark:text-emerald-400">[LM ↔ REPL]</span>
      <span> → </span>
      <span className="text-amber-600 dark:text-amber-400">Answer</span>
    </div>
  );
}
````

## File: visualizer/src/components/CodeBlock.tsx
````typescript
'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import { CodeBlock as CodeBlockType } from '@/lib/types';
import { CodeWithLineNumbers } from './CodeWithLineNumbers';

interface CodeBlockProps {
  block: CodeBlockType;
  index: number;
}

export function CodeBlock({ block, index }: CodeBlockProps) {
  const [isOpen, setIsOpen] = useState(true);
  const hasError = block.result?.stderr && block.result.stderr.length > 0;
  const hasOutput = block.result?.stdout && block.result.stdout.length > 0;
  const executionTime = block.result?.execution_time 
    ? block.result.execution_time.toFixed(2) 
    : null;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card className={cn(
        'border overflow-hidden transition-all',
        hasError 
          ? 'border-red-500/40 bg-red-500/5 dark:border-red-400/40 dark:bg-red-400/5' 
          : 'border-emerald-500/30 bg-emerald-500/5 dark:border-emerald-400/30 dark:bg-emerald-400/5'
      )}>
        <CollapsibleTrigger asChild>
          <CardHeader className="py-2 px-4 cursor-pointer hover:bg-muted/30 transition-colors">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-emerald-600 dark:text-emerald-400 font-mono text-sm">
                  {'>'}_
                </span>
                <CardTitle className="text-sm font-medium">
                  Code Block #{index + 1}
                </CardTitle>
              </div>
              <div className="flex items-center gap-2">
                {executionTime && (
                  <Badge variant="outline" className="font-mono text-xs">
                    {executionTime}s
                  </Badge>
                )}
                {hasError && (
                  <Badge variant="destructive" className="text-xs">
                    Error
                  </Badge>
                )}
                {hasOutput && !hasError && (
                  <Badge className="bg-emerald-500 text-white dark:bg-emerald-400 dark:text-emerald-950 text-xs">
                    Output
                  </Badge>
                )}
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                  <span className="text-xs">{isOpen ? '▼' : '▶'}</span>
                </Button>
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>
        
        <CollapsibleContent>
          <CardContent className="p-0">
            {/* Code */}
            <div className="bg-muted border-t border-border">
              <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                  Python
                </span>
              </div>
              <div className="code-block p-4 overflow-x-auto">
                <CodeWithLineNumbers code={block.code} language="python" />
              </div>
            </div>

            {/* Output */}
            {hasOutput && (
              <div className="border-t border-border bg-emerald-500/5 dark:bg-emerald-400/5">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400 font-medium">
                    stdout
                  </span>
                </div>
                <pre className="code-block p-4 overflow-x-auto">
                  <code className="text-emerald-700 dark:text-emerald-300">
                    {block.result.stdout}
                  </code>
                </pre>
              </div>
            )}

            {/* Errors */}
            {hasError && (
              <div className="border-t border-border bg-red-500/5 dark:bg-red-400/5">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-red-600 dark:text-red-400 font-medium">
                    stderr
                  </span>
                </div>
                <pre className="code-block p-4 overflow-x-auto">
                  <code className="text-red-700 dark:text-red-300">
                    {block.result.stderr}
                  </code>
                </pre>
              </div>
            )}

            {/* Locals */}
            {block.result?.locals && Object.keys(block.result.locals).length > 0 && (
              <div className="border-t border-border bg-muted/50">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                    Variables
                  </span>
                </div>
                <div className="p-4 grid grid-cols-2 md:grid-cols-3 gap-2">
                  {Object.entries(block.result.locals).map(([key, value]) => (
                    <div 
                      key={key} 
                      className="bg-background rounded px-2 py-1.5 font-mono text-xs overflow-hidden border border-border"
                    >
                      <span className="text-sky-600 dark:text-sky-400">{key}</span>
                      <span className="text-muted-foreground mx-1">=</span>
                      <span className="text-amber-600 dark:text-amber-400 truncate">
                        {typeof value === 'string' 
                          ? value.length > 30 ? value.slice(0, 30) + '...' : value
                          : JSON.stringify(value).slice(0, 30)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Sub-LM Calls */}
            {block.result?.rlm_calls && block.result.rlm_calls.length > 0 && (
              <div className="border-t border-border bg-fuchsia-500/5 dark:bg-fuchsia-400/5">
                <div className="px-3 py-1.5 border-b border-border/50 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-fuchsia-600 dark:text-fuchsia-400 font-medium">
                    Sub-LM Calls ({block.result.rlm_calls.length})
                  </span>
                </div>
                <div className="p-4 space-y-3">
                  {block.result.rlm_calls.map((call, i) => (
                    <div 
                      key={i}
                      className="border border-fuchsia-500/30 dark:border-fuchsia-400/30 rounded-lg p-3 bg-background"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <Badge className="bg-fuchsia-500 text-white dark:bg-fuchsia-400 dark:text-fuchsia-950 text-xs">
                          llm_query #{i + 1}
                        </Badge>
                        <div className="flex gap-2 text-xs text-muted-foreground">
                          <span>{call.prompt_tokens} prompt</span>
                          <span>•</span>
                          <span>{call.completion_tokens} completion</span>
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground mb-1">Prompt:</div>
                      <div className="text-sm bg-muted rounded p-2 mb-2 max-h-24 overflow-y-auto border border-border">
                        {typeof call.prompt === 'string' 
                          ? call.prompt.slice(0, 500) + (call.prompt.length > 500 ? '...' : '')
                          : JSON.stringify(call.prompt).slice(0, 500)}
                      </div>
                      <div className="text-xs text-muted-foreground mb-1">Response:</div>
                      <div className="text-sm bg-muted rounded p-2 max-h-24 overflow-y-auto border border-border">
                        {call.response.slice(0, 500) + (call.response.length > 500 ? '...' : '')}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
````

## File: visualizer/src/components/TrajectoryPanel.tsx
````typescript
'use client';

import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { RLMIteration, extractFinalAnswer } from '@/lib/types';

interface TrajectoryPanelProps {
  iterations: RLMIteration[];
  selectedIteration: number;
  onSelectIteration: (index: number) => void;
}

// Helper to format message content for display
function formatMessageContent(content: string): string {
  if (content.length > 8000) {
    return content.slice(0, 8000) + '\n\n... [content truncated for display]';
  }
  return content;
}

// Role icon component
function RoleIcon({ role }: { role: string }) {
  if (role === 'system') {
    return (
      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-violet-500/20">
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </div>
    );
  }
  if (role === 'user') {
    return (
      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-green-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      </div>
    );
  }
  // assistant
  return (
    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-blue-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
      <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
    </div>
  );
}

// Role label
function RoleLabel({ role }: { role: string }) {
  const labels: Record<string, { name: string; color: string }> = {
    system: { name: 'System Prompt', color: 'text-violet-600 dark:text-violet-400' },
    user: { name: 'User', color: 'text-emerald-600 dark:text-emerald-400' },
    assistant: { name: 'Assistant', color: 'text-sky-600 dark:text-sky-400' },
  };
  const config = labels[role] || { name: role, color: 'text-muted-foreground' };
  
  return (
    <span className={cn('font-semibold text-sm', config.color)}>
      {config.name}
    </span>
  );
}

export function TrajectoryPanel({ 
  iterations, 
  selectedIteration, 
}: TrajectoryPanelProps) {
  const currentIteration = iterations[selectedIteration];

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between bg-muted/30 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center">
            <span className="text-white text-sm font-bold">◈</span>
          </div>
          <div>
            <h2 className="font-semibold text-sm">Conversation</h2>
            <p className="text-[11px] text-muted-foreground">
              Iteration {selectedIteration + 1} of {iterations.length}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {currentIteration?.code_blocks.length > 0 && (
            <Badge variant="secondary" className="text-[10px]">
              {currentIteration.code_blocks.length} code
            </Badge>
          )}
          {currentIteration?.final_answer && (
            <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 text-[10px]">
              ✓ Answer
            </Badge>
          )}
        </div>
      </div>

      {/* Content - with explicit height constraint for scrolling */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-4 space-y-4">
            {/* Prompt messages */}
            {currentIteration?.prompt.map((msg, idx) => (
              <div 
                key={idx}
                className={cn(
                  'rounded-xl border p-4 transition-all',
                  msg.role === 'system' && 'bg-violet-500/5 border-violet-500/20 dark:bg-violet-500/10',
                  msg.role === 'user' && 'bg-emerald-500/5 border-emerald-500/20 dark:bg-emerald-500/10',
                  msg.role === 'assistant' && 'bg-sky-500/5 border-sky-500/20 dark:bg-sky-500/10'
                )}
              >
                {/* Message header */}
                <div className="flex items-center gap-3 mb-3 pb-3 border-b border-border/50">
                  <RoleIcon role={msg.role} />
                  <div className="flex-1">
                    <RoleLabel role={msg.role} />
                    {msg.role === 'system' && (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        Instructions & context setup
                      </p>
                    )}
                    {msg.role === 'user' && idx > 0 && (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        Continuation prompt
                      </p>
                    )}
                  </div>
                </div>
                
                {/* Message content */}
                <div className="bg-background/60 rounded-lg p-3 border border-border/50">
                  <pre className="whitespace-pre-wrap font-mono text-foreground/90 text-[12px] leading-relaxed overflow-x-auto">
                    {formatMessageContent(msg.content)}
                  </pre>
                </div>
              </div>
            ))}
            
            {/* Current response - highlighted */}
            {currentIteration?.response && (
              <div className="rounded-xl border-2 border-sky-500/40 bg-gradient-to-br from-sky-500/10 to-indigo-500/10 p-4 shadow-lg shadow-sky-500/5">
                {/* Response header */}
                <div className="flex items-center gap-3 mb-3 pb-3 border-b border-sky-500/20">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
                    <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                  </div>
                  <div className="flex-1">
                    <span className="font-semibold text-sm text-sky-600 dark:text-sky-400">
                      Model Response
                    </span>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      Iteration {currentIteration.iteration}
                    </p>
                  </div>
                  <Badge variant="outline" className="text-[10px] border-sky-500/30 text-sky-600 dark:text-sky-400">
                    {currentIteration.response.length.toLocaleString()} chars
                  </Badge>
                </div>
                
                {/* Response content */}
                <div className="bg-background/80 rounded-lg p-3 border border-sky-500/20">
                  <pre className="whitespace-pre-wrap font-mono text-foreground text-[12px] leading-relaxed overflow-x-auto">
                    {formatMessageContent(currentIteration.response)}
                  </pre>
                </div>
              </div>
            )}

            {/* Final answer highlight */}
            {currentIteration?.final_answer && (
              <div className="rounded-xl border-2 border-emerald-500/50 bg-gradient-to-br from-emerald-500/15 to-green-500/15 p-4 shadow-lg shadow-emerald-500/10">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-emerald-500 to-green-600 flex items-center justify-center shadow-lg shadow-emerald-500/30">
                    <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <span className="font-bold text-emerald-600 dark:text-emerald-400 text-base">
                      Final Answer
                    </span>
                    <p className="text-[10px] text-muted-foreground">
                      Task completed successfully
                    </p>
                  </div>
                </div>
                <div className="bg-background/80 rounded-lg p-4 border border-emerald-500/30">
                  <p className="text-[15px] font-medium text-foreground leading-relaxed">
                    {extractFinalAnswer(currentIteration.final_answer)}
                  </p>
                </div>
              </div>
            )}
            
            {/* Bottom padding for scroll */}
            <div className="h-4" />
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
````

## File: .github/workflows/docs.yml
````yaml
name: Deploy Docs to GitHub Pages

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: docs/package.json

      - name: Install dependencies
        working-directory: docs
        run: npm ci

      - name: Build
        working-directory: docs
        run: npm run build

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs/out

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    permissions:
      pages: write
      id-token: write
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
````

## File: visualizer/src/components/ExecutionPanel.tsx
````typescript
'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CodeBlock } from './CodeBlock';
import { RLMIteration } from '@/lib/types';

interface ExecutionPanelProps {
  iteration: RLMIteration | null;
}

export function ExecutionPanel({ iteration }: ExecutionPanelProps) {
  if (!iteration) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-muted/30 border border-border flex items-center justify-center">
            <span className="text-3xl opacity-50">◇</span>
          </div>
          <p className="text-muted-foreground text-sm">
            Select an iteration to view execution details
          </p>
        </div>
      </div>
    );
  }

  const totalSubCalls = iteration.code_blocks.reduce(
    (acc, block) => acc + (block.result?.rlm_calls?.length || 0), 
    0
  );

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b border-border bg-muted/30">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
              <span className="text-emerald-500 text-sm">⟨⟩</span>
            </div>
            <div>
              <h2 className="font-semibold text-sm">Code & Sub-LM Calls</h2>
              <p className="text-[11px] text-muted-foreground">
                Iteration {iteration.iteration} • {new Date(iteration.timestamp).toLocaleString()}
              </p>
            </div>
          </div>
        </div>
        
        {/* Quick stats */}
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="text-xs">
            {iteration.code_blocks.length} code block{iteration.code_blocks.length !== 1 ? 's' : ''}
          </Badge>
          {totalSubCalls > 0 && (
            <Badge className="bg-fuchsia-500/15 text-fuchsia-600 dark:text-fuchsia-400 border-fuchsia-500/30 text-xs">
              {totalSubCalls} sub-LM call{totalSubCalls !== 1 ? 's' : ''}
            </Badge>
          )}
          {iteration.final_answer && (
            <Badge className="bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30 text-xs">
              Has Final Answer
            </Badge>
          )}
        </div>
      </div>

      {/* Tabs - Code Execution and Sub-LM Calls only */}
      <Tabs defaultValue="code" className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-shrink-0 px-4 pt-3">
          <TabsList className="w-full grid grid-cols-2">
            <TabsTrigger value="code" className="text-xs">
              Code Execution
            </TabsTrigger>
            <TabsTrigger value="sublm" className="text-xs">
              Sub-LM Calls ({totalSubCalls})
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="flex-1 overflow-hidden">
          <TabsContent value="code" className="h-full m-0 data-[state=active]:flex data-[state=active]:flex-col">
            <ScrollArea className="flex-1 h-full">
              <div className="p-4 space-y-4">
                {iteration.code_blocks.length > 0 ? (
                  iteration.code_blocks.map((block, idx) => (
                    <CodeBlock key={idx} block={block} index={idx} />
                  ))
                ) : (
                  <Card className="border-dashed">
                    <CardContent className="p-8 text-center">
                      <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-muted/30 border border-border flex items-center justify-center">
                        <span className="text-xl opacity-50">⟨⟩</span>
                      </div>
                      <p className="text-muted-foreground text-sm">
                        No code was executed in this iteration
                      </p>
                      <p className="text-muted-foreground text-xs mt-1">
                        The model didn&apos;t write any code blocks
                      </p>
                    </CardContent>
                  </Card>
                )}
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="sublm" className="h-full m-0 data-[state=active]:flex data-[state=active]:flex-col">
            <ScrollArea className="flex-1 h-full">
              <div className="p-4 space-y-4">
                {totalSubCalls > 0 ? (
                  iteration.code_blocks.flatMap((block, blockIdx) =>
                    (block.result?.rlm_calls || []).map((call, callIdx) => (
                      <Card 
                        key={`${blockIdx}-${callIdx}`}
                        className="border-fuchsia-500/30 bg-fuchsia-500/5 dark:border-fuchsia-400/30 dark:bg-fuchsia-400/5"
                      >
                        <CardHeader className="py-3 px-4">
                          <div className="flex items-center justify-between flex-wrap gap-2">
                            <CardTitle className="text-sm flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full bg-fuchsia-500 dark:bg-fuchsia-400" />
                              llm_query() from Block #{blockIdx + 1}
                            </CardTitle>
                            <div className="flex gap-2">
                              <Badge variant="outline" className="text-[10px] font-mono">
                                {call.prompt_tokens} in
                              </Badge>
                              <Badge variant="outline" className="text-[10px] font-mono">
                                {call.completion_tokens} out
                              </Badge>
                              <Badge variant="outline" className="text-[10px] font-mono">
                                {call.execution_time.toFixed(2)}s
                              </Badge>
                            </div>
                          </div>
                        </CardHeader>
                        <CardContent className="px-4 pb-4 space-y-3">
                          <div>
                            <p className="text-xs text-muted-foreground mb-1.5 font-medium uppercase tracking-wider">
                              Prompt
                            </p>
                            <div className="bg-muted/50 rounded-lg p-3 max-h-40 overflow-y-auto border border-border">
                              <pre className="text-xs whitespace-pre-wrap font-mono">
                                {typeof call.prompt === 'string' 
                                  ? call.prompt 
                                  : JSON.stringify(call.prompt, null, 2)}
                              </pre>
                            </div>
                          </div>
                          <div>
                            <p className="text-xs text-muted-foreground mb-1.5 font-medium uppercase tracking-wider">
                              Response
                            </p>
                            <div className="bg-fuchsia-500/10 dark:bg-fuchsia-400/10 rounded-lg p-3 max-h-56 overflow-y-auto border border-fuchsia-500/20 dark:border-fuchsia-400/20">
                              <pre className="text-xs whitespace-pre-wrap font-mono text-fuchsia-700 dark:text-fuchsia-300">
                                {call.response}
                              </pre>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    ))
                  )
                ) : (
                  <Card className="border-dashed">
                    <CardContent className="p-8 text-center">
                      <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-muted/30 border border-border flex items-center justify-center">
                        <span className="text-xl opacity-50">⊘</span>
                      </div>
                      <p className="text-muted-foreground text-sm">
                        No sub-LM calls were made in this iteration
                      </p>
                      <p className="text-muted-foreground text-xs mt-1">
                        Sub-LM calls appear when using llm_query() in the REPL
                      </p>
                    </CardContent>
                  </Card>
                )}
              </div>
            </ScrollArea>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
````

## File: visualizer/src/components/IterationTimeline.tsx
````typescript
'use client';

import { useRef, useEffect } from 'react';
import { Badge } from '@/components/ui/badge';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { RLMIteration, extractFinalAnswer } from '@/lib/types';

interface IterationTimelineProps {
  iterations: RLMIteration[];
  selectedIteration: number;
  onSelectIteration: (index: number) => void;
}

function getIterationStats(iteration: RLMIteration) {
  let totalSubCalls = 0;
  let codeExecTime = 0;
  let hasError = false;
  
  for (const block of iteration.code_blocks) {
    if (block.result) {
      codeExecTime += block.result.execution_time || 0;
      if (block.result.stderr) hasError = true;
      if (block.result.rlm_calls) {
        totalSubCalls += block.result.rlm_calls.length;
      }
    }
  }
  
  // Use iteration_time if available, otherwise fall back to code execution time
  const iterTime = iteration.iteration_time ?? codeExecTime;
  
  // Estimate token counts from prompt (rough estimation)
  const promptText = iteration.prompt.map(m => m.content).join('');
  const estimatedInputTokens = Math.round(promptText.length / 4);
  const estimatedOutputTokens = Math.round(iteration.response.length / 4);
  
  return {
    codeBlocks: iteration.code_blocks.length,
    subCalls: totalSubCalls,
    execTime: iterTime,
    hasError,
    hasFinal: iteration.final_answer !== null,
    inputTokens: estimatedInputTokens,
    outputTokens: estimatedOutputTokens,
  };
}

export function IterationTimeline({ 
  iterations, 
  selectedIteration, 
  onSelectIteration 
}: IterationTimelineProps) {
  const selectedRef = useRef<HTMLDivElement>(null);
  
  // Auto-scroll to selected iteration
  useEffect(() => {
    if (selectedRef.current) {
      selectedRef.current.scrollIntoView({ 
        behavior: 'smooth', 
        block: 'nearest',
        inline: 'center' 
      });
    }
  }, [selectedIteration]);

  return (
    <div className="border-b border-border bg-muted/30 flex-shrink-0">
      {/* Section header */}
      <div className="px-4 pt-3 pb-2 flex items-center gap-2">
        <div className="w-5 h-5 rounded bg-primary/10 flex items-center justify-center">
          <svg className="w-3 h-3 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <span className="text-xs font-semibold text-foreground">Recursive Language Model Trajectory</span>
        <span className="text-[10px] text-muted-foreground">
          ({iterations.length} total)
        </span>
        <div className="flex-1" />
        <span className="text-[10px] text-muted-foreground">
          ← scroll →
        </span>
      </div>
      
      <ScrollArea className="w-full">
        <div className="flex gap-2 px-3 pb-3">
          {iterations.map((iteration, idx) => {
            const stats = getIterationStats(iteration);
            const isSelected = idx === selectedIteration;
            const finalAnswer = extractFinalAnswer(iteration.final_answer);
            const responseSnippet = iteration.response.slice(0, 60).replace(/\n/g, ' ');
            
            return (
              <div
                key={idx}
                ref={isSelected ? selectedRef : null}
                onClick={() => onSelectIteration(idx)}
                className={cn(
                  'flex-shrink-0 w-72 cursor-pointer transition-all duration-150 rounded-lg border',
                  isSelected
                    ? 'border-primary bg-primary/10 shadow-md shadow-primary/15'
                    : stats.hasFinal
                      ? 'border-emerald-500/40 bg-emerald-500/5 hover:border-emerald-500/60 dark:border-emerald-400/40 dark:bg-emerald-400/5'
                      : stats.hasError
                        ? 'border-red-500/40 bg-red-500/5 hover:border-red-500/60 dark:border-red-400/40 dark:bg-red-400/5'
                        : 'border-border hover:border-primary/40 hover:bg-muted/50'
                )}
              >
                {/* Compact single-row layout */}
                <div className="p-2.5 flex items-start gap-3">
                  {/* Iteration number */}
                  <div className={cn(
                    'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0',
                    isSelected
                      ? 'bg-primary text-primary-foreground'
                      : stats.hasFinal
                        ? 'bg-emerald-500 text-white dark:bg-emerald-400'
                        : stats.hasError
                          ? 'bg-red-500 text-white dark:bg-red-400'
                          : 'bg-muted text-muted-foreground'
                  )}>
                    {idx + 1}
                  </div>
                  
                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    {/* Top row: badges */}
                    <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
                      {stats.hasFinal && (
                        <Badge className="bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/30 text-[9px] px-1 py-0 h-4">
                          FINAL
                        </Badge>
                      )}
                      {stats.hasError && (
                        <Badge variant="destructive" className="text-[9px] px-1 py-0 h-4">
                          ERR
                        </Badge>
                      )}
                      {stats.codeBlocks > 0 && (
                        <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
                          {stats.codeBlocks} code
                        </span>
                      )}
                      {stats.subCalls > 0 && (
                        <span className="text-[10px] text-fuchsia-600 dark:text-fuchsia-400">
                          {stats.subCalls} sub
                        </span>
                      )}
                      <span className="text-[10px] text-muted-foreground ml-auto">
                        {stats.execTime.toFixed(2)}s
                      </span>
                    </div>
                    
                    {/* Response preview */}
                    <p className="text-[10px] text-muted-foreground truncate leading-relaxed">
                      {responseSnippet}{iteration.response.length > 60 ? '...' : ''}
                    </p>
                    
                    {/* Bottom row: tokens */}
                    <div className="flex items-center gap-2 mt-1 text-[9px] font-mono text-muted-foreground/70">
                      <span>
                        <span className="text-sky-600 dark:text-sky-400">{(stats.inputTokens / 1000).toFixed(1)}k</span>
                        <span className="mx-0.5">→</span>
                        <span className="text-emerald-600 dark:text-emerald-400">{(stats.outputTokens / 1000).toFixed(1)}k</span>
                      </span>
                      {stats.hasFinal && finalAnswer && (
                        <>
                          <span className="text-border">│</span>
                          <span className="text-amber-600 dark:text-amber-400 truncate max-w-[100px]">
                            = {finalAnswer}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </div>
  );
}
````

## File: visualizer/src/components/LogViewer.tsx
````typescript
'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { StatsCard } from './StatsCard';
import { TrajectoryPanel } from './TrajectoryPanel';
import { ExecutionPanel } from './ExecutionPanel';
import { IterationTimeline } from './IterationTimeline';
import { ThemeToggle } from './ThemeToggle';
import { RLMLogFile } from '@/lib/types';

interface LogViewerProps {
  logFile: RLMLogFile;
  onBack: () => void;
}

export function LogViewer({ logFile, onBack }: LogViewerProps) {
  const [selectedIteration, setSelectedIteration] = useState(0);
  const { iterations, metadata, config } = logFile;

  const goToPrevious = useCallback(() => {
    setSelectedIteration(prev => Math.max(0, prev - 1));
  }, []);

  const goToNext = useCallback(() => {
    setSelectedIteration(prev => Math.min(iterations.length - 1, prev + 1));
  }, [iterations.length]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' || e.key === 'j') {
        goToPrevious();
      } else if (e.key === 'ArrowRight' || e.key === 'k') {
        goToNext();
      } else if (e.key === 'Escape') {
        onBack();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [goToPrevious, goToNext, onBack]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-background">
      {/* Top Bar - Compact header */}
      <header className="border-b border-border bg-card/80 backdrop-blur-sm">
        <div className="px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={onBack}
                className="text-muted-foreground hover:text-foreground"
              >
                ← Back
              </Button>
              <div className="h-5 w-px bg-border" />
              <div>
                <h1 className="font-semibold flex items-center gap-2 text-sm">
                  <span className="text-primary">◈</span>
                  {logFile.fileName}
                </h1>
                <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                  {config.root_model ?? 'Unknown model'} • {config.backend ?? 'Unknown backend'} • {config.environment_type ?? 'Unknown env'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {metadata.hasErrors && (
                <Badge variant="destructive" className="text-xs">Has Errors</Badge>
              )}
              {metadata.finalAnswer && (
                <Badge className="bg-emerald-500 hover:bg-emerald-600 text-white text-xs">
                  Completed
                </Badge>
              )}
              <ThemeToggle />
            </div>
          </div>
        </div>
      </header>

      {/* Question & Answer + Stats Row */}
      <div className="border-b border-border bg-muted/30 px-6 py-4">
        <div className="flex gap-6">
          {/* Question & Answer Summary */}
          <Card className="flex-1 bg-gradient-to-r from-primary/5 to-accent/5 border-primary/20">
            <CardContent className="p-4">
              <div className="grid md:grid-cols-2 gap-4">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">
                    Context / Question
                  </p>
                  <p className="text-sm font-medium line-clamp-2">
                    {metadata.contextQuestion}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">
                    Final Answer
                  </p>
                  <p className="text-sm font-medium text-emerald-600 dark:text-emerald-400 line-clamp-2">
                    {metadata.finalAnswer || 'Not yet completed'}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Quick Stats */}
          <div className="flex gap-2">
            <StatsCard
              label="Iterations"
              value={metadata.totalIterations}
              icon="◎"
              variant="cyan"
            />
            <StatsCard
              label="Code"
              value={metadata.totalCodeBlocks}
              icon="⟨⟩"
              variant="green"
            />
            <StatsCard
              label="Sub-LM"
              value={metadata.totalSubLMCalls}
              icon="◇"
              variant="magenta"
            />
            <StatsCard
              label="Exec"
              value={`${metadata.totalExecutionTime.toFixed(2)}s`}
              icon="⏱"
              variant="yellow"
            />
          </div>
        </div>
      </div>

      {/* Iteration Timeline - Full width scrollable row */}
      <IterationTimeline
        iterations={iterations}
        selectedIteration={selectedIteration}
        onSelectIteration={setSelectedIteration}
      />

      {/* Main Content - Resizable Split View */}
      <div className="flex-1 min-h-0">
        <ResizablePanelGroup orientation="horizontal">
          {/* Left Panel - Prompt & Response */}
          <ResizablePanel defaultSize={50} minSize={20} maxSize={80}>
            <div className="h-full border-r border-border">
              <TrajectoryPanel
                iterations={iterations}
                selectedIteration={selectedIteration}
                onSelectIteration={setSelectedIteration}
              />
            </div>
          </ResizablePanel>

          <ResizableHandle withHandle className="bg-border hover:bg-primary/30 transition-colors" />

          {/* Right Panel - Code Execution & Sub-LM Calls */}
          <ResizablePanel defaultSize={50} minSize={20} maxSize={80}>
            <div className="h-full bg-background">
              <ExecutionPanel
                iteration={iterations[selectedIteration] || null}
              />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      {/* Keyboard hint footer */}
      <div className="border-t border-border bg-muted/30 px-6 py-1.5">
        <div className="flex items-center justify-center gap-6 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <kbd className="px-1 py-0.5 bg-muted rounded text-[9px]">←</kbd>
            <kbd className="px-1 py-0.5 bg-muted rounded text-[9px]">→</kbd>
            Navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1 py-0.5 bg-muted rounded text-[9px]">Esc</kbd>
            Back
          </span>
        </div>
      </div>
    </div>
  );
}
````

## File: .gitignore
````
# MacOS
.DS_Store

# Logs
logs/

# Byte-compiled / optimized / DLL files
__pycache__/
*.py[codz]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
!docs/src/lib/
!visualizer/src/lib/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# PyInstaller
#  Usually these files are written by a python script from a template
#  before PyInstaller builds the exe, so as to inject date/other infos into it.
*.manifest
*.spec

# Installer logs
pip-log.txt
pip-delete-this-directory.txt

# Unit test / coverage reports
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py.cover
.hypothesis/
.pytest_cache/
cover/

# Translations
*.mo
*.pot

# Django stuff:
*.log
local_settings.py
db.sqlite3
db.sqlite3-journal

# Flask stuff:
instance/
.webassets-cache

# Scrapy stuff:
.scrapy

# Sphinx documentation
docs/_build/

# PyBuilder
.pybuilder/
target/

# Jupyter Notebook
.ipynb_checkpoints

# IPython
profile_default/
ipython_config.py

# pyenv
#   For a library or package, you might want to ignore these files since the code is
#   intended to run in multiple environments; otherwise, check them in:
# .python-version

# pipenv
#   According to pypa/pipenv#598, it is recommended to include Pipfile.lock in version control.
#   However, in case of collaboration, if having platform-specific dependencies or dependencies
#   having no cross-platform support, pipenv may install dependencies that don't work, or not
#   install all needed dependencies.
#Pipfile.lock

# UV
#   Similar to Pipfile.lock, it is generally recommended to include uv.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
#uv.lock

# poetry
#   Similar to Pipfile.lock, it is generally recommended to include poetry.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
#   https://python-poetry.org/docs/basic-usage/#commit-your-poetrylock-file-to-version-control
#poetry.lock
#poetry.toml

# pdm
#   Similar to Pipfile.lock, it is generally recommended to include pdm.lock in version control.
#   pdm recommends including project-wide configuration in pdm.toml, but excluding .pdm-python.
#   https://pdm-project.org/en/latest/usage/project/#working-with-version-control
#pdm.lock
#pdm.toml
.pdm-python
.pdm-build/

# pixi
#   Similar to Pipfile.lock, it is generally recommended to include pixi.lock in version control.
#pixi.lock
#   Pixi creates a virtual environment in the .pixi directory, just like venv module creates one
#   in the .venv directory. It is recommended not to include this directory in version control.
.pixi

# PEP 582; used by e.g. github.com/David-OConnor/pyflow and github.com/pdm-project/pdm
__pypackages__/

# Celery stuff
celerybeat-schedule
celerybeat.pid

# SageMath parsed files
*.sage.py

# Environments
.env
.envrc
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# Spyder project settings
.spyderproject
.spyproject

# Rope project settings
.ropeproject

# mkdocs documentation
/site

# mypy
.mypy_cache/
.dmypy.json
dmypy.json

# Pyre type checker
.pyre/

# pytype static type analyzer
.pytype/

# Cython debug symbols
cython_debug/

# PyCharm
#  JetBrains specific template is maintained in a separate JetBrains.gitignore that can
#  be found at https://github.com/github/gitignore/blob/main/Global/JetBrains.gitignore
#  and can be added to the global gitignore or merged into this file.  For a more nuclear
#  option (not recommended) you can uncomment the following to ignore the entire idea folder.
#.idea/

# Abstra
# Abstra is an AI-powered process automation framework.
# Ignore directories containing user credentials, local state, and settings.
# Learn more at https://abstra.io/docs
.abstra/

# Visual Studio Code
#  Visual Studio Code specific template is maintained in a separate VisualStudioCode.gitignore 
#  that can be found at https://github.com/github/gitignore/blob/main/Global/VisualStudioCode.gitignore
#  and can be added to the global gitignore or merged into this file. However, if you prefer, 
#  you could uncomment the following to ignore the entire vscode folder
# .vscode/

# Ruff stuff:
.ruff_cache/

# PyPI configuration file
.pypirc

# Cursor
#  Cursor is an AI-powered code editor. `.cursorignore` specifies files/directories to
#  exclude from AI features like autocomplete and code analysis. Recommended for sensitive data
#  refer to https://docs.cursor.com/context/ignore-files
.cursorignore
.cursorindexingignore

# Marimo
marimo/_static/
marimo/_lsp/
__marimo__/
````

## File: rlm/environments/prime_repl.py
````python
"""
Prime Intellect REPL environment that runs Python code in Prime Sandboxes.

Uses the Prime SDK (https://docs.primeintellect.ai/sandboxes/sdk) for sandbox management.
Follows the same HTTP broker pattern as ModalREPL for LLM communication.
"""

import base64
import json
import textwrap
import threading
import time
from typing import Any

import requests
from dotenv import load_dotenv
from prime_sandboxes import (
    APIClient,
    BackgroundJob,
    CreateSandboxRequest,
    SandboxClient,
)

from rlm.core.comms_utils import LMRequest, send_lm_request, send_lm_request_batched
from rlm.core.types import REPLResult, RLMChatCompletion
from rlm.environments.base_env import IsolatedEnv
from rlm.environments.constants import APT_PACKAGES, PIP_PACKAGES

load_dotenv()

# =============================================================================
# Broker Server Script (runs inside sandbox, handles LLM request queue)
# =============================================================================

_BROKER_SCRIPT = textwrap.dedent(
    '''
import json
import threading
import uuid
from flask import Flask, request, jsonify

app = Flask(__name__)

# Request queue: {{request_id: {{"request": {{...}}, "response": None, "event": Event}}}}
pending_requests = {{}}
lock = threading.Lock()

@app.route("/health")
def health():
    return jsonify({{"status": "ok"}})

@app.route("/enqueue", methods=["POST"])
def enqueue():
    """Called by sandbox code to submit an LLM request and wait for response."""
    data = request.json
    request_id = str(uuid.uuid4())
    event = threading.Event()

    with lock:
        pending_requests[request_id] = {{
            "request": data,
            "response": None,
            "event": event,
        }}

    # Wait for response (with timeout)
    event.wait(timeout=300)

    with lock:
        entry = pending_requests.pop(request_id, None)

    if entry and entry["response"] is not None:
        return jsonify(entry["response"])
    else:
        return jsonify({{"error": "Request timed out"}}), 504

@app.route("/pending")
def get_pending():
    """Called by PrimeREPL to get pending requests."""
    with lock:
        pending = [
            {{"id": rid, "request": entry["request"]}}
            for rid, entry in pending_requests.items()
            if entry["response"] is None
        ]
    return jsonify({{"pending": pending}})

@app.route("/respond", methods=["POST"])
def respond():
    """Called by PrimeREPL to submit a response."""
    data = request.json
    request_id = data.get("id")
    response = data.get("response")

    with lock:
        if request_id in pending_requests:
            pending_requests[request_id]["response"] = response
            pending_requests[request_id]["event"].set()
            return jsonify({{"status": "ok"}})

    return jsonify({{"error": "Request not found"}}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port={broker_port}, threaded=True)
'''
)


# =============================================================================
# Execution Script (runs inside the sandbox for each code block)
# =============================================================================


def _build_exec_script(code: str, broker_port: int = 8888, depth: int = 1) -> str:
    """
    Build a script that executes code with state persistence.
    LLM queries go through the local broker server.
    """
    code_b64 = base64.b64encode(code.encode()).decode()

    return textwrap.dedent(
        f'''
import sys
import io
import json
import base64
import traceback
import os
import requests

try:
    import dill
except ImportError:
    import pickle as dill

# =============================================================================
# LLM Query Functions (via local broker)
# =============================================================================

BROKER_URL = "http://127.0.0.1:{broker_port}"

def llm_query(prompt, model=None):
    """Query the LM via the broker."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "single", "prompt": prompt, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return f"Error: {{data['error']}}"
        return data.get("response", "Error: No response")
    except Exception as e:
        return f"Error: LM query failed - {{e}}"


def llm_query_batched(prompts, model=None):
    """Query the LM with multiple prompts."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "batched", "prompts": prompts, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return [f"Error: {{data['error']}}"] * len(prompts)
        return data.get("responses", ["Error: No response"] * len(prompts))
    except Exception as e:
        return [f"Error: LM query failed - {{e}}"] * len(prompts)


# =============================================================================
# State Management
# =============================================================================

STATE_FILE = "/tmp/rlm_state.dill"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return dill.load(f)
        except:
            pass
    return {{}}

def save_state(state):
    clean_state = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            dill.dumps(v)
            clean_state[k] = v
        except:
            pass
    with open(STATE_FILE, "wb") as f:
        dill.dump(clean_state, f)

def serialize_locals(state):
    result = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            result[k] = repr(v)
        except:
            result[k] = f"<{{type(v).__name__}}>"
    return result

# =============================================================================
# Execution
# =============================================================================

_locals = load_state()

def FINAL_VAR(variable_name):
    variable_name = variable_name.strip().strip("\\"\\'")
    if variable_name in _locals:
        return str(_locals[variable_name])
    available = [k for k in _locals.keys() if not k.startswith("_")]
    if available:
        return f"Error: Variable '{{variable_name}}' not found. Available variables: {{available}}. You must create and assign a variable BEFORE calling FINAL_VAR on it."
    return f"Error: Variable '{{variable_name}}' not found. No variables have been created yet. You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."

def SHOW_VARS():
    available = {{k: type(v).__name__ for k, v in _locals.items() if not k.startswith("_")}}
    if not available:
        return "No variables created yet. Use ```repl``` blocks to create variables."
    return f"Available variables: {{available}}"

_globals = {{
    "__builtins__": __builtins__,
    "__name__": "__main__",
    "llm_query": llm_query,
    "llm_query_batched": llm_query_batched,
    "FINAL_VAR": FINAL_VAR,
    "SHOW_VARS": SHOW_VARS,
}}

code = base64.b64decode("{code_b64}").decode()

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
old_stdout, old_stderr = sys.stdout, sys.stderr

try:
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    combined = {{**_globals, **_locals}}
    exec(code, combined, combined)
    for key, value in combined.items():
        if key not in _globals and not key.startswith("_"):
            _locals[key] = value
except Exception as e:
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout = old_stdout
    sys.stderr = old_stderr

save_state(_locals)

result = {{
    "stdout": stdout_buf.getvalue(),
    "stderr": stderr_buf.getvalue(),
    "locals": serialize_locals(_locals),
}}
print(json.dumps(result))
'''
    )


class PrimeREPL(IsolatedEnv):
    """
    Prime Intellect REPL environment that runs Python code in Prime Sandboxes.

    Uses Prime's port exposure for LLM communication:
    - Sandbox runs a broker server exposed via sandboxes.expose()
    - PrimeREPL polls the broker for pending LLM requests
    - PrimeREPL forwards requests to the LM handler and posts responses back
    """

    BROKER_PORT = 8888

    def __init__(
        self,
        name: str = "rlm-sandbox",
        docker_image: str = "python:3.11-slim",
        timeout_minutes: int = 60,
        lm_handler_address: tuple[str, int] | None = None,
        context_payload: dict | list | str | None = None,
        setup_code: str | None = None,
        network_access: bool = True,
        persistent: bool = False,
        depth: int = 1,
        **kwargs: Any,
    ):
        super().__init__(persistent=persistent, depth=depth, **kwargs)

        if persistent:
            raise NotImplementedError(
                "Persistent REPLs are currently not supported for environment: PrimeREPL"
            )

        self.name = name
        self.docker_image = docker_image
        self.timeout_minutes = timeout_minutes
        self.lm_handler_address = lm_handler_address
        self.network_access = network_access

        # Client and sandbox state
        self.client: SandboxClient | None = None
        self.sandbox_id: str | None = None
        self.broker_job: BackgroundJob | None = None
        self.broker_url: str | None = None
        self.broker_exposure_id: str | None = None

        # Polling thread for LLM requests
        self.poller_thread: threading.Thread | None = None
        self.poller_stop = threading.Event()
        self.pending_llm_calls: list[RLMChatCompletion] = []
        self._calls_lock = threading.Lock()

        self.setup()

        if context_payload is not None:
            self.load_context(context_payload)

        if setup_code:
            self.execute_code(setup_code)

    def setup(self):
        """Create the Prime sandbox, broker, and start polling."""
        # Create the client
        self.client = SandboxClient(APIClient())

        # Create the sandbox
        request = CreateSandboxRequest(
            name=self.name,
            docker_image=self.docker_image,
            timeout_minutes=self.timeout_minutes,
            network_access=self.network_access,
        )
        sandbox = self.client.create(request)
        self.sandbox_id = sandbox.id

        # Wait for sandbox to be ready
        self.client.wait_for_creation(self.sandbox_id, max_attempts=self.timeout_minutes * 60)

        # Install apt dependencies
        apt_cmd = "apt-get update && apt-get install -y " + " ".join(APT_PACKAGES)
        self.client.execute_command(self.sandbox_id, apt_cmd)

        # Install pip dependencies
        pip_cmd = "pip install " + " ".join(f'"{pkg}"' for pkg in PIP_PACKAGES)
        self.client.execute_command(self.sandbox_id, pip_cmd)

        # Write the broker script to the sandbox.
        # Unlike Modal's sandbox.exec() which accepts separate args, Prime's
        # start_background_job() takes a shell command string. We write to a file
        # to avoid shell escaping issues with quotes/special chars in the script.
        broker_script = _BROKER_SCRIPT.format(broker_port=self.BROKER_PORT)
        broker_script_b64 = base64.b64encode(broker_script.encode()).decode()
        self.client.execute_command(
            self.sandbox_id,
            f"echo '{broker_script_b64}' | base64 -d > /tmp/broker.py",
        )

        # Start the broker as a background job
        self.broker_job = self.client.start_background_job(
            self.sandbox_id,
            "python /tmp/broker.py",
        )

        # Wait for broker to be ready with health check
        self._wait_for_broker()

        # Expose the broker port
        exposed = self.client.expose(self.sandbox_id, port=self.BROKER_PORT, name="rlm-broker")
        self.broker_url = exposed.url
        self.broker_exposure_id = exposed.exposure_id

        # Start polling thread if we have an LM handler
        if self.lm_handler_address and self.broker_url:
            self.poller_stop.clear()
            self.poller_thread = threading.Thread(target=self._poll_broker, daemon=True)
            self.poller_thread.start()

    def _wait_for_broker(self, max_attempts: int = 30):
        """Wait for the broker to be ready by checking health endpoint."""
        # Use Python to check health (curl may not be installed in slim images)
        health_check_cmd = (
            f'python -c "import requests; '
            f"r = requests.get('http://127.0.0.1:{self.BROKER_PORT}/health', timeout=2); "
            f'print(r.text)"'
        )

        for _ in range(max_attempts):
            time.sleep(1)
            try:
                result = self.client.execute_command(
                    self.sandbox_id,
                    health_check_cmd,
                )
                if "ok" in result.stdout.lower():
                    return
            except Exception:
                pass

        # Get broker logs for debugging by reading log files directly
        error_info = "Broker failed to start."
        if self.broker_job:
            try:
                stdout_result = self.client.execute_command(
                    self.sandbox_id,
                    f"cat {self.broker_job.stdout_log_file} 2>/dev/null || echo 'No stdout log'",
                )
                stderr_result = self.client.execute_command(
                    self.sandbox_id,
                    f"cat {self.broker_job.stderr_log_file} 2>/dev/null || echo 'No stderr log'",
                )
                error_info += f"\nstdout: {stdout_result.stdout}\nstderr: {stderr_result.stdout}"
            except Exception as e:
                error_info += f"\nFailed to read logs: {e}"
        raise RuntimeError(error_info)

    def _poll_broker(self):
        """Poll the broker for pending LLM requests and handle them."""
        while not self.poller_stop.is_set():
            try:
                # Get pending requests
                resp = requests.get(
                    f"{self.broker_url}/pending",
                    timeout=10,
                )
                pending = resp.json().get("pending", [])

                for item in pending:
                    request_id = item["id"]
                    req_data = item["request"]

                    # Handle the request
                    response = self._handle_llm_request(req_data)

                    # Send response back
                    requests.post(
                        f"{self.broker_url}/respond",
                        json={"id": request_id, "response": response},
                        timeout=10,
                    )

            except requests.exceptions.RequestException:
                pass
            except Exception:
                pass

            time.sleep(0.1)

    def _handle_llm_request(self, req_data: dict) -> dict:
        """Handle an LLM request from the sandbox."""
        req_type = req_data.get("type")
        model = req_data.get("model")

        if req_type == "single":
            prompt = req_data.get("prompt")
            request = LMRequest(prompt=prompt, model=model, depth=self.depth)
            response = send_lm_request(self.lm_handler_address, request)

            if not response.success:
                return {"error": response.error}

            # Track the call
            with self._calls_lock:
                self.pending_llm_calls.append(response.chat_completion)

            return {"response": response.chat_completion.response}

        elif req_type == "batched":
            prompts = req_data.get("prompts", [])
            responses = send_lm_request_batched(
                self.lm_handler_address, prompts, model=model, depth=self.depth
            )

            results = []
            for resp in responses:
                if not resp.success:
                    results.append(f"Error: {resp.error}")
                else:
                    with self._calls_lock:
                        self.pending_llm_calls.append(resp.chat_completion)
                    results.append(resp.chat_completion.response)

            return {"responses": results}

        return {"error": "Unknown request type"}

    def load_context(self, context_payload: dict | list | str):
        """Load context into the sandbox environment."""
        if isinstance(context_payload, str):
            escaped = context_payload.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            context_code = f'context = """{escaped}"""'
        else:
            context_json = json.dumps(context_payload)
            escaped_json = context_json.replace("\\", "\\\\").replace("'", "\\'")
            context_code = f"import json; context = json.loads('{escaped_json}')"

        self.execute_code(context_code)

    def execute_code(self, code: str) -> REPLResult:
        """Execute code in the Prime sandbox and return result."""
        start_time = time.perf_counter()

        # Clear pending LLM calls
        with self._calls_lock:
            self.pending_llm_calls.clear()

        # Build and write the script
        script = _build_exec_script(code, self.BROKER_PORT, self.depth)
        script_b64 = base64.b64encode(script.encode()).decode()
        self.client.execute_command(
            self.sandbox_id,
            f"echo '{script_b64}' | base64 -d > /tmp/exec_script.py",
        )

        # Execute the script
        result = self.client.execute_command(
            self.sandbox_id, "python /tmp/exec_script.py", timeout=60 * 10
        )
        stdout = result.stdout
        stderr = result.stderr

        # Collect LLM calls made during this execution
        with self._calls_lock:
            pending_calls = self.pending_llm_calls.copy()
            self.pending_llm_calls.clear()

        execution_time = time.perf_counter() - start_time

        # Parse the JSON result
        try:
            lines = stdout.strip().split("\n")
            result_json = lines[-1] if lines else "{}"
            parsed = json.loads(result_json)

            return REPLResult(
                stdout=parsed.get("stdout", ""),
                stderr=parsed.get("stderr", "") + stderr,
                locals=parsed.get("locals", {}),
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )
        except json.JSONDecodeError:
            return REPLResult(
                stdout=stdout,
                stderr=stderr or "Failed to parse execution result",
                locals={},
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )

    def cleanup(self):
        """Terminate the sandbox and stop polling."""
        # Stop the poller thread
        if self.poller_thread is not None:
            self.poller_stop.set()
            self.poller_thread.join(timeout=2)
            self.poller_thread = None

        # Cleanup sandbox resources
        if self.client is None or self.sandbox_id is None:
            return

        # Unexpose the broker port
        if self.broker_exposure_id:
            try:
                self.client.unexpose(self.sandbox_id, self.broker_exposure_id)
            except Exception:
                pass

        # Delete the sandbox
        try:
            self.client.delete(self.sandbox_id)
        except Exception:
            pass

        self.sandbox_id = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
````

## File: rlm/utils/parsing.py
````python
"""
Parsing utilities for RLM trjaectories.
"""

import re
from typing import TYPE_CHECKING

from rlm.core.types import REPLResult, RLMIteration

if TYPE_CHECKING:
    from rlm.environments.base_env import BaseEnv


def find_code_blocks(text: str) -> list[str]:
    """
    Find REPL code blocks in text wrapped in triple backticks and return List of content(s).
    Returns None if no code blocks are found.
    """
    pattern = r"```repl\s*\n(.*?)\n```"
    results = []

    for match in re.finditer(pattern, text, re.DOTALL):
        code_content = match.group(1).strip()
        results.append(code_content)

    return results


def find_final_answer(text: str, environment: "BaseEnv | None" = None) -> str | None:
    """
    Find FINAL(...) or FINAL_VAR(...) statement in response and return the final answer string.

    If FINAL_VAR is found and an environment is provided, executes code to retrieve the variable value.
    Returns None if neither pattern is found.

    Args:
        text: The response text to parse
        environment: Optional environment to execute code for FINAL_VAR retrieval

    Returns:
        The final answer string, or None if no final answer pattern is found
    """
    # Check for FINAL_VAR pattern first - must be at start of line
    final_var_pattern = r"^\s*FINAL_VAR\((.*?)\)"
    match = re.search(final_var_pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        variable_name = match.group(1).strip().strip('"').strip("'")
        if environment is not None:
            result = environment.execute_code(f"print(FINAL_VAR({variable_name!r}))")
            final_answer = result.stdout.strip()
            if final_answer == "":
                final_answer = result.stderr.strip() or ""
            return final_answer
        return None

    # Check for FINAL pattern - must be at start of line
    # Use greedy matching to capture content with nested parentheses
    final_pattern = r"^\s*FINAL\((.*)\)\s*$"
    match = re.search(final_pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()

    return None


def format_iteration(
    iteration: RLMIteration, max_character_length: int = 20000
) -> list[dict[str, str]]:
    """
    Format an RLM iteration (including all code blocks) to append to the message history for
    the prompt of the LM in the next iteration. We also truncate code execution results
    that exceed the max_character_length.

    Args:
        iteration: The iteration to format
        max_character_length: The maximum character length of the result

    Returns:
        A list of messages to add to the next prompt
    """
    messages = [{"role": "assistant", "content": iteration.response}]

    for code_block in iteration.code_blocks:
        code = code_block.code
        result = code_block.result
        result = format_execution_result(result)
        if len(result) > max_character_length:
            result = (
                result[:max_character_length]
                + f"... + [{len(result) - max_character_length} chars...]"
            )

        execution_message = {
            "role": "user",
            "content": f"Code executed:\n```python\n{code}\n```\n\nREPL output:\n{result}",
        }
        messages.append(execution_message)
    return messages


################
# TODO: Remove and refactor these soon
################


def format_execution_result(result: REPLResult) -> str:
    """
    Format the execution result as a string for display.

    Args:
        result: The REPLResult object to format.
    """
    result_parts = []

    if result.stdout:
        result_parts.append(f"\n{result.stdout}")

    if result.stderr:
        result_parts.append(f"\n{result.stderr}")

    # Show some key variables (excluding internal ones)
    important_vars = {}
    for key, value in result.locals.items():
        if not key.startswith("_") and key not in [
            "__builtins__",
            "__name__",
            "__doc__",
        ]:
            # Only show simple types or short representations
            if isinstance(value, (str, int, float, bool, list, dict, tuple)):
                important_vars[key] = ""

    if important_vars:
        result_parts.append(f"REPL variables: {list(important_vars.keys())}\n")

    return "\n\n".join(result_parts) if result_parts else "No output"


def check_for_final_answer(response: str, repl_env, logger) -> str | None:
    """Check if response contains a final answer."""
    # Use the new find_final_answer function which handles both FINAL and FINAL_VAR
    return find_final_answer(response, environment=repl_env)


def convert_context_for_repl(context):
    """
    Convert REPL context to either some
    """
    if isinstance(context, dict):
        context_data = context
        context_str = None
    elif isinstance(context, str):
        context_data = None
        context_str = context
    elif isinstance(context, list):
        if len(context) > 0 and isinstance(context[0], dict):
            if "content" in context[0]:
                context_data = [msg.get("content", "") for msg in context]
            else:
                context_data = context
            context_str = None
        else:
            context_data = context
            context_str = None
    else:
        context_data = context
        context_str = None

    return context_data, context_str
````

## File: rlm/clients/base_lm.py
````python
from abc import ABC, abstractmethod
from typing import Any

from rlm.core.types import ModelUsageSummary, UsageSummary


class BaseLM(ABC):
    """
    Base class for all language model routers / clients. When the RLM makes sub-calls, it currently
    does so in a model-agnostic way, so this class provides a base interface for all language models.
    """

    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs

    @abstractmethod
    def completion(self, prompt: str | dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    async def acompletion(self, prompt: str | dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_usage_summary(self) -> UsageSummary:
        """Get cost summary for all model calls."""
        raise NotImplementedError

    @abstractmethod
    def get_last_usage(self) -> ModelUsageSummary:
        """Get the last cost summary of the model."""
        raise NotImplementedError
````

## File: rlm/environments/base_env.py
````python
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from rlm.core.types import REPLResult


class BaseEnv(ABC):
    """
    Base REPL-like environment that the RLM uses to interact with. The primary types are isolated and non-isolated,
    where isolated environments are on a separate machine from the LM.
    """

    def __init__(self, persistent: bool = False, depth: int = 1, **kwargs):
        self.persistent = persistent
        self.depth = depth
        self.kwargs = kwargs

    @abstractmethod
    def setup(self):
        raise NotImplementedError

    @abstractmethod
    def load_context(self, context_payload: dict | list | str):
        raise NotImplementedError

    @abstractmethod
    def execute_code(self, code: str) -> REPLResult:
        raise NotImplementedError


class IsolatedEnv(BaseEnv, ABC):
    """
    These environments (e.g. Prime Envs, Modal Envs) sit on a completely separate machine from the LM,
    guaranteeing complete isolation from the LM process.
    """

    def __init__(self, persistent: bool = False, **kwargs):
        super().__init__(persistent=persistent, **kwargs)

    @abstractmethod
    def setup(self):
        raise NotImplementedError

    @abstractmethod
    def load_context(self, context_payload: dict | list | str):
        raise NotImplementedError

    @abstractmethod
    def execute_code(self, code: str) -> REPLResult:
        raise NotImplementedError


class NonIsolatedEnv(BaseEnv, ABC):
    """
    These environments run on the same machine as the LM, and provide different levels of isolation
    depending on the choice of environment. The simplest, default is a local Python REPL that runs
    as a subprocess.
    """

    def __init__(self, persistent: bool = False, **kwargs):
        super().__init__(persistent=persistent, **kwargs)

    @abstractmethod
    def setup(self):
        raise NotImplementedError

    @abstractmethod
    def load_context(self, context_payload: dict | list | str):
        raise NotImplementedError

    @abstractmethod
    def execute_code(self, code: str) -> REPLResult:
        raise NotImplementedError


@runtime_checkable
class SupportsPersistence(Protocol):
    """Protocol for environments that support persistent multi-turn sessions.

    CHECKING SUPPORT:
        Use isinstance(env, SupportsPersistence) to check if an environment
        supports persistence capabilities.

    IMPLEMENTING THIS PROTOCOL:
        To add persistence to your environment, implement these 5 methods.
        See tests/test_local_repl_persistent.py for expected behavior.

    VERSIONING BEHAVIOR:
        Contexts and histories are versioned with numeric suffixes:
        - First context  -> context_0, context_1, context_2, ...
        - First history  -> history_0, history_1, history_2, ...

    ALIASING BEHAVIOR:
        The unversioned names always point to index 0:
        - context  -> context_0 (first context)
        - history  -> history_0 (first history)

    EXAMPLE IMPLEMENTATION:
        See rlm/environments/local_repl.py for a complete reference.

    TESTS:
        - Unit tests: tests/test_local_repl_persistent.py
        - Integration tests: tests/test_multi_turn_integration.py

        Run: uv run pytest tests/test_local_repl_persistent.py -v
    """

    def update_handler_address(self, address: tuple[str, int]) -> None:
        """Update the LM handler address for nested LLM calls.

        Called by RLM when the handler address changes between completions.
        Store the address so llm_query() calls from executed code can reach
        the LM handler.

        Args:
            address: (host, port) tuple for the LM handler server.
        """
        ...

    def add_context(
        self, context_payload: dict | list | str, context_index: int | None = None
    ) -> int:
        """Add a context payload, making it available as context_N in code.

        Versioning:
            - context_index=None: auto-increment (0, 1, 2, ...)
            - context_index=N: use specific index N

        Storage:
            Must store so executed code can access:
            - context_0, context_1, etc. (versioned)
            - context (alias to context_0)

        Args:
            context_payload: The context data (string, dict, or list).
            context_index: Optional specific index, or None to auto-increment.

        Returns:
            The index used (for auto-increment, returns the assigned index).
        """
        ...

    def get_context_count(self) -> int:
        """Return the number of contexts added so far.

        Used by RLM to inform the model how many contexts are available.
        """
        ...

    def add_history(
        self, message_history: list[dict[str, Any]], history_index: int | None = None
    ) -> int:
        """Add a message history, making it available as history_N in code.

        Versioning:
            - history_index=None: auto-increment (0, 1, 2, ...)
            - history_index=N: use specific index N

        Storage:
            Must store so executed code can access:
            - history_0, history_1, etc. (versioned)
            - history (alias to history_0)

        IMPORTANT: Store a deep copy, not a reference. The caller may
        modify the list after calling this method.

        Args:
            message_history: List of message dicts (role, content).
            history_index: Optional specific index, or None to auto-increment.

        Returns:
            The index used.
        """
        ...

    def get_history_count(self) -> int:
        """Return the number of histories added so far.

        Used by RLM to inform the model how many conversation histories
        are available.
        """
        ...
````

## File: rlm/environments/docker_repl.py
````python
"""
Docker REPL environment that runs Python code in a Docker container.

Setup:
    docker build -t rlm-sandbox -f Dockerfile.sandbox .

Or use any Python 3.11+ image with: pip install dill requests
"""

import base64
import json
import os
import subprocess
import tempfile
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from rlm.core.comms_utils import LMRequest, send_lm_request, send_lm_request_batched
from rlm.core.types import REPLResult, RLMChatCompletion
from rlm.environments.base_env import NonIsolatedEnv


class LLMProxyHandler(BaseHTTPRequestHandler):
    """HTTP handler for LLM requests from the container."""

    lm_handler_address: tuple[str, int] | None = None
    pending_calls: list[RLMChatCompletion] = []
    lock: threading.Lock = threading.Lock()
    depth: int = 1

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        if self.path == "/llm_query":
            result = self._handle_single(body)
        elif self.path == "/llm_query_batched":
            result = self._handle_batched(body)
        else:
            self._respond(404, {"error": "Not found"})
            return

        self._respond(200, result)

    def _respond(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _handle_single(self, body: dict) -> dict:
        if not self.lm_handler_address:
            return {"error": "No LM handler configured"}

        request = LMRequest(prompt=body.get("prompt"), model=body.get("model"), depth=self.depth)
        response = send_lm_request(self.lm_handler_address, request)

        if not response.success:
            return {"error": response.error}

        with self.lock:
            self.pending_calls.append(response.chat_completion)

        return {"response": response.chat_completion.response}

    def _handle_batched(self, body: dict) -> dict:
        if not self.lm_handler_address:
            return {"error": "No LM handler configured"}

        prompts = body.get("prompts", [])
        responses = send_lm_request_batched(
            self.lm_handler_address, prompts, model=body.get("model"), depth=self.depth
        )

        results = []
        for resp in responses:
            if not resp.success:
                results.append(f"Error: {resp.error}")
            else:
                with self.lock:
                    self.pending_calls.append(resp.chat_completion)
                results.append(resp.chat_completion.response)

        return {"responses": results}


def _build_exec_script(code: str, proxy_port: int, depth: int = 1) -> str:
    """Build execution script for the container."""
    code_b64 = base64.b64encode(code.encode()).decode()

    return textwrap.dedent(
        f'''
import sys, io, json, base64, traceback, os, requests
try:
    import dill
except ImportError:
    import pickle as dill

PROXY = "http://host.docker.internal:{proxy_port}"
STATE = "/workspace/state.dill"

def llm_query(prompt, model=None):
    try:
        r = requests.post(f"{{PROXY}}/llm_query", json={{"prompt": prompt, "model": model, "depth": {depth}}}, timeout=300)
        d = r.json()
        return d.get("response") or f"Error: {{d.get('error')}}"
    except Exception as e:
        return f"Error: {{e}}"

def llm_query_batched(prompts, model=None):
    try:
        r = requests.post(f"{{PROXY}}/llm_query_batched", json={{"prompts": prompts, "model": model, "depth": {depth}}}, timeout=300)
        d = r.json()
        return d.get("responses") or [f"Error: {{d.get('error')}}"] * len(prompts)
    except Exception as e:
        return [f"Error: {{e}}"] * len(prompts)

def load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE, "rb") as f:
                return dill.load(f)
        except:
            pass
    return {{}}

def save_state(s):
    clean = {{k: v for k, v in s.items() if not k.startswith("_")}}
    for k in list(clean.keys()):
        try:
            dill.dumps(clean[k])
        except:
            del clean[k]
    with open(STATE, "wb") as f:
        dill.dump(clean, f)

_locals = load_state()

def FINAL_VAR(name):
    name = name.strip().strip("\\"\\'")
    if name in _locals:
        return str(_locals[name])
    available = [k for k in _locals.keys() if not k.startswith("_")]
    if available:
        return f"Error: Variable '{{name}}' not found. Available variables: {{available}}. You must create and assign a variable BEFORE calling FINAL_VAR on it."
    return f"Error: Variable '{{name}}' not found. No variables have been created yet. You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."

def SHOW_VARS():
    available = {{k: type(v).__name__ for k, v in _locals.items() if not k.startswith("_")}}
    if not available:
        return "No variables created yet. Use ```repl``` blocks to create variables."
    return f"Available variables: {{available}}"

_globals = {{"__builtins__": __builtins__, "__name__": "__main__", "llm_query": llm_query, "llm_query_batched": llm_query_batched, "FINAL_VAR": FINAL_VAR, "SHOW_VARS": SHOW_VARS}}

code = base64.b64decode("{code_b64}").decode()
stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
old_stdout, old_stderr = sys.stdout, sys.stderr

try:
    sys.stdout, sys.stderr = stdout_buf, stderr_buf
    combined = {{**_globals, **_locals}}
    exec(code, combined, combined)
    for k, v in combined.items():
        if k not in _globals and not k.startswith("_"):
            _locals[k] = v
except:
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout, sys.stderr = old_stdout, old_stderr

save_state(_locals)
print(json.dumps({{"stdout": stdout_buf.getvalue(), "stderr": stderr_buf.getvalue(), "locals": {{k: repr(v) for k, v in _locals.items() if not k.startswith("_")}}}}, ensure_ascii=False))
'''
    )


class DockerREPL(NonIsolatedEnv):
    """
    Docker REPL - runs Python in a Docker container with LLM support.

    Requires: Docker with a Python 3.11+ image (default: python:3.11-slim).
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        lm_handler_address: tuple[str, int] | None = None,
        context_payload: dict | list | str | None = None,
        setup_code: str | None = None,
        persistent: bool = False,
        depth: int = 1,
        **kwargs,
    ):
        if persistent:
            raise NotImplementedError(
                "Persistent REPLs are currently not supported for environment: DockerREPL"
            )
        super().__init__(persistent=persistent, depth=depth, **kwargs)

        self.image = image
        self.lm_handler_address = lm_handler_address
        self.container_id: str | None = None
        self.proxy_server: HTTPServer | None = None
        self.proxy_thread: threading.Thread | None = None
        self.proxy_port: int = 0
        base_dir = os.environ.get(
            "RLM_DOCKER_WORKSPACE_DIR", os.path.join(os.getcwd(), ".rlm_workspace")
        )
        os.makedirs(base_dir, exist_ok=True)
        self.temp_dir = tempfile.mkdtemp(prefix="docker_repl_", dir=base_dir)
        self.pending_calls: list[RLMChatCompletion] = []
        self._calls_lock = threading.Lock()

        self.setup()

        if context_payload:
            self.load_context(context_payload)
        if setup_code:
            self.execute_code(setup_code)

    def setup(self):
        """Start the proxy server and Docker container."""
        # Start LLM proxy server
        handler = type(
            "Handler",
            (LLMProxyHandler,),
            {
                "lm_handler_address": self.lm_handler_address,
                "pending_calls": self.pending_calls,
                "lock": self._calls_lock,
                "depth": self.depth,
            },
        )
        self.proxy_server = HTTPServer(("127.0.0.1", 0), handler)
        self.proxy_port = self.proxy_server.server_address[1]
        self.proxy_thread = threading.Thread(target=self.proxy_server.serve_forever, daemon=True)
        self.proxy_thread.start()

        # Start Docker container
        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "-v",
                f"{self.temp_dir}:/workspace",
                "--add-host",
                "host.docker.internal:host-gateway",
                self.image,
                "tail",
                "-f",
                "/dev/null",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")

        self.container_id = result.stdout.strip()

        # Install dependencies
        subprocess.run(
            ["docker", "exec", self.container_id, "pip", "install", "-q", "dill", "requests"],
            capture_output=True,
        )

    def load_context(self, context_payload: dict | list | str):
        """Load context by writing to a file in the mounted workspace."""
        if isinstance(context_payload, str):
            context_path = os.path.join(self.temp_dir, "context.txt")
            with open(context_path, "w") as f:
                f.write(context_payload)
            self.execute_code(
                "with open('/workspace/context.txt', 'r') as f:\n    context = f.read()"
            )
        else:
            context_path = os.path.join(self.temp_dir, "context.json")
            with open(context_path, "w") as f:
                json.dump(context_payload, f)
            self.execute_code(
                "import json\nwith open('/workspace/context.json', 'r') as f:\n    context = json.load(f)"
            )

    def execute_code(self, code: str) -> REPLResult:
        start = time.perf_counter()

        with self._calls_lock:
            self.pending_calls.clear()

        script = _build_exec_script(code, self.proxy_port, self.depth)
        result = subprocess.run(
            ["docker", "exec", self.container_id, "python", "-c", script],
            capture_output=True,
            text=True,
        )

        with self._calls_lock:
            calls = self.pending_calls.copy()
            self.pending_calls.clear()

        try:
            lines = result.stdout.strip().split("\n")
            data = json.loads(lines[-1]) if lines else {}
            return REPLResult(
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", "") + result.stderr,
                locals=data.get("locals", {}),
                execution_time=time.perf_counter() - start,
                rlm_calls=calls,
            )
        except json.JSONDecodeError:
            return REPLResult(
                stdout=result.stdout,
                stderr=result.stderr or "Parse error",
                locals={},
                execution_time=time.perf_counter() - start,
                rlm_calls=calls,
            )

    def cleanup(self):
        if hasattr(self, "container_id") and self.container_id:
            subprocess.run(["docker", "stop", self.container_id], capture_output=True)
            self.container_id = None
        if hasattr(self, "proxy_server") and self.proxy_server:
            self.proxy_server.shutdown()
            self.proxy_server = None
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            import shutil

            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
````

## File: rlm/clients/portkey.py
````python
from collections import defaultdict
from typing import Any

from portkey_ai import AsyncPortkey, Portkey
from portkey_ai.api_resources.types.chat_complete_type import ChatCompletions

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary


class PortkeyClient(BaseLM):
    """
    LM Client for running models with the Portkey API.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str | None = None,
        base_url: str | None = "https://api.portkey.ai/v1",
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)
        self.client = Portkey(api_key=api_key, base_url=base_url)
        self.async_client = AsyncPortkey(api_key=api_key, base_url=base_url)
        self.model_name = model_name

        # Per-model usage tracking
        self.model_call_counts: dict[str, int] = defaultdict(int)
        self.model_input_tokens: dict[str, int] = defaultdict(int)
        self.model_output_tokens: dict[str, int] = defaultdict(int)
        self.model_total_tokens: dict[str, int] = defaultdict(int)

    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Portkey client.")

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
        )
        self._track_cost(response, model)
        return response.choices[0].message.content

    async def acompletion(self, prompt: str | dict[str, Any], model: str | None = None) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for Portkey client.")

        response = await self.async_client.chat.completions.create(model=model, messages=messages)
        self._track_cost(response, model)
        return response.choices[0].message.content

    def _track_cost(self, response: ChatCompletions, model: str):
        self.model_call_counts[model] += 1
        self.model_input_tokens[model] += response.usage.prompt_tokens
        self.model_output_tokens[model] += response.usage.completion_tokens
        self.model_total_tokens[model] += response.usage.total_tokens

        # Track last call for handler to read
        self.last_prompt_tokens = response.usage.prompt_tokens
        self.last_completion_tokens = response.usage.completion_tokens

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model in self.model_call_counts:
            model_summaries[model] = ModelUsageSummary(
                total_calls=self.model_call_counts[model],
                total_input_tokens=self.model_input_tokens[model],
                total_output_tokens=self.model_output_tokens[model],
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self.last_prompt_tokens,
            total_output_tokens=self.last_completion_tokens,
        )
````

## File: rlm/core/comms_utils.py
````python
"""
Communication utilities for RLM socket protocol.

Protocol: 4-byte big-endian length prefix + JSON payload.
Used for communication between LMHandler and environment subprocesses.
"""

import json
import socket
import struct
from dataclasses import dataclass
from typing import Any

from rlm.core.types import RLMChatCompletion

# =============================================================================
# Message Dataclasses
# =============================================================================


@dataclass
class LMRequest:
    """Request message sent to the LM Handler.

    Supports both single prompt (prompt field) and batched prompts (prompts field).
    """

    prompt: str | dict[str, Any] | None = None
    prompts: list[str | dict[str, Any]] | None = None
    model: str | None = None
    depth: int = 0

    @property
    def is_batched(self) -> bool:
        """Check if this is a batched request."""
        return self.prompts is not None and len(self.prompts) > 0

    def to_dict(self) -> dict:
        """Convert to dict, excluding None values."""
        d = {}
        if self.prompt is not None:
            d["prompt"] = self.prompt
        if self.prompts is not None:
            d["prompts"] = self.prompts
        if self.model is not None:
            d["model"] = self.model
        d["depth"] = self.depth
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "LMRequest":
        """Create from dict."""
        return cls(
            prompt=data.get("prompt"),
            prompts=data.get("prompts"),
            model=data.get("model"),
            depth=data.get("depth", -1),  # TODO: Default should throw an error
        )


@dataclass
class LMResponse:
    """Response message from the LM Handler.

    Supports both single response (chat_completion) and batched responses (chat_completions).
    """

    error: str | None = None
    chat_completion: RLMChatCompletion | None = None
    chat_completions: list[RLMChatCompletion] | None = None

    @property
    def success(self) -> bool:
        """Check if response was successful."""
        return self.error is None

    @property
    def is_batched(self) -> bool:
        """Check if this is a batched response."""
        return self.chat_completions is not None

    def to_dict(self) -> dict:
        """Convert to dict, excluding None values."""
        if self.error is not None:
            return {
                "error": self.error,
                "chat_completion": None,
                "chat_completions": None,
            }
        if self.chat_completions is not None:
            return {
                "chat_completions": [c.to_dict() for c in self.chat_completions],
                "chat_completion": None,
                "error": None,
            }
        if self.chat_completion is not None:
            return {
                "chat_completion": self.chat_completion.to_dict(),
                "chat_completions": None,
                "error": None,
            }
        return {
            "error": "No chat completion or error provided.",
            "chat_completion": None,
            "chat_completions": None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LMResponse":
        """Create from dict."""
        chat_completions = None
        if data.get("chat_completions"):
            chat_completions = [RLMChatCompletion.from_dict(c) for c in data["chat_completions"]]

        chat_completion = None
        if data.get("chat_completion"):
            chat_completion = RLMChatCompletion.from_dict(data["chat_completion"])

        return cls(
            error=data.get("error"),
            chat_completion=chat_completion,
            chat_completions=chat_completions,
        )

    @classmethod
    def success_response(cls, chat_completion: RLMChatCompletion) -> "LMResponse":
        """Create a successful single response."""
        return cls(chat_completion=chat_completion)

    @classmethod
    def batched_success_response(cls, chat_completions: list[RLMChatCompletion]) -> "LMResponse":
        """Create a successful batched response."""
        return cls(chat_completions=chat_completions)

    @classmethod
    def error_response(cls, error: str) -> "LMResponse":
        """Create an error response."""
        return cls(error=error)


# =============================================================================
# Socket Protocol Helpers
# =============================================================================


def socket_send(sock: socket.socket, data: dict) -> None:
    """Send a length-prefixed JSON message over socket.

    Protocol: 4-byte big-endian length prefix + UTF-8 JSON payload.
    """
    payload = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def socket_recv(sock: socket.socket) -> dict:
    """Receive a length-prefixed JSON message from socket.

    Protocol: 4-byte big-endian length prefix + UTF-8 JSON payload.
    Returns empty dict if connection closed before length received.

    Raises:
        ConnectionError: If connection closes mid-message.
    """
    raw_len = sock.recv(4)
    if not raw_len:
        return {}

    length = struct.unpack(">I", raw_len)[0]
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            raise ConnectionError("Connection closed before message complete")
        payload += chunk

    return json.loads(payload.decode("utf-8"))


def socket_request(address: tuple[str, int], data: dict, timeout: int = 300) -> dict:
    """Send a request and receive a response over a new socket connection.

    Opens a new TCP connection, sends the request, waits for response, then closes.

    Args:
        address: (host, port) tuple to connect to.
        data: Dictionary to send as JSON.
        timeout: Socket timeout in seconds (default 300).

    Returns:
        Response dictionary.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(address)
        socket_send(sock, data)
        return socket_recv(sock)


# =============================================================================
# Typed Request Helpers
# =============================================================================


def send_lm_request(
    address: tuple[str, int], request: LMRequest, timeout: int = 300, depth: int | None = None
) -> LMResponse:
    """Send an LM request and return typed response.

    Args:
        address: (host, port) tuple of LM Handler server.
        request: LMRequest to send.
        timeout: Socket timeout in seconds.
        depth: Optional depth to override request depth.

    Returns:
        LMResponse with content or error.
    """
    try:
        if depth is not None:
            request.depth = depth
        response_data = socket_request(address, request.to_dict(), timeout)
        return LMResponse.from_dict(response_data)
    except Exception as e:
        return LMResponse.error_response(f"Request failed: {e}")


def send_lm_request_batched(
    address: tuple[str, int],
    prompts: list[str | dict[str, Any]],
    model: str | None = None,
    timeout: int = 300,
    depth: int = 0,
) -> list[LMResponse]:
    """Send a batched LM request and return a list of typed responses.

    Args:
        address: (host, port) tuple of LM Handler server.
        prompts: List of prompts to send.
        model: Optional model name to use.
        timeout: Socket timeout in seconds.
        depth: Depth for routing (default 0).

    Returns:
        List of LMResponse objects, one per prompt, in the same order.
    """
    try:
        request = LMRequest(prompts=prompts, model=model, depth=depth)
        response_data = socket_request(address, request.to_dict(), timeout)
        response = LMResponse.from_dict(response_data)

        if not response.success:
            # Return error responses for all prompts
            return [LMResponse.error_response(response.error)] * len(prompts)

        if response.chat_completions is None:
            return [LMResponse.error_response("No completions returned")] * len(prompts)

        # Convert batched response to list of individual responses
        return [
            LMResponse.success_response(chat_completion)
            for chat_completion in response.chat_completions
        ]
    except Exception as e:
        return [LMResponse.error_response(f"Request failed: {e}")] * len(prompts)
````

## File: rlm/environments/modal_repl.py
````python
import base64
import json
import textwrap
import threading
import time

import modal
import requests

from rlm.core.comms_utils import LMRequest, send_lm_request, send_lm_request_batched
from rlm.core.types import REPLResult, RLMChatCompletion
from rlm.environments.base_env import IsolatedEnv
from rlm.environments.constants import APT_PACKAGES, PIP_PACKAGES

# =============================================================================
# Default Modal Image
# =============================================================================


def get_default_image() -> modal.Image:
    """
    Build a default Modal image with common libraries for data science,
    math, and general Python work.
    """
    return (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install(*APT_PACKAGES)
        .pip_install(*PIP_PACKAGES)
    )


# =============================================================================
# Broker Server Script (runs inside sandbox, handles LLM request queue)
# =============================================================================

_BROKER_SCRIPT = textwrap.dedent(
    '''
import json
import threading
import uuid
from flask import Flask, request, jsonify

app = Flask(__name__)

# Request queue: {request_id: {"request": {...}, "response": None, "event": Event}}
pending_requests = {}
lock = threading.Lock()

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/enqueue", methods=["POST"])
def enqueue():
    """Called by sandbox code to submit an LLM request and wait for response."""
    data = request.json
    request_id = str(uuid.uuid4())
    event = threading.Event()

    with lock:
        pending_requests[request_id] = {
            "request": data,
            "response": None,
            "event": event,
        }

    # Wait for response (with timeout)
    event.wait(timeout=300)

    with lock:
        entry = pending_requests.pop(request_id, None)

    if entry and entry["response"] is not None:
        return jsonify(entry["response"])
    else:
        return jsonify({"error": "Request timed out"}), 504

@app.route("/pending")
def get_pending():
    """Called by ModalREPL to get pending requests."""
    with lock:
        pending = [
            {"id": rid, "request": entry["request"]}
            for rid, entry in pending_requests.items()
            if entry["response"] is None
        ]
    return jsonify({"pending": pending})

@app.route("/respond", methods=["POST"])
def respond():
    """Called by ModalREPL to submit a response."""
    data = request.json
    request_id = data.get("id")
    response = data.get("response")

    with lock:
        if request_id in pending_requests:
            pending_requests[request_id]["response"] = response
            pending_requests[request_id]["event"].set()
            return jsonify({"status": "ok"})

    return jsonify({"error": "Request not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
'''
)


# =============================================================================
# Execution Script (runs inside the sandbox for each code block)
# =============================================================================


def _build_exec_script(code: str, broker_port: int = 8080, depth: int = 1) -> str:
    """
    Build a script that executes code with state persistence.
    LLM queries go through the local broker server.
    """
    code_b64 = base64.b64encode(code.encode()).decode()

    return textwrap.dedent(
        f'''
import sys
import io
import json
import base64
import traceback
import os
import requests

try:
    import dill
except ImportError:
    import pickle as dill

# =============================================================================
# LLM Query Functions (via local broker)
# =============================================================================

BROKER_URL = "http://127.0.0.1:{broker_port}"

def llm_query(prompt, model=None):
    """Query the LM via the broker."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "single", "prompt": prompt, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return f"Error: {{data['error']}}"
        return data.get("response", "Error: No response")
    except Exception as e:
        return f"Error: LM query failed - {{e}}"


def llm_query_batched(prompts, model=None):
    """Query the LM with multiple prompts."""
    try:
        response = requests.post(
            f"{{BROKER_URL}}/enqueue",
            json={{"type": "batched", "prompts": prompts, "model": model, "depth": {depth}}},
            timeout=300,
        )
        data = response.json()
        if data.get("error"):
            return [f"Error: {{data['error']}}"] * len(prompts)
        return data.get("responses", ["Error: No response"] * len(prompts))
    except Exception as e:
        return [f"Error: LM query failed - {{e}}"] * len(prompts)


# =============================================================================
# State Management
# =============================================================================

STATE_FILE = "/tmp/rlm_state.dill"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return dill.load(f)
        except:
            pass
    return {{}}

def save_state(state):
    clean_state = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            dill.dumps(v)
            clean_state[k] = v
        except:
            pass
    with open(STATE_FILE, "wb") as f:
        dill.dump(clean_state, f)

def serialize_locals(state):
    result = {{}}
    for k, v in state.items():
        if k.startswith("_"):
            continue
        try:
            result[k] = repr(v)
        except:
            result[k] = f"<{{type(v).__name__}}>"
    return result

# =============================================================================
# Execution
# =============================================================================

_locals = load_state()

def FINAL_VAR(variable_name):
    variable_name = variable_name.strip().strip("\\"\\'")
    if variable_name in _locals:
        return str(_locals[variable_name])
    available = [k for k in _locals.keys() if not k.startswith("_")]
    if available:
        return f"Error: Variable '{{variable_name}}' not found. Available variables: {{available}}. You must create and assign a variable BEFORE calling FINAL_VAR on it."
    return f"Error: Variable '{{variable_name}}' not found. No variables have been created yet. You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."

def SHOW_VARS():
    available = {{k: type(v).__name__ for k, v in _locals.items() if not k.startswith("_")}}
    if not available:
        return "No variables created yet. Use ```repl``` blocks to create variables."
    return f"Available variables: {{available}}"

_globals = {{
    "__builtins__": __builtins__,
    "__name__": "__main__",
    "llm_query": llm_query,
    "llm_query_batched": llm_query_batched,
    "FINAL_VAR": FINAL_VAR,
    "SHOW_VARS": SHOW_VARS,
}}

code = base64.b64decode("{code_b64}").decode()

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
old_stdout, old_stderr = sys.stdout, sys.stderr

try:
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    combined = {{**_globals, **_locals}}
    exec(code, combined, combined)
    for key, value in combined.items():
        if key not in _globals and not key.startswith("_"):
            _locals[key] = value
except Exception as e:
    traceback.print_exc(file=stderr_buf)
finally:
    sys.stdout = old_stdout
    sys.stderr = old_stderr

save_state(_locals)

result = {{
    "stdout": stdout_buf.getvalue(),
    "stderr": stderr_buf.getvalue(),
    "locals": serialize_locals(_locals),
}}
print(json.dumps(result))
'''
    )


class ModalREPL(IsolatedEnv):
    """
    Modal REPL environment that runs Python code in a Modal Sandbox.

    Uses Modal tunnels for LLM communication:
    - Sandbox runs a broker server exposed via encrypted_ports
    - ModalREPL polls the broker for pending LLM requests
    - ModalREPL forwards requests to the LM handler and posts responses back
    """

    BROKER_PORT = 8080

    def __init__(
        self,
        app_name: str = "rlm-sandbox",
        image: modal.Image | None = None,
        timeout: int = 600,
        lm_handler_address: tuple[str, int] | None = None,
        context_payload: dict | list | str | None = None,
        setup_code: str | None = None,
        persistent: bool = False,
        depth: int = 1,
        **kwargs,
    ):
        if persistent:
            raise NotImplementedError(
                "Persistent REPLs are currently not supported for environment: ModalREPL"
            )
        super().__init__(persistent=persistent, depth=depth, **kwargs)

        self.app_name = app_name
        self.timeout = timeout
        self.lm_handler_address = lm_handler_address

        self.image = image or get_default_image()

        self.app = None
        self.sandbox = None
        self.broker_process = None
        self.broker_url: str | None = None
        self.poller_thread: threading.Thread | None = None
        self.poller_stop = threading.Event()
        self.pending_llm_calls: list[RLMChatCompletion] = []
        self._calls_lock = threading.Lock()

        self.setup()

        if context_payload is not None:
            self.load_context(context_payload)

        if setup_code:
            self.execute_code(setup_code)

    def setup(self):
        """Create the Modal app, sandbox, broker, and start polling."""
        self.app = modal.App.lookup(self.app_name, create_if_missing=True)

        # Create sandbox with encrypted port for broker
        self.sandbox = modal.Sandbox.create(
            app=self.app,
            image=self.image,
            timeout=self.timeout,
            encrypted_ports=[self.BROKER_PORT],
        )

        # Start the broker server in the sandbox
        self.broker_process = self.sandbox.exec(
            "python",
            "-c",
            _BROKER_SCRIPT,
        )

        # Wait for broker to be ready
        time.sleep(2)

        # Get the tunnel URL
        tunnels = self.sandbox.tunnels()
        if self.BROKER_PORT in tunnels:
            self.broker_url = tunnels[self.BROKER_PORT].url

        # Start polling thread if we have an LM handler
        if self.lm_handler_address and self.broker_url:
            self.poller_stop.clear()
            self.poller_thread = threading.Thread(target=self._poll_broker, daemon=True)
            self.poller_thread.start()

    def _poll_broker(self):
        """Poll the broker for pending LLM requests and handle them."""
        while not self.poller_stop.is_set():
            try:
                # Get pending requests
                resp = requests.get(
                    f"{self.broker_url}/pending",
                    timeout=5,
                )
                pending = resp.json().get("pending", [])

                for item in pending:
                    request_id = item["id"]
                    req_data = item["request"]

                    # Handle the request
                    response = self._handle_llm_request(req_data)

                    # Send response back
                    requests.post(
                        f"{self.broker_url}/respond",
                        json={"id": request_id, "response": response},
                        timeout=10,
                    )

            except requests.exceptions.RequestException:
                pass
            except Exception:
                pass

            time.sleep(0.1)

    def _handle_llm_request(self, req_data: dict) -> dict:
        """Handle an LLM request from the sandbox."""
        req_type = req_data.get("type")
        model = req_data.get("model")

        if req_type == "single":
            prompt = req_data.get("prompt")
            request = LMRequest(prompt=prompt, model=model, depth=self.depth)
            response = send_lm_request(self.lm_handler_address, request)

            if not response.success:
                return {"error": response.error}

            # Track the call
            with self._calls_lock:
                self.pending_llm_calls.append(response.chat_completion)

            return {"response": response.chat_completion.response}

        elif req_type == "batched":
            prompts = req_data.get("prompts", [])
            responses = send_lm_request_batched(
                self.lm_handler_address, prompts, model=model, depth=self.depth
            )

            results = []
            for resp in responses:
                if not resp.success:
                    results.append(f"Error: {resp.error}")
                else:
                    with self._calls_lock:
                        self.pending_llm_calls.append(resp.chat_completion)
                    results.append(resp.chat_completion.response)

            return {"responses": results}

        return {"error": "Unknown request type"}

    def load_context(self, context_payload: dict | list | str):
        """Load context into the sandbox environment."""
        if isinstance(context_payload, str):
            escaped = context_payload.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            context_code = f'context = """{escaped}"""'
        else:
            context_json = json.dumps(context_payload)
            escaped_json = context_json.replace("\\", "\\\\").replace("'", "\\'")
            context_code = f"import json; context = json.loads('{escaped_json}')"

        self.execute_code(context_code)

    def execute_code(self, code: str) -> REPLResult:
        """Execute code in the Modal sandbox and return result."""
        start_time = time.perf_counter()

        # Clear pending LLM calls
        with self._calls_lock:
            self.pending_llm_calls.clear()

        # Build and execute the script
        script = _build_exec_script(code, self.BROKER_PORT, self.depth)
        process = self.sandbox.exec("python", "-c", script)

        # Read output
        stdout = process.stdout.read()
        stderr = process.stderr.read()

        # Collect LLM calls made during this execution
        with self._calls_lock:
            pending_calls = self.pending_llm_calls.copy()
            self.pending_llm_calls.clear()

        execution_time = time.perf_counter() - start_time

        # Parse the JSON result
        try:
            lines = stdout.strip().split("\n")
            result_json = lines[-1] if lines else "{}"
            result = json.loads(result_json)

            return REPLResult(
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", "") + stderr,
                locals=result.get("locals", {}),
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )
        except json.JSONDecodeError:
            return REPLResult(
                stdout=stdout,
                stderr=stderr or "Failed to parse execution result",
                locals={},
                execution_time=execution_time,
                rlm_calls=pending_calls,
            )

    def cleanup(self):
        """Terminate the sandbox and stop polling."""
        # Stop the poller thread
        if self.poller_thread is not None:
            self.poller_stop.set()
            self.poller_thread.join(timeout=2)
            self.poller_thread = None

        if self.sandbox is not None:
            try:
                self.sandbox.terminate()
            except Exception:
                pass
            self.sandbox = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
````

## File: rlm/clients/__init__.py
````python
from typing import Any

from dotenv import load_dotenv

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ClientBackend

load_dotenv()


def get_client(
    backend: ClientBackend,
    backend_kwargs: dict[str, Any],
) -> BaseLM:
    """
    Routes a specific backend and the args (as a dict) to the appropriate client if supported.
    Currently supported backends: ['openai']
    """
    if backend == "openai":
        from rlm.clients.openai import OpenAIClient

        return OpenAIClient(**backend_kwargs)
    elif backend == "vllm":
        from rlm.clients.openai import OpenAIClient

        assert "base_url" in backend_kwargs, (
            "base_url is required to be set to local vLLM server address for vLLM"
        )
        return OpenAIClient(**backend_kwargs)
    elif backend == "portkey":
        from rlm.clients.portkey import PortkeyClient

        return PortkeyClient(**backend_kwargs)
    elif backend == "openrouter":
        from rlm.clients.openai import OpenAIClient

        backend_kwargs.setdefault("base_url", "https://openrouter.ai/api/v1")
        return OpenAIClient(**backend_kwargs)
    elif backend == "vercel":
        from rlm.clients.openai import OpenAIClient

        backend_kwargs.setdefault("base_url", "https://ai-gateway.vercel.sh/v1")
        return OpenAIClient(**backend_kwargs)
    elif backend == "litellm":
        from rlm.clients.litellm import LiteLLMClient

        return LiteLLMClient(**backend_kwargs)
    elif backend == "anthropic":
        from rlm.clients.anthropic import AnthropicClient

        return AnthropicClient(**backend_kwargs)
    elif backend == "gemini":
        from rlm.clients.gemini import GeminiClient

        return GeminiClient(**backend_kwargs)
    elif backend == "azure_openai":
        from rlm.clients.azure_openai import AzureOpenAIClient

        return AzureOpenAIClient(**backend_kwargs)
    else:
        raise ValueError(
            f"Unknown backend: {backend}. Supported backends: ['openai', 'vllm', 'portkey', 'openrouter', 'litellm', 'anthropic', 'azure_openai', 'gemini', 'vercel']"
        )
````

## File: rlm/environments/__init__.py
````python
from typing import Any, Literal

from rlm.environments.base_env import BaseEnv, SupportsPersistence
from rlm.environments.local_repl import LocalREPL

__all__ = ["BaseEnv", "LocalREPL", "SupportsPersistence", "get_environment"]


def get_environment(
    environment: Literal["local", "modal", "docker", "daytona", "prime", "e2b"],
    environment_kwargs: dict[str, Any],
) -> BaseEnv:
    """
    Routes a specific environment and the args (as a dict) to the appropriate environment if supported.
    Currently supported environments: ['local', 'modal', 'docker', 'daytona', 'prime', 'e2b']
    """
    if environment == "local":
        return LocalREPL(**environment_kwargs)
    elif environment == "modal":
        from rlm.environments.modal_repl import ModalREPL

        return ModalREPL(**environment_kwargs)
    elif environment == "docker":
        from rlm.environments.docker_repl import DockerREPL

        return DockerREPL(**environment_kwargs)
    elif environment == "daytona":
        from rlm.environments.daytona_repl import DaytonaREPL

        return DaytonaREPL(**environment_kwargs)
    elif environment == "prime":
        from rlm.environments.prime_repl import PrimeREPL

        return PrimeREPL(**environment_kwargs)
    elif environment == "e2b":
        from rlm.environments.e2b_repl import E2BREPL

        return E2BREPL(**environment_kwargs)
    else:
        raise ValueError(
            f"Unknown environment: {environment}. Supported: ['local', 'modal', 'docker', 'daytona', 'prime', 'e2b']"
        )
````

## File: rlm/utils/prompts.py
````python
import textwrap

from rlm.core.types import QueryMetadata

# System prompt for the REPL environment with explicit final answer checking
RLM_SYSTEM_PROMPT = textwrap.dedent(
    """You are tasked with answering a query with associated context. You can access, transform, and analyze this context interactively in a REPL environment that can recursively query sub-LLMs, which you are strongly encouraged to use as much as possible. You will be queried iteratively until you provide a final answer.

The REPL environment is initialized with:
1. A `context` variable that contains extremely important information about your query. You should check the content of the `context` variable to understand what you are working with. Make sure you look through it sufficiently as you answer your query.
2. A `llm_query` function that allows you to query an LLM (that can handle around 500K chars) inside your REPL environment.
3. A `llm_query_batched` function that allows you to query multiple prompts concurrently: `llm_query_batched(prompts: List[str]) -> List[str]`. This is much faster than sequential `llm_query` calls when you have multiple independent queries. Results are returned in the same order as the input prompts.
4. A `SHOW_VARS()` function that returns all variables you have created in the REPL. Use this to check what variables exist before using FINAL_VAR.
5. The ability to use `print()` statements to view the output of your REPL code and continue your reasoning.

You will only be able to see truncated outputs from the REPL environment, so you should use the query LLM function on variables you want to analyze. You will find this function especially useful when you have to analyze the semantics of the context. Use these variables as buffers to build up your final answer.
Make sure to explicitly look through the entire context in REPL before answering your query. An example strategy is to first look at the context and figure out a chunking strategy, then break up the context into smart chunks, and query an LLM per chunk with a particular question and save the answers to a buffer, then query an LLM with all the buffers to produce your final answer.

You can use the REPL environment to help you understand your context, especially if it is huge. Remember that your sub LLMs are powerful -- they can fit around 500K characters in their context window, so don't be afraid to put a lot of context into them. For example, a viable strategy is to feed 10 documents per sub-LLM query. Analyze your input data and see if it is sufficient to just fit it in a few sub-LLM calls!

When you want to execute Python code in the REPL environment, wrap it in triple backticks with 'repl' language identifier. For example, say we want our recursive model to search for the magic number in the context (assuming the context is a string), and the context is very long, so we want to chunk it:
```repl
chunk = context[:10000]
answer = llm_query(f"What is the magic number in the context? Here is the chunk: {{chunk}}")
print(answer)
```

As an example, suppose you're trying to answer a question about a book. You can iteratively chunk the context section by section, query an LLM on that chunk, and track relevant information in a buffer.
```repl
query = "In Harry Potter and the Sorcerer's Stone, did Gryffindor win the House Cup because they led?"
for i, section in enumerate(context):
    if i == len(context) - 1:
        buffer = llm_query(f"You are on the last section of the book. So far you know that: {{buffers}}. Gather from this last section to answer {{query}}. Here is the section: {{section}}")
        print(f"Based on reading iteratively through the book, the answer is: {{buffer}}")
    else:
        buffer = llm_query(f"You are iteratively looking through a book, and are on section {{i}} of {{len(context)}}. Gather information to help answer {{query}}. Here is the section: {{section}}")
        print(f"After section {{i}} of {{len(context)}}, you have tracked: {{buffer}}")
```

As another example, when the context isn't that long (e.g. >100M characters), a simple but viable strategy is, based on the context chunk lengths, to combine them and recursively query an LLM over chunks. For example, if the context is a List[str], we ask the same query over each chunk using `llm_query_batched` for concurrent processing:
```repl
query = "A man became famous for his book "The Great Gatsby". How many jobs did he have?"
# Suppose our context is ~1M chars, and we want each sub-LLM query to be ~0.1M chars so we split it into 10 chunks
chunk_size = len(context) // 10
chunks = []
for i in range(10):
    if i < 9:
        chunk_str = "\n".join(context[i*chunk_size:(i+1)*chunk_size])
    else:
        chunk_str = "\n".join(context[i*chunk_size:])
    chunks.append(chunk_str)

# Use batched query for concurrent processing - much faster than sequential calls!
prompts = [f"Try to answer the following query: {{query}}. Here are the documents:\n{{chunk}}. Only answer if you are confident in your answer based on the evidence." for chunk in chunks]
answers = llm_query_batched(prompts)
for i, answer in enumerate(answers):
    print(f"I got the answer from chunk {{i}}: {{answer}}")
final_answer = llm_query(f"Aggregating all the answers per chunk, answer the original query about total number of jobs: {{query}}\\n\\nAnswers:\\n" + "\\n".join(answers))
```

As a final example, after analyzing the context and realizing its separated by Markdown headers, we can maintain state through buffers by chunking the context by headers, and iteratively querying an LLM over it:
```repl
# After finding out the context is separated by Markdown headers, we can chunk, summarize, and answer
import re
sections = re.split(r'### (.+)', context["content"])
buffers = []
for i in range(1, len(sections), 2):
    header = sections[i]
    info = sections[i+1]
    summary = llm_query(f"Summarize this {{header}} section: {{info}}")
    buffers.append(f"{{header}}: {{summary}}")
final_answer = llm_query(f"Based on these summaries, answer the original query: {{query}}\\n\\nSummaries:\\n" + "\\n".join(buffers))
```
In the next step, we can return FINAL_VAR(final_answer).

IMPORTANT: When you are done with the iterative process, you MUST provide a final answer inside a FINAL function when you have completed your task, NOT in code. Do not use these tags unless you have completed your task. You have two options:
1. Use FINAL(your final answer here) to provide the answer directly
2. Use FINAL_VAR(variable_name) to return a variable you have created in the REPL environment as your final output

WARNING - COMMON MISTAKE: FINAL_VAR retrieves an EXISTING variable. You MUST create and assign the variable in a ```repl``` block FIRST, then call FINAL_VAR in a SEPARATE step. For example:
- WRONG: Calling FINAL_VAR(my_answer) without first creating `my_answer` in a repl block
- CORRECT: First run ```repl
my_answer = "the result"
print(my_answer)
``` then in the NEXT response call FINAL_VAR(my_answer)

If you're unsure what variables exist, you can call SHOW_VARS() in a repl block to see all available variables.

Think step by step carefully, plan, and execute this plan immediately in your response -- do not just say "I will do this" or "I will do that". Output to the REPL environment and recursive LLMs as much as possible. Remember to explicitly answer the original query in your final answer.
"""
)


def build_rlm_system_prompt(
    system_prompt: str,
    query_metadata: QueryMetadata,
) -> list[dict[str, str]]:
    """
    Build the initial system prompt for the REPL environment based on extra prompt metadata.

    Args:
        query_metadata: QueryMetadata object containing context metadata

    Returns:
        List of message dictionaries
    """

    context_lengths = query_metadata.context_lengths
    context_total_length = query_metadata.context_total_length
    context_type = query_metadata.context_type

    # If there are more than 100 chunks, truncate to the first 100 chunks.
    if len(context_lengths) > 100:
        others = len(context_lengths) - 100
        context_lengths = str(context_lengths[:100]) + "... [" + str(others) + " others]"

    metadata_prompt = f"Your context is a {context_type} with {context_total_length} total characters, and is broken up into chunks of char lengths: {context_lengths}."

    return [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": metadata_prompt},
    ]


USER_PROMPT = """Think step-by-step on what to do using the REPL environment (which contains the context) to answer the prompt.\n\nContinue using the REPL environment, which has the `context` variable, and querying sub-LLMs by writing to ```repl``` tags, and determine your answer. Your next action:"""
USER_PROMPT_WITH_ROOT = """Think step-by-step on what to do using the REPL environment (which contains the context) to answer the original prompt: \"{root_prompt}\".\n\nContinue using the REPL environment, which has the `context` variable, and querying sub-LLMs by writing to ```repl``` tags, and determine your answer. Your next action:"""


def build_user_prompt(
    root_prompt: str | None = None,
    iteration: int = 0,
    context_count: int = 1,
    history_count: int = 0,
) -> dict[str, str]:
    if iteration == 0:
        safeguard = "You have not interacted with the REPL environment or seen your prompt / context yet. Your next action should be to look through and figure out how to answer the prompt, so don't just provide a final answer yet.\n\n"
        prompt = safeguard + (
            USER_PROMPT_WITH_ROOT.format(root_prompt=root_prompt) if root_prompt else USER_PROMPT
        )
    else:
        prompt = "The history before is your previous interactions with the REPL environment. " + (
            USER_PROMPT_WITH_ROOT.format(root_prompt=root_prompt) if root_prompt else USER_PROMPT
        )

    # Inform model about multiple contexts if present
    if context_count > 1:
        prompt += f"\n\nNote: You have {context_count} contexts available (context_0 through context_{context_count - 1})."

    # Inform model about prior conversation histories if present
    if history_count > 0:
        if history_count == 1:
            prompt += "\n\nNote: You have 1 prior conversation history available in the `history` variable."
        else:
            prompt += f"\n\nNote: You have {history_count} prior conversation histories available (history_0 through history_{history_count - 1})."

    return {"role": "user", "content": prompt}
````

## File: rlm/core/lm_handler.py
````python
"""
LMHandler - Routes LLM requests from the RLM process and environment subprocesses.

Uses a multi-threaded socket server. Protocol: 4-byte length prefix + JSON payload.
"""

import asyncio
import time
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Thread

from rlm.clients.base_lm import BaseLM
from rlm.core.comms_utils import LMRequest, LMResponse, socket_recv, socket_send
from rlm.core.types import RLMChatCompletion, UsageSummary


class LMRequestHandler(StreamRequestHandler):
    """Socket handler for LLM completion requests."""

    def handle(self):
        try:
            request_data = socket_recv(self.connection)
            if not isinstance(request_data, dict):
                response = LMResponse.error_response("Request must be a JSON object")
                self._safe_send(response)
                return

            request = LMRequest.from_dict(request_data)
            handler: LMHandler = self.server.lm_handler  # type: ignore

            if request.is_batched:
                # Batched request: process multiple prompts concurrently
                response = self._handle_batched(request, handler)
            elif request.prompt:
                # Single request: process one prompt
                response = self._handle_single(request, handler)
            else:
                response = LMResponse.error_response("Missing 'prompt' or 'prompts' in request.")

            self._safe_send(response)

        except (BrokenPipeError, ConnectionError, ConnectionResetError, OSError):
            # Client disconnected - this is expected during parallel execution
            # when workers complete and close their sockets. Silently ignore.
            pass

        except Exception as e:
            # Try to send error response, but don't fail if socket is broken
            response = LMResponse.error_response(str(e))
            self._safe_send(response)

    def _safe_send(self, response: LMResponse) -> bool:
        """Send response, returning False if the socket is broken."""
        try:
            socket_send(self.connection, response.to_dict())
            return True
        except (BrokenPipeError, ConnectionError, ConnectionResetError, OSError):
            # Client disconnected - silently ignore
            return False

    def _handle_single(self, request: LMRequest, handler: "LMHandler") -> LMResponse:
        """Handle a single prompt request."""
        client = handler.get_client(request.model, request.depth)

        start_time = time.perf_counter()
        content = client.completion(request.prompt)
        end_time = time.perf_counter()

        model_usage = client.get_last_usage()
        root_model = request.model or client.model_name
        usage_summary = UsageSummary(model_usage_summaries={root_model: model_usage})
        return LMResponse.success_response(
            chat_completion=RLMChatCompletion(
                root_model=root_model,
                prompt=request.prompt,
                response=content,
                usage_summary=usage_summary,
                execution_time=end_time - start_time,
            )
        )

    def _handle_batched(self, request: LMRequest, handler: "LMHandler") -> LMResponse:
        """Handle a batched prompts request using async for concurrency."""
        client = handler.get_client(request.model, request.depth)

        start_time = time.perf_counter()

        async def run_all():
            tasks = [client.acompletion(prompt) for prompt in request.prompts]
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_all())
        end_time = time.perf_counter()

        total_time = end_time - start_time
        model_usage = client.get_last_usage()
        root_model = request.model or client.model_name
        usage_summary = UsageSummary(model_usage_summaries={root_model: model_usage})

        chat_completions = [
            RLMChatCompletion(
                root_model=root_model,
                prompt=prompt,
                response=content,
                usage_summary=usage_summary,
                execution_time=total_time / len(request.prompts),  # approximate per-prompt time
            )
            for prompt, content in zip(request.prompts, results, strict=True)
        ]

        return LMResponse.batched_success_response(chat_completions=chat_completions)


class ThreadingLMServer(ThreadingTCPServer):
    """Multi-threaded TCP server for LM requests."""

    daemon_threads = True
    allow_reuse_address = True


class LMHandler:
    """
    Handles all LM calls from the RLM main process and environment subprocesses.

    Uses a multi-threaded socket server for concurrent requests.
    Protocol: 4-byte big-endian length prefix + JSON payload.
    """

    def __init__(
        self,
        client: BaseLM,
        host: str = "127.0.0.1",
        port: int = 0,  # auto-assign available port
        other_backend_client: BaseLM | None = None,
    ):
        self.default_client = client
        self.other_backend_client = other_backend_client
        self.clients: dict[str, BaseLM] = {}
        self.host = host
        self._server: ThreadingLMServer | None = None
        self._thread: Thread | None = None
        self._port = port

        self.register_client(client.model_name, client)

    def register_client(self, model_name: str, client: BaseLM) -> None:
        """Register a client for a specific model name."""
        self.clients[model_name] = client

    def get_client(self, model: str | None = None, depth: int = 0) -> BaseLM:
        """Get client by model name or depth, or return default.

        Routing logic:
        - depth=0: use default_client (main backend)
        - depth=1: use other_backend_client if it exists, otherwise default_client
        - If model is specified and exists in clients, use that (overrides depth routing)
        """
        if model and model in self.clients:
            return self.clients[model]

        # Route based on depth
        if depth == 1 and self.other_backend_client is not None:
            return self.other_backend_client

        return self.default_client

    @property
    def port(self) -> int:
        """Get the actual port (useful when auto-assigned)."""
        if self._server:
            return self._server.server_address[1]
        return self._port

    @property
    def address(self) -> tuple[str, int]:
        """Get (host, port) tuple for connecting."""
        return (self.host, self.port)

    def start(self) -> tuple[str, int]:
        """Start the socket server in a background thread. Returns (host, port)."""
        if self._server is not None:
            return self.address

        self._server = ThreadingLMServer((self.host, self._port), LMRequestHandler)
        self._server.lm_handler = self  # type: ignore

        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        return self.address

    def stop(self):
        """Stop the socket server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None

    def completion(self, prompt: str, model: str | None = None) -> str:
        """Direct completion call (for main process use)."""
        return self.get_client(model).completion(prompt)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def get_usage_summary(self) -> UsageSummary:
        """Get the usage summary for all clients, merged into a single dict."""
        merged = {}
        # Include default client
        default_summary = self.default_client.get_usage_summary()
        merged.update(default_summary.model_usage_summaries)
        # Include other backend client if it exists
        if self.other_backend_client is not None:
            other_summary = self.other_backend_client.get_usage_summary()
            merged.update(other_summary.model_usage_summaries)
        # Include all registered clients
        for client in self.clients.values():
            client_summary = client.get_usage_summary()
            merged.update(client_summary.model_usage_summaries)
        return UsageSummary(model_usage_summaries=merged)
````

## File: rlm/core/rlm.py
````python
import time
from contextlib import contextmanager
from typing import Any

from rlm.clients import BaseLM, get_client
from rlm.core.lm_handler import LMHandler
from rlm.core.types import (
    ClientBackend,
    CodeBlock,
    EnvironmentType,
    REPLResult,
    RLMChatCompletion,
    RLMIteration,
    RLMMetadata,
)
from rlm.environments import BaseEnv, SupportsPersistence, get_environment
from rlm.logger import RLMLogger, VerbosePrinter
from rlm.utils.parsing import (
    find_code_blocks,
    find_final_answer,
    format_iteration,
)
from rlm.utils.prompts import (
    RLM_SYSTEM_PROMPT,
    QueryMetadata,
    build_rlm_system_prompt,
    build_user_prompt,
)
from rlm.utils.rlm_utils import filter_sensitive_keys


class RLM:
    """
    Recursive Language Model class that the user instantiates and runs on their tasks.

    Each completion() call spawns its own environment and LM handler, which are
    cleaned up when the call completes.
    """

    def __init__(
        self,
        backend: ClientBackend = "openai",
        backend_kwargs: dict[str, Any] | None = None,
        environment: EnvironmentType = "local",
        environment_kwargs: dict[str, Any] | None = None,
        depth: int = 0,
        max_depth: int = 1,
        max_iterations: int = 30,
        custom_system_prompt: str | None = None,
        other_backends: list[ClientBackend] | None = None,
        other_backend_kwargs: list[dict[str, Any]] | None = None,
        logger: RLMLogger | None = None,
        verbose: bool = False,
        persistent: bool = False,
    ):
        """
        Args:
            backend: The backend to use for the RLM.
            backend_kwargs: The kwargs to pass to the backend.
            environment: The environment to use for the RLM.
            environment_kwargs: The kwargs to pass to the environment.
            depth: The current depth of the RLM (0-indexed).
            max_depth: The maximum depth of the RLM. Currently, only depth 1 is supported.
            max_iterations: The maximum number of iterations of the RLM.
            custom_system_prompt: The custom system prompt to use for the RLM.
            other_backends: A list of other client backends that the environments can use to make sub-calls.
            other_backend_kwargs: The kwargs to pass to the other client backends (ordered to match other_backends).
            logger: The logger to use for the RLM.
            verbose: Whether to print verbose output in rich to console.
            persistent: If True, reuse the environment across completion() calls for multi-turn conversations.
        """
        # Store config for spawning per-completion
        self.backend = backend
        self.backend_kwargs = backend_kwargs
        self.environment_type = environment
        self.environment_kwargs = (
            environment_kwargs.copy() if environment_kwargs is not None else {}
        )
        # Validate other_backends: currently only support one additional backend
        if other_backends is not None:
            if len(other_backends) != 1:
                raise ValueError(
                    "We currently only support one additional backend for the recursive sub-calls! "
                    "This model will be the model used for recursive sub-calls, but this will change in the future"
                )

        self.other_backends = other_backends
        self.other_backend_kwargs = other_backend_kwargs

        self.depth = depth
        self.max_depth = max_depth
        self.max_iterations = max_iterations
        self.system_prompt = custom_system_prompt if custom_system_prompt else RLM_SYSTEM_PROMPT
        self.logger = logger
        self.verbose = VerbosePrinter(enabled=verbose)

        # Persistence support
        self.persistent = persistent
        self._persistent_env: SupportsPersistence | None = None

        # Validate persistence support at initialization
        if self.persistent:
            self._validate_persistent_environment_support()

        # Log metadata if logger is provided
        if self.logger or verbose:
            metadata = RLMMetadata(
                root_model=backend_kwargs.get("model_name", "unknown")
                if backend_kwargs
                else "unknown",
                max_depth=max_depth,
                max_iterations=max_iterations,
                backend=backend,
                backend_kwargs=filter_sensitive_keys(backend_kwargs) if backend_kwargs else {},
                environment_type=environment,
                environment_kwargs=filter_sensitive_keys(environment_kwargs)
                if environment_kwargs
                else {},
                other_backends=other_backends,
            )
            if self.logger:
                self.logger.log_metadata(metadata)
            self.verbose.print_metadata(metadata)

    @contextmanager
    def _spawn_completion_context(self, prompt: str | dict[str, Any]):
        """
        Spawn an LM handler and environment for a single completion call.

        When persistent=True, the environment is reused across calls.
        When persistent=False (default), creates fresh environment each call.
        """
        # Create client and wrap in handler
        client: BaseLM = get_client(self.backend, self.backend_kwargs)

        # Create other_backend_client if provided (for depth=1 routing)
        other_backend_client: BaseLM | None = None
        if self.other_backends and self.other_backend_kwargs:
            other_backend_client = get_client(self.other_backends[0], self.other_backend_kwargs[0])

        lm_handler = LMHandler(client, other_backend_client=other_backend_client)

        # Register other clients to be available as sub-call options (by model name)
        if self.other_backends and self.other_backend_kwargs:
            for backend, kwargs in zip(self.other_backends, self.other_backend_kwargs, strict=True):
                other_client: BaseLM = get_client(backend, kwargs)
                lm_handler.register_client(other_client.model_name, other_client)

        lm_handler.start()

        # Environment: reuse if persistent, otherwise create fresh
        if self.persistent and self._persistent_env is not None:
            environment = self._persistent_env
            # Defensive check: ensure environment supports persistence methods
            if not self._env_supports_persistence(environment):
                raise RuntimeError(
                    f"Persistent environment of type '{type(environment).__name__}' does not "
                    f"implement required methods (update_handler_address, add_context, get_context_count). "
                    f"This should have been caught at initialization."
                )
            environment.update_handler_address((lm_handler.host, lm_handler.port))
            environment.add_context(prompt)
        else:
            env_kwargs = self.environment_kwargs.copy()
            env_kwargs["lm_handler_address"] = (lm_handler.host, lm_handler.port)
            env_kwargs["context_payload"] = prompt
            env_kwargs["depth"] = self.depth + 1  # Environment depth is RLM depth + 1
            environment: BaseEnv = get_environment(self.environment_type, env_kwargs)

            if self.persistent:
                self._persistent_env = environment

        try:
            yield lm_handler, environment
        finally:
            lm_handler.stop()
            if not self.persistent and hasattr(environment, "cleanup"):
                environment.cleanup()

    def _setup_prompt(self, prompt: str | dict[str, Any]) -> list[dict[str, Any]]:
        """
        Setup the system prompt for the RLM. Also include metadata about the prompt and build
        up the initial message history.
        """
        metadata = QueryMetadata(prompt)
        message_history = build_rlm_system_prompt(
            system_prompt=self.system_prompt, query_metadata=metadata
        )

        return message_history

    def completion(
        self, prompt: str | dict[str, Any], root_prompt: str | None = None
    ) -> RLMChatCompletion:
        """
        Recursive Language Model completion call. This is the main entry point for querying an RLM, and
        can replace a regular LM completion call.

        Spawns its own environment and LM handler for the duration of this call.

        Args:
            prompt: A single string or dictionary of messages to pass as context to the model.
            root_prompt: We allow the RLM's root LM to see a (small) prompt that the user specifies. A common example of this
            is if the user is asking the RLM to answer a question, we can pass the question as the root prompt.
        Returns:
            A final answer as a string.
        """
        time_start = time.perf_counter()

        # If we're at max depth, the RLM is an LM, so we fallback to the regular LM.
        if self.depth >= self.max_depth:
            return self._fallback_answer(prompt)

        with self._spawn_completion_context(prompt) as (lm_handler, environment):
            message_history = self._setup_prompt(prompt)

            for i in range(self.max_iterations):
                # Current prompt = message history + additional prompt suffix
                context_count = (
                    environment.get_context_count()
                    if isinstance(environment, SupportsPersistence)
                    else 1
                )
                history_count = (
                    environment.get_history_count()
                    if isinstance(environment, SupportsPersistence)
                    else 0
                )
                current_prompt = message_history + [
                    build_user_prompt(root_prompt, i, context_count, history_count)
                ]

                iteration: RLMIteration = self._completion_turn(
                    prompt=current_prompt,
                    lm_handler=lm_handler,
                    environment=environment,
                )

                # Check if RLM is done and has a final answer.
                final_answer = find_final_answer(iteration.response, environment=environment)
                iteration.final_answer = final_answer

                # If logger is used, log the iteration.
                if self.logger:
                    self.logger.log(iteration)

                # Verbose output for this iteration
                self.verbose.print_iteration(iteration, i + 1)

                if final_answer is not None:
                    time_end = time.perf_counter()
                    usage = lm_handler.get_usage_summary()
                    self.verbose.print_final_answer(final_answer)
                    self.verbose.print_summary(i + 1, time_end - time_start, usage.to_dict())

                    # Store message history in persistent environment
                    if self.persistent and isinstance(environment, SupportsPersistence):
                        environment.add_history(message_history)

                    return RLMChatCompletion(
                        root_model=self.backend_kwargs.get("model_name", "unknown")
                        if self.backend_kwargs
                        else "unknown",
                        prompt=prompt,
                        response=final_answer,
                        usage_summary=usage,
                        execution_time=time_end - time_start,
                    )

                # Format the iteration for the next prompt.
                new_messages = format_iteration(iteration)

                # Update message history with the new messages.
                message_history.extend(new_messages)

            # Default behavior: we run out of iterations, provide one final answer
            time_end = time.perf_counter()
            final_answer = self._default_answer(message_history, lm_handler)
            usage = lm_handler.get_usage_summary()
            self.verbose.print_final_answer(final_answer)
            self.verbose.print_summary(self.max_iterations, time_end - time_start, usage.to_dict())

            # Store message history in persistent environment
            if self.persistent and isinstance(environment, SupportsPersistence):
                environment.add_history(message_history)

            return RLMChatCompletion(
                root_model=self.backend_kwargs.get("model_name", "unknown")
                if self.backend_kwargs
                else "unknown",
                prompt=prompt,
                response=final_answer,
                usage_summary=usage,
                execution_time=time_end - time_start,
            )

    def _completion_turn(
        self,
        prompt: str | dict[str, Any],
        lm_handler: LMHandler,
        environment: BaseEnv,
    ) -> RLMIteration:
        """
        Perform a single iteration of the RLM, including prompting the model
        and code execution + tool execution.
        """
        iter_start = time.perf_counter()
        response = lm_handler.completion(prompt)
        code_block_strs = find_code_blocks(response)
        code_blocks = []

        for code_block_str in code_block_strs:
            code_result: REPLResult = environment.execute_code(code_block_str)
            code_blocks.append(CodeBlock(code=code_block_str, result=code_result))

        iteration_time = time.perf_counter() - iter_start
        return RLMIteration(
            prompt=prompt,
            response=response,
            code_blocks=code_blocks,
            iteration_time=iteration_time,
        )

    def _default_answer(self, message_history: list[dict[str, Any]], lm_handler: LMHandler) -> str:
        """
        Default behavior if the RLM runs out of iterations and does not find a final answer.
        It will take the message history, and try to generate a final answer from it.
        """
        current_prompt = message_history + [
            {
                "role": "assistant",
                "content": "Please provide a final answer to the user's question based on the information provided.",
            }
        ]
        response = lm_handler.completion(current_prompt)

        if self.logger:
            self.logger.log(
                RLMIteration(
                    prompt=current_prompt,
                    response=response,
                    final_answer=response,
                    code_blocks=[],
                )
            )

        return response

    def _fallback_answer(self, message: str | dict[str, Any]) -> str:
        """
        Fallback behavior if the RLM is actually at max depth, and should be treated as an LM.
        """
        client: BaseLM = get_client(self.backend, self.backend_kwargs)
        response = client.completion(message)
        return response

    def _validate_persistent_environment_support(self) -> None:
        """
        Validate that the configured environment type supports persistent mode.

        Persistent mode requires environments to implement:
        - update_handler_address(address): Update LM handler address between calls
        - add_context(payload, index): Add new context for multi-turn conversations
        - get_context_count(): Return the number of loaded contexts

        Currently only 'local' (LocalREPL) supports these methods.

        Raises:
            ValueError: If the environment type does not support persistent mode.
        """
        # Known environments that support persistence
        persistent_supported_environments = {"local"}

        if self.environment_type not in persistent_supported_environments:
            raise ValueError(
                f"persistent=True is not supported for environment type '{self.environment_type}'. "
                f"Persistent mode requires environments that implement update_handler_address(), "
                f"add_context(), and get_context_count(). "
                f"Supported environments: {sorted(persistent_supported_environments)}"
            )

    @staticmethod
    def _env_supports_persistence(env: BaseEnv) -> bool:
        """Check if an environment instance supports persistent mode methods."""
        return isinstance(env, SupportsPersistence)

    def close(self) -> None:
        """Clean up persistent environment. Call when done with multi-turn conversations."""
        if self._persistent_env is not None:
            if hasattr(self._persistent_env, "cleanup"):
                self._persistent_env.cleanup()
            self._persistent_env = None

    def __enter__(self) -> "RLM":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False
````

## File: rlm/environments/local_repl.py
````python
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any

from rlm.core.comms_utils import LMRequest, send_lm_request, send_lm_request_batched
from rlm.core.types import REPLResult, RLMChatCompletion
from rlm.environments.base_env import NonIsolatedEnv

# =============================================================================
# Safe Builtins
# =============================================================================

# Safe builtins - blocks dangerous operations like eval/exec/input
_SAFE_BUILTINS = {
    # Core types and functions
    "print": print,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bool": bool,
    "type": type,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "any": any,
    "all": all,
    "pow": pow,
    "divmod": divmod,
    "chr": chr,
    "ord": ord,
    "hex": hex,
    "bin": bin,
    "oct": oct,
    "repr": repr,
    "ascii": ascii,
    "format": format,
    "hash": hash,
    "id": id,
    "iter": iter,
    "next": next,
    "slice": slice,
    "callable": callable,
    "hasattr": hasattr,
    "getattr": getattr,
    "setattr": setattr,
    "delattr": delattr,
    "dir": dir,
    "vars": vars,
    "bytes": bytes,
    "bytearray": bytearray,
    "memoryview": memoryview,
    "complex": complex,
    "object": object,
    "super": super,
    "property": property,
    "staticmethod": staticmethod,
    "classmethod": classmethod,
    "__import__": __import__,
    "open": open,
    # Exceptions
    "Exception": Exception,
    "BaseException": BaseException,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "FileNotFoundError": FileNotFoundError,
    "OSError": OSError,
    "IOError": IOError,
    "RuntimeError": RuntimeError,
    "NameError": NameError,
    "ImportError": ImportError,
    "StopIteration": StopIteration,
    "AssertionError": AssertionError,
    "NotImplementedError": NotImplementedError,
    "ArithmeticError": ArithmeticError,
    "LookupError": LookupError,
    "Warning": Warning,
    # Blocked
    "input": None,
    "eval": None,
    "exec": None,
    "compile": None,
    "globals": None,
    "locals": None,
}


class LocalREPL(NonIsolatedEnv):
    """
    Local REPL environment with persistent Python namespace.
    Executes code in a sandboxed namespace with access to context data.
    """

    def __init__(
        self,
        lm_handler_address: tuple[str, int] | None = None,
        context_payload: dict | list | str | None = None,
        setup_code: str | None = None,
        persistent: bool = False,
        depth: int = 1,
        **kwargs,
    ):
        super().__init__(persistent=persistent, depth=depth, **kwargs)

        self.lm_handler_address = lm_handler_address
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.mkdtemp(prefix=f"repl_env_{uuid.uuid4()}_")
        self._lock = threading.Lock()
        self._context_count: int = 0
        self._history_count: int = 0

        # Setup globals, locals, and modules in environment.
        self.setup()

        # Load context if provided
        if context_payload is not None:
            self.load_context(context_payload)

        # Run setup code if provided
        if setup_code:
            self.execute_code(setup_code)

    def setup(self):
        """Setup the environment."""
        # Create sandboxed globals
        self.globals: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS.copy(),
            "__name__": "__main__",
        }
        self.locals: dict[str, Any] = {}

        # Track LLM calls made during code execution
        self._pending_llm_calls: list[RLMChatCompletion] = []

        # Add helper functions
        self.globals["FINAL_VAR"] = self._final_var
        self.globals["SHOW_VARS"] = self._show_vars
        self.globals["llm_query"] = self._llm_query
        self.globals["llm_query_batched"] = self._llm_query_batched

    def _final_var(self, variable_name: str) -> str:
        """Return the value of a variable as a final answer."""
        variable_name = variable_name.strip().strip("\"'")
        if variable_name in self.locals:
            return str(self.locals[variable_name])

        # Provide helpful error message with available variables
        available = [k for k in self.locals.keys() if not k.startswith("_")]
        if available:
            return (
                f"Error: Variable '{variable_name}' not found. "
                f"Available variables: {available}. "
                f"You must create and assign a variable BEFORE calling FINAL_VAR on it."
            )
        return (
            f"Error: Variable '{variable_name}' not found. "
            f"No variables have been created yet. "
            f"You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."
        )

    def _show_vars(self) -> str:
        """Show all available variables in the REPL environment."""
        available = {k: type(v).__name__ for k, v in self.locals.items() if not k.startswith("_")}
        if not available:
            return "No variables created yet. Use ```repl``` blocks to create variables."
        return f"Available variables: {available}"

    def _llm_query(self, prompt: str, model: str | None = None) -> str:
        """Query the LM via socket connection to the handler.

        Args:
            prompt: The prompt to send to the LM.
            model: Optional model name to use (if handler has multiple clients).
        """
        if not self.lm_handler_address:
            return "Error: No LM handler configured"

        try:
            request = LMRequest(prompt=prompt, model=model, depth=self.depth)
            response = send_lm_request(self.lm_handler_address, request)

            if not response.success:
                return f"Error: {response.error}"

            # Track this LLM call
            self._pending_llm_calls.append(
                response.chat_completion,
            )

            return response.chat_completion.response
        except Exception as e:
            return f"Error: LM query failed - {e}"

    def _llm_query_batched(self, prompts: list[str], model: str | None = None) -> list[str]:
        """Query the LM with multiple prompts concurrently.

        Args:
            prompts: List of prompts to send to the LM.
            model: Optional model name to use (if handler has multiple clients).

        Returns:
            List of responses in the same order as input prompts.
        """
        if not self.lm_handler_address:
            return ["Error: No LM handler configured"] * len(prompts)

        try:
            responses = send_lm_request_batched(
                self.lm_handler_address, prompts, model=model, depth=self.depth
            )

            results = []
            for response in responses:
                if not response.success:
                    results.append(f"Error: {response.error}")
                else:
                    # Track this LLM call in list of all calls -- we may want to do this hierarchically
                    self._pending_llm_calls.append(response.chat_completion)
                    results.append(response.chat_completion.response)

            return results
        except Exception as e:
            return [f"Error: LM query failed - {e}"] * len(prompts)

    def load_context(self, context_payload: dict | list | str):
        """Load context into the environment as context_0 (and 'context' alias)."""
        self.add_context(context_payload, 0)

    def add_context(
        self, context_payload: dict | list | str, context_index: int | None = None
    ) -> int:
        """
        Add a context with versioned variable name.

        Args:
            context_payload: The context data to add
            context_index: Optional explicit index. If None, auto-increments.

        Returns:
            The context index used.
        """
        if context_index is None:
            context_index = self._context_count

        var_name = f"context_{context_index}"

        if isinstance(context_payload, str):
            context_path = os.path.join(self.temp_dir, f"context_{context_index}.txt")
            with open(context_path, "w") as f:
                f.write(context_payload)
            self.execute_code(f"with open(r'{context_path}', 'r') as f:\n    {var_name} = f.read()")
        else:
            context_path = os.path.join(self.temp_dir, f"context_{context_index}.json")
            with open(context_path, "w") as f:
                json.dump(context_payload, f)
            self.execute_code(
                f"import json\nwith open(r'{context_path}', 'r') as f:\n    {var_name} = json.load(f)"
            )

        # Alias context_0 as 'context' for backward compatibility
        if context_index == 0:
            self.execute_code(f"context = {var_name}")

        self._context_count = max(self._context_count, context_index + 1)
        return context_index

    def update_handler_address(self, address: tuple[str, int]) -> None:
        """Update the LM handler address for a new completion call."""
        self.lm_handler_address = address

    def get_context_count(self) -> int:
        """Return the number of contexts loaded."""
        return self._context_count

    def add_history(
        self, message_history: list[dict[str, Any]], history_index: int | None = None
    ) -> int:
        """
        Store a conversation's message history as a versioned variable.

        Args:
            message_history: The list of message dicts from a completion call
            history_index: Optional explicit index. If None, auto-increments.

        Returns:
            The history index used.
        """
        if history_index is None:
            history_index = self._history_count

        var_name = f"history_{history_index}"

        # Store deep copy to avoid reference issues with nested dicts
        self.locals[var_name] = copy.deepcopy(message_history)

        # Alias history_0 as 'history' for convenience
        if history_index == 0:
            self.locals["history"] = self.locals[var_name]

        self._history_count = max(self._history_count, history_index + 1)
        return history_index

    def get_history_count(self) -> int:
        """Return the number of conversation histories stored."""
        return self._history_count

    @contextmanager
    def _capture_output(self):
        """Thread-safe context manager to capture stdout/stderr."""
        with self._lock:
            old_stdout, old_stderr = sys.stdout, sys.stderr
            stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
            try:
                sys.stdout, sys.stderr = stdout_buf, stderr_buf
                yield stdout_buf, stderr_buf
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr

    @contextmanager
    def _temp_cwd(self):
        """Temporarily change to temp directory for execution."""
        old_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            yield
        finally:
            os.chdir(old_cwd)

    def execute_code(self, code: str) -> REPLResult:
        """Execute code in the persistent namespace and return result."""
        start_time = time.perf_counter()

        # Clear pending LLM calls from previous execution
        self._pending_llm_calls = []

        with self._capture_output() as (stdout_buf, stderr_buf), self._temp_cwd():
            try:
                combined = {**self.globals, **self.locals}
                exec(code, combined, combined)

                # Update locals with new variables
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value

                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue()
            except Exception as e:
                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            rlm_calls=self._pending_llm_calls.copy(),
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def cleanup(self):
        """Clean up temp directory and reset state."""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
        self.globals.clear()
        self.locals.clear()

    def __del__(self):
        self.cleanup()
````

## File: rlm/clients/openai.py
````python
import os
from collections import defaultdict
from typing import Any

import openai
from dotenv import load_dotenv

from rlm.clients.base_lm import BaseLM
from rlm.core.types import ModelUsageSummary, UsageSummary

load_dotenv()

# Load API keys from environment variables
DEFAULT_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DEFAULT_VERCEL_API_KEY = os.getenv("AI_GATEWAY_API_KEY")
DEFAULT_PRIME_INTELLECT_BASE_URL = "https://api.pinference.ai/api/v1/"


class OpenAIClient(BaseLM):
    """
    LM Client for running models with the OpenAI API. Works with vLLM as well.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        super().__init__(model_name=model_name, **kwargs)

        if api_key is None:
            if base_url == "https://api.openai.com/v1" or base_url is None:
                api_key = DEFAULT_OPENAI_API_KEY
            elif base_url == "https://openrouter.ai/api/v1":
                api_key = DEFAULT_OPENROUTER_API_KEY
            elif base_url == "https://ai-gateway.vercel.sh/v1":
                api_key = DEFAULT_VERCEL_API_KEY

        # For vLLM, set base_url to local vLLM server address.
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.async_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

        # Per-model usage tracking
        self.model_call_counts: dict[str, int] = defaultdict(int)
        self.model_input_tokens: dict[str, int] = defaultdict(int)
        self.model_output_tokens: dict[str, int] = defaultdict(int)
        self.model_total_tokens: dict[str, int] = defaultdict(int)

    def completion(self, prompt: str | list[dict[str, Any]], model: str | None = None) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for OpenAI client.")

        extra_body = {}
        if self.client.base_url == DEFAULT_PRIME_INTELLECT_BASE_URL:
            extra_body["usage"] = {"include": True}

        response = self.client.chat.completions.create(
            model=model, messages=messages, extra_body=extra_body
        )
        self._track_cost(response, model)
        return response.choices[0].message.content

    async def acompletion(
        self, prompt: str | list[dict[str, Any]], model: str | None = None
    ) -> str:
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list) and all(isinstance(item, dict) for item in prompt):
            messages = prompt
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        model = model or self.model_name
        if not model:
            raise ValueError("Model name is required for OpenAI client.")

        extra_body = {}
        if self.client.base_url == DEFAULT_PRIME_INTELLECT_BASE_URL:
            extra_body["usage"] = {"include": True}

        response = await self.async_client.chat.completions.create(
            model=model, messages=messages, extra_body=extra_body
        )
        self._track_cost(response, model)
        return response.choices[0].message.content

    def _track_cost(self, response: openai.ChatCompletion, model: str):
        self.model_call_counts[model] += 1

        usage = getattr(response, "usage", None)
        if usage is None:
            raise ValueError("No usage data received. Tracking tokens not possible.")

        self.model_input_tokens[model] += usage.prompt_tokens
        self.model_output_tokens[model] += usage.completion_tokens
        self.model_total_tokens[model] += usage.total_tokens

        # Track last call for handler to read
        self.last_prompt_tokens = usage.prompt_tokens
        self.last_completion_tokens = usage.completion_tokens

    def get_usage_summary(self) -> UsageSummary:
        model_summaries = {}
        for model in self.model_call_counts:
            model_summaries[model] = ModelUsageSummary(
                total_calls=self.model_call_counts[model],
                total_input_tokens=self.model_input_tokens[model],
                total_output_tokens=self.model_output_tokens[model],
            )
        return UsageSummary(model_usage_summaries=model_summaries)

    def get_last_usage(self) -> ModelUsageSummary:
        return ModelUsageSummary(
            total_calls=1,
            total_input_tokens=self.last_prompt_tokens,
            total_output_tokens=self.last_completion_tokens,
        )
````

## File: rlm/core/types.py
````python
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Literal

ClientBackend = Literal[
    "openai",
    "portkey",
    "openrouter",
    "vercel",
    "vllm",
    "litellm",
    "anthropic",
    "azure_openai",
    "gemini",
]
EnvironmentType = Literal["local", "docker", "modal", "prime", "daytona", "e2b"]


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-serializable representation."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, ModuleType):
        return f"<module '{value.__name__}'>"
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if callable(value):
        return f"<{type(value).__name__} '{getattr(value, '__name__', repr(value))}'>"
    # Try to convert to string for other types
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


########################################################
########    Types for LM Cost Tracking         #########
########################################################


@dataclass
class ModelUsageSummary:
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int

    def to_dict(self):
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelUsageSummary":
        return cls(
            total_calls=data.get("total_calls"),
            total_input_tokens=data.get("total_input_tokens"),
            total_output_tokens=data.get("total_output_tokens"),
        )


@dataclass
class UsageSummary:
    model_usage_summaries: dict[str, ModelUsageSummary]

    def to_dict(self):
        return {
            "model_usage_summaries": {
                model: usage_summary.to_dict()
                for model, usage_summary in self.model_usage_summaries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UsageSummary":
        return cls(
            model_usage_summaries={
                model: ModelUsageSummary.from_dict(usage_summary)
                for model, usage_summary in data.get("model_usage_summaries", {}).items()
            },
        )


########################################################
########   Types for REPL and RLM Iterations   #########
########################################################
@dataclass
class RLMChatCompletion:
    """Record of a single LLM call made from within the environment."""

    root_model: str
    prompt: str | dict[str, Any]
    response: str
    usage_summary: UsageSummary
    execution_time: float

    def to_dict(self):
        return {
            "root_model": self.root_model,
            "prompt": self.prompt,
            "response": self.response,
            "usage_summary": self.usage_summary.to_dict(),
            "execution_time": self.execution_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RLMChatCompletion":
        return cls(
            root_model=data.get("root_model"),
            prompt=data.get("prompt"),
            response=data.get("response"),
            usage_summary=UsageSummary.from_dict(data.get("usage_summary")),
            execution_time=data.get("execution_time"),
        )


@dataclass
class REPLResult:
    stdout: str
    stderr: str
    locals: dict
    execution_time: float
    llm_calls: list["RLMChatCompletion"]

    def __init__(
        self,
        stdout: str,
        stderr: str,
        locals: dict,
        execution_time: float = None,
        rlm_calls: list["RLMChatCompletion"] = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.locals = locals
        self.execution_time = execution_time
        self.rlm_calls = rlm_calls or []

    def __str__(self):
        return f"REPLResult(stdout={self.stdout}, stderr={self.stderr}, locals={self.locals}, execution_time={self.execution_time}, rlm_calls={len(self.rlm_calls)})"

    def to_dict(self):
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "locals": {k: _serialize_value(v) for k, v in self.locals.items()},
            "execution_time": self.execution_time,
            "rlm_calls": [call.to_dict() for call in self.rlm_calls],
        }


@dataclass
class CodeBlock:
    code: str
    result: REPLResult

    def to_dict(self):
        return {"code": self.code, "result": self.result.to_dict()}


@dataclass
class RLMIteration:
    prompt: str | dict[str, Any]
    response: str
    code_blocks: list[CodeBlock]
    final_answer: str | None = None
    iteration_time: float | None = None

    def to_dict(self):
        return {
            "prompt": self.prompt,
            "response": self.response,
            "code_blocks": [code_block.to_dict() for code_block in self.code_blocks],
            "final_answer": self.final_answer,
            "iteration_time": self.iteration_time,
        }


########################################################
########   Types for RLM Metadata   #########
########################################################


@dataclass
class RLMMetadata:
    """Metadata about the RLM configuration."""

    root_model: str
    max_depth: int
    max_iterations: int
    backend: str
    backend_kwargs: dict[str, Any]
    environment_type: str
    environment_kwargs: dict[str, Any]
    other_backends: list[str] | None = None

    def to_dict(self):
        return {
            "root_model": self.root_model,
            "max_depth": self.max_depth,
            "max_iterations": self.max_iterations,
            "backend": self.backend,
            "backend_kwargs": {k: _serialize_value(v) for k, v in self.backend_kwargs.items()},
            "environment_type": self.environment_type,
            "environment_kwargs": {
                k: _serialize_value(v) for k, v in self.environment_kwargs.items()
            },
            "other_backends": self.other_backends,
        }


########################################################
########   Types for RLM Prompting   #########
########################################################


@dataclass
class QueryMetadata:
    context_lengths: list[int]
    context_total_length: int
    context_type: str

    def __init__(self, prompt: str | list[str] | dict[Any, Any] | list[dict[Any, Any]]):
        if isinstance(prompt, str):
            self.context_lengths = [len(prompt)]
            self.context_type = "str"
        elif isinstance(prompt, dict):
            self.context_type = "dict"
            self.context_lengths = []
            for chunk in prompt.values():
                if isinstance(chunk, str):
                    self.context_lengths.append(len(chunk))
                    continue
                try:
                    import json

                    self.context_lengths.append(len(json.dumps(chunk, default=str)))
                except Exception:
                    self.context_lengths.append(len(repr(chunk)))
            self.context_type = "dict"
        elif isinstance(prompt, list):
            self.context_type = "list"
            if len(prompt) == 0:
                self.context_lengths = [0]
            elif isinstance(prompt[0], dict):
                if "content" in prompt[0]:
                    self.context_lengths = [len(str(chunk.get("content", ""))) for chunk in prompt]
                else:
                    self.context_lengths = []
                    for chunk in prompt:
                        try:
                            import json

                            self.context_lengths.append(len(json.dumps(chunk, default=str)))
                        except Exception:
                            self.context_lengths.append(len(repr(chunk)))
            else:
                self.context_lengths = [len(chunk) for chunk in prompt]
        else:
            raise ValueError(f"Invalid prompt type: {type(prompt)}")

        self.context_total_length = sum(self.context_lengths)
````

## File: pyproject.toml
````toml
[project]
name = "rlms"
authors = [
    {name = "Alex Zhang", email = "altzhang@mit.edu"},
]
version = "0.1.0"
description = "Recursive Language Models."
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

dependencies = [
    "anthropic>=0.75.0",
    "google-genai>=1.56.0",
    "openai>=2.14.0",
    "portkey-ai>=2.1.0",
    "pytest>=9.0.2",
    "python-dotenv>=1.2.1",
    "requests>=2.32.5",
    "rich>=13.0.0",
]

[project.urls]
Homepage = "https://github.com/alexzhang13/rlm"
Repository = "https://github.com/alexzhang13/rlm"
Issues = "https://github.com/alexzhang13/rlm/issues"

[project.optional-dependencies]
modal = ["modal>=0.73.0", "dill>=0.3.7"]
e2b = ["e2b-code-interpreter>=0.0.11", "dill>=0.3.7"]
daytona = ["daytona>=0.128.1", "dill>=0.3.7"]
prime = ["prime-sandboxes>=0.2.0", "dill>=0.3.7"]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["rlm", "rlm.*"]

[dependency-groups]
dev = [
    "pre-commit>=4.5.1",
    "ruff>=0.14.10",
    "ty>=0.0.7",
]
test = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "UP",  # pyupgrade
]
ignore = [
    "E501",  # line too long (handled by formatter)
]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
````

## File: README.md
````markdown
---

<h1 align="center" style="font-size:2.8em">
<span>Recursive Language Models (<span style="color:orange">RLM</span>s)</span>
</h1>

<p align="center" style="font-size:1.3em">
  <a href="https://arxiv.org/abs/2512.24601">Full Paper</a> •
  <a href="https://alexzhang13.github.io/blog/2025/rlm/">Blogpost</a> •
  <a href="https://alexzhang13.github.io/rlm/">Documentation</a> •
  <a href="https://github.com/alexzhang13/rlm-minimal">RLM Minimal</a>
</p>

<p align="center">
  <a href="https://github.com/alexzhang13/rlm/actions/workflows/style.yml">
    <img src="https://github.com/alexzhang13/rlm/actions/workflows/style.yml/badge.svg" alt="Style" />
  </a>
  <a href="https://github.com/alexzhang13/rlm/actions/workflows/test.yml">
    <img src="https://github.com/alexzhang13/rlm/actions/workflows/test.yml/badge.svg" alt="Test" />
  </a>
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2512.24601">
    <img src="media/paper_preview.png" alt="Paper Preview" width="300"/>
  </a>
</p>

## Overview
Recursive Language Models (RLMs) are a task-agnostic inference paradigm for language models (LMs) to handle near-infinite length contexts by enabling the LM to *programmatically* examine, decompose, and recursively call itself over its input. RLMs replace the canonical `llm.completion(prompt, model)` call with a `rlm.completion(prompt, model)` call. RLMs offload the context as a variable in a REPL environment that the LM can interact with and launch sub-LM calls inside of.

This repository provides an extensible inference engine for using RLMs around standard API-based and local LLMs. The initial experiments and idea were proposed in a [blogpost](https://alexzhang13.github.io/blog/2025/rlm/) in 2025, with expanded results in an [arXiv preprint](https://arxiv.org/abs/2512.24601).

> [!NOTE]
> This repository contains inference code for RLMs with support for various sandbox environments. Open-source contributions are welcome. This repository is maintained by the authors of the paper from the MIT OASYS lab.

## Quick Setup
You can try out RLMs quickly by installing from PyPi:
```bash
pip install rlms
```

The default RLM client uses a REPL environment that runs on the host process through Python `exec` calls. It uses the same virtual environment as the host process (i.e. it will have access to the same dependencies), but with some limitations in its available global modules. As an example, we can call RLM completions using GPT-5-nano:
```python
from rlm import RLM

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "gpt-5-nano"},
    verbose=True,  # For printing to console with rich, disabled by default.
)

print(rlm.completion("Print me the first 100 powers of two, each on a newline.").response)
```

<details>
<summary><b>Manual Setup</b></summary>

Set up the dependencies with `uv` (or your virtual environment of choice):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv init && uv venv --python 3.12  # change version as needed
uv pip install -e .
```

This project includes a `Makefile` to simplify common tasks.

- `make install`: Install base dependencies.
- `make check`: Run linter, formatter, and tests.

To run a quick test, the following will run an RLM query with the OpenAI client using your environment variable `OPENAI_API_KEY` (feel free to change this). This will generate console output as well as a log which you can use with the visualizer to explore the trajectories.
```bash
make quickstart
```

</details>

## REPL Environments
We support two types of REPL environments -- isolated, and non-isolated. Non-isolated environments (default) run code execution on the same machine as the RLM (e.g. through `exec`), which is pretty reasonable for some local low-risk tasks, like simple benchmarking, but can be problematic if the prompts or tool calls can interact with malicious users. Fully isolated environments used Cloud-based sandboxes (e.g. Prime Sandboxes, [Modal Sandboxes](https://modal.com/docs/guide/sandboxes)) to run code generated by the RLM, ensuring completely isolation from the host process. Environments can be added, but we natively support the following: `local` (default), `modal`, `prime`.

```python
rlm = RLM(
    environment="...", # "local", "docker", "modal", "prime"
    environment_kwargs={...},
)
```

### Local Environments
The default `local` environment `LocalREPL` runs in the same process as the RLM itself, with specified global and local namespaces for minimal security. Using this REPL is generally safe, but should not be used for production settings. It also shares the same virtual environment (e.g. Conda or uv) as the host process.

#### Docker <img src="https://github.com/docker.png" alt="Docker" height="20" style="vertical-align: middle;"/> (*requires [Docker installed](https://docs.docker.com/desktop/setup/install/)*)
We also support a Docker-based environment called `DockerREPL` that launches the REPL environment as a Docker image. By default, we use the `python:3.11-slim` image, but the user can specify custom images as well.

### Isolated Environments
We support several different REPL environments that run on separate, cloud-based machines. Whenever a recursive sub-call is made in these instances, it is requested from the host process.

#### Modal Sandboxes <img src="https://github.com/modal-labs.png" alt="Modal" height="20" style="vertical-align: middle;"/>
To use [Modal Sandboxes](https://modal.com/docs/guide/sandboxes) as the REPL environment, you need to install and authenticate your Modal account.
```bash
uv add modal  # add modal library
modal setup   # authenticate account
```

#### Prime Intellect Sandboxes <img src="https://github.com/PrimeIntellect-ai.png" alt="Prime Intellect" height="20" style="vertical-align: middle;"/>
> [!NOTE]
> **Prime Intellect Sandboxes** are currently a beta feature. See the [documentation](https://docs.primeintellect.ai/sandboxes/overview) for more information. We noticed slow runtimes when using these sandboxes, which is currently an open issue.


To use [Prime Sandboxes](https://docs.primeintellect.ai/sandboxes/sdk), install the SDK and set your API key:
```bash
uv pip install -e ".[prime]"
export PRIME_API_KEY=...
```


### Model Providers
We currently support most major clients (OpenAI, Anthropic), as well as the router platforms (OpenRouter, Portkey, LiteLLM). For local models, we recommend using vLLM (which interfaces with the [OpenAI client](https://github.com/alexzhang13/rlm/blob/main/rlm/clients/openai.py)). To view or add support for more clients, start by looking at [`rlm/clients/`](https://github.com/alexzhang13/rlm/tree/main/rlm/clients).

## Relevant Reading
* **[Dec '25]** [Recursive Language Models arXiv](https://arxiv.org/abs/2512.24601)
* **[Oct '25]** [Recursive Language Models Blogpost](https://alexzhang13.github.io/blog/2025/rlm/)

If you use this code or repository in your research, please cite:

```bibtex
@misc{zhang2025recursivelanguagemodels,
      title={Recursive Language Models}, 
      author={Alex L. Zhang and Tim Kraska and Omar Khattab},
      year={2025},
      eprint={2512.24601},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2512.24601}, 
}
```

## Optional Debugging: Visualizing RLM Trajectories
We additionally provide a simple visualizer tool to examine and view the code, sub-LM, and root-LM calls of an RLM trajectory. To save log files (`.jsonl`) on every completion call that can be viewed in the visualizer, initialize the `RLMLogger` object and pass it into the `RLM` on initialization:
```python
from rlm.logger import RLMLogger
from rlm import RLM

logger = RLMLogger(log_dir="./logs")
rlm = RLM(
    ...
    logger=logger
)
```

To run the visualizer locally, we use Node.js and shadcn/ui:
```
cd visualizer/
npm run dev        # default localhost:3001
```

You'll have the option to select saved `.jsonl` files 
<p align="center">
  <img src="media/visualizer.png" alt="RLM Visualizer Example" width="800"/>
</p>
````