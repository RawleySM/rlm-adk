# Polya Understand Phase: GAP-DC-009

**Five broken fixtures not excluded from CI**

---

## 1. Problem Restatement

Five provider-fake fixture JSON files are known to be incompatible with the current thread bridge execution semantics, yet they are not excluded from the parametrized test discovery in `test_provider_fake_e2e.py`. The `_all_fixture_paths()` function globs every `*.json` file in the fixture directory, filters only by `index.json` and by membership in `_WORKER_FIXTURE_EXCLUSIONS`, and these five fixtures appear in neither filter. They will therefore be collected by pytest as `test_fixture_contract[<name>]` parametrize IDs, run through the real production pipeline, and fail -- either silently (if CI does not gate on them) or loudly (if CI does gate). Either way, the test suite's signal is degraded: failures that are known-broken rather than genuine regressions consume attention and erode trust in the suite.

## 2. Exact Objective

Produce a state where these five fixtures either:
- (a) are excluded from automatic parametrized discovery so they do not generate false-negative test results, or
- (b) are updated to work correctly under thread bridge execution semantics and pass the contract runner, or
- (c) are retired (deleted) with documentation explaining why.

The minimum safe deliverable is (a). The correct long-term deliverable is (b) for salvageable fixtures and (c) for those that are architecturally obsolete.

## 3. Knowns / Givens

### Data

| Fixture | On disk | In `_WORKER_FIXTURE_EXCLUSIONS` | In `index.json` | Failure mode |
|---|---|---|---|---|
| `adaptive_confidence_gating` | Yes | No | Yes | `llm_query_batched` response sequences designed for AST-rewriter path |
| `deterministic_guardrails` | Yes | No | Yes | `llm_query` / `llm_query_batched` response sequences designed for AST-rewriter path |
| `full_pipeline` | Yes | No | Yes | `llm_query_batched` response sequences designed for AST-rewriter path |
| `structured_control_plane` | Yes | No | Yes | `llm_query_batched` response sequences designed for AST-rewriter path |
| `fake_polya_t4_debate` | Yes | No | **No** | Hard `ModuleNotFoundError` -- imports from deleted `rlm_repl_skills` namespace |

### Rules

- `_all_fixture_paths()` discovers fixtures by globbing `FIXTURE_DIR/*.json`, excluding `index.json` and names in `_WORKER_FIXTURE_EXCLUSIONS`.
- `test_fixture_contract` is parametrized over `_all_fixture_paths()`, so any fixture not excluded is collected.
- The contract runner executes fixtures through the real production pipeline (`create_rlm_runner` -> `Runner.run_async`).
- Under thread bridge semantics, `llm_query()` and `llm_query_batched()` are sync callables that dispatch via `asyncio.run_coroutine_threadsafe()` to child orchestrators at depth+1. Each child orchestrator makes multiple API calls (its own REPL tool loop), not a single API call as old leaf `LlmAgent` workers did.
- The AST rewriter that previously detected and rewrote `llm_query()` calls in REPL code has been deleted. `llm_query` is now a real sync callable injected into REPL globals via the thread bridge.
- The `rlm_repl_skills` namespace (source-expansion-based skill system) has been replaced by the ADK `SkillToolset` integration and the `rlm_adk/skills/loader.py` system.

### Context

- The thread bridge migration (Plan B, 27 TDD cycles) was completed on 2026-03-24.
- `rlm_adk_docs/thread_bridge.md` explicitly lists these 5 fixtures under "Known Remaining Work."
- `MEMORY.md` also documents them as known open issues.
- No `xfail` or `skip` markers reference these fixtures anywhere in the test suite.

### Constraints

- **AR-CRIT-001**: State mutation must go through `tool_context.state`, `callback_context.state`, `EventActions(state_delta={})`, or `output_key`. Never `ctx.session.state[key] = value` in dispatch closures.
- **Thread safety**: The thread bridge crosses a ContextVar visibility boundary. Sync REPL code runs in a worker thread; async dispatch runs in the event-loop thread. Data flows only through function arguments and return values.
- **Backward compatibility**: Any fixture update must produce the same semantic behavior (same contract assertions pass) while using thread bridge dispatch semantics instead of AST-rewriter semantics.
- **Response sequence depth**: Under the old AST-rewriter, each `llm_query()` call consumed exactly 1 response from the fixture's scripted response list (one API call per worker). Under thread bridge, each `llm_query()` spawns a child orchestrator that consumes multiple responses (at minimum: one for the child reasoning agent's `execute_code` or `set_model_response` call, potentially more for its tool loop iterations).

## 4. Unknowns

1. **How many responses does a child orchestrator consume per `llm_query()` dispatch under thread bridge?** At minimum 1 (if the child immediately emits `set_model_response`), but the contract runner's `FakeGeminiServer` `ScenarioRouter` must serve enough responses for each child's full tool loop.

