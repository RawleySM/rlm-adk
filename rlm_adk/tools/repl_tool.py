"""REPLTool -- ADK BaseTool wrapping LocalREPL for function-calling execution.

Replaces regex-parsed ```repl code blocks with a proper ADK tool that the
model calls via function calling. The tool:

- Executes Python code in a persistent LocalREPL environment
- Detects llm_query calls and routes through the AST rewriter for async execution
- Enforces a configurable call limit
- Records execution traces when a trace_holder list is provided
- Flushes dispatch accumulators into ToolContext.state when a flush_fn is provided
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Callable, Optional

from google.adk.tools import BaseTool, ToolContext
from google.genai.types import FunctionDeclaration, Schema, Type

from rlm_adk.artifacts import save_repl_code
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async
from rlm_adk.repl.trace import REPLTrace
from rlm_adk.state import (
    ITERATION_COUNT, LAST_REPL_RESULT, OBS_CHILD_DISPATCH_COUNT,
    OBS_REWRITE_COUNT, OBS_REWRITE_FAILURE_CATEGORIES,
    OBS_REWRITE_FAILURE_COUNT, OBS_REWRITE_TOTAL_MS,
    REPL_SUBMITTED_CODE, REPL_SUBMITTED_CODE_CHARS,
    REPL_SUBMITTED_CODE_HASH, REPL_SUBMITTED_CODE_PREVIEW,
    depth_key,
)

_CALL_LIMIT_MSG = "REPL call limit reached. Submit your final answer now."


class REPLTool(BaseTool):
    """ADK tool that executes Python code in a persistent REPL environment.

    Variables persist between calls. Returns stdout, stderr, and current
    variable values. Supports both sync code and async code containing
    llm_query/llm_query_batched calls (auto-detected via AST analysis).
    """

    def __init__(
        self,
        repl: LocalREPL,
        *,
        max_calls: int = 60,
        trace_holder: Optional[list] = None,
        flush_fn: Optional[Callable[[], dict]] = None,
        depth: int = 0,
        fanout_idx: int = 0,
        summarization_threshold: int = 5000,
    ):
        super().__init__(
            name="execute_code",
            description=(
                "Execute Python code in a persistent REPL environment. "
                "Variables persist between calls. Returns stdout, stderr, "
                "and current variable values."
            ),
        )
        self.repl = repl
        self._max_calls = max_calls
        self._call_count = 0
        self.trace_holder = trace_holder
        self._flush_fn = flush_fn
        self._depth = depth
        self._fanout_idx = fanout_idx
        self._summarization_threshold = summarization_threshold
        self._rewrite_count = 0
        self._rewrite_total_ms = 0.0
        self._rewrite_failure_count = 0

    def _get_declaration(self) -> FunctionDeclaration:
        return FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=Schema(
                type=Type.OBJECT,
                properties={
                    "code": Schema(
                        type=Type.STRING,
                        description="Python code to execute in the REPL.",
                    ),
                },
                required=["code"],
            ),
        )

    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> dict:
        code = args["code"]

        # OG-03 fix: persist submitted code for observability
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        tool_context.state[depth_key(REPL_SUBMITTED_CODE, self._depth)] = code
        tool_context.state[depth_key(REPL_SUBMITTED_CODE_CHARS, self._depth)] = len(code)
        tool_context.state[depth_key(REPL_SUBMITTED_CODE_HASH, self._depth)] = code_hash
        tool_context.state[depth_key(REPL_SUBMITTED_CODE_PREVIEW, self._depth)] = code[:500]

        # Persist submitted code as a versioned artifact file
        await save_repl_code(
            tool_context,
            iteration=self._call_count + 1,
            turn=0,
            code=code,
            depth=self._depth,
            fanout_idx=self._fanout_idx,
        )

        self._call_count += 1
        # Track iteration count in session state for observability
        tool_context.state[depth_key(ITERATION_COUNT, self._depth)] = self._call_count
        if self._call_count > self._max_calls:
            return {
                "stdout": "",
                "stderr": _CALL_LIMIT_MSG,
                "variables": {},
                "llm_calls_made": False,
                "call_number": self._call_count,
            }

        llm_calls_made = False

        # Create a REPLTrace when trace_holder is provided so dispatch
        # closures and LocalREPL can record timing/LLM-call data.
        trace: REPLTrace | None = None
        if self.trace_holder is not None:
            trace = REPLTrace(
                submitted_code_chars=len(code),
                submitted_code_hash=code_hash,
                submitted_code_preview=code[:500],
            )
            # Orchestrator passes [None]; set [0] so dispatch closures see
            # the live trace.  Empty lists (e.g. from tests) get an append.
            if self.trace_holder:
                self.trace_holder[0] = trace
            else:
                self.trace_holder.append(trace)

        try:
            if has_llm_calls(code):
                llm_calls_made = True
                try:
                    _t0 = time.perf_counter()
                    tree = rewrite_for_async(code)
                    _rewrite_ms = (time.perf_counter() - _t0) * 1000
                    self._rewrite_count += 1
                    self._rewrite_total_ms += _rewrite_ms
                    # Write rewrite instrumentation early -- the count is known
                    # after the AST transform, before execution begins, so it
                    # survives execution errors (CancelledError / Exception).
                    tool_context.state[OBS_REWRITE_COUNT] = self._rewrite_count
                    tool_context.state[OBS_REWRITE_TOTAL_MS] = round(self._rewrite_total_ms, 3)
                    compiled = compile(tree, "<repl>", "exec")
                except Exception as rewrite_exc:
                    # Track rewrite failures separately from execution failures
                    self._rewrite_failure_count += 1
                    tool_context.state[OBS_REWRITE_FAILURE_COUNT] = self._rewrite_failure_count
                    categories = tool_context.state.get(OBS_REWRITE_FAILURE_CATEGORIES, {})
                    err_name = type(rewrite_exc).__name__
                    categories[err_name] = categories.get(err_name, 0) + 1
                    tool_context.state[OBS_REWRITE_FAILURE_CATEGORIES] = categories
                    raise
                # Merge globals and locals so _repl_exec sees variables from
                # previous executions (imports, user-defined vars, etc.)
                ns = {**self.repl.globals, **self.repl.locals}
                exec(compiled, ns)
                repl_exec_fn = ns["_repl_exec"]
                result = await self.repl.execute_code_async(code, repl_exec_fn, trace=trace)
            else:
                result = self.repl.execute_code(code, trace=trace)
        except asyncio.CancelledError as exc:
            # OG-04 fix: ensure end_time is set so trace summary is non-negative
            if trace is not None and trace.start_time and not trace.end_time:
                trace.end_time = time.perf_counter()
            # FM-13 fix: flush accumulators before returning so dispatch
            # counts from this iteration are not lost (accumulator drift).
            total_llm_calls = 0
            if self._flush_fn is not None:
                acc = self._flush_fn()
                for k, v in acc.items():
                    tool_context.state[k] = v
                total_llm_calls = acc.get(OBS_CHILD_DISPATCH_COUNT, 0)
            # Write LAST_REPL_RESULT even on cancellation for observability
            tool_context.state[depth_key(LAST_REPL_RESULT, self._depth)] = {
                "code_blocks": 1,
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": total_llm_calls,
                "stdout_preview": "",
                "cancelled": True,
            }
            return {
                "stdout": "",
                "stderr": f"CancelledError: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }
        except Exception as exc:
            # OG-04 fix: ensure end_time is set so trace summary is non-negative
            if trace is not None and trace.start_time and not trace.end_time:
                trace.end_time = time.perf_counter()
            # FM-14 fix: flush accumulators before returning so dispatch
            # counts from this iteration are not lost (accumulator drift).
            total_llm_calls = 0
            if self._flush_fn is not None:
                acc = self._flush_fn()
                for k, v in acc.items():
                    tool_context.state[k] = v
                total_llm_calls = acc.get(OBS_CHILD_DISPATCH_COUNT, 0)
            # Write LAST_REPL_RESULT even on exception for observability
            tool_context.state[depth_key(LAST_REPL_RESULT, self._depth)] = {
                "code_blocks": 1,
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": total_llm_calls,
                "stdout_preview": "",
            }
            return {
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }

        # Flush dispatch accumulators into tool_context.state
        total_llm_calls = 0
        if self._flush_fn is not None:
            acc = self._flush_fn()
            for k, v in acc.items():
                tool_context.state[k] = v
            total_llm_calls = acc.get(OBS_CHILD_DISPATCH_COUNT, 0)

        # Write LAST_REPL_RESULT summary for observability plugins
        last_repl: dict[str, Any] = {
            "code_blocks": 1,
            "has_errors": bool(result.stderr),
            "has_output": bool(result.stdout),
            "total_llm_calls": total_llm_calls,
            "stdout_preview": result.stdout[:500],
            "submitted_code_chars": len(code),
            "submitted_code_hash": code_hash,
        }
        if trace is not None:
            last_repl["trace_summary"] = trace.summary()
        tool_context.state[depth_key(LAST_REPL_RESULT, self._depth)] = last_repl

        # Skip ADK's post-tool summarization call for large outputs to save tokens
        output_len = len(result.stdout) + len(result.stderr)
        if output_len >= self._summarization_threshold:
            tool_context.actions.skip_summarization = True

        # Extract JSON-serializable variables from REPL locals.
        # We attempt json.dumps to catch nested non-serializable objects
        # (e.g., a dict containing module references) that would cause ADK's
        # deepcopy to fail with TypeError.
        variables: dict[str, Any] = {}
        for k, v in result.locals.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                try:
                    json.dumps(v)
                    variables[k] = v
                except (TypeError, ValueError, OverflowError, RecursionError):
                    pass  # Skip non-serializable values (incl. circular refs)

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "variables": variables,
            "llm_calls_made": llm_calls_made,
            "call_number": self._call_count,
        }
