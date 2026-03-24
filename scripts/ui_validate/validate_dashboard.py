"""Overnight dashboard UI validation pipeline.

Orchestrates a 5-agent sequential pipeline for each unchecked manifest item:
  Selector -> Tester -> Implementer -> Reviewer -> Checker

Uses `claude --print` (Claude Code CLI) — runs on your Max subscription.
No ANTHROPIC_API_KEY needed.

Usage:
    python scripts/ui_validate/validate_dashboard.py [--dry-run] [--max-items N]

The script is idempotent — items with checked=true are skipped on re-run.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "scripts" / "ui_validate" / "manifest.json"
_REPORTS_DIR = _REPO_ROOT / "scripts" / "ui_validate" / "reports"
_RUN_REPORT_PATH = _REPO_ROOT / "scripts" / "ui_validate" / "run_report.md"
_DASHBOARD_DIR = _REPO_ROOT / "rlm_adk" / "dashboard"
_REPLAY_DIR = _REPO_ROOT / "tests_rlm_adk" / "replay"
_STATE_PY = _REPO_ROOT / "rlm_adk" / "state.py"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ui_validate")

# ---------------------------------------------------------------------------
# Claude CLI wrapper
# ---------------------------------------------------------------------------

_CLAUDE_BIN: str | None = None


def _find_claude() -> str:
    """Locate the claude CLI binary."""
    global _CLAUDE_BIN
    if _CLAUDE_BIN is None:
        path = shutil.which("claude")
        if not path:
            log.error(
                "claude CLI not found on PATH. "
                "Install Claude Code: https://claude.ai/code"
            )
            sys.exit(1)
        _CLAUDE_BIN = path
    return _CLAUDE_BIN


def _call(system: str, user: str, *, label: str = "") -> str:
    """Call Claude via `claude --print` and return the response text.

    Uses --print for headless single-shot mode (no interactive session).
    Runs on Max subscription — no API key needed.

    Parameters
    ----------
    system:
        System prompt context (prepended to the user prompt since --print
        does not have a separate system prompt flag).
    user:
        User-turn message (the task).
    label:
        Short label for log messages.

    Returns
    -------
    str
        Claude's response text.
    """
    if label:
        log.debug("  -> %s calling claude --print", label)

    claude = _find_claude()

    # Combine system + user into a single prompt for --print mode
    full_prompt = f"{system}\n\n---\n\n{user}"

    try:
        result = subprocess.run(
            [claude, "--print", full_prompt],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout per agent call
            cwd=str(_REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        log.warning("  %s timed out after 300s", label)
        return "(timeout — no response)"
    except FileNotFoundError:
        log.error("claude binary not found at %s", claude)
        sys.exit(1)

    if result.returncode != 0:
        stderr_preview = (result.stderr or "")[:500]
        log.warning(
            "  %s exited with code %d: %s", label, result.returncode, stderr_preview
        )
        # Still return whatever stdout we got
        if result.stdout:
            return result.stdout.strip()
        return f"(error: exit code {result.returncode})"

    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest() -> dict:
    with open(_MANIFEST_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(manifest: dict) -> None:
    # Recompute summary counts before writing.
    items = manifest.get("items", [])
    checked = sum(1 for it in items if it.get("checked", False))
    manifest.setdefault("summary", {})
    manifest["summary"]["checked"] = checked
    manifest["summary"]["unchecked"] = len(items) - checked
    with open(_MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def unchecked_items(manifest: dict) -> list[dict]:
    return [it for it in manifest.get("items", []) if not it.get("checked", False)]


# ---------------------------------------------------------------------------
# Context helpers — give agents enough project knowledge to work with
# ---------------------------------------------------------------------------

_DASHBOARD_COMPONENT_LIST: str | None = None
_REPLAY_FIXTURE_LIST: str | None = None


def _dashboard_component_list() -> str:
    global _DASHBOARD_COMPONENT_LIST
    if _DASHBOARD_COMPONENT_LIST is None:
        files = sorted(
            p.name for p in _DASHBOARD_DIR.rglob("*.py") if not p.name.startswith("__")
        )
        _DASHBOARD_COMPONENT_LIST = ", ".join(files)
    return _DASHBOARD_COMPONENT_LIST


def _replay_fixture_list() -> str:
    global _REPLAY_FIXTURE_LIST
    if _REPLAY_FIXTURE_LIST is None:
        files = sorted(p.name for p in _REPLAY_DIR.glob("*.json"))
        _REPLAY_FIXTURE_LIST = ", ".join(files)
    return _REPLAY_FIXTURE_LIST


def _item_context(item: dict) -> str:
    """Render a manifest item as a compact context block for agent prompts."""
    lines = [
        f"ID: {item.get('id', '?')}",
        f"Category: {item.get('category', '?')}",
        f"Name: {item.get('name', '?')}",
    ]
    if "key" in item:
        lines.append(f"State key: {item['key']}")
    if "description" in item:
        lines.append(f"Description: {item['description']}")
    if "writer" in item:
        lines.append(f"Writer: {item['writer']}")
    if "reader" in item:
        lines.append(f"Reader: {item['reader']}")
    if item.get("depth_scoped"):
        lines.append("Depth-scoped: yes (key suffixed with @dN at depth > 0)")
    if "element" in item:
        lines.append(f"UI element: {item['element']}")
    if "handler" in item:
        lines.append(f"Handler: {item['handler']}")
    if "route" in item:
        lines.append(f"Route: {item['route']}")
    if "sub_elements" in item:
        sub = ", ".join(item["sub_elements"])
        lines.append(f"Sub-elements: {sub}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Project context block (shared across agent system prompts)
# ---------------------------------------------------------------------------

_PROJECT_CONTEXT = textwrap.dedent(f"""\
    PROJECT CONTEXT
    ===============
    This is the RLM-ADK (Recursive Language Model) project built on Google ADK.

    Repository root: /home/rawley-stanhope/dev/rlm-adk
    Dashboard directory: rlm_adk/dashboard/
    Dashboard components: {_dashboard_component_list()}
    Replay fixtures (tests_rlm_adk/replay/): {_replay_fixture_list()}
    State keys defined in: rlm_adk/state.py

    Key architectural facts:
    - RLMOrchestratorAgent delegates to reasoning_agent.run_async(ctx) with REPLTool
    - REPLTool (BaseTool, name="execute_code") wraps LocalREPL
    - State mutation rules: NEVER ctx.session.state[key]=value in dispatch closures.
      Correct: tool_context.state[key], callback_context.state[key],
               EventActions(state_delta={{...}}), output_key
    - Depth-scoped keys: key@dN format at recursion depth N (depth_key() in state.py)
    - Dashboard is NiceGUI-based, reads from SQLite traces.db + JSONL
    - LiveDashboardLoader loads telemetry; LiveDashboardController drives UI state
    - Run tests: .venv/bin/python -m pytest tests_rlm_adk/
