# FINAL

Provide the final answer directly as inline text (not a REPL tool — parsed from the response).

## Syntax

```
FINAL(your final answer here)
```

This is **not** a Python function call — it is a text pattern recognized by the orchestrator's response parser.

## How It Works

The orchestrator's `find_final_answer()` scans each reasoning agent response for `FINAL(...)` at the start of a line. When found, the text inside the parentheses is extracted as the final answer, the iteration loop terminates, and the answer is yielded as the output event.

`FINAL_VAR(name)` takes precedence over `FINAL(text)` if both appear in the same response.

## Usage

The reasoning agent writes this as plain text in its response (not inside a `repl` block):

```
Based on my analysis, the answer is:

FINAL(The repository uses a layered architecture with three main modules:
authentication, data processing, and API gateway. The modules communicate
through a shared event bus.)
```

## When to Use

- Use `FINAL(text)` when the answer is written directly in the response.
- Use `FINAL_VAR(variable_name)` when the answer is stored in a REPL variable.

## Notes

- Must appear at the start of a line (leading whitespace is allowed).
- Supports nested parentheses in the answer text.
- Do not use `FINAL` until the task is fully complete — it terminates the iteration loop immediately.
- If code blocks in the same iteration had errors, `FINAL_VAR` resolution is skipped (Bug-8 fix), but `FINAL(text)` is still honored.

## Source

- Parsed by: `rlm_adk/utils/parsing.py` (`find_final_answer`)
- Acted on by: `rlm_adk/orchestrator.py` (terminates iteration loop, yields final event)
