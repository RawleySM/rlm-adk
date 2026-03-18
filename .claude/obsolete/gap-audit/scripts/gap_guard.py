#!/usr/bin/env python3
"""Gap registry validator — Stop hook for Claude Code.

Exit codes:
  0 — all clear (or mode=report, or GAP_AUDIT_ACTIVE=0, or re-entry guard)
  2 — violations found AND mode=strict AND GAP_AUDIT_ACTIVE=1

Environment:
  GAP_AUDIT_ACTIVE — "0" (default) = pass-through, "1" = enforce.
    Set in .claude/settings.local.json env section.
    The /gap-audit skill flips this to "1" as its first step.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
REGISTRY_PATH = REPO_ROOT / "rlm_adk_docs" / "gap_registry.json"
SCHEMA_PATH = REPO_ROOT / "rlm_adk_docs" / "gap_registry.schema.json"
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.local.json"


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def is_audit_active() -> bool:
    """Check GAP_AUDIT_ACTIVE env var, falling back to settings.local.json."""
    val = os.environ.get("GAP_AUDIT_ACTIVE")
    if val is not None:
        return val == "1"
    # Fallback: read settings file directly (env may not propagate mid-session)
    if SETTINGS_PATH.exists():
        try:
            settings = load_json(SETTINGS_PATH)
            return settings.get("env", {}).get("GAP_AUDIT_ACTIVE", "0") == "1"
        except (json.JSONDecodeError, KeyError):
            pass
    return False


def validate_schema(registry: dict, schema: dict) -> list[str]:
    """Validate registry against JSON Schema. Returns list of error messages."""
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema package not installed — schema validation skipped"]
    errors = []
    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(registry), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path)
        errors.append(f"Schema: {path}: {error.message}")
    return errors


def validate_count(registry: dict) -> list[str]:
    """Check meta.total_gaps matches actual entry count."""
    expected = registry["meta"]["total_gaps"]
    actual = len(registry["gaps"])
    if expected != actual:
        return [f"Count mismatch: meta.total_gaps={expected} but found {actual} entries"]
    return []


def validate_evidence(gap: dict) -> list[str]:
    """Validate evidence consistency for closed gaps."""
    errors = []
    gid = gap["id"]
    ev = gap["evidence"]
    tier = ev.get("evidence_tier")

    if gap["disposition"] != "closed":
        return errors

    if tier is None:
        errors.append(f"{gid}: closed but evidence_tier is null")
        return errors

    if tier == "demo_verified":
        if not ev.get("demo_path"):
            errors.append(f"{gid}: demo_verified but demo_path is null/empty")
        elif not (REPO_ROOT / ev["demo_path"]).exists():
            errors.append(f"{gid}: demo_path does not exist: {ev['demo_path']}")
        if not ev.get("test_paths"):
            errors.append(f"{gid}: demo_verified but test_paths is empty")
        if not ev.get("code_paths"):
            errors.append(f"{gid}: demo_verified but code_paths is empty")

    elif tier == "test_only":
        if not ev.get("test_paths"):
            errors.append(f"{gid}: test_only but test_paths is empty")
        if not ev.get("code_paths"):
            errors.append(f"{gid}: test_only but code_paths is empty")

    elif tier == "code_review":
        if not ev.get("code_paths"):
            errors.append(f"{gid}: code_review but code_paths is empty")

    return errors


def validate_disposition(gap: dict) -> list[str]:
    """Validate dismissed/deferred gaps have category and reason."""
    errors = []
    gid = gap["id"]
    disp = gap["disposition"]

    if disp in ("dismissed", "deferred"):
        if not gap.get("disposition_category"):
            errors.append(f"{gid}: {disp} but disposition_category is null")
        if not gap.get("disposition_reason"):
            errors.append(f"{gid}: {disp} but disposition_reason is null/empty")
        elif len(gap["disposition_reason"]) < 50:
            errors.append(
                f"{gid}: {disp} disposition_reason too short "
                f"({len(gap['disposition_reason'])} chars, need >= 50)"
            )
    return errors


def check_reentry() -> bool:
    """Check if we're being called inside a stop hook (re-entry guard)."""
    try:
        stdin_data = ""
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
        if stdin_data:
            hook_input = json.loads(stdin_data)
            if hook_input.get("stop_hook_active"):
                return True
    except (json.JSONDecodeError, TypeError):
        pass
    return False


