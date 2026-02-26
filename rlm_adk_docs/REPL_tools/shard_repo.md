# shard_repo

Pack a repository and split it into directory-aware chunks for parallel analysis.

## Signature

```python
shard_repo(
    source: str,
    max_bytes_per_shard: int = 512000,
    calculate_tokens: bool = True,
) -> ShardResult
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | required | Local directory path or remote git URL (https, git@, ssh://). |
| `max_bytes_per_shard` | `int` | `512000` (~500KB) | Maximum bytes per output chunk. Chunks are split at directory boundaries. |
| `calculate_tokens` | `bool` | `True` | Whether to count tokens during processing. |

## Returns

`ShardResult` dataclass with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `chunks` | `list[str]` | List of XML chunk strings, each containing files from one or more top-level directories. |
| `total_files` | `int` | Total number of files across all chunks. |
| `total_chars` | `int` | Total character count across all chunks. |
| `total_tokens` | `int` | Total token count (0 if `calculate_tokens=False`). |

`ShardResult.__str__()` returns a compact summary:
```
ShardResult(shards=4, files=120, chars=1,234,567, tokens=245,678)
```

## How It Works

1. For remote URLs, clones the repository to a temp directory using `repomix.shared.git_utils.clone_repository`.
2. Runs the repomix file pipeline: `search_files` -> `collect_files` -> `process_files`.
3. Calls `generate_split_output_parts()` to split processed files into parts at directory boundaries. Files within the same top-level directory are kept together.
4. Returns each part's XML content as a chunk string.
5. Cleans up the temp clone directory (if remote).

This avoids the `RepoProcessor.process()` temp-dir cleanup race condition — `shard_repo` manages the clone lifecycle itself.

## REPL Usage

```repl
# Shard a large repo and analyze chunks concurrently
shards = shard_repo("https://github.com/org/large-repo")
print(shards)  # ShardResult(shards=4, files=120, ...)

query = "Identify architecture patterns and dependencies in this section."
prompts = [f"{query}\n\n{chunk}" for chunk in shards.chunks]
analyses = llm_query_batched(prompts)

# Aggregate partial results
combined = "\n---\n".join(f"Part {i+1}:\n{a}" for i, a in enumerate(analyses))
final = llm_query(f"Synthesize these analyses:\n\n{combined}")
print(final)
```

```repl
# Custom shard size for smaller context windows
shards = shard_repo("/path/to/repo", max_bytes_per_shard=250 * 1024)
print(f"Split into {len(shards.chunks)} chunks")
```

## When to Use

- Best for **large repos** (>= ~125K tokens) that don't fit in a single sub-LLM context window.
- Pair with `llm_query_batched` for concurrent chunk analysis.
- Use `probe_repo` first to check if sharding is needed.

## Recommended Pattern

```repl
info = probe_repo("https://github.com/org/repo")
if info.total_tokens < 125_000:
    xml = pack_repo("https://github.com/org/repo")
    answer = llm_query(f"Analyze:\n\n{xml}")
else:
    shards = shard_repo("https://github.com/org/repo")
    prompts = [f"Analyze:\n\n{c}" for c in shards.chunks]
    parts = llm_query_batched(prompts)
    combined = "\n---\n".join(f"Part {i+1}:\n{a}" for i, a in enumerate(parts))
    answer = llm_query(f"Synthesize:\n\n{combined}")
print(answer)
```

## Notes

- No imports needed — `shard_repo` is pre-loaded in the REPL globals.
- Raises `ValueError` if a single directory group exceeds `max_bytes_per_shard` (increase the shard size or filter files).
- Remote URLs are detected by prefix: `http://`, `https://`, `git@`, `ssh://`.
- Chunks are XML-formatted with `<file>`, `<path>`, `<content>` tags.

## Source

- Defined in: `rlm_adk/skills/repomix_helpers.py`
- Injected into REPL globals by: `rlm_adk/orchestrator.py`
