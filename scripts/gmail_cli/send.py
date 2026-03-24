"""Send commands: compose and send emails."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path
from typing import Annotated

import typer

from scripts.gmail_cli.output import print_error, print_info, print_json, should_use_json

app = typer.Typer(rich_markup_mode="rich", help="Send emails.")


def _create_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> dict:
    """Build a base64url-encoded email message dict."""
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


@app.command("email")
def send_email(
    to: Annotated[str, typer.Option("--to", help="Recipient email address")],
    subject: Annotated[str, typer.Option("--subject", help="Email subject")],
    body: Annotated[str | None, typer.Option("--body", help="Email body text")] = None,
    body_file: Annotated[Path | None, typer.Option("--body-file", help="Read body from file")] = None,
    cc: Annotated[str | None, typer.Option("--cc", help="CC recipient")] = None,
    bcc: Annotated[str | None, typer.Option("--bcc", help="BCC recipient")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Send a plain text email."""
    if body is None and body_file is None:
        print_error("Provide either --body or --body-file")
        raise typer.Exit(1)

    if body_file is not None:
        if not body_file.exists():
            print_error(f"File not found: {body_file}")
            raise typer.Exit(1)
        body = body_file.read_text()

    if not yes:
        print_info(f"To: {to}", quiet)
        print_info(f"Subject: {subject}", quiet)
        if cc:
            print_info(f"CC: {cc}", quiet)
        if bcc:
            print_info(f"BCC: {bcc}", quiet)
        if not typer.confirm("Send this email?"):
            print_info("Cancelled.", quiet)
            raise typer.Exit(0)

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(
        token_path=Path(token_path) if token_path else None
    )
    assert body is not None  # guaranteed by earlier check
    message = _create_message(to, subject, body, cc=cc, bcc=bcc)
    result = service.users().messages().send(userId="me", body=message).execute()

    if should_use_json(json):
        print_json({"id": result["id"], "threadId": result.get("threadId", "")})
    else:
        print_info(f"Sent! Message ID: {result['id']}", quiet)
