# Google ADK ArtifactService Documentation

> Sources:
> - https://google.github.io/adk-docs/artifacts/
> - https://google.github.io/adk-docs/api-reference/python/
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/base_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/in_memory_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/gcs_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/file_artifact_service.py
> - https://deepwiki.com/google/adk-python/7.4-artifact-storage

## Overview

The ADK Artifact system provides a pluggable persistence layer for managing named, versioned binary data associated with agent sessions or users. It enables agents and tools to handle data beyond simple text strings -- files, images, audio, PDFs, and other binary formats -- without inflating session history or consuming LLM context window space.

Artifacts are stored **separately** from conversation events and session state. Their storage and retrieval are managed by a dedicated **Artifact Service** (an implementation of `BaseArtifactService`).

## Core Concepts

### What is an Artifact?

An artifact is a piece of binary data (like the content of a file) identified by:
- A unique **filename** string within a specific scope
- An automatically assigned integer **version** number (starting at 0)

Artifacts are represented as `google.genai.types.Part` objects containing inline binary data:

```python
from google.genai import types

# Create an artifact from bytes
artifact = types.Part.from_bytes(
    data=binary_bytes,
    mime_type="application/pdf"
)

# Or construct manually
artifact = types.Part(
    inline_data=types.Blob(
        mime_type="application/pdf",
        data=binary_bytes
    )
)
```

### Scoping: Session vs. User

Artifacts support two scoping strategies:

| Scope | Filename Pattern | Storage Key | Use Case |
|-------|-----------------|-------------|----------|
| **Session-scoped** | `"report.pdf"` (plain filename) | `(app_name, user_id, session_id, filename)` | Temporary conversation files, single-session data |
| **User-scoped** | `"user:settings.json"` (prefixed with `user:`) | `(app_name, user_id, filename)` | Cross-session persistence, user preferences |

- Session-scoped artifacts require a `session_id` parameter.
- User-scoped artifacts (filenames starting with `"user:"`) omit `session_id` and are accessible across all sessions for that user.

### Versioning

- Each call to `save_artifact()` with the same filename creates a **new version** (0, 1, 2, ...).
- `load_artifact()` without a `version` parameter retrieves the **latest** version.
- `load_artifact(version=N)` retrieves a specific version N.
- The service tracks all versions. You can list versions via `list_versions()` and `list_artifact_versions()`.

## The BaseArtifactService Abstract Class

`BaseArtifactService` (in `google.adk.artifacts.base_artifact_service`) is the abstract base class defining the artifact persistence contract. All implementations must provide the following async methods:

| Method | Purpose | Returns |
|--------|---------|---------|
| `save_artifact()` | Store a new version of an artifact | `int` (version number) |
| `load_artifact()` | Retrieve artifact data by name/version | `Optional[types.Part]` |
| `list_artifact_keys()` | List all artifact filenames in scope | `list[str]` |
| `delete_artifact()` | Remove an artifact and all its versions | `None` |
| `list_versions()` | List version numbers for an artifact | `list[int]` |
| `list_artifact_versions()` | List versions with full metadata | `list[ArtifactVersion]` |
| `get_artifact_version()` | Get metadata for a specific version | `Optional[ArtifactVersion]` |

### ArtifactVersion Model

`ArtifactVersion` is a Pydantic `BaseModel` that stores metadata about a specific artifact version:

```python
class ArtifactVersion(BaseModel):
    version: int                          # Monotonically increasing version ID
    canonical_uri: str                    # URI referencing the persisted payload
    custom_metadata: dict[str, Any] = {}  # Optional user-supplied metadata
    create_time: float                    # Unix timestamp (seconds)
    mime_type: Optional[str] = None       # MIME type of the binary payload
```

The model uses camelCase alias generation for JSON serialization (`model_config` with `alias_generator=alias_generators.to_camel`).

## Available Implementations

### 1. InMemoryArtifactService

**Module:** `google.adk.artifacts.in_memory_artifact_service`

Stores artifacts in a Python dictionary in memory. Suitable for testing and development only.

```python
from google.adk.artifacts import InMemoryArtifactService

artifact_service = InMemoryArtifactService()
```