def build_delegation_prompt(
    pending_gaps: list[dict],
    project_phase: str,
    total: int,
    resolved: int,
) -> str:
    """Build an impartial prompt for a sub-agent to assess gap resolution priority."""
    gap_summary = "\n".join(
        f"  - {g['id']} [{g['severity']}] {g['title']}" for g in pending_gaps
    )
    return f"""## Gap Resolution Assessment

You are an impartial reviewer. The gap registry has {len(pending_gaps)} pending gaps \
out of {total} total ({resolved} resolved). The project is in the \
"{project_phase}" phase.

### Pending Gaps
{gap_summary}

### Your Task
For each pending gap, assess whether it should be:
1. **Resolved now** — if it blocks the current project phase or is critical
2. **Deferred** — if it's not relevant to the current phase
3. **Dismissed** — if it's not worth tracking at all

Consider:
- In "{project_phase}", what level of observability is appropriate?
- Does the gap's severity warrant immediate attention at this stage?
- Would deferring the gap create technical debt that compounds?
- Is there a simpler path (close, defer, or dismiss) that is honest and accurate?

Respond with a prioritized action plan: which gaps to address first, which to \
defer, and which to dismiss, with brief justifications for each."""


def main() -> int:
    check_only = "--check-only" in sys.argv

    # Registry missing — not an error, just report
    if not REGISTRY_PATH.exists():
        print("gap_guard: registry not found, skipping", file=sys.stderr)
        return 0

    # GAP_AUDIT_ACTIVE gate — when inactive, allow stop unconditionally
    if not check_only and not is_audit_active():
        print("gap_guard: GAP_AUDIT_ACTIVE=0, pass-through", file=sys.stderr)
        return 0

    # Re-entry guard
    if not check_only and check_reentry():
        print("gap_guard: re-entry detected, reporting only", file=sys.stderr)

    registry = load_json(REGISTRY_PATH)
    mode = registry.get("meta", {}).get("mode", "report")
    project_phase = registry.get("meta", {}).get("project_phase", "unknown")

    # Schema validation
    schema_errors = []
    if SCHEMA_PATH.exists():
        schema = load_json(SCHEMA_PATH)
        schema_errors = validate_schema(registry, schema)

    # Count validation
    count_errors = validate_count(registry)

    # Per-gap validation
    gaps = registry.get("gaps", {})
    evidence_errors = []
    disposition_errors = []
    pending_gaps = []

    for gid in sorted(gaps):
        gap = gaps[gid]
        evidence_errors.extend(validate_evidence(gap))
        disposition_errors.extend(validate_disposition(gap))
        if gap["disposition"] == "pending":
            pending_gaps.append(gap)

    # Build report
    total = len(gaps)
    resolved = total - len(pending_gaps)
    pct = (resolved / total * 100) if total > 0 else 0

    all_errors = schema_errors + count_errors + evidence_errors + disposition_errors
    has_violations = len(pending_gaps) > 0 or len(all_errors) > 0

    # Always print report to stderr
    report_lines = [
        f"=== GAP REGISTRY: {len(pending_gaps)} of {total} gaps still pending ===",
        f"Mode: {mode} | Phase: {project_phase} | Progress: {pct:.0f}% ({resolved}/{total} resolved)",
        "",
    ]

    if pending_gaps:
        report_lines.append("PENDING (blocks stop in strict mode):")
        for g in sorted(pending_gaps, key=lambda x: x["id"]):
            report_lines.append(f"  {g['id']} [{g['severity']}] {g['title']}")
        report_lines.append("")

    if all_errors:
        report_lines.append("VALIDATION ERRORS:")
        for err in all_errors:
            report_lines.append(f"  {err}")
        report_lines.append("")

    # In strict mode with pending gaps, emit delegation prompt instead of blocking
    if mode == "strict" and has_violations and not check_only:
        delegation = build_delegation_prompt(pending_gaps, project_phase, total, resolved)
        report_lines.append("DELEGATION: Strict mode with pending gaps detected.")
        report_lines.append("Return to team leader with the following sub-agent prompt:")
        report_lines.append("")
        report_lines.append(delegation)
        report_lines.append("")
        report_lines.append(
            "ACTION: Team leader should delegate this assessment to a sub-agent, "
            "then apply the recommended dispositions via /gap-audit close|dismiss|defer."
        )

    report_lines.append("Resolve via: /gap-audit close|dismiss|defer <gap-id>")

    print("\n".join(report_lines), file=sys.stderr)

    # Exit decision
    if check_only:
        return 0

    if mode == "strict" and has_violations:
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
