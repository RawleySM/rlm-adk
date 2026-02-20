# FileArtifactService Reference

> Source: `google.adk.artifacts.file_artifact_service` (ADK v1.25.0)
> Installed at: `.venv/lib/python3.11/site-packages/google/adk/artifacts/file_artifact_service.py`

## Overview

`FileArtifactService` is a filesystem-backed implementation of the `BaseArtifactService` abstract class. It stores artifact payloads as files on disk with a structured directory layout, automatic versioning, and JSON metadata sidecar files. All async methods delegate to synchronous filesystem operations via `asyncio.to_thread()`.

This service exists alongside two other implementations:
- **`InMemoryArtifactService`**: Dictionary-based, no persistence. For testing/development.
- **`GcsArtifactService`**: Google Cloud Storage-backed. For production on GCP.

## Import

```python
from google.adk.artifacts import FileArtifactService
# or
from google.adk.artifacts.file_artifact_service import FileArtifactService
```

`FileArtifactService` is exported from `google.adk.artifacts.__init__`.

---

## BaseArtifactService Interface

All artifact services implement this abstract base class. Understanding the interface is essential before diving into the file-based implementation.

### ArtifactVersion Model

```python
class ArtifactVersion(BaseModel):
    version: int           # Monotonically increasing version identifier (0-based)
    canonical_uri: str     # URI referencing the persisted artifact payload
    custom_metadata: dict[str, Any] = {}  # Optional user-supplied metadata
    create_time: float     # Unix timestamp (seconds), defaults to now
    mime_type: Optional[str] = None       # MIME type for binary artifacts
```

Uses camelCase aliases for JSON serialization (`alias_generator=to_camel`, `populate_by_name=True`).

### Abstract Methods

```python
class BaseArtifactService(ABC):

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
    ) -> int:
        """Saves artifact, returns version number (0-based, incrementing)."""

    @abstractmethod
    async def load_artifact(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Optional[types.Part]:
        """Loads artifact. Returns latest if version is None. Returns None if not found."""

    @abstractmethod
    async def list_artifact_keys(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> list[str]:
        """Lists filenames. If session_id given, includes both session and user-scoped."""

    @abstractmethod
    async def delete_artifact(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Deletes artifact and all its versions."""

    @abstractmethod
    async def list_versions(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: Optional[str] = None,
    ) -> list[int]:
        """Lists all version numbers for an artifact."""

    @abstractmethod
    async def list_artifact_versions(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: Optional[str] = None,
    ) -> list[ArtifactVersion]:
        """Lists ArtifactVersion metadata objects for all versions."""

    @abstractmethod
    async def get_artifact_version(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Optional[ArtifactVersion]:
        """Gets metadata for a specific version. Latest if version is None."""
```

---

## FileArtifactService Constructor

```python
class FileArtifactService(BaseArtifactService):
    def __init__(self, root_dir: Path | str):
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root_dir` | `Path \| str` | (required) | Root directory for artifact storage. Expanded (`~`) and resolved to absolute path. Created if it does not exist (`mkdir(parents=True, exist_ok=True)`). |

### Example

```python
from pathlib import Path
from google.adk.artifacts import FileArtifactService

# String path
service = FileArtifactService(root_dir="./artifact_data")

# Path object
service = FileArtifactService(root_dir=Path("/var/data/artifacts"))

# Home directory expansion
service = FileArtifactService(root_dir="~/agent_artifacts")
```

---

## Storage Layout

```
root_dir/
  users/
    {user_id}/
      artifacts/                           # User-scoped artifacts
        {artifact_path}/                   # Derived from filename
          versions/
            0/
              {original_filename}          # Payload file
              metadata.json                # Version metadata
            1/
              {original_filename}
              metadata.json
      sessions/
        {session_id}/
          artifacts/                       # Session-scoped artifacts
            {artifact_path}/
              versions/
                0/
                  {original_filename}
                  metadata.json
```

