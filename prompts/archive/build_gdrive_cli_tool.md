<!-- generated: 2026-03-21 -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- classification: UPDATE -->
# Build a Typer CLI for Google Drive Agent Interaction

## Context

The project has four standalone Gmail/YouTube scripts (`scripts/send_followup.py`, `scripts/send_love_poem.py`, `scripts/test_gmail_pull.py`, `scripts/test_youtube_search.py`) that share an OAuth `token.json` credential-loading pattern. The existing `token.json` already has full Google Drive scopes (`drive` + `drive.activity`). Build a Typer-based CLI tool at `scripts/gdrive_cli/` that reuses this auth layer and exposes a comprehensive, progressively-disclosed command set for an agent (or human) to interact with Google Drive — list, search, download, upload, move, share, export, and manage folders. Search must be a frictionless first-class operation because the user's Drive is not well-organized and contains many file types.

## Original Transcription

> Voice to prompt Memo to follow. Please generate a CLI tool using Typer for empowering an agent to interact with my Google Drive. This tool will be exclusively built around the token JSON file in my working directory in a pattern that has been proven through the Gmail scripts in the scripts folder. This token should have all the Google Drive permissions scoped to it, If not, please rectify that. Before building the script. For the CLI tool. Maximize the things the CLI do, with progressive disclosure in mind. The CLI tool should have a rich set of commands listed in the help menu that the agent can use for navigation to the correct command Assume that I will store many different types of files in my Google Drive. And that the the Organization. Is not currently optimized. Therefore, search will need to be a frictionless utility of the CLI.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn an `Auth-Layer` teammate to create a shared auth module at `scripts/gdrive_cli/auth.py`.**
   - Extract the duplicated `get_*_service()` / `token.json` loading pattern from the existing scripts (`scripts/send_followup.py:19-28`, `scripts/test_gmail_pull.py:16-27`, `scripts/test_youtube_search.py:16-20`)
   - Single function: `get_drive_service(token_path: str = "token.json") -> Resource` that loads `token.json`, auto-refreshes expired credentials, and returns a built Drive v3 service
   - Default scopes: `['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/drive.activity']` (both are already in `token.json` — verified)
   - If `token.json` is missing or invalid, print a clear error directing the user to run `python scripts/setup_rlm_agent_auth.py`
   - Add `scripts/gdrive_cli/__init__.py` and `scripts/gdrive_cli/__main__.py` (for `python -m scripts.gdrive_cli` invocation)

2. **Spawn a `CLI-Scaffold` teammate to create the Typer app at `scripts/gdrive_cli/cli.py`.**
   - Create a top-level Typer app with Rich markup enabled (`typer.Typer(rich_markup_mode="rich")`)
   - Register top-level convenience commands: `ls`, `search`, `info`, `cat`, `download`, `upload`
   - Register subcommand groups: `files`, `folders`, `sharing`, `export`, `about`
   - Wire the `__main__.py` entry to call `app()`
   - Add global options: `--token-path` (default: `token.json`), `--json` (machine-readable output)
   - Auto-detect TTY: when stdout is not a TTY (piped), default to JSON output
   - Add `typer>=0.21.0`, `google-api-python-client>=2.0.0`, and `google-auth-oauthlib>=1.0.0` to `pyproject.toml` dependencies (line ~20-38)
   - *[Added — Typer and google-api-python-client are available transitively but should be explicit since this CLI depends on them directly.]*

