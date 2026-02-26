"""Tests for the repomix REPL skill helpers and skill definition."""

import os

import pytest

from rlm_adk.skills.repomix_helpers import (
    ProbeResult,
    ShardResult,
    pack_repo,
    probe_repo,
    shard_repo,
)
from rlm_adk.skills.repomix_skill import REPOMIX_SKILL, build_skill_instruction_block


# ---------------------------------------------------------------------------
# probe_repo
# ---------------------------------------------------------------------------


class TestProbeRepo:
    def test_local_dir(self):
        """probe_repo on a small local directory returns valid stats."""
        result = probe_repo("rlm_adk/repl/", calculate_tokens=False)
        assert isinstance(result, ProbeResult)
        assert result.total_files > 0
        assert result.total_chars > 0
        assert isinstance(result.file_tree, dict)
        assert isinstance(result.file_char_counts, dict)

    def test_str_representation(self):
        result = probe_repo("rlm_adk/repl/", calculate_tokens=False)
        s = str(result)
        assert "ProbeResult" in s
        assert "files=" in s
        assert "chars=" in s


# ---------------------------------------------------------------------------
# pack_repo
# ---------------------------------------------------------------------------


class TestPackRepo:
    def test_returns_xml_string(self):
        """pack_repo returns a non-empty XML string."""
        xml = pack_repo("rlm_adk/repl/", calculate_tokens=False)
        assert isinstance(xml, str)
        assert len(xml) > 100
        # Should contain XML-style tags from repomix
        assert "<file" in xml or "<repository" in xml.lower() or "<?xml" in xml.lower()


# ---------------------------------------------------------------------------
# shard_repo
# ---------------------------------------------------------------------------


class TestShardRepo:
    def test_small_shard_size_forces_multiple_chunks(self):
        """shard_repo with a small max_bytes_per_shard produces multiple chunks."""
        # Use rlm_adk/callbacks/ + rlm_adk/plugins/ as a stable target.
        # Use the full rlm_adk/ package with a shard size large enough
        # to fit the biggest single directory group but small enough to
        # force multiple shards overall.
        result = shard_repo(
            "rlm_adk/",
            max_bytes_per_shard=500 * 1024,  # 500KB — default
            calculate_tokens=False,
        )
        assert isinstance(result, ShardResult)
        assert result.total_files > 0
        assert len(result.chunks) >= 2, f"Expected >=2 chunks, got {len(result.chunks)}"
        # Each chunk should be a non-empty string
        for chunk in result.chunks:
            assert isinstance(chunk, str)
            assert len(chunk) > 0

    def test_str_representation(self):
        result = shard_repo("rlm_adk/repl/", calculate_tokens=False)
        s = str(result)
        assert "ShardResult" in s
        assert "shards=" in s
        assert "files=" in s


# ---------------------------------------------------------------------------
# Skill definition
# ---------------------------------------------------------------------------


class TestRepomixSkill:
    def test_skill_object(self):
        """REPOMIX_SKILL has correct frontmatter and instructions."""
        assert REPOMIX_SKILL.frontmatter.name == "repomix-repl-helpers"
        assert "probe_repo" in REPOMIX_SKILL.instructions
        assert "pack_repo" in REPOMIX_SKILL.instructions
        assert "shard_repo" in REPOMIX_SKILL.instructions

    def test_build_skill_instruction_block(self):
        """build_skill_instruction_block returns XML discovery + instructions."""
        block = build_skill_instruction_block()
        assert isinstance(block, str)
        assert "repomix-repl-helpers" in block
        assert "<available_skills>" in block
        assert "probe_repo" in block
        assert "pack_repo" in block
        assert "shard_repo" in block


# ---------------------------------------------------------------------------
# REPL globals injection
# ---------------------------------------------------------------------------


class TestREPLInjection:
    def test_inject_and_execute(self):
        """Inject helpers into REPL globals and execute probe_repo."""
        from rlm_adk.repl.local_repl import LocalREPL

        # Use absolute path since REPL may have a different cwd
        repl_dir = os.path.join(os.getcwd(), "rlm_adk", "repl")

        repl = LocalREPL(depth=1)
        try:
            repl.globals["probe_repo"] = probe_repo
            repl.globals["pack_repo"] = pack_repo
            repl.globals["shard_repo"] = shard_repo

            result = repl.execute_code(
                f'info = probe_repo("{repl_dir}", calculate_tokens=False)\n'
                'print(f"files={info.total_files}")'
            )
            assert result.stderr == "", f"Unexpected stderr: {result.stderr}"
            assert "files=" in result.stdout
            # The variable should exist in REPL locals now
            assert "info" in result.locals
        finally:
            repl.cleanup()
