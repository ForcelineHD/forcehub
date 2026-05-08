#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/flozi/projects/forcehub"
VENV="$PROJECT_DIR/.venv"
HOST="127.0.0.1"
PORT="8001"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$LOG_DIR/forcehub.pid"
LOG_FILE="$LOG_DIR/forcehub.log"

cd "$PROJECT_DIR"

if [ ! -f "$VENV/bin/activate" ]; then
  echo "ERROR: venv not found: $VENV"
  exit 1
fi

source "$VENV/bin/activate"
mkdir -p "$LOG_DIR"

TOKEN_FILE="$PROJECT_DIR/data/agent_token.txt"
mkdir -p "$PROJECT_DIR/data"

if [ ! -f "$TOKEN_FILE" ]; then
  openssl rand -hex 32 > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
fi

export FORCEHUB_AGENT_TOKEN="$(cat "$TOKEN_FILE")"

http_code() {
  curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/" || true
}

http_alive() {
  CODE="$(http_code)"
  case "$CODE" in
    200|301|302|401|403)
      echo "HTTP reachable: $CODE"
      return 0
      ;;
    *)
      echo "HTTP not ready: $CODE"
      return 1
      ;;
  esac
}

start() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ForceHub already running. PID: $(cat "$PID_FILE")"
    http_alive || true
    exit 0
  fi

  echo "Starting ForceHub on http://$HOST:$PORT ..."
  nohup python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  sleep 2

  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ForceHub started. PID: $(cat "$PID_FILE")"
    http_alive || {
      echo "Process is running, but HTTP check failed. Last logs:"
      tail -80 "$LOG_FILE"
      exit 1
    }
  else
    echo "Failed to start ForceHub."
    tail -80 "$LOG_FILE"
    exit 1
  fi
}

stop() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Stopping ForceHub. PID: $(cat "$PID_FILE")"
    kill "$(cat "$PID_FILE")" || true
    rm -f "$PID_FILE"
  else
    echo "ForceHub is not running."
    rm -f "$PID_FILE"
  fi
}

status() {
  echo "== Git =="
  git status --short --branch
  echo

  echo "== App process =="
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Running. PID: $(cat "$PID_FILE")"
  else
    echo "Not running."
  fi
  echo

  echo "== Port =="
  ss -ltnp | grep ":$PORT" || echo "Port $PORT not listening"
  echo

  echo "== HTTP =="
  http_alive || true
}

restart() {
  stop
  sleep 1
  start
}

test_all() {
  echo "== Python compile =="
  python -m py_compile app/main.py main.py

  echo
  echo "== Pytest =="
  pytest -q
}

logs() {
  tail -120 "$LOG_FILE"
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  test) test_all ;;
  logs) logs ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|test|logs}"
    exit 1
    ;;
esac
