"""Substack client with lazy cookie extraction and self-healing auth.

Cookie extraction pipeline:
  1. Try browser-cookie3 to read Chrome's cookie DB
  2. On failure, pip-upgrade browser-cookie3 and retry once
  3. On second failure, fall back to public-only API (no paywalled content)
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from substack_api import Newsletter, Post, SubstackAuth, User

log = logging.getLogger(__name__)

_COOKIE_NAMES = ("substack.sid", "substack.lli")
_COOKIE_CACHE_PATH = Path.home() / ".config" / "substack" / "cookies.json"


def _extract_cookies_from_chrome() -> list[dict[str, Any]] | None:
    """Extract Substack cookies from Chrome's local cookie store."""
    try:
        import browser_cookie3

        cj = browser_cookie3.chrome(domain_name=".substack.com")
        cookies = []
        for c in cj:
            if c.name in _COOKIE_NAMES:
                cookies.append(
                    {
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path,
                        "secure": c.secure,
                    }
                )
        if len(cookies) >= 2:
            return cookies
        log.warning("Found %d of 2 expected Substack cookies", len(cookies))
        return None
    except Exception as e:
        log.warning("Cookie extraction failed: %s", e)
        return None


def _upgrade_browser_cookie3() -> bool:
    """Pip-upgrade browser-cookie3 in the current venv. Returns True on success."""
    log.info("Upgrading browser-cookie3...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "browser-cookie3"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            log.info("browser-cookie3 upgraded successfully")
            # Force reimport of the upgraded module
            for mod_name in list(sys.modules):
                if mod_name.startswith("browser_cookie3"):
                    del sys.modules[mod_name]
            return True
        log.warning("Upgrade failed: %s", result.stderr[:200])
        return False
    except Exception as e:
        log.warning("Upgrade subprocess failed: %s", e)
        return False


def _extract_with_retry() -> list[dict[str, Any]] | None:
    """Try cookie extraction, upgrade browser-cookie3 on failure, retry once."""
    cookies = _extract_cookies_from_chrome()
    if cookies:
        return cookies

    if _upgrade_browser_cookie3():
        return _extract_cookies_from_chrome()

    return None


def _save_cookie_cache(cookies: list[dict[str, Any]]) -> None:
    _COOKIE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COOKIE_CACHE_PATH.write_text(json.dumps(cookies, indent=2))


def _load_cookie_cache() -> list[dict[str, Any]] | None:
    if _COOKIE_CACHE_PATH.exists():
        try:
            cookies = json.loads(_COOKIE_CACHE_PATH.read_text())
            if len(cookies) >= 2:
                return cookies
        except (json.JSONDecodeError, KeyError):
            pass
    return None


class SubstackClient:
    """Substack client with lazy auth and graceful degradation.

    Auth is resolved on first use, not at construction time.
    Paywalled content requires Chrome to be available for cookie extraction.
    Public content (posts, metadata, subscriptions) works without auth.
    """

    def __init__(self, username: str) -> None:
        self.username = username
        self._auth: SubstackAuth | None = None
        self._auth_resolved = False
        self._user: User | None = None

    def _resolve_auth(self) -> SubstackAuth | None:
        """Lazy auth: extract cookies on first access, cache for process lifetime."""
        if self._auth_resolved:
            return self._auth

        self._auth_resolved = True

        # Try fresh extraction from Chrome
        cookies = _extract_with_retry()
        if cookies:
            _save_cookie_cache(cookies)
            self._auth = SubstackAuth(cookies_path=str(_COOKIE_CACHE_PATH))
            if self._auth.authenticated:
                log.info("Authenticated via Chrome cookie extraction")
                return self._auth

        # Fall back to cached cookies
        cached = _load_cookie_cache()
        if cached:
            self._auth = SubstackAuth(cookies_path=str(_COOKIE_CACHE_PATH))
            if self._auth.authenticated:
                log.info("Authenticated via cached cookies (may be stale)")
                return self._auth

        log.warning("No auth available — public API only")
        self._auth = None
        return None

    @property
    def authenticated(self) -> bool:
        return self._resolve_auth() is not None

    def get_user(self) -> User:
        if self._user is None:
            self._user = User(self.username)
        return self._user

    def get_subscriptions(self) -> list[dict[str, Any]]:
        """Get subscriptions. Uses authenticated endpoint when available.

        The public profile API hides some paid subscriptions.
        The authenticated /api/v1/subscriptions endpoint returns the full list.
        """
        auth = self._resolve_auth()
        if auth:
            resp = auth.get("https://substack.com/api/v1/subscriptions")
            if resp.status_code == 200:
                data = resp.json()
                pubs = {p["id"]: p for p in data.get("publications", [])}
                results = []
                for s in data.get("subscriptions", []):
                    pub = pubs.get(s.get("publication_id"), {})
                    domain = (
                        pub.get("custom_domain")
                        or f"{pub.get('subdomain', '?')}.substack.com"
                    )
                    results.append(
                        {
                            "publication_id": pub.get("id", s.get("publication_id")),
                            "publication_name": pub.get("name", "Unknown"),
                            "domain": domain,
                            "membership_state": s.get("membership_state", "unknown"),
                        }
                    )
                return results

        # Fallback to public API (incomplete for paid subs)
        return self.get_user().get_subscriptions()

    def get_newsletter(self, url: str) -> Newsletter:
        auth = self._resolve_auth()
        if auth:
            return Newsletter(url, auth=auth)
        return Newsletter(url)

    def get_post(self, url: str) -> Post:
        auth = self._resolve_auth()
        if auth:
            return Post(url, auth=auth)
        return Post(url)

    def get_post_content(self, post_url: str) -> str:
        """Fetch full HTML content of a post. Auth enables paywalled access."""
        content = self.get_post(post_url).get_content()
        return content or ""

    def get_post_metadata(self, post_url: str) -> dict[str, Any]:
        return self.get_post(post_url).get_metadata()

    def get_recent_posts(self, newsletter_url: str, limit: int = 10) -> list[Post]:
        return self.get_newsletter(newsletter_url).get_posts(limit=limit)