""")


# ---------------------------------------------------------------------------
# Agent 1 — Selector
# ---------------------------------------------------------------------------

_SELECTOR_SYSTEM = textwrap.dedent("""\
    You are the Selector agent in a dashboard UI validation pipeline.

    Your job: given a manifest item that has been pre-selected for validation,
    produce a compact, structured selection report that will be passed to the
    Tester agent. The report must include:

    1. SELECTED_ITEM block: echo the item's id, category, name, description,
       writer, reader, and any other relevant fields.
    2. VALIDATION_STRATEGY: explain in 2-4 sentences what the most meaningful
       validation approach is for this category of item. Be concrete about
       what "validated" means — what evidence would prove the item works.
    3. RELEVANT_FILES: list the 1-3 source files most directly relevant to
       validating this item (paths relative to repo root).
    4. RELEVANT_FIXTURES: if any of the replay fixtures in tests_rlm_adk/replay/
       are likely to exercise this item, name them. Otherwise state "none obvious".

    Be terse. No preamble. Output only the four numbered sections.
""")


def run_selector(item: dict) -> str:
    """Agent 1: Selector — produces the item selection report."""
    item_ctx = _item_context(item)
    user = textwrap.dedent(f"""\
        {_PROJECT_CONTEXT}

        MANIFEST ITEM TO SELECT:
        {item_ctx}

        Produce the selection report now.
    """)
    return _call(_SELECTOR_SYSTEM, user, label=f"Selector[{item['id']}]")


# ---------------------------------------------------------------------------
# Agent 2 — Tester
# ---------------------------------------------------------------------------

_TESTER_SYSTEM = textwrap.dedent("""\
    You are the Tester agent in a dashboard UI validation pipeline.

    Your job: given a Selector report about a manifest item, design a
    concrete validation test. Output a structured TEST_PLAN with:

    1. TEST_KIND: one of [replay_fixture | static_code_analysis | python_unit_test | grep_search | manual_inspection]
    2. TEST_DESCRIPTION: what the test will check, specifically
    3. TEST_COMMANDS_OR_CODE: the exact shell commands or Python code that
       would perform the validation. Use the project venv:
         .venv/bin/python -m pytest tests_rlm_adk/
         .venv/bin/python -c "..."
       Use grep/find only for static analysis. Never require a running browser.
    4. EXPECTED_OUTCOME: what output or result proves the item is correctly implemented
    5. REWARD_HACK_RISKS: list 1-2 ways the test could pass trivially without
       actually validating the real thing, and how to prevent them

    Prioritize:
    - For state_keys / depth_scoped_keys: import state.py, check constants and depth_key()
    - For data_models: import the model class, verify fields exist
    - For flow_blocks / dashboard components: grep the component file for expected functions/classes
    - For routes_pages: grep app.py / live_app.py / flow_child_page.py for route definitions
    - For event_handlers / controller methods: grep live_controller.py for method names
    - For visual_styling: grep live_app.py CSS for the color value
    - For dead_key_candidates: grep the entire codebase for the key string

    Keep it realistic — tests should be executable without network or a running server.
