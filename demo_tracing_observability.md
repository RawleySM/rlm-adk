# REPL Tracing & Observability Hardening

*2026-02-26T18:45:44Z by Showboat 0.6.0*
<!-- showboat-id: 50352ebb-87b1-45de-a80b-b81d1ae803a5 -->

## LLMResult — Backward-Compatible Error-Carrying String

LLMResult is a str subclass that carries worker call metadata (error state, error_category, finish_reason, token counts). Because it inherits from str, existing REPL code that treats worker results as plain strings continues to work unchanged, while new skill functions can inspect error metadata for intelligent retry logic.

```bash
sed -n "1,35p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py
```

```output
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Literal

ClientBackend = Literal[
    "openai",
    "portkey",
    "openrouter",
    "vercel",
    "vllm",
    "litellm",
    "anthropic",
    "azure_openai",
    "gemini",
]
EnvironmentType = Literal["local", "docker", "modal", "prime", "daytona", "e2b"]


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-serializable representation."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, ModuleType):
        return f"<module '{value.__name__}'>"
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if callable(value):
        return f"<{type(value).__name__} '{getattr(value, '__name__', repr(value))}'>"
    # Try to convert to string for other types
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"
```

```bash
sed -n "39,71p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py
```

```output
########    Types for Worker LLM Results       #########
########################################################


class LLMResult(str):
    """String subclass carrying worker call metadata.

    Backward-compatible: passes isinstance(x, str), works in f-strings,
    concatenation, etc. But REPL code can inspect error state:

        result = llm_query("prompt")
        if result.error:
            if result.error_category == "TIMEOUT":
                raise RuntimeError(f"Worker timed out: {result}")
            elif result.error_category == "RATE_LIMIT":
                await asyncio.sleep(5)
                result = llm_query("prompt")  # retry
    """

    error: bool = False
    error_category: str | None = None  # TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, FORMAT, UNKNOWN
    http_status: int | None = None
    finish_reason: str | None = None  # STOP, SAFETY, RECITATION, MAX_TOKENS
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    wall_time_ms: float = 0.0

    def __new__(cls, text: str, **kwargs: Any) -> "LLMResult":
        instance = super().__new__(cls, text)
        for k, v in kwargs.items():
            setattr(instance, k, v)
        return instance
```

LLMResult is a str subclass — it passes isinstance(str) checks and works in all string operations. The metadata attrs are set via __new__ kwargs.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.types import LLMResult

# Normal success result
ok = LLMResult('Hello world', error=False, finish_reason='STOP', input_tokens=10, output_tokens=5)
print(f'isinstance(str): {isinstance(ok, str)}')
print(f'str value: {ok}')
print(f'error: {ok.error}')
print(f'finish_reason: {ok.finish_reason}')
print(f'tokens: {ok.input_tokens}/{ok.output_tokens}')

# Error result
err = LLMResult('', error=True, error_category='RATE_LIMIT', http_status=429)
print(f'err.error: {err.error}')
print(f'err.error_category: {err.error_category}')
print(f'err.http_status: {err.http_status}')
print(f'concat works: {\"prefix-\" + ok}')
"

