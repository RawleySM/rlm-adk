# ADK ArtifactService Source Code Analysis

> Analysis of the `google.adk.artifacts` module from the google/adk-python repository.

---

## Table of Contents

1. [Directory Structure](#1-directory-structure)
2. [Module Exports (__init__.py)](#2-module-exports)
3. [BaseArtifactService - Abstract Interface](#3-baseartifactservice---abstract-interface)
4. [ArtifactVersion - Metadata Model](#4-artifactversion---metadata-model)
5. [InMemoryArtifactService - In-Memory Implementation](#5-inmemoryartifactservice---in-memory-implementation)
6. [GcsArtifactService - Google Cloud Storage Implementation](#6-gcsartifactservice---google-cloud-storage-implementation)
7. [FileArtifactService - Local Filesystem Implementation](#7-fileartifactservice---local-filesystem-implementation)
8. [artifact_util.py - URI Utilities](#8-artifact_utilpy---uri-utilities)
9. [SaveFilesAsArtifactsPlugin - User Upload Handler](#9-savefilesasartifactsplugin---user-upload-handler)
10. [Dependencies and Imports](#10-dependencies-and-imports)
11. [Storage Path Conventions](#11-storage-path-conventions)
12. [Serialization and Content Type Handling](#12-serialization-and-content-type-handling)
13. [Async Patterns](#13-async-patterns)
14. [Implementation Comparison Matrix](#14-implementation-comparison-matrix)

---

## 1. Directory Structure

```
src/google/adk/artifacts/
    __init__.py                    # Public exports
    artifact_util.py               # URI parsing/construction utilities
    base_artifact_service.py       # ABC + ArtifactVersion Pydantic model
    file_artifact_service.py       # Local filesystem implementation
    gcs_artifact_service.py        # Google Cloud Storage implementation
    in_memory_artifact_service.py  # In-memory dict implementation

src/google/adk/plugins/
    save_files_as_artifacts_plugin.py  # Auto-save user uploads as artifacts

tests/unittests/artifacts/
    __init__.py
    test_artifact_service.py       # Parameterized tests for all implementations
    test_artifact_util.py          # URI utility tests
```

Source: https://github.com/google/adk-python/tree/main/src/google/adk/artifacts

---

## 2. Module Exports

```python
# src/google/adk/artifacts/__init__.py

from .base_artifact_service import BaseArtifactService
from .file_artifact_service import FileArtifactService
from .gcs_artifact_service import GcsArtifactService
from .in_memory_artifact_service import InMemoryArtifactService

__all__ = [
    'BaseArtifactService',
    'FileArtifactService',
    'GcsArtifactService',
    'InMemoryArtifactService',
]
```

Note: `ArtifactVersion` is NOT exported at the package level. To use it directly, import from the submodule:

```python
from google.adk.artifacts.base_artifact_service import ArtifactVersion
```

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/__init__.py

---

## 3. BaseArtifactService - Abstract Interface

The abstract base class defines the contract that all artifact service implementations must fulfill. It uses Python's `abc.ABC` with `@abstractmethod` decorators.

### Required Imports

```python
from abc import ABC, abstractmethod
from typing import Any, Optional
from google.genai import types
```

### Abstract Methods (7 total)

| Method | Returns | Purpose |
|--------|---------|---------|
| `save_artifact(...)` | `int` | Save artifact, return version number |
| `load_artifact(...)` | `Optional[types.Part]` | Load artifact by name, optional version |
| `list_artifact_keys(...)` | `list[str]` | List all artifact filenames in scope |
| `delete_artifact(...)` | `None` | Delete all versions of an artifact |
| `list_versions(...)` | `list[int]` | List version numbers for an artifact |
| `list_artifact_versions(...)` | `list[ArtifactVersion]` | List versions with full metadata |
| `get_artifact_version(...)` | `Optional[ArtifactVersion]` | Get metadata for a specific version |

### Common Parameter Pattern

All methods share these keyword-only parameters:

```python
async def method(
    self,
    *,
    app_name: str,          # Application identifier
    user_id: str,            # User identifier
    filename: str,           # Artifact name (with optional "user:" prefix)
    session_id: Optional[str] = None,  # None = user-scoped
    ...
) -> ...:
```

### Key Design Decisions

- All methods are `async` (coroutines)
- All parameters are keyword-only (enforced by `*` separator)
- `session_id=None` signals user-scoped storage
- Filenames starting with `"user:"` are always user-scoped regardless of session_id
- Version 0 is the first version, incrementing by 1

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/base_artifact_service.py

---

## 4. ArtifactVersion - Metadata Model

A Pydantic `BaseModel` that describes a specific version of an artifact.

```python
from pydantic import BaseModel, ConfigDict, Field, alias_generators
from datetime import datetime
from typing import Any, Optional

class ArtifactVersion(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,  # camelCase JSON serialization
        populate_by_name=True,                        # accept both camel and snake
    )

    version: int = Field(
        description="Monotonically increasing identifier for the artifact version."
    )
    canonical_uri: str = Field(
        description="Canonical URI referencing the persisted artifact payload."
    )
    custom_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional user-supplied metadata stored with the artifact.",
    )
    create_time: float = Field(
        default_factory=lambda: datetime.now().timestamp(),
        description="Unix timestamp (seconds) when the version record was created.",
    )
    mime_type: Optional[str] = Field(
        default=None,
        description="MIME type when the artifact payload is stored as binary data.",
    )
```

### Canonical URI Formats

Each implementation uses a different URI scheme:

| Implementation | URI Format |
|---------------|------------|
| InMemoryArtifactService | `memory://apps/{app}/users/{user}/sessions/{session}/artifacts/{file}/versions/{v}` |
| GcsArtifactService | `gs://{bucket}/{app}/{user}/{session}/{file}/{v}` |
| FileArtifactService | `file:///absolute/path/to/versions/{v}/{filename}` |

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/base_artifact_service.py

---

## 5. InMemoryArtifactService - In-Memory Implementation

### Class Hierarchy

```
BaseModel (Pydantic)
    |
BaseArtifactService (ABC)
    |
InMemoryArtifactService
```

Dual inheritance from both `BaseArtifactService` and Pydantic's `BaseModel`.

### Internal Storage Structure

```python
@dataclasses.dataclass
class _ArtifactEntry:
    data: types.Part
    artifact_version: ArtifactVersion

class InMemoryArtifactService(BaseArtifactService, BaseModel):
    artifacts: dict[str, list[_ArtifactEntry]] = Field(default_factory=dict)
```

The storage key is a path string: `"{app_name}/{user_id}/{session_id}/{filename}"` for session-scoped, or `"{app_name}/{user_id}/user/{filename}"` for user-scoped.

### Key Implementation Details

**Path construction:**
```python
def _artifact_path(self, app_name, user_id, filename, session_id):
    if self._file_has_user_namespace(filename):  # starts with "user:"
        return f"{app_name}/{user_id}/user/{filename}"
    if session_id is None:
        raise InputValidationError("Session ID must be provided for session-scoped artifacts.")
    return f"{app_name}/{user_id}/{session_id}/{filename}"
```

**Version management:** Version = `len(self.artifacts[path])` (list index).

**Artifact reference resolution:** When loading, if the artifact is an artifact reference (URI starting with `artifact://`), it recursively loads the referenced artifact.

**Empty artifact detection:** Returns `None` for empty `Part()`, `Part(text="")`, or `Part(inline_data=Blob(data=b""))`.

**MIME type inference:**
- `inline_data` present: uses `inline_data.mime_type`
- `text` present: uses `"text/plain"`
- `file_data` present: validates artifact reference URI or uses `file_data.mime_type`

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/in_memory_artifact_service.py

---

## 6. GcsArtifactService - Google Cloud Storage Implementation

### Class Hierarchy

```
BaseArtifactService (ABC)
    |
GcsArtifactService
```

Does NOT inherit from Pydantic BaseModel (unlike InMemoryArtifactService).

### Constructor

```python
def __init__(self, bucket_name: str, **kwargs):
    from google.cloud import storage  # lazy import
    self.bucket_name = bucket_name
    self.storage_client = storage.Client(**kwargs)
    self.bucket = self.storage_client.bucket(self.bucket_name)
```

The `google.cloud.storage` import is deferred to `__init__` to avoid import errors when GCS is not needed.

### GCS Blob Naming Convention

```
{app_name}/{user_id}/{session_id}/{filename}/{version}     # session-scoped
{app_name}/{user_id}/user/{filename}/{version}              # user-scoped
```

Each version is a separate blob. Version number is the last path segment.

### Async-to-Sync Bridge Pattern

All public methods are async but delegate to synchronous private methods via `asyncio.to_thread()`:

```python
@override
async def save_artifact(self, *, ...) -> int:
    return await asyncio.to_thread(
        self._save_artifact,
        app_name, user_id, session_id, filename, artifact, custom_metadata,
    )
```

This pattern runs blocking GCS I/O in a thread pool without blocking the event loop.

### Serialization Handling

```python
def _save_artifact(self, ...):
    if artifact.inline_data:
        blob.upload_from_string(
            data=artifact.inline_data.data,
            content_type=artifact.inline_data.mime_type,
        )
    elif artifact.text:
        blob.upload_from_string(
            data=artifact.text,
            content_type="text/plain",
        )
    elif artifact.file_data:
        raise NotImplementedError(
            "Saving artifact with file_data is not supported yet in GcsArtifactService."
        )
```

### Deserialization

```python
def _load_artifact(self, ...):
    artifact_bytes = blob.download_as_bytes()
    artifact = types.Part.from_bytes(
        data=artifact_bytes,
        mime_type=blob.content_type,
    )
```

Note: GCS stores content_type as blob metadata, so MIME type is always preserved.

### Version Discovery

Versions are discovered by listing blobs with a prefix and parsing the last path segment:

```python
def _list_versions(self, ...):
    prefix = self._get_blob_prefix(...)
    blobs = self.storage_client.list_blobs(self.bucket, prefix=f"{prefix}/")
    versions = []
    for blob in blobs:
        *_, version = blob.name.split("/")
        versions.append(int(version))
    return versions
```

### Custom Metadata

GCS custom metadata is stored as blob metadata (string key-value pairs):

```python
if custom_metadata:
    blob.metadata = {k: str(v) for k, v in custom_metadata.items()}
```

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/gcs_artifact_service.py

---

## 7. FileArtifactService - Local Filesystem Implementation

### Class Hierarchy

```
BaseArtifactService (ABC)
    |
FileArtifactService
```

### Storage Layout

```
root_dir/
  users/
    {user_id}/
      sessions/
        {session_id}/
          artifacts/
            {artifact_path}/
              versions/
                {version}/
                  {original_filename}   # payload
                  metadata.json          # FileArtifactVersion
      artifacts/                         # user-scoped
        {artifact_path}/
          versions/
            {version}/
              {original_filename}
              metadata.json
```

### Security: Path Traversal Protection

The `_resolve_scoped_artifact_path` function guards against directory traversal:

```python
def _resolve_scoped_artifact_path(scope_root, filename):
    stripped = _strip_user_namespace(filename).strip()
    pure_path = _to_posix_path(stripped)

    if pure_path.is_absolute():
        raise InputValidationError("Absolute artifact filename not permitted")

    candidate = (scope_root.resolve() / Path(pure_path)).resolve()

    try:
        relative = candidate.relative_to(scope_root.resolve())
    except ValueError:
        raise InputValidationError(f"Artifact filename escapes storage directory")

    return candidate, relative
```

This rejects filenames like `"../../etc/passwd"` or `"/absolute/path"`.

### Metadata Persistence

Each version stores a `metadata.json` file alongside the payload:

```python
class FileArtifactVersion(ArtifactVersion):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
    )
    file_name: str = Field(description="Original filename supplied by the caller.")
```

Serialization uses Pydantic's `model_dump_json(by_alias=True, exclude_none=True)` for camelCase JSON.
Deserialization uses `FileArtifactVersion.model_validate_json(...)`.

### Content Type Handling

```python
def _save_artifact_sync(self, ...):
    if artifact.inline_data:
        content_path.write_bytes(artifact.inline_data.data)
        mime_type = artifact.inline_data.mime_type or "application/octet-stream"
    elif artifact.text is not None:
        content_path.write_text(artifact.text, encoding="utf-8")
        mime_type = None  # text artifacts have no explicit MIME type
    else:
        raise InputValidationError("Artifact must have either inline_data or text content.")
```

When loading, `mime_type is not None` signals binary data (read as bytes), while `mime_type is None` signals text (read as UTF-8 string).

### Async Pattern

Same as GCS: uses `asyncio.to_thread()` for all filesystem I/O.

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/file_artifact_service.py

---

## 8. artifact_util.py - URI Utilities

Provides utilities for the `artifact://` URI scheme used for cross-referencing artifacts.

### URI Formats

```
artifact://apps/{app}/users/{user}/sessions/{session}/artifacts/{file}/versions/{version}
artifact://apps/{app}/users/{user}/artifacts/{file}/versions/{version}
```

### Key Functions

```python
# Parse an artifact URI into components
def parse_artifact_uri(uri: str) -> Optional[ParsedArtifactUri]:
    ...

# Construct an artifact URI from components
def get_artifact_uri(app_name, user_id, filename, version, session_id=None) -> str:
    ...

# Check if a Part is an artifact reference
def is_artifact_ref(artifact: types.Part) -> bool:
    return bool(
        artifact.file_data
        and artifact.file_data.file_uri
        and artifact.file_data.file_uri.startswith("artifact://")
    )
```

### ParsedArtifactUri

```python
class ParsedArtifactUri(NamedTuple):
    app_name: str
    user_id: str
    session_id: Optional[str]
    filename: str
    version: int
```

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/artifact_util.py

---

## 9. SaveFilesAsArtifactsPlugin - User Upload Handler

Located in `src/google/adk/plugins/save_files_as_artifacts_plugin.py`, this plugin intercepts user messages and auto-saves embedded files.

### Plugin Flow

1. Iterates over `user_message.parts`
2. For each part with `inline_data`:
   - Extracts `display_name` (or generates one: `artifact_{invocation_id}_{index}`)
   - Calls `invocation_context.artifact_service.save_artifact(...)` directly
   - Replaces the inline data with a text placeholder: `[Uploaded Artifact: "name"]`
   - If the artifact's canonical URI is model-accessible (`gs://`, `https://`, `http://`), also appends a `FileData` part
3. Returns modified `Content` with placeholders instead of raw binary data

### Model-Accessible URI Check

```python
_MODEL_ACCESSIBLE_URI_SCHEMES = {'gs', 'https', 'http'}

def _is_model_accessible_uri(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    return parsed.scheme.lower() in _MODEL_ACCESSIBLE_URI_SCHEMES
```

The `memory://` and `file://` schemes used by InMemoryArtifactService and FileArtifactService are NOT model-accessible. Only GCS-backed artifacts get file references that models can access directly.

Source: https://github.com/google/adk-python/blob/main/src/google/adk/plugins/save_files_as_artifacts_plugin.py

---

## 10. Dependencies and Imports

### Core (all implementations)

```python
from google.genai import types          # types.Part, types.Blob, types.FileData
from google.adk.errors.input_validation_error import InputValidationError
```

### InMemoryArtifactService

```python
import dataclasses
from pydantic import BaseModel, Field
from typing_extensions import override
from . import artifact_util
```

### GcsArtifactService

```python
import asyncio
from google.cloud import storage         # lazy import in __init__
from typing_extensions import override
```

### FileArtifactService

```python
import asyncio
import os
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlparse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, alias_generators
from typing_extensions import override
```

### SaveFilesAsArtifactsPlugin

```python
import copy
import urllib.parse
from google.genai import types
from ..agents.invocation_context import InvocationContext
from .base_plugin import BasePlugin
```

### Install Requirements

```
google-adk                      # core package
google-cloud-storage             # only for GcsArtifactService
google-genai                     # genai types (Part, Blob, etc.)
pydantic                         # models and validation
```

---

## 11. Storage Path Conventions

### InMemoryArtifactService (dict keys)

```
{app_name}/{user_id}/{session_id}/{filename}      # session-scoped
{app_name}/{user_id}/user/{filename}               # user-scoped (user: prefix)
```

### GcsArtifactService (blob paths)

```
{app_name}/{user_id}/{session_id}/{filename}/{version}   # session-scoped
{app_name}/{user_id}/user/{filename}/{version}            # user-scoped
```

### FileArtifactService (directory paths)

```
{root}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_path}/versions/{version}/
{root}/users/{user_id}/artifacts/{artifact_path}/versions/{version}/
```

Each version directory contains:
- The payload file (named after the last segment of the artifact path)
- `metadata.json` (FileArtifactVersion serialized as camelCase JSON)

---

## 12. Serialization and Content Type Handling

### Artifact Data Container

All implementations use `google.genai.types.Part` as the data container:

```python
# Binary data
types.Part(inline_data=types.Blob(data=bytes, mime_type=str))
# or
types.Part.from_bytes(data=bytes, mime_type=str)

# Text data
types.Part(text=str)
# or
types.Part.from_text(str)

# File reference (artifact cross-reference)
types.Part(file_data=types.FileData(file_uri=str, mime_type=str))
```

### Save Logic (common across implementations)

| Part Type | How Stored | MIME Type |
|-----------|-----------|-----------|
| `inline_data` | Raw bytes | From `inline_data.mime_type` |
| `text` | UTF-8 encoded string | `"text/plain"` or `None` |
| `file_data` (artifact ref) | URI reference only (InMemory) | From `file_data.mime_type` |
| `file_data` (non-ref) | Not supported (GCS raises `NotImplementedError`) | N/A |

### Load Logic

| Implementation | Binary Return | Text Return |
|---------------|--------------|-------------|
| InMemory | Original `types.Part` object | Original `types.Part` object |
| GCS | `types.Part.from_bytes(data, mime_type=blob.content_type)` | Same as binary (text stored as bytes) |
| File | `types.Part(inline_data=Blob(mime_type, data))` | `types.Part(text=content)` |

---

## 13. Async Patterns

### InMemoryArtifactService

All methods are native async (no threading needed since operations are in-memory dict lookups).

### GcsArtifactService and FileArtifactService

Both use the same pattern: async public methods that delegate to synchronous private methods via `asyncio.to_thread()`:

```python
# Public async interface
@override
async def save_artifact(self, *, ...) -> int:
    return await asyncio.to_thread(self._save_artifact_sync, ...)

# Private sync implementation
def _save_artifact_sync(self, ...) -> int:
    # blocking I/O here
    ...
```

This pattern:
- Keeps the async interface consistent across all implementations
- Runs blocking I/O (filesystem, GCS API) in the default thread pool
- Avoids blocking the asyncio event loop
- Allows the sync implementations to use straightforward sequential code

---

## 14. Implementation Comparison Matrix

| Feature | InMemory | GCS | File |
|---------|----------|-----|------|
| Persistence | None (process lifetime) | GCS bucket | Local filesystem |
| Pydantic BaseModel | Yes | No | No |
| Async strategy | Native async | `asyncio.to_thread` | `asyncio.to_thread` |
| Metadata storage | In `_ArtifactEntry` dataclass | GCS blob metadata | `metadata.json` files |
| Artifact references | Resolved recursively | Not supported | Not supported |
| Path traversal guard | N/A (string keys) | N/A (GCS paths) | Yes (`_resolve_scoped_artifact_path`) |
| `file_data` save | Supported (artifact refs) | `NotImplementedError` | `InputValidationError` |
| Custom metadata | In `ArtifactVersion` | GCS blob metadata (string values) | In `metadata.json` |
| MIME type source | Part inspection | Part inspection + blob content_type | Part inspection + metadata.json |
| Version discovery | `len(list)` | Blob listing + name parsing | Directory listing + name parsing |
| URI scheme | `memory://` | `gs://` | `file://` |
| Model-accessible URI | No | Yes | No |
| Install dependency | None extra | `google-cloud-storage` | None extra |

---

## Source URLs

- Repository: https://github.com/google/adk-python
- Artifacts module: https://github.com/google/adk-python/tree/main/src/google/adk/artifacts
- base_artifact_service.py: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/base_artifact_service.py
- in_memory_artifact_service.py: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/in_memory_artifact_service.py
- gcs_artifact_service.py: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/gcs_artifact_service.py
- file_artifact_service.py: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/file_artifact_service.py
- artifact_util.py: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/artifact_util.py
- __init__.py: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/__init__.py
- save_files_as_artifacts_plugin.py: https://github.com/google/adk-python/blob/main/src/google/adk/plugins/save_files_as_artifacts_plugin.py
- Test files: https://github.com/google/adk-python/tree/main/tests/unittests/artifacts
- Official documentation: https://google.github.io/adk-docs/artifacts/
