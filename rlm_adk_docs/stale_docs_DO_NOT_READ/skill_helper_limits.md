# Research Memo: Imported Skill Helper Capabilities And Limits

> **Status:** Current as of 2026-03-12, branch `main` @ `6d4b147`
> **Scope:** What a single-line imported skill helper can and cannot contain today

---

## 1. Short Answer

A source-expanded skill helper **can** safely contain `llm_query()` and `llm_query_batched()` today, including forwarding `output_schema`. The AST rewriter sees these calls because expansion inlines the helper source into the submitted code **before** AST analysis. However, helpers **cannot** create new state keys, influence dynamic instruction variables, or persist data through ADK-tracked channels without orchestrator/callback/template plumbing outside the helper body. Cross-turn reuse of expanded helpers is unsafe — the helper must be imported and called in the same code block.

---

## 2. What Imported Skill Helpers Can Contain Today

| Capability | Status | Delivery Mode |
|---|---|---|
| `llm_query(prompt, model=...)` | **Implemented and safe** | Source expansion only |
| `llm_query_batched(prompts, model=...)` | **Implemented and safe** | Source expansion only |
| `output_schema=MySchema` forwarding | **Implemented and safe** | Source expansion only |
| Plain Python computation | **Implemented and safe** | Either mode |
| REPL local variable creation | **Implemented and safe** | Either mode |
| Reading `LLMResult.parsed` | **Implemented and safe** | Source expansion only |
| Reading `LLMResult.error` | **Implemented and safe** | Source expansion only |
| Calling other expanded helpers | **Implemented and safe** | Source expansion (same block) |

**How it works (the expansion → rewrite pipeline):**

1. `expand_skill_imports(code)` inlines skill source as function definitions into `exec_code` (repl_tool.py:163)
2. `has_llm_calls(exec_code)` detects `llm_query` / `llm_query_batched` via `ast.walk` over the **expanded** source (repl_tool.py:184)
3. `rewrite_for_async(exec_code)` transforms the expanded source (repl_tool.py:188):
   - `LlmCallRewriter.visit_Call()` rewrites `llm_query(p)` → `await llm_query_async(p)` (ast_rewriter.py:55-67)
   - `_promote_functions_to_async()` promotes any `def` containing `await` to `async def` (ast_rewriter.py:82-119)
   - Promotion is **transitive**: if `foo()` calls promoted `bar()`, `foo` is also promoted
   - Call sites to promoted functions are wrapped with `await`
4. The entire module is wrapped in `async def _repl_exec(): ... return locals()` and compiled

**Test evidence:** `test_skill_expander_ast.py` lines 26-34 (expanded llm_query detected), 46-57 (function promoted to async), 117-140 (full pipeline).

---

## 3. What They Cannot Safely Contain Today

| Limitation | Category | Reason |
|---|---|---|
| `llm_query()` in `repl.globals`-injected helper | **Hard runtime constraint** | AST rewriter is lexical-only; pre-compiled callables are opaque |
| Cross-turn async helper reuse | **Hard runtime constraint** | Rewrite is per submitted code block; later block won't re-expand |
| `tool_context.state[key] = value` writes | **Not implemented** | `tool_context` is not in REPL namespace |
| `callback_context.state[key] = value` writes | **Not implemented** | `callback_context` is not in REPL namespace |
| `EventActions(state_delta={...})` writes | **Not implemented** | No event-yielding mechanism in REPL |
| New dynamic instruction variable creation | **Not implemented** | Requires template + state key + orchestrator seeding |
| Wildcard imports (`from rlm_repl_skills.x import *`) | **Rejected** | skill_registry.py `expand()` method |
| Aliased imports (`import ... as alias`) | **Rejected** | skill_registry.py `expand()` method |
| Plain imports (`import rlm_repl_skills.x`) | **Rejected** | skill_registry.py `expand()` method |
| LLM calls hidden behind aliases/attributes/eval | **Hard runtime constraint** | Lexical detection only matches `llm_query` / `llm_query_batched` by name |

---

## 4. State And Dynamic Instruction Boundaries

### State Writes

A helper can **indirectly** cause state writes through the dispatch accumulator pipeline:

