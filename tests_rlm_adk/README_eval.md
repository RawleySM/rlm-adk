# RLM-ADK Replay Evaluation Guide

This document describes the `--replay` evaluation prompts under `tests_rlm_adk/replay/` and how to run them against the live ADK agent.

## Running a Replay

```bash
adk run --replay tests_rlm_adk/replay/<file>.json rlm_adk
```

The `--replay` flag feeds the JSON file's `state` as initial session state and submits each entry in `queries` as a user message.  The agent then enters its iterative REPL loop, generating code, executing it, and converging toward a `FINAL(...)` or `FINAL_VAR(...)` answer.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `RLM_ADK_MODEL` | `gemini-3-pro-preview` | Model for reasoning agent (depth=0) |
| `RLM_MAX_ITERATIONS` | `30` | Hard ceiling on REPL iterations |
| `RLM_MAX_CONCURRENT_WORKERS` | `4` | Max parallel sub-LM dispatches per batch |
| `RLM_LLM_MAX_RETRIES` | `3` | Retry count for transient LLM errors |
| `RLM_ADK_DEBUG` | unset | Set `1` to enable DebugLoggingPlugin |

### Replay JSON Schema

```json
{
  "state": {
    "app:max_iterations": <int>,
    "app:max_depth": <int>,
    "<session_key>": "<value>"
  },
  "queries": ["<user prompt string>"]
}
```

- **`state`**: Initial session state.  `app:` prefixed keys configure the orchestrator.  Unprefixed keys (e.g. `repo_url`) are session-scoped and available for ADK instruction template resolution via `{key?}` syntax.
- **`queries`**: One or more user prompts submitted sequentially.

---

## Replay Prompts

### 1. `test_basic_context.json`

**Purpose**: Smoke test — verifies the minimal REPL loop completes without sub-LM dispatch.

**State**:
- `app:max_iterations`: 3
- `app:max_depth`: 1

**Query**: Summarize a short inline context string in one sentence.

**Expected Behavior**:

| Step | What Happens |
|---|---|
| Iteration 0 | Reasoning agent reads the inline context, writes a trivial `repl` block (optional) |
| Iteration 1-2 | Agent converges on a summary and emits `FINAL(...)` |

**Key Assertions**:
- Completes within 3 iterations (no max-iteration exhaustion)
- No `llm_query` / `llm_query_batched` calls (no worker dispatch)
- Produces a coherent one-sentence summary
- `FINAL(...)` detected and returned as the final answer

**What This Tests** (SRS refs):
- FR-002: Iterative orchestration loop
- FR-003: Final answer extraction
- FR-004: REPL code block parsing
- FR-005: REPL execution core behavior

---

### 2. `test_repo_analysis.json`

**Purpose**: End-to-end repo analysis with repomix, batched sub-LM dispatch, and aggregation.

**State**:
- `repo_url`: `https://github.com/google/adk-python`
- `app:max_iterations`: 20
- `app:max_depth`: 1

**Query**: Clone/pack the repo with repomix (XML style, split at ~500KB), read all split parts into memory, use `llm_query_batched` to analyze each chunk concurrently, then aggregate with a final `llm_query`.

**Expected Behavior**:

| Phase | Iterations (approx.) | What Happens |
|---|---|---|
| Ingestion | 1-3 | `from repomix import RepoProcessor, RepomixConfig` — pack repo, read split parts into a `chunks` list |
| Batched analysis | 3-6 | Build a prompt list (one per chunk), call `llm_query_batched(prompts)` — triggers `ParallelAgent` with worker pool |
| Aggregation | 6-10 | Combine partial analyses into a single string, call `llm_query(...)` for synthesis |
| Finalization | 10-15 | Store result, emit `FINAL_VAR(...)` |

**Key Assertions**:
- repomix processes the remote repo without error
- `llm_query_batched` dispatches N workers (N = number of chunks, typically 3-8)
- Worker pool acquires and releases workers correctly; on-demand workers created if batch > pool_size
- `ParallelAgent` collects all worker outputs
- Final answer is a coherent architectural summary
- Iteration count stays well under the 20-iteration ceiling

