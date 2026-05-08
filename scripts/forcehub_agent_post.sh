#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/flozi/projects/forcehub"
TOKEN_FILE="$PROJECT_DIR/data/agent_token.txt"
URL="${1:-http://127.0.0.1:8001/api/agents/checkin}"

cd "$PROJECT_DIR"

if [ ! -s "$TOKEN_FILE" ]; then
  echo "ERROR: missing agent token: $TOKEN_FILE" >&2
  exit 1
fi

TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"

curl -sS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "X-ForceHub-Agent-Token: ${TOKEN}" \
  --data-binary @-
