#!/usr/bin/env bash
# ABOUTME: Stop Vector — SIGTERM with SIGKILL fallback after 5s.
# ABOUTME: No-ops gracefully if Vector is not running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/pids"
VECTOR_PID_FILE="$PID_DIR/vector.pid"

stop_service() {
  local name="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    echo "$name not running (no PID file)."
    return 0
  fi

  local pid
  pid=$(cat "$pid_file")

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name not running (stale PID $pid)."
    rm -f "$pid_file"
    return 0
  fi

  echo "Stopping $name (pid $pid)..."
  kill -TERM "$pid"

  # Wait up to 5s for graceful shutdown
  local i=0
  while kill -0 "$pid" 2>/dev/null && [ $i -lt 10 ]; do
    sleep 0.5
    ((i++))
  done

  if kill -0 "$pid" 2>/dev/null; then
    echo "$name did not stop gracefully — sending SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
  fi

  rm -f "$pid_file"
  echo "$name stopped."
}

stop_service "Vector" "$VECTOR_PID_FILE"
