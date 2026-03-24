"""Sharing subgroup — list, add, remove permissions, manage link sharing."""

from __future__ import annotations

import json as json_mod
from typing import Annotated

import typer

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    console_out,
    print_error,
    print_table,
    should_use_json,
)

app = typer.Typer(help="Sharing — manage file permissions and link sharing.")

PERMISSION_COLUMNS = [
    ("email", "Email"),
    ("role", "Role"),
    ("type", "Type"),
    ("id", "Permission ID"),
]


@app.command("list")
def sharing_list(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """List all permissions on a file."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    perms = service.permissions().list(fileId=file_id, fields="permissions(id,emailAddress,role,type)").execute()
    permissions = perms.get("permissions", [])

    if not permissions:
        print_error("No permissions found.")
        raise typer.Exit(0)

    rows = [
        {
            "email": p.get("emailAddress", "—"),
            "role": p.get("role", ""),
            "type": p.get("type", ""),
            "id": p.get("id", ""),
        }
        for p in permissions
    ]
    print_table(rows, PERMISSION_COLUMNS, json_mode)


@app.command("add")
def sharing_add(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    email: Annotated[str, typer.Argument(help="Email address to share with.")],
    role: Annotated[str, typer.Option("--role", help="Permission role: reader, commenter, writer, organizer.")] = "reader",
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Share a file with a user."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    body = {"type": "user", "role": role, "emailAddress": email}
    perm = service.permissions().create(fileId=file_id, body=body, fields="id,emailAddress,role,type").execute()

    if json_mode:
        print(json_mod.dumps(perm))
    else:
        console_out.print(f"[green]Shared:[/green] {email} ({role})")


@app.command("remove")
def sharing_remove(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    permission_id: Annotated[str, typer.Argument(help="Permission ID to remove.")],
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Remove a permission from a file."""
    service = get_drive_service(token_path)
    service.permissions().delete(fileId=file_id, permissionId=permission_id).execute()
    console_out.print(f"[green]Removed permission:[/green] {permission_id}")


@app.command("link")
def sharing_link(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    anyone: Annotated[bool, typer.Option("--anyone", help="Enable 'anyone with link' sharing.")] = False,
    off: Annotated[bool, typer.Option("--off", help="Disable link sharing.")] = False,
    role: Annotated[str, typer.Option("--role", help="Role for link sharing.")] = "reader",
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Manage 'anyone with link' sharing."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    if off:
        # Find and remove the 'anyone' permission
        perms = service.permissions().list(fileId=file_id, fields="permissions(id,type)").execute()
        for p in perms.get("permissions", []):
            if p.get("type") == "anyone":
                service.permissions().delete(fileId=file_id, permissionId=p["id"]).execute()
                console_out.print("[green]Link sharing disabled.[/green]")
                return
        print_error("No 'anyone' link sharing found.")
        raise typer.Exit(1)

    if anyone:
        body = {"type": "anyone", "role": role}
        perm = service.permissions().create(fileId=file_id, body=body, fields="id,role,type").execute()

        # Get the web link
        meta = service.files().get(fileId=file_id, fields="webViewLink").execute()

        if json_mode:
            result = {**perm, "webViewLink": meta.get("webViewLink", "")}
            print(json_mod.dumps(result))
        else:
            console_out.print(f"[green]Link sharing enabled ({role}):[/green] {meta.get('webViewLink', '')}")
    else:
        print_error("Use --anyone to enable or --off to disable link sharing.")
        raise typer.Exit(1)
