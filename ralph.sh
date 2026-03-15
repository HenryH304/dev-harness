#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop
# Usage: ./ralph.sh [max_iterations] [tool]
# tool defaults to 'claude', can be set to 'opencode'

# Don't use set -e - we handle errors ourselves
MAX_ITERATIONS=${1:-10}
TOOL=${2:-claude}
MAX_RETRIES=3
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"

# Archive previous run if branch changed
if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    # Archive the previous run
    DATE=$(date +%Y-%m-%d)
    # Strip "ralph/" prefix from branch name for folder
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"

    echo "Archiving previous run: $LAST_BRANCH"
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"

    # Reset progress file for new run
    echo "# Ralph Progress Log" > "$PROGRESS_FILE"
    echo "Started: $(date)" >> "$PROGRESS_FILE"
    echo "---" >> "$PROGRESS_FILE"
  fi
fi

# Track current branch
if [ -f "$PRD_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  if [ -n "$CURRENT_BRANCH" ]; then
    echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
  fi
fi

# Initialize progress file if it doesn't exist
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

echo "Starting Ralph - Max iterations: $MAX_ITERATIONS"

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "  Ralph Iteration $i of $MAX_ITERATIONS - $(date '+%Y-%m-%d %H:%M:%S')"
  echo "═══════════════════════════════════════════════════════"

  # Retry loop for transient API errors
  RETRY_COUNT=0
  SUCCESS=false

  while [ $RETRY_COUNT -lt $MAX_RETRIES ] && [ "$SUCCESS" = "false" ]; do
    if [ $RETRY_COUNT -gt 0 ]; then
      echo ""
      echo "[$(date '+%H:%M:%S')] Retry attempt $RETRY_COUNT of $MAX_RETRIES starting..."
    else
      echo "[$(date '+%H:%M:%S')] Starting session..."
    fi

    # Run tool with the ralph prompt (capture output to log)
    # Use subshell and || true to prevent SIGPIPE or crashes from killing the script
    if [ "$TOOL" = "claude" ]; then
      (cat "$SCRIPT_DIR/prompt.md" | claude --dangerously-skip-permissions -p 2>&1 || true) | tee "$SCRIPT_DIR/ralph.log"
      EXIT_CODE=${PIPESTATUS[0]}
    else
      (opencode run --model "opencode/grok-code" "$(cat "$SCRIPT_DIR/prompt.md")" 2>&1 || true) | tee "$SCRIPT_DIR/ralph.log"
      EXIT_CODE=${PIPESTATUS[0]}
    fi
    OUTPUT=$(cat "$SCRIPT_DIR/ralph.log")

    echo ""
    echo "[$(date '+%H:%M:%S')] Session ended (exit code: $EXIT_CODE)"

    # Check for transient API errors
    if echo "$OUTPUT" | grep -qE "(No messages returned|ECONNRESET|ETIMEDOUT|rate limit|503|502)"; then
      RETRY_COUNT=$((RETRY_COUNT + 1))
      ERROR_TYPE=$(echo "$OUTPUT" | grep -oE "(No messages returned|ECONNRESET|ETIMEDOUT|rate limit|503|502)" | head -1)
      echo "[$(date '+%H:%M:%S')] WARNING: Transient error detected: $ERROR_TYPE"

      if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo "[$(date '+%H:%M:%S')] Waiting 10 seconds before retry $RETRY_COUNT of $MAX_RETRIES..."
        sleep 10
      else
        echo "[$(date '+%H:%M:%S')] FAILED: Max retries ($MAX_RETRIES) reached. Moving to next iteration..."
        SUCCESS=true
      fi
    elif [ $EXIT_CODE -ne 0 ]; then
      # Non-zero exit but not a known transient error
      echo "[$(date '+%H:%M:%S')] WARNING: Exited with code $EXIT_CODE (non-transient). Continuing..."
      SUCCESS=true
    else
      echo "[$(date '+%H:%M:%S')] Session completed successfully"
      SUCCESS=true
    fi
  done

  # Check for completion signal
  if echo "$OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "  Ralph completed all tasks!"
    echo "  Finished at iteration $i of $MAX_ITERATIONS"
    echo "  Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "════════════════════════════════════════════════════════"
    exit 0
  fi

  echo ""
  echo "[$(date '+%H:%M:%S')] Iteration $i complete. Starting next iteration in 2 seconds..."
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status."
exit 1