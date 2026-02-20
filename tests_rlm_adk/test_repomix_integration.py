"""Integration tests for repomix-python package.

Verifies repomix can be imported and used programmatically to pack
repositories with various configurations (XML style, split output, etc.).
"""

import glob
import os
import tempfile

import pytest
from repomix import RepomixConfig, RepoProcessor


# Use a small subdirectory of the project itself for testing
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_TARGET = os.path.join(REPO_ROOT, "rlm_adk", "repl")


class TestRepomixImport:
    """Basic import and configuration tests."""

    def test_import(self):
        from repomix import RepomixConfig, RepoProcessor
        assert RepoProcessor is not None
        assert RepomixConfig is not None

    def test_config_defaults(self):
        config = RepomixConfig()
        assert config.output.style == "markdown"
        assert config.output.split_output is None

    def test_config_xml_style(self):
        config = RepomixConfig()
        config.output.style = "xml"
        assert config.output.style == "xml"


class TestRepomixProcessing:
    """Tests that verify actual repo packing works."""

    def test_pack_small_directory_xml(self):
        """Pack the rlm_adk/repl/ subdirectory as XML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, "packed.xml")
            config = RepomixConfig()
            config.output.file_path = outfile
            config.output.style = "xml"
            config.include = ["*.py"]

            processor = RepoProcessor(TEST_TARGET, config=config)
            result = processor.process()

            assert result.total_files > 0
            assert os.path.exists(outfile)

            content = open(outfile).read()
            assert len(content) > 100
            # XML output should contain file tags
            assert "<file" in content.lower() or "<source" in content.lower() or "<?xml" in content.lower()

    def test_pack_with_token_count(self):
        """Pack with token counting enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, "packed.xml")
            config = RepomixConfig()
            config.output.file_path = outfile
            config.output.style = "xml"
            config.output.calculate_tokens = True
            config.include = ["*.py"]

            processor = RepoProcessor(TEST_TARGET, config=config)
            result = processor.process()

            assert result.total_files > 0
            assert result.total_tokens > 0

    def test_pack_with_split_output(self):
        """Pack the full rlm_adk/ directory with split output enabled."""
        target = os.path.join(REPO_ROOT, "rlm_adk")
        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, "packed.xml")
            config = RepomixConfig()
            config.output.file_path = outfile
            config.output.style = "xml"
            # Very small split size to force multiple parts
            config.output.split_output = 2 * 1024  # 2KB
            config.include = ["**/*.py"]

            processor = RepoProcessor(target, config=config)
            result = processor.process()

            assert result.total_files > 0
            # Check for split files
            parts = sorted(glob.glob(os.path.join(tmpdir, "packed*.xml")))
            assert len(parts) >= 1

    def test_pack_reads_into_memory(self):
        """Verify the full workflow: pack -> read into memory -> analyze."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, "packed.xml")
            config = RepomixConfig()
            config.output.file_path = outfile
            config.output.style = "xml"
            config.include = ["*.py"]

            processor = RepoProcessor(TEST_TARGET, config=config)
            result = processor.process()

            # Read into memory (simulating what the REPL code does)
            packed = open(outfile).read()
            assert isinstance(packed, str)
            assert len(packed) > 0

            # Should contain Python source code
            assert "def " in packed or "class " in packed

    def test_pack_json_style(self):
        """Pack as JSON for structured parsing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, "packed.json")
            config = RepomixConfig()
            config.output.file_path = outfile
            config.output.style = "json"
            config.include = ["*.py"]

            processor = RepoProcessor(TEST_TARGET, config=config)
            result = processor.process()

            assert result.total_files > 0
            import json
            content = json.loads(open(outfile).read())
            assert isinstance(content, dict)