""")


def run_tester(item: dict, selector_report: str) -> str:
    """Agent 2: Tester — designs the concrete validation test."""
    item_ctx = _item_context(item)
    user = textwrap.dedent(f"""\
        {_PROJECT_CONTEXT}

        MANIFEST ITEM:
        {item_ctx}

        SELECTOR REPORT:
        {selector_report}

        Design the test plan now.
    """)
    return _call(_TESTER_SYSTEM, user, label=f"Tester[{item['id']}]")


# ---------------------------------------------------------------------------
# Agent 3 — Implementer
# ---------------------------------------------------------------------------

_IMPLEMENTER_SYSTEM = textwrap.dedent("""\
    You are the Implementer agent in a dashboard UI validation pipeline.

    Your job: execute the test plan (mentally/statically — you cannot run code,
    but you have read access to the codebase via the context provided) and
    produce a validation report.

    You will be given:
    - The manifest item details
    - The test plan from the Tester agent
    - Excerpts from relevant source files (provided in the user message)

    Your output must be a markdown report with these sections:

    ## Validation Report: {item_id}

    ### Summary
    One sentence verdict: PASS or FAIL with a brief reason.

    ### Evidence
    - List specific code evidence you found (function names, line patterns,
      constant values, CSS properties, etc.)
    - For each piece of evidence, state what file it was found in

    ### Bugs Found
    If any bugs or missing implementations are found, describe them precisely:
    - Bug: [description]
    - Location: [file and approximate line]
    - Severity: [critical | warning | cosmetic]
    - Fix: [concrete fix suggestion]

    ### Validation Notes
    2-4 sentences summarizing what was validated, what the evidence proves,
    and any caveats or limitations of this static validation approach.

    Be rigorous. Do not declare PASS unless the evidence directly supports
    the item's described behavior. A missing implementation is always a FAIL.
