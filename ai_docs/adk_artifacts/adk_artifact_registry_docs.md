# Google ADK Artifact Registry Pattern Documentation

> Sources:
> - https://google.github.io/adk-docs/artifacts/
> - https://deepwiki.com/google/adk-python/7.4-artifact-storage
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/__init__.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/artifact_util.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/plugins/save_files_as_artifacts_plugin.py

## Overview

The ADK artifact "registry" is not a standalone registry class but rather a pattern implemented through the combination of:
1. The **ArtifactService** abstraction (storage backend)
2. **Naming conventions** (filename strings with optional namespace prefixes)
3. **Context-mediated access** (ToolContext/CallbackContext methods)
4. **Event-driven tracking** (artifact_delta in EventActions)

Agents register artifacts by saving them through the artifact service, and discover artifacts by listing available keys. The Runner coordinates the service, making it available to agents and tools via the InvocationContext.

## How Agents Register Artifacts

### Saving (Registering) Artifacts

Agents and tools register artifacts by calling `save_artifact()` on their context object:

```python
async def generate_report(data: str, tool_context: ToolContext) -> dict:
    report_bytes = create_pdf(data)
    artifact = types.Part.from_bytes(data=report_bytes, mime_type="application/pdf")

    # Register the artifact -- returns version number
    version = tool_context.save_artifact(
        filename="analysis_report.pdf",
        artifact=artifact
    )
    return {"status": "registered", "version": version}
```

The artifact is keyed by `(app_name, user_id, session_id, filename)`. Subsequent saves with the same filename create new versions, not new entries.

### Automatic Registration via Plugin

The `SaveFilesAsArtifactsPlugin` automatically registers user-uploaded files:

```python
from google.adk.plugins import SaveFilesAsArtifactsPlugin

# Plugin auto-registers files from user messages
plugin = SaveFilesAsArtifactsPlugin(name="save_files_as_artifacts_plugin")
```

When a user sends a message containing inline binary data, the plugin:
1. Extracts the `display_name` from `inline_data` (or generates one: `artifact_{invocation_id}_{index}`)
2. Saves the data through `artifact_service.save_artifact()`
3. Replaces inline data with a text placeholder and optional file reference
4. Logs success/failure for each artifact

## How Agents Discover Artifacts

### Listing Available Artifacts

```python
async def find_files(tool_context: ToolContext) -> dict:
    filenames = tool_context.list_artifacts()
    return {"available_artifacts": filenames}
```

The `list_artifact_keys()` method on the underlying service returns:
- If `session_id` is provided: both session-scoped AND user-scoped artifact filenames
- If `session_id` is `None`: only user-scoped artifact filenames

Results are returned sorted alphabetically.

### Loading a Specific Artifact

```python
artifact = tool_context.load_artifact(filename="analysis_report.pdf")
if artifact and artifact.inline_data:
    data = artifact.inline_data.data  # bytes
    mime = artifact.inline_data.mime_type
```

### Version Discovery

At the service level (not exposed via context objects directly):

```python
# List version numbers
versions = await artifact_service.list_versions(
    app_name="my_app", user_id="user1",
    filename="report.pdf", session_id="session1"
)
# Returns: [0, 1, 2]

# List versions with metadata
artifact_versions = await artifact_service.list_artifact_versions(
    app_name="my_app", user_id="user1",
    filename="report.pdf", session_id="session1"
)
# Returns: [ArtifactVersion(version=0, ...), ArtifactVersion(version=1, ...), ...]

# Get specific version metadata
version_info = await artifact_service.get_artifact_version(
    app_name="my_app", user_id="user1",
    filename="report.pdf", session_id="session1",
    version=1
)
# Returns: ArtifactVersion or None
```

## Artifact Naming Conventions and Namespacing

### Filename Rules

- Filenames are plain strings (e.g., `"report.pdf"`, `"data.csv"`)
- Must be unique within their scope (app + user + session, or app + user for user-scoped)
- Should include file extensions for clarity and MIME type consistency
- Must not contain path traversal characters (`..`, absolute paths) -- the `FileArtifactService` enforces this

### Namespace Prefixes

| Prefix | Scope | Storage Path (InMemory) | Lifetime |
|--------|-------|------------------------|----------|
| (none) | Session | `{app}/{user}/{session}/{filename}` | Single session |
| `user:` | User | `{app}/{user}/user/{filename}` | Across all user sessions |

Examples:
```python
# Session-scoped -- only available in current session
tool_context.save_artifact(filename="temp_chart.png", artifact=chart_part)

# User-scoped -- available across all sessions for this user
tool_context.save_artifact(filename="user:preferences.json", artifact=prefs_part)
```

