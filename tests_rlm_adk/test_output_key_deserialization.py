"""Phase 3 Part D: output_key deserialization pattern tests.

Tests that ReasoningOutput round-trips through JSON serialization correctly,
validating the pattern used when ADK stores structured output via output_key.

RED: These tests will fail until ReasoningOutput is added to rlm_adk/types.py.
"""

import json

from rlm_adk.types import ReasoningOutput


class TestOutputKeyDeserialization:
    def test_output_key_json_string_roundtrip(self):
        """ReasoningOutput -> model_dump -> json.dumps -> json.loads -> dict."""
        ro = ReasoningOutput(final_answer="42", reasoning_summary="math")
        serialized = json.dumps(ro.model_dump())
        raw = serialized
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        assert parsed["final_answer"] == "42"
        assert parsed["reasoning_summary"] == "math"

    def test_output_key_already_dict_passthrough(self):
        """When raw is already a dict, passthrough works."""
        raw = {"final_answer": "42", "reasoning_summary": "math"}
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        assert parsed["final_answer"] == "42"

    def test_model_validate_from_dict(self):
        """Pydantic model_validate can reconstruct from a dict."""
        raw = {"final_answer": "42", "reasoning_summary": "math"}
        ro = ReasoningOutput.model_validate(raw)
        assert ro.final_answer == "42"
        assert ro.reasoning_summary == "math"

    def test_model_validate_json(self):
        """Pydantic model_validate_json can reconstruct from a JSON string."""
        json_str = '{"final_answer": "hello", "reasoning_summary": "greeting"}'
        ro = ReasoningOutput.model_validate_json(json_str)
        assert ro.final_answer == "hello"
        assert ro.reasoning_summary == "greeting"

    def test_default_reasoning_summary_in_serialized(self):
        """When reasoning_summary is omitted, it serializes as empty string."""
        ro = ReasoningOutput(final_answer="42")
        d = ro.model_dump()
        assert d["reasoning_summary"] == ""