```
helper calls llm_query_async()
  → dispatch closure accumulates obs data in local variables
  → REPLTool calls flush_fn() after code execution (repl_tool.py:272-275)
  → flush_fn() returns accumulated dict, resets accumulators (dispatch.py:693-719)
  → REPLTool writes dict to tool_context.state
```

The keys written are exclusively observability keys (`OBS_CHILD_DISPATCH_COUNT`, `OBS_CHILD_ERROR_COUNTS`, etc.) — the helper cannot influence which keys are written or add custom keys.

A helper **cannot**:
- Write depth-scoped keys like `FINAL_ANSWER@dN`, `REASONING_OUTPUT@dN`
- Create arbitrary state keys through any tracked channel
- Access `tool_context`, `callback_context`, or `EventActions` directly

### Dynamic Instruction Variables

Dynamic instruction resolution uses ADK's built-in `{var?}` template mechanism in `LlmAgent`. The pipeline:

1. Template declared in `RLM_DYNAMIC_INSTRUCTION` (prompts.py:82-86): `{repo_url?}`, `{root_prompt?}`, `{test_context?}`
2. State keys declared in `state.py:35-39`: `DYN_REPO_URL`, `DYN_ROOT_PROMPT`
3. Orchestrator seeds values in `_run_async_impl()` (orchestrator.py:309-327)
4. ADK resolves placeholders from `ctx.session.state` before model call
5. `reasoning_before_model()` (reasoning.py:109-174) extracts and relocates resolved text to system instruction

**A helper cannot create new dynamic instruction variables.** Required participants:

| Participant | File | Lines |
|---|---|---|
| State key constant | `state.py` | 35-39 |
| Template placeholder | `utils/prompts.py` | 82-86 |
| Orchestrator field + seeding | `orchestrator.py` | 309-327 |
| Factory parameter | `agent.py` | `create_rlm_orchestrator()` |
| Callback extraction (optional) | `callbacks/reasoning.py` | 109-174 |

**Note:** `{test_context?}` exists in the template but has no corresponding `DYN_TEST_CONTEXT` constant or seeding code — it is a latent extension point.

---

## 5. Single-Turn vs Cross-Turn Behavior

| Scenario | Behavior | Status |
|---|---|---|
| Import + call in same code block | Expanded, rewritten, works | **Safe** |
| Import in block A, call in block B | Block B sees the function in `repl.locals` but it was defined as sync `def` — call returns a coroutine object | **Unsafe** |
| Helper already in `repl.globals` (pre-compiled) | AST rewriter cannot see internal `llm_query()` calls | **Unsafe** |
| Helper in `repl.globals` with NO `llm_query()` | Works normally as pure Python callable | **Safe** |

**Root cause of cross-turn unsafety:** The AST rewrite pipeline operates on the **submitted code text** of each block independently. A function defined and promoted to `async def` in turn N exists in `repl.locals` as a compiled async function, but turn N+1's submitted code contains only `result = my_helper()` — the rewriter sees no `llm_query()` calls, takes the sync execution path, and the call to an async function returns a coroutine instead of executing it.

---

## 6. Parent vs Child Orchestrator Behavior

When a helper calls `llm_query_async(prompt, model, output_schema)`:

1. Dispatch creates a **child orchestrator** via `create_child_orchestrator()` (dispatch.py:353)
2. Child inherits: config, invocation context, depth bounds, output_schema, shared session state (read-only)
3. Child runs its own reasoning agent with its own REPL (if it has tools)
4. Child results are normalized via `_read_child_completion()` (dispatch.py:199-311)
5. Result returned as `LLMResult` with `.parsed` field from structured output validation

**Output schema forwarding is fully implemented:**
- `llm_query_async(prompt, model, output_schema)` → `_run_child(..., output_schema)` → `create_child_orchestrator(..., output_schema=output_schema)` → child's reasoning agent created with `output_schema=output_schema`
- Self-healing via `WorkerRetryPlugin` + `ReflectAndRetryToolPlugin`
- Validated output in `LLMResult.parsed`

**State isolation:** Child's state deltas are accumulated in a local `_child_state` dict during the child run. They do **not** merge into the parent's session state. Only observability accumulators flow back via `flush_fn()`.

---

## 7. Open Extension Seams

