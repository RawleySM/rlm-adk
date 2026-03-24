# Google Drive CLI

Agent-friendly Typer CLI for interacting with Google Drive. Designed for progressive disclosure: top-level commands cover 80% of use cases, subgroups expose deeper operations.

## Quick Start

```bash
# Run via module
python -m scripts.gdrive_cli --help

# Search (first-class, frictionless)
python -m scripts.gdrive_cli search "quarterly report"
python -m scripts.gdrive_cli search "budget" --type sheet --after 2026-01-01

# List files
python -m scripts.gdrive_cli ls
python -m scripts.gdrive_cli ls FOLDER_ID --recursive

# File operations
python -m scripts.gdrive_cli info FILE_ID
python -m scripts.gdrive_cli cat FILE_ID
python -m scripts.gdrive_cli download FILE_ID -o ./local.pdf
python -m scripts.gdrive_cli upload ./report.docx --folder FOLDER_ID
```

## Authentication

Uses `token.json` (OAuth credentials) searched in this order:

1. `--token-path` option (if provided)
2. `./token.json` (current working directory)
3. `~/.config/rlm-adk/token.json`

Required scopes: `drive`, `drive.activity` (already present in the project's `token.json`).

If credentials are missing or expired, the CLI prints a clear error directing you to run `python scripts/setup_rlm_agent_auth.py`.

## Command Reference

### Top-Level Commands

| Command | Description |
|---------|-------------|
| `search QUERY` | Full-text search with composable filters |
| `ls [FOLDER_ID]` | List folder contents (folders first, sorted by name) |
| `info FILE_ID` | Detailed file metadata panel |
| `cat FILE_ID` | Print file contents (auto-exports Workspace files to text) |
| `download FILE_ID` | Download with progress bar (auto-exports Workspace files) |
| `upload PATH` | Upload with progress bar and optional `--convert` |

### Search Filters (all composable)

```
--type TYPE        doc, sheet, slide, pdf, image, video, audio, folder, zip, or raw MIME
--in FOLDER_ID     Scope to folder
--owner EMAIL      Filter by owner
--after DATE       Modified after (YYYY-MM-DD)
--before DATE      Modified before (YYYY-MM-DD)
--shared           Only files shared with you
--starred          Only starred files
--trashed          Search trash
--recent           List 25 most recently modified (no query needed)
--count N          Max results (default 25)
```

### Subgroups

**`files`** — File management

| Command | Description |
|---------|-------------|
| `files move FILE_ID DEST_FOLDER_ID` | Move file |
| `files copy FILE_ID` | Copy (`--name`, `--folder`) |
| `files rename FILE_ID NEW_NAME` | Rename |
| `files trash FILE_ID` | Soft delete |
| `files untrash FILE_ID` | Restore from trash |
| `files delete FILE_ID --yes` | Permanent delete (requires `--yes`) |
| `files list-trashed` | List trashed files |

**`folders`** — Folder operations

| Command | Description |
|---------|-------------|
| `folders list [PARENT_ID]` | List subfolders |
| `folders create NAME` | Create folder (`--parent`) |
| `folders tree [FOLDER_ID]` | ASCII tree view (`--depth N`, default 3) |

**`sharing`** — Permission management

| Command | Description |
|---------|-------------|
| `sharing list FILE_ID` | List permissions |
| `sharing add FILE_ID EMAIL` | Share (`--role reader\|commenter\|writer\|organizer`) |
| `sharing remove FILE_ID PERM_ID` | Remove permission |
| `sharing link FILE_ID --anyone` | Enable link sharing (`--role`, `--off` to disable) |

**`export`** — Google Workspace file conversion

| Command | Description |
|---------|-------------|
| `export file FILE_ID FORMAT` | Export to format (`-o` for output path) |
| `export formats` | List all supported format mappings |

Supported formats: Docs → pdf/docx/txt/html/epub/md, Sheets → xlsx/csv/pdf/tsv, Slides → pptx/pdf/txt, Drawings → png/svg/pdf.

**`about`** — Account info

| Command | Description |
|---------|-------------|
| `about` | User email, storage quota |
| `about quota` | Detailed quota breakdown |

## Agent Ergonomics

- **`--json`** on every command: outputs newline-delimited JSON (one object per line)
- **Auto-TTY detection**: when stdout is piped (not a TTY), defaults to JSON output
- **Errors to stderr**, data to stdout — agents can pipe output cleanly
- **`--token-path`** on every command for explicit credential location
- File sizes: human-readable in table mode (`50.0 KB`), raw bytes in JSON mode
- MIME types: friendly names in table mode (`Google Doc`), raw strings in JSON mode

## Architecture

```
scripts/gdrive_cli/
├── __init__.py        # Package marker
├── __main__.py        # Entry point (python -m scripts.gdrive_cli)
├── cli.py             # Main Typer app — registers all commands/subgroups
├── auth.py            # OAuth token loading, auto-refresh, Drive v3 service builder
├── formatting.py      # Shared output: tables, JSON, MIME maps, size formatting
├── search_cmd.py      # search() — query builder, composable filters
├── ls_cmd.py          # ls() + folders subgroup (list, create, tree)
├── file_cmds.py       # info(), cat(), download(), upload() — top-level commands
├── files_cmd.py       # files subgroup — move, copy, rename, trash, delete
├── sharing_cmd.py     # sharing subgroup — permissions, link sharing
├── export_cmd.py      # export subgroup — Workspace file conversion
└── about_cmd.py       # about subgroup — account info, quota
```

**Pattern**: Top-level commands (`search`, `ls`, `info`, `cat`, `download`, `upload`) are registered as `app.command()` on the main Typer app. Subgroups (`files`, `folders`, `sharing`, `export`, `about`) use `app.add_typer()` for nested command trees.

**Auth flow**: `auth.py` mirrors the pattern from `scripts/send_followup.py` and `scripts/test_gmail_pull.py` — load `Credentials` from `token.json`, auto-refresh if expired, build service via `googleapiclient.discovery.build()`.

## Tests

```bash
# Run all 31 gdrive_cli tests
.venv/bin/python -m pytest tests_rlm_adk/test_gdrive_cli.py -x -q -o 'addopts='
```

Tests mock the Drive API service and use Typer's `CliRunner` for CLI invocation. Coverage: formatting helpers, auth error handling, search/ls/info/upload/download/files commands, MIME shorthand resolution.
