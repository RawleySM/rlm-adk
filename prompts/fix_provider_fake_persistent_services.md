<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Replace InMemory Services with Persistent Services in Provider-Fake Test Infrastructure

## Context

The provider-fake contract runner (`tests_rlm_adk/provider_fake/contract_runner.py`) currently uses `InMemorySessionService` and `InMemoryArtifactService` for all test runs. This means every provider-fake test produces throwaway sessions and artifacts that cannot be inspected after the test completes. The user has previously requested (2026-03-16) that all agent runs use real persistent services — `SqliteSessionService` with WAL pragmas and `FileArtifactService` — so that test artifacts and session history are inspectable. The `create_rlm_runner()` factory already defaults to these persistent services; the contract runner explicitly overrides them with ephemeral in-memory replacements. This override must be removed so that provider-fake tests get the same service stack as production runs.

## Original Transcription

> Delegate to an agent to review the service and file registry that allows us to use a runner from a different file and have the session service and file service attached to that runner. That should be our default all the time I'm really frustrated that don't have this already implemented in our test fixtures. Especially considering this request was made before

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `ServiceDefault-Agent` teammate to remove `InMemorySessionService` and `InMemoryArtifactService` overrides from `run_fixture_contract_with_plugins()` in `tests_rlm_adk/provider_fake/contract_runner.py` (lines 415-416).**

   Currently:
   ```python
   artifact_service = InMemoryArtifactService()
   session_service = InMemorySessionService()
   ```
   Replace with temp-directory-scoped persistent services so each test run gets isolated but inspectable storage:
   ```python
   from rlm_adk.agent import _default_session_service, _DEFAULT_ARTIFACT_ROOT
   from google.adk.artifacts import FileArtifactService

   # Use a temp-dir-scoped SQLite DB and artifact root per test run
   session_db_path = str(Path(tmpdir) / "session.db") if tmpdir else None
   artifact_root = str(Path(tmpdir) / "artifacts") if tmpdir else _DEFAULT_ARTIFACT_ROOT

   session_service = _default_session_service(db_path=session_db_path)
   artifact_service = FileArtifactService(root_dir=artifact_root)
   ```
   The function already receives a temp directory context for `traces_db_path` — extend this pattern to session and artifact services. Each test run gets its own isolated directory so parallel tests don't collide, but artifacts persist on disk for the test's duration and can be inspected in the `PluginContractResult`.

   Also update `_make_runner_and_session()` (lines 248-291) which is the non-plugin path — it also uses `InMemorySessionService()` at line 283. Apply the same fix.

   **Constraint:** Do NOT remove the `artifact_service` and `session_service` parameters from `create_rlm_runner()`. The fix is to pass persistent services instead of in-memory ones, not to stop passing them.

2. **Spawn a `ResultEnrich-Agent` teammate to update `PluginContractResult` (line 90-99) to expose the temp directory path so callers can inspect artifacts and session DB after a test run.**

   Add fields:
   ```python
   session_db_path: str | None
   artifact_root: str | None
   ```
   Update `run_fixture_contract_with_plugins()` to populate these fields. Update `run_fixture_contract()` to use a temp directory that persists for the caller's scope (currently it uses `TemporaryDirectory` as a context manager that cleans up immediately — the caller needs the ability to inspect before cleanup).

3. **Spawn a `ContractVerify-Agent` teammate to verify all existing provider-fake contract tests still pass with the new persistent services.**

   Run:
   ```bash
   .venv/bin/python -m pytest tests_rlm_adk/ -x -q
   ```
   Fix any failures caused by the service switch (e.g., SQLite file locking, path resolution, cleanup ordering). The most likely issue is that `SqliteSessionService` may need its temp DB directory to exist before initialization — ensure `mkdir -p` equivalent.

