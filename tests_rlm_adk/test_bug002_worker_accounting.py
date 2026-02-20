"""Bug 002: Worker accounting keys overwritten in parallel batches.

Verifies that when multiple workers run in parallel, all workers' token
accounting data is preserved (appended to lists), not overwritten by
last-writer-wins scalar assignment.
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.worker import worker_after_model, worker_before_model
from rlm_adk.state import (
    WORKER_CONTENT_COUNT,
    WORKER_INPUT_TOKENS,
    WORKER_OUTPUT_TOKENS,
    WORKER_PROMPT_CHARS,
)


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
    """After 3 parallel workers complete, all 3 workers' token counts must be preserved."""

    def test_three_workers_before_model_all_prompt_chars_preserved(self):
        """Simulate 3 workers calling worker_before_model on shared state.
        All 3 prompt_chars values must be preserved, not just the last one."""
        shared_state = {}

        prompts = [
            "Short prompt",          # 12 chars
            "A medium length prompt for testing purposes",  # 43 chars
            "X" * 1000,              # 1000 chars
        ]

        for i, prompt_text in enumerate(prompts):
            agent = _make_agent(name=f"worker_{i+1}", prompt=prompt_text)
            ctx = _make_callback_context(state=shared_state, agent=agent)
            request = _make_llm_request_with_content(prompt_text)
            worker_before_model(ctx, request)

        # All 3 values must be preserved in a list
        prompt_chars = shared_state[WORKER_PROMPT_CHARS]
        assert isinstance(prompt_chars, list), (
            f"WORKER_PROMPT_CHARS should be a list, got {type(prompt_chars).__name__}"
        )
        assert len(prompt_chars) == 3, (
            f"Expected 3 entries in WORKER_PROMPT_CHARS, got {len(prompt_chars)}"
        )
        # Verify each worker's value is present
        assert prompt_chars[0] == len("Short prompt")
        assert prompt_chars[1] == len("A medium length prompt for testing purposes")
        assert prompt_chars[2] == 1000

    def test_three_workers_before_model_all_content_counts_preserved(self):
        """All 3 content_count values must be preserved in a list."""
        shared_state = {}

        prompts = ["prompt1", "prompt2", "prompt3"]
        for i, prompt_text in enumerate(prompts):
            agent = _make_agent(name=f"worker_{i+1}", prompt=prompt_text)
            ctx = _make_callback_context(state=shared_state, agent=agent)
            request = _make_llm_request_with_content(prompt_text)
            worker_before_model(ctx, request)

        content_counts = shared_state[WORKER_CONTENT_COUNT]
        assert isinstance(content_counts, list), (
            f"WORKER_CONTENT_COUNT should be a list, got {type(content_counts).__name__}"
        )
        assert len(content_counts) == 3

    def test_three_workers_after_model_all_input_tokens_preserved(self):
        """Simulate 3 workers calling worker_after_model on shared state.
        All 3 input_token values must be preserved."""
        shared_state = {}

        token_data = [
            ("response1", 100, 50),
            ("response2", 5000, 200),
            ("response3", 321502, 824),
        ]

        for i, (text, inp_tok, out_tok) in enumerate(token_data):
            agent = _make_agent(name=f"worker_{i+1}")
            ctx = _make_callback_context(state=shared_state, agent=agent)
            response = _make_llm_response_with_usage(text, inp_tok, out_tok)
            worker_after_model(ctx, response)

        input_tokens = shared_state[WORKER_INPUT_TOKENS]
        assert isinstance(input_tokens, list), (
            f"WORKER_INPUT_TOKENS should be a list, got {type(input_tokens).__name__}"
        )
        assert len(input_tokens) == 3, (
            f"Expected 3 entries in WORKER_INPUT_TOKENS, got {len(input_tokens)}"
        )
        assert input_tokens[0] == 100
        assert input_tokens[1] == 5000
        assert input_tokens[2] == 321502

    def test_three_workers_after_model_all_output_tokens_preserved(self):
        """All 3 output_token values must be preserved in a list."""
        shared_state = {}

        token_data = [
            ("response1", 100, 50),
            ("response2", 5000, 200),
            ("response3", 321502, 824),
        ]

        for i, (text, inp_tok, out_tok) in enumerate(token_data):
            agent = _make_agent(name=f"worker_{i+1}")
            ctx = _make_callback_context(state=shared_state, agent=agent)
            response = _make_llm_response_with_usage(text, inp_tok, out_tok)
            worker_after_model(ctx, response)

        output_tokens = shared_state[WORKER_OUTPUT_TOKENS]
        assert isinstance(output_tokens, list), (
            f"WORKER_OUTPUT_TOKENS should be a list, got {type(output_tokens).__name__}"
        )
        assert len(output_tokens) == 3
        assert output_tokens[0] == 50
        assert output_tokens[1] == 200
        assert output_tokens[2] == 824


