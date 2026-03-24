"""Consistent output formatting for all CLI commands.

- Rich tables for human-readable output (TTY)
- Newline-delimited JSON for machine/agent consumption (--json or piped)
- Errors to stderr, data to stdout
- --quiet suppresses non-data output
"""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.table import Table

# Shared consoles: stdout for data, stderr for messages
console_out = Console()
console_err = Console(stderr=True)


def should_use_json(json_flag: bool) -> bool:
    """Return True if output should be JSON (explicit flag or piped stdout)."""
    return json_flag or not sys.stdout.isatty()


def print_table(rows: list[dict], columns: list[tuple[str, str]], json_mode: bool) -> None:
    """Print rows as a Rich table or newline-delimited JSON.

    Args:
        rows: List of dicts with data.
        columns: List of (key, header_label) tuples defining column order.
        json_mode: If True, output NDJSON instead of table.
    """
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
