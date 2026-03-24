"""Main Typer app — registers top-level commands and subcommand groups."""

from __future__ import annotations

import typer

from scripts.gdrive_cli.about_cmd import app as about_app
from scripts.gdrive_cli.export_cmd import app as export_app
from scripts.gdrive_cli.file_cmds import cat as cat_fn
from scripts.gdrive_cli.file_cmds import download as download_fn
from scripts.gdrive_cli.file_cmds import info as info_fn
from scripts.gdrive_cli.file_cmds import upload as upload_fn
from scripts.gdrive_cli.files_cmd import app as files_app
from scripts.gdrive_cli.ls_cmd import folders_app
from scripts.gdrive_cli.ls_cmd import ls as ls_fn
from scripts.gdrive_cli.search_cmd import search as search_fn
from scripts.gdrive_cli.sharing_cmd import app as sharing_app

app = typer.Typer(
    rich_markup_mode="rich",
    help="[bold]Google Drive CLI[/bold] — agent-friendly Drive interaction tool.",
    no_args_is_help=True,
)

# Register top-level commands directly
app.command("ls")(ls_fn)
app.command("search")(search_fn)
app.command("info")(info_fn)
app.command("cat")(cat_fn)
app.command("download")(download_fn)
app.command("upload")(upload_fn)

# Subcommand groups
app.add_typer(files_app, name="files")
app.add_typer(folders_app, name="folders")
app.add_typer(sharing_app, name="sharing")
app.add_typer(export_app, name="export")
app.add_typer(about_app, name="about")

if __name__ == "__main__":
    app()
