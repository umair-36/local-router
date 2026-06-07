#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PID_FILE="server.pid"
LOG_FILE="server.log"

if [ "${1:-}" = "--down" ]; then
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
  pkill -f "uvicorn api_server:app" 2>/dev/null || true
  echo "down"
  exit 0
fi

if [ ! -f server.env ]; then
  echo "missing server.env; run ./setup_server.sh <weights-url> first" >&2
  exit 2
fi

set -a
. ./server.env
set +a

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "already up: http://${HOST:-127.0.0.1}:${PORT:-8000}"
  exit 0
fi

. .venv/bin/activate

(
  while true; do
    python -m uvicorn api_server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
    sleep 2
  done
) >>"$LOG_FILE" 2>&1 &

echo "$!" > "$PID_FILE"
echo "up: http://${HOST:-127.0.0.1}:${PORT:-8000}"
