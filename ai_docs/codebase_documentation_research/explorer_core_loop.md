# RLM-ADK Core Loop & Orchestrator System - Complete Architecture Guide

## Executive Summary

RLM-ADK is a **recursive language model agent framework** built on Google ADK (Agent Development Kit). The system enables an LLM to reason, write code, and recursively spawn child LLMs—all with a collapsed orchestrator pattern, persistent REPL environment, and sophisticated dispatch infrastructure. The key innovation is the complete removal of manual iteration loops in favor of ADK's native tool-calling event loop.

---

## 1. User Entry Points & Runtime Flow

### 1.1 CLI Entry Point
**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` (lines 544-549)

```python
app = create_rlm_app(model=_root_agent_model())
root_agent = app.root_agent
```

The ADK CLI (`adk run rlm_adk`, `adk web`) discovers the module-level `app` symbol, which is a **pre-wired App** with:
- `root_agent`: RLMOrchestratorAgent
- Plugins: ObservabilityPlugin, SqliteTracingPlugin (optional), LangfuseTracingPlugin (optional), REPLTracingPlugin (optional)

### 1.2 Programmatic Entry Point
**Function:** `create_rlm_runner()` (agent.py, lines 443-536)

Returns a fully configured **Runner** with session service, artifact service, and plugins pre-wired. The Runner drives the ADK event loop:

```python
runner = create_rlm_runner(model="gemini-3.1-pro-preview")
session = await runner.session_service.create_session(app_name="rlm_adk", user_id="user")
async for event in runner.run_async(
    user_id="user", session_id=session.id, new_message=content
):
    # Process event...
```

### 1.3 Invocation Context
When the user passes a prompt (root_prompt) and optional repo_url, the orchestrator:

1. Initializes session state with `CURRENT_DEPTH=0` and `REQUEST_ID=uuid()`
2. Yields initial state delta event
3. Yields initial user Content event with root_prompt
4. Delegates to `reasoning_agent.run_async(ctx)` — ADK's native tool loop takes over

---

## 2. Collapsed Orchestrator Architecture

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`

### 2.1 Class Structure: RLMOrchestratorAgent(BaseAgent)

**Fields:**
- `reasoning_agent: LlmAgent` — Sub-agent for main reasoning (depth=0)
- `root_prompt: str | None` — User query
- `repo_url: str | None` — Optional repository URL
- `persistent: bool` — Whether to persist REPL across invocations
- `worker_pool: Any` — DispatchConfig for child dispatch
- `repl: Any` — Optional pre-configured LocalREPL
- `depth: int` — Nesting depth (0 for root)
- `output_schema: Any` — Optional Pydantic schema for structured output

### 2.2 Collapsed Iteration Pattern (Phase 5 Complete)

**The orchestrator does NOT manually iterate.** Instead:

1. **Wire tools at runtime** (orchestrator._run_async_impl, line 282-301):
   - Create REPLTool wrapping LocalREPL
   - Create SetModelResponseTool with output_schema
   - Wire both as `reasoning_agent.tools = [repl_tool, set_model_response_tool]`

2. **Delegate to ADK** (line 336-394):
   - Yield initial state + user Content event
   - Call `async for event in self.reasoning_agent.run_async(ctx)`
   - ADK's native loop handles:
     - Model invocation
     - Tool call detection (execute_code or set_model_response)
     - Tool execution
     - Retry logic (via SetModelResponseTool + WorkerRetryPlugin)

3. **Extract final answer** (line 396-408):
   - Read `output_key` from session state
   - Parse via `_collect_reasoning_completion()`
   - Save artifact
   - Yield final event

### 2.3 State Mutation Rules (AR-CRIT-001)

**CRITICAL INVARIANT:** All state writes MUST yield `Event(actions=EventActions(state_delta={}))`.

- **Correct:** `yield Event(actions=EventActions(state_delta={key: value}))`
- **Wrong:** `ctx.session.state[key] = value` (bypasses ADK event tracking)

The orchestrator strictly adheres to this: see lines 318-322, 363-368, 439-442, 460-464.

---

## 3. Core Components

