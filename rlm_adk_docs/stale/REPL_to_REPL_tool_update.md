Implementation Plan: Unified output_schema + REPLTool Architecture
Red/Green TDD Implementation

================================================================================
Phase 1: Depth-Scoped State Keys (standalone, foundation)
================================================================================

--- RED: tests_rlm_adk/test_depth_key_scoping.py ---

class TestDepthKeyFunction:
    def test_depth_zero_returns_original_key(self):
        assert depth_key("message_history", 0) == "message_history"

    def test_depth_nonzero_returns_suffixed_key(self):
        assert depth_key("message_history", 2) == "message_history@d2"

    def test_all_scoped_keys_unchanged_at_depth_zero(self):
        # For every key in DEPTH_SCOPED_KEYS, depth_key(k, 0) == k
        for key in DEPTH_SCOPED_KEYS:
            assert depth_key(key, 0) == key

    def test_global_keys_not_in_scoped_set(self):
        # OBS_*, WORKER_*, CACHE_* must NOT be in DEPTH_SCOPED_KEYS
        for key in [OBS_TOTAL_INPUT_TOKENS, WORKER_DISPATCH_COUNT, CACHE_HIT_COUNT]:
            assert key not in DEPTH_SCOPED_KEYS

class TestDepthKeyIntegration:
    def test_two_depths_write_independent_values(self):
        state = {}
        state[depth_key(MESSAGE_HISTORY, 0)] = ["msg_a"]
        state[depth_key(MESSAGE_HISTORY, 1)] = ["msg_b"]
        assert state["message_history"] == ["msg_a"]
        assert state["message_history@d1"] == ["msg_b"]

--- GREEN: rlm_adk/state.py ---

Add after line 149:

DEPTH_SCOPED_KEYS: set[str] = {
    MESSAGE_HISTORY, ITERATION_COUNT,
    FINAL_ANSWER, LAST_REPL_RESULT, SHOULD_STOP,
}
# NOTE: LAST_REASONING_RESPONSE and CURRENT_CODE_BLOCKS excluded —
# Phase 3 removes them from the write path entirely.

def depth_key(key: str, depth: int = 0) -> str:
    if depth == 0:
        return key
    return f"{key}@d{depth}"

No changes to orchestrator.py or callbacks/reasoning.py yet — those are Phase 3.
Existing tests pass unmodified (depth=0 passthrough).


================================================================================
Phase 2: REPLTool as ADK BaseTool
================================================================================

--- RED: tests_rlm_adk/test_repl_tool.py ---

Imports: REPLTool (from rlm_adk.tools.repl_tool), LocalREPL, FunctionDeclaration,
         has_llm_calls, MagicMock (for tool_context)

Helper:

def _make_tool_context(state=None):
    tc = MagicMock()
    tc.state = state if state is not None else {}
    return tc

Fixture:

@pytest.fixture
def repl_tool():
    repl = LocalREPL()
    tool = REPLTool(repl=repl)
    yield tool
    repl.cleanup()


class TestREPLToolDeclaration:
    def test_tool_name_is_execute_code(self, repl_tool):
        decl = repl_tool._get_declaration()
        assert decl.name == "execute_code"

    def test_declaration_has_code_parameter(self, repl_tool):
        decl = repl_tool._get_declaration()
        props = decl.parameters.properties
        assert "code" in props
        assert props["code"].type == "STRING"

    def test_declaration_requires_code(self, repl_tool):
        decl = repl_tool._get_declaration()
        assert "code" in decl.parameters.required


class TestREPLToolSyncExecution:
    @pytest.mark.asyncio
    async def test_simple_print_returns_stdout(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "print('hello')"}, tool_context=tc)
        assert result["stdout"].strip() == "hello"
        assert result["stderr"] == ""

    @pytest.mark.asyncio
    async def test_syntax_error_returns_stderr(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "def("}, tool_context=tc)
        assert "SyntaxError" in result["stderr"]

    @pytest.mark.asyncio
    async def test_variable_persistence_across_calls(self, repl_tool):
        tc = _make_tool_context()
        await repl_tool.run_async(args={"code": "x = 42"}, tool_context=tc)
        result = await repl_tool.run_async(args={"code": "print(x)"}, tool_context=tc)
        assert "42" in result["stdout"]

    @pytest.mark.asyncio
    async def test_variables_returned_in_result(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "answer = 99"}, tool_context=tc)
        assert result["variables"]["answer"] == 99

    @pytest.mark.asyncio
    async def test_runtime_error_returns_stderr(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "1/0"}, tool_context=tc)
        assert "ZeroDivisionError" in result["stderr"]


