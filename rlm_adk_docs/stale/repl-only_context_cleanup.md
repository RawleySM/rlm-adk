---
name: REPL-only context cleanup
overview: Remove `RLMAdkEngine`, `context_payload`, and `QueryMetadata` entirely. The reasoning agent loads all context via REPL code. Rewrite prompts to match. Delete all dead code.
todos:
  - id: delete-engine
    content: Delete RLMAdkEngine class from agent.py, update __init__.py exports
    status: in_progress
  - id: delete-query-metadata
    content: Delete QueryMetadata class from types.py
    status: pending
  - id: clean-state-keys
    content: Remove dead context metadata state keys from state.py
    status: pending
  - id: clean-local-repl
    content: Remove load_context, add_context, get_context_count, context_payload param from LocalREPL
    status: pending
  - id: rewrite-static-instruction
    content: "Rewrite RLM_STATIC_INSTRUCTION: remove context variable references, update examples to REPL-originated loading"
    status: pending
  - id: rewrite-dynamic-instruction
    content: "Simplify RLM_DYNAMIC_INSTRUCTION: remove context metadata, keep repo_url and root_prompt"
    status: pending
  - id: rewrite-user-prompts
    content: "Update USER_PROMPT, USER_PROMPT_WITH_ROOT, build_user_prompt: remove context references and context_count param"
    status: pending
  - id: clean-prompts-module
    content: Delete build_rlm_system_prompt() and QueryMetadata import from prompts.py
    status: pending
  - id: clean-orchestrator
    content: Remove context_payload, system_prompt, QueryMetadata usage, context metadata state injection from orchestrator
    status: pending
  - id: clean-agent-factory
    content: Remove context_payload and system_prompt from create_rlm_orchestrator(), add default WorkerPool creation
    status: pending
  - id: update-tests
    content: "Update all test files: remove engine tests, QueryMetadata tests, context-loading tests, update prompt/import/state tests"
    status: pending
isProject: false
---

# REPL-Only Context: Remove Engine and Pre-Loaded Context

## Guiding Principle

The reasoning agent loads all data itself via REPL code (`open()`, repomix, etc.), guided by `root_prompt`. There is no pre-loaded `context` variable. `RLMAdkEngine` is legacy wrapper code -- ADK CLI or the caller owns the runner.

## What Gets Deleted

### `RLMAdkEngine` class ([agent.py](rlm_adk/agent.py) lines 128-317)

The entire class. It wraps ADK boilerplate (App, Runner, Session, plugin wiring) that callers or `adk run`/`adk web` handle natively. The orchestrator already manages WorkerPool wiring and persistent REPL reuse.

### `QueryMetadata` class ([types.py](rlm_adk/types.py) lines 220-266)

No pre-loaded context to introspect. Entire class deleted.

### `build_rlm_system_prompt()` ([prompts.py](rlm_adk/utils/prompts.py) lines 217-246)

Builds metadata from `QueryMetadata`. Dead without it.

### Context-loading methods in `LocalREPL` ([local_repl.py](rlm_adk/repl/local_repl.py))

- `load_context()` (line 246)
- `add_context()` (lines 250-285)
- `get_context_count()` (lines 312-314)
- `_context_count` instance variable (line 181)
- `context_payload` parameter on `__init__` (line 173) and its `if context_payload` block (lines 202-204)

### Dead state keys in ([state.py](rlm_adk/state.py))

- `TEMP_CONTEXT_TYPE`, `TEMP_CONTEXT_TOTAL_LENGTH`, `TEMP_CONTEXT_LENGTHS` (lines 34-36)
- `DYN_CONTEXT_TYPE`, `DYN_CONTEXT_TOTAL_LENGTH`, `DYN_CONTEXT_LENGTHS` (lines 43-45)
- `CONTEXT_COUNT` (line 29)
- `context_payload_key()` (lines 112-114)

### Dead orchestrator field

- `system_prompt: str = ""` on `RLMOrchestratorAgent` (line 70) -- the comment says it is unused; `static_instruction` on the reasoning agent handles it
- `context_payload: Any = None` (line 71)

---

## What Gets Rewritten

### 1. `RLM_STATIC_INSTRUCTION` ([prompts.py](rlm_adk/utils/prompts.py) lines 18-196)

Current problem: Lines 21-22 promise a pre-loaded `context` variable. All code examples reference `context`.

Changes:

- Replace the "initialized with" section: instead of "A `context` variable that contains extremely important information", explain that the REPL has `open()`, `__import__`, and filesystem access, and the agent should load data referenced in the query
- Replace code examples that do `context[:10000]` with examples showing `open("/path/to/file.txt")` and `from repomix import RepoProcessor`
- The repomix section (lines 105-196) stays mostly as-is -- it already shows REPL-originated loading
- Keep `llm_query`, `llm_query_batched`, `SHOW_VARS`, `FINAL`/`FINAL_VAR` documentation unchanged

### 2. `RLM_DYNAMIC_INSTRUCTION` ([prompts.py](rlm_adk/utils/prompts.py) lines 207-214)

