"""Consistent output formatting for all CLI commands.

- Rich tables for human-readable output (TTY)
- Newline-delimited JSON for machine/agent consumption (--json or piped)
- Errors to stderr, data to stdout
- --quiet suppresses non-data output
- File sizes: human-readable in table mode, raw bytes in JSON mode
- MIME types: friendly names in table mode, raw strings in JSON mode
"""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

# Shared consoles: stdout for data, stderr for messages
console_out = Console()
console_err = Console(stderr=True)

# MIME type shorthand → Google MIME type mapping
MIME_SHORTHANDS: dict[str, str] = {
    "doc": "application/vnd.google-apps.document",
    "sheet": "application/vnd.google-apps.spreadsheet",
    "slide": "application/vnd.google-apps.presentation",
    "pdf": "application/pdf",
    "image": "image/",
    "video": "video/",
    "audio": "audio/",
    "folder": "application/vnd.google-apps.folder",
    "zip": "application/zip",
    "drawing": "application/vnd.google-apps.drawing",
}

# Friendly MIME type names for table display
MIME_FRIENDLY: dict[str, str] = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.folder": "Folder",
    "application/vnd.google-apps.drawing": "Google Drawing",
    "application/vnd.google-apps.form": "Google Form",
    "application/vnd.google-apps.site": "Google Site",
    "application/pdf": "PDF",
    "application/zip": "ZIP Archive",
    "text/plain": "Text",
    "text/html": "HTML",
    "text/csv": "CSV",
    "image/jpeg": "JPEG Image",
    "image/png": "PNG Image",
    "image/gif": "GIF Image",
    "image/svg+xml": "SVG Image",
    "video/mp4": "MP4 Video",
    "audio/mpeg": "MP3 Audio",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word Doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel Sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
}

# Google Workspace export format mappings
EXPORT_FORMATS: dict[str, dict[str, str]] = {
    "application/vnd.google-apps.document": {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "html": "text/html",
        "epub": "application/epub+zip",
        "md": "text/html",  # export as HTML, convert to markdown
    },
    "application/vnd.google-apps.spreadsheet": {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
        "pdf": "application/pdf",
        "tsv": "text/tab-separated-values",
    },
    "application/vnd.google-apps.presentation": {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pdf": "application/pdf",
        "txt": "text/plain",
    },
    "application/vnd.google-apps.drawing": {
        "png": "image/png",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
    },
}

# Default export formats for Google Workspace files (download command)
DEFAULT_EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

# Format shorthand → file extension
FORMAT_EXTENSIONS: dict[str, str] = {
    "pdf": ".pdf",
    "docx": ".docx",
    "txt": ".txt",
    "html": ".html",
    "epub": ".epub",
    "md": ".md",
    "xlsx": ".xlsx",
    "csv": ".csv",
    "tsv": ".tsv",
    "pptx": ".pptx",
    "png": ".png",
    "svg": ".svg",
}


def should_use_json(json_flag: bool) -> bool:
    """Return True if output should be JSON (explicit flag or piped stdout)."""
    return json_flag or not sys.stdout.isatty()


def friendly_mime(mime_type: str) -> str:
    """Convert a MIME type string to a friendly display name."""
    if mime_type in MIME_FRIENDLY:
        return MIME_FRIENDLY[mime_type]
    # Generic fallback: image/png → PNG, video/mp4 → MP4, etc.
    if "/" in mime_type:
        return mime_type.split("/")[-1].upper()
    return mime_type


def human_size(size_bytes: int | str | None) -> str:
    """Convert bytes to human-readable size string."""
    if size_bytes is None or size_bytes == "":
        return "—"
    n = int(size_bytes)
    if n == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def resolve_mime_type(shorthand: str) -> str:
    """Resolve a MIME type shorthand to a full MIME type, or return as-is if not a shorthand."""
    return MIME_SHORTHANDS.get(shorthand, shorthand)


def is_google_workspace_file(mime_type: str) -> bool:
    """Check if a MIME type is a Google Workspace native file."""
    return mime_type.startswith("application/vnd.google-apps.")


def print_table(rows: list[dict], columns: list[tuple[str, str]], json_mode: bool) -> None:
    """Print rows as a Rich table or newline-delimited JSON."""
    if json_mode:
        for row in rows:
            print(json.dumps(row))
        return

    table = Table(show_header=True, header_style="bold cyan")
    for _, header in columns:
        table.add_column(header)

    for row in rows:
        table.add_row(*(str(row.get(key, "")) for key, _ in columns))

    console_out.print(table)


def print_panel(data: dict, title: str, json_mode: bool) -> None:
    """Print a dict as a Rich panel or JSON."""
    if json_mode:
        print(json.dumps(data))
        return

    lines = []
    for key, value in data.items():
        lines.append(f"[bold]{key}:[/bold] {value}")
    console_out.print(Panel("\n".join(lines), title=title, border_style="blue"))


def print_tree(tree: Tree) -> None:
    """Print a Rich Tree to stdout."""
    console_out.print(tree)


def print_json(data: dict | list) -> None:
    """Print a single JSON object or list to stdout."""
    print(json.dumps(data))


def print_error(msg: str) -> None:
    """Print error message to stderr."""
    console_err.print(f"[red]Error:[/red] {msg}")


def print_info(msg: str, quiet: bool = False) -> None:
    """Print info message to stderr (skipped in quiet mode)."""
    if not quiet:
        console_err.print(msg)


def file_row(f: dict, json_mode: bool) -> dict:
    """Normalize a Drive API file dict into a display row."""
    mime = f.get("mimeType", "")
    size = f.get("size")
    return {
        "name": f.get("name", ""),
        "type": mime if json_mode else friendly_mime(mime),
        "mimeType": mime,
        "size": size if json_mode else human_size(size),
        "modified": f.get("modifiedTime", "")[:16].replace("T", " "),
        "id": f.get("id", ""),
    }


FILE_COLUMNS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("type", "Type"),
    ("size", "Size"),
    ("modified", "Modified"),
    ("id", "ID"),
]
