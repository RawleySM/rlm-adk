"""E2E replay JSON validation tests.

These tests validate the structure and content of the ADK --replay JSON files
used for non-interactive end-to-end testing. They do NOT execute the agent;
they verify the replay files are well-formed and reference valid state keys.

To actually run the agent with a replay file:
    adk run --replay tests_rlm_adk/replay/test_repo_analysis.json rlm_adk
    adk run --replay tests_rlm_adk/replay/test_basic_context.json rlm_adk
"""

import json
from pathlib import Path

import pytest

from rlm_adk import state as S

REPLAY_DIR = Path(__file__).parent / "replay"

# All replay JSON files to validate
REPLAY_FILES = list(REPLAY_DIR.glob("*.json"))


def _load_replay(path: Path) -> dict:
    """Load and parse a replay JSON file."""
    with open(path) as f:
        return json.load(f)


# ---------- Schema validation ----------


@pytest.mark.parametrize("replay_path", REPLAY_FILES, ids=lambda p: p.name)
class TestReplaySchema:
    """Validate that each replay file conforms to the ADK replay schema."""

    def test_file_is_valid_json(self, replay_path: Path):
        data = _load_replay(replay_path)
        assert isinstance(data, dict)

    def test_has_required_keys(self, replay_path: Path):
        data = _load_replay(replay_path)
        assert "state" in data, "Replay file must have a 'state' key"
        assert "queries" in data, "Replay file must have a 'queries' key"

    def test_state_is_dict(self, replay_path: Path):
        data = _load_replay(replay_path)
        assert isinstance(data["state"], dict), "'state' must be a dict"

    def test_queries_is_nonempty_list_of_strings(self, replay_path: Path):
        data = _load_replay(replay_path)
        queries = data["queries"]
        assert isinstance(queries, list), "'queries' must be a list"
        assert len(queries) > 0, "'queries' must not be empty"
        for i, q in enumerate(queries):
            assert isinstance(q, str), f"queries[{i}] must be a string"
            assert len(q.strip()) > 0, f"queries[{i}] must not be blank"

    def test_no_extra_top_level_keys(self, replay_path: Path):
        data = _load_replay(replay_path)
        allowed = {"state", "queries"}
        extra = set(data.keys()) - allowed
        assert not extra, f"Unexpected top-level keys: {extra}"


# ---------- State key validation ----------

# Collect all string constants from state.py that represent known state keys
_STATE_KEY_CONSTANTS = {
    v for k, v in vars(S).items()
    if isinstance(v, str) and not k.startswith("_") and not callable(v)
}

# State keys that use the app: or temp: prefix must match a known constant
_PREFIXED_KEY_PREFIXES = ("app:", "temp:", "obs:", "cache:", "user:")


@pytest.mark.parametrize("replay_path", REPLAY_FILES, ids=lambda p: p.name)
class TestStateKeys:
    """Verify that prefixed state keys in replay files match state.py constants."""

    def test_prefixed_keys_are_known(self, replay_path: Path):
        data = _load_replay(replay_path)
        for key in data["state"]:
            if any(key.startswith(p) for p in _PREFIXED_KEY_PREFIXES):
                assert key in _STATE_KEY_CONSTANTS, (
                    f"State key '{key}' uses a scoped prefix but is not "
                    f"defined in rlm_adk.state. Known keys: "
                    f"{sorted(_STATE_KEY_CONSTANTS)}"
                )

    def test_max_iterations_is_positive_int(self, replay_path: Path):
        data = _load_replay(replay_path)
        val = data["state"].get(S.APP_MAX_ITERATIONS)
        if val is not None:
            assert isinstance(val, int) and val > 0, (
                f"{S.APP_MAX_ITERATIONS} must be a positive integer, got {val}"
            )

    def test_max_depth_is_positive_int(self, replay_path: Path):
        data = _load_replay(replay_path)
        val = data["state"].get(S.APP_MAX_DEPTH)
        if val is not None:
            assert isinstance(val, int) and val > 0, (
                f"{S.APP_MAX_DEPTH} must be a positive integer, got {val}"
            )


# ---------- File-specific content tests ----------


class TestRepoAnalysisReplay:
    """Validate content specifics of test_repo_analysis.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_replay(REPLAY_DIR / "test_repo_analysis.json")

    def test_has_repo_url(self):
        assert "repo_url" in self.data["state"]
        assert self.data["state"]["repo_url"].startswith("https://")

    def test_max_iterations_set(self):
        assert self.data["state"][S.APP_MAX_ITERATIONS] == 20

    def test_max_depth_set(self):
        assert self.data["state"][S.APP_MAX_DEPTH] == 1

    def test_query_references_repo(self):
        query = self.data["queries"][0].lower()
        assert "repo" in query or "repository" in query


class TestBasicContextReplay:
    """Validate content specifics of test_basic_context.json."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = _load_replay(REPLAY_DIR / "test_basic_context.json")

    def test_max_iterations_set(self):
        assert self.data["state"][S.APP_MAX_ITERATIONS] == 3

    def test_max_depth_set(self):
        assert self.data["state"][S.APP_MAX_DEPTH] == 1

    def test_has_at_least_one_query(self):
        assert len(self.data["queries"]) >= 1
