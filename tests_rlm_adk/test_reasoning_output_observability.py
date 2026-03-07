from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.reasoning import reasoning_after_model
from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.state import (
    FINAL_ANSWER,
    OBS_REASONING_RETRY_COUNT,
    OBS_REASONING_RETRY_DELAY_MS,
    REASONING_PARSED_OUTPUT,
    REASONING_RAW_OUTPUT,
    REASONING_SUMMARY,
    REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS,
    REASONING_VISIBLE_OUTPUT_TEXT,
    SHOULD_STOP,
    depth_key,
)


def _make_callback_context(depth: int = 0):
    ctx = MagicMock()
    ctx.state = {}
    ctx._invocation_context.agent._rlm_depth = depth
    return ctx


def _make_response() -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part.from_text(text="Visible answer."),
                types.Part(text="Hidden chain of thought.", thought=True),
            ],
        ),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=13,
            candidates_token_count=8,
            thoughts_token_count=5,
        ),
    )


class TestReasoningAfterModelObservability:
    def test_persists_visible_and_thought_text_by_depth(self):
        ctx = _make_callback_context(depth=2)

        reasoning_after_model(ctx, _make_response())

        assert ctx.state[depth_key(REASONING_VISIBLE_OUTPUT_TEXT, 2)] == "Visible answer."
        assert ctx.state[depth_key(REASONING_THOUGHT_TEXT, 2)] == "Hidden chain of thought."
        assert ctx.state[depth_key(REASONING_THOUGHT_TOKENS, 2)] == 5
        assert depth_key(REASONING_RAW_OUTPUT, 2) not in ctx.state


class TestOrchestratorReasoningOutputPersistence:
    @pytest.mark.asyncio
    async def test_persists_raw_and_parsed_output_by_depth(self):
        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output@d2",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            worker_pool=None,
            depth=2,
        )

        async def mock_run_async(ctx):
            return
            yield

        object.__setattr__(reasoning_agent, "run_async", mock_run_async)

        ctx = MagicMock()
        ctx.invocation_id = "test-inv"
        ctx.session.state = {
            "reasoning_output@d2": (
                '{"final_answer":"done","reasoning_summary":"short summary"}'
            ),
        }

        with patch("rlm_adk.orchestrator.save_final_answer", new=AsyncMock()):
            events = [event async for event in orch._run_async_impl(ctx)]

        deltas = [
            event.actions.state_delta
            for event in events
            if getattr(getattr(event, "actions", None), "state_delta", None)
        ]
        merged = {}
        for delta in deltas:
            merged.update(delta)

        assert merged[depth_key(REASONING_RAW_OUTPUT, 2)] == (
            '{"final_answer":"done","reasoning_summary":"short summary"}'
        )
        assert merged[depth_key(REASONING_PARSED_OUTPUT, 2)] == {
            "final_answer": "done",
            "reasoning_summary": "short summary",
        }
        assert merged[depth_key(REASONING_SUMMARY, 2)] == "short summary"
        assert merged[depth_key(FINAL_ANSWER, 2)] == "done"
        assert merged[depth_key(SHOULD_STOP, 2)] is True

    @pytest.mark.asyncio
    async def test_persists_retry_count_and_cumulative_delay(self):
        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            worker_pool=None,
            depth=0,
        )

        calls = {"count": 0}

        async def flaky_run_async(ctx):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("transient")
            ctx.session.state["reasoning_output"] = '{"final_answer":"done"}'
            return
            yield

        object.__setattr__(reasoning_agent, "run_async", flaky_run_async)

        ctx = MagicMock()
        ctx.invocation_id = "test-inv"
        ctx.session.state = {}

        with patch("rlm_adk.orchestrator.save_final_answer", new=AsyncMock()), \
             patch("rlm_adk.orchestrator.asyncio.sleep", new=AsyncMock()) as sleep_mock, \
             patch("rlm_adk.orchestrator.os.getenv") as getenv_mock:
            def _getenv(key, default=None):
                if key == "RLM_LLM_MAX_RETRIES":
                    return "1"
                if key == "RLM_LLM_RETRY_DELAY":
                    return "0.25"
                return default

            getenv_mock.side_effect = _getenv
            events = [event async for event in orch._run_async_impl(ctx)]

        deltas = [
            event.actions.state_delta
            for event in events
            if getattr(getattr(event, "actions", None), "state_delta", None)
        ]
        merged = {}
        for delta in deltas:
            merged.update(delta)

        sleep_mock.assert_awaited_once_with(0.25)
        assert merged[OBS_REASONING_RETRY_COUNT] == 1
        assert merged[OBS_REASONING_RETRY_DELAY_MS] == 250

    @pytest.mark.asyncio
    async def test_persists_zero_retry_delay_when_backoff_is_zero(self):
        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            worker_pool=None,
            depth=0,
        )

        calls = {"count": 0}

        async def flaky_run_async(ctx):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("transient")
            ctx.session.state["reasoning_output"] = '{"final_answer":"done"}'
            return
            yield

        object.__setattr__(reasoning_agent, "run_async", flaky_run_async)

        ctx = MagicMock()
        ctx.invocation_id = "test-inv"
        ctx.session.state = {}

        with patch("rlm_adk.orchestrator.save_final_answer", new=AsyncMock()), \
             patch("rlm_adk.orchestrator.asyncio.sleep", new=AsyncMock()) as sleep_mock, \
             patch("rlm_adk.orchestrator.os.getenv") as getenv_mock:
            def _getenv(key, default=None):
                if key == "RLM_LLM_MAX_RETRIES":
                    return "1"
                if key == "RLM_LLM_RETRY_DELAY":
                    return "0"
                return default

            getenv_mock.side_effect = _getenv
            events = [event async for event in orch._run_async_impl(ctx)]

        deltas = [
            event.actions.state_delta
            for event in events
            if getattr(getattr(event, "actions", None), "state_delta", None)
        ]
        merged = {}
        for delta in deltas:
            merged.update(delta)

        sleep_mock.assert_awaited_once_with(0.0)
        assert merged[OBS_REASONING_RETRY_COUNT] == 1
        assert merged[OBS_REASONING_RETRY_DELAY_MS] == 0