""")


def _read_relevant_files(item: dict) -> str:
    """Read 1-3 source files most likely to contain evidence for this item.

    Returns a string with file paths and content excerpts, capped at ~4000 chars
    total to avoid overflowing the context window.
    """
    category = item.get("category", "")
    item_id = item.get("id", "")
    budget = 4000
    parts: list[str] = []

    def _read_excerpt(path: Path, max_chars: int = 1500) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars] + (" [truncated]" if len(text) > max_chars else "")
        except OSError:
            return f"[file not readable: {path}]"

    def _add(path: Path) -> None:
        nonlocal budget
        if budget <= 0:
            return
        excerpt = _read_excerpt(path, min(1500, budget))
        entry = f"=== {path.relative_to(_REPO_ROOT)} ===\n{excerpt}\n"
        parts.append(entry)
        budget -= len(entry)

    # State key categories — always read state.py
    if category in ("state_keys", "depth_scoped_keys", "dead_key_candidates"):
        _add(_STATE_PY)

    # Dynamic instructions — check state.py + prompts
    if category == "dynamic_instructions":
        _add(_STATE_PY)
        prompts_py = _REPO_ROOT / "rlm_adk" / "utils" / "prompts.py"
        if prompts_py.exists():
            _add(prompts_py)

    # UI controls, launch controls, polling timers, navigation — live_app.py
    if category in ("ui_controls", "launch_controls", "polling_timers", "navigation"):
        live_app = _DASHBOARD_DIR / "live_app.py"
        if live_app.exists():
            _add(live_app)

    # Event handlers / controller methods — live_controller.py
    if category == "event_handlers" or item_id.startswith("CTRL") or item_id.startswith("LDR"):
        ctrl = _DASHBOARD_DIR / "live_controller.py"
        if ctrl.exists():
            _add(ctrl)
        if item_id.startswith("LDR"):
            loader = _DASHBOARD_DIR / "live_loader.py"
            if loader.exists():
                _add(loader)

    # Flow blocks — flow_builder.py + the specific component file
    if category == "flow_blocks":
        fb = _DASHBOARD_DIR / "flow_builder.py"
        if fb.exists():
            _add(fb)
        elem = item.get("element", "")
        # Try to map element to a component file
        if elem:
            candidate = _DASHBOARD_DIR / "components" / elem
            if candidate.exists():
                _add(candidate)

    # Connectors/arrows
    if category == "connectors_arrows":
        conn = _DASHBOARD_DIR / "components" / "flow_connectors.py"
        if conn.exists():
            _add(conn)

    # Context inspector
    if category == "context_inspector":
        ci = _DASHBOARD_DIR / "components" / "flow_context_inspector.py"
        if ci.exists():
            _add(ci)
        if "live_context_viewer" in item.get("element", ""):
            viewer = _DASHBOARD_DIR / "components" / "live_context_viewer.py"
            if viewer.exists():
                _add(viewer)

    # Routes/pages
    if category == "routes_pages":
        app_py = _DASHBOARD_DIR / "app.py"
        if app_py.exists():
            _add(app_py)
        live_app = _DASHBOARD_DIR / "live_app.py"
        if live_app.exists():
            _add(live_app)

    # Data models
    if category == "data_models":
        # flow_models.py for Flow* classes, live_models.py for Live* classes
        name = item.get("name", "")
        if name.startswith("Flow") or name.startswith("Llm"):
            fm = _DASHBOARD_DIR / "flow_models.py"
            if fm.exists():
                _add(fm)
        else:
            lm = _DASHBOARD_DIR / "live_models.py"
            if lm.exists():
                _add(lm)

    # Visual styling — always live_app.py for CSS section
    if category == "visual_styling":
        live_app = _DASHBOARD_DIR / "live_app.py"
        if live_app.exists():
            _add(live_app)

    if not parts:
        return "(no specific source files pre-loaded for this category)"
    return "\n".join(parts)


def run_implementer(item: dict, selector_report: str, test_plan: str) -> str:
    """Agent 3: Implementer — executes validation and produces the report."""
    item_ctx = _item_context(item)
    file_excerpts = _read_relevant_files(item)

    user = textwrap.dedent(f"""\
        {_PROJECT_CONTEXT}

        MANIFEST ITEM:
        {item_ctx}

        SELECTOR REPORT:
        {selector_report}

        TEST PLAN:
        {test_plan}

        SOURCE FILE EXCERPTS:
        {file_excerpts}

        Produce the validation report now.
        Replace {{item_id}} in the report header with: {item['id']}
    """)
    return _call(_IMPLEMENTER_SYSTEM, user, label=f"Implementer[{item['id']}]")


# ---------------------------------------------------------------------------
# Agent 4 — Reviewer
# ---------------------------------------------------------------------------

_REVIEWER_SYSTEM = textwrap.dedent("""\
    You are the Reviewer agent in a dashboard UI validation pipeline.

    Your job: review the Implementer's validation report with a skeptical eye.
    Look specifically for reward hacking — cases where the test passed trivially
    without actually validating the real behavior described in the manifest.

    Common reward hacking patterns to watch for:
    - Test checked that a file exists, not that it has the right content
    - Test checked that a function name exists, not that it does the right thing
    - PASS declared based on naming conventions alone (e.g., "the file is named correctly")
    - Evidence cited that is circumstantial rather than direct
    - Bugs were found but severity was under-reported
    - For state_keys: "the constant is defined" is NOT the same as "the write path
      correctly uses tool_context.state (not ctx.session.state)"

    Your output must be exactly:

    VERDICT: PASS | FAIL

    REASONING:
    [3-5 sentences explaining your verdict. If PASS, explain what makes the
    evidence convincing. If FAIL, explain the specific gap between the evidence
    and what a real validation would require.]

    REWARD_HACK_DETECTED: yes | no

    If REWARD_HACK_DETECTED is yes, explain in one sentence what the hack was.
