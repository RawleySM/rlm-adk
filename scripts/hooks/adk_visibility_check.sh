#!/usr/bin/env bash
# preToolUse hook: reminds the model to include observability env vars
# when running `adk run` or `adk web` commands.
#
# Reads $TOOL_INPUT (JSON) from Claude Code, extracts the "command" field,
# and checks whether it contains adk run/web without the recommended env vars.
#
# Exit 0 = allow (advisory only). The reminder is printed to stderr.

set -euo pipefail

# Parse the command field from the JSON tool input
COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty')

# If no command or not an adk run/web invocation, exit silently
if [[ -z "$COMMAND" ]]; then
  exit 0
fi

if ! echo "$COMMAND" | grep -qE 'adk (run|web)'; then
  exit 0
fi

# Check which observability vars are already present
missing=()

if ! echo "$COMMAND" | grep -q 'RLM_ADK_DEBUG'; then
  missing+=("RLM_ADK_DEBUG=1")
fi

if ! echo "$COMMAND" | grep -q 'RLM_REPL_TRACE'; then
  missing+=("RLM_REPL_TRACE=1")
fi

# If all vars are present, exit silently (no nagging)
if [[ ${#missing[@]} -eq 0 ]]; then
  exit 0
fi

# Print advisory reminder to stderr
vars_str=$(IFS=' '; echo "${missing[*]}")
>&2 echo "REMINDER: Prepend observability env vars to your adk command:"
>&2 echo "  ${vars_str} ${COMMAND}"
>&2 echo ""
>&2 echo "  RLM_ADK_DEBUG=1    — stdout summary of tokens/calls/timings"
>&2 echo "  RLM_REPL_TRACE=1   — REPL execution tracing (LLM call timing, var snapshots, data flow)"

exit 0
