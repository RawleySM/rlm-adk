"""DT-002: Safe serialization and type shape tests.

Non-JSON values in locals/state must be represented safely (string/repr
fallback) without crashing serialization.  Canonical type shapes for
ModelUsageSummary, UsageSummary, RLMChatCompletion, REPLResult, etc.
"""

from rlm_adk.types import (
    CodeBlock,
    ModelUsageSummary,
    REPLResult,
    RLMChatCompletion,
    RLMIteration,
    RLMMetadata,
    UsageSummary,
    _serialize_value,
)


class TestSerializeValue:
    """DT-002: _serialize_value must never raise on arbitrary inputs."""

    def test_primitives_pass_through(self):
        assert _serialize_value(None) is None
        assert _serialize_value(True) is True
        assert _serialize_value(42) == 42
        assert _serialize_value(3.14) == 3.14
        assert _serialize_value("hello") == "hello"

    def test_list_recursion(self):
        result = _serialize_value([1, "a", None])
        assert result == [1, "a", None]

    def test_nested_list(self):
        result = _serialize_value([[1, 2], [3, 4]])
        assert result == [[1, 2], [3, 4]]

    def test_dict_recursion(self):
        result = _serialize_value({"a": 1, "b": [2, 3]})
        assert result == {"a": 1, "b": [2, 3]}

    def test_module_serializes_to_string(self):
        import os

        result = _serialize_value(os)
        assert "<module 'os'>" == result

    def test_callable_serializes_to_string(self):
        result = _serialize_value(len)
        assert "len" in result

    def test_lambda_serializes(self):
        result = _serialize_value(lambda x: x)
        assert "<function" in result

    def test_custom_class_instance_repr(self):
        class Dummy:
            def __repr__(self):
                return "Dummy()"

        result = _serialize_value(Dummy())
        assert "Dummy()" in result

    def test_unrepr_object_fallback(self):
        class BadRepr:
            def __repr__(self):
                raise RuntimeError("no repr")

        result = _serialize_value(BadRepr())
        assert "<BadRepr>" == result

    def test_tuple_serialized_as_list(self):
        result = _serialize_value((1, 2, 3))
        assert result == [1, 2, 3]


class TestModelUsageSummary:
    """FR-013: Usage type shape."""

    def test_round_trip(self):
        mus = ModelUsageSummary(total_calls=5, total_input_tokens=100, total_output_tokens=50)
        d = mus.to_dict()
        assert d == {"total_calls": 5, "total_input_tokens": 100, "total_output_tokens": 50}
        restored = ModelUsageSummary.from_dict(d)
        assert restored.total_calls == 5
        assert restored.total_input_tokens == 100
        assert restored.total_output_tokens == 50

    def test_from_dict_missing_keys(self):
        restored = ModelUsageSummary.from_dict({})
        assert restored.total_calls is None
        assert restored.total_input_tokens is None


class TestUsageSummary:
    """FR-013: Aggregated usage type shape."""

    def test_round_trip(self):
        us = UsageSummary(
            model_usage_summaries={
                "model-a": ModelUsageSummary(
                    total_calls=2, total_input_tokens=10, total_output_tokens=20
                ),
            }
        )
        d = us.to_dict()
        assert "model-a" in d["model_usage_summaries"]
        restored = UsageSummary.from_dict(d)
        assert restored.model_usage_summaries["model-a"].total_calls == 2

    def test_empty_summary(self):
        us = UsageSummary(model_usage_summaries={})
        d = us.to_dict()
        assert d == {"model_usage_summaries": {}}


class TestRLMChatCompletion:
    """FR-001: Completion response shape."""

    def test_required_fields(self):
        usage = UsageSummary(model_usage_summaries={})
        c = RLMChatCompletion(
            root_model="test-model",
            prompt="hello",
            response="world",
            usage_summary=usage,
            execution_time=1.5,
        )
        assert c.root_model == "test-model"
        assert c.prompt == "hello"
        assert c.response == "world"
        assert c.execution_time == 1.5

    def test_to_dict(self):
        usage = UsageSummary(model_usage_summaries={})
        c = RLMChatCompletion(
            root_model="m",
            prompt="p",
            response="r",
            usage_summary=usage,
            execution_time=0.1,
        )
        d = c.to_dict()
        assert set(d.keys()) == {
            "root_model",
            "prompt",
            "response",
            "usage_summary",
            "execution_time",
        }

    def test_from_dict(self):
        d = {
            "root_model": "m",
            "prompt": "p",
            "response": "r",
            "usage_summary": {"model_usage_summaries": {}},
            "execution_time": 0.5,
        }
        c = RLMChatCompletion.from_dict(d)
        assert c.root_model == "m"
        assert c.execution_time == 0.5


class TestREPLResult:
    """FR-005: REPLResult type shape."""

    def test_basic_construction(self):
        r = REPLResult(stdout="out", stderr="err", locals={"x": 1})
        assert r.stdout == "out"
        assert r.stderr == "err"
        assert r.locals == {"x": 1}
        assert r.llm_calls == []

    def test_to_dict_safe_serialization(self):
        """DT-002: Non-JSON locals must not crash to_dict."""
        import os

        r = REPLResult(stdout="", stderr="", locals={"mod": os, "fn": len, "val": 42})
        d = r.to_dict()
        assert d["locals"]["val"] == 42
        assert "<module" in d["locals"]["mod"]

    def test_str_repr(self):
        r = REPLResult(stdout="", stderr="", locals={})
        s = str(r)
        assert "REPLResult" in s


class TestCodeBlock:
    def test_to_dict(self):
        result = REPLResult(stdout="hi", stderr="", locals={})
        cb = CodeBlock(code="print('hi')", result=result)
        d = cb.to_dict()
        assert d["code"] == "print('hi')"
        assert d["result"]["stdout"] == "hi"


class TestRLMIteration:
    def test_to_dict(self):
        result = REPLResult(stdout="", stderr="", locals={})
        cb = CodeBlock(code="x=1", result=result)
        it = RLMIteration(prompt="p", response="r", code_blocks=[cb])
        d = it.to_dict()
        assert d["prompt"] == "p"
        assert len(d["code_blocks"]) == 1
        assert d["final_answer"] is None


class TestRLMMetadata:
    def test_to_dict_serializes_kwargs(self):
        import os

        meta = RLMMetadata(
            root_model="m",
            max_depth=1,
            max_iterations=30,
            backend="gemini",
            backend_kwargs={"mod": os},
            environment_type="local",
            environment_kwargs={"fn": print},
        )
        d = meta.to_dict()
        assert "<module" in d["backend_kwargs"]["mod"]
