"""FR-010: Prompt awareness for persistent assets.

build_user_prompt shall append context-count and history-count notices
when counts > 1.  Pure-function unit tests.
"""

from rlm_adk.types import QueryMetadata
from rlm_adk.utils.prompts import (
    RLM_SYSTEM_PROMPT,
    build_rlm_system_prompt,
    build_user_prompt,
)


class TestBuildUserPrompt:
    """FR-010: Prompt construction and context/history notices."""

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

    def test_single_context_no_notice(self):
        msg = build_user_prompt(context_count=1)
        assert "contexts available" not in msg["content"]

    def test_multiple_contexts_notice(self):
        msg = build_user_prompt(context_count=3)
        assert "3 contexts" in msg["content"]
        assert "context_0" in msg["content"]
        assert "context_2" in msg["content"]

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


class TestBuildRlmSystemPrompt:
    """System prompt construction with metadata."""

    def test_returns_list_of_dicts(self):
        qm = QueryMetadata("hello")
        result = build_rlm_system_prompt(RLM_SYSTEM_PROMPT, qm)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "assistant"

    def test_metadata_includes_total_length(self):
        qm = QueryMetadata("hello world")
        result = build_rlm_system_prompt(RLM_SYSTEM_PROMPT, qm)
        assert "11" in result[1]["content"]

    def test_metadata_includes_context_type(self):
        qm = QueryMetadata({"key": "val"})
        result = build_rlm_system_prompt(RLM_SYSTEM_PROMPT, qm)
        assert "dict" in result[1]["content"]

    def test_custom_system_prompt(self):
        qm = QueryMetadata("x")
        result = build_rlm_system_prompt("Custom instructions.", qm)
        assert result[0]["content"] == "Custom instructions."

    def test_large_chunk_count_truncated(self):
        """More than 100 chunks should be truncated in metadata."""
        many_items = ["x"] * 150
        qm = QueryMetadata(many_items)
        result = build_rlm_system_prompt(RLM_SYSTEM_PROMPT, qm)
        assert "others" in result[1]["content"]


class TestSystemPromptContent:
    """Verify system prompt contains required elements."""

    def test_mentions_context_variable(self):
        assert "context" in RLM_SYSTEM_PROMPT.lower()

    def test_mentions_llm_query(self):
        assert "llm_query" in RLM_SYSTEM_PROMPT

    def test_mentions_llm_query_batched(self):
        assert "llm_query_batched" in RLM_SYSTEM_PROMPT

    def test_mentions_final(self):
        assert "FINAL(" in RLM_SYSTEM_PROMPT

    def test_mentions_final_var(self):
        assert "FINAL_VAR" in RLM_SYSTEM_PROMPT

    def test_mentions_show_vars(self):
        assert "SHOW_VARS" in RLM_SYSTEM_PROMPT

    def test_mentions_repl_tag(self):
        assert "```repl" in RLM_SYSTEM_PROMPT