2. **Are any of the 4 `llm_query_batched` fixtures salvageable with reasonable effort?** This depends on whether the fixture's logical scenario (confidence gating, guardrails, pipeline, control plane) can be re-expressed with thread-bridge-compatible response sequences, or whether the scenarios were fundamentally coupled to the AST-rewriter's single-call-per-worker assumption.

3. **Is `fake_polya_t4_debate` architecturally obsolete?** It imports from `rlm_repl_skills.polya_understand_t4_debate`, which now lives under `rlm_adk/skills/obsolete/`. The skill system has been entirely replaced. Updating this fixture would require either restoring the old skill or porting the T4 debate skill to the new `SkillToolset`-based system.

4. **What is the actual CI behavior today?** Do these fixtures produce ERROR (collection failure), FAIL (assertion failure), or are they silently skipped by some other mechanism?

## 5. Definitions / Clarified Terms

- **AST rewriter**: The now-deleted mechanism that statically analyzed REPL code for `llm_query()` calls, rewrote them to async dispatch calls, and routed each call to a single-shot `LlmAgent` worker. Deleted as part of thread bridge migration.
- **Thread bridge**: The replacement mechanism (`rlm_adk/repl/thread_bridge.py`) where `llm_query()` is a real sync callable that uses `asyncio.run_coroutine_threadsafe()` to dispatch to a child `RLMOrchestratorAgent` at depth+1.
- **`_WORKER_FIXTURE_EXCLUSIONS`**: A set of fixture stems in `test_provider_fake_e2e.py` that are filtered out of `_all_fixture_paths()` discovery. Fixtures in this set are not collected for `test_fixture_contract` parametrization.
- **Provider-fake fixture**: A JSON file containing a scripted sequence of HTTP responses that the `FakeGeminiServer` serves to the production pipeline, plus `expected` contract assertions.
- **Response sequence depth**: The number of API responses a fixture must provide per logical `llm_query()` call. Under AST rewriter: 1. Under thread bridge: N >= 1 (depends on child orchestrator tool loop length).
- **`rlm_repl_skills` namespace**: The old source-expansion-based skill system where `from rlm_repl_skills.X import Y` in REPL code was intercepted and replaced with inlined source. Deleted in Phase 0B of thread bridge migration.

## 6. Facts vs Assumptions

### Confirmed Facts

- All 5 fixture files exist on disk at `tests_rlm_adk/fixtures/provider_fake/`.
- None of the 5 are in `_WORKER_FIXTURE_EXCLUSIONS`.
- None of the 5 have `xfail` or `skip` markers anywhere in the test suite.
- `fake_polya_t4_debate` imports from `rlm_repl_skills.polya_understand_t4_debate` -- a namespace that no longer exists as a live import path (moved to `rlm_adk/skills/obsolete/`).
- `fake_polya_t4_debate` is absent from `index.json`.
- The other 4 fixtures are present in `index.json`.
- The AST rewriter has been deleted; `llm_query()` is now a sync thread-bridge callable.
- `rlm_adk_docs/thread_bridge.md` and `MEMORY.md` both document these 5 as known remaining work.
- The 4 non-debate fixtures use `llm_query_batched` with response sequences that assumed 1 API call per worker dispatch.

### Assumptions

- **These fixtures currently fail when run.** This is highly likely but has not been verified in this analysis by actually running them. The `fake_polya_t4_debate` will fail with `ModuleNotFoundError` immediately. The other 4 will likely fail with response exhaustion or mismatched caller sequences.
- **CI collects and runs these fixtures.** The `_all_fixture_paths()` function will discover them; whether CI actually runs the `provider_fake` marker group depends on CI configuration (not inspected here).
- **The 4 `llm_query_batched` fixtures are salvageable.** Their logical scenarios (confidence gating, guardrails, multi-phase pipeline, control plane) are domain-valuable and could be re-expressed with updated response sequences. But this is an assumption about effort, not a verified fact.
- **`fake_polya_t4_debate` is not worth porting.** It tests a specific obsolete skill (`polya_understand_t4_debate`) through a deleted import mechanism. This assumption could be wrong if the T4 debate workflow is still strategically important.

## 7. Representation

```
                   _all_fixture_paths()
                          |
                   glob("*.json")
                          |
              filter: not index.json
              filter: stem not in _WORKER_FIXTURE_EXCLUSIONS
                          |
          +---------------+---------------+
          |                               |
    INCLUDED fixtures               EXCLUDED fixtures
    (parametrized as                (not collected)
     test_fixture_contract[X])
          |
    +-----+-----+-----+-----+
    |     |     |     |     |
   ACG   DG   FP   SCP  FPTD   <-- the 5 broken fixtures
                                    (should be excluded but are not)
    |     |     |     |     |
    v     v     v     v     v
  contract_runner.run_fixture_contract()
    |
    v
  FakeGeminiServer + real production pipeline
    |
    v
  FAILURE (response sequence mismatch or ModuleNotFoundError)
```