### Key details:

- **`{artifact_path}`** is derived from the filename. For `"report.txt"` it is `report.txt`. For `"images/photo.png"` it creates nested directories: `images/photo.png/versions/...`.
- **`{original_filename}`** stored as payload is the final component of the artifact directory name (i.e., `artifact_dir.name`).
- **`app_name` is NOT part of the directory structure**. The `app_name` parameter is accepted by all methods for interface compatibility but is not used in path construction. This means artifacts from different apps sharing the same `root_dir` and `user_id` would collide.

---

## Namespace Scoping

### Session-Scoped (Default)

Plain filenames like `"report.pdf"` are session-scoped. They require a `session_id` and are stored under `users/{user_id}/sessions/{session_id}/artifacts/`.

### User-Scoped

Filenames prefixed with `"user:"` (e.g., `"user:profile.png"`) are user-scoped. The `"user:"` prefix is stripped before path construction. These are stored under `users/{user_id}/artifacts/` and are accessible across all sessions.

The scoping decision:
```python
def _is_user_scoped(session_id: Optional[str], filename: str) -> bool:
    return session_id is None or _file_has_user_namespace(filename)
```

If `session_id` is `None`, the artifact is always treated as user-scoped regardless of the filename prefix.

---

## Method Reference

### `save_artifact`

```python
async def save_artifact(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    artifact: types.Part,
    session_id: Optional[str] = None,
    custom_metadata: Optional[dict[str, Any]] = None,
) -> int:
```

**Behavior**:
1. Resolves the artifact directory from the filename and scope.
2. Discovers existing versions on disk; next version = max + 1 (or 0 if none).
3. Creates `versions/{N}/` directory.
4. Writes payload:
   - `artifact.inline_data` -> binary write via `write_bytes()`
   - `artifact.text` -> text write via `write_text(encoding="utf-8")`
   - Other types -> raises `InputValidationError`
5. Writes `metadata.json` sidecar with `FileArtifactVersion` data.
6. Returns the new version number.

**MIME type handling**:
- Binary (`inline_data`): Uses `artifact.inline_data.mime_type`, defaults to `"application/octet-stream"`.
- Text: Sets `mime_type` to `None` in metadata.

