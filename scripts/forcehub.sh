#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${FORCEHUB_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV="${FORCEHUB_VENV:-$PROJECT_DIR/.venv}"
HOST="127.0.0.1"
PORT="8001"
LOG_DIR="${FORCEHUB_LOG_DIR:-$PROJECT_DIR/logs}"
PID_FILE="$LOG_DIR/forcehub.pid"
LOG_FILE="$LOG_DIR/forcehub.log"

cd "$PROJECT_DIR"

if [ ! -f "$VENV/bin/activate" ]; then
  echo "ERROR: venv not found: $VENV"
  exit 1
fi

source "$VENV/bin/activate"
mkdir -p "$LOG_DIR"

# FORCEHUB_AUTH_DEFAULTS
# Load local environment if present, then preserve caller-provided values.
# Authentication is enabled by default; set FORCEHUB_AUTH_DISABLED=1 only for an intentionally unauthenticated local instance.
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

export FORCEHUB_AUTH_DISABLED="${FORCEHUB_AUTH_DISABLED:-0}"

TOKEN_FILE="${FORCEHUB_AGENT_TOKEN_FILE:-$PROJECT_DIR/data/agent_token.txt}"

load_agent_token() {
  local token_source

  if [ -n "${FORCEHUB_AGENT_TOKEN:-}" ]; then
    FORCEHUB_AGENT_TOKEN="$(printf '%s' "$FORCEHUB_AGENT_TOKEN" | tr -d '\r\n')"
    token_source="env"
  else
    mkdir -p "$(dirname "$TOKEN_FILE")"
    chmod 700 "$(dirname "$TOKEN_FILE")"

    if [ ! -f "$TOKEN_FILE" ]; then
      umask 077
      openssl rand -hex 32 > "$TOKEN_FILE"
      chmod 600 "$TOKEN_FILE"
    fi

    FORCEHUB_AGENT_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
    token_source="data/agent_token.txt"
  fi

  export FORCEHUB_AGENT_TOKEN
  echo "agent token loaded"
  echo "agent token source: $token_source"
  echo "agent token length: ${#FORCEHUB_AGENT_TOKEN}"
}

validate_auth_config() {
  if [ "$FORCEHUB_AUTH_DISABLED" = "1" ]; then
    echo "WARNING: ForceHub authentication is disabled for this local instance."
    return 0
  fi

  if [ -z "${FORCEHUB_USERNAME:-}" ]; then
    echo "ERROR: FORCEHUB_USERNAME is required unless FORCEHUB_AUTH_DISABLED=1 is explicitly set." >&2
    exit 1
  fi

  if [ -z "${FORCEHUB_PASSWORD:-}" ] && [ -z "${FORCEHUB_PASSWORD_FILE:-}" ]; then
    echo "ERROR: FORCEHUB_PASSWORD or FORCEHUB_PASSWORD_FILE is required unless FORCEHUB_AUTH_DISABLED=1 is explicitly set." >&2
    exit 1
  fi

  if [ "${FORCEHUB_USERNAME:-}" = "admin" ] && { [ "${FORCEHUB_PASSWORD:-}" = "forcehub" ] || [ "${FORCEHUB_PASSWORD:-}" = "change-me-local-only" ]; }; then
    echo "ERROR: refusing to start with insecure default credentials." >&2
    echo "Set FORCEHUB_USERNAME and FORCEHUB_PASSWORD or FORCEHUB_PASSWORD_FILE to private values." >&2
    echo "For intentionally unauthenticated local testing, set FORCEHUB_AUTH_DISABLED=1." >&2
    exit 1
  fi
}



agent_api_code() {
  curl -s -o /dev/null -w "%{http_code}" \
    -H "X-ForceHub-Agent-Token: ${FORCEHUB_AGENT_TOKEN:-}" \
    "http://$HOST:$PORT/api/agents" || true
}

agent_api_alive() {
  CODE="$(agent_api_code)"
  case "$CODE" in
    200)
      echo "Agent API reachable: $CODE"
      return 0
      ;;
    *)
      echo "Agent API check failed: $CODE"
      return 1
      ;;
  esac
}

start() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ForceHub already running. PID: $(cat "$PID_FILE")"
    load_agent_token
    agent_api_alive || true
    exit 0
  fi

  validate_auth_config
  load_agent_token

  echo "Starting ForceHub on http://$HOST:$PORT ..."
  nohup "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  sleep 2

  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ForceHub started. PID: $(cat "$PID_FILE")"
    agent_api_alive || {
      echo "Process is running, but Agent API check failed. Last logs:"
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
  load_agent_token
  agent_api_alive || true
}

restart() {
  validate_auth_config
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
