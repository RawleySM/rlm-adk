<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Add Provider-Fake Fixture for User-Provided Context (Path B)

## Context

The `load_user_context()` function in `rlm_adk/utils/user_context.py` serializes a directory of textual files into a context dict that gets injected into REPL globals as `user_ctx`. The orchestrator has two code paths for this: Path A (env var `RLM_USER_CTX_DIR`) and Path B (pre-seeded `user_provided_ctx` in session state). Existing unit tests in `test_orchestrator_user_ctx.py` cover Path A via monkeypatched env vars, but there is **no provider-fake e2e fixture** that exercises Path B through the full agent pipeline — proving that `user_ctx` is accessible in REPL code and that the manifest appears in the dynamic instruction.

## Original Transcription

> Generate a a provider fake fixture for the user provided context function defined in the utils directory.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Fixture-Author` teammate to create `tests_rlm_adk/fixtures/provider_fake/user_context_preseeded.json`.**

   This fixture exercises the orchestrator's **Path B** (`orchestrator.py` L384-425): pre-seeded `user_provided_ctx` in `initial_state`. The fixture must:

   - Set `config.initial_state` with `user_provided_ctx: {"notes.txt": "meeting notes here", "spec.md": "# Spec\nproject details"}` so the orchestrator's Path B branch fires.
   - Include a reasoning response (call_index 0) that emits `execute_code` with REPL code that reads from `user_ctx` — e.g., `print(user_ctx["notes.txt"])` — proving the dict was injected into REPL globals.
   - Include a final reasoning response (call_index 1) that returns `FINAL(...)` with the extracted content.
   - Set `expected.final_answer` to match the REPL output.
   - Set `expected_state` assertions for:
     - `user_provided_ctx`: `{"$not_none": true}`
     - `user_ctx_manifest`: `{"$contains": "notes.txt"}`
     - `usr_provided_files_serialized`: `{"$type": "list", "$not_empty": true}`
     - `user_provided_ctx_exceeded`: `false`
   - Use `max_iterations: 3`, `retry_delay: 0.0`, `thinking_budget: 0`, `model: "gemini-fake"`.

2. **Spawn a `Contract-Validator` teammate to verify the new fixture passes the contract runner.**

   Run:
   ```bash
   .venv/bin/python -m pytest \
     tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[user_context_preseeded] -v
   ```
   If the fixture doesn't auto-discover (parametrized via `_all_fixture_paths()`), confirm that the fixture file is in the correct directory and the scenario_id matches the filename.

3. **Spawn a `Manifest-Verifier` teammate to add an FMEA test class in `tests_rlm_adk/test_fmea_e2e.py` (or a new file `tests_rlm_adk/test_user_ctx_e2e.py`) that asserts the manifest propagated into the dynamic instruction.**

   The test should use the class-scoped `fmea_result` fixture pattern and assert:
   - `fmea_result.final_state.get("user_ctx_manifest")` contains `"notes.txt"` and `"spec.md"`
   - `fmea_result.final_state.get("user_provided_ctx")` has exactly 2 keys
   - `fmea_result.final_state.get("user_provided_ctx_exceeded")` is `False`
   - The REPL tool result stdout contains the content from `user_ctx["notes.txt"]`

   *[Added — the transcription didn't mention manifest verification, but the orchestrator's Path B builds a manifest string and injects it into `DYN_USER_CTX_MANIFEST` (state.py L50). A fixture that doesn't verify this would miss the primary integration point between user context and the dynamic instruction template.]*

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/user_context_preseeded.json`

**Essential requirements the fixture must capture:**
- The REPL code actually reads `user_ctx["notes.txt"]` and prints its content — proving the dict was injected into REPL globals (not just session state). A naive test that only checks state keys would pass even if the REPL never received the dict.
- The `user_ctx_manifest` state key contains file names and character counts — proving Path B's manifest builder ran. This is the value that flows into `{user_ctx_manifest?}` in the dynamic instruction template.
- The `user_provided_ctx_exceeded` state key is `False` — proving the budget logic correctly reported no overflow when all files fit.
- The fixture uses `initial_state` (not `initial_repl_globals`) to pre-seed context, ensuring the orchestrator's Path B branch is the one that fires (not the contract runner's `_make_repl` shortcut).

