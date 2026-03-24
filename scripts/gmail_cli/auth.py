"""Shared Gmail OAuth authentication module.

Extracts the duplicated token.json loading pattern from the existing scripts
into a single reusable function.
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Full scope list matching scripts/setup_rlm_agent_auth.py
DEFAULT_SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.activity",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/cloud-platform",
]

# Search order for token.json
_TOKEN_SEARCH_PATHS = [
    Path.cwd() / "token.json",
    Path.home() / ".config" / "rlm-adk" / "token.json",
]


def _find_token(override: Path | None = None) -> Path:
    """Locate token.json, checking override path first, then default locations."""
    if override is not None:
        if override.exists():
            return override
        print(
            f"Error: token.json not found at specified path: {override}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    for candidate in _TOKEN_SEARCH_PATHS:
        if candidate.exists():
            return candidate

    search_locs = "\n  ".join(str(p) for p in _TOKEN_SEARCH_PATHS)
    print(
        f"Error: token.json not found. Searched:\n  {search_locs}\n\n"
        "Run `python scripts/setup_rlm_agent_auth.py` to create it.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def get_gmail_service(
    scopes: list[str] | None = None,
    token_path: Path | None = None,
):
    """Load credentials from token.json, auto-refresh if expired, return Gmail v1 service.

    Args:
        scopes: OAuth scopes. Defaults to DEFAULT_SCOPES.
        token_path: Explicit path to token.json. If None, searches default locations.

    Returns:
        A Gmail API v1 service Resource.
    """
    scopes = scopes or DEFAULT_SCOPES
    path = _find_token(token_path)

    creds = Credentials.from_authorized_user_file(str(path), scopes)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print(
                "Error: Credentials are invalid and cannot be refreshed.\n"
                "Run `python scripts/setup_rlm_agent_auth.py` to re-authenticate.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    return build("gmail", "v1", credentials=creds)
