# Artifact Persistence Architecture

## Storage Layout

**Default Artifact Root**: `.adk/artifacts/` (defined in `rlm_adk/agent.py` line 65)

```
.adk/artifacts/
└── users/
    └── {user_id}/
        ├── sessions/
        │   └── {session_id}/
        │       └── artifacts/
        │           └── {artifact_path}/
        │               └── versions/
        │                   └── {version}/
        │                       ├── {original_filename}
        │                       └── metadata.json
        └── artifacts/
            └── {artifact_path}/...
```

---

## Key Files Involved

### 1. RLM ADK Project Code

#### Artifact helper functions (`rlm_adk/artifacts.py`)
| Function | Lines | Purpose |
|----------|-------|---------|
| `save_repl_output()` | 62-107 | Saves REPL stdout/stderr |
| `save_repl_code()` | 110-150 | Saves Python code blocks |
| `save_worker_result()` | 153-195 | Saves worker/sub-agent results |
| `save_final_answer()` | 198-236 | Saves final answer as markdown |
| `save_binary_artifact()` | 239-275 | Saves arbitrary binary data |
| `load_artifact()` | 278-313 | Loads artifacts by filename |
| `list_artifacts()` | 316-341 | Lists all artifact filenames |
| `delete_artifact()` | 344-373 | Deletes artifacts |
| `_update_save_tracking()` | 376-397 | Updates state metadata |

#### Orchestrator integration (`rlm_adk/orchestrator.py`)
- Line 22: Imports artifact save functions
- Line 280: `await save_repl_code(ctx, iteration=i, turn=turn_idx, code=code_str)` - saves code after execution
- Lines 291-296: `await save_repl_output(ctx, ...)` - saves output after code blocks
- Line 349: `await save_final_answer(ctx, answer=final_answer)` - saves when final answer detected

#### Agent factory (`rlm_adk/agent.py`)
- Line 65: `_DEFAULT_ARTIFACT_ROOT = ".adk/artifacts"`
- Lines 361, 409-413: `artifact_service` parameter declaration
- Lines 439-440: Default `FileArtifactService` instantiation
- Lines 442-446: Runner creation with artifact_service

### 2. Google ADK Package Code (installed)

#### FileArtifactService (`.venv/.../google/adk/artifacts/file_artifact_service.py`)
- Lines 210-217: `__init__()` - initializes with root_dir, creates directory
- Lines 219-237: Path building methods (`_base_root()`, `_scope_root()`)
- Lines 338-400: `_save_artifact_sync()` - **actual disk write**
  - Line 347-351: Computes artifact directory
  - Line 352: `artifact_dir.mkdir(parents=True, exist_ok=True)`
  - Lines 354-358: Version numbering and directory creation
  - Lines 364-377: Writes content (bytes or text)
  - Lines 385-392: Writes `metadata.json`
- Lines 420-471: `_load_artifact_sync()` - reads from disk
- Lines 487-516: `_list_artifact_keys_sync()` - enumerates artifacts

#### InvocationContext (`.venv/.../google/adk/agents/invocation_context.py`)
- Contains `artifact_service: Optional[BaseArtifactService]`

#### Runner artifact delta tracking (`.venv/.../google/adk/runners.py`)
- Line 124: `artifact_service: Optional[BaseArtifactService]`
- Lines 645-699: `_compute_artifact_delta_for_rewind()` - tracks artifact versions

#### Callback context (`.venv/.../google/adk/agents/callback_context.py`)
- Lines 110-119: `save_artifact()` - calls service and updates `artifact_delta`
- Line 118: `self._event_actions.artifact_delta[filename] = version`

#### Event actions (`.venv/.../google/adk/events/event_actions.py`)
- Line 69: `artifact_delta: dict[str, int]` - tracks filename -> version mappings

---

## Entrypoint and Toggle Mechanism

### CLI Entrypoint
The ADK CLI discovers the `app` symbol in `rlm_adk/agent.py`:
- Line 459: `app = create_rlm_runner(model=_root_agent_model())`
- Used by `adk run rlm_adk` and `adk web`

### Programmatic Entrypoint
```python
# rlm_adk/agent.py lines 348-447
def create_rlm_runner(
    model: str,
    ...
    artifact_service: BaseArtifactService | None = None,
    ...
) -> Runner:
```

### Toggle / Configuration

| Mechanism | How | Effect |
|-----------|-----|--------|
| **Default** | Pass nothing | Uses `FileArtifactService(root_dir=".adk/artifacts")` |
| **In-memory** | `artifact_service=InMemoryArtifactService()` | Volatile, no disk writes |
| **Custom root** | `FileArtifactService(root_dir="/custom/path")` | Changes storage location |
| **Disable** | Set artifact_service field to None | All save ops gracefully skip with debug log |
| **No env var toggle** | N/A | No direct env var to toggle on/off |

---

## Full Call Chain: Entrypoint to Disk Write

```
1. CLI: adk run rlm_adk
   └─> Discovers app symbol (rlm_adk/agent.py:459)

2. Programmatic: create_rlm_runner()
   └─> rlm_adk/agent.py:419-446
   └─> Resolves artifact_service (line 439-440):
       default: FileArtifactService(root_dir=".adk/artifacts")
   └─> Creates Runner(artifact_service=artifact_service)

3. Runner.run_async(user_id, session_id, new_message)
   └─> Sets ctx.artifact_service before invocation

4. RLMOrchestratorAgent._run_async_impl()
   └─> Iteration loop (orchestrator.py:92+)
   └─> save_repl_code(ctx, ...) → artifacts.py:110-150
   └─> save_repl_output(ctx, ...) → artifacts.py:62-107
   └─> save_final_answer(ctx, ...) → artifacts.py:198-236

5. Each save function calls:
   └─> ctx.artifact_service.save_artifact(app_name, user_id, session_id, filename, artifact)

6. FileArtifactService.save_artifact() [async wrapper]
   └─> file_artifact_service.py:311-336
   └─> asyncio.to_thread(self._save_artifact_sync, ...)

7. FileArtifactService._save_artifact_sync() [disk write]
   └─> file_artifact_service.py:338-400
   └─> mkdir, version numbering, write_bytes/write_text, metadata.json

8. Event tracking:
   └─> artifact_delta[filename] = version (callback_context.py:118)
   └─> Yielded in Event.actions.artifact_delta
```

---

## Artifact Naming Conventions (from `artifacts.py`)

| Type | Filename Pattern |
|------|-----------------|
| REPL code | `repl_code_iter_{iteration}_turn_{turn}.py` |
| REPL output | `repl_output_iter_{iteration}.txt` |
| Worker results | `worker_{name}_iter_{iteration}.txt` |
| Final answer | `final_answer.md` |

## Artifact Lifecycle
1. **Creation**: Automatic during orchestrator execution
2. **Versioning**: Incremental integer (0, 1, 2, ...)
3. **Metadata**: JSON per version (filename, mime_type, canonical_uri, custom_metadata)
4. **Scoping**: Session-scoped (default) or user-scoped with `user:` prefix
5. **Operations**: Save, load, list, delete via artifact service API
