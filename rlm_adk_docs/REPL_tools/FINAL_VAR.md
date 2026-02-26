# FINAL_VAR

Return the value of an existing REPL variable as the final answer.

## Signature

```python
FINAL_VAR(variable_name: str) -> str
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `variable_name` | `str` | required | Name of a variable previously created in a `repl` block. |

## Returns

`str` — The string representation of the variable's value.

If the variable does not exist, returns an error message listing available variables (or stating none exist). If the last REPL execution had an error, the error is included in the diagnostic message.

## How It Works

`FINAL_VAR` looks up `variable_name` in the REPL's `locals` dict. If found, it returns `str(value)`. This is used by the orchestrator's `find_final_answer()` parser — when the reasoning agent writes `FINAL_VAR(my_result)` outside a code block, the orchestrator resolves the variable and terminates the iteration loop.

## REPL Usage

The reasoning agent uses `FINAL_VAR` in a **two-step** pattern:

**Step 1** — Create the variable in a `repl` block:
```repl
my_answer = llm_query(f"Synthesize: {combined}")
print(my_answer)
```

**Step 2** — In the **next** response (outside code), call:
```
FINAL_VAR(my_answer)
```

## Common Mistakes

- **Wrong:** Calling `FINAL_VAR(x)` without first creating `x` in a `repl` block.
- **Wrong:** Calling `FINAL_VAR` inside a `repl` block (it should be called as plain text in the response).
- **Tip:** Use `SHOW_VARS()` in a `repl` block first to verify what variables exist.

## Notes

- `FINAL_VAR` is an alternative to `FINAL(text)` — use `FINAL_VAR` when the answer is already stored in a variable, and `FINAL` when providing the answer inline.
- If code blocks had errors in the current iteration, the orchestrator skips `FINAL_VAR` resolution to prevent returning error strings as the final answer (Bug-8 fix).

## Source

- Defined in: `rlm_adk/repl/local_repl.py` (`LocalREPL._final_var`)
- Injected into REPL globals at: `LocalREPL.__init__`
- Parsed by: `rlm_adk/utils/parsing.py` (`find_final_answer`)
