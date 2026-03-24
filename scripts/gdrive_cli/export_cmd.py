"""Export subgroup — export Google Workspace files to various formats."""

from __future__ import annotations

import json as json_mod
from pathlib import Path
from typing import Annotated

import typer

from scripts.gdrive_cli.auth import get_drive_service
from scripts.gdrive_cli.formatting import (
    EXPORT_FORMATS,
    FORMAT_EXTENSIONS,
    console_out,
    is_google_workspace_file,
    print_error,
    print_table,
    should_use_json,
)

app = typer.Typer(help="Export — convert Google Workspace files to other formats.")


@app.command("file")
def export_file(
    file_id: Annotated[str, typer.Argument(help="File ID to export.")],
    format: Annotated[str, typer.Argument(help="Target format: pdf, docx, txt, html, epub, md, xlsx, csv, tsv, pptx, png, svg.")],
    output: Annotated[str | None, typer.Option("--output", "-o", help="Output path.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    token_path: Annotated[
        str | None, typer.Option("--token-path", help="Path to token.json.")
    ] = None,
) -> None:
    """Export a Google Workspace file to a specific format."""
    json_mode = should_use_json(json_output)
    service = get_drive_service(token_path)

    meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    mime = meta.get("mimeType", "")
    name = meta.get("name", "export")

    if not is_google_workspace_file(mime):
        print_error(f"File is not a Google Workspace file (type: {mime}). Use `gdrive download` instead.")
        raise typer.Exit(1)

    format_map = EXPORT_FORMATS.get(mime, {})
    if format not in format_map:
        supported = ", ".join(format_map.keys()) if format_map else "none"
        print_error(f"Unsupported format '{format}' for this file type. Supported: {supported}")
        raise typer.Exit(1)

    export_mime = format_map[format]
    ext = FORMAT_EXTENSIONS.get(format, f".{format}")
    out_path = Path(output) if output else Path(name + ext)

    content = service.files().export(fileId=file_id, mimeType=export_mime).execute()

    # Special handling for markdown: export as HTML then strip tags
    if format == "md" and isinstance(content, bytes):
        import re

        html = content.decode("utf-8")
        # Simple HTML to markdown conversion (strip tags, preserve structure)
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", lambda m: "#" * int(m.group(1)) + " " + m.group(2), text)
        text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
        text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text)
        text = re.sub(r"<i>(.*?)</i>", r"*\1*", text)
        text = re.sub(r"<em>(.*?)</em>", r"*\1*", text)
        text = re.sub(r"<[^>]+>", "", text)
        out_path.write_text(text, encoding="utf-8")
    else:
        out_path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))

    result = {"file": str(out_path), "id": file_id, "format": format}
    if json_mode:
        print(json_mod.dumps(result))
    else:
        console_out.print(f"[green]Exported:[/green] {out_path}")


@app.command("formats")
def export_formats(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """List all supported export format mappings."""
    json_mode = should_use_json(json_output)

    if json_mode:
        print(json_mod.dumps(EXPORT_FORMATS))
        return

    rows = []
    for source_mime, formats in EXPORT_FORMATS.items():
        from scripts.gdrive_cli.formatting import friendly_mime

        source_name = friendly_mime(source_mime)
        for fmt, target_mime in formats.items():
            rows.append({
                "source": source_name,
                "format": fmt,
                "mime": target_mime,
            })

    columns = [
        ("source", "Source Type"),
        ("format", "Format"),
        ("mime", "Export MIME Type"),
    ]
    print_table(rows, columns, json_mode)
