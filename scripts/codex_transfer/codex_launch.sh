#!/usr/bin/env bash
# codex_launch.sh -- Launch Codex CLI headlessly to continue a task from Claude Code
#
# Usage:
#   ./codex_launch.sh <handoff_doc_path> [additional_context]
#
# Arguments:
#   handoff_doc_path   -- Absolute path to the handoff document
#   additional_context -- Optional extra instructions (string)
#
# Environment variables (optional overrides):
#   CODEX_MODEL          -- Model to use (default: gpt-5.4)
#   CODEX_REPO_DIR       -- Repository root (default: /home/rawley-stanhope/dev/rlm-adk)
#   CODEX_BIN            -- Path to codex binary (default: ~/.npm-global/bin/codex)
#   CODEX_LOG_DIR        -- Directory for logs (default: ./logs)
#   CODEX_OUTPUT_REPORT  -- Where codex writes its completion report

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${CODEX_REPO_DIR:-/home/rawley-stanhope/dev/rlm-adk}"
CODEX_BIN="${CODEX_BIN:-$HOME/.npm-global/bin/codex}"
MODEL="${CODEX_MODEL:-gpt-5.4}"
LOG_DIR="${CODEX_LOG_DIR:-${SCRIPT_DIR}/logs}"
TEMPLATE_PATH="${SCRIPT_DIR}/docs/codex_prompt_template.md"

CLAUDE_MEMORY_PATH="$HOME/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/memory/MEMORY.md"
CLAUDE_SESSION_DIR="$HOME/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/"

# ── Argument Parsing ────────────────────────────────────────────────────────

if [ $# -lt 1 ]; then
    echo "Usage: $0 <handoff_doc_path> [additional_context]"
    echo ""
    echo "  handoff_doc_path   Absolute path to the handoff document"
    echo "  additional_context Optional extra instructions (quoted string)"
    exit 1
fi

HANDOFF_DOC_PATH="$1"
ADDITIONAL_CONTEXT="${2:-}"

# Validate handoff doc exists
if [ ! -f "$HANDOFF_DOC_PATH" ]; then
    echo "ERROR: Handoff document not found: $HANDOFF_DOC_PATH"
    exit 1
fi

# Validate codex binary exists
if [ ! -x "$CODEX_BIN" ]; then
    echo "ERROR: Codex CLI not found at: $CODEX_BIN"
    exit 1
fi

# ── Prepare Directories ─────────────────────────────────────────────────────

mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RUN_ID="transfer_${TIMESTAMP}"
OUTPUT_REPORT="${CODEX_OUTPUT_REPORT:-${SCRIPT_DIR}/completion_report_${TIMESTAMP}.md}"

LOG_EVENTS="${LOG_DIR}/${RUN_ID}_events.jsonl"
LOG_STDERR="${LOG_DIR}/${RUN_ID}_stderr.log"
LOG_RESULT="${LOG_DIR}/${RUN_ID}_result.md"
TRANSFER_LOG="${LOG_DIR}/transfer_log.txt"

# ── Extract Prompt Template ─────────────────────────────────────────────────

# Extract the template block from the markdown file (content between the
# first pair of ``` fences after "## Template")
TEMPLATE_RAW="$(sed -n '/^## Template$/,/^---$/p' "$TEMPLATE_PATH" \
    | sed -n '/^```$/,/^```$/p' \
    | sed '1d;$d')"

# ── Substitute Variables ─────────────────────────────────────────────────────

PROMPT="$TEMPLATE_RAW"
PROMPT="${PROMPT//\{\{HANDOFF_DOC_PATH\}\}/$HANDOFF_DOC_PATH}"
PROMPT="${PROMPT//\{\{CLAUDE_MEMORY_PATH\}\}/$CLAUDE_MEMORY_PATH}"
PROMPT="${PROMPT//\{\{CLAUDE_SESSION_DIR\}\}/$CLAUDE_SESSION_DIR}"
PROMPT="${PROMPT//\{\{ADDITIONAL_CONTEXT\}\}/$ADDITIONAL_CONTEXT}"
PROMPT="${PROMPT//\{\{OUTPUT_REPORT_PATH\}\}/$OUTPUT_REPORT}"

# ── Log the Launch ───────────────────────────────────────────────────────────

{
    echo "════════════════════════════════════════════════════════════════"
    echo "Transfer Launch: ${RUN_ID}"
    echo "Timestamp:       $(date -Iseconds)"
    echo "Handoff Doc:     ${HANDOFF_DOC_PATH}"
    echo "Model:           ${MODEL}"
    echo "Repo Dir:        ${REPO_DIR}"
    echo "Output Report:   ${OUTPUT_REPORT}"
    echo "Event Log:       ${LOG_EVENTS}"
    echo "Stderr Log:      ${LOG_STDERR}"
    echo "Result File:     ${LOG_RESULT}"
    echo "Additional Ctx:  ${ADDITIONAL_CONTEXT:-<none>}"
    echo "════════════════════════════════════════════════════════════════"
} | tee -a "$TRANSFER_LOG"

# ── Launch Codex (Detached) ──────────────────────────────────────────────────

echo ""
echo "Launching Codex headlessly..."

setsid "$CODEX_BIN" exec \
    --dangerously-bypass-approvals-and-sandbox \
    --enable multi_agent \
    --enable child_agents_md \
    -m "$MODEL" \
    -c model_reasoning_effort="high" \
    -C "$REPO_DIR" \
    -o "$LOG_RESULT" \
    --json \
    - <<< "$PROMPT" \
    > "$LOG_EVENTS" 2>"$LOG_STDERR" &

CODEX_PID=$!

{
    echo "PID:             ${CODEX_PID}"
    echo "Status:          LAUNCHED"
    echo ""
} | tee -a "$TRANSFER_LOG"

echo "Codex is running in the background (PID: ${CODEX_PID})."
echo ""
echo "Monitor with:"
echo "  tail -f ${LOG_STDERR}              # stderr / progress"
echo "  tail -f ${LOG_EVENTS}              # JSONL event stream"
echo "  cat ${LOG_RESULT}                  # final agent message (when done)"
echo "  cat ${OUTPUT_REPORT}               # completion report (when done)"
echo "  kill ${CODEX_PID}                  # abort"
echo ""
echo "Transfer logged to: ${TRANSFER_LOG}"
