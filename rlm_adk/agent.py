"""RLM ADK Application - Wires all components into a runnable ADK App.

This module provides:
- create_rlm_app(): Factory to create the configured ADK App
- RLMAdkEngine: Public API class matching rlm.RLM.completion() interface
"""

import asyncio
import logging
import time
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from rlm_adk.callbacks.default_answer import default_after_model, default_before_model
from rlm_adk.callbacks.reasoning import reasoning_after_model, reasoning_before_model
from rlm_adk.callbacks.worker import worker_after_model, worker_before_model
from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.plugins import (
    CachePlugin,
    DebugLoggingPlugin,
    DepthGuardPlugin,
    ObservabilityPlugin,
    PolicyPlugin,
)
from rlm_adk.state import APP_MAX_DEPTH, APP_MAX_ITERATIONS, TEMP_FINAL_ANSWER
from rlm_adk.types import ModelUsageSummary, RLMChatCompletion, UsageSummary

logger = logging.getLogger(__name__)


def create_reasoning_agent(model: str) -> LlmAgent:
    """Create the ReasoningAgent (main LLM for depth=0 reasoning)."""
    return LlmAgent(
        name="reasoning_agent",
        model=model,
        description="Main reasoning agent for RLM iteration loop",
        instruction="",  # Prompts injected via before_model_callback
        include_contents="none",  # HIGH-3
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        output_key="reasoning_output",
        before_model_callback=reasoning_before_model,
        after_model_callback=reasoning_after_model,
    )


def create_default_answer_agent(model: str) -> LlmAgent:
    """Create the DefaultAnswerAgent (fallback when max iterations reached)."""
    return LlmAgent(
        name="default_answer_agent",
        model=model,
        description="Generates final answer when max iterations exhausted",
        instruction="",  # Prompts injected via before_model_callback
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        output_key="default_answer",
        before_model_callback=default_before_model,
        after_model_callback=default_after_model,
    )


def create_rlm_orchestrator(
    model: str,
    context_payload: Any = None,
    root_prompt: str | None = None,
    system_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
) -> RLMOrchestratorAgent:
    """Create the RLMOrchestratorAgent with all sub-agents."""
    reasoning = create_reasoning_agent(model)
    default_answer = create_default_answer_agent(model)

    kwargs: dict[str, Any] = {
        "name": "rlm_orchestrator",
        "description": "RLM recursive iteration loop orchestrator",
        "reasoning_agent": reasoning,
        "default_answer_agent": default_answer,
        "context_payload": context_payload,
        "root_prompt": root_prompt,
        "persistent": persistent,
        "worker_pool": worker_pool,
        "repl": repl,
        "sub_agents": [reasoning, default_answer],
    }
    if system_prompt:
        kwargs["system_prompt"] = system_prompt

    return RLMOrchestratorAgent(**kwargs)


