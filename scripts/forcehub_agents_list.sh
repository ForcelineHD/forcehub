#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${FORCEHUB_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TOKEN_FILE="${FORCEHUB_AGENT_TOKEN_FILE:-$PROJECT_DIR/data/agent_token.txt}"
URL="${1:-${FORCEHUB_AGENTS_URL:-http://127.0.0.1:8001/api/agents}}"

cd "$PROJECT_DIR"

if [ ! -s "$TOKEN_FILE" ]; then
  echo "ERROR: missing agent token: $TOKEN_FILE" >&2
  exit 1
fi

TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"

curl -sS "$URL" \
  -H "X-ForceHub-Agent-Token: ${TOKEN}"
