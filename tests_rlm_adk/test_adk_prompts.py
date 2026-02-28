"""FR-010: Prompt awareness for persistent assets.

build_user_prompt shall append history-count notices when counts > 1.
Pure-function unit tests.
"""

from rlm_adk.utils.prompts import (
    RLM_STATIC_INSTRUCTION,
    build_user_prompt,
)


class TestBuildUserPrompt:
    """FR-010: Prompt construction and history notices."""

    def test_iteration_0_safeguard(self):
        msg = build_user_prompt(root_prompt=None, iteration=0)
        assert msg["role"] == "user"
        assert "not interacted" in msg["content"].lower() or "not" in msg["content"].lower()

    def test_iteration_0_with_root_prompt(self):
        msg = build_user_prompt(root_prompt="What is 2+2?", iteration=0)
        assert "What is 2+2?" in msg["content"]

    def test_iteration_1_references_history(self):
        msg = build_user_prompt(root_prompt=None, iteration=1)
        assert (
            "previous interactions" in msg["content"].lower()
            or "history before" in msg["content"].lower()
        )

    def test_iteration_1_with_root_prompt(self):
        msg = build_user_prompt(root_prompt="Summarize this.", iteration=1)
        assert "Summarize this." in msg["content"]

    def test_no_history_no_notice(self):
        msg = build_user_prompt(history_count=0)
        assert "conversation histor" not in msg["content"]

    def test_single_history_notice(self):
        msg = build_user_prompt(history_count=1)
        assert "1 prior conversation history" in msg["content"]
        assert "`history` variable" in msg["content"]

    def test_multiple_histories_notice(self):
        msg = build_user_prompt(history_count=3)
        assert "3 prior conversation histories" in msg["content"]
        assert "history_0" in msg["content"]
        assert "history_2" in msg["content"]


class TestSystemPromptContent:
    """Verify system prompt contains required elements."""

    def test_mentions_repl_environment(self):
        assert "repl environment" in RLM_STATIC_INSTRUCTION.lower()

    def test_mentions_open_builtin(self):
        assert "open()" in RLM_STATIC_INSTRUCTION

    def test_mentions_import_builtin(self):
        assert "__import__" in RLM_STATIC_INSTRUCTION

    def test_mentions_llm_query(self):
        assert "llm_query" in RLM_STATIC_INSTRUCTION

    def test_mentions_llm_query_batched(self):
        assert "llm_query_batched" in RLM_STATIC_INSTRUCTION

    def test_mentions_execute_code_tool(self):
        """Phase 3: prompt references execute_code tool instead of FINAL()."""
        assert "execute_code" in RLM_STATIC_INSTRUCTION

    def test_mentions_set_model_response_tool(self):
        """Phase 3: prompt references set_model_response tool instead of FINAL_VAR()."""
        assert "set_model_response" in RLM_STATIC_INSTRUCTION

    def test_mentions_show_vars(self):
        assert "SHOW_VARS" in RLM_STATIC_INSTRUCTION

    def test_does_not_mention_repl_tag(self):
        """Phase 3: ```repl code fences replaced by execute_code tool."""
        assert "```repl" not in RLM_STATIC_INSTRUCTION

    def test_no_context_variable_reference(self):
        """Static instruction should not promise a pre-loaded context variable."""
        assert "A `context` variable" not in RLM_STATIC_INSTRUCTION
        assert "initialized with" not in RLM_STATIC_INSTRUCTION.lower() or \
            "context variable" not in RLM_STATIC_INSTRUCTION.lower()