### Artifact URI Scheme

ADK uses a custom `artifact://` URI scheme for internal references:

```
# Session-scoped artifact URI
artifact://apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{filename}/versions/{version}

# User-scoped artifact URI
artifact://apps/{app_name}/users/{user_id}/artifacts/{filename}/versions/{version}
```

These URIs are used internally for artifact cross-references (e.g., when one artifact references another). The `is_artifact_ref()` function detects these references, and `parse_artifact_uri()` extracts the components.

### Canonical URIs by Backend

Each storage backend generates its own canonical URI format:

| Backend | URI Pattern | Example |
|---------|-------------|---------|
| InMemory | `memory://apps/{app}/users/{user}/...` | `memory://apps/myapp/users/u1/sessions/s1/artifacts/report.pdf/versions/0` |
| File | `file://{absolute_path}` | `file:///home/user/.adk/artifacts/users/u1/sessions/s1/artifacts/report.pdf/versions/0/payload` |
| GCS | `gs://{bucket}/{blob}` | `gs://my-bucket/myapp/u1/s1/report.pdf/0` |

## Registry Lifecycle Management

### Initialization

The artifact registry (service) is initialized at Runner creation time:

```python
runner = Runner(
    agent=my_agent,
    app_name="my_app",
    session_service=session_service,
    artifact_service=InMemoryArtifactService()  # Registry is ready
)
```

The service is then propagated to agents through `InvocationContext.artifact_service`.

### Runtime Tracking via artifact_delta

During execution, the ADK event system tracks artifact changes:

```python
# EventActions field
artifact_delta: dict[str, int]  # Maps filename -> version number
```

Each time an artifact is saved, the delta is recorded in the event's `EventActions.artifact_delta`. The `SessionService` applies these deltas after each invocation step.

### Session Rewind and Artifact State

When a session is rewound to a previous point:

1. The Runner computes `versions_at_rewind_point` by scanning events up to the rewind index
2. Compares with current artifact versions
3. Creates new artifact versions to restore state at the rewind point
4. Records restoration in `artifact_delta` for the rewind event

This ensures artifact state is consistent with conversation state after rewind.

### Deletion

Artifacts can be deleted at the service level:

```python
await artifact_service.delete_artifact(
    app_name="my_app",
    user_id="user1",
    filename="old_report.pdf",
    session_id="session1"
)
```

- `InMemoryArtifactService`: Removes the entry from the dictionary
- `GcsArtifactService`: Deletes all version blobs from GCS
- `FileArtifactService`: Removes files and cleans up directories

Note: Delete is available on the service but is NOT exposed through `ToolContext` or `CallbackContext`. Direct service access is required.

### Cleanup Strategies

- **InMemoryArtifactService**: No cleanup needed (data lost on process termination)
- **FileArtifactService**: Manual file cleanup or OS-level scheduled tasks
- **GcsArtifactService**: Use GCS lifecycle policies for automatic expiration, or call `delete_artifact()` programmatically

### Service Factory and URI Resolution

The ADK CLI and web server use a factory pattern to resolve artifact service URIs:

| URI | Resolution |
|-----|-----------|
| `gs://bucket-name` | `GcsArtifactService(bucket_name="bucket-name")` |
| `memory://` | `InMemoryArtifactService()` |
| `None` / default | `FileArtifactService` (if writable) or `InMemoryArtifactService` (fallback) |

Environment variable overrides:
- `ADK_DISABLE_LOCAL_STORAGE=1` -- bypass file storage, use in-memory
- `ADK_FORCE_LOCAL_STORAGE=1` -- force file storage even in cloud environments
- `K_SERVICE` / `KUBERNETES_SERVICE_HOST` -- auto-detect cloud, default to in-memory

### DotAdkFolder Management

For local development, the `DotAdkFolder` class manages artifact paths:

| Property | Path |
|----------|------|
| `dot_adk_dir` | `<agent_dir>/.adk` |
| `artifacts_dir` | `<agent_dir>/.adk/artifacts` |
| `session_db_path` | `<agent_dir>/.adk/session.db` |

Built-in agents (names starting with `__`) store artifacts in the root `.adk` directory rather than per-agent directories.

## Multi-Agent Artifact Sharing

In multi-agent systems:
- Artifacts are scoped to `(app_name, user_id, session_id)` -- all agents in the same session share the same artifact namespace
- An artifact saved by one agent is accessible to other agents in the same session via `load_artifact()`
- User-scoped artifacts (`"user:"` prefix) are accessible across all sessions for the same user, regardless of which agent saved them
- Transfer between agents (via `EventActions.transfer`) preserves artifact access since the session context is shared