3. **Spawn a `Search-Commands` teammate to implement search as a first-class top-level command.**
   Search is the highest-priority command because the user's Drive is disorganized. It must be frictionless.
   - `gdrive search QUERY` — Full-text search across all Drive files using the Drive API `files().list(q=...)` with `fullText contains` query. Output: Rich table with columns [Name, Type, Size, Modified, ID]. Default 25 results.
   - `gdrive search QUERY --type TYPE` — Filter by MIME type shorthand: `doc`, `sheet`, `slide`, `pdf`, `image`, `video`, `audio`, `folder`, `zip`, or raw MIME type. Map shorthands to Google MIME types (e.g., `doc` → `application/vnd.google-apps.document`)
   - `gdrive search QUERY --in FOLDER_ID` — Scope search to a specific folder (uses `'FOLDER_ID' in parents`)
   - `gdrive search QUERY --owner EMAIL` — Filter by owner
   - `gdrive search QUERY --after DATE --before DATE` — Date range filtering (`modifiedTime > 'DATE'`)
   - `gdrive search QUERY --shared` — Only files shared with the user (not owned)
   - `gdrive search QUERY --starred` — Only starred files
   - `gdrive search QUERY --trashed` — Search trash
   - `gdrive search QUERY --count N` — Limit results (default 25)
   - `gdrive search QUERY --json` — Machine-readable output (one JSON object per line)
   - `gdrive search --recent` — Shortcut: list 25 most recently modified files (no query needed)
   - All search flags are composable (e.g., `--type pdf --after 2026-01-01 --in FOLDER_ID`)

4. **Spawn a `List-Commands` teammate to implement the `ls` top-level command and `folders` subgroup.**
   - `gdrive ls [FOLDER_ID]` — List contents of a folder (default: root `'root'`). Output: Rich table [Name, Type, Size, Modified, ID]. Folders listed first, then files, sorted by name.
   - `gdrive ls FOLDER_ID --recursive` — Recursive listing (BFS traversal, indented display)
   - `gdrive ls --json` — Machine-readable output
   - `gdrive folders list [PARENT_ID]` — Same as `ls` but only shows folders
   - `gdrive folders create NAME [--parent FOLDER_ID]` — Create a new folder
   - `gdrive folders tree [FOLDER_ID]` — Display folder structure as an ASCII tree (Rich `Tree` widget). Default depth 3, `--depth N` to override.
   - *[Added — `folders tree` is critical for understanding disorganized Drives. An agent can use this to map the folder hierarchy before deciding where to put files.]*

5. **Spawn a `File-Commands` teammate to implement file read/metadata commands.**
   - `gdrive info FILE_ID` — Display detailed file metadata: name, MIME type, size, created, modified, owners, shared, parents, web link, description. Rich panel for humans, flat JSON for `--json`.
   - `gdrive cat FILE_ID` — Print file contents to stdout. For Google Workspace files (Docs, Sheets, Slides), auto-export to plain text. For binary files, print an error suggesting `gdrive download` instead.
   - `gdrive download FILE_ID [--output PATH]` — Download a file. Default output: current directory with original filename. For Google Workspace files, prompt for export format or use sensible defaults (Docs→docx, Sheets→xlsx, Slides→pptx). Show progress bar via Rich.
   - `gdrive upload PATH [--folder FOLDER_ID] [--name NAME] [--description TEXT]` — Upload a file. Auto-detect MIME type. Show progress bar. Print the new file ID on success.
   - `gdrive upload PATH --convert` — Upload and convert to Google Workspace format (e.g., .docx → Google Doc, .xlsx → Google Sheet)

6. **Spawn a `File-Management` teammate to implement move/copy/rename/trash operations in the `files` subgroup.**
   - `gdrive files move FILE_ID DEST_FOLDER_ID` — Move a file to a different folder (update parents)
   - `gdrive files copy FILE_ID [--name NEW_NAME] [--folder DEST_FOLDER_ID]` — Copy a file
   - `gdrive files rename FILE_ID NEW_NAME` — Rename a file
   - `gdrive files trash FILE_ID` — Move to trash (soft delete)
   - `gdrive files untrash FILE_ID` — Restore from trash
   - `gdrive files delete FILE_ID --yes` — Permanently delete (requires `--yes` confirmation flag, no interactive prompt so agents can use it)
   - `gdrive files list-trashed` — List all files in trash
   - All commands print the updated file metadata on success