**What This Tests** (SRS refs):
- FR-002: Iterative orchestration loop
- FR-003: Final answer extraction (`FINAL_VAR`)
- FR-011: Sub-LM query support (batched + single)
- AR-CRIT-002: AST rewriter transforms `llm_query` to `await llm_query_async`
- AR-HIGH-003: Worker agent isolation (`include_contents='none'`)
- AR-HIGH-005: Routing semantics (depth=1 workers use `other_model`)

**Observable Console Output** (with `RLM_ADK_DEBUG=1`):
```
[RLM] --- iter=0 START max=20 ---
...
[RLM] worker batch 1/2 (4 prompts)
[RLM] worker batch 2/2 (3 prompts)
[RLM] iter=3 worker_events_drained=14
...
[RLM] FINAL_ANSWER detected at iter=8 length=...
```

---

### 3. `test_structured_pipeline.json`

**Purpose**: Advanced multi-agent pipeline requiring structured JSON schemas, programmatic output parsing, cross-agent computation, and synthesis — demonstrating that the REPL environment supports complex coordination beyond simple `print()` workflows.

**State**:
- `repo_url`: `https://github.com/google/adk-python`
- `app:max_iterations`: 25
- `app:max_depth`: 1

**Query**: A 4-phase structured pipeline prompt (~4,700 chars) that instructs the reasoning agent to coordinate 5 specialized sub-LM agents, each with an explicit JSON output schema.

#### Phase 1: Repository Ingestion

Pack the repo with repomix (XML, split at 500KB), load all parts into an in-memory list.

**Expected REPL pattern**:
```python
from repomix import RepoProcessor, RepomixConfig
import glob

config = RepomixConfig()
config.output.file_path = "/tmp/repo.xml"
config.output.style = "xml"
config.output.split_output = 500 * 1024

processor = RepoProcessor(repo_url, config=config)
result = processor.process()

parts = sorted(glob.glob("/tmp/repo*.xml"))
chunks = [open(p).read() for p in parts]
```

#### Phase 2: Structured Multi-Agent Analysis

Dispatch 5 sub-LMs via `llm_query_batched`, each receiving a codebase chunk plus a strict JSON output schema:

| Agent | Schema Keys | Purpose |
|---|---|---|
| Architecture Mapper | `modules`, `layer_graph`, `patterns` | Module inventory + dependency graph |
| API Surface Extractor | `endpoints`, `total_public`, `total_internal` | Public/internal API signatures |
| Complexity Analyst | `files`, `hotspots`, `avg_complexity` | Cyclomatic/cognitive complexity metrics |
| Security Scanner | `findings`, `risk_score`, `safe_patterns` | Vulnerability scan + risk score 0-1 |
| Test & Quality Assessor | `test_files`, `estimated_coverage`, `quality_score` | Coverage estimate + quality score 0-1 |

**Expected REPL pattern** (not just `print()`):
```python
import json

# Build prompts with embedded JSON schemas
prompts = [
    f"You are the Architecture Mapper. Analyze this code and return ONLY valid JSON matching this schema: {{...}}\n\n{chunk}"
    for chunk in chunks
]
raw_responses = llm_query_batched(prompts)

# Parse and validate — NOT print()
arch_data = json.loads(raw_responses[0])
assert "modules" in arch_data and "layer_graph" in arch_data
```

**Key Distinction from test_repo_analysis**: Every sub-LM response must be:
1. Prompted with an explicit JSON schema
2. Parsed with `json.loads()`
3. Validated for required keys
4. Stored as a typed Python dict for downstream computation

#### Phase 3: Programmatic Cross-Agent Computation

Pure Python code (no sub-LM calls) that processes the parsed structured outputs:

| Computation | Inputs | Output |
|---|---|---|
| Dependency adjacency matrix | `layer_graph` from Architecture Mapper | In-degree/out-degree per module, highest fan-in module |
| Weighted Health Score | `risk_score`, `quality_score`, `avg_complexity`, `total_public`, `total_internal`, `estimated_coverage` | Single float in [0.0, 1.0] |
| Priority-ranked improvements | Security `findings` + complexity `hotspots` | List of `{"file", "priority", "reasons"}` sorted by priority |
| Module risk heatmap | Architecture modules + security findings + complexity | `{module_name: risk_float}` dict |

