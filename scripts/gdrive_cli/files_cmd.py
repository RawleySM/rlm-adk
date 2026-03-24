"""Files subgroup — move, copy, rename, trash, untrash, delete, list-trashed."""

from __future__ import annotations

import json as json_mod
from typing import Annotated

import typer

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    FILE_COLUMNS,
    console_out,
    file_row,
    print_error,
    print_table,
    should_use_json,
)

app = typer.Typer(help="File management — move, copy, rename, trash, delete.")


@app.command("move")
def move(
    file_id: Annotated[str, typer.Argument(help="File ID to move.")],
    dest_folder_id: Annotated[str, typer.Argument(help="Destination folder ID.")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Move a file to a different folder."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    # Get current parents
    meta = service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(meta.get("parents", []))

    updated = (
        service.files()
        .update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=previous_parents,
            fields="id,name,mimeType,parents",
        )
        .execute()
    )

    if json_mode:
        print(json_mod.dumps(updated))
    else:
        console_out.print(f"[green]Moved:[/green] {updated['name']} → folder {dest_folder_id}")


@app.command("copy")
def copy(
    file_id: Annotated[str, typer.Argument(help="File ID to copy.")],
    name: Annotated[str | None, typer.Option("--name", help="New name for copy.")] = None,
    folder: Annotated[str | None, typer.Option("--folder", help="Destination folder ID.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Copy a file."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    body: dict = {}
    if name:
        body["name"] = name
    if folder:
        body["parents"] = [folder]

    copied = service.files().copy(fileId=file_id, body=body, fields="id,name,mimeType,size").execute()

    if json_mode:
        print(json_mod.dumps(copied))
    else:
        console_out.print(f"[green]Copied:[/green] {copied['name']} (ID: {copied['id']})")


@app.command("rename")
def rename(
    file_id: Annotated[str, typer.Argument(help="File ID to rename.")],
    new_name: Annotated[str, typer.Argument(help="New name.")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Rename a file."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    updated = (
        service.files()
        .update(fileId=file_id, body={"name": new_name}, fields="id,name,mimeType")
        .execute()
    )

    if json_mode:
        print(json_mod.dumps(updated))
    else:
        console_out.print(f"[green]Renamed:[/green] {updated['name']}")


@app.command("trash")
def trash(
    file_id: Annotated[str, typer.Argument(help="File ID to trash.")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Move a file to trash (soft delete)."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    updated = (
        service.files()
        .update(fileId=file_id, body={"trashed": True}, fields="id,name,trashed")
        .execute()
    )

    if json_mode:
        print(json_mod.dumps(updated))
    else:
        console_out.print(f"[yellow]Trashed:[/yellow] {updated['name']}")


@app.command("untrash")
def untrash(
    file_id: Annotated[str, typer.Argument(help="File ID to restore.")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Restore a file from trash."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    updated = (
        service.files()
        .update(fileId=file_id, body={"trashed": False}, fields="id,name,trashed")
        .execute()
    )

    if json_mode:
        print(json_mod.dumps(updated))
    else:
        console_out.print(f"[green]Restored:[/green] {updated['name']}")


@app.command("delete")
def delete(
    file_id: Annotated[str, typer.Argument(help="File ID to permanently delete.")],
    yes: Annotated[bool, typer.Option("--yes", help="Confirm permanent deletion.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Permanently delete a file. Requires --yes flag."""
    if not yes:
        print_error("Permanent deletion requires --yes flag.")
        raise typer.Exit(1)

    service = get_drive_service(token_path)
    service.files().delete(fileId=file_id).execute()
    console_out.print(f"[red]Deleted:[/red] {file_id}")


@app.command("list-trashed")
def list_trashed(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    count: Annotated[int, typer.Option("--count", "-n", help="Max results.")] = 25,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """List all files in trash."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    fields = "files(id,name,mimeType,modifiedTime,size)"
    results = (
        service.files()
        .list(q="trashed = true", pageSize=count, fields=fields)
        .execute()
    )
    files = results.get("files", [])

    if not files:
        print_error("Trash is empty.")
        raise typer.Exit(0)

    rows = [file_row(f, json_mode) for f in files]
    print_table(rows, FILE_COLUMNS, json_mode)
