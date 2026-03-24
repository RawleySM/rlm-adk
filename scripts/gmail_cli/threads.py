"""Thread commands: list, read, reply."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Annotated

import typer

from scripts.gmail_cli.output import print_info, print_json, print_table, should_use_json

app = typer.Typer(rich_markup_mode="rich", help="View and reply to threads.")


def _get_header(headers: list[dict], name: str, default: str = "") -> str:
    return next((h["value"] for h in headers if h["name"] == name), default)


@app.command("list")
def threads_list(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of threads")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List recent threads."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    print_info(f"Fetching {count} threads...", quiet)

    results = service.users().threads().list(userId="me", maxResults=count).execute()
    threads = results.get("threads", [])

    rows = []
    for thread in threads:
        t = service.users().threads().get(
            userId="me", id=thread["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        msgs = t.get("messages", [])
        first_msg = msgs[0] if msgs else {}
        last_msg = msgs[-1] if msgs else {}
        first_headers = first_msg.get("payload", {}).get("headers", [])
        last_headers = last_msg.get("payload", {}).get("headers", [])

        rows.append({
            "id": thread["id"],
            "subject": _get_header(first_headers, "Subject", "(no subject)"),
            "from": _get_header(last_headers, "From", "Unknown"),
            "date": _get_header(last_headers, "Date", ""),
            "messages": len(msgs),
            "snippet": last_msg.get("snippet", ""),
        })

    columns = [
        ("id", "ID"),
        ("subject", "Subject"),
        ("from", "Last From"),
        ("date", "Last Date"),
        ("messages", "Msgs"),
        ("snippet", "Snippet"),
    ]
    print_table(rows, columns, should_use_json(json))


@app.command("read")
def threads_read(
    thread_id: Annotated[str, typer.Argument(help="Thread ID")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Display full conversation thread with all messages."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service
    from scripts.gmail_cli.inbox import _extract_body

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    t = service.users().threads().get(userId="me", id=thread_id, format="full").execute()

    messages = []
    for msg in t.get("messages", []):
        headers = msg.get("payload", {}).get("headers", [])
        messages.append({
            "id": msg["id"],
            "from": _get_header(headers, "From"),
            "to": _get_header(headers, "To"),
            "date": _get_header(headers, "Date"),
            "subject": _get_header(headers, "Subject"),
            "body": _extract_body(msg["payload"]),
        })

    if should_use_json(json):
        for m in messages:
            print_json(m)
    else:
        for i, m in enumerate(messages):
            if i > 0:
                print("=" * 60)
            print(f"From: {m['from']}")
            print(f"To: {m['to']}")
            print(f"Date: {m['date']}")
            print(f"Subject: {m['subject']}")
            print(f"---\n{m['body']}\n")


@app.command("reply")
def threads_reply(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to reply to")],
    body: Annotated[str, typer.Option("--body", help="Reply body text")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Reply to a thread with correct threading headers."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)

    # Get the last message in the thread for headers
    t = service.users().threads().get(
        userId="me", id=thread_id, format="metadata",
        metadataHeaders=["From", "To", "Subject", "Message-ID", "References"],
    ).execute()
    msgs = t.get("messages", [])
    if not msgs:
        from scripts.gmail_cli.output import print_error
        print_error(f"Thread {thread_id} has no messages")
        raise typer.Exit(1)

    last_msg = msgs[-1]
    headers = last_msg.get("payload", {}).get("headers", [])
    original_from = _get_header(headers, "From")
    original_subject = _get_header(headers, "Subject")
    message_id = _get_header(headers, "Message-ID")
    references = _get_header(headers, "References")

    if not yes:
        print_info(f"Replying to: {original_from}", quiet)
        print_info(f"Subject: Re: {original_subject}", quiet)
        if not typer.confirm("Send reply?"):
            print_info("Cancelled.", quiet)
            raise typer.Exit(0)

    # Build reply
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = original_from
    msg["Subject"] = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject
    if message_id:
        msg["In-Reply-To"] = message_id
        msg["References"] = f"{references} {message_id}".strip() if references else message_id

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()

    if should_use_json(json):
        print_json({"id": result["id"], "threadId": result.get("threadId", "")})
    else:
        print_info(f"Reply sent! Message ID: {result['id']}", quiet)
