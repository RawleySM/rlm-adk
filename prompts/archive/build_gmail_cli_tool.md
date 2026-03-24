<!-- generated: 2026-03-21 -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- classification: UPDATE -->
# Build a Typer CLI for Gmail Agent Interaction

## Context

The project has four standalone Gmail scripts (`scripts/send_followup.py`, `scripts/send_love_poem.py`, `scripts/test_gmail_pull.py`, `scripts/setup_rlm_agent_auth.py`) that each duplicate the same `token.json` OAuth credential-loading pattern. Build a single Typer-based CLI tool that consolidates the auth layer and exposes a rich command set for an agent (or human) to interact with Gmail programmatically — read, send, search, label, thread, and manage drafts — all through clean subcommands.

## Original Transcription

> Please build a CLI tool that utilizes the token dot JSON pattern established with the email or I should say gmail scripts and utilizes Typer. With a rich set of commands for empowering an agent to interact with my Gmail account. Through the CLI.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn an `Auth-Layer` teammate to create a shared auth module at `scripts/gmail_cli/auth.py`.**
   - Extract the duplicated `get_gmail_service()` / `token.json` loading pattern from the existing scripts (`scripts/send_followup.py:19-28`, `scripts/send_love_poem.py:19-30`, `scripts/test_gmail_pull.py:16-27`)
   - Single function: `get_gmail_service(scopes: list[str] | None = None) -> Resource` that loads `token.json`, auto-refreshes expired credentials, and returns a built Gmail v1 service
   - Default scopes should match `scripts/setup_rlm_agent_auth.py:8-34` (the full scope list)
   - If `token.json` is missing or invalid, print a clear error directing the user to run `python scripts/setup_rlm_agent_auth.py`
   - Add `scripts/gmail_cli/__init__.py` and `scripts/gmail_cli/__main__.py` (for `python -m scripts.gmail_cli` invocation)

2. **Spawn a `CLI-Scaffold` teammate to create the Typer app at `scripts/gmail_cli/cli.py`.**
   - Create a top-level Typer app with Rich markup enabled (`typer.Typer(rich_markup_mode="rich")`)
   - Register subcommand groups: `inbox`, `send`, `search`, `labels`, `threads`, `drafts`
   - Wire the `__main__.py` entry to call `app()`
   - Add `typer>=0.21.0` to `pyproject.toml` dependencies (line ~20-38) and `google-api-python-client>=2.0.0` + `google-auth-oauthlib>=1.0.0` as explicit dependencies
   - *[Added — Typer is in the lock file as a transitive dep but not declared in pyproject.toml. google-api-python-client and google-auth-oauthlib are available transitively but should be explicit since this CLI depends on them directly.]*

