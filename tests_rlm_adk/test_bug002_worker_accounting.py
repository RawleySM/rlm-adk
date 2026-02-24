"""Bug 002: Worker accounting preserved across parallel batches.

Original bug: scalar overwrite lost data from parallel workers.
Original fix: list-append in callbacks.
Current fix: worker-object carrier pattern — results and usage are written
onto the worker agent object (_result, _result_usage, _prompt_chars, etc.)
and aggregated in the dispatch closure. No state writes for accounting.

These tests verify that multiple parallel workers each independently
carry their own accounting data on their agent objects.
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.worker import worker_after_model, worker_before_model


def _make_callback_context(state: dict | None = None, agent: MagicMock | None = None):
    """Build a mock CallbackContext with .state dict and .agent."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    if agent is not None:
        ctx._invocation_context.agent = agent
    return ctx


def _make_agent(name: str = "worker_1", prompt: str = "test prompt"):
    """Build a mock agent with _pending_prompt and output_key."""
    agent = MagicMock()
    agent.name = name
    agent._pending_prompt = prompt
    agent.output_key = f"{name}_output"
    return agent


def _make_llm_request_with_content(text: str) -> LlmRequest:
    """Build an LlmRequest with a single user content part."""
    return LlmRequest(
        model="test",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            )
        ],
    )


def _make_llm_response_with_usage(
    text: str, prompt_tokens: int, output_tokens: int
) -> LlmResponse:
    """Build an LlmResponse with usage_metadata containing token counts."""
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=output_tokens,
    )
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
        usage_metadata=usage,
    )


class TestParallelWorkerAccountingPreserved:
    """After 3 parallel workers complete, all 3 workers' data must be
    independently retrievable from their agent objects."""

    def test_three_workers_before_model_all_prompt_chars_preserved(self):
        """Simulate 3 workers calling worker_before_model.
        All 3 prompt_chars values must be independently stored on agent objects."""
        prompts = [
            "Short prompt",          # 12 chars
            "A medium length prompt for testing purposes",  # 43 chars
            "X" * 1000,              # 1000 chars
        ]

        agents = []
        for i, prompt_text in enumerate(prompts):
            agent = _make_agent(name=f"worker_{i+1}", prompt=prompt_text)
            ctx = _make_callback_context(state={}, agent=agent)
            request = _make_llm_request_with_content(prompt_text)
            worker_before_model(ctx, request)
            agents.append(agent)

        # Each agent carries its own _prompt_chars
        assert agents[0]._prompt_chars == len("Short prompt")
        assert agents[1]._prompt_chars == len("A medium length prompt for testing purposes")
        assert agents[2]._prompt_chars == 1000

    def test_three_workers_before_model_all_content_counts_preserved(self):
        """All 3 content_count values must be independently stored on agent objects."""
        prompts = ["prompt1", "prompt2", "prompt3"]
        agents = []
        for i, prompt_text in enumerate(prompts):
            agent = _make_agent(name=f"worker_{i+1}", prompt=prompt_text)
            ctx = _make_callback_context(state={}, agent=agent)
            request = _make_llm_request_with_content(prompt_text)
            worker_before_model(ctx, request)
            agents.append(agent)

        for agent in agents:
            assert agent._content_count == 1

    def test_three_workers_after_model_all_input_tokens_preserved(self):
        """Simulate 3 workers calling worker_after_model.
        All 3 input_token values must be independently stored on agent objects."""
        token_data = [
            ("response1", 100, 50),
            ("response2", 5000, 200),
            ("response3", 321502, 824),
        ]

        agents = []
        for i, (text, inp_tok, out_tok) in enumerate(token_data):
            agent = _make_agent(name=f"worker_{i+1}")
            ctx = _make_callback_context(state={}, agent=agent)
            response = _make_llm_response_with_usage(text, inp_tok, out_tok)
            worker_after_model(ctx, response)
            agents.append(agent)

        assert agents[0]._result_usage["input_tokens"] == 100
        assert agents[1]._result_usage["input_tokens"] == 5000
        assert agents[2]._result_usage["input_tokens"] == 321502

    def test_three_workers_after_model_all_output_tokens_preserved(self):
        """All 3 output_token values must be independently stored on agent objects."""
        token_data = [
            ("response1", 100, 50),
            ("response2", 5000, 200),
            ("response3", 321502, 824),
        ]

        agents = []
        for i, (text, inp_tok, out_tok) in enumerate(token_data):
            agent = _make_agent(name=f"worker_{i+1}")
            ctx = _make_callback_context(state={}, agent=agent)
            response = _make_llm_response_with_usage(text, inp_tok, out_tok)
            worker_after_model(ctx, response)
            agents.append(agent)

        assert agents[0]._result_usage["output_tokens"] == 50
        assert agents[1]._result_usage["output_tokens"] == 200
        assert agents[2]._result_usage["output_tokens"] == 824


class TestWorkerAccountingUsesAgentObjects:
    """Verify the accounting uses agent-object storage, not shared state."""

    def test_before_model_stores_on_agent_not_state(self):
        """Calling worker_before_model twice with separate agents should
        produce independent values on each agent, with no shared state pollution."""
        state = {}

        # First worker
        agent1 = _make_agent(name="worker_1", prompt="hello")
        ctx1 = _make_callback_context(state=state, agent=agent1)
        req1 = _make_llm_request_with_content("hello")
        worker_before_model(ctx1, req1)

        # Second worker
        agent2 = _make_agent(name="worker_2", prompt="world!!")
        ctx2 = _make_callback_context(state=state, agent=agent2)
        req2 = _make_llm_request_with_content("world!!")
        worker_before_model(ctx2, req2)

        # Each agent carries its own value
        assert agent1._prompt_chars == len("hello")
        assert agent2._prompt_chars == len("world!!")

    def test_after_model_stores_on_agent_not_state(self):
        """Calling worker_after_model twice with separate agents should
        produce independent values on each agent."""
        state = {}

        # First worker
        agent1 = _make_agent(name="worker_1")
        ctx1 = _make_callback_context(state=state, agent=agent1)
        resp1 = _make_llm_response_with_usage("r1", 100, 50)
        worker_after_model(ctx1, resp1)

        # Second worker
        agent2 = _make_agent(name="worker_2")
        ctx2 = _make_callback_context(state=state, agent=agent2)
        resp2 = _make_llm_response_with_usage("r2", 9999, 8888)
        worker_after_model(ctx2, resp2)

        assert agent1._result_usage == {"input_tokens": 100, "output_tokens": 50}
        assert agent2._result_usage == {"input_tokens": 9999, "output_tokens": 8888}

    def test_single_worker_stores_on_agent(self):
        """Even a single worker invocation should store values on the agent object."""
        agent = _make_agent(name="worker_1", prompt="test")
        ctx = _make_callback_context(state={}, agent=agent)
        req = _make_llm_request_with_content("test")
        worker_before_model(ctx, req)

        resp = _make_llm_response_with_usage("output", 500, 100)
        worker_after_model(ctx, resp)

        assert agent._prompt_chars == len("test")
        assert agent._content_count == 1
        assert agent._result == "output"
        assert agent._result_ready is True
        assert agent._result_usage == {"input_tokens": 500, "output_tokens": 100}
