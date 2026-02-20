# Google ADK Artifact API Reference

> Sources:
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/base_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/in_memory_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/gcs_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/file_artifact_service.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/__init__.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/artifact_util.py
> - https://github.com/google/adk-python/blob/main/src/google/adk/plugins/save_files_as_artifacts_plugin.py
> - https://google.github.io/adk-docs/api-reference/python/
> - https://google.github.io/adk-docs/artifacts/

## Module: `google.adk.artifacts`

### Exports (`__all__`)

```python
from google.adk.artifacts import (
    BaseArtifactService,
    FileArtifactService,
    GcsArtifactService,
    InMemoryArtifactService,
)
```

---

## Class: `ArtifactVersion`

**Module:** `google.adk.artifacts.base_artifact_service`
**Base class:** `pydantic.BaseModel`

Metadata describing a specific version of an artifact.

### Model Configuration

```python
model_config = ConfigDict(
    alias_generator=alias_generators.to_camel,
    populate_by_name=True,
)
```

Uses camelCase aliases for JSON serialization (e.g., `canonical_uri` serializes as `canonicalUri`).

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | `int` | (required) | Monotonically increasing identifier for the artifact version |
| `canonical_uri` | `str` | (required) | Canonical URI referencing the persisted artifact payload |
| `custom_metadata` | `dict[str, Any]` | `{}` | Optional user-supplied metadata stored with the artifact |
| `create_time` | `float` | `datetime.now().timestamp()` | Unix timestamp (seconds) when the version record was created |
| `mime_type` | `Optional[str]` | `None` | MIME type when the artifact payload is stored as binary data |

---

## Class: `BaseArtifactService` (Abstract)

**Module:** `google.adk.artifacts.base_artifact_service`
**Base classes:** `ABC`

Abstract base class defining the artifact persistence contract. All methods are abstract and async.

### Method: `save_artifact()`

```python
@abstractmethod
async def save_artifact(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    artifact: types.Part,
    session_id: Optional[str] = None,
    custom_metadata: Optional[dict[str, Any]] = None,
) -> int
```

Saves an artifact to the artifact service storage.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `filename` | `str` | Yes | The filename identifier for the artifact |
| `artifact` | `types.Part` | Yes | The artifact data. If `file_data`, content assumed uploaded separately |
| `session_id` | `Optional[str]` | No | The session ID. If `None`, artifact is user-scoped |
| `custom_metadata` | `Optional[dict[str, Any]]` | No | Custom metadata to associate with the artifact |

**Returns:** `int` -- The revision ID. First version is 0, incremented by 1 after each save.

### Method: `load_artifact()`

```python
@abstractmethod
async def load_artifact(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional[types.Part]
```

Retrieves an artifact from the artifact service storage.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `filename` | `str` | Yes | The filename of the artifact |
| `session_id` | `Optional[str]` | No | The session ID. If `None`, loads user-scoped artifact |
| `version` | `Optional[int]` | No | Specific version. If `None`, returns latest |

**Returns:** `Optional[types.Part]` -- The artifact data, or `None` if not found.

### Method: `list_artifact_keys()`

```python
@abstractmethod
async def list_artifact_keys(
    self,
    *,
    app_name: str,
    user_id: str,
    session_id: Optional[str] = None,
) -> list[str]
```

Lists all artifact filenames within a scope.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `session_id` | `Optional[str]` | No | The session ID |

**Returns:** `list[str]` -- Artifact filenames. If `session_id` provided, returns both session-scoped and user-scoped filenames. If `None`, returns only user-scoped filenames. Results are sorted.

### Method: `delete_artifact()`

```python
@abstractmethod
async def delete_artifact(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
) -> None
```

Deletes an artifact and all its versions.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `filename` | `str` | Yes | The artifact filename |
| `session_id` | `Optional[str]` | No | The session ID. If `None`, deletes user-scoped artifact |

**Returns:** `None`

### Method: `list_versions()`

```python
@abstractmethod
async def list_versions(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
) -> list[int]
```

Lists all version numbers of an artifact.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `filename` | `str` | Yes | The artifact filename |
| `session_id` | `Optional[str]` | No | The session ID. If `None`, lists user-scoped artifact versions |

**Returns:** `list[int]` -- List of all available version numbers (e.g., `[0, 1, 2]`).

### Method: `list_artifact_versions()`

```python
@abstractmethod
async def list_artifact_versions(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
) -> list[ArtifactVersion]
```

Lists all versions with full metadata for a specific artifact.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `filename` | `str` | Yes | The artifact filename |
| `session_id` | `Optional[str]` | No | The session ID. If `None`, lists user-scoped versions |

