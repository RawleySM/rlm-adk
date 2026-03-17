#!/usr/bin/env python3
"""Launch the dashboard in a Chrome dev-mode browser via Playwright.

The script defaults to a *copied* Chrome user-data root under
``rlm_adk/.adk/chrome-dev-profile`` so it can reuse the user's authenticated
Chrome profile without mutating or locking the primary profile in place.

Environment variables:
- ``RLM_DASHBOARD_URL``: dashboard URL to open. Default ``http://127.0.0.1:8080/live``.
- ``RLM_PLAYWRIGHT_CHROME_SOURCE_ROOT``: source Chrome user-data root to copy from.
- ``RLM_PLAYWRIGHT_CHROME_PROFILE_DIR``: profile directory name inside the source root.
- ``RLM_PLAYWRIGHT_CHROME_DEV_ROOT``: destination dev-mode user-data root.
- ``RLM_PLAYWRIGHT_CHROME_REMOTE_DEBUGGING_PORT``: Chrome remote debugging port.
- ``RLM_PLAYWRIGHT_CHROME_HEADLESS``: set to ``1`` for headless mode.
- ``RLM_PLAYWRIGHT_CHROME_REFRESH_PROFILE``: set to ``1`` to re-copy auth/profile data.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8080/live"
DEFAULT_PROFILE_DIR = "Default"
DEFAULT_REMOTE_DEBUGGING_PORT = 9222
PROFILE_IGNORE_PATTERNS = (
    "Singleton*",
    "LOCK",
    "lockfile",
    "*.lock",
    "Crashpad",
    "Crash Reports",
    "Code Cache",
    "GPUCache",
    "GrShaderCache",
    "ShaderCache",
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
)


@dataclass(frozen=True)
class ChromeDevLaunchConfig:
    dashboard_url: str
    source_root: Path | None
    dev_root: Path
    profile_dir: str
    remote_debugging_port: int
    headless: bool
    refresh_profile: bool


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_chrome_user_data_root(platform_name: str | None = None) -> Path | None:
    platform_value = platform_name or sys.platform
    home = Path.home()
    if platform_value.startswith("linux"):
        return home / ".config" / "google-chrome"
    if platform_value == "darwin":
        return home / "Library" / "Application Support" / "Google" / "Chrome"
    if platform_value in {"win32", "cygwin"}:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "Google" / "Chrome" / "User Data"
    return None


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_launch_config() -> ChromeDevLaunchConfig:
    source_root_raw = os.getenv("RLM_PLAYWRIGHT_CHROME_SOURCE_ROOT")
    source_root = (
        Path(source_root_raw).expanduser().resolve()
        if source_root_raw
        else default_chrome_user_data_root()
    )
    if source_root is not None and not source_root.exists():
        source_root = None

    dev_root_raw = os.getenv("RLM_PLAYWRIGHT_CHROME_DEV_ROOT")
    dev_root = (
        Path(dev_root_raw).expanduser().resolve()
        if dev_root_raw
        else repo_root() / "rlm_adk" / ".adk" / "chrome-dev-profile"
    )

    return ChromeDevLaunchConfig(
        dashboard_url=os.getenv("RLM_DASHBOARD_URL", DEFAULT_DASHBOARD_URL),
        source_root=source_root,
        dev_root=dev_root,
        profile_dir=os.getenv("RLM_PLAYWRIGHT_CHROME_PROFILE_DIR", DEFAULT_PROFILE_DIR),
        remote_debugging_port=int(
            os.getenv(
                "RLM_PLAYWRIGHT_CHROME_REMOTE_DEBUGGING_PORT",
                str(DEFAULT_REMOTE_DEBUGGING_PORT),
            )
        ),
        headless=env_flag("RLM_PLAYWRIGHT_CHROME_HEADLESS"),
        refresh_profile=env_flag("RLM_PLAYWRIGHT_CHROME_REFRESH_PROFILE"),
    )


def ensure_dashboard_available(dashboard_url: str) -> None:
    try:
        with urllib.request.urlopen(dashboard_url, timeout=2.0) as response:
            if 200 <= response.status < 500:
                return
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        raise RuntimeError(
            f"Dashboard is not reachable at {dashboard_url}. Start the dashboard first."
        ) from exc
    raise RuntimeError(f"Dashboard returned an unexpected response at {dashboard_url}.")


def reset_dev_root(dev_root: Path) -> None:
    if dev_root.exists():
        shutil.rmtree(dev_root)


def copy_if_exists(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*PROFILE_IGNORE_PATTERNS),
        )
        return
    shutil.copy2(source, destination)


def seed_dev_profile(config: ChromeDevLaunchConfig) -> Path:
    dev_root = config.dev_root
    source_root = config.source_root
    profile_dir = config.profile_dir

    if source_root is None:
        dev_root.mkdir(parents=True, exist_ok=True)
        return dev_root

    should_refresh = config.refresh_profile or not (dev_root / profile_dir).exists()
    if should_refresh:
        reset_dev_root(dev_root)
        dev_root.mkdir(parents=True, exist_ok=True)
        copy_if_exists(source_root / "Local State", dev_root / "Local State")
        copy_if_exists(source_root / profile_dir, dev_root / profile_dir)
    else:
        dev_root.mkdir(parents=True, exist_ok=True)
    return dev_root


def build_launch_args(config: ChromeDevLaunchConfig) -> list[str]:
    return [
        f"--profile-directory={config.profile_dir}",
        f"--remote-debugging-port={config.remote_debugging_port}",
        "--new-window",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def wait_for_cdp_endpoint(port: int, timeout_seconds: float = 10.0) -> str | None:
    deadline = time.time() + timeout_seconds
    version_url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(version_url, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                endpoint = payload.get("webSocketDebuggerUrl")
                if isinstance(endpoint, str) and endpoint:
                    return endpoint
        except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    return None


def open_dashboard_context(
    playwright: Playwright, config: ChromeDevLaunchConfig
) -> tuple[BrowserContext, dict[str, str | bool | None]]:
    ensure_dashboard_available(config.dashboard_url)
    dev_root = seed_dev_profile(config)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(dev_root),
        channel="chrome",
        headless=config.headless,
        args=build_launch_args(config),
    )
    page = context.new_page()
    page.goto(config.dashboard_url, wait_until="domcontentloaded")
    page.bring_to_front()
    cdp_ws_endpoint = wait_for_cdp_endpoint(config.remote_debugging_port)
    return context, {
        "dashboard_url": config.dashboard_url,
        "dev_root": str(dev_root),
        "profile_dir": config.profile_dir,
        "source_root": str(config.source_root) if config.source_root else None,
        "remote_debugging_port": str(config.remote_debugging_port),
        "cdp_ws_endpoint": cdp_ws_endpoint,
        "headless": config.headless,
    }


def keep_browser_open(context: BrowserContext) -> None:
    stop = False

    def _handle_signal(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    original_int = signal.signal(signal.SIGINT, _handle_signal)
    original_term = signal.signal(signal.SIGTERM, _handle_signal)
    try:
        while not stop:
            time.sleep(0.5)
    finally:
        signal.signal(signal.SIGINT, original_int)
        signal.signal(signal.SIGTERM, original_term)
        context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the resolved launch configuration as JSON and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_launch_config()
    if args.print_config:
        print(json.dumps(asdict(config), indent=2, default=str))
        return 0

    with sync_playwright() as playwright:
        context, launch_summary = open_dashboard_context(playwright, config)
        print(json.dumps(launch_summary, indent=2))
        keep_browser_open(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