**Filename validation**:
- Absolute paths raise `InputValidationError`.
- Path traversal (e.g., `../../secret.txt`) that escapes the scope root raises `InputValidationError`.
- Windows-style separators (`\`) are converted to POSIX style.
- Empty/dot filenames resolve to `"artifact"`.

**Thread safety**: Runs synchronously via `asyncio.to_thread()`. No file locking is applied. Concurrent saves to the same artifact could race on version number assignment.

### `load_artifact`

```python
async def load_artifact(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional[types.Part]:
```

**Behavior**:
1. Resolves artifact directory.
2. If `version` is `None`, loads the latest (highest version number on disk).
3. If `version` is specified but not found on disk, returns `None`.
4. Reads `metadata.json` to determine MIME type.
5. If the payload file is missing at the expected path, checks `canonical_uri` for an alternate `file://` location.
6. Returns:
   - `types.Part(inline_data=types.Blob(...))` for binary artifacts (when `mime_type` is set).
   - `types.Part(text=...)` for text artifacts (when `mime_type` is `None`).
   - `None` if artifact or version not found.

### `list_artifact_keys`

```python
async def list_artifact_keys(
    self,
    *,
    app_name: str,
    user_id: str,
    session_id: Optional[str] = None,
) -> list[str]:
```

**Behavior**:
- If `session_id` is provided: Lists both session-scoped and user-scoped artifact filenames.
- If `session_id` is `None`: Lists only user-scoped artifact filenames.
- Filenames are recovered from `metadata.json` when available, falling back to the relative directory path.
- User-scoped artifacts discovered without metadata get the `"user:"` prefix prepended.
- Returns a sorted, deduplicated list.

**Discovery mechanism**: Walks the directory tree looking for directories that contain a `versions/` subdirectory (`_iter_artifact_dirs`).

### `delete_artifact`

```python
async def delete_artifact(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
) -> None:
```

**Behavior**: Recursively deletes the entire artifact directory (`shutil.rmtree`), removing all versions and metadata. No-op if the directory does not exist.

### `list_versions`

```python
async def list_versions(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
) -> list[int]:
```

**Behavior**: Scans `versions/` subdirectories, parses directory names as integers, and returns a sorted list. Non-integer directory names are silently skipped.

### `list_artifact_versions`

```python
async def list_artifact_versions(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
) -> list[ArtifactVersion]:
```

**Behavior**: For each version on disk, reads `metadata.json` and constructs an `ArtifactVersion` object. If metadata is missing or corrupt, falls back to generating a canonical URI from the file path.

### `get_artifact_version`

```python
async def get_artifact_version(
    self,
    *,
    app_name: str,
    user_id: str,
    filename: str,
    session_id: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional[ArtifactVersion]:
```

**Behavior**: Returns metadata for a specific version (or latest if `version` is `None`). Returns `None` if no versions exist or the requested version is not found.

---

## FileArtifactVersion Model

The metadata sidecar extends `ArtifactVersion`:

```python
class FileArtifactVersion(ArtifactVersion):
    file_name: str  # Original filename supplied by the caller
```

Serialized to `metadata.json` with camelCase aliases:

```json
{
  "version": 0,
  "canonicalUri": "file:///absolute/path/to/versions/0/report.txt",
  "fileName": "report.txt",
  "mimeType": "application/pdf",
  "customMetadata": {},
  "createTime": 1708444800.0
}
```

Metadata read failures (validation errors, invalid JSON) are logged as warnings and return `None`, allowing graceful degradation.

---

## Canonical URIs

`FileArtifactService` generates `file://` URIs for artifact payloads:

```
file:///home/user/artifacts/users/user_123/sessions/sess_1/artifacts/report.txt/versions/0/report.txt
```

These URIs are stored in `metadata.json` and can be used as fallback paths when loading artifacts if the primary payload path is missing.

---

## Version Management

- Versions start at **0** and increment by 1 with each save.
- Version numbers are derived from on-disk directory names under `versions/`.
- The next version is calculated as `max(existing_versions) + 1`.
- There is **no locking** on version assignment. Concurrent saves could produce duplicate version numbers or skip numbers if a race occurs.
- Deleting an artifact removes all versions atomically (`shutil.rmtree`).
- There is no mechanism to delete individual versions.

---

## Interaction with Sessions

Artifacts interact with sessions through the `Runner` and `CallbackContext`:

```python
from google.adk.runners import Runner
from google.adk.artifacts import FileArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService

session_service = SqliteSessionService(db_path="./sessions.db")
artifact_service = FileArtifactService(root_dir="./artifacts")

runner = Runner(
    agent=my_agent,
    app_name="my_app",
    session_service=session_service,
    artifact_service=artifact_service,
)
```

Within agent tool functions, artifacts are accessed via context:

```python
from google.genai import types

async def my_tool(context):
    # Save a session-scoped artifact
    version = await context.save_artifact(
        filename="output.txt",
        artifact=types.Part(text="Hello, world!"),
    )

    # Save a user-scoped artifact (accessible across sessions)
    version = await context.save_artifact(
        filename="user:profile.json",
        artifact=types.Part.from_bytes(
            data=json.dumps(profile).encode(),
            mime_type="application/json",
        ),
    )

    # Load latest version
    part = await context.load_artifact(filename="output.txt")

    # Load specific version
    part = await context.load_artifact(filename="output.txt", version=0)

    # List all artifact filenames
    keys = await context.list_artifacts()
```

The context methods delegate to the configured `artifact_service`, automatically supplying `app_name`, `user_id`, and `session_id` from the current session.

---

## Artifact URI Utilities

The `artifact_util` module provides URI construction and parsing for cross-referencing artifacts:

```python
from google.adk.artifacts.artifact_util import get_artifact_uri, parse_artifact_uri

# Build a URI
uri = get_artifact_uri(
    app_name="my_app",
    user_id="user_123",
    filename="report.txt",
    version=2,
    session_id="sess_1",
)
# => "artifact://apps/my_app/users/user_123/sessions/sess_1/artifacts/report.txt/versions/2"

# User-scoped URI (no session)
uri = get_artifact_uri(
    app_name="my_app",
    user_id="user_123",
    filename="shared.png",
    version=0,
)
# => "artifact://apps/my_app/users/user_123/artifacts/shared.png/versions/0"

# Parse a URI
parsed = parse_artifact_uri(uri)
# => ParsedArtifactUri(app_name='my_app', user_id='user_123', session_id=None, filename='shared.png', version=0)
```

The `InMemoryArtifactService` can resolve `artifact://` references automatically when loading. `FileArtifactService` does not currently resolve `artifact://` URIs -- it only handles `file://` URIs for payload location fallback.

---

## Comparison of Artifact Service Implementations

| Feature | FileArtifactService | InMemoryArtifactService | GcsArtifactService |
|---------|-------------------|------------------------|-------------------|
| Storage | Local filesystem | Python dict in memory | Google Cloud Storage bucket |
| Persistence | Yes (survives restart) | No (lost on exit) | Yes (cloud-managed) |
| Thread model | `asyncio.to_thread()` | Direct async (no threading) | `asyncio.to_thread()` |
| Artifact references | No (`file://` URIs only) | Yes (`artifact://` URI resolution) | No |
| `file_data` support | No (raises error) | Yes (artifact refs) | No (raises `NotImplementedError`) |
| Metadata storage | JSON sidecar files | In `ArtifactVersion` objects | GCS blob metadata |
| Canonical URI scheme | `file://` | `memory://` | `gs://` |
| `app_name` in path | Not used | Used in key | Used in blob prefix |
| Text artifacts | `write_text` / `Part(text=...)` | Direct storage | `upload_from_string` as `text/plain` |
| Setup requirements | None (filesystem only) | None | GCS credentials + bucket |
| Custom metadata | Stored in `metadata.json` | Stored on `ArtifactVersion` | GCS blob custom metadata |

---

## Caveats and Limitations

1. **`app_name` is ignored in path construction**: The `FileArtifactService` does not incorporate `app_name` into the directory structure. If multiple apps share the same `root_dir`, artifacts from different apps with the same `user_id` and `filename` will collide. Use separate `root_dir` values per app, or be aware of this limitation.

2. **No file locking**: Concurrent saves to the same artifact could race on version number assignment. The version is determined by scanning directories, and the new directory is created without an atomic lock.

3. **No `artifact://` URI resolution**: Unlike `InMemoryArtifactService`, `FileArtifactService` does not resolve cross-references via `artifact://` URIs. Only `file://` URIs are supported for payload fallback.

4. **No individual version deletion**: `delete_artifact` removes all versions. There is no API to delete a single version.

5. **Metadata corruption resilience**: If `metadata.json` is corrupt or missing, methods that read metadata gracefully degrade (logging warnings and falling back to path-based defaults). However, the original filename may be lost.

6. **Path traversal protection**: Filenames that resolve outside the scope root are rejected with `InputValidationError`. Absolute paths are also rejected.

7. **Platform differences**: Windows-style separators (`\`) in filenames are automatically converted to POSIX style. The storage layout is designed to be portable.

8. **No cleanup/garbage collection**: Old versions accumulate indefinitely. There is no built-in mechanism to prune old versions or enforce retention policies.

9. **`file_data` artifacts not supported**: Only `inline_data` (binary) and `text` artifact types are supported. Attempting to save a `file_data` artifact raises `InputValidationError`.
