"""List command — top-level ls and folders subgroup."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.tree import Tree

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    FILE_COLUMNS,
    file_row,
    print_error,
    print_table,
    print_tree,
    should_use_json,
)

folders_app = typer.Typer(help="Folder operations — list, create, tree.")


def _list_folder(service, folder_id: str, fields: str, order_by: str) -> list[dict]:
    """List contents of a folder via Drive API."""
    q = f"'{folder_id}' in parents and trashed = false"
    results = (
        service.files()
        .list(q=q, pageSize=1000, orderBy=order_by, fields=fields)
        .execute()
    )
    return results.get("files", [])


def _sort_folders_first(files: list[dict]) -> list[dict]:
    """Sort files: folders first, then by name."""
    folders = [f for f in files if f.get("mimeType") == "application/vnd.google-apps.folder"]
    non_folders = [f for f in files if f.get("mimeType") != "application/vnd.google-apps.folder"]
    folders.sort(key=lambda x: x.get("name", "").lower())
    non_folders.sort(key=lambda x: x.get("name", "").lower())
    return folders + non_folders


def ls(
    folder_id: Annotated[str | None, typer.Argument(help="Folder ID (default: root).")] = None,
    recursive: Annotated[bool, typer.Option("--recursive", "-r", help="Recursive listing.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """List contents of a Drive folder."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)
    target = folder_id or "root"
    fields = "files(id,name,mimeType,modifiedTime,size)"

    if recursive:
        _ls_recursive(service, target, fields, json_mode)
    else:
        files = _list_folder(service, target, fields, "folder,name")
        files = _sort_folders_first(files)
        if not files:
            print_error("Folder is empty.")
            raise typer.Exit(0)
        rows = [file_row(f, json_mode) for f in files]
        print_table(rows, FILE_COLUMNS, json_mode)


def _ls_recursive(service, folder_id: str, fields: str, json_mode: bool) -> None:
    """BFS recursive listing with indented display."""
    import json as json_mod
    from collections import deque

    all_rows: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(folder_id, 0)])

    while queue:
        fid, depth = queue.popleft()
        files = _list_folder(service, fid, fields, "folder,name")
        files = _sort_folders_first(files)
        for f in files:
            row = file_row(f, json_mode)
            row["depth"] = depth
            if not json_mode:
                row["name"] = "  " * depth + row["name"]
            all_rows.append(row)
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                queue.append((f["id"], depth + 1))

    if json_mode:
        for row in all_rows:
            print(json_mod.dumps(row))
    else:
        print_table(all_rows, FILE_COLUMNS, json_mode=False)


# ─── folders subgroup ───


@folders_app.command("list")
def folders_list(
    parent_id: Annotated[str | None, typer.Argument(help="Parent folder ID.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """List only folders inside a parent folder."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)
    target = parent_id or "root"
    q = f"'{target}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    fields = "files(id,name,mimeType,modifiedTime,size)"
    results = service.files().list(q=q, pageSize=1000, orderBy="name", fields=fields).execute()
    files = results.get("files", [])

    if not files:
        print_error("No folders found.")
        raise typer.Exit(0)

    rows = [file_row(f, json_mode) for f in files]
    print_table(rows, FILE_COLUMNS, json_mode)


@folders_app.command("create")
def folders_create(
    name: Annotated[str, typer.Argument(help="Folder name.")],
    parent: Annotated[str | None, typer.Option("--parent", help="Parent folder ID.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Create a new folder."""
    import json as json_mod

    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent:
        metadata["parents"] = [parent]

    folder = service.files().create(body=metadata, fields="id,name,mimeType,modifiedTime").execute()

    if json_mode:
        print(json_mod.dumps(folder))
    else:
        from scripts.gdrive_cli.formatting import console_out

        console_out.print(f"[green]Created folder:[/green] {folder['name']} (ID: {folder['id']})")


@folders_app.command("tree")
def folders_tree(
    folder_id: Annotated[str | None, typer.Argument(help="Root folder ID.")] = None,
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max depth.")] = 3,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Display folder structure as a tree."""
    import json as json_mod

    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)
    target = folder_id or "root"

    if json_mode:
        tree_data = _build_tree_json(service, target, depth, 0)
        print(json_mod.dumps(tree_data))
    else:
        # Get folder name
        if target == "root":
            label = "My Drive"
        else:
            meta = service.files().get(fileId=target, fields="name").execute()
            label = meta.get("name", target)

        tree = Tree(f"[bold blue]{label}[/bold blue]")
        _build_tree_rich(service, target, tree, depth, 0)
        print_tree(tree)


def _build_tree_rich(service, folder_id: str, tree: Tree, max_depth: int, current: int) -> None:
    """Recursively build a Rich Tree."""
    if current >= max_depth:
        return

    q = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=q, pageSize=1000, orderBy="name", fields="files(id,name)").execute()

    for f in results.get("files", []):
        branch = tree.add(f"[blue]{f['name']}[/blue]")
        _build_tree_rich(service, f["id"], branch, max_depth, current + 1)


def _build_tree_json(service, folder_id: str, max_depth: int, current: int) -> dict:
    """Recursively build a JSON tree structure."""
    if folder_id == "root":
        name = "My Drive"
    else:
        meta = service.files().get(fileId=folder_id, fields="name").execute()
        name = meta.get("name", folder_id)

    node: dict = {"id": folder_id, "name": name, "children": []}

    if current >= max_depth:
        return node

    q = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=q, pageSize=1000, orderBy="name", fields="files(id,name)").execute()

    for f in results.get("files", []):
        child = _build_tree_json(service, f["id"], max_depth, current + 1)
        node["children"].append(child)

    return node