7. **Spawn a `Sharing-Commands` teammate to implement the `sharing` subgroup.**
   - `gdrive sharing list FILE_ID` — List all permissions on a file (who has access, what role). Rich table [Email, Role, Type].
   - `gdrive sharing add FILE_ID EMAIL --role ROLE` — Share a file. Roles: `reader`, `commenter`, `writer`, `organizer`. Default: `reader`.
   - `gdrive sharing remove FILE_ID PERMISSION_ID` — Remove a permission
   - `gdrive sharing link FILE_ID --anyone [--role ROLE]` — Create/update "anyone with link" sharing. Default role: `reader`.
   - `gdrive sharing link FILE_ID --off` — Disable link sharing

8. **Spawn an `Export-Commands` teammate to implement the `export` subgroup.**
   - `gdrive export FILE_ID FORMAT` — Export a Google Workspace file to a specific format. Supported formats:
     - Google Docs: `pdf`, `docx`, `txt`, `html`, `epub`, `md` (markdown via html→md)
     - Google Sheets: `xlsx`, `csv`, `pdf`, `tsv`
     - Google Slides: `pptx`, `pdf`, `txt`
     - Google Drawings: `png`, `svg`, `pdf`
   - `gdrive export FILE_ID FORMAT --output PATH` — Export to specific path
   - `gdrive export --formats` — List all supported export format mappings
   - *[Added — export is important because the user stores many file types and will need to convert between formats for different workflows.]*

9. **Spawn an `About-Commands` teammate to implement the `about` subgroup.**
   - `gdrive about` — Show Drive account info: user email, storage quota (used/total), file count
   - `gdrive about quota` — Detailed quota breakdown by file type (uses `about().get(fields='storageQuota')`)
   - *[Added — useful for an agent to check remaining storage before uploads.]*

10. **Spawn an `Output-Format` teammate to add consistent output formatting across all commands.**
    - Create `scripts/gdrive_cli/formatting.py` with shared output helpers
    - All list/table commands default to Rich tables for human readability
    - All list/table commands support `--json` flag that outputs newline-delimited JSON (one object per line) for agent parsing
    - Error messages go to stderr (`typer.echo(..., err=True)`), data goes to stdout (so agents can pipe output cleanly)
    - File sizes displayed human-readable (KB/MB/GB) in table mode, raw bytes in JSON mode
    - MIME types displayed as friendly names in table mode (e.g., `Google Doc`, `PDF`, `JPEG Image`), raw MIME strings in JSON mode
    - `--quiet` flag suppresses all non-data output

## Provider-Fake Fixture & TDD

This is a standalone CLI tool outside the ADK agent loop, so provider-fake fixtures are not applicable. Instead:

**Unit test approach:** `tests_rlm_adk/test_gdrive_cli.py`

**TDD sequence:**
1. Red: Test that `auth.get_drive_service()` raises a clear error when `token.json` is missing. Run, confirm failure.
2. Green: Implement the auth module with proper error handling. Run, confirm pass.
3. Red: Test that `gdrive search "test" --json` outputs valid JSON with expected keys (`id`, `name`, `mimeType`, `modifiedTime`, `size`). Mock the Drive API service.
4. Green: Implement search command with JSON output. Run, confirm pass.
5. Red: Test that `gdrive ls --json` returns folder contents with correct structure. Mock the API.
6. Green: Implement ls command. Run, confirm pass.
7. Red: Test that `gdrive upload PATH` constructs correct `MediaFileUpload` and calls `files().create()`. Mock the API.
8. Green: Implement upload command. Run, confirm pass.
9. Red: Test that `gdrive download FILE_ID` calls `files().get_media()` and writes to disk. Mock the API.
10. Green: Implement download command. Run, confirm pass.
11. Continue for info, cat, files management, sharing, export, about.
12. Red: Test MIME type shorthand mapping (`doc` → `application/vnd.google-apps.document`, etc.)
13. Green: Implement shorthand lookup table.