**TDD sequence:**
1. Red: Write the fixture JSON. Run `test_fixture_contract[user_context_preseeded]`. Confirm it fails (fixture not yet wired or expectations wrong).
2. Green: Adjust fixture responses/expectations until the contract passes. No production code changes should be needed — Path B already exists in the orchestrator.
3. Red: Write FMEA test class asserting manifest content. Run with `-m ""`. Confirm it fails if manifest is wrong.
4. Green: Adjust expected manifest content to match Path B's actual output format.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the fixture passes end-to-end.

## Considerations

- **No production code changes expected.** Path B in `orchestrator.py` (L384-425) already handles pre-seeded `user_provided_ctx`. This task is purely about adding test coverage for an existing, untested code path.
- **`initial_state` vs `initial_repl_globals`:** The contract runner's `_make_repl()` (contract_runner.py L221-245) handles `initial_repl_globals` independently. To test the orchestrator's Path B, the fixture must use `config.initial_state`, not `config.initial_repl_globals`. Both paths result in `user_ctx` being available in the REPL, but only `initial_state` exercises the orchestrator's wiring.
- **AR-CRIT-001:** Path B reads from `ctx.session.state` (read-only) and writes to `initial_state` which is emitted via `EventActions(state_delta=initial_state)` at L428-432. This is compliant — no direct `ctx.session.state[key] = value` writes.
- **Manifest format:** Path B builds its own manifest (L390-406) rather than calling `UserContextResult.build_manifest()`. The FMEA test should verify the actual Path B format, not assume it matches Path A's `build_manifest()` output.
- **Marker system:** The new fixture will auto-discover via `_all_fixture_paths()` in `test_provider_fake_e2e.py` and get the `provider_fake_contract` marker. The FMEA test class needs `-m ""` to run since FMEA tests carry `provider_fake_extended`.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/utils/user_context.py` | `load_user_context()` | L72 | Core function that serializes a directory into a context dict |
| `rlm_adk/utils/user_context.py` | `UserContextResult.build_manifest()` | L33 | Manifest builder (used by Path A only) |
| `rlm_adk/orchestrator.py` | Path A: env var loading | L364-383 | Env-var-driven context loading (NOT what this fixture tests) |
| `rlm_adk/orchestrator.py` | Path B: pre-seeded state | L384-425 | Pre-seeded `user_provided_ctx` in session state (what this fixture tests) |
| `rlm_adk/orchestrator.py` | `EventActions(state_delta=initial_state)` | L428-432 | Where initial_state is emitted to the event stream |
| `rlm_adk/state.py` | `USER_PROVIDED_CTX` | L44 | State key: `"user_provided_ctx"` |
| `rlm_adk/state.py` | `DYN_USER_CTX_MANIFEST` | L50 | State key: `"user_ctx_manifest"` (dynamic instruction template var) |
| `rlm_adk/state.py` | `USER_PROVIDED_CTX_EXCEEDED` | L45 | State key: `"user_provided_ctx_exceeded"` |
| `rlm_adk/state.py` | `USR_PROVIDED_FILES_SERIALIZED` | L46 | State key: `"usr_provided_files_serialized"` |
| `rlm_adk/state.py` | `USR_PROVIDED_FILES_UNSERIALIZED` | L47 | State key: `"usr_provided_files_unserialized"` |
| `rlm_adk/utils/prompts.py` | `{user_ctx_manifest?}` placeholder | L114 | Dynamic instruction template slot for manifest |
| `tests_rlm_adk/test_orchestrator_user_ctx.py` | Unit tests for Path A | L1-179 | Existing unit coverage (env-var path only) |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `_make_repl()` | L221 | REPL globals pre-loading (separate from Path B) |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `initial_state` session seeding | L285-289 | How `config.initial_state` flows into the session |
| `tests_rlm_adk/fixtures/provider_fake/repl_error_then_retry.json` | Reference fixture | — | Good template: reasoning + worker + REPL code pattern |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow "Testing" and "Dispatch & State" branches)
3. `rlm_adk_docs/testing.md` — fixture schema, contract runner API, "How to Add a Fixture" section
