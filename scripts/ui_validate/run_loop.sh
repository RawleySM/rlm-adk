#!/usr/bin/env bash
# run_loop.sh — Entry point for overnight UI validation loop.
#
# Usage patterns:
#   1. Direct run (validate 5 items):
#      ./scripts/ui_validate/run_loop.sh
#
#   2. Run with custom item count:
#      ./scripts/ui_validate/run_loop.sh --max-items 10
#
#   3. Dry run (preview only):
#      ./scripts/ui_validate/run_loop.sh --dry-run
#
#   4. Via Claude Code /loop (every 10 minutes):
#      /loop 10m run scripts/ui_validate/run_loop.sh
#
#   5. Via headless Claude Code invocation:
#      claude --print "run scripts/ui_validate/run_loop.sh --max-items 3"
#
#   6. Standalone overnight cron-style loop (no Claude Code needed):
#      ./scripts/ui_validate/run_loop.sh --loop --interval 600
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VALIDATE_SCRIPT="$SCRIPT_DIR/validate_dashboard.py"
MANIFEST="$SCRIPT_DIR/manifest.json"
LOG_DIR="$SCRIPT_DIR/logs"
LOOP_MODE=false
LOOP_INTERVAL=600  # seconds (10 minutes default)

mkdir -p "$LOG_DIR"

# Parse arguments
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --loop)
            LOOP_MODE=true
            shift
            ;;
        --interval)
            LOOP_INTERVAL="$2"
            shift 2
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

run_once() {
    local timestamp
    timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
    local log_file="$LOG_DIR/run_${timestamp}.log"

    echo "=== UI Validation Run: $timestamp ===" | tee "$log_file"
    echo "Manifest: $MANIFEST" | tee -a "$log_file"

    # Check manifest progress
    local total checked remaining
    total=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['summary']['total_items'])")
    checked=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(sum(1 for i in m['items'] if i['checked']))")
    remaining=$((total - checked))

    echo "Progress: $checked/$total validated ($remaining remaining)" | tee -a "$log_file"

    if [ "$remaining" -eq 0 ]; then
        echo "ALL ITEMS VALIDATED. Nothing left to do." | tee -a "$log_file"
        return 1  # Signal completion
    fi

    # Run the validation script
    cd "$PROJECT_ROOT"
    if "$PROJECT_ROOT/.venv/bin/python" "$VALIDATE_SCRIPT" "${PASSTHROUGH_ARGS[@]}" 2>&1 | tee -a "$log_file"; then
        echo "Run completed successfully." | tee -a "$log_file"
    else
        echo "Run encountered errors (exit code $?)." | tee -a "$log_file"
    fi

    # Print updated progress
    checked=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(sum(1 for i in m['items'] if i['checked']))")
    remaining=$((total - checked))
    echo "Updated progress: $checked/$total validated ($remaining remaining)" | tee -a "$log_file"

    return 0
}

if [ "$LOOP_MODE" = true ]; then
    echo "Starting overnight validation loop (interval: ${LOOP_INTERVAL}s)"
    echo "Press Ctrl+C to stop"
    echo "Logs: $LOG_DIR/"
    echo ""

    iteration=0
    while true; do
        iteration=$((iteration + 1))
        echo "--- Loop iteration $iteration ($(date)) ---"

        if ! run_once; then
            echo "All items validated. Stopping loop."
            break
        fi

        echo "Sleeping ${LOOP_INTERVAL}s until next run..."
        sleep "$LOOP_INTERVAL"
    done
else
    run_once
fi