Legend: ACG = adaptive_confidence_gating, DG = deterministic_guardrails,
FP = full_pipeline, SCP = structured_control_plane, FPTD = fake_polya_t4_debate

### Failure mode detail

```
fake_polya_t4_debate:
  REPL code: "from rlm_repl_skills.polya_understand_t4_debate import ..."
  -> ModuleNotFoundError (namespace deleted)
  -> execute_code returns error
  -> contract assertions fail

Other 4 fixtures:
  REPL code calls llm_query_batched(prompts)
  -> thread bridge dispatches K child orchestrators
  -> each child orchestrator consumes N responses (N >= 2: tool call + response)
  -> fixture has only 1 response per worker (designed for old 1-call workers)
  -> FakeGeminiServer runs out of scripted responses or serves wrong caller
  -> contract assertions fail (caller sequence mismatch, missing results)
```

## 8. Problem Type Classification

This is a **test infrastructure integrity / fixture-compatibility** problem with two sub-problems:

1. **Immediate safety problem**: Known-broken test cases are collected and run without exclusion, degrading test suite signal. This is a configuration/exclusion problem with a mechanical fix.

2. **Deferred migration problem**: The fixture response sequences encode assumptions about the old AST-rewriter dispatch model (1 API call per worker). Updating them to thread bridge semantics requires understanding how many API calls each child orchestrator makes and restructuring the scripted response lists accordingly. This is a fixture engineering problem.

## 9. Well-Posedness Judgment

The problem is **well-posed for the immediate safety fix** (option a: add to exclusions). The 5 fixture names are known, the exclusion mechanism is understood, and the code change is mechanical.

The problem is **under-specified for the long-term fix** (option b: update fixtures). Updating the response sequences requires determining the exact number and order of API calls each child orchestrator will make under thread bridge dispatch, which depends on the child orchestrator's tool loop behavior -- a runtime property that must be empirically determined or carefully calculated from the orchestrator's logic.

## 10. Success Criteria

### Minimum (immediate safety)

- [ ] All 5 fixture names are added to `_WORKER_FIXTURE_EXCLUSIONS` in `test_provider_fake_e2e.py`.
- [ ] A comment in the exclusion set explains these are thread-bridge-incompatible fixtures pending migration.
- [ ] `_all_fixture_paths()` no longer returns any of the 5 paths.
- [ ] The existing passing tests continue to pass (no regressions from the exclusion change).
- [ ] `ruff check` and `ruff format --check` pass on the modified file.

### Long-term (fixture migration)

- [ ] Each salvageable fixture has response sequences updated for thread bridge dispatch semantics (child orchestrator multi-call pattern).
- [ ] Each updated fixture passes `test_fixture_contract[<name>]` through the real production pipeline.
- [ ] Contract assertions (caller sequence, tool results, observability state) validate correctly.
- [ ] `fake_polya_t4_debate` is either ported to the new skill system or retired with documentation.
- [ ] The "Known Remaining Work" section in `rlm_adk_docs/thread_bridge.md` is updated.
- [ ] `MEMORY.md` is updated to remove these from "Known Open Issues."

## 11. Operational Problem Statement

**Given** 5 provider-fake fixture JSON files that encode response sequences incompatible with thread bridge dispatch semantics (4 use `llm_query_batched` with 1-response-per-worker assumptions; 1 imports from a deleted namespace), and **given** that the test discovery mechanism (`_all_fixture_paths()`) will collect them for parametrized execution because they are not in `_WORKER_FIXTURE_EXCLUSIONS`,

**produce** a code change to `tests_rlm_adk/test_provider_fake_e2e.py` that adds all 5 fixture stems to `_WORKER_FIXTURE_EXCLUSIONS` with an explanatory comment, preventing them from generating false-negative test results,

**subject to** the constraints that (1) no existing passing test is broken, (2) the change passes linting, and (3) the exclusion comment references the thread bridge migration as the reason, enabling future engineers to find and update these fixtures when the migration work is prioritized.

---

## Key Files

- `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_provider_fake_e2e.py` -- test file with `_WORKER_FIXTURE_EXCLUSIONS` and `_all_fixture_paths()`
- `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/adaptive_confidence_gating.json`
- `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/deterministic_guardrails.json`
- `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/full_pipeline.json`
- `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/structured_control_plane.json`
- `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/fake_polya_t4_debate.json`
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/thread_bridge.py` -- thread bridge implementation
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` -- `llm_query_batched_async` dispatch logic
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/thread_bridge.md` -- documents these as known remaining work