### 3.1 REPLTool — Execute Code Tool

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py`

**Purpose:** ADK BaseTool that wraps LocalREPL for function-calling execution.

**API:**
- `name = "execute_code"`
- `async def run_async(args: dict[str, str], tool_context: ToolContext) -> dict`
  - Takes `code` parameter (Python source)
  - Returns dict with stdout, stderr, variables, llm_calls_made, call_number

**Key Features:**
1. **AST Detection & Rewriting** (lines 144-172):
   - Calls `has_llm_calls(code)` to detect llm_query/llm_query_batched calls
   - If found, invokes `rewrite_for_async(code)` to transform:
     - `llm_query(p)` → `await llm_query_async(p)`
     - `llm_query_batched(ps)` → `await llm_query_batched_async(ps)`
   - Promotes sync functions to async as needed

2. **Dispatch Flushing** (lines 231-237):
   - After code execution, calls `flush_fn()` to snapshot dispatch accumulators
   - Writes merged state delta to `tool_context.state`

3. **Observability** (lines 99-103, 239-251):
   - Persists submitted code hash, char count, preview
   - Tracks iteration count
   - Writes LAST_REPL_RESULT summary with trace data

4. **Call Limits** (lines 116-123):
   - Enforces max_iterations (default 30)
   - Returns error message when exceeded

### 3.2 LocalREPL — Sandboxed Python Environment

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py`

**Purpose:** Persistent Python namespace with safe builtins and async LM dispatch hooks.

**Public API:**
- `def execute_code(code: str, trace: REPLTrace | None) -> REPLResult`
  - Sync execution with timeout enforcement
  - Serializes access to process-global state via _EXEC_LOCK
- `async def execute_code_async(code: str, repl_exec_fn: Any, trace: REPLTrace | None) -> REPLResult`
  - Async execution (for llm_query-containing code)
  - Injects cwd-aware open() to avoid os.chdir()
- `def set_llm_query_fns(llm_query_fn, llm_query_batched_fn)`
  - Sets sync (unsupported) LM query functions
- `def set_async_llm_query_fns(llm_query_async_fn, llm_query_batched_async_fn)`
  - Sets async LM query functions used by AST-rewritten code

**Persistent State:**
- `self.globals: dict` — Shared builtins and functions (llm_query, probe_repo, etc.)
- `self.locals: dict` — User-defined variables (persist between calls)
- `self.temp_dir: str` — Working directory for code execution

**Safe Builtins:**
- Allowed: print, len, str, int, list, dict, open, __import__, etc.
- Blocked: eval, compile, input, globals

**Helper Functions:**
- `FINAL_VAR(var_name)` — Return a variable as final answer
- `SHOW_VARS()` — Display available variables
- `probe_repo()`, `pack_repo()`, `shard_repo()` — Injected by orchestrator (see section 5.2)

### 3.3 AST Rewriter — Sync-to-Async Bridge

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/ast_rewriter.py`

**Purpose:** Transform synchronous REPL code to async execution by rewriting LM calls.

**Algorithm:**

1. **Detect LM Calls** (`has_llm_calls`, lines 15-36):
   - Parse code to AST
   - Walk for `ast.Call` nodes where func.id in {llm_query, llm_query_batched}
   - Return True if found (else False)

2. **Transform Calls** (`rewrite_for_async`, lines 161-228):
   - Apply `LlmCallRewriter` (lines 39-67):
     - Replace `llm_query` → `llm_query_async`
     - Replace `llm_query_batched` → `llm_query_batched_async`
     - Wrap all in `ast.Await`
   - Promote sync functions to async (`_promote_functions_to_async`, lines 82-119):
     - If a FunctionDef contains await, convert to AsyncFunctionDef
     - Wrap call sites with await (transitive closure)
   - Wrap entire code body in `async def _repl_exec(): ... return locals()`
   - Return transformed ast.Module ready for compile()

3. **Execution** (local_repl.execute_code_async, lines 368-445):
   - Compile AST and extract _repl_exec function
   - Call `await _repl_exec()` to get updated locals
   - Update self.locals with new variables

---

## 4. Dispatch System — Child Orchestrator Spawning

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`

