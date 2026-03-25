# GAP-C: Skill functions can't use `llm_query_batched_fn`

## What was fixed

The injection wrapper in `rlm_adk/skills/loader.py` only handled `llm_query_fn`.
Skill functions that declared `llm_query_batched_fn` as a parameter received
`None` at call time -- the loader never detected or injected it.

---

## Before (the problem)

**Detection:** Only `_has_llm_query_fn_param` existed.  No equivalent for
`llm_query_batched_fn`.

**Wrapper:** `_wrap_with_llm_query_injection` only checked for `llm_query_fn`
and only injected `kwargs["llm_query_fn"]`.

**Collect guard:** `collect_skill_repl_globals` only wrapped callables that
matched `_has_llm_query_fn_param(obj)`.  A function with *only*
`llm_query_batched_fn` passed through unwrapped.

**`run_test_skill` signature:**

```python
def run_test_skill(
    child_prompt: str = ...,
    *,
    emit_debug: bool = True,
    rlm_state: dict[str, Any] | None = None,
    llm_query_fn=None,
    # llm_query_batched_fn -- MISSING
) -> TestSkillResult:
```

---

## After (the fix)

### New detection helper

```python
def _has_llm_query_batched_fn_param(fn: Callable) -> bool:
    """Return True if *fn* has a parameter named ``llm_query_batched_fn``."""
    sig = inspect.signature(fn)
    return "llm_query_batched_fn" in sig.parameters
```

### Extended wrapper

`_wrap_with_llm_query_injection` now probes for both params independently
and injects each from `repl_globals` when needed:

```python
needs_query = _has_llm_query_fn_param(fn)
needs_batched = _has_llm_query_batched_fn_param(fn)

def wrapper(*args, **kwargs):
    if needs_query and "llm_query_fn" not in kwargs:
        kwargs["llm_query_fn"] = repl_globals.get("llm_query")  # + RuntimeError guard
    if needs_batched and "llm_query_batched_fn" not in kwargs:
        kwargs["llm_query_batched_fn"] = repl_globals.get("llm_query_batched")  # + RuntimeError guard
    return fn(*args, **kwargs)
```

### Updated collect guard

```python
# Before
if callable(obj) and _has_llm_query_fn_param(obj):

# After
if callable(obj) and (
    _has_llm_query_fn_param(obj) or _has_llm_query_batched_fn_param(obj)
):
```

### `run_test_skill` signature (new)

```python
def run_test_skill(
    child_prompt: str = ...,
    *,
    emit_debug: bool = True,
    rlm_state: dict[str, Any] | None = None,
    llm_query_fn=None,
    llm_query_batched_fn=None,      # <-- NEW
) -> TestSkillResult:
```

---

## Changed files

| File | Change |
|---|---|
| `rlm_adk/skills/loader.py` | Added `_has_llm_query_batched_fn_param`; extended `_wrap_with_llm_query_injection` and `collect_skill_repl_globals` guard |
| `rlm_adk/skills/test_skill/skill.py` | Added `llm_query_batched_fn=None` param to `run_test_skill` |
| `tests_rlm_adk/test_skill_loader.py` | Added `TestLlmQueryBatchedFnInjection` (7 tests across 4 cycles) |

---

## Runnable verification

```bash
# All 7 GAP-C tests
.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestLlmQueryBatchedFnInjection -v -o "addopts="

# Full loader suite (existing + GAP-C, should stay green)
.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py -v -o "addopts="
```

---

## Verification Checklist

- [ ] `_has_llm_query_batched_fn_param` returns `True` for fns with the param, `False` otherwise
- [ ] Wrapper injects `llm_query_batched_fn` from `repl_globals["llm_query_batched"]` (lazy binding)
- [ ] Wrapper injects *only* `llm_query_batched_fn` when `llm_query_fn` is not declared
- [ ] Wrapper raises `RuntimeError` when `llm_query_batched` is missing from `repl_globals`
- [ ] Wrapper does NOT override an explicitly passed `llm_query_batched_fn`
- [ ] `collect_skill_repl_globals` wraps functions that declare only `llm_query_batched_fn`
- [ ] `run_test_skill` signature includes `llm_query_batched_fn=None`
- [ ] All pre-existing loader tests remain green
