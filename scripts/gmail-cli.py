#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer>=0.21.0",
#     "rich>=13.0.0",
#     "google-api-python-client>=2.0.0",
#     "google-auth-oauthlib>=1.0.0",
#     "google-auth-httplib2>=0.2.0",
# ]
# ///
"""Gmail CLI — agent-friendly Gmail interaction via Typer subcommands.

Single-file script with inline PEP 723 metadata.  Run directly with uv:

    uv run scripts/gmail-cli.py --help

Or via the bash alias (after sourcing ~/.bashrc):

    gmail inbox list
    gmail send email --to a@b.com --subject Hi --body Hello --yes
"""
from __future__ import annotations

import base64
import json
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

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

_TOKEN_SEARCH_PATHS = [
    Path.cwd() / "token.json",
    Path.home() / ".config" / "rlm-adk" / "token.json",
]


def _find_token(override: Path | None = None) -> Path:
    if override is not None:
        if override.exists():
            return override
        print(f"Error: token.json not found at: {override}", file=sys.stderr)
        raise SystemExit(1)
    for candidate in _TOKEN_SEARCH_PATHS:
        if candidate.exists():
            return candidate
    locs = "\n  ".join(str(p) for p in _TOKEN_SEARCH_PATHS)
    print(
        f"Error: token.json not found. Searched:\n  {locs}\n\n"
        "Run `python scripts/setup_rlm_agent_auth.py` to create it.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def get_gmail_service(
    scopes: list[str] | None = None,
    token_path: Path | None = None,
):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    scopes = scopes or DEFAULT_SCOPES
    path = _find_token(token_path)
    creds = Credentials.from_authorized_user_file(str(path), scopes)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print(
                "Error: Credentials invalid and cannot be refreshed.\n"
                "Run `python scripts/setup_rlm_agent_auth.py` to re-authenticate.",
                file=sys.stderr,
            )
            raise SystemExit(1)
    return build("gmail", "v1", credentials=creds)


def _svc(token_path: str | None) -> object:
    return get_gmail_service(token_path=Path(token_path) if token_path else None)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_con_out = Console()
_con_err = Console(stderr=True)


def _use_json(flag: bool) -> bool:
    return flag or not sys.stdout.isatty()


def _print_table(rows: list[dict], columns: list[tuple[str, str]], json_mode: bool) -> None:
    if json_mode:
        for row in rows:
            print(json.dumps(row))
        return
    table = Table(show_header=True, header_style="bold cyan")
    for _, header in columns:
        table.add_column(header)
    for row in rows:
        table.add_row(*(str(row.get(key, "")) for key, _ in columns))
    _con_out.print(table)


def _print_json(data: dict | list) -> None:
    print(json.dumps(data))


def _err(msg: str) -> None:
    _con_err.print(f"[red]Error:[/red] {msg}")


def _info(msg: str, quiet: bool = False) -> None:
    if not quiet:
        _con_err.print(msg)


# ---------------------------------------------------------------------------
# Shared Gmail helpers
# ---------------------------------------------------------------------------

def _hdr(headers: list[dict], name: str, default: str = "") -> str:
    return next((h["value"] for h in headers if h["name"] == name), default)


def _fetch_messages(service, query: str, count: int) -> list[dict]:
    results = service.users().messages().list(userId="me", q=query, maxResults=count).execute()
    rows = []
    for msg in results.get("messages", []):
        m = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        hdrs = m["payload"]["headers"]
        rows.append({
            "id": msg["id"],
            "from": _hdr(hdrs, "From", "Unknown"),
            "subject": _hdr(hdrs, "Subject", "(no subject)"),
            "date": _hdr(hdrs, "Date", ""),
            "snippet": m.get("snippet", ""),
        })
    return rows


_MSG_COLS = [("id", "ID"), ("from", "From"), ("subject", "Subject"), ("date", "Date"), ("snippet", "Snippet")]


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    return ""


def _create_raw_message(
    to: str, subject: str, body: str,
    cc: str | None = None, bcc: str | None = None,
    in_reply_to: str | None = None, references: str | None = None,
) -> str:
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _resolve_label_id(service, label_name_or_id: str) -> str | None:
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["id"] == label_name_or_id or label["name"] == label_name_or_id:
            return label["id"]
    return None


# ---------------------------------------------------------------------------
# Typer app & subcommand groups
# ---------------------------------------------------------------------------

