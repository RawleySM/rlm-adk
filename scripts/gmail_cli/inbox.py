"""Inbox commands: list, read, unread."""

from __future__ import annotations

import base64
from typing import Annotated

import typer

from scripts.gmail_cli.output import print_info, print_table, should_use_json

app = typer.Typer(rich_markup_mode="rich", help="Read and browse your inbox.")


def _get_header(headers: list[dict], name: str, default: str = "") -> str:
    return next((h["value"] for h in headers if h["name"] == name), default)


def _fetch_message_list(service, query: str, count: int) -> list[dict]:
    """Fetch message list with metadata for table display."""
    results = service.users().messages().list(
        userId="me", q=query, maxResults=count
    ).execute()
    messages = results.get("messages", [])

    rows = []
    for msg in messages:
        m = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = m["payload"]["headers"]
        rows.append({
            "id": msg["id"],
            "from": _get_header(headers, "From", "Unknown"),
            "subject": _get_header(headers, "Subject", "(no subject)"),
            "date": _get_header(headers, "Date", ""),
            "snippet": m.get("snippet", ""),
        })
    return rows


_COLUMNS = [
    ("id", "ID"),
    ("from", "From"),
    ("subject", "Subject"),
    ("date", "Date"),
    ("snippet", "Snippet"),
]


@app.command("list")
def inbox_list(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of messages")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List recent messages from primary inbox."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    print_info(f"Fetching {count} messages from primary inbox...", quiet)
    rows = _fetch_message_list(service, "label:INBOX category:primary", count)
    print_table(rows, _COLUMNS, should_use_json(json))


@app.command("read")
def inbox_read(
    msg_id: Annotated[str, typer.Argument(help="Message ID to read")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Fetch and display full message body."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service
    from scripts.gmail_cli.output import print_json

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    m = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = m["payload"]["headers"]

    body_text = _extract_body(m["payload"])

    if should_use_json(json):
        print_json({
            "id": m["id"],
            "threadId": m.get("threadId", ""),
            "from": _get_header(headers, "From"),
            "to": _get_header(headers, "To"),
            "subject": _get_header(headers, "Subject"),
            "date": _get_header(headers, "Date"),
            "body": body_text,
        })
    else:
        print(f"From: {_get_header(headers, 'From')}")
        print(f"To: {_get_header(headers, 'To')}")
        print(f"Subject: {_get_header(headers, 'Subject')}")
        print(f"Date: {_get_header(headers, 'Date')}")
        print(f"---\n{body_text}")


@app.command("unread")
def inbox_unread(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of messages")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List unread messages."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    print_info(f"Fetching {count} unread messages...", quiet)
    rows = _fetch_message_list(service, "is:unread", count)
    print_table(rows, _COLUMNS, should_use_json(json))


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from MIME payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    # Fallback: try body data directly
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    return ""
