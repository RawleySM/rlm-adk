"""Main Typer app — registers all subcommand groups."""

from __future__ import annotations

import typer

from scripts.gmail_cli.drafts import app as drafts_app
from scripts.gmail_cli.inbox import app as inbox_app
from scripts.gmail_cli.labels import app as labels_app
from scripts.gmail_cli.search import app as search_app
from scripts.gmail_cli.send import app as send_app
from scripts.gmail_cli.threads import app as threads_app

app = typer.Typer(
    rich_markup_mode="rich",
    help="[bold]Gmail CLI[/bold] — agent-friendly Gmail interaction tool.",
    no_args_is_help=True,
)

app.add_typer(inbox_app, name="inbox")
app.add_typer(send_app, name="send")
app.add_typer(search_app, name="search")
app.add_typer(labels_app, name="labels")
app.add_typer(threads_app, name="threads")
app.add_typer(drafts_app, name="drafts")

if __name__ == "__main__":
    app()