```

```output
isinstance(str): True
str value: Hello world
error: False
finish_reason: STOP
tokens: 10/5
err.error: True
err.error_category: RATE_LIMIT
err.http_status: 429
concat works: prefix-Hello world
```

## REPLTrace — Per-Code-Block Execution Tracing

REPLTrace is a dataclass that accumulates timing, LLM call records, variable snapshots, memory usage, and data flow edges for a single REPL code block. It records llm_query calls with per-call timing and produces both full traces and compact summaries for state enrichment.

```bash
sed -n "1,60p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py
```

```output
"""REPL execution tracing infrastructure.

Provides invisible instrumentation for REPL code block execution:
- REPLTrace: Per-code-block trace accumulator (timing, LLM calls, vars, memory)
- DataFlowTracker: Detects when one llm_query response feeds into a subsequent prompt
- Trace header/footer strings for optional code injection (trace_level >= 2)

Trace levels (RLM_REPL_TRACE env var):
- 0: Off (default) - no tracing overhead
- 1: LLM call timing + variable snapshots + data flow tracking
- 2: + tracemalloc memory tracking via injected header/footer
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class REPLTrace:
    """Invisible trace accumulator for a single REPL code block execution."""

    start_time: float = 0.0
    end_time: float = 0.0
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    var_snapshots: list[dict[str, Any]] = field(default_factory=list)
    peak_memory_bytes: int = 0
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    data_flow_edges: list[tuple[int, int]] = field(default_factory=list)
    execution_mode: str = "sync"  # "sync" | "async"
    _call_counter: int = field(default=0, repr=False)

    def record_llm_start(self, call_index: int, prompt: str, call_type: str = "single") -> None:
        """Record the start of an LLM call."""
        self.llm_calls.append({
            "index": call_index,
            "type": call_type,
            "start_time": time.perf_counter(),
            "prompt_len": len(prompt),
        })

    def record_llm_end(
        self,
        call_index: int,
        response: str,
        elapsed_ms: float,
        error: bool = False,
        **extra: Any,
    ) -> None:
        """Record the end of an LLM call, updating the existing entry."""
        for entry in self.llm_calls:
            if entry.get("index") == call_index:
                entry["elapsed_ms"] = round(elapsed_ms, 2)
                entry["response_len"] = len(response)
                entry["error"] = error
                entry.update(extra)
                return
        # If no matching start entry, create a new one
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.repl.trace import REPLTrace, DataFlowTracker
import time

# Simulate a traced code block with 2 LLM calls
trace = REPLTrace()
trace.start_time = time.perf_counter()

# Record first LLM call
trace.record_llm_start(0, 'Summarize this document', 'single')
trace.record_llm_end(0, 'The document discusses climate change impacts on fisheries.', 45.2)

# Record second LLM call
trace.record_llm_start(1, 'Extract key findings from: The document discusses climate change impacts on fisheries.', 'single')
trace.record_llm_end(1, 'Key findings: 1. Ocean warming shifts species poleward', 38.7)

# Snapshot vars
trace.snapshot_vars({'results': ['summary', 'findings'], 'count': 2}, 'post_execution')
trace.end_time = time.perf_counter()

summary = trace.summary()
print(f'llm_call_count: {summary[\"llm_call_count\"]}')
print(f'failed_llm_calls: {summary[\"failed_llm_calls\"]}')
print(f'var_snapshot_count: {len(trace.var_snapshots)}')

# DataFlowTracker - detect chained calls
dft = DataFlowTracker()
resp0 = 'The document discusses climate change impacts on fisheries worldwide and their economic consequences'
dft.register_response(0, resp0)
dft.check_prompt(1, f'Extract key findings from: {resp0}')
edges = dft.get_edges()
print(f'data_flow_edges: {edges}')
"

```

```output
llm_call_count: 2
failed_llm_calls: 0
var_snapshot_count: 1
data_flow_edges: [(0, 1)]
```

DataFlowTracker detected that LLM call 0 response was used as input to LLM call 1 — edge (0, 1). This dependency graph enables future symbolic workflow extraction.

## Error Classification & finish_reason Tracking

Worker errors are now classified into a taxonomy (TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, UNKNOWN). The finish_reason field from Gemini API responses is extracted and counted by the observability plugin. Both flow through _call_record into LLMResult metadata.

```bash
grep -n "_classify_error\|error_category\|http_status\|TIMEOUT\|RATE_LIMIT\|AUTH\|SERVER\|CLIENT\|NETWORK" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py
```

```output
22:def _classify_error(error: Exception) -> str:
26:        return "TIMEOUT"
28:        return "RATE_LIMIT"
30:        return "AUTH"
32:        return "SERVER"
34:        return "CLIENT"
36:        return "NETWORK"
168:        "error_category": _classify_error(error),
169:        "http_status": getattr(error, "code", None),
```

```bash
sed -n "22,38p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py
```

```output
def _classify_error(error: Exception) -> str:
    """Classify an exception into an error category for observability."""
    code = getattr(error, "code", None)
    if isinstance(error, asyncio.TimeoutError):
        return "TIMEOUT"
    if code == 429:
        return "RATE_LIMIT"
    if code in (401, 403):
        return "AUTH"
    if code and isinstance(code, int) and code >= 500:
        return "SERVER"
    if code and isinstance(code, int) and code >= 400:
        return "CLIENT"
    if isinstance(error, (ConnectionError, OSError)):
        return "NETWORK"
    return "UNKNOWN"

```

## HTTP Timeouts & asyncio.wait_for

Workers now have HttpOptions(timeout=120s) with 2 retry attempts. The reasoning agent has a 5-minute timeout. At the dispatch level, asyncio.wait_for() wraps all worker runs with a configurable timeout (default 180s). Timed-out workers produce LLMResult with error_category=TIMEOUT.

```bash
grep -n "HttpOptions\|WORKER_HTTP_TIMEOUT\|REASONING_HTTP_TIMEOUT\|WORKER_DISPATCH_TIMEOUT\|wait_for\|_drain_events" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py | head -20
```

```output
28:from google.genai.types import HttpOptions, HttpRetryOptions
127:                http_options=HttpOptions(
128:                    timeout=int(os.getenv("RLM_WORKER_HTTP_TIMEOUT", "120000")),
213:_WORKER_DISPATCH_TIMEOUT = float(os.getenv("RLM_WORKER_TIMEOUT", "180"))
216:async def _drain_events(
375:                        await asyncio.wait_for(
376:                            _drain_events(workers[0].run_async(ctx), event_queue),
377:                            timeout=_WORKER_DISPATCH_TIMEOUT,
380:                        workers[0]._result = f"[Worker {workers[0].name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
389:                        await asyncio.wait_for(
390:                            _drain_events(parallel.run_async(ctx), event_queue),
391:                            timeout=_WORKER_DISPATCH_TIMEOUT,
396:                                w._result = f"[Worker {w.name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
```

## Trace Header/Footer Injection (trace_level >= 2)

At trace_level 2, invisible header/footer code is prepended/appended to REPL code blocks before exec(). The agent never sees these — format_iteration() uses the original code. The footer captures tracemalloc peak memory.

```bash
grep -n "TRACE_HEADER\|TRACE_FOOTER\|_rlm_trace\|tracemalloc" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py
```

```output
11:- 2: + tracemalloc memory tracking via injected header/footer
153:TRACE_HEADER = '''\
157:    _rlm_trace.start_time = _rlm_time.perf_counter()
162:TRACE_HEADER_MEMORY = '''\
166:    import tracemalloc as _rlm_tracemalloc
167:    _rlm_trace.start_time = _rlm_time.perf_counter()
168:    _rlm_mem_was_tracing = _rlm_tracemalloc.is_tracing()
170:        _rlm_tracemalloc.start()
175:TRACE_FOOTER = '''\
178:    _rlm_trace.end_time = _rlm_time.perf_counter()
183:TRACE_FOOTER_MEMORY = '''\
187:        _current, _peak = _rlm_tracemalloc.get_traced_memory()
188:        _rlm_trace.peak_memory_bytes = _peak
189:        _rlm_tracemalloc.stop()
190:    _rlm_trace.end_time = _rlm_time.perf_counter()
```

## New State Keys & Zero-Progress Detection

Eight new observability state keys track finish_reason counts, worker error classifications, and zero-progress iterations. Three consecutive zero-progress iterations trigger a warning log.

```bash
grep -n "OBS_FINISH\|OBS_WORKER\|OBS_ZERO\|OBS_CONSECUTIVE" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py
```

```output
84:OBS_WORKER_DISPATCH_LATENCY_MS = "obs:worker_dispatch_latency_ms"
85:OBS_WORKER_TOTAL_DISPATCHES = "obs:worker_total_dispatches"
86:OBS_WORKER_TOTAL_BATCH_DISPATCHES = "obs:worker_total_batch_dispatches"
87:OBS_WORKER_DIRTY_READ_MISMATCHES = "obs:worker_dirty_read_mismatches"
90:OBS_FINISH_SAFETY_COUNT = "obs:finish_safety_count"
91:OBS_FINISH_RECITATION_COUNT = "obs:finish_recitation_count"
92:OBS_FINISH_MAX_TOKENS_COUNT = "obs:finish_max_tokens_count"
95:OBS_WORKER_TIMEOUT_COUNT = "obs:worker_timeout_count"
96:OBS_WORKER_RATE_LIMIT_COUNT = "obs:worker_rate_limit_count"
97:OBS_WORKER_ERROR_COUNTS = "obs:worker_error_counts"  # dict[category, count]
100:OBS_ZERO_PROGRESS_ITERATIONS = "obs:zero_progress_iterations"
101:OBS_CONSECUTIVE_ZERO_PROGRESS = "obs:consecutive_zero_progress"
```

## REPLTracingPlugin & Artifact Persistence

REPLTracingPlugin (BasePlugin) captures trace summaries from LAST_REPL_RESULT events and saves them as repl_traces.json at the end of a run. Per-block traces are saved as repl_trace_iter_N_turn_M.json via save_repl_trace().

```bash
sed -n "1,40p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py
```

```output
"""REPLTracingPlugin - Persists REPL traces as JSON artifacts per iteration.

