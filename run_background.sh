#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$APP_DIR/app.log"
PID_FILE="$APP_DIR/app.pid"

cd "$APP_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "generator.py is already running with PID $OLD_PID"
    echo "Logs: $LOG_FILE"
    exit 0
  fi
fi

nohup python3 -u generator.py >> "$LOG_FILE" 2>&1 &
NEW_PID="$!"
echo "$NEW_PID" > "$PID_FILE"

echo "Started generator.py in the background with PID $NEW_PID"
echo "Logs: $LOG_FILE"
echo "Follow logs with: tail -f \"$LOG_FILE\""
