# ADK v1.27.0 Opportunity: `types.SchemaUnion` as `output_schema`

<!-- created: 2026-03-17 -->

## 1. What Changed in ADK v1.27.0

ADK v1.27.0 adds: **"Support for all `types.SchemaUnion` as output_schema in LLM Agent"**.

Previously, `LlmAgent.output_schema` only accepted `type[BaseModel]`. In v1.27.0, the field type widens to `types.SchemaUnion`, which is defined in `google.genai.types` (line 4255) as:

```python
SchemaUnion = Union[
    dict[Any, Any],       # Raw JSON Schema dict
    type,                 # Any Python type (includes BaseModel subclasses)
    Schema,               # google.genai.types.Schema object
    GenericAlias,          # e.g. list[str], dict[str, int]
    VersionedUnionType,   # Python 3.10+ X | Y union syntax
]
```

### What This Enables

1. **Raw JSON Schema dicts** as `output_schema` -- no Pydantic model definition required
2. **`google.genai.types.Schema` objects** for fine-grained control over JSON Schema features
3. **Python generic aliases** (`list[str]`, `dict[str, int]`) as output schemas
4. **Union types** (`str | int`) as output schemas

The most impactful for RLM-ADK is (1): REPL code can pass a plain `dict` as `output_schema` to `llm_query()` without needing to define and import a Pydantic `BaseModel` subclass at runtime.

---

## 2. Current Codebase Constraint Map

Every location that currently constrains `output_schema` to `type[BaseModel]` or `type`:

### 2.1 `rlm_adk/agent.py`

| Location | Current Type | Line |
|----------|-------------|------|
| `create_reasoning_agent(output_schema=)` | `type \| None` | 203 |
| `create_child_orchestrator(output_schema=)` | `type \| None` | 346 |
| Docstring: "Optional Pydantic BaseModel subclass" | (text) | 237, 362 |
| Passes `output_schema=output_schema` to `LlmAgent(...)` | pass-through | 278 |
| Passes `output_schema=output_schema` to `RLMOrchestratorAgent(...)` | pass-through | 388 |

### 2.2 `rlm_adk/dispatch.py`

| Location | Current Type | Line |
|----------|-------------|------|
| `_run_child(output_schema=)` | `type[BaseModel] \| None` | 386 |
| `llm_query_async(output_schema=)` | `type[BaseModel] \| None` | 658 |
| `llm_query_batched_async(output_schema=)` | `type[BaseModel] \| None` | 698 |
| `getattr(output_schema, "__name__", None)` in obs summary | assumes `type` | 631 |

### 2.3 `rlm_adk/orchestrator.py`

| Location | Current Type | Line |
|----------|-------------|------|
| `RLMOrchestratorAgent.output_schema` | `Any` (comment: `type[BaseModel] \| None`) | 223 |
| `SetModelResponseTool(schema)` | requires `type[BaseModel]` | 308 |
| `_infer_completion_error(output_schema=)` | `Any` | 112 |
| `_collect_reasoning_completion(output_schema=)` | `Any` | 144 |
| `getattr(output_schema, "__name__", ...)` | assumes `type` | 126 |

### 2.4 `rlm_adk/types.py`

| Location | Current Type | Line |
|----------|-------------|------|
| `LLMResult.parsed` | `dict \| None` | 122 |

### 2.5 `rlm_adk/callbacks/worker_retry.py`

| Location | Impact | Line |
|----------|--------|------|
| `WorkerRetryPlugin.extract_error_from_result()` | Inspects `tool_args` dict from `set_model_response` | 89-109 |
| `after_tool_cb` captures `tool_response` as dict | Stores on `agent._structured_result` | 163 |
| BUG-13 patch parses JSON from `get_structured_model_response()` | Operates on string/dict | 261-281 |

### 2.6 Installed ADK (current, pre-v1.27.0)

