"""In-process replay launch helpers for the live dashboard."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.genai import types

from rlm_adk.agent import _root_agent_model, create_rlm_runner
from rlm_adk.skills import normalize_enabled_skill_names
from rlm_adk.state import ENABLED_SKILLS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REPLAY_FIXTURE = "tests_rlm_adk/replay/recursive_ping.json"


@dataclass(frozen=True)
class ReplayLaunchHandle:
    """Prepared replay run with a persisted session and executable queries."""

    runner: Any
    user_id: str
    session_id: str
    queries: tuple[str, ...]

    async def run(self) -> None:
        for query in self.queries:
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=query)],
            )
            async for _event in self.runner.run_async(
                user_id=self.user_id,
                session_id=self.session_id,
                new_message=content,
            ):
                pass


def list_replay_fixtures(
    *,
    replay_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> list[str]:
    """Return stable replay fixture paths for the dashboard launch picker."""
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _REPO_ROOT
    resolved_replay_dir = (
        Path(replay_dir).expanduser().resolve()
        if replay_dir
        else resolved_repo_root / "tests_rlm_adk" / "replay"
    )
    if not resolved_replay_dir.exists():
        return []

    fixtures: list[str] = []
    for fixture_path in sorted(resolved_replay_dir.rglob("*.json")):
        if not fixture_path.is_file():
            continue
        try:
            fixtures.append(fixture_path.relative_to(resolved_repo_root).as_posix())
        except ValueError:
            fixtures.append(fixture_path.as_posix())
    return fixtures


def list_provider_fake_fixtures(
    *,
    fixture_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> list[str]:
    """Return sorted provider-fake fixture stems for the dashboard picker."""
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _REPO_ROOT
    resolved_fixture_dir = (
        Path(fixture_dir).expanduser().resolve()
        if fixture_dir
        else resolved_repo_root / "tests_rlm_adk" / "fixtures" / "provider_fake"
    )
    if not resolved_fixture_dir.exists():
        return []

    stems: list[str] = []
    for fixture_path in sorted(resolved_fixture_dir.glob("*.json")):
        if not fixture_path.is_file():
            continue
        stems.append(fixture_path.stem)
    return stems


def default_replay_fixture(fixtures: Iterable[str]) -> str:
    fixture_list = list(fixtures)
    if _DEFAULT_REPLAY_FIXTURE in fixture_list:
        return _DEFAULT_REPLAY_FIXTURE
    return fixture_list[0] if fixture_list else ""


def _resolve_replay_path(replay_path: str | Path) -> Path:
    raw_path = Path(replay_path).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()

    repo_relative = (_REPO_ROOT / raw_path).resolve()
    if repo_relative.exists():
        return repo_relative
    return raw_path.resolve()


def _load_replay_file(replay_path: str | Path) -> dict[str, Any]:
    path = _resolve_replay_path(replay_path)
    if not path.exists():
        raise FileNotFoundError(f"Replay file not found: {path}")

    with path.open() as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict):
        raise ValueError("Replay payload must be a JSON object")

    state = payload.get("state")
    queries = payload.get("queries")
    if not isinstance(state, dict):
        raise ValueError("Replay payload must contain a dict 'state'")
    if (
        not isinstance(queries, list)
        or not queries
        or not all(isinstance(query, str) and query.strip() for query in queries)
    ):
        raise ValueError("Replay payload must contain a non-empty string list 'queries'")

    return {
        "path": path,
        "state": state,
        "queries": tuple(query.strip() for query in queries),
    }


async def prepare_replay_launch(
    replay_path: str | Path,
    *,
    enabled_skills: Iterable[str] | None = None,
    user_id: str = "dashboard-user",
) -> ReplayLaunchHandle:
    """Create a persisted session for a replay run and return an executable handle."""
    payload = _load_replay_file(replay_path)
    resolved_skills = normalize_enabled_skill_names(enabled_skills)
    initial_state = dict(payload["state"])
    initial_state[ENABLED_SKILLS] = list(resolved_skills)

    runner = create_rlm_runner(
        model=_root_agent_model(),
        enabled_skills=resolved_skills,
    )
    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id=user_id,
        state=initial_state,
    )

    return ReplayLaunchHandle(
        runner=runner,
        user_id=user_id,
        session_id=session.id,
        queries=payload["queries"],
    )
