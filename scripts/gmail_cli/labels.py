"""Label commands: list, add, remove, create."""

from __future__ import annotations

from typing import Annotated

import typer

from scripts.gmail_cli.output import (
    print_error,
    print_info,
    print_json,
    print_table,
    should_use_json,
)

app = typer.Typer(rich_markup_mode="rich", help="Manage Gmail labels.")


@app.command("list")
def labels_list(
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """List all labels with message counts."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    print_info("Fetching labels...", quiet)

    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])

    rows = []
    for label in labels:
        detail = service.users().labels().get(userId="me", id=label["id"]).execute()
        rows.append({
            "id": label["id"],
            "name": label["name"],
            "type": label.get("type", ""),
            "messages_total": detail.get("messagesTotal", 0),
            "messages_unread": detail.get("messagesUnread", 0),
        })

    columns = [
        ("id", "ID"),
        ("name", "Name"),
        ("type", "Type"),
        ("messages_total", "Total"),
        ("messages_unread", "Unread"),
    ]
    print_table(rows, columns, should_use_json(json))


@app.command("add")
def labels_add(
    msg_id: Annotated[str, typer.Argument(help="Message ID")],
    label: Annotated[str, typer.Argument(help="Label name or ID to add")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Add a label to a message."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    label_id = _resolve_label_id(service, label)
    if not label_id:
        print_error(f"Label not found: {label}")
        raise typer.Exit(1)

    service.users().messages().modify(
        userId="me", id=msg_id, body={"addLabelIds": [label_id]}
    ).execute()

    if should_use_json(json):
        print_json({"msg_id": msg_id, "label_added": label})
    else:
        print_info(f"Added label '{label}' to message {msg_id}", quiet)


@app.command("remove")
def labels_remove(
    msg_id: Annotated[str, typer.Argument(help="Message ID")],
    label: Annotated[str, typer.Argument(help="Label name or ID to remove")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Remove a label from a message."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    label_id = _resolve_label_id(service, label)
    if not label_id:
        print_error(f"Label not found: {label}")
        raise typer.Exit(1)

    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": [label_id]}
    ).execute()

    if should_use_json(json):
        print_json({"msg_id": msg_id, "label_removed": label})
    else:
        print_info(f"Removed label '{label}' from message {msg_id}", quiet)


@app.command("create")
def labels_create(
    name: Annotated[str, typer.Argument(help="New label name")],
    json: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-data output")] = False,
    token_path: Annotated[str | None, typer.Option("--token-path", help="Path to token.json")] = None,
):
    """Create a new label."""
    from pathlib import Path

    from scripts.gmail_cli.auth import get_gmail_service

    service = get_gmail_service(token_path=Path(token_path) if token_path else None)
    result = service.users().labels().create(
        userId="me", body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    ).execute()

    if should_use_json(json):
        print_json({"id": result["id"], "name": result["name"]})
    else:
        print_info(f"Created label '{result['name']}' (ID: {result['id']})", quiet)


def _resolve_label_id(service, label_name_or_id: str) -> str | None:
    """Resolve a label name to its ID. If already an ID, return as-is."""
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["id"] == label_name_or_id or label["name"] == label_name_or_id:
            return label["id"]
    return None