**Characteristics:**
- Inherits from both `BaseArtifactService` and Pydantic `BaseModel`
- Storage: `dict[str, list[_ArtifactEntry]]` where keys are path strings
- Path format: `"{app_name}/{user_id}/{session_id}/{filename}"` (session-scoped) or `"{app_name}/{user_id}/user/{filename}"` (user-scoped)
- Canonical URI format: `"memory://apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{filename}/versions/{version}"`
- All data is lost when the process terminates
- Not suitable for multi-threaded production environments
- Automatically used by `InMemoryRunner`

**Internal data structure:**
```python
@dataclasses.dataclass
class _ArtifactEntry:
    data: types.Part               # The actual artifact data
    artifact_version: ArtifactVersion  # Version metadata
```

**When auto-selected:**
- `use_local_storage=False` is specified
- Local storage initialization fails (permission errors)
- Running in Cloud Run (`K_SERVICE` env var) or Kubernetes (`KUBERNETES_SERVICE_HOST` env var)
- `ADK_DISABLE_LOCAL_STORAGE=1` environment variable is set

### 2. FileArtifactService

**Module:** `google.adk.artifacts.file_artifact_service`

Stores artifacts as files on the local filesystem. Default for local development when the agents directory is writable.

```python
from google.adk.artifacts import FileArtifactService

artifact_service = FileArtifactService(root_dir="/path/to/storage")
```

**Characteristics:**
- Constructor takes a `root_dir: Path | str` parameter
- Directory structure:
  ```
  root/
  +-- users/
      +-- {user_id}/
          +-- sessions/
          |   +-- {session_id}/
          |       +-- artifacts/
          |           +-- {filename}/
          |               +-- versions/
          |                   +-- {version}/
          |                       +-- payload (binary data)
          |                       +-- metadata.json
          +-- artifacts/
              +-- {filename}/
                  +-- versions/...
  ```
- Canonical URI format: `"file://..."`
- Includes path traversal attack prevention (rejects absolute paths, validates resolved paths stay in scope)
- All async methods delegate to synchronous `_*_sync()` implementations via `asyncio.to_thread()`
- Stores metadata as JSON alongside payload via `FileArtifactVersion` Pydantic model
- Default location: `.adk/artifacts/` under the agent directory

**Default auto-selection:**
- Used during local development when the agents directory is writable
- Default when no URI is specified and local storage is available

### 3. GcsArtifactService

**Module:** `google.adk.artifacts.gcs_artifact_service`

Stores artifacts in Google Cloud Storage buckets. Recommended for production deployments.

```python
from google.adk.artifacts import GcsArtifactService

artifact_service = GcsArtifactService(bucket_name="my-adk-artifacts-bucket")
```

**Characteristics:**
- Constructor: `__init__(self, bucket_name: str, **kwargs)` -- kwargs passed to `google.cloud.storage.Client`
- Requires `google-cloud-storage` package
- Blob naming: `"{app_name}/{user_id}/{session_id}/{filename}/{version}"` (session-scoped) or `"{app_name}/{user_id}/user/{filename}/{version}"` (user-scoped)
- Canonical URI format: `"gs://{bucket_name}/{blob_name}"`
- All async methods delegate to synchronous GCS operations via `asyncio.to_thread()`
- Requires appropriate IAM permissions and Application Default Credentials
- `file_data` artifacts are not yet supported (`NotImplementedError`)
- CLI usage: `adk web --artifact_service_uri="gs://{bucket_name}"`

**Version management:** Automatically increments by querying existing blobs and computing `max(versions) + 1`.

**Custom metadata:** Stored as GCS blob metadata (all values converted to strings).

## Integration with ADK Agents and Sessions

### Runner Configuration

The artifact service is provided when initializing the `Runner`:

```python
from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService

runner = Runner(
    agent=my_agent,
    app_name="my_app",
    session_service=session_service,
    artifact_service=InMemoryArtifactService()  # Optional but required for artifact operations
)
```

If no artifact service is configured, calling artifact methods on context objects raises `ValueError`.

### Context Methods (ToolContext / CallbackContext)

The primary way to interact with artifacts within agent logic is through `ToolContext` and `CallbackContext`, which abstract away the underlying storage details:

```python
# In a tool function
async def my_tool(query: str, tool_context: ToolContext) -> dict:
    # Save an artifact
    data = b"binary content here"
    artifact = types.Part.from_bytes(data=data, mime_type="application/pdf")
    version = tool_context.save_artifact(filename="report.pdf", artifact=artifact)

    # Load an artifact
    loaded = tool_context.load_artifact(filename="report.pdf")  # Latest version
    loaded_v0 = tool_context.load_artifact(filename="report.pdf", version=0)

    # List all artifacts
    filenames = tool_context.list_artifacts()

    return {"saved_version": version, "available_files": filenames}
```

