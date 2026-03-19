"""Tests for list_provider_fake_fixtures() in run_service."""

from __future__ import annotations

import json
from pathlib import Path


class TestListProviderFakeFixturesReal:
    """Test against the real fixtures directory."""

    def test_returns_sorted_list_of_stems(self):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        result = list_provider_fake_fixtures()
        assert isinstance(result, list)
        assert len(result) > 0
        assert result == sorted(result)

    def test_contains_known_fixtures(self):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        result = list_provider_fake_fixtures()
        assert "fake_recursive_ping" in result
        assert "index" in result

    def test_returns_stems_not_full_paths(self):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        result = list_provider_fake_fixtures()
        for stem in result:
            assert "/" not in stem
            assert "\\" not in stem
            assert not stem.endswith(".json")


class TestListProviderFakeFixturesTempDir:
    """Test with a controlled temp directory."""

    def test_sorted_stems_from_temp_dir(self, tmp_path: Path):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        for name in ["zebra.json", "alpha.json", "middle.json"]:
            (tmp_path / name).write_text(json.dumps({"test": True}))

        result = list_provider_fake_fixtures(fixture_dir=tmp_path)
        assert result == ["alpha", "middle", "zebra"]

    def test_empty_directory(self, tmp_path: Path):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        result = list_provider_fake_fixtures(fixture_dir=tmp_path)
        assert result == []

    def test_nonexistent_directory(self, tmp_path: Path):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        result = list_provider_fake_fixtures(fixture_dir=tmp_path / "no_such_dir")
        assert result == []

    def test_ignores_non_json_files(self, tmp_path: Path):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        (tmp_path / "valid.json").write_text("{}")
        (tmp_path / "readme.txt").write_text("not a fixture")
        (tmp_path / "data.yaml").write_text("key: val")

        result = list_provider_fake_fixtures(fixture_dir=tmp_path)
        assert result == ["valid"]

    def test_ignores_directories_with_json_name(self, tmp_path: Path):
        from rlm_adk.dashboard.run_service import list_provider_fake_fixtures

        (tmp_path / "real_file.json").write_text("{}")
        (tmp_path / "dir_that_looks_like_json.json").mkdir()

        result = list_provider_fake_fixtures(fixture_dir=tmp_path)
        assert result == ["real_file"]