""")


def run_reviewer(item: dict, implementer_report: str) -> tuple[bool, str]:
    """Agent 4: Reviewer — skeptically reviews the implementer's report.

    Returns
    -------
    (passed, full_reviewer_output)
        passed: True if the reviewer verdict is PASS
    """
    item_ctx = _item_context(item)
    user = textwrap.dedent(f"""\
        MANIFEST ITEM:
        {item_ctx}

        IMPLEMENTER REPORT:
        {implementer_report}

        Review now.
    """)
    output = _call(_REVIEWER_SYSTEM, user, label=f"Reviewer[{item['id']}]")

    # Parse the VERDICT line.
    passed = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("VERDICT:"):
            verdict = stripped.replace("VERDICT:", "").strip().upper()
            passed = verdict == "PASS"
            break

    return passed, output


# ---------------------------------------------------------------------------
# Agent 5 — Checker
# ---------------------------------------------------------------------------

_CHECKER_SYSTEM = textwrap.dedent("""\
    You are the Checker agent in a dashboard UI validation pipeline.

    Your job: synthesize the validation pipeline outputs into a compact
    summary suitable for storing in the manifest's validation_notes field.

    The validation_notes must be:
    - 1-3 sentences maximum
    - Factual and specific (mention what evidence was found)
    - Include the date validated
    - Flag any bugs found with "BUG:" prefix if applicable

    Output ONLY the validation_notes text. No headers. No extra formatting.
    No preamble. Just the 1-3 sentence summary.
