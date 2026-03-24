"""Search command — first-class top-level command for frictionless Drive search."""

from __future__ import annotations

from typing import Annotated

import typer

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    FILE_COLUMNS,
    file_row,
    print_error,
    print_table,
    resolve_mime_type,
    should_use_json,
)


def _build_query(
    text: str | None,
    mime_type: str | None,
    folder_id: str | None,
    owner: str | None,
    after: str | None,
    before: str | None,
    shared: bool,
    starred: bool,
    trashed: bool,
) -> str:
    """Build a Drive API q= query string from search parameters."""
    clauses: list[str] = []

    if text:
        escaped = text.replace("\\", "\\\\").replace("'", "\\'")
        clauses.append(f"fullText contains '{escaped}'")

    if mime_type:
        resolved = resolve_mime_type(mime_type)
        # For prefix-based types (image/, video/, audio/) use contains
        if resolved.endswith("/"):
            clauses.append(f"mimeType contains '{resolved}'")
        else:
            clauses.append(f"mimeType = '{resolved}'")

    if folder_id:
        clauses.append(f"'{folder_id}' in parents")

    if owner:
        clauses.append(f"'{owner}' in owners")

    if after:
        clauses.append(f"modifiedTime > '{after}T00:00:00'")

    if before:
        clauses.append(f"modifiedTime < '{before}T23:59:59'")

    if shared:
        clauses.append("not 'me' in owners")

    if starred:
        clauses.append("starred = true")

    if not trashed:
        clauses.append("trashed = false")
    else:
        clauses.append("trashed = true")

    return " and ".join(clauses)


def search(
    query: Annotated[str | None, typer.Argument(help="Full-text search query.")] = None,
    type: Annotated[
        str | None,
        typer.Option(
            "--type", "-t",
            help="Filter by type: doc, sheet, slide, pdf, image, video, audio, folder, zip, or raw MIME.",
        ),
    ] = None,
    in_folder: Annotated[
        str | None, typer.Option("--in", help="Scope search to a folder ID.")
    ] = None,
    owner: Annotated[
        str | None, typer.Option("--owner", help="Filter by owner email.")
    ] = None,
    after: Annotated[
        str | None, typer.Option("--after", help="Modified after date (YYYY-MM-DD).")
    ] = None,
    before: Annotated[
        str | None, typer.Option("--before", help="Modified before date (YYYY-MM-DD).")
    ] = None,
    shared: Annotated[bool, typer.Option("--shared", help="Only files shared with you.")] = False,
    starred: Annotated[bool, typer.Option("--starred", help="Only starred files.")] = False,
    trashed: Annotated[bool, typer.Option("--trashed", help="Search trash.")] = False,
    count: Annotated[int, typer.Option("--count", "-n", help="Max results.")] = 25,
    recent: Annotated[
        bool, typer.Option("--recent", help="List 25 most recently modified files.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Search Google Drive files. Full-text search with composable filters."""
    if not query and not recent:
        print_error("Provide a search query or use --recent.")
        raise typer.Exit(1)

    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    if recent:
        order_by = "modifiedTime desc"
        q = "trashed = false"
    else:
        order_by = "modifiedTime desc"
        q = _build_query(query, type, in_folder, owner, after, before, shared, starred, trashed)

    fields = "files(id,name,mimeType,modifiedTime,size)"
    results = (
        service.files()
        .list(q=q, pageSize=count, orderBy=order_by, fields=fields)
        .execute()
    )
    files = results.get("files", [])

    if not files:
        print_error("No files found.")
        raise typer.Exit(0)

    rows = [file_row(f, json_mode) for f in files]
    print_table(rows, FILE_COLUMNS, json_mode)