class TestREPLToolAsyncExecution:
    @pytest.mark.asyncio
    async def test_code_with_llm_query_uses_async_path(self, repl_tool):
        # Inject a fake async llm_query into REPL globals
        async def fake_llm_query_async(prompt, **kw):
            return "mocked_response"
        repl_tool.repl.set_async_llm_query_fns(fake_llm_query_async, None)
        tc = _make_tool_context()
        result = await repl_tool.run_async(
            args={"code": "result = llm_query('test prompt')\nprint(result)"},
            tool_context=tc,
        )
        assert "mocked_response" in result["stdout"]
        assert result["llm_calls_made"] is True

    @pytest.mark.asyncio
    async def test_code_without_llm_query_uses_sync_path(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(
            args={"code": "x = 2 + 2\nprint(x)"},
            tool_context=tc,
        )
        assert result["llm_calls_made"] is False
        assert "4" in result["stdout"]


class TestREPLToolCallLimit:
    @pytest.mark.asyncio
    async def test_call_limit_returns_error_after_threshold(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, max_calls=2)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        await tool.run_async(args={"code": "x = 2"}, tool_context=tc)
        result = await tool.run_async(args={"code": "x = 3"}, tool_context=tc)
        assert "call limit reached" in result["stderr"].lower()
        assert result["stdout"] == ""
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_call_count_tracked_in_result(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, max_calls=60)
        tc = _make_tool_context()
        r1 = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        r2 = await tool.run_async(args={"code": "x = 2"}, tool_context=tc)
        assert r1["call_number"] == 1
        assert r2["call_number"] == 2
        repl.cleanup()


class TestREPLToolTraceRecording:
    @pytest.mark.asyncio
    async def test_trace_holder_receives_trace_data(self):
        repl = LocalREPL()
        traces = []
        tool = REPLTool(repl=repl, trace_holder=traces)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        repl.cleanup()
        assert len(traces) == 1  # one trace per execution


class TestREPLToolTelemetryFlush:
    """Verify dispatch accumulator flush writes to tool_context.state (C2 fix)."""

    @pytest.mark.asyncio
    async def test_flush_fn_writes_accumulators_to_tool_context_state(self):
        repl = LocalREPL()
        flush_calls = []
        def fake_flush():
            flush_calls.append(1)
            return {"worker_dispatch_count": 5, "obs:worker_dispatch_latency_ms": [12.3]}
        tool = REPLTool(repl=repl, flush_fn=fake_flush)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        repl.cleanup()
        assert len(flush_calls) == 1
        assert tc.state["worker_dispatch_count"] == 5
        assert tc.state["obs:worker_dispatch_latency_ms"] == [12.3]

    @pytest.mark.asyncio
    async def test_no_flush_fn_is_noop(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl)  # no flush_fn
        tc = _make_tool_context()
        result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        repl.cleanup()
        assert result["stdout"] == ""  # no crash


class TestREPLToolExceptionSafety:
    """Top-level exception handler returns stderr, never propagates (INFO fix)."""

    @pytest.mark.asyncio
    async def test_cancelled_error_returns_stderr(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        # Patch execute_code to raise CancelledError
        import asyncio
        repl.execute_code = lambda code, **kw: (_ for _ in ()).throw(asyncio.CancelledError())
        tc = _make_tool_context()
        result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        assert "CancelledError" in result["stderr"]
        repl.cleanup()


--- GREEN: New file rlm_adk/tools/__init__.py ---

(empty)


--- GREEN: New file rlm_adk/tools/repl_tool.py ---

from google.adk.tools import BaseTool, ToolContext
from google.genai.types import FunctionDeclaration, Schema, Type

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async

_CALL_LIMIT_MSG = "REPL call limit reached. Submit your final answer now."


class REPLTool(BaseTool):
    def __init__(
        self,
        repl: LocalREPL,
        *,
        max_calls: int = 60,
        trace_holder: list | None = None,
        flush_fn: Callable[[], dict] | None = None,
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
        self._flush_fn = flush_fn  # dispatch accumulator snapshot+reset

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

    async def run_async(self, *, args: dict, tool_context: ToolContext) -> dict:
        code = args["code"]

        # ── Call-limit safety (C4 primary mechanism) ──
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

        # ── Top-level exception handler (INFO fix) ──
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
        except Exception as exc:
            return {
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }

        if self.trace_holder is not None:
            self.trace_holder.append(result.trace if result.trace else result.to_dict())

        # ── Flush dispatch accumulators into tool_context.state (C2 fix) ──
        if self._flush_fn is not None:
            acc = self._flush_fn()
            for k, v in acc.items():
                tool_context.state[k] = v

        # Expose simple-type variables (for model context, truncated)
        variables = {}
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


================================================================================
Phase 3: Reasoning Agent Restructure (the big one)
================================================================================

--- RED: tests_rlm_adk/test_reasoning_output_schema.py ---

Tests for the new ReasoningOutput schema and agent factory wiring.

class TestReasoningOutputSchema:
    def test_schema_requires_final_answer(self):
        with pytest.raises(ValidationError):
            ReasoningOutput(reasoning_summary="oops")

    def test_schema_defaults_reasoning_summary(self):
        ro = ReasoningOutput(final_answer="42")
        assert ro.reasoning_summary == ""

    def test_schema_accepts_full_input(self):
        ro = ReasoningOutput(final_answer="42", reasoning_summary="did math")
        assert ro.final_answer == "42"
        assert ro.reasoning_summary == "did math"


class TestReasoningAgentFactory:
    def test_create_reasoning_agent_with_tools_and_schema(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        agent = create_reasoning_agent(
            model="gemini-fake",
            tools=[tool],
            output_schema=ReasoningOutput,
        )
        assert tool in agent.tools
        assert agent.output_schema == ReasoningOutput
        repl.cleanup()

    def test_create_reasoning_agent_backward_compat_no_tools(self):
        # Existing callers with no tools/output_schema still work
        agent = create_reasoning_agent(model="gemini-fake")
        assert agent.tools == []
        assert agent.output_schema is None


--- RED: tests_rlm_adk/test_orchestrator_collapse.py ---

Integration tests using provider_fake fixtures.
New fixture files needed: functionCall-based responses instead of text ```repl blocks.

New fixture: fixtures/provider_fake/tool_call_single_iteration.json

Scenario: Model makes one execute_code tool call, then calls set_model_response.
Response sequence:
  1. functionCall: execute_code(code="x = 2 + 2\nprint(x)")
  2. functionCall: set_model_response(final_answer="The answer is 4")

class TestOrchestratorWithToolCalls:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fake_gemini",
        [FIXTURE_DIR / "tool_call_single_iteration.json"],
        indirect=True,
    )
    async def test_single_iteration_tool_call_produces_final_answer(self, fake_gemini):
        result = await run_fixture_contract(fake_gemini.fixture_path)
        assert result.passed
        assert "4" in result.checks[0]["actual"]  # final_answer check

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fake_gemini",
        [FIXTURE_DIR / "tool_call_multi_iteration.json"],
        indirect=True,
    )
    async def test_multi_iteration_tool_calls_accumulate_state(self, fake_gemini):
        result = await run_fixture_contract(fake_gemini.fixture_path)
        assert result.passed


--- RED: tests_rlm_adk/test_multi_turn_contents_integrity.py (T1) ---

Verify that under include_contents='default', tool-response turns retain prior
tool context — the model sees REPL output from previous tool calls.

New fixture: fixtures/provider_fake/tool_call_multi_turn_contents.json

Scenario: Model calls execute_code("x = 2+2"), sees result, then calls
execute_code("print(x)") referencing the prior variable. Second call's
request must contain the first tool call + response in its contents.

class TestMultiTurnContentsIntegrity:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fake_gemini",
        [FIXTURE_DIR / "tool_call_multi_turn_contents.json"],
        indirect=True,
    )
    async def test_second_tool_call_sees_first_tool_response(self, fake_gemini):
        """The LLM request for call_index=2 must contain the tool response from call_index=0."""
        result = await run_fixture_contract(fake_gemini.fixture_path)
        assert result.passed
        # Verify the second LLM request's contents included the first tool response
        second_request = fake_gemini.recorded_requests[2]
        contents_text = str(second_request.get("contents", []))
        assert "4" in contents_text  # stdout from first execute_code


--- RED: tests_rlm_adk/test_output_key_deserialization.py (T3) ---

class TestOutputKeyDeserialization:
    def test_output_key_json_string_roundtrip(self):
        """output_key writes serialized JSON; orchestrator must deserialize."""
        import json
        ro = ReasoningOutput(final_answer="42", reasoning_summary="math")
        serialized = json.dumps(ro.model_dump())
        # Simulate what ADK writes to state[output_key]:
        raw = serialized
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        assert parsed["final_answer"] == "42"
        assert parsed["reasoning_summary"] == "math"

    def test_output_key_already_dict_passthrough(self):
        """If ADK writes a dict directly, deserialization is a no-op."""
        import json
        raw = {"final_answer": "42", "reasoning_summary": "math"}
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        assert parsed["final_answer"] == "42"


--- RED: tests_rlm_adk/test_prompts_tool_instructions.py ---

class TestToolCallingPrompt:
    def test_prompt_mentions_execute_code_tool(self):
        assert "execute_code" in RLM_STATIC_INSTRUCTION

    def test_prompt_mentions_set_model_response(self):
        assert "set_model_response" in RLM_STATIC_INSTRUCTION

    def test_prompt_does_not_mention_repl_fence(self):
        assert "```repl" not in RLM_STATIC_INSTRUCTION

    def test_prompt_does_not_mention_FINAL(self):
        assert "FINAL(" not in RLM_STATIC_INSTRUCTION
        assert "FINAL_VAR(" not in RLM_STATIC_INSTRUCTION


--- GREEN ---

types.py — Add ReasoningOutput:

class ReasoningOutput(BaseModel):
    final_answer: str = Field(description="Complete final answer to the query.")
    reasoning_summary: str = Field(default="", description="Brief reasoning summary.")

NOTE: Do NOT add finish_reason/repl_call_count here (W3). The schema goes to
the model — extra fields distract it. Record observability in tool_context.state
from REPLTool's flush (call count) and from after_model callback (finish_reason).


agent.py — Update create_reasoning_agent():

def create_reasoning_agent(
    model: str,
    *,
    tools: list | None = None,
    output_schema: type[BaseModel] | None = None,
    **kwargs,
) -> LlmAgent:
    agent = LlmAgent(
        name="reasoning_agent",
        model=model,
        include_contents="default",  # ADK manages tool call/response history
        tools=tools or [],
        output_schema=output_schema,
        disallow_transfer_to_parent=True,   # W7: prevent agent transfer
        disallow_transfer_to_peers=True,     # W7: prevent agent transfer
        ...existing kwargs...
    )
    return agent


orchestrator.py — Collapse iteration loop:

The entire `for i in range(max_iterations)` loop (lines 185-493) replaced by:

async def _run_async_impl(self, ctx):
    # 1. Initialize state + wire dispatch closures into REPLTool's REPL
    #    Wire flush_fn from dispatch accumulators into REPLTool constructor
    repl_tool = REPLTool(
        repl=repl,
        max_calls=max_iterations,
        trace_holder=trace_holder,
        flush_fn=dispatch_flush_fn,  # from create_dispatch_closures
    )

    # 2. Inject initial prompt as a real session event (user-role Content),
    #    NOT via MESSAGE_HISTORY state. ADK's _ContentLlmRequestProcessor
    #    picks it up automatically from session events.
    yield Event(
        invocation_id=ctx.invocation_id,
        author=self.name,
        content=types.Content(
            role="user",
            parts=[types.Part.from_text(text=initial_prompt)],
        ),
    )

    # 3. Delegate to ADK step loop — NO event_queue drain needed.
    #    Worker telemetry flows through tool_context.state writes in
    #    REPLTool.run_async (C2 fix). ADK wraps those into event state_deltas.
    async for event in self.reasoning_agent.run_async(ctx):
        yield event

    # 4. Extract final_answer from structured output (via output_key in state).
    #    output_key writes serialized JSON — must deserialize (W4 fix).
    raw = ctx.session.state.get(OUTPUT_KEY, "{}")
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    final_answer = parsed.get("final_answer", "")


prompts.py — Rewrite RLM_STATIC_INSTRUCTION:

Replace ```repl block instructions + FINAL()/FINAL_VAR() with:

You have access to two tools:
1. execute_code(code="..."): Execute Python in a persistent REPL.
   Variables persist between calls. Returns stdout, stderr, and variables.
2. set_model_response(final_answer="...", reasoning_summary="..."):
   Provide your final answer. Call ONLY when analysis is complete.


callbacks/reasoning.py — Gut contents manipulation, keep accounting only (C1 fix):

reasoning_before_model:
- DELETE the llm_request.contents = contents line entirely.
  ADK's _ContentLlmRequestProcessor handles contents via include_contents='default'.
- KEEP system_instruction merge (static_si + dynamic_instruction into
  llm_request.config.system_instruction). This is idempotent and safe on every turn.
- KEEP token accounting reads from llm_request AFTER ADK populates it
  (read llm_request.contents that ADK built, don't overwrite it).

reasoning_after_model — Accounting-only (W1 fix):
- DELETE LAST_REASONING_RESPONSE write (no longer needed — ADK manages
  conversation context, orchestrator reads output_key not response text).
- KEEP token accounting:
    def reasoning_after_model(callback_context, llm_response):
        usage = llm_response.usage_metadata
        if usage:
            callback_context.state[REASONING_INPUT_TOKENS] = (
                getattr(usage, "prompt_token_count", 0) or 0
            )
            callback_context.state[REASONING_OUTPUT_TOKENS] = (
                getattr(usage, "candidates_token_count", 0) or 0
            )
        return None


Deprecated/Removed:
- find_code_blocks() in utils/parsing.py — regex extraction eliminated
- find_final_answer() / check_for_final_answer() — structured output replaces sentinels
- format_iteration() — ADK manages conversation context
- build_user_prompt() — no iterative prompt rebuilding
- FINAL_VAR registration in local_repl.py globals
- event_queue parameter + all 3 drain loops — telemetry migrated to tool_context.state (C2)
- LAST_REASONING_RESPONSE state key — dead write path


Max-Iterations Safety (C4 fix):
- Primary: REPLTool internal counter (self._call_count vs self._max_calls).
  Returns error message after threshold, guiding model to call set_model_response.
  Derive max_calls from APP_MAX_ITERATIONS at construction time.
  Self-contained — does not interfere with worker call counts.
- Secondary: RunConfig.max_llm_calls set generously (APP_MAX_ITERATIONS * 10)
  as a hard backstop. Wire where RunConfig is constructed in orchestrator entry
  point, reading APP_MAX_ITERATIONS from session state or config.
- Do NOT use LoopAgent — LlmAgent's internal tool-call loop already provides
  multi-step iteration. LoopAgent would add an unnecessary wrapper layer.


--- Provider-Fake Fixture Format Change ---

New fixture JSON for functionCall responses:

{
  "scenario_id": "tool_call_single_iteration",
  "config": { "model": "gemini-fake", "max_iterations": 5, "retry_delay": 0.0 },
  "responses": [
    {
      "call_index": 0,
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": { "code": "x = 2 + 2\nprint(x)" }
              }
            }]
          },
          "finishReason": "STOP"
        }]
      }
    },
    {
      "call_index": 1,
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": { "final_answer": "The answer is 4" }
              }
            }]
          },
          "finishReason": "STOP"
        }]
      }
    }
  ],
  "expected": {
    "final_answer": "The answer is 4",
    "total_model_calls": 2
  }
}


================================================================================
Phase 4: Worker Dispatch Simplification
================================================================================

--- RED: Update tests_rlm_adk/test_adk_worker_retry.py ---

class TestWorkerOutputSchemaBifurcatedWiring:
    """C3 fix: wiring depends on whether worker_repl is present."""

    @pytest.mark.asyncio
    async def test_worker_with_repl_and_schema_has_repl_tool_only(self):
        """When worker_repl is provided, tools=[REPLTool] + output_schema set.
        _OutputSchemaRequestProcessor injects SetModelResponseTool at runtime."""
        pool = WorkerPool(...)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        repl = LocalREPL()
        repl_tool = REPLTool(repl=repl)
        worker.tools = [repl_tool]
        worker.output_schema = SomeSchema
        assert len(worker.tools) == 1  # Only REPLTool in .tools
        assert worker.tools[0].name == "execute_code"
        assert worker.output_schema == SomeSchema
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_worker_without_repl_has_explicit_set_model_response(self):
        """T4: When worker_repl is None, explicit SetModelResponseTool is required.
        _OutputSchemaRequestProcessor won't fire with empty tools."""
        pool = WorkerPool(...)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        worker.output_schema = SomeSchema
        worker.tools = [SetModelResponseTool(SomeSchema)]
        assert len(worker.tools) == 1
        assert worker.tools[0]._get_declaration().name == "set_model_response"

    @pytest.mark.asyncio
    async def test_worker_output_schema_no_tools_processor_skips(self):
        """T4 regression: output_schema + empty tools = processor early-returns,
        no SetModelResponseTool injected. This scenario MUST use explicit tool."""
        pool = WorkerPool(...)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        worker.output_schema = SomeSchema
        worker.tools = []  # BUG: processor skips, no structured output
        # This is the broken state — test documents the failure mode
        assert len(worker.tools) == 0
        # Verify processor would skip:
        assert not worker.tools  # not agent.tools → True → early return

    @pytest.mark.asyncio
    async def test_worker_cleanup_resets_all_wiring(self):
        pool = WorkerPool(...)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        worker.output_schema = SomeSchema
        worker.tools = [SetModelResponseTool(SomeSchema)]
        worker.after_tool_callback = lambda *a: None
        worker.on_tool_error_callback = lambda *a: None
        # Cleanup:
        worker.output_schema = None
        worker.tools = []
        worker.after_tool_callback = None
        worker.on_tool_error_callback = None
        assert worker.output_schema is None
        assert worker.tools == []


class TestWorkerRetryPluginWithToolNameGuard:
    """W2+W9: error callback + retry plugin must guard on tool name."""

    @pytest.mark.asyncio
    async def test_extract_error_ignores_repl_tool(self):
        plugin = WorkerRetryPlugin(max_retries=2)
        tool = MagicMock()
        tool.name = "execute_code"
        error = plugin.extract_error_from_result(
            result={"stdout": "hello", "stderr": ""},
            tool=tool,
            tool_args={"code": "print('hello')"},
            tool_context=_make_tool_context(),
        )
        assert error is None

    @pytest.mark.asyncio
    async def test_extract_error_catches_set_model_response(self):
        plugin = WorkerRetryPlugin(max_retries=2)
        tool = MagicMock()
        tool.name = "set_model_response"
        error = plugin.extract_error_from_result(
            result={"summary": "", "analysis": ""},  # empty values
            tool=tool,
            tool_args={"summary": "", "analysis": ""},
            tool_context=_make_tool_context(),
        )
        assert error is not None

    def test_set_model_response_tool_name_matches_guard_constant(self):
        """W9: Verify synthesized name matches the guard string."""
        from rlm_adk.callbacks.worker_retry import _SET_MODEL_RESPONSE_TOOL_NAME
        tool = SetModelResponseTool(SomeSchema)
        assert tool._get_declaration().name == _SET_MODEL_RESPONSE_TOOL_NAME


class TestWorkerErrorCallbackToolNameGuard:
    """W2: on_tool_error_callback must ignore execute_code errors."""

    @pytest.mark.asyncio
    async def test_error_callback_ignores_repl_errors(self):
        _, error_cb = make_worker_tool_callbacks(max_retries=2)
        # Simulate REPLTool error — should pass through, not trigger retry
        result = error_cb(
            tool_context=_make_tool_context(),
            tool_name="execute_code",
            error=RuntimeError("REPL crashed"),
        )
        assert result is None  # None = don't intercept

    @pytest.mark.asyncio
    async def test_error_callback_handles_set_model_response_errors(self):
        _, error_cb = make_worker_tool_callbacks(max_retries=2)
        result = error_cb(
            tool_context=_make_tool_context(),
            tool_name="set_model_response",
            error=ValidationError("bad schema"),
        )
        assert result is not None  # intercept and reflect


--- RED: tests_rlm_adk/test_worker_processor_runtime.py (T5) ---

class TestWorkerProcessorRuntimeState:
    """T5: Verify _OutputSchemaRequestProcessor injects SetModelResponseTool
    at runtime when tools=[REPLTool] + output_schema are both set."""

    @pytest.mark.asyncio
    async def test_processor_injects_set_model_response_alongside_repl(self):
        """After processor fires, LlmRequest.tools should contain BOTH
        execute_code AND set_model_response."""
        repl = LocalREPL()
        worker = LlmAgent(
            name="test_worker",
            model="gemini-fake",
            tools=[REPLTool(repl=repl)],
            output_schema=SomeSchema,
        )
        # Build a mock InvocationContext + LlmRequest and run processor
        # ... (use real _OutputSchemaRequestProcessor.run_async) ...
        # Assert both tools present in final request
        tool_names = [t.name for t in llm_request.tools]
        assert "execute_code" in tool_names
        assert "set_model_response" in tool_names
        repl.cleanup()


--- RED: tests_rlm_adk/test_worker_with_repl_tool.py ---

class TestWorkerREPLExecution:
    """Workers can use REPL before submitting structured output."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fake_gemini",
        [FIXTURE_DIR / "worker_repl_then_structured_output.json"],
        indirect=True,
    )
    async def test_worker_executes_repl_then_returns_structured(self, fake_gemini):
        result = await run_fixture_contract_with_plugins(fake_gemini.fixture_path)
        assert result.contract.passed
        # Worker should have used REPL before submitting final structured output


--- RED: tests_rlm_adk/test_parallel_worker_repl_no_chdir_race.py ---

class TestParallelWorkerChdirSafety:
    @pytest.mark.asyncio
    async def test_concurrent_repls_do_not_race_on_chdir(self):
        repl_a = LocalREPL()
        repl_b = LocalREPL()
        # Run both concurrently — neither should corrupt the other's cwd
        result_a, result_b = await asyncio.gather(
            asyncio.to_thread(repl_a.execute_code, "import os; print(os.getcwd())"),
            asyncio.to_thread(repl_b.execute_code, "import os; print(os.getcwd())"),
        )
        # Each REPL should see its OWN temp dir, not the other's
        assert repl_a.temp_dir in result_a.stdout
        assert repl_b.temp_dir in result_b.stdout
        assert result_a.stdout.strip() != result_b.stdout.strip()
        repl_a.cleanup()
        repl_b.cleanup()


--- GREEN ---

dispatch.py — Bifurcated wiring (C3 fix, lines 394-403):

Before:
    if output_schema is not None:
        worker.tools = [SetModelResponseTool(output_schema)]
        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
        worker.after_tool_callback = after_cb
        worker.on_tool_error_callback = error_cb
        worker._structured_result = None

After:
    if output_schema is not None:
        worker.output_schema = output_schema
        if worker_repl is not None:
            # tools=[REPLTool] → processor sees non-empty tools + output_schema
            # → injects SetModelResponseTool into LlmRequest at runtime
            worker.tools = [REPLTool(worker_repl)]
        else:
            # tools=[] → processor early-returns (not agent.tools → True)
            # → explicit SetModelResponseTool required
            worker.tools = [SetModelResponseTool(output_schema)]
        after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
        worker.after_tool_callback = after_cb
        worker.on_tool_error_callback = error_cb
        worker._structured_result = None

Cleanup in finally: reset ALL wiring:
    worker.output_schema = None
    worker.tools = []
    worker.after_tool_callback = None
    worker.on_tool_error_callback = None
    worker.parent_agent = None

dispatch.py — Remove event_queue, add flush_fn (C2 fix):

create_dispatch_closures() signature change:
  Before: (worker_pool, ctx, event_queue, ...)
  After:  (worker_pool, ctx, ...)  # no event_queue

  Returns: (llm_query_async, llm_query_batched_async, flush_fn)
  flush_fn: Callable[[], dict] — snapshots + resets local accumulators,
  returns dict of state keys to write. Called by REPLTool.run_async.

  Remove all event_queue.put_nowait() calls. Local accumulators (_acc_*)
  already track everything. flush_fn reads and resets them:

  def flush_fn() -> dict:
      nonlocal _acc_dispatch_count, _acc_total_dispatches, ...
      delta = {
          WORKER_DISPATCH_COUNT: _acc_dispatch_count,
          OBS_WORKER_TOTAL_DISPATCHES: _acc_total_dispatches,
          OBS_WORKER_DISPATCH_LATENCY_MS: list(_acc_latencies),
          ...
      }
      _acc_dispatch_count = 0
      _acc_latencies.clear()
      ...
      return delta

WorkerRetryPlugin — Add tool-name guard to on_tool_error_callback (W2 fix):

def error_cb(tool_context, tool_name, error, ...):
    if tool_name != _SET_MODEL_RESPONSE_TOOL_NAME:
        return None  # Let REPL errors pass through normally
    # ... existing retry/reflection logic ...

Add module-level constant (W9 fix):
_SET_MODEL_RESPONSE_TOOL_NAME = "set_model_response"

os.chdir Race Fix (local_repl.py):
Replace os.chdir(self.temp_dir) with ContextVar-based CWD or
path-qualified operations for parallel worker safety.


================================================================================
Sequencing
================================================================================

Phase 1: Depth-Scoped State     ──┐
                                   ├──→ Phase 3: Reasoning Agent Redesign
Phase 2: REPLTool               ──┘         │
                                              ↓
                                     Phase 4: Worker Dispatch Simplification

Phases 1 and 2 are independent and can be done in parallel.
Phase 3 depends on both. Phase 4 depends on Phase 3.

Per-phase TDD cycle:
  1. Write all RED tests for the phase (they fail)
  2. Write GREEN production code (tests pass)
  3. Run full suite to verify no regressions


================================================================================
Review Fix Traceability
================================================================================

Each fix from REPL_to_REPL_tool_update_REVIEW.md is addressed:

CRITICAL:
  C1  reasoning_before_model incompatible with collapsed loop
      → Phase 3: include_contents='default', callback gutted to
        system_instruction merge + token accounting only. No contents writes.

  C2  Worker event queue drain has no replacement
      → Phase 2: REPLTool.flush_fn writes accumulators to tool_context.state.
      → Phase 4: dispatch removes event_queue, returns flush_fn instead.
        ADK wraps tool_context.state mutations into event state_deltas.

  C3  output_schema + empty tools breaks structured output on workers
      → Phase 4: Bifurcated wiring — REPLTool present → processor injects
        SetModelResponseTool; no REPL → explicit SetModelResponseTool.

  C4  RunConfig.max_llm_calls unsuitable as primary safety
      → Phase 2: REPLTool._call_count as primary limit (self-contained).
      → Phase 3: RunConfig.max_llm_calls as generous backstop only.

WARNINGS:
  W1  Token accounting goes dark    → Phase 3: accounting-only after_model callback
  W2  Error callback no tool guard  → Phase 4: tool_name != "set_model_response" guard
  W3  Schema missing observability  → Phase 3: NOTE — keep schema minimal, use tool_context.state
  W4  output_key serialized JSON    → Phase 3: json.loads deserialization in orchestrator
  W5  DEPTH_SCOPED_KEYS dead keys   → Phase 1: removed LAST_REASONING_RESPONSE, CURRENT_CODE_BLOCKS
  W6  Dispatch telemetry dropped    → Addressed by C2 fix
  W7  Missing disallow_transfer     → Phase 3: flags on create_reasoning_agent
  W8  Event ordering non-determ.    → Addressed by C2 fix (tool_context.state is synchronous)
  W9  Tool name guard unverified    → Phase 4: _SET_MODEL_RESPONSE_TOOL_NAME constant + assertion

TEST GAPS:
  T1  Multi-turn contents integrity → Phase 3: test_multi_turn_contents_integrity.py
  T2  Missing kwargs in retry tests → Phase 4: added tool_args + tool_context kwargs
  T3  output_key deserialization    → Phase 3: test_output_key_deserialization.py
  T4  No-tools regression test      → Phase 4: test_worker_output_schema_no_tools_processor_skips
  T5  Pre-processor vs runtime      → Phase 4: test_worker_processor_runtime.py

INFO (from review, addressed in plan):
  - REPLTool.run_async top-level exception handler → Phase 2: try/except in run_async
  - @d{N} suffix keys avoid temp: stripping → No action needed (correct as-is)
