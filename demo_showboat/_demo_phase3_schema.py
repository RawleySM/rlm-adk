from pydantic import BaseModel, ValidationError
from rlm_adk.types import ReasoningOutput

# 1. It is a Pydantic BaseModel
assert issubclass(ReasoningOutput, BaseModel)
print("issubclass(ReasoningOutput, BaseModel):", True)

# 2. final_answer is required -- omitting it raises ValidationError
try:
    ReasoningOutput(reasoning_summary="oops")
    assert False, "Should have raised"
except ValidationError as e:
    print("Missing final_answer raises ValidationError:", True)

# 3. reasoning_summary defaults to empty string
ro = ReasoningOutput(final_answer="42")
assert ro.reasoning_summary == ""
print("Default reasoning_summary:", repr(ro.reasoning_summary))

# 4. Both fields provided
ro2 = ReasoningOutput(final_answer="42", reasoning_summary="did math")
assert ro2.final_answer == "42"
assert ro2.reasoning_summary == "did math"
print("Full input: final_answer=%r, reasoning_summary=%r" % (ro2.final_answer, ro2.reasoning_summary))

# 5. model_dump produces dict (for JSON serialization)
d = ro2.model_dump()
assert isinstance(d, dict)
assert d["final_answer"] == "42"
print("model_dump() keys:", sorted(d.keys()))

print()
print("PASS: ReasoningOutput validates required fields, defaults, and serializes")