### 7a. `repl.globals` LLM-Call Bridge (Not Implemented)

A `repl.globals`-injected helper could safely wrap `llm_query()` if the helper were pre-wired to call `llm_query_async` directly (bypassing AST rewrite). This would require:
- Injecting `llm_query_async` into the helper's closure at orchestrator setup time
- Making the helper itself `async def`
- Ensuring the REPL execution path detects the `await` in user code that calls it

**Seam:** `orchestrator.py:248-272` (globals injection), `local_repl.py:220-227` (`set_async_llm_query_fns`)

### 7b. Helper-Authored State Creation (Not Implemented)

A helper could write arbitrary state keys if `tool_context` or a state-write proxy were injected into the REPL namespace.

**Seam:** `repl_tool.py:272-275` (flush path), `dispatch.py:693-719` (`flush_fn` return dict). A custom `state_proxy` object in `repl.globals` could accumulate writes and merge them into the `flush_fn` return value.

### 7c. Dynamic Instruction Variable Injection (Not Implemented)

The `{test_context?}` placeholder in `RLM_DYNAMIC_INSTRUCTION` is already present but unwired. A helper could influence this if:
- A `DYN_TEST_CONTEXT` constant were added to `state.py`
- The state proxy (7b) or `flush_fn` path could write it
- ADK would resolve it on the next model call

**Seam:** `state.py:35-39`, `utils/prompts.py:82-86`, `orchestrator.py:309-327`

### 7d. Cross-Turn Skill Persistence (Not Implemented)

The REPL could maintain a registry of "known async helpers" across turns. When a later turn calls a function that exists in this registry, the execution path could force async mode even without detecting `llm_query()` in the submitted code.

**Seam:** `repl_tool.py:184` (the `has_llm_calls` check could be augmented with a registry lookup), `local_repl.py:209` (`self.locals` persists across calls)

---

## 8. Evidence Table

| File | Class/Function | Lines | What It Proves |
|---|---|---|---|
| `repl/skill_registry.py` | `SkillRegistry.expand()` | 58-169 | Only `from rlm_repl_skills.<mod> import <sym>` is supported; source is inlined as text |
| `repl/skill_registry.py` | `_collect_user_defined_names()` | 190-209 | Operates on parsed AST of submitted code, not runtime globals |
| `repl/ast_rewriter.py` | `has_llm_calls()` | 15-36 | Detects `llm_query` / `llm_query_batched` by name via `ast.walk`; lexical only |
| `repl/ast_rewriter.py` | `LlmCallRewriter.visit_Call()` | 55-67 | Rewrites sync calls to `await async_variant()`; preserves all args |
| `repl/ast_rewriter.py` | `_promote_functions_to_async()` | 82-119 | Transitively promotes sync `def` containing `await` to `async def`; iterates until stable |
| `repl/ast_rewriter.py` | `_contains_await()` | 70-79 | Checks direct body only; does NOT descend into nested function/class scopes |
| `repl/ast_rewriter.py` | `rewrite_for_async()` | 161-228 | Parses source text only — no runtime introspection of function objects |
| `tools/repl_tool.py` | `REPLTool.run_async()` | 163 | Expansion happens BEFORE AST rewrite; `exec_code = expansion.expanded_code` |
| `tools/repl_tool.py` | `REPLTool.run_async()` | 184 | `has_llm_calls(exec_code)` inspects EXPANDED code |
| `tools/repl_tool.py` | `REPLTool.run_async()` | 272-275 | `flush_fn()` → `tool_context.state` is the only state write path from dispatch |
| `repl/local_repl.py` | `set_async_llm_query_fns()` | 220-227 | Injects `llm_query_async` into `self.globals`; available at runtime but invisible to AST |
| `repl/local_repl.py` | `execute_code_async()` | 421-427 | Namespace merge: `{**self.globals, **self.locals}` |
| `orchestrator.py` | `_run_async_impl()` | 248-272 | Injects `probe_repo`, `pack_repo`, `shard_repo` as pre-compiled callables (no LLM calls) |
| `orchestrator.py` | `_run_async_impl()` | 258-265 | `sync_llm_query_unsupported` raises error if sync path called in async context |
| `orchestrator.py` | `_run_async_impl()` | 309-327 | Seeds `DYN_REPO_URL`, `DYN_ROOT_PROMPT` into session state |
| `state.py` | Module constants | 35-39 | Only `DYN_REPO_URL` and `DYN_ROOT_PROMPT` declared; no `DYN_TEST_CONTEXT` |
| `utils/prompts.py` | `RLM_DYNAMIC_INSTRUCTION` | 82-86 | Template includes `{test_context?}` — placeholder present but unwired |
| `dispatch.py` | `create_dispatch_closures()` | 105-142 | Creates 3 closures + 6 local accumulators; captures `tool_context` indirectly via `flush_fn` |
| `dispatch.py` | `llm_query_async` closure | 565-603 | Accepts `output_schema` parameter; forwards to `_run_child` |
| `dispatch.py` | `_run_child()` | 313-563 | Child inherits output_schema; results normalized to `LLMResult` with `.parsed` |
| `dispatch.py` | `flush_fn` closure | 693-719 | Returns accumulated obs dict; resets all 6 accumulators |
| `agent.py` | `create_reasoning_agent()` | 188-270 | Uses `instruction=dynamic_instruction` with ADK template resolution |
| `callbacks/reasoning.py` | `reasoning_before_model()` | 109-174 | Extracts ADK-resolved dynamic instruction; relocates to system instruction |