| Location | Current Type | Notes |
|----------|-------------|-------|
| `LlmAgent.output_schema` | `Optional[type[BaseModel]]` | `.venv/.../llm_agent.py:319` |
| `SetModelResponseTool.__init__(output_schema=)` | `type[BaseModel]` | `.venv/.../set_model_response_tool.py:41` |
| `SetModelResponseTool.run_async()` | calls `self.output_schema.model_validate(args)` | line 109 |
| `LlmAgent.__maybe_save_output_to_state()` | calls `self.output_schema.model_validate_json(result)` | line 836 |
| `_OutputSchemaRequestProcessor.run_async()` | passes `agent.output_schema` to `SetModelResponseTool()` | `_output_schema_processor.py:53` |

---

## 3. Proposed Code Changes

### 3.1 Define a Type Alias

Create a codebase-wide type alias that tracks the ADK's `SchemaUnion`:

**File:** `rlm_adk/types.py`

```python
from google.genai.types import SchemaUnion

# Re-export for internal use. Matches ADK v1.27+ LlmAgent.output_schema type.
OutputSchema = SchemaUnion | None
```

### 3.2 Widen `rlm_adk/agent.py` Signatures

```python
# Line 203: create_reasoning_agent
- output_schema: type | None = None,
+ output_schema: SchemaUnion | None = None,

# Line 346: create_child_orchestrator
- output_schema: type | None = None,
+ output_schema: SchemaUnion | None = None,
```

Update docstrings from "Optional Pydantic BaseModel subclass" to "Optional output schema (Pydantic BaseModel subclass, raw JSON Schema dict, or google.genai.types.Schema)."

### 3.3 Widen `rlm_adk/dispatch.py` Signatures

```python
# Line 386: _run_child
- output_schema: type[BaseModel] | None,
+ output_schema: SchemaUnion | None,

# Line 658: llm_query_async
- output_schema: type[BaseModel] | None = None,
+ output_schema: SchemaUnion | None = None,

# Line 698: llm_query_batched_async
- output_schema: type[BaseModel] | None = None,
+ output_schema: SchemaUnion | None = None,
```

Remove the `from pydantic import BaseModel` import (line 28) if no other usages remain.

### 3.4 Fix `__name__` Lookups for Non-Type Schemas

Two places read `getattr(output_schema, "__name__", ...)` assuming `output_schema` is a `type`. When it is a `dict` or `Schema`, this returns `None` or the class name `"Schema"` -- neither is useful.

**Add a helper to `rlm_adk/types.py`:**

```python
def schema_display_name(schema: SchemaUnion | None) -> str | None:
    """Return a human-readable name for any SchemaUnion variant."""
    if schema is None:
        return None
    if isinstance(schema, type):
        return schema.__name__
    if isinstance(schema, dict):
        # Try to use the dict's "title" field (JSON Schema convention)
        title = schema.get("title")
        if title:
            return str(title)
        return "<dict_schema>"
    # google.genai.types.Schema or GenericAlias
    return type(schema).__name__
```

**Update callsites:**

- `rlm_adk/orchestrator.py` line 126:
  ```python
  - schema_name = getattr(output_schema, "__name__", "structured output schema")
  + schema_name = schema_display_name(output_schema) or "structured output schema"
  ```

- `rlm_adk/dispatch.py` line 631:
  ```python
  - "schema_name": getattr(output_schema, "__name__", None),
  + "schema_name": schema_display_name(output_schema),
  ```

### 3.5 `SetModelResponseTool` Compatibility (CRITICAL)

This is the hardest part. The current `SetModelResponseTool.__init__` (ADK source, line 41-81) does:

```python
def __init__(self, output_schema: type[BaseModel]):
    schema_fields = output_schema.model_fields       # Pydantic-only
    # ... builds inspect.Parameter from field_info.annotation
```

And `run_async` does:

```python
validated_response = self.output_schema.model_validate(args)  # Pydantic-only
return validated_response.model_dump()
```

**Both methods are hard-coded to Pydantic `BaseModel`.**

#### What ADK v1.27.0 Must Change

ADK v1.27.0 *must* update `SetModelResponseTool` to handle `SchemaUnion`, otherwise the `LlmAgent.output_schema` widening is incomplete. The likely approach:
- Convert `SchemaUnion` to `google.genai.types.Schema` via `google.genai._transformers.t_schema()`
- Build function declaration from the Schema object instead of Pydantic introspection
- Validate responses against JSON Schema (not Pydantic `model_validate`)

