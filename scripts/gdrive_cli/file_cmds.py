"""File read/metadata commands — info, cat, download, upload (top-level)."""

from __future__ import annotations

import io
import json as json_mod
import mimetypes
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import Progress

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    DEFAULT_EXPORT_FORMATS,
    console_out,
    friendly_mime,
    human_size,
    is_google_workspace_file,
    print_error,
    print_panel,
    should_use_json,
)


def info(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Display detailed file metadata."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    fields = "id,name,mimeType,size,createdTime,modifiedTime,owners,shared,parents,webViewLink,description"
    meta = service.files().get(fileId=file_id, fields=fields).execute()

    if json_mode:
        print(json_mod.dumps(meta))
    else:
        owners = ", ".join(
            o.get("emailAddress", o.get("displayName", "Unknown"))
            for o in meta.get("owners", [])
        )
        data = {
            "Name": meta.get("name", ""),
            "MIME Type": friendly_mime(meta.get("mimeType", "")),
            "Size": human_size(meta.get("size")),
            "Created": meta.get("createdTime", "")[:19].replace("T", " "),
            "Modified": meta.get("modifiedTime", "")[:19].replace("T", " "),
            "Owners": owners,
            "Shared": str(meta.get("shared", False)),
            "Parents": ", ".join(meta.get("parents", [])),
            "Web Link": meta.get("webViewLink", "—"),
            "Description": meta.get("description", "—"),
        }
        print_panel(data, meta.get("name", "File Info"), json_mode)


def cat(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Print file contents to stdout. Auto-exports Google Workspace files to plain text."""
    service = get_drive_service(token_path)

    meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime = meta.get("mimeType", "")

    if is_google_workspace_file(mime):
        # Export to plain text
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        if isinstance(content, bytes):
            print(content.decode("utf-8"))
        else:
            print(content)
    elif mime.startswith(("image/", "video/", "audio/", "application/zip")):
        print_error(f"Cannot display binary file ({friendly_mime(mime)}). Use `gdrive download` instead.")
        raise typer.Exit(1)
    else:
        # Download text content
        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        try:
            print(buf.read().decode("utf-8"))
        except UnicodeDecodeError:
            print_error("Binary file detected. Use `gdrive download` instead.")
            raise typer.Exit(1) from None


def download(
    file_id: Annotated[str, typer.Argument(help="File ID.")],
    output: Annotated[str | None, typer.Option("--output", "-o", help="Output path.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Download a file. Google Workspace files are auto-exported to default formats."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    meta = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    name = meta.get("name", "download")
    mime = meta.get("mimeType", "")
    total_size = int(meta.get("size", 0) or 0)

    if is_google_workspace_file(mime):
        # Export Google Workspace file
        export_mime, ext = DEFAULT_EXPORT_FORMATS.get(mime, ("application/pdf", ".pdf"))
        out_path = Path(output) if output else Path(name + ext)

        content = service.files().export(fileId=file_id, mimeType=export_mime).execute()
        out_path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

        result = {"file": str(out_path), "id": file_id, "exported_as": export_mime}
    else:
        # Direct download with progress
        from googleapiclient.http import MediaIoBaseDownload

        out_path = Path(output) if output else Path(name)
        request = service.files().get_media(fileId=file_id)

        with open(out_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            if not json_mode and total_size > 0:
                with Progress() as progress:
                    task = progress.add_task(f"Downloading {name}", total=total_size)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                        if status:
                            progress.update(task, completed=int(status.progress() * total_size))
                    progress.update(task, completed=total_size)
            else:
                done = False
                while not done:
                    _, done = downloader.next_chunk()

        result = {"file": str(out_path), "id": file_id, "size": total_size}

    if json_mode:
        print(json_mod.dumps(result))
    else:
        console_out.print(f"[green]Downloaded:[/green] {out_path}")


def upload(
    path: Annotated[str, typer.Argument(help="File path to upload.")],
    folder: Annotated[str | None, typer.Option("--folder", help="Destination folder ID.")] = None,
    name: Annotated[str | None, typer.Option("--name", help="Override file name.")] = None,
    description: Annotated[str | None, typer.Option("--description", help="File description.")] = None,
    convert: Annotated[bool, typer.Option("--convert", help="Convert to Google Workspace format.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Upload a file to Google Drive."""
    from googleapiclient.http import MediaFileUpload

    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    file_path = Path(path)
    if not file_path.exists():
        print_error(f"File not found: {path}")
        raise typer.Exit(1)

    file_name = name or file_path.name
    mime_type, _ = mimetypes.guess_type(str(file_path))

    metadata: dict = {"name": file_name}
    if folder:
        metadata["parents"] = [folder]
    if description:
        metadata["description"] = description

    media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)

    # If converting, set the appropriate Google MIME type
    if convert and mime_type:
        convert_map = {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "application/vnd.google-apps.document",
            "application/msword": "application/vnd.google-apps.document",
            "text/plain": "application/vnd.google-apps.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "application/vnd.google-apps.spreadsheet",
            "application/vnd.ms-excel": "application/vnd.google-apps.spreadsheet",
            "text/csv": "application/vnd.google-apps.spreadsheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": "application/vnd.google-apps.presentation",
            "application/vnd.ms-powerpoint": "application/vnd.google-apps.presentation",
        }
        if mime_type in convert_map:
            metadata["mimeType"] = convert_map[mime_type]

    if not json_mode:
        with Progress() as progress:
            task = progress.add_task(f"Uploading {file_name}", total=file_path.stat().st_size)
            response = None
            while response is None:
                status, response = (
                    service.files()
                    .create(body=metadata, media_body=media, fields="id,name,mimeType,size")
                    .next_chunk()
                )
                if status:
                    progress.update(task, completed=int(status.progress() * file_path.stat().st_size))
            progress.update(task, completed=file_path.stat().st_size)
    else:
        response = (
            service.files()
            .create(body=metadata, media_body=media, fields="id,name,mimeType,size")
            .execute()
        )

    if json_mode:
        print(json_mod.dumps(response))
    else:
        console_out.print(f"[green]Uploaded:[/green] {response['name']} (ID: {response['id']})")