### InvocationContext Access

The `InvocationContext` holds a direct reference to the `artifact_service` instance. Agent implementations can access it through `invocation_context.artifact_service`, though this is typically delegated to callbacks/tools via the simpler context objects.

### Event System Integration (artifact_delta)

When tools or callbacks invoke `save_artifact()`, the ADK framework tracks these operations through the event system:

- `EventActions.artifact_delta` records artifact changes as `dict[str, int]` mapping filenames to version numbers
- Changes become part of event metadata
- The `SessionService` applies artifact deltas after each invocation step
- During session rewind, the Runner computes `artifact_delta` to restore artifact state at the rewind point

### Service Factory (URI-based Resolution)

ADK includes a factory that resolves service URIs to implementations:

| URI Pattern | Service Type | Example |
|------------|--------------|---------|
| `gs://...` | `GcsArtifactService` | `gs://my-bucket/artifacts` |
| `memory://` | `InMemoryArtifactService` | `memory://` |
| `None` (default) | `FileArtifactService` or `InMemoryArtifactService` | `.adk/artifacts` |

Environment variables controlling defaults:
- `ADK_DISABLE_LOCAL_STORAGE=1` -- forces in-memory storage
- `ADK_FORCE_LOCAL_STORAGE=1` -- forces file storage even in cloud
- `K_SERVICE` (Cloud Run) -- defaults to in-memory
- `KUBERNETES_SERVICE_HOST` -- defaults to in-memory

### SaveFilesAsArtifactsPlugin

ADK provides a built-in plugin (`google.adk.plugins.save_files_as_artifacts_plugin`) that automatically saves files embedded in user messages as artifacts:

```python
from google.adk.plugins import SaveFilesAsArtifactsPlugin

# Add to agent configuration
plugin = SaveFilesAsArtifactsPlugin()
```

The plugin:
1. Intercepts user messages containing `inline_data` parts
2. Saves each file through the artifact service
3. Replaces inline data with text placeholders (`[Uploaded Artifact: "filename"]`)
4. Adds model-accessible file references (for `gs://`, `https://`, `http://` URIs)
5. Falls back gracefully if no artifact service is configured

## Artifact URI System

ADK uses a custom `artifact://` URI scheme for internal artifact references:

```
# Session-scoped
artifact://apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{filename}/versions/{version}

# User-scoped
artifact://apps/{app_name}/users/{user_id}/artifacts/{filename}/versions/{version}
```

Utility functions in `google.adk.artifacts.artifact_util`:
- `parse_artifact_uri(uri: str) -> Optional[ParsedArtifactUri]` -- parses artifact URIs
- `get_artifact_uri(app_name, user_id, filename, version, session_id=None) -> str` -- constructs URIs
- `is_artifact_ref(artifact: types.Part) -> bool` -- checks if a Part references an artifact

The `ParsedArtifactUri` is a `NamedTuple` with fields: `app_name`, `user_id`, `session_id` (Optional), `filename`, `version`.

## Error Handling

1. **Missing service:** Calling artifact methods without a configured service raises `ValueError`
2. **Invalid scope:** Session-scoped artifacts without `session_id` raise `InputValidationError`
3. **Invalid artifact type:** Saving unsupported Part types raises `InputValidationError`
4. **Invalid artifact URI:** Malformed `artifact://` URIs raise `InputValidationError`
5. **GCS errors:** Permission errors, network failures, missing buckets propagate as GCS client exceptions
6. **File system errors:** `FileArtifactService` falls back to in-memory on `PermissionError`, `EACCES`, `EPERM`, `EROFS`

## Best Practices

- Use `InMemoryArtifactService` for dev/test; `GcsArtifactService` for production
- Use descriptive filenames with extensions (e.g., `"monthly_report.pdf"`)
- Always specify accurate MIME types for correct data interpretation
- Use `"user:"` prefix only for genuinely cross-session user data
- Implement cleanup strategies for persistent backends (GCS lifecycle policies)
- Monitor memory consumption with `InMemoryArtifactService` for large/numerous artifacts
- Always validate return values from `load_artifact()` (can return `None`)
- Use the context offloading pattern: store large data as artifacts and inject into LLM requests on-demand rather than keeping in session history
