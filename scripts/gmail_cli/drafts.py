"""Draft commands: list, create, send, delete."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Annotated

import typer

from scripts.gmail_cli.output import (
    print_info,
    print_json,
    print_table,
    should_use_json,
)

app = typer.Typer(rich_markup_mode="rich", help="Manage email drafts.")


def _get_header(headers: list[dict], name: str, default: str = "") -> str:
    return next((h["value"] for h in headers if h["name"] == name), default)


@app.command("list")
def drafts_list(
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List all drafts."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    print_info("Fetching drafts...", quiet)

    results = service.users().drafts().list(userId="me").execute()
    drafts = results.get("drafts", [])

    rows = []
    for draft in drafts:
        d = service.users().drafts().get(userId="me", id=draft["id"], format="metadata").execute()
        msg = d.get("message", {})
        headers = msg.get("payload", {}).get("headers", [])
        rows.append({
            "draft_id": draft["id"],
            "msg_id": msg.get("id", ""),
            "to": _get_header(headers, "To"),
            "subject": _get_header(headers, "Subject", "(no subject)"),
            "date": _get_header(headers, "Date", ""),
            "snippet": msg.get("snippet", ""),
        })

    columns = [
        ("draft_id", "Draft ID"),
        ("to", "To"),
        ("subject", "Subject"),
        ("date", "Date"),
        ("snippet", "Snippet"),
    ]
    print_table(rows, columns, should_use_json(json))


@app.command("create")
def drafts_create(
    to: Annotated[str, typer.Option("--to", help="Recipient email")],
    subject: Annotated[str, typer.Option("--subject", help="Subject")],
    body: Annotated[str, typer.Option("--body", help="Body text")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Create a draft without sending."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)

    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = to
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    result = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()

    if should_use_json(json):
        print_json({"draft_id": result["id"], "msg_id": result.get("message", {}).get("id", "")})
    else:
        print_info(f"Draft created! ID: {result['id']}", quiet)


@app.command("send")
def drafts_send(
    draft_id: Annotated[str, typer.Argument(help="Draft ID to send")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Send an existing draft."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    if not yes:
        if not typer.confirm(f"Send draft {draft_id}?"):
            print_info("Cancelled.", quiet)
            raise typer.Exit(0)

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    result = service.users().drafts().send(
        userId="me", body={"id": draft_id}
    ).execute()

    if should_use_json(json):
        print_json({"id": result["id"], "threadId": result.get("threadId", "")})
    else:
        print_info(f"Draft sent! Message ID: {result['id']}", quiet)


@app.command("delete")
def drafts_delete(
    draft_id: Annotated[str, typer.Argument(help="Draft ID to delete")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Delete a draft."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    if not yes:
        if not typer.confirm(f"Delete draft {draft_id}?"):
            print_info("Cancelled.", quiet)
            raise typer.Exit(0)

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    service.users().drafts().delete(userId="me", id=draft_id).execute()

    if should_use_json(json):
        print_json({"draft_id": draft_id, "deleted": True})
    else:
        print_info(f"Draft {draft_id} deleted.", quiet)
