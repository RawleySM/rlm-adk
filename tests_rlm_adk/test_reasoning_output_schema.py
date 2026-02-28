"""Phase 3 Part A: ReasoningOutput Pydantic schema tests.

Tests that ReasoningOutput enforces required fields and provides defaults.
RED: These tests will fail until ReasoningOutput is added to rlm_adk/types.py.
"""

import pytest
from pydantic import ValidationError

from rlm_adk.types import ReasoningOutput


class TestReasoningOutputSchema:
    def test_schema_requires_final_answer(self):
        """final_answer is required -- omitting it raises ValidationError."""
        with pytest.raises(ValidationError):
            ReasoningOutput(reasoning_summary="oops")

    def test_schema_defaults_reasoning_summary(self):
        """reasoning_summary defaults to empty string when omitted."""
        ro = ReasoningOutput(final_answer="42")
        assert ro.reasoning_summary == ""

    def test_schema_accepts_full_input(self):
        """Both fields provided -- no error, values preserved."""
        ro = ReasoningOutput(final_answer="42", reasoning_summary="did math")
        assert ro.final_answer == "42"
        assert ro.reasoning_summary == "did math"

    def test_is_pydantic_base_model(self):
        """ReasoningOutput must be a Pydantic BaseModel for ADK output_schema."""
        from pydantic import BaseModel

        assert issubclass(ReasoningOutput, BaseModel)

    def test_model_dump_produces_dict(self):
        """model_dump() produces a plain dict for JSON serialization."""
        ro = ReasoningOutput(final_answer="hello", reasoning_summary="greeting")
        d = ro.model_dump()
        assert isinstance(d, dict)
        assert d["final_answer"] == "hello"
        assert d["reasoning_summary"] == "greeting"