**Demo:** Run `uvx showboat` to generate an executable demo document showing each subcommand in action (with mocked API responses).

## Considerations

- **Token location:** The existing scripts assume `token.json` is in the current working directory. The CLI should look for it via a `--token-path` global option (default: `token.json`), searching the project root first. This matches the existing pattern in `scripts/test_gmail_pull.py:8`.
- **Token scopes verified:** The existing `token.json` already contains `https://www.googleapis.com/auth/drive` and `https://www.googleapis.com/auth/drive.activity`. No re-auth needed.
- **Agent ergonomics:** The `--json` and `--quiet` flags are critical. An agent calling this CLI needs parseable output, not Rich tables. Auto-detect TTY: when stdout is not a TTY, default to JSON output so piped usage Just Works.
- **Progressive disclosure:** Top-level commands (`ls`, `search`, `info`, `cat`, `download`, `upload`) cover 80% of use cases. Subgroups (`files`, `folders`, `sharing`, `export`, `about`) expose deeper operations. The help menu becomes the agent's discovery mechanism.
- **Rate limits:** Drive API has per-user rate limits (1000 queries/100 seconds). The CLI does not need retry logic initially, but error messages should clearly indicate rate limit errors (HTTP 403 with `rateLimitExceeded` reason) so the calling agent can back off.
- **Large file handling:** Use `MediaIoBaseDownload` with chunked downloads for large files. Use `MediaFileUpload` with resumable uploads. Show Rich progress bars for both.
- **Google Workspace MIME types:** The CLI must handle the distinction between Google-native files (Docs, Sheets, Slides — no direct download, must export) and binary files (PDFs, images, etc. — direct download). The `cat` and `download` commands must detect this automatically.
- **No ADK state mutation involved** — this is a standalone CLI tool, so AR-CRIT-001 does not apply.
- **Existing scripts:** After the CLI is working, the existing Gmail scripts remain separate. A future task could build a similar `gmail_cli/` tool following this same pattern (note: `scripts/gmail_cli/` may already exist from the Gmail CLI prompt).
- **Dependencies:** `typer`, `google-api-python-client`, and `google-auth-oauthlib` are all already installed in the venv but should be declared as explicit dependencies in `pyproject.toml` since this CLI imports them directly.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `scripts/setup_rlm_agent_auth.py` | `SCOPES`, `main()` | L8-34, L36-68 | Master OAuth scope list (includes Drive scopes) and token bootstrap flow |
| `scripts/send_followup.py` | `get_gmail_service()` | L19-28 | Auth pattern to replicate for Drive service |
| `scripts/test_gmail_pull.py` | `get_gmail_service()`, `TOKEN_PATH` | L8, L16-27 | Auth pattern with TOKEN_PATH constant |
| `scripts/test_youtube_search.py` | `get_creds()` | L16-20 | Minimal auth pattern variant |
| `token.json` | OAuth credentials | — | Already has `drive` + `drive.activity` scopes (verified) |
| `client_secret.json` | OAuth client config | — | Used by `setup_rlm_agent_auth.py` if re-auth needed |
| `pyproject.toml` | `dependencies` | L20 | Where to add typer, google-api-python-client, google-auth-oauthlib |

## Priming References

Before starting implementation, read these in order:
1. All four existing scripts listed in the appendix — they establish the auth pattern and Google API usage
2. [Typer documentation](https://typer.tiangolo.com/) — subcommand groups, Rich integration, testing with `CliRunner`
3. [Google Drive API v3 reference](https://developers.google.com/drive/api/reference/rest/v3) — `files.list`, `files.get`, `files.create`, `files.update`, `files.copy`, `files.delete`, `files.export`, `permissions.*`, `about.get`
4. [Google Drive API MIME types](https://developers.google.com/drive/api/guides/mime-types) — Google Workspace MIME type mappings for export
