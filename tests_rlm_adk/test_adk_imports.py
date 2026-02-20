"""FR-014: Public API importability.

Core ADK package exports must be importable without circular-import failures.
``__all__`` declarations must map to valid exports with no duplicate names.
"""

import importlib


class TestPackageImport:
    """Verify top-level rlm_adk package imports cleanly."""

    def test_import_rlm_adk(self):
        mod = importlib.import_module("rlm_adk")
        assert hasattr(mod, "create_rlm_orchestrator")
        assert hasattr(mod, "create_rlm_app")
        assert hasattr(mod, "create_rlm_runner")

    def test_rlm_adk_all_no_duplicates(self):
        mod = importlib.import_module("rlm_adk")
        all_names = mod.__all__
        assert len(all_names) == len(set(all_names)), "Duplicate names in __all__"

    def test_rlm_adk_all_resolvable(self):
        mod = importlib.import_module("rlm_adk")
        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not resolvable"


class TestSubpackageImports:
    """Verify all subpackage imports succeed without circular dependencies."""

    def test_import_types(self):
        from rlm_adk.types import (
            REPLResult,
            RLMChatCompletion,
        )

        assert RLMChatCompletion is not None
        assert REPLResult is not None

    def test_import_state(self):
        from rlm_adk.state import (
            APP_MAX_DEPTH,
        )

        assert APP_MAX_DEPTH == "app:max_depth"

    def test_import_parsing(self):
        from rlm_adk.utils.parsing import find_code_blocks, find_final_answer

        assert callable(find_code_blocks)
        assert callable(find_final_answer)

    def test_import_prompts(self):
        from rlm_adk.utils.prompts import (
            RLM_STATIC_INSTRUCTION,
            build_user_prompt,
        )

        assert callable(build_user_prompt)
        assert len(RLM_STATIC_INSTRUCTION) > 0

    def test_import_local_repl(self):
        from rlm_adk.repl.local_repl import LocalREPL

        assert callable(LocalREPL)

    def test_import_ast_rewriter(self):
        from rlm_adk.repl.ast_rewriter import (
            has_llm_calls,
        )

        assert callable(has_llm_calls)

    def test_import_dispatch(self):
        from rlm_adk.dispatch import WorkerPool

        assert callable(WorkerPool)

    def test_import_orchestrator(self):
        from rlm_adk.orchestrator import RLMOrchestratorAgent

        assert RLMOrchestratorAgent is not None

    def test_import_callbacks(self):
        from rlm_adk.callbacks import (
            reasoning_before_model,
        )

        assert callable(reasoning_before_model)

    def test_import_callbacks_all_no_duplicates(self):
        mod = importlib.import_module("rlm_adk.callbacks")
        all_names = mod.__all__
        assert len(all_names) == len(set(all_names))

    def test_import_plugins(self):
        from rlm_adk.plugins import (
            CachePlugin,
        )

        assert CachePlugin is not None

    def test_import_plugins_all_no_duplicates(self):
        mod = importlib.import_module("rlm_adk.plugins")
        all_names = mod.__all__
        assert len(all_names) == len(set(all_names))

    def test_import_plugins_all_resolvable(self):
        mod = importlib.import_module("rlm_adk.plugins")
        for name in mod.__all__:
            assert hasattr(mod, name), f"{name} listed in __all__ but not resolvable"

    def test_import_agent(self):
        from rlm_adk.agent import (
            create_reasoning_agent,
            create_rlm_app,
            create_rlm_orchestrator,
            create_rlm_runner,
        )

        assert callable(create_rlm_orchestrator)
        assert callable(create_reasoning_agent)
        assert callable(create_rlm_app)
        assert callable(create_rlm_runner)

    def test_agent_module_exports_app(self):
        """ADK CLI discovers ``app`` (App instance) before ``root_agent``."""
        from google.adk.apps.app import App

        mod = importlib.import_module("rlm_adk.agent")
        assert hasattr(mod, "app"), "agent.py must export 'app' for ADK CLI"
        assert isinstance(mod.app, App)
        assert len(mod.app.plugins) >= 1, "App should have at least ObservabilityPlugin"

    def test_agent_app_contains_observability_plugin(self):
        from rlm_adk.agent import app
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin_types = [type(p) for p in app.plugins]
        assert ObservabilityPlugin in plugin_types

    def test_create_rlm_runner_returns_runner(self):
        """create_rlm_runner() returns a Runner wrapping the App."""
        from google.adk.runners import Runner

        from rlm_adk.agent import create_rlm_runner

        runner = create_rlm_runner(model="gemini-2.5-flash")
        assert isinstance(runner, Runner)

    def test_runner_has_session_service(self):
        """Runner provides a session_service for state persistence."""
        from rlm_adk.agent import create_rlm_runner

        runner = create_rlm_runner(model="gemini-2.5-flash")
        assert runner.session_service is not None
