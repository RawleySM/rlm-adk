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
from typing import Any, Callable, Optional

from google.adk.tools import BaseTool, ToolContext
from google.genai.types import FunctionDeclaration, Schema, Type

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async

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
        if self._call_count > self._max_calls:
            return {
                "stdout": "",
                "stderr": _CALL_LIMIT_MSG,
                "variables": {},
                "llm_calls_made": False,
                "call_number": self._call_count,
            }

        llm_calls_made = False

        try:
            if has_llm_calls(code):
                llm_calls_made = True
                tree = rewrite_for_async(code)
                compiled = compile(tree, "<repl>", "exec")
                exec(compiled, self.repl.globals)
                repl_exec_fn = self.repl.globals["_repl_exec"]
                result = await self.repl.execute_code_async(code, repl_exec_fn)
            else:
                result = self.repl.execute_code(code)
        except (Exception, asyncio.CancelledError) as exc:
            return {
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }

        # Record trace if holder provided.
        # REPLResult.trace is a dict (from REPLTrace.to_dict()) or None.
        # When trace is None (no REPLTrace was passed to execute_code),
        # we record the full REPLResult dict instead.
        if self.trace_holder is not None:
            if result.trace is not None:
                self.trace_holder.append(result.trace)
            else:
                self.trace_holder.append(result.to_dict())

        # Flush dispatch accumulators into tool_context.state
        if self._flush_fn is not None:
            acc = self._flush_fn()
            for k, v in acc.items():
                tool_context.state[k] = v

        # Extract simple-type variables from REPL locals
        variables: dict[str, Any] = {}
        for k, v in result.locals.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                variables[k] = v

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "variables": variables,
            "llm_calls_made": llm_calls_made,
            "call_number": self._call_count,
        }