#### RLM-ADK Strategy: Two-Phase Approach

**Phase 1 (Pre-ADK-upgrade, safe now):** Widen RLM-ADK type annotations only. Continue passing `type[BaseModel]` to `SetModelResponseTool`. When `output_schema` is a `dict` or `Schema`, convert it to a runtime-generated Pydantic model before passing to `SetModelResponseTool`:

```python
# rlm_adk/orchestrator.py, around line 307
from rlm_adk.types import to_pydantic_model  # new helper

schema = self.output_schema or ReasoningOutput
if not isinstance(schema, type) or not issubclass(schema, BaseModel):
    schema = to_pydantic_model(schema)  # Convert dict/Schema -> BaseModel
set_model_response_tool = SetModelResponseTool(schema)
```

The `to_pydantic_model` helper would dynamically construct a Pydantic model from a JSON Schema dict:

```python
# rlm_adk/types.py
def to_pydantic_model(schema: SchemaUnion) -> type[BaseModel]:
    """Convert a SchemaUnion to a Pydantic BaseModel subclass.

    Supports dict (JSON Schema), google.genai.types.Schema, and type.
    Falls back to a generic model with a single 'response' field.
    """
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    if isinstance(schema, dict):
        # Build from JSON Schema dict
        from pydantic import create_model, Field
        fields = {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        for name, prop in properties.items():
            field_type = _json_type_to_python(prop.get("type", "string"))
            description = prop.get("description", "")
            if name in required:
                fields[name] = (field_type, Field(description=description))
            else:
                fields[name] = (field_type | None, Field(default=None, description=description))
        return create_model("DynamicSchema", **fields)
    # google.genai.types.Schema -> extract properties from Schema object
    if hasattr(schema, "properties"):
        # ... similar conversion from Schema.properties
        pass
    # Fallback
    return ReasoningOutput
```

**Phase 2 (After ADK v1.27.0 upgrade):** Remove the `to_pydantic_model` shim. Pass `SchemaUnion` directly to `SetModelResponseTool`, which ADK v1.27.0 will handle natively.

### 3.6 `WorkerRetryPlugin` Impact

`WorkerRetryPlugin.extract_error_from_result()` (line 89-109) only inspects `tool_args` as a `dict[str, Any]` and checks for empty string values. It does **not** inspect or depend on the schema type. **No changes needed.**

The `after_tool_cb` captures `tool_response` (a dict from `SetModelResponseTool.run_async()`) on `agent._structured_result`. Since `SetModelResponseTool.run_async()` always returns a `dict` regardless of input schema type, **no changes needed.**

### 3.7 BUG-13 Patch Impact

The BUG-13 patch in `worker_retry.py` (lines 238-288) operates on the JSON string returned by `get_structured_model_response()`. It parses the string as JSON and checks for the `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel. This is schema-type-agnostic. **No changes needed.**

### 3.8 `LLMResult.parsed` Impact

`LLMResult.parsed` is `dict | None` (line 122). When `output_schema` is a JSON Schema dict rather than a Pydantic model, the validated result will still be a `dict`. **No changes needed** -- the `dict | None` type is already correct for all `SchemaUnion` variants, since structured output always resolves to a dict.

### 3.9 `__maybe_save_output_to_state` Impact

The current ADK code (`.venv/.../llm_agent.py:836`):
```python
result = self.output_schema.model_validate_json(result).model_dump(exclude_none=True)
```

This is inside ADK itself, not RLM-ADK code. However, RLM-ADK deliberately does **not** set `output_schema` on the `LlmAgent` (see orchestrator.py comment at line 301-306). Instead, it wires `SetModelResponseTool` as a tool. This means `__maybe_save_output_to_state` never hits the `output_schema` branch for RLM-ADK agents. **No RLM-ADK change needed**, but confirms the RLM pattern is robust against this ADK internal behavior.

### 3.10 REPL Ergonomics: Dict-Based Schemas in `llm_query()`

The main user-facing win. After these changes, REPL code can do:

```python
# Before: requires defining a Pydantic model (awkward in REPL)
from pydantic import BaseModel
class ExtractedFacts(BaseModel):
    facts: list[str]
    confidence: float
