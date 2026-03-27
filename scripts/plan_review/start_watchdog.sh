#!/usr/bin/env bash
# start_watchdog.sh -- Launch the plan-review watchdog in background
#
# Usage:
#   ./start_watchdog.sh              # Normal mode (live Codex review)
#   ./start_watchdog.sh --test       # Test mode (deterministic ping/pong)
#   ./start_watchdog.sh --one-shot   # Process one plan and exit
#
# Environment variables (optional overrides):
#   PLAN_REVIEW_ENABLED         Feature gate (default: 1)
#   PLAN_REVIEW_TEST_MODE       Deterministic responses (default: 0)
#   PLAN_REVIEW_MAX_ITERATIONS  Max review loop iterations (default: 5)
#   PLAN_REVIEW_VERBOSE         Detailed logging (default: 0)
#   PLAN_REVIEW_POLL_INTERVAL   Polling interval secs (default: 2)
#   PLAN_REVIEW_SESSION_ID      Claude session ID for --resume

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WATCHDOG="$SCRIPT_DIR/watchdog.py"
LOG_DIR="${SCRIPT_DIR}/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/watchdog_${TIMESTAMP}.log"

# ── Argument Parsing ────────────────────────────────────────────────────────

EXTRA_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --test)
            export PLAN_REVIEW_TEST_MODE=1
            export PLAN_REVIEW_VERBOSE=1
            ;;
        --one-shot)
            EXTRA_ARGS+=("--one-shot")
            ;;
        --verbose|-v)
            export PLAN_REVIEW_VERBOSE=1
            ;;
        *)
            EXTRA_ARGS+=("$arg")
            ;;
    esac
done

# ── Dependency check: inotifywait ────────────────────────────────────────────

if ! command -v inotifywait &>/dev/null; then
    echo "WARNING: inotifywait not found — watchdog will use polling fallback."
    echo "  Install for better performance: sudo apt-get install -y inotify-tools"
    echo ""
fi

# ── Set defaults ─────────────────────────────────────────────────────────────

export PLAN_REVIEW_ENABLED="${PLAN_REVIEW_ENABLED:-1}"
export PLAN_REVIEW_MAX_ITERATIONS="${PLAN_REVIEW_MAX_ITERATIONS:-5}"

# ── Prepare directories ─────────────────────────────────────────────────────

mkdir -p "$LOG_DIR"
mkdir -p "$REPO_DIR/proposals/plans"
mkdir -p "$HOME/.claude/plans"

# ── Launch ───────────────────────────────────────────────────────────────────

echo "════════════════════════════════════════════════════════════════"
echo "  Plan Review Watchdog"
echo "════════════════════════════════════════════════════════════════"
echo "  Timestamp:      $(date -Iseconds)"
echo "  Plans dir:      ~/.claude/plans/"
echo "  Proposals dir:  $REPO_DIR/proposals/plans/"
echo "  Test mode:      ${PLAN_REVIEW_TEST_MODE:-0}"
echo "  Max iterations: ${PLAN_REVIEW_MAX_ITERATIONS}"
echo "  Log file:       ${LOG_FILE}"
echo "════════════════════════════════════════════════════════════════"
echo ""

setsid python3 "$WATCHDOG" "${EXTRA_ARGS[@]}" \
    > "$LOG_FILE" 2>&1 &

WATCHDOG_PID=$!

echo "Watchdog running in background (PID: ${WATCHDOG_PID})."
echo ""
echo "Monitor with:"
echo "  tail -f ${LOG_FILE}"
echo ""
echo "Stop with:"
echo "  kill ${WATCHDOG_PID}"
echo ""
echo "PID written to: ${LOG_DIR}/watchdog.pid"

echo "$WATCHDOG_PID" > "${LOG_DIR}/watchdog.pid"
