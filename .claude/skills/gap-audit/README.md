# Gap Accountability System

## Problem

Phase 1-2 agents identified ~64 observability gaps across 6 docs. Phase 3 TDD agents silently skipped 39 of them (17% close rate). The most critical cluster (REPL code/prompt/response persistence) was dismissed as "By design: privacy/size concern" in a single line. The existing three-doc triage (`observability_gaps.md`, `observability_gaps_deferred.md`, `observability_gaps_codex.md`) had no enforcement — agents could finish their turn without addressing any gap.

## Solution

A deterministic, hook-enforced system that makes silent skipping structurally impossible. Every gap must have an explicit disposition with evidence or a substantive reason before Claude Code can stop.

```
┌──────────────────────┐     ┌─────────────────────┐
│  /gap-audit skill     │────▶│  gap_registry.json   │◀── seed_gap_registry.py
│  (status/close/       │     │  (source of truth)   │
│   dismiss/defer)      │     └─────────┬───────────┘
└──────────────────────┘                │
                                        ▼
┌──────────────────────┐     ┌─────────────────────┐
│  Stop hook            │────▶│  gap_guard.py        │
│  (.claude/settings)   │     │  (deterministic      │
│                       │     │   validator)          │
└──────────────────────┘     └─────────────────────┘
         │                              │
         ▼                              ▼
   exit(0) = proceed            exit(2) = BLOCK
                            stderr = actionable report
```

## File Inventory

```
.claude/skills/gap-audit/
├── SKILL.md                    # Agent-facing skill definition (/gap-audit)
├── README.md                   # This file
└── scripts/
    ├── gap_guard.py            # Stop hook validator (exit 0 or 2)
    └── seed_gap_registry.py    # One-time bootstrap from markdown docs

rlm_adk_docs/
├── gap_registry.json           # Source of truth (61 gaps)
├── gap_registry.schema.json    # JSON Schema draft-07 contract
├── observability_gaps.md       # Original gap analysis (read-only reference)
├── observability_gaps_deferred.md  # Deferred items (read-only reference)
└── observability_gaps_codex.md     # Active codex items (read-only reference)
```

## Registry Design

**61 total gaps**: 33 active (`OG-01` through `OG-33`) + 28 deferred (`OD-01` through `OD-28`).

Each gap has a mandatory disposition: `pending` | `closed` | `dismissed` | `deferred`.

### Evidence Tiers (for `closed` gaps)

| Tier | Required For | What's Needed |
|------|-------------|---------------|
| `demo_verified` | CRITICAL/HIGH | showboat demo + tests + code paths |
| `test_only` | MEDIUM | tests + code paths |
| `code_review` | LOW | code paths only (emits warning) |

### Disposition Categories (controlled vocabulary)

`redundant_with_active`, `low_value_detail`, `perf_outside_scope`, `platform_maturity`, `by_design_privacy`, `by_design_architecture`, `superseded`, `out_of_scope`

All `dismissed`/`deferred` gaps require a category from this list plus a prose reason of at least 50 characters.

## Modes

- **`report`** (default): Stop hook prints progress but always exits 0. Safe for normal development.
- **`strict`**: Stop hook exits 2 (blocks Claude Code) if any gaps remain `pending` or have evidence violations.

Switch by editing `meta.mode` in `gap_registry.json`.

## Guard Script Behavior

`gap_guard.py` validates:
1. Registry matches JSON Schema
2. `meta.total_gaps` matches actual entry count (prevents accidental deletion)
3. `pending` gaps are violations in strict mode
4. `closed` gaps have evidence consistent with their tier (files exist, paths non-empty)
5. `dismissed`/`deferred` gaps have category + reason >= 50 chars

**Re-entry safety**: When invoked with `stop_hook_active: true` in stdin JSON, reports only (never exits 2). Prevents infinite block loops.

## Usage

```bash
# Check status
/gap-audit status

# Close a gap with evidence
/gap-audit close OG-22

# Dismiss a gap with reason
/gap-audit dismiss OG-31

# Defer a gap
/gap-audit defer OG-09

# Run guard manually
.venv/bin/python .claude/skills/gap-audit/scripts/gap_guard.py --check-only

# Re-bootstrap (destructive — overwrites registry)
.venv/bin/python .claude/skills/gap-audit/scripts/seed_gap_registry.py
```

## Why This Design

| Decision | Rationale |
|----------|-----------|
| Three evidence tiers instead of uniform demo requirement | LOW-severity gaps don't need full showboat demos — requiring them incentivizes thin demos just to pass the check |
| Controlled vocabulary + 50-char prose | "By design: privacy/size concern" (33 chars, no category) would fail — agents must pick from defined categories AND explain why |
| Unified 61-gap registry (active + deferred) | Deferred doc was a shadow registry where items languished without enforcement |
| `report`/`strict` mode in registry JSON | Mode is version-controlled, visible in git diff, persists across sessions |
| JSON Schema enforcement | Prevents registry corruption from malformed agent writes |
| Stop hook + skill separation | The skill guides agents through correct updates; the hook catches anything that slipped through |
| Re-entry guard | Without it, the Stop hook creates an infinite loop: block → retry → block |