Remove context metadata lines. Keep `repo_url` and `root_prompt`:

```
Repository URL: {repo_url?}
Original query: {root_prompt?}
```

### 3. `USER_PROMPT` and `USER_PROMPT_WITH_ROOT` ([prompts.py](rlm_adk/utils/prompts.py) lines 249-250)

Remove "which contains the context" and "`context` variable" references. Replace with REPL-centric wording:

```python
USER_PROMPT = """Think step-by-step on what to do using the REPL environment to answer the prompt.\n\nUse the REPL to load and analyze any data referenced in the prompt, querying sub-LLMs by writing to ```repl``` tags, and determine your answer. Your next action:"""
```

### 4. `build_user_prompt()` ([prompts.py](rlm_adk/utils/prompts.py) lines 253-280)

- Remove `context_count` parameter entirely
- Remove the multi-context notice block (lines 269-271)
- Keep `history_count` for persistent mode
- Update iteration-0 safeguard to say "You have not interacted with the REPL environment yet" (drop "or seen your context")

### 5. Orchestrator `_run_async_impl` ([orchestrator.py](rlm_adk/orchestrator.py))

- Remove `QueryMetadata` import and usage (line 45, 118)
- Remove the entire context metadata state injection block (lines 117-151): no more `TEMP_CONTEXT_TYPE`, `DYN_CONTEXT_TYPE`, `context_lengths_display`, etc.
- Simplify initial state to just flow-control keys + root_prompt + repo_url
- REPL init (line 92): `LocalREPL(depth=1)` -- no `context_payload`
- Remove `context_count` from `build_user_prompt` call (line 174, 177)
- Remove state key imports for deleted keys (lines 23-26, 28-30)

### 6. `create_rlm_orchestrator()` ([agent.py](rlm_adk/agent.py) lines 81-116)

- Remove `context_payload` parameter
- Remove `system_prompt` parameter (dead -- orchestrator field being removed)
- Add default WorkerPool creation: if `worker_pool` is None, create `WorkerPool(default_model=model)`
- Remove `context_payload` and `system_prompt` from kwargs dict

### 7. `root_agent` module-level symbol ([agent.py](rlm_adk/agent.py) line 125)

Stays as-is. With `context_payload` removed from the factory, this naturally works for `adk run`/`adk web`.

### 8. `__init__.py` (**[init**.py](rlm_adk/__init__.py))

Replace `RLMAdkEngine` export with `create_rlm_orchestrator`:

```python
from rlm_adk.agent import create_rlm_orchestrator, create_reasoning_agent
__all__ = ["create_rlm_orchestrator", "create_reasoning_agent"]
```

---

## Test Updates

- **[test_adk_imports.py](tests_rlm_adk/test_adk_imports.py)**: Replace `RLMAdkEngine` import assertions with `create_rlm_orchestrator`
- **[test_adk_orchestrator_loop.py](tests_rlm_adk/test_adk_orchestrator_loop.py)**: Remove `TestCompletionContractShape` (tests `RLMAdkEngine`); update `LocalREPL(context_payload=...)` calls to plain `LocalREPL()`
- **[test_adk_types.py](tests_rlm_adk/test_adk_types.py)**: Delete `TestQueryMetadata` class (lines 228-261). Keep `TestRLMChatCompletion`, `TestUsageSummary`, etc. (still used by REPL)
- **[test_adk_prompts.py](tests_rlm_adk/test_adk_prompts.py)**: Delete `TestBuildRlmSystemPrompt` class. Update `TestSystemPromptContent` to check for new REPL-loading language instead of `context` variable. Update `TestBuildUserPrompt` to remove `context_count` tests
- **[test_adk_state_schema.py](tests_rlm_adk/test_adk_state_schema.py)**: Remove `test_context_payload_key` and imports of deleted keys
- **[test_adk_persistence.py](tests_rlm_adk/test_adk_persistence.py)**: Remove/rewrite context accumulation tests. Keep history persistence tests
- **[test_adk_repl_local.py](tests_rlm_adk/test_adk_repl_local.py)**: Remove context-loading tests. Keep code execution, `FINAL_VAR`, `SHOW_VARS`, `llm_query` tests
- **[conftest.py](tests_rlm_adk/conftest.py)**: Remove `repl_with_context`, `repl_with_dict_context`, `repl_with_list_context` fixtures (replace with plain `LocalREPL()` fixtures)

---

## What Stays Unchanged

- `callbacks/reasoning.py` -- content-agnostic, reads `TEMP_MESSAGE_HISTORY`
- `callbacks/worker.py` -- unrelated
- `plugins/*` -- observe-only, no context assumptions
- `dispatch.py` -- WorkerPool internals unchanged
- `types.py` -- `RLMChatCompletion`, `UsageSummary`, `ModelUsageSummary`, `REPLResult`, `CodeBlock`, `RLMIteration`, `RLMMetadata` all stay (used by REPL and orchestrator)
- `local_repl.py` -- `add_history()`, `get_history_count()`, `execute_code()`, `execute_code_async()`, safe builtins all stay

