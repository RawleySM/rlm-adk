"""Phase 3 Part B: Prompt rewrite tests for tool-calling instructions.

Tests that RLM_STATIC_INSTRUCTION references execute_code / set_model_response
tools and no longer references ```repl fences or FINAL()/FINAL_VAR() patterns.

RED: These tests will fail until RLM_STATIC_INSTRUCTION is rewritten in
rlm_adk/utils/prompts.py.
"""

from rlm_adk.utils.prompts import RLM_STATIC_INSTRUCTION


class TestToolCallingPrompt:
    def test_prompt_mentions_execute_code_tool(self):
        """Prompt must reference the execute_code tool."""
        assert "execute_code" in RLM_STATIC_INSTRUCTION

    def test_prompt_mentions_set_model_response(self):
        """Prompt must reference the set_model_response tool."""
        assert "set_model_response" in RLM_STATIC_INSTRUCTION

    def test_prompt_does_not_mention_repl_fence(self):
        """The old ```repl code fence pattern should be removed."""
        assert "```repl" not in RLM_STATIC_INSTRUCTION

    def test_prompt_does_not_mention_FINAL(self):
        """The old FINAL()/FINAL_VAR() patterns should be removed."""
        assert "FINAL(" not in RLM_STATIC_INSTRUCTION
        assert "FINAL_VAR(" not in RLM_STATIC_INSTRUCTION

    def test_prompt_still_mentions_llm_query(self):
        """llm_query is still available in the REPL -- prompt should reference it."""
        assert "llm_query" in RLM_STATIC_INSTRUCTION

    def test_prompt_still_mentions_llm_query_batched(self):
        """llm_query_batched is still available -- prompt should reference it."""
        assert "llm_query_batched" in RLM_STATIC_INSTRUCTION

    def test_prompt_still_mentions_repl_environment(self):
        """The REPL environment concept should still be described."""
        assert "repl" in RLM_STATIC_INSTRUCTION.lower()