3. **Spawn an `Inbox-Commands` teammate to implement inbox reading commands.**
   - `gmail inbox list` — List recent messages from primary inbox (default 10, `--count N` flag). Output: Rich table with columns [#, From, Subject, Date, Snippet]. Use the query pattern from `scripts/test_gmail_pull.py:31` (`label:INBOX category:primary`)
   - `gmail inbox read MSG_ID` — Fetch and display full message body (decode MIME parts). Output plain text to stdout (agent-friendly)
   - `gmail inbox unread` — List unread messages only (`is:unread` query)
   - All commands should support `--json` flag for machine-readable output (agent consumption)

4. **Spawn a `Send-Commands` teammate to implement email sending commands.**
   - `gmail send --to EMAIL --subject TEXT --body TEXT` — Send a plain text email. Use the `create_message` + `users().messages().send()` pattern from `scripts/send_followup.py:30-37`
   - `gmail send --to EMAIL --subject TEXT --body-file PATH` — Send with body read from a file
   - `gmail send --to EMAIL --subject TEXT --body TEXT --cc EMAIL --bcc EMAIL` — CC/BCC support
   - Confirm before sending unless `--yes` flag is passed (agent can pass `--yes` to skip confirmation)

5. **Spawn a `Search-Commands` teammate to implement Gmail search.**
   - `gmail search QUERY` — Full Gmail search syntax support (e.g., `"from:foo subject:bar after:2026/03/01"`). Output: Rich table matching the inbox list format
   - `gmail search QUERY --count N` — Limit results
   - `gmail search QUERY --json` — Machine-readable output

6. **Spawn a `Label-Commands` teammate to implement label management.**
   - `gmail labels list` — List all labels with message counts
   - `gmail labels add MSG_ID LABEL` — Add a label to a message
   - `gmail labels remove MSG_ID LABEL` — Remove a label from a message
   - `gmail labels create NAME` — Create a new label

7. **Spawn a `Thread-Commands` teammate to implement thread operations.**
   - `gmail threads list` — List recent threads (default 10)
   - `gmail threads read THREAD_ID` — Display full conversation thread with all messages
   - `gmail threads reply THREAD_ID --body TEXT` — Reply to a thread (sets correct `In-Reply-To` and `References` headers, uses same `threadId`)

8. **Spawn a `Draft-Commands` teammate to implement draft management.**
   - `gmail drafts list` — List all drafts
   - `gmail drafts create --to EMAIL --subject TEXT --body TEXT` — Create a draft without sending
   - `gmail drafts send DRAFT_ID` — Send an existing draft
   - `gmail drafts delete DRAFT_ID` — Delete a draft

9. **Spawn a `Output-Format` teammate to add consistent output formatting.**
   - All list commands default to Rich tables for human readability
   - All list commands support `--json` flag that outputs newline-delimited JSON (one object per line) for agent parsing
   - Error messages go to stderr, data goes to stdout (so agents can pipe output cleanly)
   - `--quiet` flag suppresses all non-data output

## Provider-Fake Fixture & TDD

This is a standalone CLI tool outside the ADK agent loop, so provider-fake fixtures are not applicable. Instead:

**Unit test approach:** `tests_rlm_adk/test_gmail_cli.py`

**TDD sequence:**
1. Red: Test that `auth.get_gmail_service()` raises a clear error when `token.json` is missing. Run, confirm failure.
2. Green: Implement the auth module with proper error handling. Run, confirm pass.
3. Red: Test that `gmail inbox list --json` outputs valid JSON with expected keys (`id`, `from`, `subject`, `date`, `snippet`). Mock the Gmail API service.
4. Green: Implement inbox list command with JSON output. Run, confirm pass.
5. Red: Test that `gmail send --to X --subject Y --body Z --yes` constructs correct base64url-encoded message and calls `users().messages().send()`. Mock the API.
6. Green: Implement send command. Run, confirm pass.
7. Continue for search, labels, threads, drafts.

**Demo:** Run `uvx showboat` to generate an executable demo document showing each subcommand in action (with mocked API responses).

## Considerations

- **Token location:** The existing scripts assume `token.json` is in the current working directory. The CLI should look for it in a predictable location — either the project root or `~/.config/rlm-adk/token.json` — with a `--token-path` global option to override.
- **Agent ergonomics:** The `--json` and `--quiet` flags are critical — an agent calling this CLI needs parseable output, not Rich tables. Consider making `--json` the default when stdout is not a TTY (piped output).
- **Rate limits:** Gmail API has per-user rate limits. The CLI does not need retry logic initially, but error messages should clearly indicate rate limit errors (HTTP 429) so the calling agent can back off.
- **No ADK state mutation involved** — this is a standalone CLI tool, so AR-CRIT-001 does not apply.
- **Existing scripts:** After the CLI is working, the existing `send_followup.py`, `send_love_poem.py`, and `test_gmail_pull.py` could be replaced by CLI invocations, but that refactor is out of scope for this task.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `scripts/setup_rlm_agent_auth.py` | `SCOPES`, `main()` | L8-34, L36-68 | Master OAuth scope list and token bootstrap flow |
| `scripts/send_followup.py` | `get_gmail_service()`, `create_message()` | L19-28, L30-37 | Auth pattern and email construction to reuse |
| `scripts/send_love_poem.py` | `get_gmail_service()`, `send_message()` | L19-30, L43-50 | Auth pattern and send-with-error-handling to reuse |
| `scripts/test_gmail_pull.py` | `get_gmail_service()`, `fetch_latest_emails()` | L16-27, L29-53 | Auth pattern and inbox fetch logic to reuse |
| `pyproject.toml` | `dependencies` | L20-38 | Where to add typer, google-api-python-client, google-auth-oauthlib |

## Priming References

Before starting implementation, read these in order:
1. All four existing scripts listed in the appendix — they establish the auth pattern and Gmail API usage
2. [Typer documentation](https://typer.tiangolo.com/) — subcommand groups, Rich integration, testing with `CliRunner`
3. Gmail API reference for `users().messages()`, `users().labels()`, `users().threads()`, `users().drafts()` endpoints
