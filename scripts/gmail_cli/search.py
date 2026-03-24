"""Search commands: full Gmail search syntax."""

from __future__ import annotations

from typing import Annotated

import typer

from scripts.gmail_cli.output import print_info, print_table, should_use_json

app = typer.Typer(rich_markup_mode="rich", help="Search Gmail messages.")

_COLUMNS = [
    ("id", "ID"),
    ("from", "From"),
    ("subject", "Subject"),
    ("date", "Date"),
    ("snippet", "Snippet"),
]


def _get_header(headers: list[dict], name: str, default: str = "") -> str:
    return next((h["value"] for h in headers if h["name"] == name), default)


@app.command("query")
def search_query(
    query: Annotated[str, typer.Argument(help="Gmail search query (full syntax supported)")],
    count: Annotated[int, typer.Option("--count", "-n", help="Max results")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Search messages with full Gmail query syntax."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    print_info(f"Searching: {query} (max {count})...", quiet)

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

    print_table(rows, _COLUMNS, should_use_json(json))
