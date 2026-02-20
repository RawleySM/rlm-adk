# ADK ArtifactService Code Examples

> Collected from the google/adk-python repository, official documentation, community tutorials, and GitHub discussions.

---

## Table of Contents

1. [Instantiating ArtifactService Implementations](#1-instantiating-artifactservice-implementations)
2. [Configuring ArtifactService with Runner](#2-configuring-artifactservice-with-runner)
3. [Saving Artifacts from Within Agents](#3-saving-artifacts-from-within-agents)
4. [Loading Artifacts from Within Agents](#4-loading-artifacts-from-within-agents)
5. [Listing Artifacts](#5-listing-artifacts)
6. [Artifact Versioning](#6-artifact-versioning)
7. [User-Scoped vs Session-Scoped Artifacts](#7-user-scoped-vs-session-scoped-artifacts)
8. [Using Artifacts in Custom Tools (ToolContext)](#8-using-artifacts-in-custom-tools-toolcontext)
9. [Using Artifacts in Callbacks (CallbackContext)](#9-using-artifacts-in-callbacks-callbackcontext)
10. [After-Tool Callback Pattern (Large Output Optimization)](#10-after-tool-callback-pattern-large-output-optimization)
11. [SaveFilesAsArtifactsPlugin Usage](#11-savefilesasartifactsplugin-usage)
12. [Binary Data Handling (Images, PDFs)](#12-binary-data-handling-images-pdfs)
13. [CSV Artifact Pattern](#13-csv-artifact-pattern)
14. [Metadata Embedding Pattern](#14-metadata-embedding-pattern)
15. [Test Patterns for ArtifactService](#15-test-patterns-for-artifactservice)
16. [Error Handling Best Practices](#16-error-handling-best-practices)

---

## 1. Instantiating ArtifactService Implementations

### InMemoryArtifactService (Development / Testing)

Stores artifacts in application memory. Data is lost when the process exits.

```python
from google.adk.artifacts import InMemoryArtifactService

artifact_service = InMemoryArtifactService()
```

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/in_memory_artifact_service.py

### GcsArtifactService (Production - Google Cloud Storage)

Persists artifacts to a GCS bucket. Requires `google-cloud-storage` and Application Default Credentials.

```python
from google.adk.artifacts import GcsArtifactService

gcs_bucket_name = "your-gcs-bucket-for-adk-artifacts"

try:
    gcs_service = GcsArtifactService(bucket_name=gcs_bucket_name)
except Exception as e:
    print(f"Error initializing GcsArtifactService: {e}")
```

The constructor accepts `**kwargs` that are passed through to `google.cloud.storage.Client(...)`.

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/gcs_artifact_service.py

### FileArtifactService (Local Filesystem)

Persists artifacts to a local directory with versioned subdirectories and JSON metadata.

```python
from google.adk.artifacts import FileArtifactService
from pathlib import Path

file_service = FileArtifactService(root_dir=Path("./my_artifacts"))
# or
file_service = FileArtifactService(root_dir="~/.adk/artifacts")
```

The directory is created automatically if it does not exist. Path traversal attacks are rejected.

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/file_artifact_service.py

---

## 2. Configuring ArtifactService with Runner

The `artifact_service` is provided when constructing the `Runner`. All context objects (`ToolContext`, `CallbackContext`) then gain access to artifact operations.

```python
from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

agent = LlmAgent(name="my_agent", model="gemini-2.0-flash")

artifact_service = InMemoryArtifactService()

runner = Runner(
    agent=agent,
    app_name="artifact_app",
    session_service=InMemorySessionService(),
    artifact_service=artifact_service,  # <-- required for artifact operations
)
```

Without an `artifact_service`, calls to `context.save_artifact(...)` raise `ValueError`.

Source: https://google.github.io/adk-docs/artifacts/

---

## 3. Saving Artifacts from Within Agents

### Using CallbackContext (in before/after model callbacks)

```python
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

async def save_generated_report(context: CallbackContext, report_bytes: bytes):
    """Save a PDF report as a versioned artifact."""
    report_artifact = types.Part.from_bytes(
        data=report_bytes,
        mime_type="application/pdf"
    )
    filename = "generated_report.pdf"

    try:
        version = await context.save_artifact(
            filename=filename,
            artifact=report_artifact,
        )
        print(f"Saved artifact '{filename}' as version {version}")
    except ValueError as e:
        print(f"Error: {e}. Is ArtifactService configured in Runner?")
```

### Using ToolContext (in custom tools)

```python
from google.adk.tools.tool_context import ToolContext
from google.genai import types

async def extract_text(document: str, tool_context: ToolContext) -> dict:
    """Extract text and save as artifact."""
    extracted = f"EXTRACTED TEXT FROM: {document}"
    part = types.Part.from_text(extracted)

    version = await tool_context.save_artifact(
        filename=f"{document}_extracted.txt",
        artifact=part,
    )

    return {
        "status": "success",
        "version": version,
        "filename": f"{document}_extracted.txt",
    }
```

Source: https://google.github.io/adk-docs/artifacts/, https://google.github.io/adk-docs/context/

---

## 4. Loading Artifacts from Within Agents

```python
async def process_latest_report(context: CallbackContext):
    filename = "generated_report.pdf"
    try:
        report_artifact = await context.load_artifact(filename=filename)

        if report_artifact and report_artifact.inline_data:
            pdf_bytes = report_artifact.inline_data.data
            mime_type = report_artifact.inline_data.mime_type
            print(f"Loaded '{filename}': {len(pdf_bytes)} bytes, type={mime_type}")
        else:
            print(f"Artifact '{filename}' not found")

    except ValueError as e:
        print(f"Error: {e}")
```

### Load a specific version

```python
async def load_version(context: CallbackContext, filename: str, version: int):
    """Load a specific historical version of an artifact (0-indexed)."""
    artifact = await context.load_artifact(filename=filename, version=version)
    if artifact:
        return artifact.text  # or artifact.inline_data.data for binary
    return None
```

Source: https://google.github.io/adk-docs/artifacts/

---

## 5. Listing Artifacts

```python
async def list_user_files(tool_context: ToolContext) -> str:
    """List all artifacts in the current session scope."""
    try:
        available_files = await tool_context.list_artifacts()
        if not available_files:
            return "No saved artifacts"
        file_list = "\n".join([f"- {fname}" for fname in available_files])
        return f"Available artifacts:\n{file_list}"
    except ValueError as e:
        return f"Error listing artifacts: {e}"
```

Source: https://google.github.io/adk-docs/artifacts/

---

## 6. Artifact Versioning

Versions are 0-indexed and auto-increment. Each call to `save_artifact` with the same filename creates a new version.

```python
async def demonstrate_versioning(context: CallbackContext):
    part_v0 = types.Part.from_text("Version 0 content")
    v0 = await context.save_artifact(filename="doc.txt", artifact=part_v0)
    assert v0 == 0

    part_v1 = types.Part.from_text("Version 1 content - updated")
    v1 = await context.save_artifact(filename="doc.txt", artifact=part_v1)
    assert v1 == 1

    # Load latest (version 1)
    latest = await context.load_artifact(filename="doc.txt")
    assert latest.text == "Version 1 content - updated"

    # Load specific version (version 0)
    original = await context.load_artifact(filename="doc.txt", version=0)
    assert original.text == "Version 0 content"
```

### Listing all versions (direct service API)

```python
# Direct service API (not through context):
versions = await artifact_service.list_versions(
    app_name="my_app",
    user_id="user1",
    filename="doc.txt",
    session_id="session1",
)
# Returns: [0, 1]

# With metadata:
artifact_versions = await artifact_service.list_artifact_versions(
    app_name="my_app",
    user_id="user1",
    filename="doc.txt",
    session_id="session1",
)
# Returns: [ArtifactVersion(version=0, ...), ArtifactVersion(version=1, ...)]
```

Source: https://github.com/google/adk-python/blob/main/src/google/adk/artifacts/base_artifact_service.py

---

## 7. User-Scoped vs Session-Scoped Artifacts

By default, artifacts are session-scoped. Prefix with `"user:"` for cross-session persistence.

```python
# Session-scoped: only available in this session
await context.save_artifact(filename="summary.txt", artifact=part)

# User-scoped: available across all sessions for this user
await context.save_artifact(filename="user:settings.json", artifact=part)

# Loading user-scoped artifact from any session
settings = await context.load_artifact(filename="user:settings.json")
```

Source: https://google.github.io/adk-docs/artifacts/

---

## 8. Using Artifacts in Custom Tools (ToolContext)

The `tool_context` parameter is injected automatically by ADK. Do NOT include it in the tool docstring.

```python
from google.adk.tools.tool_context import ToolContext
from google.genai import types

async def process_document(
    document_name: str,
    analysis_query: str,
    tool_context: ToolContext,
) -> dict:
    """Analyzes a document stored as an artifact.

    Args:
        document_name: Name of the document artifact to analyze.
        analysis_query: The analysis to perform.
    """
    # Load artifact
    document_part = await tool_context.load_artifact(document_name)
    if not document_part:
        return {"status": "error", "message": f"Document '{document_name}' not found"}

    # Process the document content
    if document_part.inline_data:
        content = document_part.inline_data.data.decode("utf-8")
    elif document_part.text:
        content = document_part.text
    else:
        return {"status": "error", "message": "Unknown artifact format"}

    analysis_result = f"Analysis of '{document_name}': {len(content)} chars processed"

    # Save analysis result as new artifact
    analysis_part = types.Part.from_text(text=analysis_result)
    version = await tool_context.save_artifact(
        filename=f"analysis_{document_name}",
        artifact=analysis_part,
    )
    return {"status": "success", "version": version}
```

Source: https://google.github.io/adk-docs/tools-custom/

---

## 9. Using Artifacts in Callbacks (CallbackContext)

### Processing user-uploaded images in before_model_callback

```python
from google.adk.agents.callback_context import CallbackContext
from google.genai import types
from typing import List

async def _process_inline_data_part(
    part: types.Part,
    callback_context: CallbackContext,
) -> List[types.Part]:
    """Save user-uploaded images as artifacts and create placeholder references."""
    artifact_id = f"upload_{hash(part.inline_data.data)}.png"

    if artifact_id not in await callback_context.list_artifacts():
        await callback_context.save_artifact(filename=artifact_id, artifact=part)

    return [
        types.Part(text=f'[Uploaded Artifact: "{artifact_id}"]'),
        part,
    ]
```

Source: https://codelabs.developers.google.com/adk-multimodal-tool-part-1

### Retrieving tool-generated artifacts in after_model_callback

```python
async def _process_function_response_part(
    part: types.Part,
    callback_context: CallbackContext,
) -> List[types.Part]:
    """Load and inline artifacts referenced in tool responses."""
    artifact_id = part.function_response.response.get("tool_response_artifact_id")

    if not artifact_id:
        return [part]

    artifact = await callback_context.load_artifact(filename=artifact_id)
    return [
        part,
        types.Part(text=f"[Tool Artifact: {artifact_id}]"),
        artifact,
    ]
```

Source: https://codelabs.developers.google.com/adk-multimodal-tool-part-1

---

## 10. After-Tool Callback Pattern (Large Output Optimization)

Store large tool outputs as artifacts and return only a summary to keep the conversation context small.

```python
from google.adk.tools import ToolContext, BaseTool
import json

async def summarize_and_save_to_artifact(
    *,
    tool: BaseTool,
    tool_args: dict,
    tool_context: ToolContext,
    result: dict,
) -> dict:
    """After-tool callback: save large output as artifact, return summary."""
    if tool.name == "my_large_output_tool":
        summary = f"Summary: {result.get('summary', 'No summary')}"

        # Save the full result as a JSON artifact
        artifact_name = f"tool_output_{tool_context.function_call_id}.json"
        full_data = json.dumps(result).encode("utf-8")
        artifact_part = types.Part.from_bytes(
            data=full_data,
            mime_type="application/json",
        )
        version = await tool_context.save_artifact(
            filename=artifact_name,
            artifact=artifact_part,
        )

        # Return only the summary + reference
        modified_result = {
            "summary": summary,
            "artifact_name": artifact_name,
            "artifact_version": version,
        }

        # Prevent the agent from summarizing this already-summarized result
        tool_context.actions.skip_summarization = True

        return modified_result

    return result
```

Source: https://github.com/google/adk-python/discussions/3150

---

## 11. SaveFilesAsArtifactsPlugin Usage

The built-in plugin automatically saves files embedded in user messages as artifacts.

```python
from google.adk.plugins.save_files_as_artifacts_plugin import SaveFilesAsArtifactsPlugin
from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.adk.agents import LlmAgent

agent = LlmAgent(
    name="file_processor",
    model="gemini-2.0-flash",
    instruction="Process uploaded files.",
)

runner = Runner(
    agent=agent,
    app_name="file_app",
    session_service=InMemorySessionService(),
    artifact_service=InMemoryArtifactService(),
)

# The plugin is typically configured at the framework level.
# It intercepts user messages with inline_data parts,
# saves them as artifacts, and replaces them with placeholder text:
#   [Uploaded Artifact: "filename.ext"]
```

The plugin:
- Checks for `inline_data` in user message parts
- Saves each file via `invocation_context.artifact_service.save_artifact(...)`
- Replaces inline data with `[Uploaded Artifact: "display_name"]` placeholder
- Builds a model-accessible file reference if the canonical URI uses `gs://`, `https://`, or `http://`

Source: https://github.com/google/adk-python/blob/main/src/google/adk/plugins/save_files_as_artifacts_plugin.py

---

## 12. Binary Data Handling (Images, PDFs)

### Saving an image artifact

```python
async def save_image(context: CallbackContext, image_bytes: bytes):
    """Save image artifact with explicit MIME type."""
    image_part = types.Part(
        inline_data=types.Blob(
            data=image_bytes,
            mime_type="image/png",
        )
    )
    # Or use the convenience constructor:
    # image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

    version = await context.save_artifact(filename="chart.png", artifact=image_part)
    return version
```

### Saving tool-generated images

```python
# Inside a tool that generates images via Gemini
for part in response.candidates[0].content.parts:
    if part.inline_data is not None:
        artifact_id = f"edited_img_{tool_context.function_call_id}.png"
        await tool_context.save_artifact(filename=artifact_id, artifact=part)
```

Source: https://codelabs.developers.google.com/adk-multimodal-tool-part-1

---

## 13. CSV Artifact Pattern

```python
from google.adk.tools.tool_context import ToolContext
from google.genai import types

def save_csv_artifact(context: ToolContext):
    """Save CSV data as an artifact with user: prefix for cross-session access."""
    with open("./data/supply_chain_data.csv", "rb") as f:
        csv_bytes = f.read()

    csv_part = types.Part.from_bytes(data=csv_bytes, mime_type="text/csv")
    filename = "user:supply_chain_data.csv"

    try:
        version = context.save_artifact(filename=filename, artifact=csv_part)
        print(f"Saved artifact '{filename}' version {version}")
    except ValueError as e:
        print(f"Error: {e}. Is ArtifactService configured?")
```

### Loading CSV into pandas

```python
import pandas as pd
from io import BytesIO

async def load_csv_as_dataframe(tool_context: ToolContext, filename: str):
    """Load a CSV artifact and parse it into a DataFrame."""
    artifact = await tool_context.load_artifact(filename=filename)
    if artifact and artifact.inline_data:
        csv_bytes = artifact.inline_data.data
        df = pd.read_csv(BytesIO(csv_bytes))
        return df
    raise FileNotFoundError(f"Artifact '{filename}' not found")
```

Source: https://github.com/google/adk-python/discussions/907

---

## 14. Metadata Embedding Pattern

Since `save_artifact` accepts `custom_metadata` at the service level but not through the context API, you can embed metadata within the artifact content.

```python
import json
from google.genai import types

async def save_with_metadata(context, filename: str, content: str, metadata: dict):
    """Embed metadata within artifact content as JSON envelope."""
    wrapped = {
        "metadata": metadata,
        "content": content,
    }
    json_str = json.dumps(wrapped, indent=2)
    part = types.Part.from_text(json_str)
    version = await context.save_artifact(filename=filename, artifact=part)
    return version

async def load_with_metadata(context, filename: str):
    """Extract metadata from a JSON-envelope artifact."""
    artifact = await context.load_artifact(filename=filename)
    if artifact and artifact.text:
        data = json.loads(artifact.text)
        return data["content"], data["metadata"]
    return None, None
```

Source: https://raphaelmansuy.github.io/adk_training/docs/artifacts_files/

---

## 15. Test Patterns for ArtifactService

### Basic test setup with InMemoryArtifactService

```python
import pytest
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.genai import types

@pytest.fixture
def artifact_service():
    return InMemoryArtifactService()

@pytest.mark.asyncio
async def test_save_load_artifact(artifact_service):
    """Test basic save and load cycle."""
    part = types.Part.from_bytes(data=b"hello world", mime_type="text/plain")

    version = await artifact_service.save_artifact(
        app_name="test_app",
        user_id="user1",
        session_id="session1",
        filename="test.txt",
        artifact=part,
    )
    assert version == 0

    loaded = await artifact_service.load_artifact(
        app_name="test_app",
        user_id="user1",
        session_id="session1",
        filename="test.txt",
    )
    assert loaded is not None
    assert loaded.inline_data.data == b"hello world"
```

### Testing versioning

```python
@pytest.mark.asyncio
async def test_artifact_versioning(artifact_service):
    """Test that repeated saves create incremented versions."""
    for i in range(3):
        part = types.Part.from_bytes(data=f"v{i}".encode(), mime_type="text/plain")
        version = await artifact_service.save_artifact(
            app_name="app",
            user_id="user1",
            session_id="sess1",
            filename="versioned.txt",
            artifact=part,
        )
        assert version == i

    versions = await artifact_service.list_versions(
        app_name="app",
        user_id="user1",
        session_id="sess1",
        filename="versioned.txt",
    )
    assert versions == [0, 1, 2]

    # Latest version
    latest = await artifact_service.load_artifact(
        app_name="app",
        user_id="user1",
        session_id="sess1",
        filename="versioned.txt",
    )
    assert latest.inline_data.data == b"v2"
```

### Testing list and delete

```python
@pytest.mark.asyncio
async def test_list_and_delete(artifact_service):
    """Test listing artifact keys and deletion."""
    part = types.Part.from_text("content")
    await artifact_service.save_artifact(
        app_name="app", user_id="u1", session_id="s1",
        filename="a.txt", artifact=part,
    )
    await artifact_service.save_artifact(
        app_name="app", user_id="u1", session_id="s1",
        filename="b.txt", artifact=part,
    )

    keys = await artifact_service.list_artifact_keys(
        app_name="app", user_id="u1", session_id="s1",
    )
    assert "a.txt" in keys
    assert "b.txt" in keys

    await artifact_service.delete_artifact(
        app_name="app", user_id="u1", session_id="s1",
        filename="a.txt",
    )

    keys = await artifact_service.list_artifact_keys(
        app_name="app", user_id="u1", session_id="s1",
    )
    assert "a.txt" not in keys
    assert "b.txt" in keys
```

### Testing with FileArtifactService (using tmp_path)

```python
@pytest.fixture
def file_artifact_service(tmp_path):
    return FileArtifactService(root_dir=tmp_path / "artifacts")

@pytest.mark.asyncio
async def test_file_service_roundtrip(file_artifact_service):
    part = types.Part.from_bytes(data=b"file content", mime_type="text/plain")
    version = await file_artifact_service.save_artifact(
        app_name="app", user_id="u1", session_id="s1",
        filename="doc.txt", artifact=part,
    )
    assert version == 0

    loaded = await file_artifact_service.load_artifact(
        app_name="app", user_id="u1", session_id="s1",
        filename="doc.txt",
    )
    assert loaded.inline_data.data == b"file content"
```

### Parameterized testing across all service types

The official test suite uses `@pytest.mark.parametrize` to run the same tests against all implementations:

```python
import enum

class ArtifactServiceType(enum.Enum):
    FILE = "FILE"
    IN_MEMORY = "IN_MEMORY"
    GCS = "GCS"

@pytest.fixture
def artifact_service_factory(tmp_path):
    def factory(service_type: ArtifactServiceType):
        if service_type == ArtifactServiceType.IN_MEMORY:
            return InMemoryArtifactService()
        elif service_type == ArtifactServiceType.FILE:
            return FileArtifactService(root_dir=tmp_path / "artifacts")
        elif service_type == ArtifactServiceType.GCS:
            return mock_gcs_artifact_service()
    return factory

@pytest.mark.asyncio
@pytest.mark.parametrize("service_type", [
    ArtifactServiceType.FILE,
    ArtifactServiceType.IN_MEMORY,
    ArtifactServiceType.GCS,
])
async def test_save_load_delete(artifact_service_factory, service_type):
    service = artifact_service_factory(service_type)
    # ... test logic ...
```

Source: https://github.com/google/adk-python/blob/main/tests/unittests/artifacts/test_artifact_service.py

---

## 16. Error Handling Best Practices

```python
async def safe_artifact_operation(context, filename: str):
    """Demonstrates defensive artifact handling."""
    try:
        artifact = await context.load_artifact(filename=filename)
        if artifact is None:
            print(f"Artifact '{filename}' does not exist")
            return None

        # Check what kind of data the artifact contains
        if artifact.inline_data:
            return artifact.inline_data.data
        elif artifact.text:
            return artifact.text.encode("utf-8")
        else:
            print(f"Artifact '{filename}' has unknown format")
            return None

    except ValueError as e:
        # Raised when artifact_service is not configured
        print(f"ArtifactService not configured: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error loading '{filename}': {e}")
        return None
```

Key error scenarios:
- `ValueError`: ArtifactService not configured in Runner
- `None` return: Artifact does not exist or version not found
- `InputValidationError`: Invalid filename (path traversal, absolute path) or missing session_id for session-scoped artifacts

Source: https://google.github.io/adk-docs/artifacts/

---

## Quick Reference: Method Signatures

### Context API (ToolContext / CallbackContext)

```python
# Save - returns version number (int, 0-indexed)
version: int = await context.save_artifact(filename: str, artifact: types.Part)

# Load - returns Part or None
artifact: Optional[types.Part] = await context.load_artifact(filename: str, version: Optional[int] = None)

# List - returns list of filenames
filenames: list[str] = await context.list_artifacts()
```

### Direct Service API (BaseArtifactService)

```python
# Save
version: int = await service.save_artifact(
    app_name=str, user_id=str, filename=str, artifact=types.Part,
    session_id=Optional[str], custom_metadata=Optional[dict[str, Any]])

# Load
artifact: Optional[types.Part] = await service.load_artifact(
    app_name=str, user_id=str, filename=str,
    session_id=Optional[str], version=Optional[int])

# List keys
filenames: list[str] = await service.list_artifact_keys(
    app_name=str, user_id=str, session_id=Optional[str])

# Delete
await service.delete_artifact(
    app_name=str, user_id=str, filename=str, session_id=Optional[str])

# List version numbers
versions: list[int] = await service.list_versions(
    app_name=str, user_id=str, filename=str, session_id=Optional[str])

# List version metadata
artifact_versions: list[ArtifactVersion] = await service.list_artifact_versions(
    app_name=str, user_id=str, filename=str, session_id=Optional[str])

# Get single version metadata
version_meta: Optional[ArtifactVersion] = await service.get_artifact_version(
    app_name=str, user_id=str, filename=str,
    session_id=Optional[str], version=Optional[int])
```

---

## Source URLs

- Official docs: https://google.github.io/adk-docs/artifacts/
- Context docs: https://google.github.io/adk-docs/context/
- Custom tools docs: https://google.github.io/adk-docs/tools-custom/
- Repository: https://github.com/google/adk-python
- Artifacts source: https://github.com/google/adk-python/tree/main/src/google/adk/artifacts
- Plugin source: https://github.com/google/adk-python/blob/main/src/google/adk/plugins/save_files_as_artifacts_plugin.py
- Test files: https://github.com/google/adk-python/tree/main/tests/unittests/artifacts
- Multimodal codelab: https://codelabs.developers.google.com/adk-multimodal-tool-part-1
- Training hub tutorial: https://raphaelmansuy.github.io/adk_training/docs/artifacts_files/
- Discussion (large outputs): https://github.com/google/adk-python/discussions/3150
- Discussion (CSV artifacts): https://github.com/google/adk-python/discussions/907
- Community blog: https://arjunprabhulal.com/adk-artifacts/