**Returns:** `list[ArtifactVersion]` -- List of `ArtifactVersion` objects with metadata.

### Method: `get_artifact_version()`

```python
@abstractmethod
async def get_artifact_version(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional[ArtifactVersion]
```

Gets metadata for a specific version of an artifact.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | The application name |
| `user_id` | `str` | Yes | The user ID |
| `filename` | `str` | Yes | The artifact filename |
| `session_id` | `Optional[str]` | No | The session ID. If `None`, fetches from user-scoped artifacts |
| `version` | `Optional[int]` | No | Version number. If `None`, returns latest version |

**Returns:** `Optional[ArtifactVersion]` -- Metadata for the version, or `None` if not found.

---

## Class: `InMemoryArtifactService`

**Module:** `google.adk.artifacts.in_memory_artifact_service`
**Base classes:** `BaseArtifactService`, `pydantic.BaseModel`

In-memory artifact service implementation. Not suitable for multi-threaded production environments.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `artifacts` | `dict[str, list[_ArtifactEntry]]` | `{}` | Dictionary mapping path strings to versioned artifact entries |

### Internal Class: `_ArtifactEntry`

```python
@dataclasses.dataclass
class _ArtifactEntry:
    data: types.Part               # The actual artifact data
    artifact_version: ArtifactVersion  # Metadata about this version
```

### Methods

All `BaseArtifactService` abstract methods are implemented:

- `save_artifact()` -- Appends new `_ArtifactEntry` to the list at the path key. Returns `len(existing_list)` as version.
- `load_artifact()` -- Indexes into list by version (or -1 for latest). Follows `artifact://` references recursively.
- `list_artifact_keys()` -- Scans dictionary keys by prefix. Returns sorted list.
- `delete_artifact()` -- Pops the path key from the dictionary.
- `list_versions()` -- Returns `list(range(len(entries)))`.
- `list_artifact_versions()` -- Returns `[entry.artifact_version for entry in entries]`.
- `get_artifact_version()` -- Indexes into entries and returns `artifact_version` field.

### Private Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `_file_has_user_namespace()` | `(filename: str) -> bool` | Checks if filename starts with `"user:"` |
| `_artifact_path()` | `(app_name, user_id, filename, session_id) -> str` | Constructs storage path key |

### Path Format

- Session-scoped: `"{app_name}/{user_id}/{session_id}/{filename}"`
- User-scoped: `"{app_name}/{user_id}/user/{filename}"`

### Canonical URI Format

- Session-scoped: `"memory://apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{filename}/versions/{version}"`
- User-scoped: `"memory://apps/{app_name}/users/{user_id}/artifacts/{filename}/versions/{version}"`

### Error Handling

- `InputValidationError` if `session_id` is `None` for non-user-scoped artifacts
- `InputValidationError` for unsupported artifact types (no `inline_data`, `text`, or `file_data`)
- `InputValidationError` for invalid artifact reference URIs
- Returns `None` for `IndexError` on version access

---

## Class: `FileArtifactService`

**Module:** `google.adk.artifacts.file_artifact_service`
**Base class:** `BaseArtifactService`

Filesystem-backed artifact storage with hierarchical directory organization.

### Constructor

```python
def __init__(self, root_dir: Path | str)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `root_dir` | `Path \| str` | Yes | Root directory for artifact storage. Created if it does not exist. |

### Directory Structure

```
root_dir/
+-- users/
    +-- {user_id}/
        +-- sessions/
        |   +-- {session_id}/
        |       +-- artifacts/
        |           +-- {filename}/
        |               +-- versions/
        |                   +-- {version}/
        |                       +-- payload
        |                       +-- metadata.json
        +-- artifacts/
            +-- {filename}/
                +-- versions/...
```

### Methods

All `BaseArtifactService` abstract methods are implemented. Each async method delegates to a synchronous `_*_sync()` counterpart via `asyncio.to_thread()`.

### Private Methods

| Method | Description |
|--------|-------------|
| `_base_root(user_id)` | Returns user's artifacts root path |
| `_scope_root(user_id, session_id, filename)` | Determines session vs user scope |
| `_artifact_dir(user_id, session_id, filename)` | Builds full artifact directory path |
| `_canonical_uri(user_id, session_id, filename, version)` | Generates `file://` URIs |
| `_write_metadata()` | Persists `FileArtifactVersion` as JSON |
| `_read_metadata()` | Loads and validates metadata from JSON |

### Security Features

- Rejects absolute paths in filenames
- Validates resolved paths remain within the root directory scope
- Prevents directory traversal attacks
- Strips user namespace prefixes for filesystem storage
- Converts Windows paths to POSIX format