app = typer.Typer(
    rich_markup_mode="rich",
    help="[bold]Gmail CLI[/bold] — agent-friendly Gmail interaction tool.",
    no_args_is_help=True,
)
inbox_app = typer.Typer(rich_markup_mode="rich", help="Read and browse your inbox.")
send_app = typer.Typer(rich_markup_mode="rich", help="Send emails.")
search_app = typer.Typer(rich_markup_mode="rich", help="Search Gmail messages.")
labels_app = typer.Typer(rich_markup_mode="rich", help="Manage Gmail labels.")
threads_app = typer.Typer(rich_markup_mode="rich", help="View and reply to threads.")
drafts_app = typer.Typer(rich_markup_mode="rich", help="Manage email drafts.")

app.add_typer(inbox_app, name="inbox")
app.add_typer(send_app, name="send")
app.add_typer(search_app, name="search")
app.add_typer(labels_app, name="labels")
app.add_typer(threads_app, name="threads")
app.add_typer(drafts_app, name="drafts")


# ---------------------------------------------------------------------------
# inbox commands
# ---------------------------------------------------------------------------


@inbox_app.command("list")
def inbox_list(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of messages")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List recent messages from primary inbox."""
    service = _svc(token_path)
    _info(f"Fetching {count} messages from primary inbox...", quiet)
    _print_table(_fetch_messages(service, "label:INBOX category:primary", count), _MSG_COLS, _use_json(json))


@inbox_app.command("read")
def inbox_read(
    msg_id: Annotated[str, typer.Argument(help="Message ID to read")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Fetch and display full message body."""
    service = _svc(token_path)
    m = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    hdrs = m["payload"]["headers"]
    body_text = _extract_body(m["payload"])
    if _use_json(json):
        _print_json({
            "id": m["id"], "threadId": m.get("threadId", ""),
            "from": _hdr(hdrs, "From"), "to": _hdr(hdrs, "To"),
            "subject": _hdr(hdrs, "Subject"), "date": _hdr(hdrs, "Date"),
            "body": body_text,
        })
    else:
        print(f"From: {_hdr(hdrs, 'From')}\nTo: {_hdr(hdrs, 'To')}")
        print(f"Subject: {_hdr(hdrs, 'Subject')}\nDate: {_hdr(hdrs, 'Date')}")
        print(f"---\n{body_text}")


@inbox_app.command("unread")
def inbox_unread(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of messages")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List unread messages."""
    service = _svc(token_path)
    _info(f"Fetching {count} unread messages...", quiet)
    _print_table(_fetch_messages(service, "is:unread", count), _MSG_COLS, _use_json(json))


# ---------------------------------------------------------------------------
# send commands
# ---------------------------------------------------------------------------


@send_app.command("email")
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
        _err("Provide either --body or --body-file")
        raise typer.Exit(1)
    if body_file is not None:
        if not body_file.exists():
            _err(f"File not found: {body_file}")
            raise typer.Exit(1)
        body = body_file.read_text()
    if not yes:
        _info(f"To: {to}", quiet)
        _info(f"Subject: {subject}", quiet)
        if cc:
            _info(f"CC: {cc}", quiet)
        if bcc:
            _info(f"BCC: {bcc}", quiet)
        if not typer.confirm("Send this email?"):
            _info("Cancelled.", quiet)
            raise typer.Exit(0)
    service = _svc(token_path)
    assert body is not None
    raw = _create_raw_message(to, subject, body, cc=cc, bcc=bcc)
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    if _use_json(json):
        _print_json({"id": result["id"], "threadId": result.get("threadId", "")})
    else:
        _info(f"Sent! Message ID: {result['id']}", quiet)


# ---------------------------------------------------------------------------
# search commands
# ---------------------------------------------------------------------------


@search_app.command("query")
def search_query(
    query: Annotated[str, typer.Argument(help="Gmail search query (full syntax supported)")],
    count: Annotated[int, typer.Option("--count", "-n", help="Max results")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Search messages with full Gmail query syntax."""
    service = _svc(token_path)
    _info(f"Searching: {query} (max {count})...", quiet)
    _print_table(_fetch_messages(service, query, count), _MSG_COLS, _use_json(json))


# ---------------------------------------------------------------------------
# labels commands
# ---------------------------------------------------------------------------


@labels_app.command("list")
def labels_list(
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List all labels with message counts."""
    service = _svc(token_path)
    _info("Fetching labels...", quiet)
    results = service.users().labels().list(userId="me").execute()
    rows = []
    for label in results.get("labels", []):
        detail = service.users().labels().get(userId="me", id=label["id"]).execute()
        rows.append({
            "id": label["id"], "name": label["name"], "type": label.get("type", ""),
            "messages_total": detail.get("messagesTotal", 0),
            "messages_unread": detail.get("messagesUnread", 0),
        })
    cols = [("id", "ID"), ("name", "Name"), ("type", "Type"), ("messages_total", "Total"), ("messages_unread", "Unread")]
    _print_table(rows, cols, _use_json(json))


@labels_app.command("add")
def labels_add(
    msg_id: Annotated[str, typer.Argument(help="Message ID")],
    label: Annotated[str, typer.Argument(help="Label name or ID to add")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Add a label to a message."""
    service = _svc(token_path)
    label_id = _resolve_label_id(service, label)
    if not label_id:
        _err(f"Label not found: {label}")
        raise typer.Exit(1)
    service.users().messages().modify(userId="me", id=msg_id, body={"addLabelIds": [label_id]}).execute()
    if _use_json(json):
        _print_json({"msg_id": msg_id, "label_added": label})
    else:
        _info(f"Added label '{label}' to message {msg_id}", quiet)


@labels_app.command("remove")
def labels_remove(
    msg_id: Annotated[str, typer.Argument(help="Message ID")],
    label: Annotated[str, typer.Argument(help="Label name or ID to remove")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Remove a label from a message."""
    service = _svc(token_path)
    label_id = _resolve_label_id(service, label)
    if not label_id:
        _err(f"Label not found: {label}")
        raise typer.Exit(1)
    service.users().messages().modify(userId="me", id=msg_id, body={"removeLabelIds": [label_id]}).execute()
    if _use_json(json):
        _print_json({"msg_id": msg_id, "label_removed": label})
    else:
        _info(f"Removed label '{label}' from message {msg_id}", quiet)


@labels_app.command("create")
def labels_create(
    name: Annotated[str, typer.Argument(help="New label name")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Create a new label."""
    service = _svc(token_path)
    result = service.users().labels().create(
        userId="me", body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    ).execute()
    if _use_json(json):
        _print_json({"id": result["id"], "name": result["name"]})
    else:
        _info(f"Created label '{result['name']}' (ID: {result['id']})", quiet)


# ---------------------------------------------------------------------------
# threads commands
# ---------------------------------------------------------------------------


@threads_app.command("list")
def threads_list(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of threads")] = 10,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List recent threads."""
    service = _svc(token_path)
    _info(f"Fetching {count} threads...", quiet)
    results = service.users().threads().list(userId="me", maxResults=count).execute()
    rows = []
    for thread in results.get("threads", []):
        t = service.users().threads().get(
            userId="me", id=thread["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        msgs = t.get("messages", [])
        first_msg = msgs[0] if msgs else {}
        last_msg = msgs[-1] if msgs else {}
        first_hdrs = first_msg.get("payload", {}).get("headers", [])
        last_hdrs = last_msg.get("payload", {}).get("headers", [])
        rows.append({
            "id": thread["id"],
            "subject": _hdr(first_hdrs, "Subject", "(no subject)"),
            "from": _hdr(last_hdrs, "From", "Unknown"),
            "date": _hdr(last_hdrs, "Date", ""),
            "messages": len(msgs),
            "snippet": last_msg.get("snippet", ""),
        })
    cols = [("id", "ID"), ("subject", "Subject"), ("from", "Last From"), ("date", "Last Date"), ("messages", "Msgs"), ("snippet", "Snippet")]
    _print_table(rows, cols, _use_json(json))


@threads_app.command("read")
def threads_read(
    thread_id: Annotated[str, typer.Argument(help="Thread ID")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Display full conversation thread with all messages."""
    service = _svc(token_path)
    t = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    messages = []
    for msg in t.get("messages", []):
        hdrs = msg.get("payload", {}).get("headers", [])
        messages.append({
            "id": msg["id"], "from": _hdr(hdrs, "From"), "to": _hdr(hdrs, "To"),
            "date": _hdr(hdrs, "Date"), "subject": _hdr(hdrs, "Subject"),
            "body": _extract_body(msg["payload"]),
        })
    if _use_json(json):
        for m in messages:
            _print_json(m)
    else:
        for i, m in enumerate(messages):
            if i > 0:
                print("=" * 60)
            print(f"From: {m['from']}\nTo: {m['to']}\nDate: {m['date']}\nSubject: {m['subject']}\n---\n{m['body']}\n")


@threads_app.command("reply")
def threads_reply(
    thread_id: Annotated[str, typer.Argument(help="Thread ID to reply to")],
    body: Annotated[str, typer.Option("--body", help="Reply body text")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Reply to a thread with correct threading headers."""
    service = _svc(token_path)
    t = service.users().threads().get(
        userId="me", id=thread_id, format="metadata",
        metadataHeaders=["From", "To", "Subject", "Message-ID", "References"],
    ).execute()
    msgs = t.get("messages", [])
    if not msgs:
        _err(f"Thread {thread_id} has no messages")
        raise typer.Exit(1)
    last = msgs[-1]
    hdrs = last.get("payload", {}).get("headers", [])
    orig_from = _hdr(hdrs, "From")
    orig_subject = _hdr(hdrs, "Subject")
    message_id = _hdr(hdrs, "Message-ID")
    refs = _hdr(hdrs, "References")
    if not yes:
        _info(f"Replying to: {orig_from}", quiet)
        _info(f"Subject: Re: {orig_subject}", quiet)
        if not typer.confirm("Send reply?"):
            _info("Cancelled.", quiet)
            raise typer.Exit(0)
    reply_subject = f"Re: {orig_subject}" if not orig_subject.startswith("Re:") else orig_subject
    reply_refs = f"{refs} {message_id}".strip() if refs else message_id if message_id else None
    raw = _create_raw_message(
        orig_from, reply_subject, body,
        in_reply_to=message_id or None, references=reply_refs,
    )
    result = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()
    if _use_json(json):
        _print_json({"id": result["id"], "threadId": result.get("threadId", "")})
    else:
        _info(f"Reply sent! Message ID: {result['id']}", quiet)


# ---------------------------------------------------------------------------
# drafts commands
# ---------------------------------------------------------------------------


@drafts_app.command("list")
def drafts_list(
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List all drafts."""
    service = _svc(token_path)
    _info("Fetching drafts...", quiet)
    results = service.users().drafts().list(userId="me").execute()
    rows = []
    for draft in results.get("drafts", []):
        d = service.users().drafts().get(userId="me", id=draft["id"], format="metadata").execute()
        msg = d.get("message", {})
        hdrs = msg.get("payload", {}).get("headers", [])
        rows.append({
            "draft_id": draft["id"], "msg_id": msg.get("id", ""),
            "to": _hdr(hdrs, "To"), "subject": _hdr(hdrs, "Subject", "(no subject)"),
            "date": _hdr(hdrs, "Date", ""), "snippet": msg.get("snippet", ""),
        })
    cols = [("draft_id", "Draft ID"), ("to", "To"), ("subject", "Subject"), ("date", "Date"), ("snippet", "Snippet")]
    _print_table(rows, cols, _use_json(json))


@drafts_app.command("create")
def drafts_create(
    to: Annotated[str, typer.Option("--to", help="Recipient email")],
    subject: Annotated[str, typer.Option("--subject", help="Subject")],
    body: Annotated[str, typer.Option("--body", help="Body text")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Create a draft without sending."""
    service = _svc(token_path)
    raw = _create_raw_message(to, subject, body)
    result = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    if _use_json(json):
        _print_json({"draft_id": result["id"], "msg_id": result.get("message", {}).get("id", "")})
    else:
        _info(f"Draft created! ID: {result['id']}", quiet)


@drafts_app.command("send")
def drafts_send(
    draft_id: Annotated[str, typer.Argument(help="Draft ID to send")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Send an existing draft."""
    if not yes:
        if not typer.confirm(f"Send draft {draft_id}?"):
            _info("Cancelled.", quiet)
            raise typer.Exit(0)
    service = _svc(token_path)
    result = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    if _use_json(json):
        _print_json({"id": result["id"], "threadId": result.get("threadId", "")})
    else:
        _info(f"Draft sent! Message ID: {result['id']}", quiet)


@drafts_app.command("delete")
def drafts_delete(
    draft_id: Annotated[str, typer.Argument(help="Draft ID to delete")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Delete a draft."""
    if not yes:
        if not typer.confirm(f"Delete draft {draft_id}?"):
            _info("Cancelled.", quiet)
            raise typer.Exit(0)
    service = _svc(token_path)
    service.users().drafts().delete(userId="me", id=draft_id).execute()
    if _use_json(json):
        _print_json({"draft_id": draft_id, "deleted": True})
    else:
        _info(f"Draft {draft_id} deleted.", quiet)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