---

## 9. Specific Issue Resolutions

### Issue 1: "A zero-import helper preloaded into repl.globals cannot safely contain llm_query() today."

**TRUE.** A pre-compiled callable in `repl.globals` is opaque to the AST rewriter. The rewriter operates on source text only (ast_rewriter.py:161, `ast.parse(code)`). Internal `llm_query()` calls will not be detected, not rewritten to async, and will either call the sync stub (which raises `RuntimeError` per orchestrator.py:258-265) or return a coroutine object without awaiting it.

### Issue 2: "Code expansion lets the AST rewriter catch llm_query() inside imported skill helpers."

**TRUE.** Expansion inlines skill source as text into `exec_code` (repl_tool.py:163). The rewriter then parses and walks the **expanded** source (repl_tool.py:184-188), finding `llm_query()` calls inside inlined function bodies.

### Issue 3: Exact boundary of Issue 2

- **Same-block import + call:** Works. The expansion and rewrite operate on the full submitted block.
- **Later-block call after prior import:** **Unsafe.** The later block's submitted code contains only the call site, not the function definition. The function exists in `repl.locals` as a compiled object (sync or async from the prior block's rewrite), but the later block's code may take the sync execution path.
- **Helper already in `repl.globals`:** **Does not benefit from expansion.** Only synthetic `from rlm_repl_skills.*` imports trigger expansion.

### Issue 4: Can a helper create...

- **A plain REPL local variable:** Yes. Any assignment in the helper body creates a variable in the REPL namespace after execution.
- **A `tool_context.state[...]` write:** No. `tool_context` is not in the REPL namespace.
- **A `callback_context.state[...]` write:** No. `callback_context` is not in the REPL namespace.
- **An `EventActions(state_delta=...)` write:** No. No event-yielding mechanism exists in the REPL.

### Issue 5: Can a helper mint new state keys that appear in dynamic instruction template resolution?

**No.** The template is fixed at agent creation time (prompts.py:82-86). State keys must be pre-declared (state.py:35-39). The orchestrator must seed them (orchestrator.py:309-327). All three steps are outside the helper's reach.

### Issue 6: Classes/functions required for a state-to-dynamic-instruction bridge

1. `rlm_adk/state.py` — add `DYN_<KEY>` constant (lines 35-39)
2. `rlm_adk/utils/prompts.py` — add `{key?}` to `RLM_DYNAMIC_INSTRUCTION` (lines 82-86)
3. `rlm_adk/orchestrator.py` — add field + seeding in `_run_async_impl()` (lines 309-327)
4. `rlm_adk/agent.py` — add parameter to `create_rlm_orchestrator()` / `create_reasoning_agent()`
5. `rlm_adk/callbacks/reasoning.py` — optionally update extraction in `reasoning_before_model()` (lines 109-174)

---

## 10. Proposed Changes To Open Up These Limitations

### Proposal A: State Write Proxy for Helpers

