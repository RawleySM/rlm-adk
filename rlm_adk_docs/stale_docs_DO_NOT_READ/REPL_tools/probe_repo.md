# probe_repo

Get quick stats about a repository without returning the full packed content.

## Signature

```python
probe_repo(source: str, calculate_tokens: bool = True) -> ProbeResult
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | required | Local directory path or remote git URL (https, git@, ssh://). |
| `calculate_tokens` | `bool` | `True` | Whether to count tokens. Set to `False` for faster results when you only need file/char counts. |

## Returns

`ProbeResult` dataclass with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `total_files` | `int` | Number of files in the repository. |
| `total_chars` | `int` | Total character count across all files. |
| `total_tokens` | `int` | Total token count (0 if `calculate_tokens=False`). |
| `file_tree` | `dict` | Nested dict representing the file tree structure. |
| `file_char_counts` | `dict[str, int]` | Per-file character counts keyed by relative path. |
| `file_token_counts` | `dict[str, int]` | Per-file token counts keyed by relative path. |

`ProbeResult.__str__()` returns a compact summary:
```
ProbeResult(files=42, chars=156,789, tokens=31,234)
file_tree={'src': {'main.py': '', 'utils.py': ''}, 'tests': {'test_main.py': ''}}
```

## How It Works

Uses `repomix-python`'s `RepoProcessor` to process the repository. For remote URLs, repomix auto-clones to a temp directory and cleans up afterward. The full packed content is generated internally but not returned — only the metadata is extracted into the `ProbeResult`.

## REPL Usage

```repl
# Probe a remote repo to decide on analysis strategy
info = probe_repo("https://github.com/org/repo")
print(info)
print(f"Tokens: {info.total_tokens}")

# Use token count to choose strategy
if info.total_tokens < 125_000:
    print("Small repo — use pack_repo for single-shot analysis")
else:
    print("Large repo — use shard_repo for chunked analysis")
```

```repl
# Probe a local directory
info = probe_repo("/path/to/local/repo", calculate_tokens=False)
print(f"Files: {info.total_files}, Chars: {info.total_chars}")
```

## Notes

- No imports needed — `probe_repo` is pre-loaded in the REPL globals.
- Remote URLs are detected by prefix: `http://`, `https://`, `git@`, `ssh://`.
- Token counting uses the `o200k_base` encoding (same as GPT-4/Gemini tokenizers).
- For the full packed XML content, use `pack_repo` instead.

## Source

- Defined in: `rlm_adk/skills/repomix_helpers.py`
- Injected into REPL globals by: `rlm_adk/orchestrator.py`
