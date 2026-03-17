"""Managed auto-launch for the NiceGUI dashboard."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

logger = logging.getLogger(__name__)

DASHBOARD_ACTIVE_ENV = "RLM_ADK_DASHBOARD_ACTIVE"
DASHBOARD_FINGERPRINT_ENV = "RLM_ADK_DASHBOARD_FINGERPRINT"
DASHBOARD_INSTANCE_FILE_ENV = "RLM_ADK_DASHBOARD_INSTANCE_FILE"
DISABLE_AUTOLAUNCH_ENV = "RLM_ADK_DISABLE_DASHBOARD_AUTOLAUNCH"
PLAYWRIGHT_DASHBOARD_DEV_ENV = "RLM_DASHBOARD_DEV"
PLAYWRIGHT_DASHBOARD_DEV_ALIAS_ENV = "DASHBOARD_DEV"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8080/live"
DEFAULT_DASHBOARD_PORT = 8080


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def dashboard_instance_file_path(repo_root_path: str | Path | None = None) -> Path:
    root = Path(repo_root_path).expanduser().resolve() if repo_root_path else repo_root()
    return root / "rlm_adk" / ".adk" / "dashboard_instance.json"


def iter_dashboard_fingerprint_paths(
    repo_root_path: str | Path | None = None,
) -> list[Path]:
    root = Path(repo_root_path).expanduser().resolve() if repo_root_path else repo_root()
    dashboard_dir = root / "rlm_adk" / "dashboard"
    paths = sorted(dashboard_dir.rglob("*.py"))
    paths.append(root / "rlm_adk" / "plugins" / "dashboard_auto_launch.py")
    paths.append(root / "scripts" / "launch_dashboard_chrome.sh")
    paths.append(root / "scripts" / "launch_dashboard_playwright_chrome.py")
    return [path for path in paths if path.exists()]


def compute_dashboard_fingerprint(
    repo_root_path: str | Path | None = None,
    *,
    paths: Iterable[str | Path] | None = None,
) -> str:
    digest = hashlib.sha256()
    path_list = (
        [Path(path).expanduser().resolve() for path in paths]
        if paths is not None
        else iter_dashboard_fingerprint_paths(repo_root_path)
    )
    for path in sorted(path_list):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class DashboardInstanceRecord:
    pid: int
    port: int
    url: str
    fingerprint: str
    started_at: str
    log_path: str

    @classmethod
    def from_path(cls, path: Path) -> DashboardInstanceRecord | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        try:
            return cls(
                pid=int(payload["pid"]),
                port=int(payload["port"]),
                url=str(payload["url"]),
                fingerprint=str(payload["fingerprint"]),
                started_at=str(payload["started_at"]),
                log_path=str(payload["log_path"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def write_to(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")


@dataclass(frozen=True)
class DashboardLaunchPlan:
    action: str
    reason: str
    target_pid: int | None = None


def dashboard_command_matches(command: str | None) -> bool:
    if not command:
        return False
    normalized = " ".join(command.split())
    return "python -m rlm_adk.dashboard" in normalized or ".venv/bin/python -m rlm_adk.dashboard" in normalized


def process_command_for_pid(pid: int | None) -> str | None:
    if pid is None or pid <= 0:
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    command = result.stdout.strip()
    return command or None


def listening_pid_for_port(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return int(text.splitlines()[0])
    except ValueError:
        return None


def pid_exists(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def dashboard_url_responding(url: str, *, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


def dashboard_log_reports_ready(log_path: str | Path, base_url: str) -> bool:
    try:
        text = Path(log_path).read_text()
    except OSError:
        return False
    return f"NiceGUI ready to go on {base_url}" in text


def resolve_dashboard_launch_plan(
    *,
    current_fingerprint: str,
    dashboard_url: str,
    dashboard_port: int,
    instance_record: DashboardInstanceRecord | None,
    live_url_responding: bool,
    live_port_pid: int | None,
    live_port_command: str | None,
) -> DashboardLaunchPlan:
    live_port_is_dashboard = dashboard_command_matches(live_port_command)
    managed_pid = instance_record.pid if instance_record else None
    managed_port_matches = instance_record is not None and instance_record.port == dashboard_port
    managed_pid_live = managed_pid is not None and managed_pid == live_port_pid and live_port_is_dashboard

    if instance_record and managed_port_matches and managed_pid_live:
        if live_url_responding and instance_record.fingerprint == current_fingerprint:
            return DashboardLaunchPlan(
                action="reuse_managed",
                reason="managed instance matches current fingerprint",
                target_pid=managed_pid,
            )
        return DashboardLaunchPlan(
            action="restart_managed",
            reason="managed instance is stale or unhealthy",
            target_pid=managed_pid,
        )

    if live_url_responding and live_port_pid is not None:
        if live_port_is_dashboard:
            return DashboardLaunchPlan(
                action="replace_unmanaged_dashboard",
                reason="dashboard is live but not managed by the current lock file",
                target_pid=live_port_pid,
            )
        return DashboardLaunchPlan(
            action="skip_external_service",
            reason="another service is listening on the configured dashboard port",
            target_pid=None,
        )

    return DashboardLaunchPlan(
        action="start_new",
        reason="no reusable dashboard instance is available",
        target_pid=None,
    )


class DashboardAutoLaunchPlugin(BasePlugin):
    """Spawn the managed dashboard launcher once per process when a run starts."""

    _launch_lock = threading.Lock()
    _launch_attempted = False

    def __init__(
        self,
        *,
        name: str = "dashboard_auto_launch",
        script_path: str | Path | None = None,
    ) -> None:
        super().__init__(name=name)
        self._script_path = (
            Path(script_path).expanduser().resolve()
            if script_path
            else repo_root() / "scripts" / "launch_dashboard_chrome.sh"
        )

    async def before_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> types.Content | None:
        del invocation_context

        if self._should_skip():
            return None

        with type(self)._launch_lock:
            if type(self)._launch_attempted:
                return None
            type(self)._launch_attempted = True

        if not self._script_path.is_file():
            logger.warning("Dashboard launcher script missing: %s", self._script_path)
            return None

        try:
            subprocess.Popen(
                [str(self._script_path)],
                cwd=str(self._script_path.parent.parent),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception:
            logger.exception("Failed to start dashboard launcher script: %s", self._script_path)

        return None

    def _should_skip(self) -> bool:
        if os.getenv(DASHBOARD_ACTIVE_ENV, "").lower() in {"1", "true", "yes"}:
            return True
        if os.getenv(DISABLE_AUTOLAUNCH_ENV, "").lower() in {"1", "true", "yes"}:
            return True
        if os.getenv("PYTEST_CURRENT_TEST"):
            return True
        return False


__all__ = [
    "DASHBOARD_ACTIVE_ENV",
    "DASHBOARD_FINGERPRINT_ENV",
    "DASHBOARD_INSTANCE_FILE_ENV",
    "DISABLE_AUTOLAUNCH_ENV",
    "DEFAULT_DASHBOARD_PORT",
    "DEFAULT_DASHBOARD_URL",
    "DashboardAutoLaunchPlugin",
    "DashboardInstanceRecord",
    "DashboardLaunchPlan",
    "compute_dashboard_fingerprint",
    "dashboard_command_matches",
    "dashboard_instance_file_path",
    "dashboard_log_reports_ready",
    "dashboard_url_responding",
    "iter_dashboard_fingerprint_paths",
    "listening_pid_for_port",
    "pid_exists",
    "PLAYWRIGHT_DASHBOARD_DEV_ALIAS_ENV",
    "PLAYWRIGHT_DASHBOARD_DEV_ENV",
    "process_command_for_pid",
    "repo_root",
    "resolve_dashboard_launch_plan",
]
