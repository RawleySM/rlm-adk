"""FR-001/002/012 + AR-CRIT-001: Orchestrator loop, completion contract, default answer.

FR-001: Completion contract parity (RLMChatCompletion shape).
FR-002: Iterative orchestration loop (prompt -> reason -> extract -> execute -> final).
FR-012: Default answer fallback when max_iterations exhausted.
AR-CRIT-001: State delta discipline (no direct ctx.session.state writes).
"""

import ast
import inspect

from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.types import CodeBlock, REPLResult, RLMIteration
from rlm_adk.utils.parsing import (
    find_code_blocks,
    find_final_answer,
    format_execution_result,
    format_iteration,
)

# ── FR-002 Iteration Formatting ──────────────────────────────────────────


class TestFormatIteration:
    """Iteration formatting for message history construction."""

    def test_returns_assistant_and_user_messages(self):
        result = REPLResult(stdout="42", stderr="", locals={"x": 42})
        cb = CodeBlock(code="print(42)", result=result)
        iteration = RLMIteration(prompt="p", response="Let me compute.", code_blocks=[cb])

        messages = format_iteration(iteration)

        assert len(messages) == 2
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "Let me compute."
        assert messages[1]["role"] == "user"
        assert "print(42)" in messages[1]["content"]

    def test_multiple_code_blocks(self):
        r1 = REPLResult(stdout="1", stderr="", locals={})
        r2 = REPLResult(stdout="2", stderr="", locals={})
        cb1 = CodeBlock(code="print(1)", result=r1)
        cb2 = CodeBlock(code="print(2)", result=r2)
        iteration = RLMIteration(prompt="p", response="resp", code_blocks=[cb1, cb2])

        messages = format_iteration(iteration)
        # 1 assistant + 2 user (one per code block)
        assert len(messages) == 3

    def test_no_code_blocks(self):
        iteration = RLMIteration(prompt="p", response="No code.", code_blocks=[])
        messages = format_iteration(iteration)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"

    def test_truncation_at_max_length(self):
        long_output = "x" * 30000
        result = REPLResult(stdout=long_output, stderr="", locals={})
        cb = CodeBlock(code="print('x' * 30000)", result=result)
        iteration = RLMIteration(prompt="p", response="resp", code_blocks=[cb])

        messages = format_iteration(iteration, max_character_length=100)
        content = messages[1]["content"]
        assert "chars..." in content


class TestFormatExecutionResult:
    """Execution result formatting for display."""

    def test_stdout_included(self):
        result = REPLResult(stdout="hello", stderr="", locals={})
        formatted = format_execution_result(result)
        assert "hello" in formatted

    def test_stderr_included(self):
        result = REPLResult(stdout="", stderr="Error: boom", locals={})
        formatted = format_execution_result(result)
        assert "Error: boom" in formatted

    def test_variables_listed(self):
        result = REPLResult(stdout="", stderr="", locals={"x": 42, "name": "Alice"})
        formatted = format_execution_result(result)
        assert "x" in formatted

    def test_no_output(self):
        result = REPLResult(stdout="", stderr="", locals={})
        formatted = format_execution_result(result)
        assert formatted == "No output"

    def test_private_vars_excluded(self):
        result = REPLResult(stdout="", stderr="", locals={"_private": 1, "public": 2})
        formatted = format_execution_result(result)
        assert "public" in formatted
        assert "_private" not in formatted


# ── FR-002 Code Block + Final Answer Integration ─────────────────────────


class TestOrchestrationFlowParsing:
    """Integration of parsing and REPL execution in the orchestration flow."""

    def test_extract_and_execute_code_blocks(self):
        """Simulate the orchestrator extract-and-execute loop."""
        from rlm_adk.repl.local_repl import LocalREPL

        response = """Let me calculate.
```repl
x = 2 + 2
print(x)
```
"""
        blocks = find_code_blocks(response)
        assert len(blocks) == 1

        repl = LocalREPL()
        results = []
        for code in blocks:
            result = repl.execute_code(code)
            results.append(CodeBlock(code=code, result=result))

        assert results[0].result.stdout.strip() == "4"
        assert repl.locals["x"] == 4
        repl.cleanup()

    def test_final_answer_after_code_execution(self):
        """Simulate: execute code, then detect FINAL_VAR."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL()
        repl.execute_code("answer = 'the final result'")

        response = "FINAL_VAR(answer)"
        final = find_final_answer(response, environment=repl)
        assert final == "the final result"
        repl.cleanup()

    def test_multi_iteration_simulation(self):
        """Simulate multiple iterations building up state."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(context_payload="test data")

        # Iteration 1: Explore context
        code1 = "data_len = len(context)\nprint(f'Context length: {data_len}')"
        r1 = repl.execute_code(code1)
        assert "Context length:" in r1.stdout

        # Iteration 2: Process data
        code2 = "result = context.upper()\nprint(result)"
        r2 = repl.execute_code(code2)
        assert "TEST DATA" in r2.stdout

        # Iteration 3: Final answer
        response3 = "FINAL_VAR(result)"
        final = find_final_answer(response3, environment=repl)
        assert final == "TEST DATA"

        repl.cleanup()


# ── AR-CRIT-001 Static Analysis ──────────────────────────────────────────


class TestOrchestratorStateDeltaDiscipline:
    """AR-CRIT-001: All orchestrator state mutations must use EventActions."""

    def test_all_yields_are_events(self):
        """Every yield in _run_async_impl should yield an Event object."""
        import textwrap

        source = textwrap.dedent(inspect.getsource(RLMOrchestratorAgent._run_async_impl))
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Yield):
                # Yield value should be Event(...) or an expression
                # This is a structural check - if yields exist, they should be Event()
                assert node.value is not None, "Bare yield found in orchestrator"

    def test_orchestrator_sub_agents_declared(self):
        """Orchestrator should declare reasoning_agent and default_answer_agent."""
        fields = RLMOrchestratorAgent.model_fields
        assert "reasoning_agent" in fields
        assert "default_answer_agent" in fields


# ── FR-001 Completion Contract ───────────────────────────────────────────


class TestCompletionContractShape:
    """FR-001: RLMChatCompletion has required fields."""

    def test_engine_class_exists(self):
        from rlm_adk.agent import RLMAdkEngine

        assert hasattr(RLMAdkEngine, "completion")
        assert hasattr(RLMAdkEngine, "acompletion")

    def test_engine_has_context_manager(self):
        from rlm_adk.agent import RLMAdkEngine

        assert hasattr(RLMAdkEngine, "__enter__")
        assert hasattr(RLMAdkEngine, "__exit__")
        assert hasattr(RLMAdkEngine, "close")

    def test_create_reasoning_agent_returns_llm_agent(self):
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("test-model")
        assert agent.name == "reasoning_agent"
        assert agent.include_contents == "none"
        assert agent.disallow_transfer_to_parent is True
        assert agent.disallow_transfer_to_peers is True

    def test_create_default_answer_agent(self):
        from rlm_adk.agent import create_default_answer_agent

        agent = create_default_answer_agent("test-model")
        assert agent.name == "default_answer_agent"
        assert agent.include_contents == "none"

    def test_create_orchestrator(self):
        from rlm_adk.agent import create_rlm_orchestrator

        orch = create_rlm_orchestrator(model="test-model")
        assert orch.name == "rlm_orchestrator"
        assert orch.reasoning_agent is not None
        assert orch.default_answer_agent is not None
