#!/usr/bin/env bash
# ABOUTME: Start Vector — PID-guarded, idempotent. Safe to call multiple times.
# ABOUTME: Cleans stale JSONL data older than 3 days and oversized logs on each start.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
PID_DIR="$SCRIPT_DIR/pids"
LOG_DIR="$SCRIPT_DIR/logs"
DATA_DIR="$SCRIPT_DIR/data"
VECTOR_BIN="$BIN_DIR/vector"
VECTOR_PID="$PID_DIR/vector.pid"
VECTOR_CONFIG="$SCRIPT_DIR/vector.toml"

# Must be run from project root so relative paths in vector.toml resolve correctly
cd "$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

mkdir -p "$PID_DIR" "$LOG_DIR" "$DATA_DIR/jsonl/logs" "$DATA_DIR/jsonl/traces" "$DATA_DIR/jsonl/metrics"

# Cleanup stale data
find "$DATA_DIR/jsonl" -name "*.jsonl" -mtime +3 -delete 2>/dev/null || true
find "$LOG_DIR" -name "*.log" -size +10M -exec truncate -s 0 {} \; 2>/dev/null || true

# Install if missing
if [ ! -f "$VECTOR_BIN" ]; then
  echo "Vector binary not found — running install.sh first..."
  "$SCRIPT_DIR/install.sh"
fi

# PID guard — check if already running
if [ -f "$VECTOR_PID" ]; then
  PID=$(cat "$VECTOR_PID")
  if kill -0 "$PID" 2>/dev/null; then
    # Verify it's actually vector, not a recycled PID
    COMM=$(ps -p "$PID" -o comm= 2>/dev/null || true)
    if [[ "$COMM" == *vector* ]]; then
      echo "Vector already running (pid $PID) — skipping."
      exit 0
    fi
  fi
  rm -f "$VECTOR_PID"
fi

echo "Starting Vector..."
"$VECTOR_BIN" --config "$VECTOR_CONFIG" \
  > "$LOG_DIR/vector.log" 2>&1 &
VECTOR_PID_VALUE=$!
echo "$VECTOR_PID_VALUE" > "$VECTOR_PID"

# Post-start verification — background processes can crash immediately
sleep 0.5
if ! kill -0 "$VECTOR_PID_VALUE" 2>/dev/null; then
  echo "ERROR: Vector exited immediately. Check $LOG_DIR/vector.log"
  cat "$LOG_DIR/vector.log" | tail -20
  rm -f "$VECTOR_PID"
  exit 1
fi

echo "Vector started (pid $VECTOR_PID_VALUE)"
echo "  OTLP gRPC  : 127.0.0.1:4317"
echo "  OTLP HTTP  : 127.0.0.1:4318"
echo "  API        : 127.0.0.1:8686"
echo "  Logs       : $LOG_DIR/vector.log"
echo "  JSONL data : $DATA_DIR/jsonl/"
