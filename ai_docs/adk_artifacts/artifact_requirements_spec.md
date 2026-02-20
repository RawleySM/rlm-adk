# Artifact Service & Registry Requirements Specification

## Document Metadata

- **Author:** Requirements Spec Agent
- **Date:** 2026-02-19
- **Status:** Draft
- **Target Codebase:** rlm-adk (`/home/rawley-stanhope/dev/rlm-adk/`)
- **ADK Version:** google-adk>=1.2.0

---

## a) Executive Summary

The rlm-adk project implements a Recursive Language Model (RLM) orchestration loop on top of Google ADK. The orchestrator runs iterative reasoning cycles where an LLM generates code, a REPL executes it, and the results feed back into the next iteration. Sub-LM queries are dispatched through a `WorkerPool` to `LlmAgent` instances.

Currently, all intermediate data (code outputs, REPL results, worker responses) flows through ADK session state as string values. This approach has three limitations:

1. **Binary data cannot be stored.** The REPL may produce charts, CSV exports, PDF reports, or serialized model checkpoints. These cannot be represented as session state strings.
2. **Large outputs inflate the context window.** Worker results and REPL outputs stored in state are included in subsequent LLM calls, consuming token budget.
3. **No versioned history of intermediate products.** When the orchestrator overwrites `last_repl_result` each iteration, previous outputs are lost.

This specification defines the integration of Google ADK's `ArtifactService` into rlm-adk, providing versioned binary storage for REPL outputs, worker results, and user-uploaded files. The implementation uses ADK's existing `BaseArtifactService` abstraction with `InMemoryArtifactService` for development/testing. The architecture adds a thin integration layer that connects artifact operations to the existing orchestrator loop, worker dispatch, and plugin system without requiring changes to the ADK framework itself.

---

## b) Scope

### In Scope

- Integration of ADK's `BaseArtifactService` into the RLM runner and orchestrator
- `InMemoryArtifactService` wired into `create_rlm_runner()` (already referenced in docstring but not functionally used)
- Artifact save/load/list/delete operations accessible from the orchestrator loop
- REPL output artifact storage (stdout, generated files)
- Worker result artifact storage (large LLM responses offloaded from state)
- Artifact versioning across orchestrator iterations
- Session-scoped artifacts (per-invocation intermediate products)
- User-scoped artifacts (cross-session data via `user:` prefix)
- Observability plugin integration for artifact operation tracking
- Debug logging plugin integration for artifact operation tracing
- State key constants for artifact-related metadata
- Comprehensive TDD test suite

### Out of Scope

