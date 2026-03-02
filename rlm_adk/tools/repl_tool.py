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
import json
from typing import Any, Callable, Optional

from google.adk.tools import BaseTool, ToolContext
from google.genai.types import FunctionDeclaration, Schema, Type

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async
from rlm_adk.repl.trace import REPLTrace
from rlm_adk.state import ITERATION_COUNT, LAST_REPL_RESULT, WORKER_DISPATCH_COUNT

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

        self._call_count += 1
        # Track iteration count in session state for observability
        tool_context.state[ITERATION_COUNT] = self._call_count
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
            trace = REPLTrace()
            # Orchestrator passes [None]; set [0] so dispatch closures see
            # the live trace.  Empty lists (e.g. from tests) get an append.
            if self.trace_holder:
                self.trace_holder[0] = trace
            else:
                self.trace_holder.append(trace)

        try:
            if has_llm_calls(code):
                llm_calls_made = True
                tree = rewrite_for_async(code)
                compiled = compile(tree, "<repl>", "exec")
                # Merge globals and locals so _repl_exec sees variables from
                # previous executions (imports, user-defined vars, etc.)
                ns = {**self.repl.globals, **self.repl.locals}
                exec(compiled, ns)
                repl_exec_fn = ns["_repl_exec"]
                result = await self.repl.execute_code_async(code, repl_exec_fn, trace=trace)
            else:
                result = self.repl.execute_code(code, trace=trace)
        except asyncio.CancelledError as exc:
            # FM-13 fix: flush accumulators before returning so dispatch
            # counts from this iteration are not lost (accumulator drift).
            total_llm_calls = 0
            if self._flush_fn is not None:
                acc = self._flush_fn()
                for k, v in acc.items():
                    tool_context.state[k] = v
                total_llm_calls = acc.get(WORKER_DISPATCH_COUNT, 0)
            # Write LAST_REPL_RESULT even on cancellation for observability
            tool_context.state[LAST_REPL_RESULT] = {
                "code_blocks": 1,
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": total_llm_calls,
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
            # FM-14 fix: flush accumulators before returning so dispatch
            # counts from this iteration are not lost (accumulator drift).
            total_llm_calls = 0
            if self._flush_fn is not None:
                acc = self._flush_fn()
                for k, v in acc.items():
                    tool_context.state[k] = v
                total_llm_calls = acc.get(WORKER_DISPATCH_COUNT, 0)
            # Write LAST_REPL_RESULT even on exception for observability
            tool_context.state[LAST_REPL_RESULT] = {
                "code_blocks": 1,
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": total_llm_calls,
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
            total_llm_calls = acc.get(WORKER_DISPATCH_COUNT, 0)

        # Write LAST_REPL_RESULT summary for observability plugins
        last_repl: dict[str, Any] = {
            "code_blocks": 1,
            "has_errors": bool(result.stderr),
            "has_output": bool(result.stdout),
            "total_llm_calls": total_llm_calls,
        }
        if trace is not None:
            last_repl["trace_summary"] = trace.summary()
        tool_context.state[LAST_REPL_RESULT] = last_repl

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
