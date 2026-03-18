<!-- generated: 2026-03-16 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Create User-Provided Context REPL Parse Replay Fixture

## Context

The existing `test_user_context.json` replay fixture uses toy inline strings (93 chars, 89 chars) and does not verify that the agent actually processes multi-file-type context through the REPL. Before running the full understand benchmark, we need a simpler replay fixture that confirms user-provided context loads correctly with diverse file types (.json, .txt, .md) and that the agent can iterate over and summarize the content programmatically via `execute_code` REPL calls — not just from the dynamic instruction manifest.

## Original Transcription

> Look at the replay fixtures for running live evaluations. Determine if we have a replay fixture for the user provided context load. If we don't, build a user provided context fixture that would include a simple "summarize what the context is" prompt. I think we might have something similar for the actual understand benchmark, but I don't want to run that complicated prompt yet because I want to make sure that we have the user context working first. So please generate that fixture and point it to the same directory maybe as what we had before. Ensure that that directory has different file types. I have another directory in the benchmark folder that includes PDFs that we can use. But regardless, I want a user provided context replay fixture that's just simply confirming that that loads up and the agent can read what's in that folder set from and actually parse it through the REPL.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Context-Fixture` teammate to create a new replay fixture at `tests_rlm_adk/replay/test_user_context_repl_parse.json`.**

   The fixture must:
   - Pre-seed `user_provided_ctx` in session state (Path B in `rlm_adk/orchestrator.py`, line 380) with the full blended_family corpus from `rlm_adk/eval/understand_bench/corpus/context/generated/blended_family/`
   - Include all 11 files: 4x `.json` (W-2s, 1099-DIV, 1099-INT, prior year 1040), 6x `.txt` (charitable receipt, 2x childcare receipts, email thread, handwritten notes), 1x `.md` (intake notes)
   - Set `user_provided_ctx_exceeded: false`, populate `usr_provided_files_serialized` with all 11 filenames, `usr_provided_files_unserialized: []`
   - Build a correct `user_ctx_manifest` string matching the format in `rlm_adk/orchestrator.py` lines 386-401
   - Set `app:max_iterations: 3` and `app:max_depth: 1` (single depth, enough iterations to parse + summarize)
   - The query must explicitly instruct the agent to use `user_ctx` in the REPL — e.g., "You have pre-loaded context files available as `user_ctx` in the REPL. Write code to iterate over the files, identify each file type and its key data points, then produce a structured summary of all the context provided."
   - The query must force REPL execution (not just a text response) — the purpose of this fixture is to confirm `user_ctx` is accessible as a dict in `repl.globals` and the model writes code to parse it

   **Why the blended_family corpus**: It has the right diversity (3 file extensions, 11 files, structured JSON + freeform text + markdown) and is small enough to fully serialize without exceeding the 500K char budget. PDFs in `real_docs/` cannot be used because `load_user_context()` in `rlm_adk/utils/user_context.py` (line 85) filters to `_TEXTUAL_EXTENSIONS` only.

   *[Added — the transcription didn't mention building `user_ctx_manifest`, but Path B requires it for the dynamic instruction template `{user_ctx_manifest?}` in `rlm_adk/utils/prompts.py` line 114.]*

## Provider-Fake Fixture & TDD

This is a **replay fixture** (not a provider-fake fixture), so the TDD sequence is different — it validates by running `adk run --replay`.

**Fixture:** `tests_rlm_adk/replay/test_user_context_repl_parse.json`

**Essential requirements the fixture must capture:**
- All 11 blended_family files are present in `user_provided_ctx` with their full content (not truncated)
- The `user_ctx_manifest` string lists all 11 files with correct char counts
- The query forces the agent to write REPL code that accesses `user_ctx` keys — not just describe the manifest
- File type diversity is preserved: `.json`, `.txt`, `.md` all present

**Validation sequence:**
1. Run: `.venv/bin/adk run --replay tests_rlm_adk/replay/test_user_context_repl_parse.json rlm_adk`
2. Confirm: Agent writes `execute_code` calls that iterate `user_ctx`
3. Confirm: Agent's summary mentions specific data from the corpus (W-2 wages, childcare amounts, etc.)
4. Confirm: No errors related to missing `user_ctx` key or empty context

**Demo:** Run `uvx showboat` to generate an executable demo document proving the fixture loads and the agent parses context through the REPL.

## Considerations

- **PDFs are excluded**: `_TEXTUAL_EXTENSIONS` in `rlm_adk/utils/user_context.py` (line 14) does not include `.pdf`. The `real_docs/` directory cannot be used for this fixture. If PDF support is needed later, that's a separate feature (add `.pdf` to the extension set + integrate a PDF-to-text library).
- **Path B vs Path A**: Replay fixtures use Path B (pre-seeded session state), not Path A (env var `RLM_USER_CTX_DIR`). The fixture must embed file content directly in the JSON `state.user_provided_ctx` dict.
- **AR-CRIT-001**: Not directly involved — user context is loaded during orchestrator `_run_async_impl` before any dispatch closures run. No state mutation rules are at risk.
- **Existing test_user_context.json**: Leave it in place — it tests the minimal happy path. The new fixture tests realistic multi-file-type context with REPL parsing.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/orchestrator.py` | `_run_async_impl` Path A (env var) | L360-379 | User context loading from directory |
| `rlm_adk/orchestrator.py` | `_run_async_impl` Path B (pre-seeded) | L380-421 | User context loading from session state — used by replay |
| `rlm_adk/state.py` | `USER_PROVIDED_CTX` | L44 | State key constant |
| `rlm_adk/state.py` | `DYN_USER_CTX_MANIFEST` | L50 | Dynamic instruction manifest key |
| `rlm_adk/utils/user_context.py` | `_TEXTUAL_EXTENSIONS` | L14 | File extension filter (no .pdf) |
| `rlm_adk/utils/user_context.py` | `load_user_context()` | L72 | Directory-based context loader |
| `rlm_adk/utils/prompts.py` | `{user_ctx_manifest?}` template | L114 | Dynamic instruction injection point |
| `rlm_adk/eval/understand_bench/corpus/context/generated/blended_family/` | Corpus directory | — | Source of fixture content (11 files) |
| `tests_rlm_adk/replay/test_user_context.json` | Existing fixture | — | Minimal toy fixture (2 inline strings) |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links relevant to this task)