### 4.1 DispatchConfig / WorkerPool

**Class:** `DispatchConfig` (lines 83-102)

Holds model configuration for child dispatch:
```python
class DispatchConfig:
    default_model: str  # e.g., "gemini-2.5-flash"
    other_model: str | None  # Alternative model
    pool_size: int = 5  # Unused (backward compat)
```

**Backward Compat:** `WorkerPool = DispatchConfig` (line 102)

### 4.2 Dispatch Closures

**Function:** `create_dispatch_closures` (lines 105-709)

Returns a 3-tuple: `(llm_query_async, llm_query_batched_async, flush_fn)`

**Local Accumulators** (AR-CRIT-001 compliance):
- `_acc_child_dispatches: int` — Total child calls this iteration
- `_acc_child_batch_dispatches: int` — Batch dispatch count
- `_acc_child_latencies: list[float]` — Latencies in ms
- `_acc_child_error_counts: dict[str, int]` — Error classification counts
- `_acc_child_summaries: dict` — Per-child observability

### 4.3 llm_query_async

**Signature:**
```python
async def llm_query_async(
    prompt: str,
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> LLMResult
```

**Flow:**
1. Delegates to `llm_query_batched_async([prompt], ...)`
2. Returns first result
3. Records trace entry if trace_sink provided

**Returns:** LLMResult (str subclass with metadata)

### 4.4 llm_query_batched_async

**Signature:**
```python
async def llm_query_batched_async(
    prompts: list[str],
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
    _record_trace_entries: bool = True,
) -> list[LLMResult]
```

**Flow:**
1. Spawn K child orchestrators concurrently via `_run_child()`
2. Limit concurrency via `_child_semaphore` (default 3)
3. Accumulate latencies, errors, and per-child summaries
4. Return list[LLMResult] in same order as prompts

**Key Implementation Details:**

- **Depth Limit Check** (lines 315-323):
  - If `depth + 1 >= max_depth`, return error LLMResult immediately
  - Default max_depth=3, overrideable via RLM_MAX_DEPTH env var

- **Child Creation** (lines 337-343):
  - Call `create_child_orchestrator(model, depth+1, prompt, ...)`
  - Pass same dispatch_config for recursive dispatch

- **State Delta Extraction** (lines 347-351):
  - Collect all state_delta from child's events into _child_state

- **Completion Reading** (lines 354-407):
  - Extract final answer, tokens, error category from child
  - Build comprehensive LLMResult with all telemetry

- **Error Accumulation** (lines 646-649):
  - Categorize errors (TIMEOUT, RATE_LIMIT, SCHEMA_VALIDATION_EXHAUSTED, etc.)
  - Increment _acc_child_error_counts[category]

- **Per-Child Summary** (lines 479-543):
  - Write `obs:child_summary@d{depth}f{fanout_idx}` with full details
  - Includes nested dispatch info, structured output outcome, reasoning retries

### 4.5 flush_fn

**Signature:**
```python
def flush_fn() -> dict[str, Any]
```

**Purpose:** Return accumulated state and reset accumulators (called after each REPL execution)

**Delta Keys:**
- OBS_CHILD_DISPATCH_COUNT: Total child calls
- OBS_CHILD_DISPATCH_LATENCY_MS: List of latencies
- OBS_CHILD_TOTAL_BATCH_DISPATCHES: Count of batches
- OBS_CHILD_ERROR_COUNTS: Error category counts
- OBS_STRUCTURED_OUTPUT_FAILURES: Schema validation failures
- OBS_BUG13_SUPPRESS_COUNT: BUG-13 monkey-patch invocations
- Per-child summary dicts (obs:child_summary@...)

**Accumulator Reset:**
- _acc_child_dispatches = 0
- _acc_child_batch_dispatches = 0
- _acc_child_latencies.clear()
- _acc_child_error_counts.clear()
- _acc_child_summaries.clear()
- _acc_structured_output_failures = 0

---

