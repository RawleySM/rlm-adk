# SHOW_VARS

List all variables currently available in the REPL environment.

## Signature

```python
SHOW_VARS() -> str
```

## Parameters

None.

## Returns

`str` — A formatted string showing variable names and their types, e.g.:
```
Available variables: {'data': 'str', 'chunks': 'list', 'result': 'ProbeResult'}
```

If no variables have been created, returns:
```
No variables created yet. Use ```repl``` blocks to create variables.
```

## How It Works

`SHOW_VARS` iterates over the REPL's `locals` dict and collects all entries whose key does not start with `_`. For each, it records the variable name and `type(value).__name__`.

## REPL Usage

```repl
# Check what variables are available before calling FINAL_VAR
SHOW_VARS()
```

```repl
# After some work
data = open("/path/to/file.txt").read()
chunks = [data[i:i+10000] for i in range(0, len(data), 10000)]
print(SHOW_VARS())
# Output: Available variables: {'data': 'str', 'chunks': 'list'}
```

## Notes

- Private variables (names starting with `_`) are excluded from the listing.
- Useful for debugging when `FINAL_VAR` reports a variable not found.
- Only shows variables in `locals` (user-created), not `globals` (built-in functions like `llm_query`).

## Source

- Defined in: `rlm_adk/repl/local_repl.py` (`LocalREPL._show_vars`)
- Injected into REPL globals at: `LocalREPL.__init__`