class RLMAdkEngine:
    """Public API for the ADK-based RLM engine.

    Provides the same interface as rlm.RLM:
    - completion(prompt, root_prompt=None) -> RLMChatCompletion

    Usage:
        engine = RLMAdkEngine(
            model="gemini-2.5-flash",
            other_model="gemini-2.5-flash",  # for sub-calls
            max_iterations=30,
        )
        result = engine.completion("What is 2+2?")
        print(result.response)
    """

    def __init__(
        self,
        model: str,
        other_model: str | None = None,
        max_iterations: int = 30,
        max_depth: int = 1,
        system_prompt: str | None = None,
        persistent: bool = False,
        debug: bool = False,
        blocked_patterns: list[str] | None = None,
        cache_enabled: bool = True,
        cache_max_entries: int = 1000,
        cache_ttl: float = 300.0,
        worker_pool_size: int = 5,
    ):
        self.model = model
        self.other_model = other_model or model
        self.max_iterations = max_iterations
        self.max_depth = max_depth
        self.system_prompt = system_prompt
        self.persistent = persistent
        self.debug = debug
        self.worker_pool_size = worker_pool_size

        # Build plugins list
        self.plugins: list = []
        self.plugins.append(DepthGuardPlugin(name="depth_guard"))
        if cache_enabled:
            self.plugins.append(
                CachePlugin(
                    name="cache",
                    max_entries=cache_max_entries,
                    ttl_seconds=cache_ttl,
                )
            )
        self.plugins.append(ObservabilityPlugin(name="observability"))
        self.plugins.append(
            PolicyPlugin(
                name="policy",
                blocked_patterns=blocked_patterns,
            )
        )
        if debug:
            self.plugins.append(DebugLoggingPlugin(name="debug_logging"))

        # Worker pool for sub-LM dispatch
        self.worker_pool = WorkerPool(
            default_model=model,
            other_model=self.other_model,
            pool_size=worker_pool_size,
        )

        # Persistent REPL (BUG-8)
        self._persistent_repl: Any = None

    def completion(
        self, prompt: str | dict[str, Any], root_prompt: str | None = None
    ) -> RLMChatCompletion:
        """Run an RLM completion synchronously.

        Args:
            prompt: Context payload (string, dict, or list)
            root_prompt: Optional root prompt shown to the LLM

        Returns:
            RLMChatCompletion with response, usage, and timing
        """
        return asyncio.run(self.acompletion(prompt, root_prompt))

    async def acompletion(
        self, prompt: str | dict[str, Any], root_prompt: str | None = None
    ) -> RLMChatCompletion:
        """Run an RLM completion asynchronously."""
        time_start = time.perf_counter()

        # BUG-8: Manage persistent REPL
        repl = None
        if self.persistent:
            if self._persistent_repl is None:
                from rlm_adk.repl.local_repl import LocalREPL

                self._persistent_repl = LocalREPL(context_payload=prompt, depth=1)
            else:
                self._persistent_repl.add_context(prompt)
            repl = self._persistent_repl

        # Create orchestrator for this completion
        orchestrator = create_rlm_orchestrator(
            model=self.model,
            context_payload=prompt,
            root_prompt=root_prompt,
            system_prompt=self.system_prompt,
            persistent=self.persistent,
            worker_pool=self.worker_pool,
            repl=repl,
        )

        # Wire orchestrator + plugins into an ADK App, then pass to runner
        app = App(
            name="rlm_adk",
            root_agent=orchestrator,
            plugins=self.plugins,
        )
        runner = InMemoryRunner(app=app)

        # Create session with app-level state
        session = await runner.session_service.create_session(
            app_name="rlm_adk",
            user_id="rlm_user",
            state={
                APP_MAX_DEPTH: self.max_depth,
                APP_MAX_ITERATIONS: self.max_iterations,
            },
        )

        # Build a short user message for the runner
        prompt_str = str(prompt)
        display_text = prompt_str[:100] + "..." if len(prompt_str) > 100 else prompt_str
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=display_text)],
        )

        # Run and collect the final answer
        final_answer = ""
        async for event in runner.run_async(
            user_id="rlm_user",
            session_id=session.id,
            new_message=content,
        ):
            # Check for final answer in events
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_answer = part.text

        time_end = time.perf_counter()

        # BUG-6: Build usage summary from session state (populated by ObservabilityPlugin)
        session = await runner.session_service.get_session(
            app_name="rlm_adk", user_id="rlm_user", session_id=session.id
        )
        model_summaries = {}
        if session and session.state:
            for key, value in session.state.items():
                if key.startswith("obs:model_usage:") and isinstance(value, dict):
                    model_name = key.replace("obs:model_usage:", "")
                    model_summaries[model_name] = ModelUsageSummary(
                        total_calls=value.get("calls", 0),
                        total_input_tokens=value.get("input_tokens", 0),
                        total_output_tokens=value.get("output_tokens", 0),
                    )
        usage = UsageSummary(model_usage_summaries=model_summaries)

        return RLMChatCompletion(
            root_model=self.model,
            prompt=prompt,
            response=final_answer,
            usage_summary=usage,
            execution_time=time_end - time_start,
        )

    def close(self):
        """Clean up resources."""
        if self._persistent_repl is not None:
            self._persistent_repl.cleanup()
            self._persistent_repl = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