---

## Class: `GcsArtifactService`

**Module:** `google.adk.artifacts.gcs_artifact_service`
**Base class:** `BaseArtifactService`

Google Cloud Storage-backed artifact service for production deployments.

### Constructor

```python
def __init__(self, bucket_name: str, **kwargs)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bucket_name` | `str` | Yes | GCS bucket name |
| `**kwargs` | `Any` | No | Passed to `google.cloud.storage.Client()` |

### Instance Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `bucket_name` | `str` | GCS bucket name |
| `storage_client` | `storage.Client` | Google Cloud Storage client |
| `bucket` | `storage.Bucket` | Bucket handle |

### Dependencies

Requires `google-cloud-storage` package (lazy-imported in constructor).

### Methods

All `BaseArtifactService` abstract methods are implemented. Each async method delegates to a synchronous counterpart via `asyncio.to_thread()`.

### Async/Sync Method Mapping

| Async Method | Sync Implementation |
|-------------|-------------------|
| `save_artifact()` | `_save_artifact()` |
| `load_artifact()` | `_load_artifact()` |
| `list_artifact_keys()` | `_list_artifact_keys()` |
| `delete_artifact()` | `_delete_artifact()` |
| `list_versions()` | `_list_versions()` |
| `list_artifact_versions()` | `_list_artifact_versions_sync()` |
| `get_artifact_version()` | `_get_artifact_version_sync()` |

### Private Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `_file_has_user_namespace()` | `(filename: str) -> bool` | Checks `"user:"` prefix |
| `_get_blob_prefix()` | `(app_name, user_id, filename, session_id) -> str` | Constructs blob path without version |
| `_get_blob_name()` | `(app_name, user_id, filename, version, session_id) -> str` | Constructs full blob path with version |

### Blob Naming

- Session-scoped: `"{app_name}/{user_id}/{session_id}/{filename}/{version}"`
- User-scoped: `"{app_name}/{user_id}/user/{filename}/{version}"`

### Canonical URI Format

`"gs://{bucket_name}/{blob_name}"`

### Limitations

- `file_data` artifacts raise `NotImplementedError` in `_save_artifact()`
- Custom metadata values are converted to strings (`str(v)`) for GCS blob metadata

### CLI Integration

```bash
adk web --artifact_service_uri="gs://{bucket_name}"
```

---

## Module: `google.adk.artifacts.artifact_util`

Utility functions for handling artifact URIs.

### Class: `ParsedArtifactUri`

```python
class ParsedArtifactUri(NamedTuple):
    app_name: str
    user_id: str
    session_id: Optional[str]
    filename: str
    version: int
```

### Function: `parse_artifact_uri()`

```python
def parse_artifact_uri(uri: str) -> Optional[ParsedArtifactUri]
```

Parses an `artifact://` URI into its components.

**Parameters:**
- `uri` (`str`) -- The URI string to parse

**Returns:** `Optional[ParsedArtifactUri]` -- Parsed components, or `None` if invalid/not an artifact URI.

**Supported URI patterns:**
- Session-scoped: `artifact://apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{filename}/versions/{version}`
- User-scoped: `artifact://apps/{app_name}/users/{user_id}/artifacts/{filename}/versions/{version}`

### Function: `get_artifact_uri()`

```python
def get_artifact_uri(
    app_name: str,
    user_id: str,
    filename: str,
    version: int,
    session_id: Optional[str] = None,
) -> str
```

Constructs an `artifact://` URI from components.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `app_name` | `str` | Yes | Application name |
| `user_id` | `str` | Yes | User ID |
| `filename` | `str` | Yes | Artifact filename |
| `version` | `int` | Yes | Version number |
| `session_id` | `Optional[str]` | No | Session ID. Omit for user-scoped |

**Returns:** `str` -- Formatted artifact URI.

### Function: `is_artifact_ref()`

```python
def is_artifact_ref(artifact: types.Part) -> bool
```

Checks if a `types.Part` object is an artifact reference (contains `file_data` with an `artifact://` URI).

**Parameters:**
- `artifact` (`types.Part`) -- The part to check

**Returns:** `bool` -- `True` if the part contains a `file_data.file_uri` starting with `"artifact://"`.

---

## Integration Points

### Runner

```python
from google.adk.runners import Runner

runner = Runner(
    agent=my_agent,
    app_name="my_app",
    session_service=session_service,
    artifact_service=artifact_service,  # Optional[BaseArtifactService]
)
```

The `Runner` stores the artifact service and propagates it to `InvocationContext`.

### InvocationContext

