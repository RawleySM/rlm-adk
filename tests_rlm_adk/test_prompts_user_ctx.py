"""Tests for prompt template refinements — user context manifest support."""

import re

from rlm_adk.utils.prompts import (
    RLM_CHILD_STATIC_INSTRUCTION,
    RLM_DYNAMIC_INSTRUCTION,
    RLM_STATIC_INSTRUCTION,
)


# ---------------------------------------------------------------------------
# Static instruction tests
# ---------------------------------------------------------------------------


def test_static_instruction_no_context_variable_name():
    """Static instruction must NOT mention a specific variable like 'user_ctx'."""
    assert "user_ctx" not in RLM_STATIC_INSTRUCTION


def test_static_instruction_has_preloaded_context_note():
    """Static instruction should contain a generic note about pre-loaded context."""
    assert "pre-loaded into your environment" in RLM_STATIC_INSTRUCTION


def test_static_instruction_has_strategy_patterns():
    """Static instruction should document three named strategy patterns."""
    assert "Pattern 1" in RLM_STATIC_INSTRUCTION
    assert "Pattern 2" in RLM_STATIC_INSTRUCTION
    assert "Pattern 3" in RLM_STATIC_INSTRUCTION


def test_static_instruction_has_llm_query_docs():
    """Static instruction should document llm_query and llm_query_batched."""
    assert "llm_query(prompt)" in RLM_STATIC_INSTRUCTION
    assert "llm_query_batched(prompts)" in RLM_STATIC_INSTRUCTION


def test_static_instruction_has_repo_helpers():
    """Static instruction should reference probe_repo, pack_repo, shard_repo."""
    assert "probe_repo" in RLM_STATIC_INSTRUCTION
    assert "pack_repo" in RLM_STATIC_INSTRUCTION
    assert "shard_repo" in RLM_STATIC_INSTRUCTION


def test_static_instruction_has_completion_section():
    """Static instruction should document set_model_response."""
    assert "set_model_response" in RLM_STATIC_INSTRUCTION


# ---------------------------------------------------------------------------
# Dynamic instruction tests
# ---------------------------------------------------------------------------


def test_dynamic_instruction_has_user_ctx_manifest():
    """Dynamic instruction should include the user_ctx_manifest placeholder."""
    assert "{user_ctx_manifest?}" in RLM_DYNAMIC_INSTRUCTION


def test_dynamic_instruction_optional_placeholders():
    """All placeholders in the dynamic instruction must use the ? suffix."""
    # Find all {name} placeholders and ensure each has ? before }
    placeholders = re.findall(r"\{(\w+\??)\}", RLM_DYNAMIC_INSTRUCTION)
    assert len(placeholders) > 0, "No placeholders found"
    for ph in placeholders:
        assert ph.endswith("?"), f"Placeholder {{{ph}}} missing ? suffix"


# ---------------------------------------------------------------------------
# Child static instruction tests
# ---------------------------------------------------------------------------


def test_child_static_instruction_no_context_variable_name():
    """Child static instruction must NOT mention a specific variable like 'user_ctx'."""
    assert "user_ctx" not in RLM_CHILD_STATIC_INSTRUCTION


def test_child_static_instruction_has_preloaded_note():
    """Child static instruction should contain the generic pre-loaded context note."""
    assert "pre-loaded into your environment" in RLM_CHILD_STATIC_INSTRUCTION