class TestWorkerAccountingUsesListAppend:
    """Verify the accounting state uses list-append, not scalar overwrite."""

    def test_before_model_appends_not_overwrites(self):
        """Calling worker_before_model twice should produce a 2-element list,
        not a scalar that equals only the second value."""
        shared_state = {}

        # First worker
        agent1 = _make_agent(name="worker_1", prompt="hello")
        ctx1 = _make_callback_context(state=shared_state, agent=agent1)
        req1 = _make_llm_request_with_content("hello")
        worker_before_model(ctx1, req1)

        # Second worker
        agent2 = _make_agent(name="worker_2", prompt="world!!")
        ctx2 = _make_callback_context(state=shared_state, agent=agent2)
        req2 = _make_llm_request_with_content("world!!")
        worker_before_model(ctx2, req2)

        prompt_chars = shared_state[WORKER_PROMPT_CHARS]
        # Must NOT be a scalar equal to only the second value
        assert prompt_chars != len("world!!"), (
            "WORKER_PROMPT_CHARS is a scalar matching only the last writer -- "
            "this is the overwrite bug"
        )
        assert isinstance(prompt_chars, list)
        assert len(prompt_chars) == 2

    def test_after_model_appends_not_overwrites(self):
        """Calling worker_after_model twice should produce 2-element lists,
        not scalars that equal only the second value."""
        shared_state = {}

        # First worker
        agent1 = _make_agent(name="worker_1")
        ctx1 = _make_callback_context(state=shared_state, agent=agent1)
        resp1 = _make_llm_response_with_usage("r1", 100, 50)
        worker_after_model(ctx1, resp1)

        # Second worker
        agent2 = _make_agent(name="worker_2")
        ctx2 = _make_callback_context(state=shared_state, agent=agent2)
        resp2 = _make_llm_response_with_usage("r2", 9999, 8888)
        worker_after_model(ctx2, resp2)

        input_tokens = shared_state[WORKER_INPUT_TOKENS]
        output_tokens = shared_state[WORKER_OUTPUT_TOKENS]

        assert input_tokens != 9999, (
            "WORKER_INPUT_TOKENS is a scalar matching only the last writer"
        )
        assert output_tokens != 8888, (
            "WORKER_OUTPUT_TOKENS is a scalar matching only the last writer"
        )
        assert isinstance(input_tokens, list)
        assert isinstance(output_tokens, list)
        assert len(input_tokens) == 2
        assert len(output_tokens) == 2

    def test_single_worker_still_produces_list(self):
        """Even a single worker invocation should store values in a list
        for consistency."""
        shared_state = {}

        agent = _make_agent(name="worker_1", prompt="test")
        ctx = _make_callback_context(state=shared_state, agent=agent)
        req = _make_llm_request_with_content("test")
        worker_before_model(ctx, req)

        resp = _make_llm_response_with_usage("output", 500, 100)
        worker_after_model(ctx, resp)

        assert isinstance(shared_state[WORKER_PROMPT_CHARS], list)
        assert isinstance(shared_state[WORKER_CONTENT_COUNT], list)
        assert isinstance(shared_state[WORKER_INPUT_TOKENS], list)
        assert isinstance(shared_state[WORKER_OUTPUT_TOKENS], list)

        assert shared_state[WORKER_PROMPT_CHARS] == [len("test")]
        assert shared_state[WORKER_CONTENT_COUNT] == [1]
        assert shared_state[WORKER_INPUT_TOKENS] == [500]
        assert shared_state[WORKER_OUTPUT_TOKENS] == [100]