```python
class InvocationContext:
    artifact_service: Optional[BaseArtifactService]  # Service reference
    artifact_delta: dict[str, int]  # Tracks filename -> version changes
```

### EventActions

```python
class EventActions:
    artifact_delta: dict[str, int]  # Maps filename -> version for event tracking
```

### CallbackContext

Methods available on `CallbackContext` (and `ToolContext` which extends it):

```python
# Save artifact -- returns version number
version: int = context.save_artifact(filename: str, artifact: types.Part)

# Load artifact -- returns Part or None
artifact: Optional[types.Part] = context.load_artifact(filename: str, version: Optional[int] = None)

# List artifacts (ToolContext only)
filenames: list[str] = context.list_artifacts()
```

### Session

Artifacts are scoped to sessions but stored externally. The session tracks artifact state through events' `artifact_delta` fields.

---

## Class: `SaveFilesAsArtifactsPlugin`

**Module:** `google.adk.plugins.save_files_as_artifacts_plugin`
**Base class:** `BasePlugin`

Automatically saves files embedded in user messages as artifacts.

### Constructor

```python
def __init__(self, name: str = "save_files_as_artifacts_plugin")
```

### Method: `on_user_message_callback()`

```python
async def on_user_message_callback(
    self,
    *,
    invocation_context: InvocationContext,
    user_message: types.Content,
) -> Optional[types.Content]
```

Processes user messages, saves inline data as artifacts, and replaces them with placeholders.

**Behavior:**
1. Skips if no `artifact_service` is configured (logs warning)
2. Iterates through message parts
3. For each part with `inline_data`:
   - Uses `display_name` or generates `artifact_{invocation_id}_{index}`
   - Saves via `artifact_service.save_artifact()`
   - Replaces with text placeholder: `[Uploaded Artifact: "{display_name}"]`
   - Adds file reference Part if URI is model-accessible (`gs://`, `https://`, `http://`)
4. Returns modified `Content` if any changes, `None` otherwise

### Private Method: `_build_file_reference_part()`

```python
async def _build_file_reference_part(
    self,
    *,
    invocation_context: InvocationContext,
    filename: str,
    version: int,
    mime_type: Optional[str],
    display_name: str,
) -> Optional[types.Part]
```

Constructs a `file_data` Part with the artifact's canonical URI if it uses a model-accessible scheme.

### Module-level Function: `_is_model_accessible_uri()`

```python
def _is_model_accessible_uri(uri: str) -> bool
```

Returns `True` if the URI scheme is in `{'gs', 'https', 'http'}`.

---

## Configuration Options Summary

### Runner-Level

| Parameter | Type | Description |
|-----------|------|-------------|
| `artifact_service` | `Optional[BaseArtifactService]` | Storage backend instance |

### CLI Options

| Flag | Description |
|------|-------------|
| `--artifact_service_uri="gs://bucket"` | Use GCS backend |
| `--artifact_service_uri="memory://"` | Use in-memory backend |

### Environment Variables

| Variable | Effect |
|----------|--------|
| `ADK_DISABLE_LOCAL_STORAGE=1` | Force in-memory storage |
| `ADK_FORCE_LOCAL_STORAGE=1` | Force file storage in cloud |
| `K_SERVICE` | Cloud Run auto-detection (defaults to in-memory) |
| `KUBERNETES_SERVICE_HOST` | Kubernetes auto-detection (defaults to in-memory) |

---

## Error Types

| Error | Module | Raised When |
|-------|--------|-------------|
| `InputValidationError` | `google.adk.errors` | Missing `session_id` for session-scoped artifacts; unsupported artifact type; invalid artifact URI |
| `ValueError` | built-in | Artifact methods called without configured service |
| `NotImplementedError` | built-in | `file_data` artifacts in `GcsArtifactService` |

---

## Type Reference

### `google.genai.types.Part`

The standard container for artifact data. Key constructors:

```python
# From bytes
part = types.Part.from_bytes(data=b"...", mime_type="application/pdf")

# From inline data
part = types.Part(inline_data=types.Blob(mime_type="image/png", data=b"..."))

# From text
part = types.Part(text="plain text content")

# From file reference
part = types.Part(file_data=types.FileData(file_uri="gs://...", mime_type="..."))
```

### Accessing artifact data:

```python
# Binary data
if artifact.inline_data:
    data: bytes = artifact.inline_data.data
    mime: str = artifact.inline_data.mime_type

# Text data
if artifact.text:
    content: str = artifact.text

# File reference
if artifact.file_data:
    uri: str = artifact.file_data.file_uri
    mime: str = artifact.file_data.mime_type
```