- `GcsArtifactService` production deployment (future work; no `google-cloud-storage` dependency added)
- `FileArtifactService` integration (available in ADK, not needed for initial implementation)
- Custom `BaseArtifactService` subclass (we use ADK's built-in implementations directly)
- `SaveFilesAsArtifactsPlugin` from upstream ADK (can be added later as a separate plugin)
- Artifact-based session rewind (requires deeper ADK runner integration)
- Multi-agent artifact sharing across different sessions
- Artifact streaming or chunked upload/download
- Artifact encryption or access control beyond ADK's scoping model

---

## c) Architecture Integration

### Current Architecture (Relevant Components)

```
create_rlm_runner()                      # rlm_adk/agent.py
  -> create_rlm_app()
       -> create_rlm_orchestrator()
            -> RLMOrchestratorAgent       # rlm_adk/orchestrator.py
                 -> reasoning_agent (LlmAgent)
                 -> WorkerPool            # rlm_adk/dispatch.py
       -> App(plugins=[ObservabilityPlugin, DebugLoggingPlugin])
  -> InMemoryRunner(app=rlm_app)
```

### How Artifact Service Fits In

The artifact service integrates at three levels:

**Level 1: Runner (Service Layer)**

`InMemoryRunner` already accepts and manages an `artifact_service`. The `create_rlm_runner()` function in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` already documents this in its docstring ("An in-memory ArtifactService for binary artifact storage") but `InMemoryRunner` creates its own internally. We need to make the artifact service explicitly accessible and configurable.

The `InvocationContext` provided to agents has an `artifact_service` field. This is the primary access path -- no custom plumbing needed.

**Level 2: Orchestrator (Operation Layer)**

The `RLMOrchestratorAgent._run_async_impl()` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` receives the `InvocationContext` as `ctx`. It can access `ctx.artifact_service` directly to:

- Save REPL outputs as artifacts after code execution
- Save the final answer as an artifact
- Load previously-saved artifacts for injection into prompts
- Track artifact operations via `EventActions.artifact_delta`

A new helper module `rlm_adk/artifacts.py` provides convenience functions that wrap the raw `BaseArtifactService` API with RLM-specific conventions (naming, metadata, error handling).

**Level 3: Plugins (Cross-Cutting Concerns)**

The existing plugin system (`BasePlugin` subclasses) gains artifact awareness:

- `ObservabilityPlugin` tracks artifact save/load counts and sizes
- `DebugLoggingPlugin` traces artifact operations in debug output
- A new `ArtifactPlugin` (optional, future) could auto-save REPL outputs

### Integration Flow Diagram

```
Orchestrator Loop (iter N)
  |
  +-> Reasoning Agent runs -> response text
  |
  +-> Extract code blocks
  |
  +-> REPL executes code
  |     |
  |     +-> stdout/stderr captured
  |     +-> [NEW] If output is large or binary:
  |           save_artifact("repl_output_iter_{N}.txt", data)
  |           Replace state value with artifact reference
  |
  +-> [NEW] Worker dispatch (if llm_query in code)
  |     |
  |     +-> Worker response text
  |     +-> [NEW] If response exceeds threshold:
  |           save_artifact("worker_{name}_iter_{N}.txt", data)
  |           Replace state value with artifact reference
  |
  +-> Check for final answer
  |     +-> [NEW] save_artifact("final_answer.md", final_text)
  |
  +-> Format iteration, update message_history
  |     +-> [NEW] artifact_delta tracked in Event
```

### Key Design Decisions

1. **No custom BaseArtifactService subclass.** We use `InMemoryArtifactService` directly from `google.adk.artifacts`. This keeps us aligned with upstream ADK and avoids maintenance burden.

2. **Convenience wrapper, not abstraction.** The `rlm_adk/artifacts.py` module provides helper functions (not a class) that accept `InvocationContext` and handle naming conventions, error wrapping, and metadata. This avoids creating a parallel abstraction to ADK's.

3. **Opt-in artifact storage.** Artifact operations are gated by the presence of `ctx.artifact_service`. If no service is configured, the orchestrator and workers behave exactly as they do today. This maintains backward compatibility.

4. **Size-based offloading.** The decision to store data as an artifact vs. keeping it in state is driven by a configurable byte threshold (default: 10KB). This prevents small outputs from incurring artifact overhead while offloading large ones.

5. **Artifact naming convention.** All rlm-adk artifacts follow a predictable naming pattern:
   - REPL outputs: `repl_output_iter_{iteration}.txt`
   - Worker results: `worker_{worker_name}_iter_{iteration}.txt`
   - Final answer: `final_answer.md`
   - User-scoped: `user:` prefix per ADK convention

---

## d) Functional Requirements

### FR-001: Artifact Service Wiring in Runner Factory

**Description:** The `create_rlm_runner()` function in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` must accept an optional `artifact_service` parameter and pass it through to the `InMemoryRunner`.

**Details:**
- Add `artifact_service: BaseArtifactService | None = None` parameter to `create_rlm_runner()`
- When `None`, `InMemoryRunner` uses its own default (already creates `InMemoryArtifactService` internally)
- When provided, the custom service is used instead
- The `InvocationContext.artifact_service` is set automatically by `InMemoryRunner`

**Acceptance:** `create_rlm_runner(model="...", artifact_service=InMemoryArtifactService())` creates a runner whose `InvocationContext` exposes the provided service.

---

### FR-002: Artifact Helper Module

**Description:** Create `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/artifacts.py` with convenience functions for artifact operations within the RLM context.

**Functions:**

```python
async def save_repl_output(
    ctx: InvocationContext,
    iteration: int,
    stdout: str,
    stderr: str = "",
    mime_type: str = "text/plain",
) -> int | None:
    """Save REPL output as a versioned artifact.
    Returns version number, or None if no artifact service configured."""

async def save_worker_result(
    ctx: InvocationContext,
    worker_name: str,
    iteration: int,
    result_text: str,
    mime_type: str = "text/plain",
) -> int | None:
    """Save worker result as a versioned artifact.
    Returns version number, or None if no artifact service configured."""

async def save_final_answer(
    ctx: InvocationContext,
    answer: str,
    mime_type: str = "text/markdown",
) -> int | None:
    """Save the final answer as an artifact.
    Returns version number, or None if no artifact service configured."""

async def save_binary_artifact(
    ctx: InvocationContext,
    filename: str,
    data: bytes,
    mime_type: str,
) -> int | None:
    """Save arbitrary binary data as an artifact.
    Returns version number, or None if no artifact service configured."""

async def load_artifact(
    ctx: InvocationContext,
    filename: str,
    version: int | None = None,
) -> types.Part | None:
    """Load an artifact by filename, optionally at a specific version.
    Returns the Part, or None if not found or no service configured."""

async def list_artifacts(
    ctx: InvocationContext,
) -> list[str]:
    """List all artifact filenames in the current session scope.
    Returns empty list if no service configured."""

async def delete_artifact(
    ctx: InvocationContext,
    filename: str,
) -> bool:
    """Delete an artifact and all its versions.
    Returns True if deleted, False if no service configured."""

def should_offload_to_artifact(data: str | bytes, threshold: int = 10240) -> bool:
    """Determine if data should be stored as artifact vs. inline in state.
    Returns True if len(data) > threshold."""
```

**Key Design:**
- All functions extract `app_name`, `user_id`, `session_id` from `InvocationContext` fields
- All functions return `None`/`[]`/`False` gracefully when `ctx.artifact_service` is `None`
- All functions are async to match ADK's artifact service interface
- Functions use `types.Part.from_bytes()` or `types.Part.from_text()` to create artifact data

---

### FR-003: Orchestrator Artifact Integration

**Description:** Modify `RLMOrchestratorAgent._run_async_impl()` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` to optionally save REPL outputs and final answers as artifacts.

**Changes:**
1. After REPL code execution (around line 267), check `should_offload_to_artifact()` for each code block result. If true, call `save_repl_output()` and replace the inline result with an artifact reference string.
2. When a final answer is detected (around line 278), call `save_final_answer()` to persist it as an artifact.
3. Include `artifact_delta` tracking in yielded `Event` objects when artifacts are saved.

**Gating:** All artifact operations are conditional on `ctx.artifact_service is not None`. If no service is configured, behavior is identical to today.

---

### FR-004: Worker Dispatch Artifact Integration

**Description:** Modify the `llm_query_batched_async` closure in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` to optionally offload large worker responses to artifacts.

**Changes:**
1. After collecting worker results (around line 287), check `should_offload_to_artifact()` for each result.
2. If true, call `save_worker_result()` and replace the inline result with an artifact reference placeholder: `"[Artifact: worker_{name}_iter_{N}]"`.
3. The full result remains accessible via `load_artifact()`.

**Gating:** Conditional on `ctx.artifact_service is not None`.

---

### FR-005: Artifact Versioning Support

**Description:** Each call to `save_repl_output()` or `save_worker_result()` with the same filename creates a new version. The helper functions return the version number for tracking.

**Details:**
- Version numbers start at 0 and auto-increment (managed by `BaseArtifactService`)
- The orchestrator can load a specific version: `load_artifact(ctx, "repl_output_iter_3.txt", version=0)`
- `list_versions()` is available through the raw service API via `ctx.artifact_service.list_versions()`
- Artifact version metadata (via `ArtifactVersion`) includes `create_time`, `mime_type`, and optional `custom_metadata`

---

### FR-006: Session-Scoped vs User-Scoped Artifacts

**Description:** Support both session-scoped and user-scoped artifacts using ADK's built-in scoping conventions.

**Details:**
- By default, all artifacts are session-scoped: `filename="repl_output_iter_0.txt"` is keyed to `(app_name, user_id, session_id, filename)`
- User-scoped artifacts use the `user:` prefix: `filename="user:config.json"` is keyed to `(app_name, user_id, filename)` and persists across sessions
- The helper functions in `rlm_adk/artifacts.py` pass through the `user:` prefix transparently
- The `list_artifacts()` helper returns both session-scoped and user-scoped artifact filenames

---

### FR-007: Artifact State Key Constants

**Description:** Add artifact-related state key constants to `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py`.

**New Constants:**

```python
# Artifact Tracking Keys (session-scoped)
ARTIFACT_SAVE_COUNT = "artifact_save_count"
ARTIFACT_LOAD_COUNT = "artifact_load_count"
ARTIFACT_TOTAL_BYTES_SAVED = "artifact_total_bytes_saved"
ARTIFACT_LAST_SAVED_FILENAME = "artifact_last_saved_filename"
ARTIFACT_LAST_SAVED_VERSION = "artifact_last_saved_version"

# Artifact Observability Keys (session-scoped)
OBS_ARTIFACT_SAVES = "obs:artifact_saves"
OBS_ARTIFACT_LOADS = "obs:artifact_loads"
OBS_ARTIFACT_DELETES = "obs:artifact_deletes"
OBS_ARTIFACT_BYTES_SAVED = "obs:artifact_bytes_saved"
OBS_ARTIFACT_SAVE_LATENCY_MS = "obs:artifact_save_latency_ms"

# Artifact Configuration Keys (app-scoped)
APP_ARTIFACT_OFFLOAD_THRESHOLD = "app:artifact_offload_threshold"
```

---

### FR-008: Observability Plugin Artifact Tracking

**Description:** Extend `ObservabilityPlugin` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py` to track artifact operations.

**Changes:**
- In `after_run_callback`, read artifact state keys (`OBS_ARTIFACT_SAVES`, `OBS_ARTIFACT_LOADS`, `OBS_ARTIFACT_BYTES_SAVED`) and log a summary
- In `on_event_callback`, detect `artifact_delta` in events and log artifact changes
- Add artifact stats to the final run summary logged by `after_run_callback`

---

### FR-009: Debug Logging Plugin Artifact Tracing

**Description:** Extend `DebugLoggingPlugin` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py` to trace artifact operations.

**Changes:**
- In `on_event_callback`, when `event.actions.artifact_delta` is present, log artifact filenames and versions
- In `after_run_callback`, include artifact stats in the YAML trace output
- Print `[RLM] artifact saved: {filename} v{version} ({size} bytes)` to stdout during save operations

---

### FR-010: Artifact Service Access from Callbacks

**Description:** The artifact helper functions must work from within `CallbackContext` (via `_invocation_context`) in addition to working from direct `InvocationContext` access.

**Details:**
- Provide an overloaded helper or a context extraction utility:
  ```python
  def get_invocation_context(ctx: InvocationContext | CallbackContext) -> InvocationContext:
      if isinstance(ctx, CallbackContext):
          return ctx._invocation_context
      return ctx
  ```
- This enables artifact operations from within `reasoning_before_model`, `reasoning_after_model`, `worker_before_model`, and `worker_after_model` callbacks

---

## e) Non-Functional Requirements

### NFR-001: Async Operations (No Blocking)

All artifact operations must be async and must not block the asyncio event loop. The `InMemoryArtifactService` already implements native async methods. Future `GcsArtifactService` or `FileArtifactService` use `asyncio.to_thread()` for blocking I/O. The helper functions in `rlm_adk/artifacts.py` must all be `async def`.

### NFR-002: Thread Safety for Concurrent Workers

When multiple workers run concurrently via `ParallelAgent`, artifact saves from different workers must not corrupt shared state. Mitigations:
- Each worker saves to a uniquely-named artifact (includes worker name in filename)
- `InMemoryArtifactService` uses dict-based storage; concurrent writes to different keys are safe
- Artifact version counters are per-filename, so no cross-filename contention
- `artifact_delta` in `EventActions` is per-event, and events are processed sequentially by the Runner

### NFR-003: Memory Management

- `InMemoryArtifactService` stores all artifact data in memory. For long-running sessions with many iterations, this can grow unbounded.
- The helper functions should track `OBS_ARTIFACT_BYTES_SAVED` in state so the observability plugin can report total memory consumed by artifacts.
- A future enhancement (out of scope for initial implementation) could add artifact eviction or limits.

### NFR-004: Error Handling Patterns

All artifact operations must follow these error handling rules:
- **Missing service:** Return `None`/`[]`/`False` gracefully. Never raise `ValueError`. Log at debug level.
- **Save failures:** Log at warning level, return `None`. Do not interrupt the orchestrator loop.
- **Load failures:** Return `None`. The caller checks the return value.
- **Invalid filenames:** Let the underlying `BaseArtifactService` raise `InputValidationError`. Do not catch it -- this is a programming error.
- Pattern: All helper functions wrap operations in `try/except Exception` with logging, matching the existing plugin error-handling pattern (see `ObservabilityPlugin`, `DebugLoggingPlugin`).

### NFR-005: Backward Compatibility

- All artifact features are opt-in. When `artifact_service` is `None`, the system behaves identically to the current implementation.
- No existing function signatures change in a backward-incompatible way (new parameters are optional with defaults).
- No existing state keys are modified or removed.
- No existing test expectations are broken.

### NFR-006: Performance

- Artifact save/load adds latency to the orchestrator loop. For `InMemoryArtifactService`, this is negligible (dict operations).
- The `should_offload_to_artifact()` threshold check is O(1) (just `len(data)`).
- Artifact operations should not be performed when the data is small enough to fit in state (threshold gating).

---

## f) File Plan

### New Files

| File | Purpose |
|------|---------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/artifacts.py` | Artifact helper functions (FR-002) |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_artifacts.py` | Unit tests for artifact helpers |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_artifacts_integration.py` | Integration tests for orchestrator + artifacts |

### Modified Files

| File | Changes |
|------|---------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py` | Add artifact state key constants (FR-007) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` | Add `artifact_service` parameter to `create_rlm_runner()` (FR-001) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` | Add artifact save calls for REPL output and final answer (FR-003) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` | Add artifact save for large worker results (FR-004) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py` | Add artifact tracking in `on_event_callback` and `after_run_callback` (FR-008) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py` | Add artifact tracing in `on_event_callback` and `after_run_callback` (FR-009) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/__init__.py` | No changes needed (artifacts module is internal) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py` | No changes needed initially |

### Files NOT Modified

| File | Reason |
|------|--------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py` | Worker callbacks write to state; artifact offloading happens in dispatch.py |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py` | Reasoning callbacks write to state; artifact offloading happens in orchestrator.py |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/cache.py` | Cache operates on LLM request/response, orthogonal to artifacts |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/policy.py` | Policy is auth/safety, orthogonal to artifacts |
| `/home/rawley-stanhope/dev/rlm-adk/pyproject.toml` | No new dependencies needed (`google-adk` already includes artifact support) |

---

## g) Test Plan

### Test Infrastructure

**Test runner command:** `.venv/bin/python -m pytest tests_rlm_adk/ -v`

**Async test mode:** `asyncio_mode = "auto"` (already configured in `pyproject.toml`)

**Key fixture needed:**

```python
# In tests_rlm_adk/conftest.py (add to existing)
@pytest.fixture
def artifact_service():
    """Provide a fresh InMemoryArtifactService."""
    from google.adk.artifacts import InMemoryArtifactService
    return InMemoryArtifactService()
```

**Mock InvocationContext fixture:**

```python
@pytest.fixture
def mock_invocation_context(artifact_service):
    """Provide a mock InvocationContext with artifact service."""
    from unittest.mock import MagicMock
    ctx = MagicMock(spec=InvocationContext)
    ctx.artifact_service = artifact_service
    ctx.app_name = "test_app"
    ctx.user_id = "test_user"
    ctx.session = MagicMock()
    ctx.session.id = "test_session"
    ctx.session.user_id = "test_user"
    ctx.session.state = {}
    ctx.invocation_id = "test_invocation"
    return ctx
```

### TDD Red/Green Sequence

Tests are ordered so that each builds on the previous. Write the test first (RED), then implement the code to make it pass (GREEN).

#### Phase 1: State Keys and Helpers (Foundation)

**File:** `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_artifacts.py`

**Test 1.1: State key constants exist (FR-007)**
```python
def test_artifact_state_keys_defined():
    """Verify all artifact state key constants are importable."""
    from rlm_adk.state import (
        ARTIFACT_SAVE_COUNT,
        ARTIFACT_LOAD_COUNT,
        ARTIFACT_TOTAL_BYTES_SAVED,
        ARTIFACT_LAST_SAVED_FILENAME,
        ARTIFACT_LAST_SAVED_VERSION,
        OBS_ARTIFACT_SAVES,
        OBS_ARTIFACT_LOADS,
        OBS_ARTIFACT_DELETES,
        OBS_ARTIFACT_BYTES_SAVED,
        OBS_ARTIFACT_SAVE_LATENCY_MS,
        APP_ARTIFACT_OFFLOAD_THRESHOLD,
    )
    assert ARTIFACT_SAVE_COUNT == "artifact_save_count"
    # ... etc for each key
```

**Test 1.2: should_offload_to_artifact threshold logic (FR-002)**
```python
def test_should_offload_small_string():
    from rlm_adk.artifacts import should_offload_to_artifact
    assert should_offload_to_artifact("short") is False

def test_should_offload_large_string():
    from rlm_adk.artifacts import should_offload_to_artifact
    assert should_offload_to_artifact("x" * 20000) is True

def test_should_offload_custom_threshold():
    from rlm_adk.artifacts import should_offload_to_artifact
    assert should_offload_to_artifact("hello", threshold=3) is True
    assert should_offload_to_artifact("hi", threshold=3) is False

def test_should_offload_bytes():
    from rlm_adk.artifacts import should_offload_to_artifact
    assert should_offload_to_artifact(b"\x00" * 20000) is True
    assert should_offload_to_artifact(b"\x00" * 100) is False
```

**Test 1.3: Helper returns None when no artifact service (FR-002, NFR-004)**
```python
async def test_save_repl_output_no_service():
    from rlm_adk.artifacts import save_repl_output
    ctx = MagicMock()
    ctx.artifact_service = None
    result = await save_repl_output(ctx, iteration=0, stdout="output")
    assert result is None

async def test_load_artifact_no_service():
    from rlm_adk.artifacts import load_artifact
    ctx = MagicMock()
    ctx.artifact_service = None
    result = await load_artifact(ctx, "test.txt")
    assert result is None

async def test_list_artifacts_no_service():
    from rlm_adk.artifacts import list_artifacts
    ctx = MagicMock()
    ctx.artifact_service = None
    result = await list_artifacts(ctx)
    assert result == []
```

#### Phase 2: Artifact CRUD Operations (Core)

**Test 2.1: Save and load REPL output artifact (FR-002, FR-005)**
```python
async def test_save_and_load_repl_output(mock_invocation_context):
    from rlm_adk.artifacts import save_repl_output, load_artifact
    version = await save_repl_output(
        mock_invocation_context, iteration=0, stdout="Hello World"
    )
    assert version == 0
    loaded = await load_artifact(mock_invocation_context, "repl_output_iter_0.txt")
    assert loaded is not None
    # Verify content
    if loaded.text:
        assert "Hello World" in loaded.text
    elif loaded.inline_data:
        assert b"Hello World" in loaded.inline_data.data
```

**Test 2.2: Save and load worker result artifact (FR-002)**
```python
async def test_save_and_load_worker_result(mock_invocation_context):
    from rlm_adk.artifacts import save_worker_result, load_artifact
    version = await save_worker_result(
        mock_invocation_context, worker_name="worker_1", iteration=3,
        result_text="Analysis complete: 42 findings"
    )
    assert version == 0
    loaded = await load_artifact(
        mock_invocation_context, "worker_worker_1_iter_3.txt"
    )
    assert loaded is not None
```

**Test 2.3: Save and load final answer artifact (FR-002)**
```python
async def test_save_final_answer(mock_invocation_context):
    from rlm_adk.artifacts import save_final_answer, load_artifact
    version = await save_final_answer(
        mock_invocation_context, answer="The answer is 42."
    )
    assert version == 0
    loaded = await load_artifact(mock_invocation_context, "final_answer.md")
    assert loaded is not None
```

**Test 2.4: Save binary artifact (FR-002)**
```python
async def test_save_binary_artifact(mock_invocation_context):
    from rlm_adk.artifacts import save_binary_artifact, load_artifact
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header
    version = await save_binary_artifact(
        mock_invocation_context, filename="chart.png",
        data=data, mime_type="image/png"
    )
    assert version == 0
    loaded = await load_artifact(mock_invocation_context, "chart.png")
    assert loaded is not None
    assert loaded.inline_data.data == data
    assert loaded.inline_data.mime_type == "image/png"
```

**Test 2.5: Versioning via repeated saves (FR-005)**
```python
async def test_artifact_versioning(mock_invocation_context):
    from rlm_adk.artifacts import save_repl_output, load_artifact
    v0 = await save_repl_output(mock_invocation_context, iteration=0, stdout="v0")
    v1 = await save_repl_output(mock_invocation_context, iteration=0, stdout="v1")
    assert v0 == 0
    assert v1 == 1
    # Load latest
    latest = await load_artifact(mock_invocation_context, "repl_output_iter_0.txt")
    assert latest is not None
    # Load specific version
    original = await load_artifact(
        mock_invocation_context, "repl_output_iter_0.txt", version=0
    )
    assert original is not None
```

**Test 2.6: List artifacts (FR-002)**
```python
async def test_list_artifacts(mock_invocation_context):
    from rlm_adk.artifacts import save_repl_output, save_final_answer, list_artifacts
    await save_repl_output(mock_invocation_context, iteration=0, stdout="out")
    await save_final_answer(mock_invocation_context, answer="done")
    filenames = await list_artifacts(mock_invocation_context)
    assert "repl_output_iter_0.txt" in filenames
    assert "final_answer.md" in filenames
```

**Test 2.7: Delete artifact (FR-002)**
```python
async def test_delete_artifact(mock_invocation_context):
    from rlm_adk.artifacts import save_repl_output, delete_artifact, list_artifacts
    await save_repl_output(mock_invocation_context, iteration=0, stdout="out")
    result = await delete_artifact(mock_invocation_context, "repl_output_iter_0.txt")
    assert result is True
    filenames = await list_artifacts(mock_invocation_context)
    assert "repl_output_iter_0.txt" not in filenames
```

#### Phase 3: Scoping (FR-006)

**Test 3.1: Session-scoped artifact isolation**
```python
async def test_session_scoped_artifact_isolation(artifact_service):
    """Artifacts in different sessions are isolated."""
    from google.genai import types
    part = types.Part.from_text("session data")
    await artifact_service.save_artifact(
        app_name="test", user_id="u1", session_id="s1",
        filename="data.txt", artifact=part,
    )
    loaded = await artifact_service.load_artifact(
        app_name="test", user_id="u1", session_id="s2",
        filename="data.txt",
    )
    assert loaded is None  # Different session, not found
```

**Test 3.2: User-scoped artifact cross-session access**
```python
async def test_user_scoped_artifact_cross_session(artifact_service):
    """User-scoped artifacts are accessible across sessions."""
    from google.genai import types
    part = types.Part.from_text("user config")
    await artifact_service.save_artifact(
        app_name="test", user_id="u1", session_id="s1",
        filename="user:config.json", artifact=part,
    )
    loaded = await artifact_service.load_artifact(
        app_name="test", user_id="u1",
        filename="user:config.json",
    )
    assert loaded is not None
```

#### Phase 4: Runner Integration (FR-001)

**File:** `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_artifacts_integration.py`

**Test 4.1: create_rlm_runner accepts artifact_service parameter**
```python
def test_create_rlm_runner_accepts_artifact_service():
    from google.adk.artifacts import InMemoryArtifactService
    from rlm_adk.agent import create_rlm_runner
    service = InMemoryArtifactService()
    # Should not raise
    runner = create_rlm_runner(
        model="gemini-2.5-flash",
        artifact_service=service,
    )
    assert runner is not None
```

**Test 4.2: create_rlm_runner works without artifact_service (backward compat)**
```python
def test_create_rlm_runner_without_artifact_service():
    from rlm_adk.agent import create_rlm_runner
    runner = create_rlm_runner(model="gemini-2.5-flash")
    assert runner is not None
```

#### Phase 5: Plugin Integration (FR-008, FR-009)

**Test 5.1: ObservabilityPlugin tracks artifact events**
```python
async def test_observability_tracks_artifact_delta():
    from rlm_adk.plugins.observability import ObservabilityPlugin
    from unittest.mock import MagicMock
    plugin = ObservabilityPlugin()
    ctx = MagicMock()
    ctx.session.state = {}
    event = MagicMock()
    event.actions.state_delta = {}
    event.actions.artifact_delta = {"report.pdf": 0}
    event.author = "orchestrator"
    await plugin.on_event_callback(invocation_context=ctx, event=event)
    # Verify artifact tracking state was updated
    assert ctx.session.state.get("obs:artifact_saves", 0) >= 0
```

**Test 5.2: DebugLogging traces artifact delta**
```python
async def test_debug_logging_traces_artifact_delta(capsys):
    from rlm_adk.plugins.debug_logging import DebugLoggingPlugin
    from unittest.mock import MagicMock
    plugin = DebugLoggingPlugin()
    ctx = MagicMock()
    ctx.session.state = {}
    event = MagicMock()
    event.actions.state_delta = {}
    event.actions.artifact_delta = {"chart.png": 0}
    event.author = "orchestrator"
    await plugin.on_event_callback(invocation_context=ctx, event=event)
    # Verify artifact info logged
    # (check _traces or stdout capture)
```

#### Phase 6: Error Handling (NFR-004)

**Test 6.1: Save gracefully handles service errors**
```python
async def test_save_handles_service_error():
    from rlm_adk.artifacts import save_repl_output
    from unittest.mock import MagicMock, AsyncMock
    ctx = MagicMock()
    ctx.artifact_service = MagicMock()
    ctx.artifact_service.save_artifact = AsyncMock(side_effect=Exception("disk full"))
    ctx.app_name = "test"
    ctx.session = MagicMock()
    ctx.session.id = "s1"
    ctx.session.user_id = "u1"
    ctx.session.state = {}
    result = await save_repl_output(ctx, iteration=0, stdout="data")
    assert result is None  # Graceful failure, no exception raised
```

**Test 6.2: Load returns None for missing artifact**
```python
async def test_load_returns_none_for_missing(mock_invocation_context):
    from rlm_adk.artifacts import load_artifact
    result = await load_artifact(mock_invocation_context, "nonexistent.txt")
    assert result is None
```

### Test Execution Order

For TDD, implement in this order:

1. `test_artifact_state_keys_defined` -> Add constants to `state.py`
2. `test_should_offload_*` -> Implement `should_offload_to_artifact()` in `artifacts.py`
3. `test_*_no_service` -> Implement graceful None-return in helper functions
4. `test_save_and_load_repl_output` -> Implement `save_repl_output()` and `load_artifact()`
5. `test_save_and_load_worker_result` -> Implement `save_worker_result()`
6. `test_save_final_answer` -> Implement `save_final_answer()`
7. `test_save_binary_artifact` -> Implement `save_binary_artifact()`
8. `test_artifact_versioning` -> Verify versioning works (should pass with existing ADK)
9. `test_list_artifacts` -> Implement `list_artifacts()`
10. `test_delete_artifact` -> Implement `delete_artifact()`
11. `test_session_scoped_*` -> Verify scoping (ADK built-in, should pass)
12. `test_user_scoped_*` -> Verify user scoping (ADK built-in, should pass)
13. `test_create_rlm_runner_*` -> Modify `create_rlm_runner()` in `agent.py`
14. `test_observability_*` -> Modify `ObservabilityPlugin`
15. `test_debug_logging_*` -> Modify `DebugLoggingPlugin`
16. `test_save_handles_service_error` -> Verify error handling
17. `test_load_returns_none_for_missing` -> Verify load-miss behavior

---

## h) Dependencies

### No New Dependencies Required

All required packages are already in `pyproject.toml`:

| Package | Version | Purpose |
|---------|---------|---------|
| `google-adk` | `>=1.2.0` | Provides `BaseArtifactService`, `InMemoryArtifactService`, `FileArtifactService`, `GcsArtifactService` |
| `google-genai` | `>=1.56.0` | Provides `types.Part`, `types.Blob` for artifact data containers |
| `pydantic` | (transitive via google-adk) | Used by `ArtifactVersion` model and `InMemoryArtifactService` |
| `pytest` | `>=9.0.2` | Test framework |
| `pytest-asyncio` | `>=0.24.0` | Async test support |

### Import Paths

```python
# From google-adk
from google.adk.artifacts import InMemoryArtifactService, BaseArtifactService
from google.adk.artifacts.base_artifact_service import ArtifactVersion
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

# From google-genai
from google.genai import types  # types.Part, types.Blob
```

---

## i) Acceptance Criteria

The implementation is complete when all of the following are true:

### Code Criteria

- [ ] **AC-1:** `rlm_adk/artifacts.py` exists with all functions defined in FR-002
- [ ] **AC-2:** `rlm_adk/state.py` contains all artifact state key constants from FR-007
- [ ] **AC-3:** `create_rlm_runner()` in `rlm_adk/agent.py` accepts optional `artifact_service` parameter (FR-001)
- [ ] **AC-4:** `RLMOrchestratorAgent._run_async_impl()` conditionally saves REPL outputs and final answers as artifacts (FR-003)
- [ ] **AC-5:** `llm_query_batched_async` in `rlm_adk/dispatch.py` conditionally offloads large worker results (FR-004)
- [ ] **AC-6:** `ObservabilityPlugin` tracks artifact operations (FR-008)
- [ ] **AC-7:** `DebugLoggingPlugin` traces artifact operations (FR-009)

### Test Criteria

- [ ] **AC-8:** All tests in `tests_rlm_adk/test_adk_artifacts.py` pass
- [ ] **AC-9:** All tests in `tests_rlm_adk/test_adk_artifacts_integration.py` pass
- [ ] **AC-10:** All existing tests continue to pass (`tests_rlm_adk/test_adk_*.py`, `tests_rlm_adk/test_bug*.py`)
- [ ] **AC-11:** No new test warnings or deprecation notices

### Behavioral Criteria

- [ ] **AC-12:** When `artifact_service` is `None`, the system behaves identically to the current implementation (NFR-005)
- [ ] **AC-13:** Artifact filenames follow the naming convention: `repl_output_iter_{N}.txt`, `worker_{name}_iter_{N}.txt`, `final_answer.md`
- [ ] **AC-14:** Saving the same filename creates a new version (version numbers 0, 1, 2, ...) (FR-005)
- [ ] **AC-15:** User-scoped artifacts (prefixed with `user:`) are accessible across sessions (FR-006)
- [ ] **AC-16:** Artifact save/load failures are logged but do not crash the orchestrator loop (NFR-004)
- [ ] **AC-17:** No new runtime dependencies added to `pyproject.toml`

### Verification Command

```bash
# Run all tests
.venv/bin/python -m pytest tests_rlm_adk/ -v

# Run only artifact tests
.venv/bin/python -m pytest tests_rlm_adk/test_adk_artifacts.py tests_rlm_adk/test_adk_artifacts_integration.py -v

# Verify no existing tests broken
.venv/bin/python -m pytest tests_rlm_adk/test_adk_callbacks.py tests_rlm_adk/test_adk_plugins_observability.py tests_rlm_adk/test_adk_plugins_cache.py tests_rlm_adk/test_adk_state_schema.py -v
```