result = llm_query("Extract facts from...", output_schema=ExtractedFacts)

# After: raw JSON Schema dict (natural in REPL)
schema = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["facts", "confidence"],
}
result = llm_query("Extract facts from...", output_schema=schema)
result.parsed  # {"facts": ["..."], "confidence": 0.95}
```

---

## 4. Risk Analysis

### 4.1 BUG-13 Patch Stability (Risk: LOW)

The BUG-13 patch operates on the `get_structured_model_response()` output string. It checks for `REFLECT_AND_RETRY_RESPONSE_TYPE` in parsed JSON. This is orthogonal to the schema type used. The patch will continue to work regardless of whether `output_schema` is `type[BaseModel]`, `dict`, or `Schema`.

**Mitigation:** Existing FMEA tests (80 tests in `test_fmea_e2e.py`) cover BUG-13 runtime invocation via `_bug13_stats` delta assertions. These tests will catch any regression.

### 4.2 Structured Output Retry (Risk: LOW)

`WorkerRetryPlugin` and `make_worker_tool_callbacks()` inspect `tool_response` as a `dict` and check for empty string values. They do not depend on the schema type. The `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel is a string constant unrelated to schema structure.

**Mitigation:** Existing contract tests cover retry flows.

### 4.3 `SetModelResponseTool` Shim (Risk: MEDIUM)

The Phase 1 `to_pydantic_model()` shim must correctly convert JSON Schema dicts to Pydantic models. Edge cases include:
- Nested objects (JSON Schema `$ref` or inline objects)
- Arrays with complex item types
- Enum constraints
- Union types (`anyOf`, `oneOf`)

**Mitigation:**
- Start with flat object schemas only (covers 90% of REPL use cases)
- Add a warning log for unsupported JSON Schema features
- Phase 2 (ADK v1.27.0 native support) eliminates the shim entirely

### 4.4 Backward Compatibility (Risk: LOW)

All changes are additive. `type[BaseModel]` is a member of `SchemaUnion`, so existing code passing Pydantic models will continue to work. The `to_pydantic_model()` shim short-circuits for `BaseModel` subclasses (identity transform).

### 4.5 Observability Regression (Risk: LOW)

The `schema_display_name()` helper replaces two `getattr(output_schema, "__name__", ...)` calls. For `type[BaseModel]` inputs, it returns the same value as before. For `dict` inputs, it returns `"<dict_schema>"` or the JSON Schema `title` field -- more informative than `None`.

---

## 5. Opportunity Rating

| Dimension | Rating | Rationale |
|-----------|--------|-----------|
| **Effort** | **S** (Small) | Type annotation changes + 1 helper function + 1 shim function. No architectural changes. ~100 lines of new/changed code. |
| **Impact** | **Medium** | Unblocks a significantly better REPL ergonomic for structured output. REPL code no longer needs to define Pydantic models for `llm_query(output_schema=...)`. This is a frequent friction point when the parent model writes code that dispatches structured queries. |
| **Risk** | **Low** | All changes are additive. BUG-13 patch, retry plugin, and observability are unaffected. The Phase 1 shim is the only novel code, and it has a clear deprecation path (Phase 2 removes it after ADK upgrade). |

### Recommendation

**Proceed with Phase 1 now.** The type annotation widening and `to_pydantic_model()` shim can be implemented and tested independently of the ADK v1.27.0 upgrade. When ADK v1.27.0 is adopted, Phase 2 removes the shim and passes `SchemaUnion` natively through the stack.

### Implementation Order

1. Add `schema_display_name()` and `to_pydantic_model()` helpers to `rlm_adk/types.py`
2. Widen type annotations in `agent.py` and `dispatch.py`
3. Update `orchestrator.py` line 307-308 to use `to_pydantic_model()` shim
4. Update `__name__` lookup callsites in `orchestrator.py` and `dispatch.py`
5. Add tests: dict schema through `llm_query_async`, round-trip through `SetModelResponseTool`
6. Verify FMEA suite passes unchanged (BUG-13, retry, observability)