**Goal:** Let helpers write arbitrary state keys through ADK-tracked channels.

**Mechanism:** Inject a `StateProxy` object into `repl.globals` that accumulates writes. The `flush_fn` path merges proxy writes into `tool_context.state`.

```
# New: rlm_adk/repl/state_proxy.py
class StateProxy:
    def __init__(self):
        self._pending: dict[str, Any] = {}
    def __setitem__(self, key, value):
        self._pending[key] = value
    def flush(self) -> dict[str, Any]:
        out = dict(self._pending)
        self._pending.clear()
        return out
```

**Changes required:**
- `orchestrator.py`: Create `StateProxy`, inject as `repl.globals["state"]`
- `dispatch.py`: `flush_fn()` merges `state_proxy.flush()` into return dict
- `repl_tool.py`: No change (already writes flush dict to `tool_context.state`)

**Risk:** Low. Writes still flow through `tool_context.state` (ADK-tracked). Proxy is read-write within a single REPL execution, flushed and reset between executions.

### Proposal B: Cross-Turn Async Helper Registry

**Goal:** Allow helpers defined in turn N to be safely called in turn N+M.

**Mechanism:** The REPL maintains a set of "known async function names." When `has_llm_calls()` returns `False` but the submitted code calls a function in this set, force the async execution path.

**Changes required:**
- `repl/local_repl.py`: Add `self._async_helper_names: set[str] = set()`. After async execution, scan returned locals for `async def` objects and register their names.
- `tools/repl_tool.py`: After `has_llm_calls()` check, add: `or self.repl.calls_known_async(exec_code)`.
- `repl/ast_rewriter.py`: New function `calls_known_async(code: str, names: set[str]) -> bool` that checks if any `ast.Call` target matches a registered name.

**Risk:** Medium. Must handle name collisions (user redefines a function with the same name as a prior async helper). Mitigate by clearing the registry entry when a new `def` with the same name is detected.

### Proposal C: Wire `{test_context?}` Dynamic Instruction Variable

**Goal:** Activate the already-present `{test_context?}` placeholder.

**Changes required:**
1. `state.py`: Add `DYN_TEST_CONTEXT = "test_context"`
2. `orchestrator.py`: Add `test_context: str | None = None` field, seed in `_run_async_impl()`
3. `agent.py`: Add `test_context` parameter to `create_rlm_orchestrator()`

**Risk:** Very low. The template placeholder already exists. This is pure activation of a latent seam.

### Proposal D: Async-Ready `repl.globals` Injection

**Goal:** Allow `repl.globals`-injected helpers to contain `llm_query()` without source expansion.

**Mechanism:** At orchestrator setup, inject helpers as `async def` closures that capture `llm_query_async` directly:

```python
async def my_helper(prompt, **kwargs):
    return await llm_query_async(prompt, **kwargs)
repl.globals["my_helper"] = my_helper
```

The REPL execution path would need to detect `await` in user code (even if `has_llm_calls()` is False) and use the async path.

**Changes required:**
- `repl/ast_rewriter.py`: Add `has_await_calls(code: str) -> bool` that detects any `await` or call to known async globals
- `tools/repl_tool.py`: Use `has_llm_calls(exec_code) or has_await_calls(exec_code)` as the async path trigger
- `orchestrator.py`: Inject helpers as async closures capturing dispatch functions

**Risk:** Medium. Changes the async detection heuristic. Must ensure sync-only code blocks don't accidentally trigger the async path.

---

## Boundary Statement

**What a single-line imported skill helper can abstract today:**
- Arbitrary Python computation
- One or more `llm_query()` / `llm_query_batched()` calls with full parameter forwarding including `output_schema`
- Reading and processing `LLMResult` values (`.parsed`, `.error`, string content)
- Creating REPL-local variables visible to subsequent code in the **same block**
- Calling other expanded skill helpers (same block)

**What still requires orchestrator / REPLTool / callback / state-template plumbing outside the helper:**
- Any persistent state write through ADK-tracked channels
- Dynamic instruction variable creation or modification
- Cross-turn helper reuse with async LLM calls
- `repl.globals`-injected helpers containing LLM calls
- Observability beyond the automatic dispatch accumulator pipeline
