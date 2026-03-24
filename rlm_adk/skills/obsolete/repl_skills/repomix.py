"""Expandable REPL skill: repomix helpers.

Registers source-expandable exports at import time so
``from rlm_repl_skills.repomix import probe_repo`` (etc.) expands into
inline source before the AST rewriter runs.

Source strings extracted from repomix_helpers.py.
"""

from __future__ import annotations

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

_MODULE = "rlm_repl_skills.repomix"

# ---------------------------------------------------------------------------
# Preamble: repomix package imports (executed once at expansion time)
# ---------------------------------------------------------------------------

_REPOMIX_IMPORTS_SRC = """\
from repomix import RepomixConfig, RepoProcessor
from repomix.core.file.file_collect import collect_files
from repomix.core.file.file_process import process_files
from repomix.core.file.file_search import search_files
from repomix.core.output.output_generate import generate_output
from repomix.core.output.output_split import generate_split_output_parts
from repomix.shared.fs_utils import cleanup_temp_directory, create_temp_directory
from repomix.shared.git_utils import clone_repository\
"""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

_PROBE_RESULT_SRC = """\
class ProbeResult:
    \"\"\"Lightweight stats returned by probe_repo.\"\"\"
    def __init__(self, total_files, total_chars, total_tokens,
                 file_tree, file_char_counts, file_token_counts):
        self.total_files = total_files
        self.total_chars = total_chars
        self.total_tokens = total_tokens
        self.file_tree = file_tree
        self.file_char_counts = file_char_counts
        self.file_token_counts = file_token_counts

    def __str__(self):
        return (
            "ProbeResult(files=" + str(self.total_files)
            + ", chars=" + format(self.total_chars, ",")
            + ", tokens=" + format(self.total_tokens, ",") + ")\\n"
            + "file_tree=" + str(self.file_tree)
        )

    def __repr__(self):
        return str(self)\
"""

_SHARD_RESULT_SRC = """\
class ShardResult:
    \"\"\"Result of shard_repo containing split chunks.\"\"\"
    def __init__(self, chunks, total_files, total_chars, total_tokens):
        self.chunks = chunks
        self.total_files = total_files
        self.total_chars = total_chars
        self.total_tokens = total_tokens

    def __str__(self):
        return (
            "ShardResult(shards=" + str(len(self.chunks))
            + ", files=" + str(self.total_files)
            + ", chars=" + format(self.total_chars, ",")
            + ", tokens=" + format(self.total_tokens, ",") + ")"
        )

    def __repr__(self):
        return str(self)\
"""

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_MAKE_CONFIG_SRC = """\
def rmx_make_config(calculate_tokens):
    \"\"\"Build a standard RepomixConfig for XML output.\"\"\"
    config = RepomixConfig()
    config.output.style = "xml"
    config.output.calculate_tokens = calculate_tokens
    return config\
"""

_IS_REMOTE_SRC = """\
def rmx_is_remote(source):
    \"\"\"Return True if source looks like a remote URL.\"\"\"
    return source.startswith(("http://", "https://", "git@", "ssh://"))\
"""

# ---------------------------------------------------------------------------
# Main functions
# ---------------------------------------------------------------------------

_PROBE_REPO_SRC = '''\
def probe_repo(source, calculate_tokens=True):
    """Quick stats: file count, token count, file tree. No full content returned.

    Args:
        source: Local directory path or remote git URL.
        calculate_tokens: Whether to count tokens (slower but useful for
            deciding between single-shot and sharded analysis).

    Returns:
        A ProbeResult with file counts, token counts, and tree.
    """
    config = rmx_make_config(calculate_tokens)
    if rmx_is_remote(source):
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
    )\
'''

_PACK_REPO_SRC = '''\
def pack_repo(source, calculate_tokens=True):
    """Pack entire repo into an XML string. For small repos (<125K tokens).

    Args:
        source: Local directory path or remote git URL.
        calculate_tokens: Whether to count tokens.

    Returns:
        The full packed XML content as a string.
    """
    config = rmx_make_config(calculate_tokens)
    if rmx_is_remote(source):
        processor = RepoProcessor(repo_url=source, config=config)
    else:
        processor = RepoProcessor(source, config=config)
    result = processor.process()
    return result.output_content\
'''

_SHARD_REPO_SRC = '''\
def shard_repo(source, max_bytes_per_shard=500 * 1024, calculate_tokens=True):
    """Pack + split into chunks at directory boundaries.

    For large repos, use the returned chunks list with
    llm_query_batched() for concurrent analysis.

    Args:
        source: Local directory path or remote git URL.
        max_bytes_per_shard: Maximum bytes per output chunk (default 500KB).
        calculate_tokens: Whether to count tokens.

    Returns:
        A ShardResult with the list of XML chunk strings.
    """
    from pathlib import Path as _Path

    config = rmx_make_config(calculate_tokens)

    # Determine local path -- clone if remote
    tmp_dir = None
    if rmx_is_remote(source):
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
            cleanup_temp_directory(tmp_dir)\
'''

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="repomix_imports",
        source=_REPOMIX_IMPORTS_SRC,
        requires=[],
        kind="imports",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="ProbeResult",
        source=_PROBE_RESULT_SRC,
        requires=["repomix_imports"],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="ShardResult",
        source=_SHARD_RESULT_SRC,
        requires=["repomix_imports"],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="rmx_make_config",
        source=_MAKE_CONFIG_SRC,
        requires=["repomix_imports"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="rmx_is_remote",
        source=_IS_REMOTE_SRC,
        requires=[],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="probe_repo",
        source=_PROBE_REPO_SRC,
        requires=["repomix_imports", "ProbeResult", "rmx_make_config", "rmx_is_remote"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="pack_repo",
        source=_PACK_REPO_SRC,
        requires=["repomix_imports", "rmx_make_config", "rmx_is_remote"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module=_MODULE,
        name="shard_repo",
        source=_SHARD_REPO_SRC,
        requires=["repomix_imports", "ShardResult", "rmx_make_config", "rmx_is_remote"],
        kind="function",
    )
)