""")


def run_checker(
    item: dict,
    selector_report: str,
    implementer_report: str,
    reviewer_output: str,
    passed: bool,
) -> str:
    """Agent 5: Checker — produces the validation_notes summary."""
    item_ctx = _item_context(item)
    today = datetime.now().strftime("%Y-%m-%d")
    user = textwrap.dedent(f"""\
        MANIFEST ITEM:
        {item_ctx}

        VALIDATION RESULT: {"PASS" if passed else "FAIL"}
        DATE: {today}

        IMPLEMENTER REPORT SUMMARY:
        {implementer_report[:1200]}

        REVIEWER OUTPUT:
        {reviewer_output}

        Write the validation_notes (1-3 sentences) now.
    """)
    return _call(_CHECKER_SYSTEM, user, label=f"Checker[{item['id']}]")


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _save_item_report(item: dict, implementer_report: str, reviewer_output: str, passed: bool) -> Path:
    """Save the per-item markdown report to scripts/ui_validate/reports/{id}.md"""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORTS_DIR / f"{item['id']}.md"

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    verdict_line = "PASS" if passed else "FAIL"

    content = textwrap.dedent(f"""\
        # Validation Report: {item['id']} — {item.get('name', '')}

        **Category**: {item.get('category', '')}
        **Validated**: {today}
        **Verdict**: {verdict_line}

        ---

        {implementer_report}

        ---

        ## Reviewer Assessment

        {reviewer_output}
    """)
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _write_run_report(
    validated: list[dict],
    failed: list[dict],
    skipped_count: int,
    total: int,
    dry_run: bool,
) -> None:
    """Write the top-level run_report.md after the run completes."""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    fresh_items = load_manifest().get("items", [])
    checked_count = sum(1 for it in fresh_items if it.get("checked", False))
    pct = round(100.0 * checked_count / total, 1) if total > 0 else 0.0

    lines = [
        "# Dashboard UI Validation Run Report",
        "",
        f"**Date**: {today}  ",
        f"**Dry run**: {dry_run}  ",
        "**Engine**: claude --print (Max subscription)  ",
        "",
        "## Progress",
        "",
        f"- Total manifest items: {total}",
        f"- Checked (cumulative): {checked_count}",
        f"- Remaining: {total - checked_count}",
        f"- Progress: {pct}%",
        "",
        "## This Run",
        "",
        f"- Items attempted: {len(validated) + len(failed)}",
        f"- Items validated (PASS): {len(validated)}",
        f"- Items failed (FAIL): {len(failed)}",
        f"- Items skipped (already checked): {skipped_count}",
        "",
    ]

    if validated:
        lines += [
            "## Items Validated This Run",
            "",
        ]
        for it in validated:
            lines.append(f"- [{it['id']}] {it.get('name', '')} ({it.get('category', '')})")
        lines.append("")

    if failed:
        lines += [
            "## Items That Failed Validation",
            "",
        ]
        for it in failed:
            lines.append(f"- [{it['id']}] {it.get('name', '')} ({it.get('category', '')}) — see reports/{it['id']}.md")
        lines.append("")

    remaining_items = [it for it in fresh_items if not it.get("checked", False)]
    if remaining_items:
        lines += [
            f"## Remaining Items (next {min(10, len(remaining_items))} shown)",
            "",
        ]
        for it in remaining_items[:10]:
            lines.append(f"- [{it['id']}] {it.get('name', '')} ({it.get('category', '')})")
        if len(remaining_items) > 10:
            lines.append(f"- ... and {len(remaining_items) - 10} more")
        lines.append("")

    _RUN_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log.info("Run report written to %s", _RUN_REPORT_PATH.relative_to(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Pipeline: one item end-to-end
# ---------------------------------------------------------------------------


def run_pipeline_for_item(item: dict) -> tuple[bool, str]:
    """Run the 5-agent pipeline for a single manifest item.

    Returns
    -------
    (passed, validation_notes)
    """
    item_id = item["id"]
    log.info("  [1/5] Selector  — %s", item_id)
    selector_report = run_selector(item)

    log.info("  [2/5] Tester    — %s", item_id)
    test_plan = run_tester(item, selector_report)

    log.info("  [3/5] Implementer — %s", item_id)
    implementer_report = run_implementer(item, selector_report, test_plan)

    log.info("  [4/5] Reviewer  — %s", item_id)
    passed, reviewer_output = run_reviewer(item, implementer_report)

    log.info("  [5/5] Checker   — %s", item_id)
    validation_notes = run_checker(item, selector_report, implementer_report, reviewer_output, passed)

    # Save per-item report regardless of pass/fail.
    report_path = _save_item_report(item, implementer_report, reviewer_output, passed)
    log.info(
        "  Result: %s  (report: %s)",
        "PASS" if passed else "FAIL",
        report_path.relative_to(_REPO_ROOT),
    )

    return passed, validation_notes


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Overnight dashboard UI validation pipeline using Claude Code CLI (Max subscription).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/ui_validate/validate_dashboard.py
              python scripts/ui_validate/validate_dashboard.py --max-items 10
              python scripts/ui_validate/validate_dashboard.py --dry-run

            This script uses `claude --print` (Claude Code CLI) for all LLM calls.
            No ANTHROPIC_API_KEY needed — runs on your Max subscription.
        """),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview which items would be validated without making any calls or changes.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=5,
        metavar="N",
        help="Maximum number of items to validate per run (default: 5).",
    )
    args = parser.parse_args()

    # Verify claude CLI is available
    _find_claude()

    manifest = load_manifest()
    all_items = manifest.get("items", [])
    total = len(all_items)
    pending = unchecked_items(manifest)
    already_checked = total - len(pending)

    log.info(
        "Manifest: %d total items, %d already checked, %d pending",
        total,
        already_checked,
        len(pending),
    )

    to_process = pending[: args.max_items]

    if not to_process:
        log.info("All manifest items are already checked. Nothing to do.")
        _write_run_report([], [], already_checked, total, args.dry_run)
        return

    if args.dry_run:
        log.info("DRY RUN — would validate %d item(s):", len(to_process))
        for it in to_process:
            log.info("  [%s] %s (%s)", it["id"], it.get("name", ""), it.get("category", ""))
        log.info("No changes made. Re-run without --dry-run to execute.")
        return

    validated: list[dict] = []
    failed: list[dict] = []

    for idx, item in enumerate(to_process, start=1):
        item_id = item["id"]
        log.info(
            "Processing item %d/%d: [%s] %s",
            idx,
            len(to_process),
            item_id,
            item.get("name", ""),
        )

        try:
            passed, validation_notes = run_pipeline_for_item(item)
        except Exception as exc:  # noqa: BLE001
            log.error("Unexpected error on %s: %s", item_id, exc, exc_info=True)
            failed.append(item)
            continue

        # Find and update the item in the manifest.
        for manifest_item in manifest["items"]:
            if manifest_item["id"] == item_id:
                if passed:
                    manifest_item["checked"] = True
                    manifest_item["status"] = "validated"
                else:
                    manifest_item["checked"] = False
                    manifest_item["status"] = "failed"
                manifest_item["validation_notes"] = validation_notes
                break

        # Persist after each item so a crash mid-run doesn't lose progress.
        save_manifest(manifest)
        log.info("Manifest saved after %s", item_id)

        if passed:
            validated.append(item)
        else:
            failed.append(item)

    # Final run report.
    _write_run_report(validated, failed, already_checked, total, dry_run=False)

    # Print summary to stdout.
    print()
    print(f"Run complete: {len(validated)} PASS, {len(failed)} FAIL out of {len(to_process)} attempted.")
    print(f"Run report:   {_RUN_REPORT_PATH.relative_to(_REPO_ROOT)}")
    if _REPORTS_DIR.exists():
        report_count = len(list(_REPORTS_DIR.glob("*.md")))
        print(f"Item reports: {_REPORTS_DIR.relative_to(_REPO_ROOT)}/ ({report_count} files)")

    remaining = len(unchecked_items(load_manifest()))
    pct = round(100.0 * (total - remaining) / total, 1) if total > 0 else 0.0
    print(f"Progress:     {total - remaining}/{total} checked ({pct}%)")

    # Exit with non-zero if any items failed validation.
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