## 5. Agent Factories & Configuration

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`

### 5.1 create_reasoning_agent

**Signature:**
```python
def create_reasoning_agent(
    model: str,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    thinking_budget: int = 1024,
    retry_config: dict[str, Any] | None = None,
    *,
    tools: list | None = None,
    output_schema: type | None = None,
    include_repomix: bool = True,
    name: str = "reasoning_agent",
    output_key: str = "reasoning_output",
) -> LlmAgent
```

**Configuration:**
- **Static Instruction:** System prompt (code examples, REPL docs, repomix docs) — passed WITHOUT template processing
- **Dynamic Instruction:** Template string with {var?} placeholders — ADK resolves at runtime
- **Thinking Budget:** Token budget for extended thinking (0 to disable)
- **Retry Config:** HTTP retry options (attempts=3, exponential backoff)
- **Include Repomix:** Auto-append repomix skill instructions if True
- **include_contents:** Always set to 'default' for ADK tool call history

**Output Schema:**
- When set: ADK injects SetModelResponseTool for structured output validation
- ReasoningOutput schema includes final_answer + reasoning_summary fields

### 5.2 create_child_orchestrator

**Signature:**
```python
def create_child_orchestrator(
    model: str,
    depth: int,
    prompt: str,
    worker_pool: WorkerPool | None = None,
    max_iterations: int = 10,
    thinking_budget: int = 512,
    output_schema: type | None = None,
) -> RLMOrchestratorAgent
```

**Differences from Root:**
- Uses RLM_CHILD_STATIC_INSTRUCTION (no repomix docs, ~1/3 size)
- Depth-suffixed output_key: `reasoning_output@d{depth}`
- include_repomix=False (no skill instructions for children)
- max_iterations defaults to 10 (vs. 30 for root)
- thinking_budget=512 (vs. 1024 for root)

### 5.3 create_rlm_app

**Signature:**
```python
def create_rlm_app(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    plugins: list[BasePlugin] | None = None,
    thinking_budget: int = 1024,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> App
```

Returns **App** with orchestrator as root_agent and plugins wired.

### 5.4 create_rlm_runner

Returns **Runner** with App + SqliteSessionService + FileArtifactService + plugins.

---

## 6. State Management & Depth Scoping

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py`

### 6.1 State Key Categories

**Flow Control:**
- APP_MAX_DEPTH, APP_MAX_ITERATIONS
- CURRENT_DEPTH, ITERATION_COUNT, SHOULD_STOP

**REPL Execution:**
- LAST_REPL_RESULT, FINAL_ANSWER
- REASONING_SUMMARY, REASONING_FINISH_REASON
- REASONING_VISIBLE_OUTPUT_TEXT, REASONING_THOUGHT_TEXT
- REASONING_INPUT_TOKENS, REASONING_OUTPUT_TOKENS

**Context Metadata:**
- REPO_URL, ROOT_PROMPT
- DYN_REPO_URL, DYN_ROOT_PROMPT (for ADK template resolution)

**Observability:**
- OBS_CHILD_DISPATCH_COUNT, OBS_CHILD_ERROR_COUNTS
- OBS_CHILD_DISPATCH_LATENCY_MS
- OBS_REWRITE_COUNT, OBS_REWRITE_TOTAL_MS
- OBS_REASONING_RETRY_COUNT, OBS_REASONING_RETRY_DELAY_MS
- OBS_BUG13_SUPPRESS_COUNT

**Submitted Code:**
- REPL_SUBMITTED_CODE, REPL_SUBMITTED_CODE_HASH, REPL_SUBMITTED_CODE_CHARS, REPL_SUBMITTED_CODE_PREVIEW

### 6.2 Depth Scoping with depth_key()

**Function:** `depth_key(key: str, depth: int = 0) -> str`

**Behavior:**
- `depth == 0`: Return key unchanged
- `depth > 0`: Return f"{key}@d{depth}"

**DEPTH_SCOPED_KEYS Set:** Keys that require independent state per depth level:
```python
{MESSAGE_HISTORY, ITERATION_COUNT, FINAL_ANSWER, LAST_REPL_RESULT, SHOULD_STOP,
 REASONING_INPUT_TOKENS, REASONING_OUTPUT_TOKENS, REASONING_SUMMARY,
 REASONING_FINISH_REASON, REASONING_VISIBLE_OUTPUT_TEXT, REASONING_THOUGHT_TEXT,
 REASONING_THOUGHT_TOKENS, REASONING_RAW_OUTPUT, REASONING_PARSED_OUTPUT,
 REPL_SUBMITTED_CODE, REPL_SUBMITTED_CODE_PREVIEW, REPL_SUBMITTED_CODE_HASH,
 REPL_SUBMITTED_CODE_CHARS}
```

**Example:**
```python
depth_key(ITERATION_COUNT, 0)  # "iteration_count"
depth_key(ITERATION_COUNT, 2)  # "iteration_count@d2"
```

---

## 7. Dynamic Instructions & Skill System

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py`

### 7.1 Static Instruction (RLM_STATIC_INSTRUCTION)

Comprehensive system prompt with:
- Tool descriptions (execute_code, set_model_response)
- REPL environment capabilities (open, import, llm_query, llm_query_batched, SHOW_VARS)
- Data processing strategy examples (chunking, batching, recursive queries)
- Repository processing section (use probe_repo, pack_repo, shard_repo)

**Key Quote:** "When the data isn't that long (<100M characters), split it into chunks and recursively query an LLM over each chunk..."

### 7.2 Dynamic Instruction (RLM_DYNAMIC_INSTRUCTION)

Template with ADK state variable placeholders:
```
Repository URL: {repo_url?}
Original query: {root_prompt?}
Additional context: {test_context?}
```

ADK's before_model_callback (`reasoning_before_model` in callbacks/reasoning.py) merges this resolved instruction into system_instruction.

### 7.3 Child Static Instruction (RLM_CHILD_STATIC_INSTRUCTION)

Condensed version (~1/3 size) without:
- "Repository Processing" section
- Repomix code examples
- Skill instructions

Keeps:
- Tool descriptions
- REPL helpers
- General strategy guidance

### 7.4 Skill System: repomix-repl-helpers

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repomix_skill.py`

**Skill Definition:**
```python
REPOMIX_SKILL = Skill(
    frontmatter=Frontmatter(name="repomix-repl-helpers", description="..."),
    instructions="""...full API docs..."""
)
```

**Discovery & Injection:**
- `build_skill_instruction_block()` returns XML discovery + full instructions
- Appended to static_instruction in create_reasoning_agent (agent.py, line 208)
- Injected once at root level (include_repomix=True for root, False for children)

**Pre-Loaded Functions** (injected by orchestrator into REPL.globals):
- `probe_repo(source)` → Quick stats (files, chars, tokens)
- `pack_repo(source)` → Entire repo as XML string
- `shard_repo(source, max_bytes_per_shard=512000)` → Directory-aware chunks

**Usage Example:**
```python
# In REPL code block:
info = probe_repo("https://github.com/org/repo")
if info.total_tokens < 125_000:
    xml = pack_repo("https://github.com/org/repo")
    analysis = llm_query(f"Analyze: {xml}")
else:
    shards = shard_repo("https://github.com/org/repo")
    analyses = llm_query_batched([f"Analyze: {s}" for s in shards.chunks])
```

---

## 8. Types & Result Structures

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py`

### 8.1 ReasoningOutput (Pydantic Model)

```python
class ReasoningOutput(BaseModel):
    final_answer: str  # Complete answer
    reasoning_summary: str = ""  # Brief summary
```

Used as `output_schema` on reasoning_agent for structured output validation.

### 8.2 LLMResult (str Subclass)

Backward-compatible string that carries metadata:

```python
class LLMResult(str):
    error: bool = False
    error_category: str | None  # TIMEOUT, RATE_LIMIT, SCHEMA_VALIDATION_EXHAUSTED, etc.
    http_status: int | None
    finish_reason: str | None  # STOP, SAFETY, RECITATION, MAX_TOKENS
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    model: str | None = None
    wall_time_ms: float = 0.0
    visible_text: str | None = None
    thought_text: str | None = None
    raw_output: Any | None = None
    parsed: dict | None = None  # Validated structured output
```

**Usage in REPL:**
```python
result = llm_query("prompt")
if result.error:
    if result.error_category == "RATE_LIMIT":
        await asyncio.sleep(5)
```

### 8.3 REPLResult (Dataclass)

```python
@dataclass
class REPLResult:
    stdout: str
    stderr: str
    locals: dict
    execution_time: float | None
    llm_calls: list[RLMChatCompletion]
    trace: dict[str, Any] | None
```

Returned by LocalREPL.execute_code() and LocalREPL.execute_code_async().

### 8.4 RLMChatCompletion (Dataclass)

Record of a single child LLM call:
```python
@dataclass
class RLMChatCompletion:
    root_model: str
    prompt: str | dict[str, Any]
    response: str
    usage_summary: UsageSummary
    execution_time: float
    finish_reason: str | None = None
    thoughts_tokens: int = 0
    visible_response: str | None = None
    thought_response: str | None = None
    raw_response: Any | None = None
    parsed_response: dict[str, Any] | None = None
```

---

## 9. REPL Tracing & Observability

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py`

### 9.1 REPLTrace (Dataclass)

Accumulates per-code-block trace data when RLM_REPL_TRACE > 0:

```python
@dataclass
class REPLTrace:
    start_time: float | None = None
    end_time: float | None = None
    execution_mode: str = "sync"  # "sync" or "async"
    submitted_code_chars: int = 0
    submitted_code_hash: str = ""
    submitted_code_preview: str = ""
    llm_calls: list[dict] = field(default_factory=list)  # [{index, type, elapsed_ms, ...}]
    var_snapshots: list[dict] = field(default_factory=list)  # [{label, time, vars}]
    peak_memory_bytes: int = 0
    exceptions: list[str] = field(default_factory=list)
    data_flow_edges: list[tuple[int, int]] = field(default_factory=list)
    _call_counter: int = 0
```

**Recording Methods:**
- `record_llm_start(index, prompt, type)` — Called when llm_query starts
- `record_llm_end(index, response, elapsed_ms, ...)` — Called when llm_query ends
- `snapshot_vars(namespace, label)` — Capture variable snapshots
- `to_dict()` → JSON-serializable dict

**Trace Levels:**
- Level 0 (default): No tracing overhead
- Level 1: LLM call timing + variable snapshots + data flow tracking
- Level 2: + tracemalloc memory tracking (header/footer code injection)

### 9.2 DataFlowTracker

Detects when one llm_query response feeds into a subsequent prompt:

```python
class DataFlowTracker:
    def register_response(call_index: int, response: str) -> None
    def check_prompt(call_index: int, prompt: str) -> None
    def get_edges() -> list[tuple[int, int]]  # (source_idx, target_idx)
```

Uses substring fingerprinting: if a significant substring of a previous response appears in a later prompt, records a data flow edge.

---

## 10. Callbacks & Observability

**Files:**
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py`
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py`
- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py`

### 10.1 reasoning_before_model & reasoning_after_model

**Before Model:**
- Extract ADK-resolved dynamic instruction from contents
- Merge into system_instruction (maintain proper Gemini role alternation)
- Set REASONING_CALL_START timestamp
- Record system instruction chars, prompt chars, message count

**After Model:**
- Extract finish reason (STOP, SAFETY, RECITATION, MAX_TOKENS)
- Record input_tokens, output_tokens, thought_tokens
- Extract visible_output_text and thought_text from response parts
- Write per-invocation token accounting to depth_key'd keys

### 10.2 ObservabilityPlugin

- Tracks total token usage across invocations
- Records finish reason counts (SAFETY, RECITATION, MAX_TOKENS)
- **Does NOT fire for workers** (ParallelAgent isolation)
- Worker obs flows through: worker_after_model → _call_record → dispatch.py → flush_fn

### 10.3 WorkerRetryPlugin (BUG-13 Fix)

**Problem:** ADK's `_output_schema_processor.get_structured_model_response()` terminates workers on any `set_model_response` call.

**Solution:** Module-level monkey-patch in worker_retry.py:
```python
def _make_worker_tool_callbacks(max_retries: int = 2):
    def after_tool_cb(tool_result, ctx):
        # Detect REFLECT_AND_RETRY_RESPONSE_TYPE sentinel
        # Return None to suppress premature termination
        ...
    def on_tool_error_cb(...):
        # Per-worker error isolation
        ...
    return after_tool_cb, on_tool_error_cb
```

Invocation counter tracked in `_bug13_stats["suppress_count"]`.

---

## 11. Complete Execution Sequence

### User → Final Answer (Step-by-Step)

1. **ADK CLI discovers `app` symbol**
   - Loads RLMOrchestratorAgent as root_agent
   - Creates Runner with plugins + services

2. **Runner.run_async(user_id, session_id, new_message) starts**
   - Calls RLMOrchestratorAgent.run_async(ctx)

3. **Orchestrator._run_async_impl(ctx) begins**
   - Initialize REPL: `repl = LocalREPL(depth=1)`
   - Create DispatchConfig (default or provided)
   - Call `create_dispatch_closures()` → (llm_query_async, llm_query_batched_async, flush_fn)
   - Inject into REPL: `repl.set_async_llm_query_fns(...)`
   - Create REPLTool with max_calls=max_iterations
   - Create SetModelResponseTool with output_schema
   - Wire reasoning_agent: `reasoning_agent.tools = [repl_tool, set_model_response_tool]`
   - Yield initial state delta event
   - Yield initial user Content event with root_prompt

4. **reasoning_agent.run_async(ctx) — ADK Native Loop**
   - Invokes model with tools
   - Model chooses: execute_code OR set_model_response

   **Case A: execute_code**
   - REPLTool.run_async(code=...) invoked
   - Detect LM calls via AST → rewrite to async if needed
   - Execute code in REPL (sync or async)
   - Call flush_fn() → get delta dict
   - Write delta to tool_context.state
   - Return {stdout, stderr, variables, llm_calls_made}
   - ADK loops back to step 4

   **Case B: set_model_response**
   - SetModelResponseTool invoked with final_answer
   - Triggers SetModelResponseTool handling
   - If output_schema, WorkerRetryPlugin validates JSON
   - ADK stores in output_key ("reasoning_output")
   - If validation passes, reasoning loop exits
   - If validation fails, ADK retries (up to max_retries)

5. **Orchestrator extracts final answer**
   - Read output_key from session state
   - Parse via _collect_reasoning_completion()
   - Yield reasoning state delta
   - Save artifact
   - Yield final Content event with answer

6. **Runner receives events**
   - Commits state_delta to session service
   - Forwards events upstream (web, CLI)

---

## 12. Recursion & Depth Tracking

### Child Orchestrator Spawning

When REPL code calls `llm_query(prompt)`:

1. Detects sync `llm_query()` → AST rewriter converts to `await llm_query_async()`
2. `llm_query_async(prompt)` closure executes:
   - Calls `llm_query_batched_async([prompt])`

3. `llm_query_batched_async([prompt, ...])` executes:
   - Check depth limit: if `depth + 1 >= max_depth`, return error
   - For each prompt, call `_run_child(prompt, depth+1)`

4. `_run_child()` creates child orchestrator:
   - `create_child_orchestrator(model, depth=depth+1, prompt, ...)`
   - Calls `child.run_async(ctx)` — same orchestrator logic, but:
     - Depth-suffixed state keys (ITERATION_COUNT@d1, etc.)
     - Condensed static instruction (no repomix)
     - Max 10 iterations (vs. 30 for root)

5. Child completes → Return LLMResult to parent REPL

6. Parent REPL continues with child's answer

### Depth Limit

- Default max_depth=3 (configurable via RLM_MAX_DEPTH env var)
- If depth + 1 >= max_depth, dispatch immediately returns error LLMResult
- Prevents unbounded recursion

---

## 13. Key Invariants & Rules

### AR-CRIT-001: State Mutation Discipline

**NEVER write directly to ctx.session.state in dispatch closures.**

- Use local accumulators (nonlocal variables)
- Call flush_fn() after each REPL execution
- flush_fn() returns dict, merged into tool_context.state

### Pydantic Model Constraints

- RLMOrchestratorAgent and LlmAgent are Pydantic models
- Use `object.__setattr__(agent, 'attr', value)` for dynamic attributes
- Cannot use MagicMock as field values in tests

### ADK Callback Paths

- `reasoning_agent.before_model_callback` → Pre-model processing
- `reasoning_agent.after_model_callback` → Post-model processing
- Access agent via `callback_context._invocation_context.agent` (private API)

### Depth Scoping

- All iteration-local keys MUST use depth_key() in recursive contexts
- DEPTH_SCOPED_KEYS defines required keys
- Non-depth-scoped keys (e.g., OBS_CHILD_DISPATCH_COUNT) remain global

---

## 14. Environment Variables

Key runtime configuration:

```
RLM_ADK_MODEL=gemini-3.1-pro-preview  # Root model
RLM_MAX_ITERATIONS=30  # App:max_iterations
RLM_MAX_DEPTH=3  # Max recursion depth
RLM_MAX_CONCURRENT_CHILDREN=3  # Concurrency limit for batched dispatch
RLM_LLM_MAX_RETRIES=3  # Transient error retries
RLM_LLM_RETRY_DELAY=5.0  # Initial retry delay (seconds)
RLM_REPL_SYNC_TIMEOUT=30  # Sync execution timeout
RLM_REPL_TRACE=0  # Trace level (0, 1, or 2)
RLM_ADK_DEBUG=1  # Verbose observability mode
RLM_ADK_LANGFUSE=1  # Enable LangfuseTracingPlugin
RLM_ADK_SQLITE_TRACING=1  # Enable SqliteTracingPlugin
RLM_CONTEXT_SNAPSHOTS=1  # Enable ContextWindowSnapshotPlugin
RLM_SESSION_DB=.adk/session.db  # SQLite session database path
```

---

## 15. Extension Points

### Adding Custom Skills

1. Create Skill definition:
```python
from google.adk.skills.models import Skill, Frontmatter

MY_SKILL = Skill(
    frontmatter=Frontmatter(name="my-skill", description="..."),
    instructions="..."
)
```

2. Append to static_instruction (create_reasoning_agent)
3. Inject functions into REPL.globals (orchestrator._run_async_impl)
4. Reference in REPL code blocks

### Extending State Keys

1. Define constant in state.py:
```python
MY_KEY = "my:key"
```

2. Add to DEPTH_SCOPED_KEYS if needed for recursion
3. Use depth_key(MY_KEY, depth) when writing/reading

### Custom Plugins

Create BasePlugin subclass, wire in `_default_plugins()`:
```python
class MyPlugin(BasePlugin):
    async def before_run(self, ...): ...
    async def after_run(self, ...): ...
    async def on_session_event(self, ...): ...
```

---

## Summary Table

| Component | File | Purpose |
|-----------|------|---------|
| RLMOrchestratorAgent | orchestrator.py | Collapsed orchestrator, delegates to reasoning_agent |
| create_rlm_runner | agent.py | Factory for full Runner (App + services + plugins) |
| REPLTool | tools/repl_tool.py | ADK tool for code execution |
| LocalREPL | repl/local_repl.py | Persistent Python namespace |
| AST Rewriter | repl/ast_rewriter.py | Sync-to-async bridge for llm_query |
| Dispatch | dispatch.py | Child orchestrator spawning + accumulation |
| State Keys | state.py | Depth-scoped state management |
| Prompts | utils/prompts.py | Static + dynamic instructions + child instructions |
| Skills | skills/repomix_skill.py | Skill definitions + pre-loaded REPL helpers |
| Types | types.py | LLMResult, ReasoningOutput, REPLResult |
| Callbacks | callbacks/ | Reasoning + worker + observability hooks |
| Plugins | plugins/ | ObservabilityPlugin, SqliteTracingPlugin, etc. |

---

This documentation comprehensively covers the RLM-ADK core loop and orchestrator system with sufficient detail for implementation, debugging, and extension.
