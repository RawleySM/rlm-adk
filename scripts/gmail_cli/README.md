# Gmail CLI

Typer-based CLI for agent/human Gmail interaction. Consolidates the OAuth auth layer from the standalone Gmail scripts into a single tool with rich subcommands.

## Quick Start

```bash
# Ensure token.json exists (run once)
python scripts/setup_rlm_agent_auth.py

# Run the CLI
python -m scripts.gmail_cli --help
```

## Authentication

The CLI loads OAuth credentials from `token.json`, searching in order:

1. Current working directory (`./token.json`)
2. `~/.config/rlm-adk/token.json`

Override with `--token-path`:

```bash
python -m scripts.gmail_cli inbox list --token-path /path/to/token.json
```

If `token.json` is missing or credentials are expired beyond refresh, the CLI prints a clear error directing you to run `setup_rlm_agent_auth.py`.

## Commands

### inbox — Read and browse

```bash
gmail inbox list                    # Last 10 primary inbox messages
gmail inbox list --count 25         # Last 25
gmail inbox read MSG_ID             # Full message body
gmail inbox unread                  # Unread messages only
```

### send — Compose and send

```bash
gmail send email --to a@b.com --subject "Hi" --body "Hello"
gmail send email --to a@b.com --subject "Hi" --body-file msg.txt
gmail send email --to a@b.com --subject "Hi" --body "Hello" --cc c@d.com --bcc e@f.com
gmail send email --to a@b.com --subject "Hi" --body "Hello" --yes  # skip confirmation
```

### search — Full Gmail query syntax

```bash
gmail search query "from:alice subject:report after:2026/03/01"
gmail search query "is:starred" --count 5
```

### labels — Label management

```bash
gmail labels list                   # All labels with message counts
gmail labels add MSG_ID "MyLabel"   # Add label to message
gmail labels remove MSG_ID INBOX    # Remove label
gmail labels create "Projects/New"  # Create new label
```

### threads — Thread operations

```bash
gmail threads list                  # Recent threads
gmail threads read THREAD_ID       # Full conversation
gmail threads reply THREAD_ID --body "Thanks!"  # Reply with correct threading headers
```

### drafts — Draft management

```bash
gmail drafts list
gmail drafts create --to a@b.com --subject "Draft" --body "WIP"
gmail drafts send DRAFT_ID
gmail drafts delete DRAFT_ID
```

## Agent Ergonomics

All list/read commands support `--json` for machine-readable output (newline-delimited JSON, one object per line):

```bash
gmail inbox list --json | jq '.subject'
```

When stdout is piped (not a TTY), `--json` is automatically enabled.

Additional flags:
- `--quiet` / `-q` — suppress non-data output (info messages go to stderr)
- `--yes` / `-y` — skip confirmation prompts (send, reply, delete commands)

Errors always go to stderr; data always goes to stdout.

## Architecture

```
scripts/gmail_cli/
├── __init__.py     # Package marker
├── __main__.py     # Entry: python -m scripts.gmail_cli
├── cli.py          # Top-level Typer app, registers 6 subcommand groups
├── auth.py         # get_gmail_service() — shared OAuth, token search, auto-refresh
├── output.py       # print_table(), print_json(), should_use_json() — Rich/NDJSON formatting
├── inbox.py        # inbox list/read/unread commands
├── send.py         # send email command
├── search.py       # search query command
├── labels.py       # labels list/add/remove/create commands
├── threads.py      # threads list/read/reply commands
└── drafts.py       # drafts list/create/send/delete commands
```

**Auth layer** (`auth.py`): Single `get_gmail_service()` function replaces the duplicated pattern across `send_followup.py`, `send_love_poem.py`, and `test_gmail_pull.py`. Uses the full scope list from `setup_rlm_agent_auth.py`.

**Output layer** (`output.py`): All commands route through shared formatting functions. `print_table()` renders Rich tables in TTY mode or NDJSON when `--json` is set or stdout is piped. Info/error messages use `Console(stderr=True)`.

**Command modules**: Each module defines its own `typer.Typer()` app, registered in `cli.py` via `add_typer()`. Auth is lazily imported inside each command function to allow clean mocking in tests.

## Testing

```bash
# Run all 20 Gmail CLI tests
.venv/bin/python -m pytest tests_rlm_adk/test_gmail_cli.py -x -q -m "unit_nondefault"
```

Tests use `unittest.mock.patch` on `scripts.gmail_cli.auth.get_gmail_service` with `MagicMock` Gmail API services. No network access required.

## Dependencies

Declared in `pyproject.toml`:
- `typer>=0.21.0`
- `google-api-python-client>=2.0.0`
- `google-auth-oauthlib>=1.0.0`
- `rich>=13.0.0` (pre-existing)