**Health Score Formula**:
```
health = 0.25 * (1 - risk_score)
       + 0.25 * quality_score
       + 0.25 * (1 - avg_complexity / 20)
       + 0.15 * (total_public / max(total_public + total_internal, 1))
       + 0.10 * estimated_coverage
```
Clamped to [0.0, 1.0].

#### Phase 4: Synthesis with Computed Data

A final `llm_query` receives the **computed results** (not raw sub-LM text) and produces an executive summary:

```json
{
  "health_score": 0.73,
  "grade": "B",
  "top_3_risks": ["..."],
  "top_3_strengths": ["..."],
  "recommended_actions": [
    {"action": "...", "effort": "medium", "impact": "high"}
  ],
  "summary": "..."
}
```

The final JSON is parsed and returned via `FINAL_VAR(report)`.

**Key Assertions**:
- Reasoning agent defines JSON schemas in sub-LM prompts (not free-form prose)
- REPL code calls `json.loads()` on sub-LM responses (not `print()`)
- Parsed data is cross-referenced between agents (security + complexity overlap)
- Pure Python computation produces derived metrics (health score, adjacency matrix)
- Final synthesis sub-LM receives computed data, not raw text
- `FINAL_VAR` returns a structured report, not a narrative string
- Iteration count stays under the 25-iteration ceiling

**What This Tests** (SRS refs):
- FR-002: Iterative orchestration loop (multi-phase, 15+ iterations)
- FR-003: Final answer extraction (`FINAL_VAR` with structured data)
- FR-005: REPL execution (complex multi-block code with imports, json parsing, list comprehensions)
- FR-006: REPL helpers (`FINAL_VAR`, `SHOW_VARS`)
- FR-011: Sub-LM query support (batched + single, 6+ concurrent workers)
- AR-CRIT-002: AST rewriter handles multiple `llm_query` calls across code blocks
- AR-HIGH-003: Worker isolation under high concurrency (5 agents per batch)

**Failure Modes to Watch For**:
- Sub-LM returns markdown-fenced JSON instead of raw JSON — `json.loads()` fails
- Sub-LM omits required schema keys — validation step catches it, agent retries
- Worker pool exhausted — on-demand workers created (pool_size=5, batch=5 is at the boundary)
- Health score formula applied to non-numeric sub-LM outputs — agent must handle gracefully
- Reasoning agent falls back to `print()` instead of parsing — violates the prompt contract

---

## Comparison Matrix

| Attribute | basic_context | repo_analysis | structured_pipeline |
|---|---|---|---|
| Sub-LM calls | 0 | 5-10 | 10-15 |
| Uses `llm_query_batched` | No | Yes | Yes |
| Requires repomix | No | Yes | Yes |
| JSON schema enforcement | No | No | Yes |
| Programmatic output parsing | No | No | Yes (`json.loads`) |
| Cross-agent computation | No | No | Yes (health score, adjacency matrix) |
| Chained pipeline stages | No | Linear (chunk -> aggregate) | Multi-phase (ingest -> analyze -> compute -> synthesize) |
| Expected iterations | 1-3 | 5-15 | 10-25 |
| Primary stress point | Loop mechanics | Worker pool + AST rewriter | Structured output discipline + computation |

---

## Adding New Replay Prompts

1. Create a new JSON file in `tests_rlm_adk/replay/` following the schema above.
2. The existing `test_e2e_replay.py` automatically validates all replay files for:
   - Valid JSON structure
   - Required keys (`state`, `queries`)
   - State key prefix conformance (`app:`, `obs:`, `cache:`, `user:`)
   - `app:max_iterations` and `app:max_depth` are positive integers
3. Run schema validation: `.venv/bin/python -m pytest tests_rlm_adk/test_e2e_replay.py -v`
4. Run live evaluation: `adk run --replay tests_rlm_adk/replay/<file>.json rlm_adk`
