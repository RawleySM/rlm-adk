"""In-process replay launch helpers for the live dashboard."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.genai import types

from rlm_adk.agent import _root_agent_model, create_rlm_runner

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


@dataclass(frozen=True)
class ProviderFakeLaunchHandle:
    """Prepared provider-fake run backed by a FakeGeminiServer."""

    runner: Any
    user_id: str
    session_id: str
    prompt: str
    _server: Any  # FakeGeminiServer
    _saved_env: dict[str, str | None] = field(repr=False)

    async def run(self) -> None:
        try:
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=self.prompt)],
            )
            async for _event in self.runner.run_async(
                user_id=self.user_id,
                session_id=self.session_id,
                new_message=content,
            ):
                pass
        finally:
            await self._server.stop()
            _restore_provider_fake_env(self._saved_env)


# ── Provider-fake env helpers (mirror contract_runner logic) ──

_PF_ENV_KEYS = (
    "GOOGLE_GEMINI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "RLM_ADK_MODEL",
    "RLM_LLM_RETRY_DELAY",
    "RLM_LLM_MAX_RETRIES",
    "RLM_MAX_ITERATIONS",
    "RLM_REPL_TRACE",
    # LiteLLM mode keys — must be disabled so requests hit the Gemini fake
    # server directly (mirrors contract_runner._ENV_KEYS).
    "RLM_ADK_LITELLM",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
)


def _save_provider_fake_env() -> dict[str, str | None]:
    return {k: os.environ.get(k) for k in _PF_ENV_KEYS}


def _restore_provider_fake_env(saved: dict[str, str | None]) -> None:
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def _set_provider_fake_env(base_url: str, config: dict[str, Any]) -> None:
    # Disable LiteLLM so requests hit the Gemini fake server directly
    os.environ.pop("RLM_ADK_LITELLM", None)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("OPENAI_API_BASE", None)
    os.environ["GOOGLE_GEMINI_BASE_URL"] = base_url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ["RLM_ADK_MODEL"] = config.get("model", "gemini-fake")
    os.environ["RLM_LLM_RETRY_DELAY"] = str(config.get("retry_delay", 0.01))
    os.environ["RLM_LLM_MAX_RETRIES"] = str(config.get("max_retries", 3))
    os.environ["RLM_MAX_ITERATIONS"] = str(config.get("max_iterations", 5))
    os.environ["RLM_REPL_TRACE"] = "0"


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


def resolve_fixture_file_path(
    kind: str,
    value: str,
    *,
    repo_root: str | Path | None = None,
) -> Path | None:
    """Resolve the full filesystem path for a fixture selection.

    *kind* is ``"replay"`` or ``"provider_fake"``.
    Returns ``None`` when the path cannot be resolved or does not exist.
    """
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _REPO_ROOT
    if kind == "replay":
        path = _resolve_replay_path(value)
        return path if path.exists() else None
    if kind == "provider_fake":
        path = resolved_repo_root / "tests_rlm_adk" / "fixtures" / "provider_fake" / f"{value}.json"
        return path if path.exists() else None
    return None


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
    resolved_skills = tuple(enabled_skills) if enabled_skills else ()
    initial_state = dict(payload["state"])

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


async def prepare_provider_fake_launch(
    fixture_stem: str,
    *,
    enabled_skills: Iterable[str] | None = None,
    user_id: str = "dashboard-user",
    prompt: str = "test prompt",
) -> ProviderFakeLaunchHandle:
    """Start a FakeGeminiServer and create a runner for a provider-fake fixture."""
    from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
    from tests_rlm_adk.provider_fake.server import FakeGeminiServer

    fixture_path = resolve_fixture_file_path("provider_fake", fixture_stem)
    if fixture_path is None:
        raise FileNotFoundError(f"Provider-fake fixture not found: {fixture_stem}")

    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)

    saved_env = _save_provider_fake_env()
    base_url = await server.start()
    _set_provider_fake_env(base_url, router.config)

    resolved_skills = (
        tuple(enabled_skills) if enabled_skills
        else tuple(router.config.get("enabled_skills") or ())
    )

    runner = create_rlm_runner(
        model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
        thinking_budget=router.config.get("thinking_budget", 0),
        enabled_skills=resolved_skills,
    )

    initial_state = dict(router.config.get("initial_state") or {})

    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id=user_id,
        state=initial_state,
    )

    return ProviderFakeLaunchHandle(
        runner=runner,
        user_id=user_id,
        session_id=session.id,
        prompt=prompt,
        _server=server,
        _saved_env=saved_env,
    )