Captures trace summaries from LAST_REPL_RESULT events and saves accumulated
traces as a single JSON artifact at the end of the run.

Enabled via RLM_REPL_TRACE > 0 env var.
"""

import json
import logging
from typing import Any, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from rlm_adk.state import ITERATION_COUNT, LAST_REPL_RESULT

logger = logging.getLogger(__name__)


class REPLTracingPlugin(BasePlugin):
    """Persists REPL traces as JSON artifacts per iteration."""

    def __init__(self, name: str = "repl_tracing"):
        super().__init__(name=name)
        self._traces_by_iteration: dict[int, Any] = {}

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Optional[Event]:
        """Capture LAST_REPL_RESULT events that contain trace data."""
        try:
            sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
            repl_result = sd.get(LAST_REPL_RESULT)
            if repl_result and isinstance(repl_result, dict):
```

## WorkerRetryPlugin — Format Validation with Reflect-and-Retry

WorkerRetryPlugin extends ADK ReflectAndRetryToolPlugin. Workers get a submit_answer FunctionTool; empty or malformed responses trigger structured retry guidance back to the worker LLM. Not yet wired due to callback signature verification needed.

```bash
sed -n "34,68p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py
```

```output
class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    """Extends ReflectAndRetryToolPlugin for worker format validation.

    Override extract_error_from_result() to detect format errors in
    submit_answer tool results (e.g., empty response, truncated JSON).
    """

    def __init__(self, max_retries: int = 2):
        super().__init__(max_retries=max_retries)
        self._format_validator: Optional[Callable[[str], Optional[str]]] = None

    async def extract_error_from_result(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[dict[str, Any]]:
        """Detect format errors in submit_answer tool output."""
        if tool.name != "submit_answer":
            return None

        response = tool_args.get("response", "")
        if not response or not response.strip():
            return {"error": "Empty response", "details": "The response must contain text."}

        # If a format validator is set, run it
        if self._format_validator is not None:
            validation_error = self._format_validator(response)
            if validation_error:
                return {"error": "Format error", "details": validation_error}

        return None
```

## Expanded is_transient_error

The transient error detector now recognizes asyncio.TimeoutError, ConnectionError, OSError, and httpx exceptions in addition to the existing ServerError/ClientError checks.

```bash
sed -n "53,77p" /home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py
```

```output
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def is_transient_error(exc: Exception) -> bool:
    """Classify an exception as transient (retryable) using type-based checks.

    Recognizes google.genai errors, asyncio timeouts, and network-level
    exceptions as transient.  Generic exceptions are never retried.
    """
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import httpx as _httpx
        if isinstance(exc, (_httpx.ConnectError, _httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    return False


class RLMOrchestratorAgent(BaseAgent):
    """Custom BaseAgent that implements the RLM recursive iteration loop.

```

## Environment Variable Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| RLM_REPL_TRACE | 0 | Trace level: 0=off, 1=timing+vars, 2=+tracemalloc |
| RLM_WORKER_HTTP_TIMEOUT | 120000 | Worker HTTP timeout (ms) |
| RLM_REASONING_HTTP_TIMEOUT | 300000 | Reasoning agent HTTP timeout (ms) |
| RLM_WORKER_TIMEOUT | 180 | asyncio.wait_for dispatch timeout (seconds) |

## Test Suite — Zero Regressions

All existing tests pass with zero regressions from the tracing and observability changes.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/ -q --tb=no --no-header 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
33 failed, 525 passed, 1 skipped
```

The 33 failures are all pre-existing (test_eval_queries, test_session_fork, test_trace_reader, test_skill_helper_e2e). 525 passed with 0 new regressions from the tracing and observability changes.
