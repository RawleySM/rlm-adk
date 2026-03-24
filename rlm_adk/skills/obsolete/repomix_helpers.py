"""Pre-built REPL helper functions for repomix-python.

These functions are injected into the REPL globals so the reasoning agent
can call them directly with zero imports.  They encapsulate the 6+ deep-
subpackage imports, the ``split_output`` dead-code workaround, and the
``repo_url=`` keyword pitfall.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repomix import RepomixConfig, RepoProcessor
from repomix.core.file.file_collect import collect_files
from repomix.core.file.file_process import process_files
from repomix.core.file.file_search import search_files
from repomix.core.output.output_generate import generate_output
from repomix.core.output.output_split import generate_split_output_parts
from repomix.shared.fs_utils import cleanup_temp_directory, create_temp_directory
from repomix.shared.git_utils import clone_repository


@dataclass
class ProbeResult:
    """Lightweight stats returned by :func:`probe_repo`."""

    total_files: int
    total_chars: int
    total_tokens: int
    file_tree: dict
    file_char_counts: dict[str, int]
    file_token_counts: dict[str, int]

    def __str__(self) -> str:
        return (
            f"ProbeResult(files={self.total_files}, "
            f"chars={self.total_chars:,}, "
            f"tokens={self.total_tokens:,})\n"
            f"file_tree={self.file_tree}"
        )


@dataclass
class ShardResult:
    """Result of :func:`shard_repo` containing split chunks."""

    chunks: list[str]
    total_files: int
    total_chars: int
    total_tokens: int

    def __str__(self) -> str:
        return (
            f"ShardResult(shards={len(self.chunks)}, "
            f"files={self.total_files}, "
            f"chars={self.total_chars:,}, "
            f"tokens={self.total_tokens:,})"
        )


def _make_config(calculate_tokens: bool) -> RepomixConfig:
    """Build a standard RepomixConfig for XML output."""
    config = RepomixConfig()
    config.output.style = "xml"
    config.output.calculate_tokens = calculate_tokens
    return config


def _is_remote(source: str) -> bool:
    """Return True if *source* looks like a remote URL."""
    return source.startswith(("http://", "https://", "git@", "ssh://"))


def probe_repo(source: str, calculate_tokens: bool = True) -> ProbeResult:
    """Quick stats: file count, token count, file tree.  No full content returned.

    Args:
        source: Local directory path or remote git URL.
        calculate_tokens: Whether to count tokens (slower but useful for
            deciding between single-shot and sharded analysis).

    Returns:
        A :class:`ProbeResult` with file counts, token counts, and tree.
    """
    config = _make_config(calculate_tokens)
    if _is_remote(source):
        processor = RepoProcessor(repo_url=source, config=config)
    else:
        processor = RepoProcessor(source, config=config)
    result = processor.process()
    return ProbeResult(
        total_files=result.total_files,
        total_chars=result.total_chars,
        total_tokens=result.total_tokens,
        file_tree=result.file_tree,
        file_char_counts=result.file_char_counts,
        file_token_counts=result.file_token_counts,
    )


def pack_repo(source: str, calculate_tokens: bool = True) -> str:
    """Pack entire repo into an XML string.  For small repos (<125K tokens).

    Args:
        source: Local directory path or remote git URL.
        calculate_tokens: Whether to count tokens.

    Returns:
        The full packed XML content as a string.
    """
    config = _make_config(calculate_tokens)
    if _is_remote(source):
        processor = RepoProcessor(repo_url=source, config=config)
    else:
        processor = RepoProcessor(source, config=config)
    result = processor.process()
    return result.output_content


def shard_repo(
    source: str,
    max_bytes_per_shard: int = 500 * 1024,
    calculate_tokens: bool = True,
) -> ShardResult:
    """Pack + split into chunks at directory boundaries.

    For large repos, use the returned ``chunks`` list with
    ``llm_query_batched()`` for concurrent analysis.

    Args:
        source: Local directory path or remote git URL.
        max_bytes_per_shard: Maximum bytes per output chunk (default 500KB).
        calculate_tokens: Whether to count tokens.

    Returns:
        A :class:`ShardResult` with the list of XML chunk strings.
    """
    config = _make_config(calculate_tokens)

    # Determine local path — clone if remote
    tmp_dir: Path | None = None
    if _is_remote(source):
        tmp_dir = create_temp_directory()
        clone_repository(source, tmp_dir)
        local_path = str(tmp_dir)
    else:
        local_path = source

    try:
        # Run the file pipeline
        search_result = search_files(local_path, config)
        raw_files = collect_files(search_result.file_paths, local_path)
        processed_files = process_files(raw_files, config)

        file_char_counts = {pf.path: len(pf.content) for pf in processed_files}
        file_token_counts = {pf.path: 0 for pf in processed_files}
        all_file_paths = [pf.path for pf in processed_files]

        parts = generate_split_output_parts(
            processed_files=processed_files,
            all_file_paths=all_file_paths,
            max_bytes_per_part=max_bytes_per_shard,
            base_config=config,
            generate_output_fn=generate_output,
            file_char_counts=file_char_counts,
            file_token_counts=file_token_counts,
        )

        chunks = [part.content for part in parts]
        total_chars = sum(len(c) for c in chunks)
        total_files = len(processed_files)
        total_tokens = sum(file_token_counts.values())

        return ShardResult(
            chunks=chunks,
            total_files=total_files,
            total_chars=total_chars,
            total_tokens=total_tokens,
        )
    finally:
        if tmp_dir is not None:
            cleanup_temp_directory(tmp_dir)