4. *[Added — the transcription didn't mention this, but inspectable artifacts are the whole point of this change.]* **Spawn a `ArtifactInspect-Agent` teammate to write a verification test that runs a provider-fake fixture with the new persistent services and asserts that artifacts are actually written to disk.**

   The test should:
   - Run the `fake_recursive_ping` fixture via `run_fixture_contract_with_plugins()`
   - Assert `result.artifact_root` is not None
   - Assert that `repl_code_*.py` artifact files exist on disk under `result.artifact_root`
   - Assert that `final_answer_*.md` artifact file exists on disk
   - Assert that `result.session_db_path` exists and is a valid SQLite DB with session data

## Provider-Fake Fixture & TDD

**Fixture:** No new fixture JSON needed — this modifies the test infrastructure, not the agent behavior.

**Essential requirements the tests must capture:**
- Artifacts are written to real files on disk (not silently swallowed by InMemoryArtifactService)
- Session state persists in a real SQLite DB (not silently held in memory)
- Parallel test runs don't collide (each gets its own temp directory)
- The `PluginContractResult` provides paths that callers can use to inspect post-run
- All 52+ existing contract tests still pass (no regressions)

**TDD sequence:**
1. Red: Write `test_artifacts_persisted_to_disk` asserting artifact files exist after a fixture run. Run, confirm failure (InMemory services don't write files).
2. Green: Replace InMemory services with temp-dir-scoped persistent services. Run, confirm pass.
3. Red: Write `test_session_db_exists` asserting SQLite DB exists. Run, confirm pass (should pass immediately after step 2).
4. Green: Verify full default suite passes.

**Demo:** Run `uvx showboat` to generate an executable demo document proving artifacts and session DB are inspectable after a provider-fake test run.

## Considerations

- **AR-CRIT-001**: No state mutation changes — this only affects service wiring, not state write paths.
- **Test isolation**: Each test run MUST get its own temp directory. Do not use a shared `.adk/` directory for tests — that would cause test pollution.
- **Cleanup**: Temp directories should be cleaned up after test completion via `TemporaryDirectory` context managers, but the `PluginContractResult` must be returned BEFORE cleanup so the caller can inspect.
- **`_default_session_service()` creates parent dirs**: It calls `mkdir -p` on the DB path's parent directory (agent.py lines ~155-160), so passing a temp dir path should work.
- **Prior feedback**: Memory `feedback_no_inmemory_services.md` (2026-03-16) explicitly states: "NEVER default to InMemorySessionService or InMemoryArtifactService for benchmark runs, evaluation harnesses, or any agent execution that should produce observable data."
- **`services.py` is for CLI only**: The `register_services()` function in `services.py` registers URI-scheme factories for `adk run`/`adk web`. Programmatic callers like the contract runner should use `create_rlm_runner()` with explicit service instances, which is what it already does — the fix is just passing persistent ones instead of ephemeral ones.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `tests_rlm_adk/provider_fake/contract_runner.py` | `run_fixture_contract_with_plugins()` | L355 | Main function to fix — uses InMemory services at L415-416 |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `_make_runner_and_session()` | L248 | Non-plugin path — also uses InMemorySessionService at L283 |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `PluginContractResult` | L90 | Dataclass to enrich with artifact/session paths |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `run_fixture_contract()` | L320 | Wrapper that creates TemporaryDirectory — cleanup timing issue |
| `rlm_adk/agent.py` | `create_rlm_runner()` | L531 | Factory — defaults to persistent services when none provided |
| `rlm_adk/agent.py` | `_default_session_service()` | L129 | Creates SqliteSessionService with WAL pragmas |
| `rlm_adk/agent.py` | `_DEFAULT_ARTIFACT_ROOT` | L117 | Default `.adk/artifacts` path |
| `rlm_adk/services.py` | `register_services()` | L56 | CLI-only service registry (not relevant to this fix) |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow "Artifacts & Session" and "Testing" branches)
3. `rlm_adk_docs/artifacts_and_session.md` — detailed service architecture and correct patterns
