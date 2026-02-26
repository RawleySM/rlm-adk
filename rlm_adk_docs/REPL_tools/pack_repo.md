# pack_repo

Pack an entire repository into a single XML string.

## Signature

```python
pack_repo(source: str, calculate_tokens: bool = True) -> str
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | required | Local directory path or remote git URL (https, git@, ssh://). |
| `calculate_tokens` | `bool` | `True` | Whether to count tokens during processing. |

## Returns

`str` — The full repository packed as an XML string with `<file>`, `<path>`, and `<content>` tags. The XML format gives sub-LLMs explicit file boundaries for reliable parsing.

## How It Works

Uses `repomix-python`'s `RepoProcessor` with XML output style. For remote URLs, repomix auto-clones to a temp directory and cleans up afterward. The entire packed output is returned as an in-memory string (no disk I/O needed by the caller).

## REPL Usage

```repl
# Pack a small remote repo and analyze in one shot
xml = pack_repo("https://github.com/org/small-repo")
analysis = llm_query(f"Analyze this repository's architecture:\n\n{xml}")
print(analysis)
```

```repl
# Pack a local directory
xml = pack_repo("/path/to/local/repo")
print(f"Packed size: {len(xml)} chars")
```

## When to Use

- Best for **small repos** (< ~125K tokens / < ~500K chars).
- For larger repos, use `shard_repo` to split into chunks that fit in sub-LLM context windows.
- Use `probe_repo` first to check token count if unsure about repo size.

## Recommended Pattern

```repl
info = probe_repo("https://github.com/org/repo")
if info.total_tokens < 125_000:
    xml = pack_repo("https://github.com/org/repo")
    answer = llm_query(f"Question about this repo:\n\n{xml}")
    print(answer)
else:
    # Too large for single-shot — use shard_repo instead
    print(f"Repo too large ({info.total_tokens} tokens), use shard_repo")
```

## Notes

- No imports needed — `pack_repo` is pre-loaded in the REPL globals.
- Remote URLs are detected by prefix: `http://`, `https://`, `git@`, `ssh://`.
- Output is always XML style (`<file>`, `<path>`, `<content>` tags).
- The packed string includes a file tree header and all file contents.

## Source

- Defined in: `rlm_adk/skills/repomix_helpers.py`
- Injected into REPL globals by: `rlm_adk/orchestrator.py`
