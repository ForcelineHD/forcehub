#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${FORCEHUB_PROJECT_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SRC="$ROOT/agent/cpp/forcehub_agent.cpp"
OUT_DIR="$ROOT/build/windows"
OUT="$OUT_DIR/ForceHubAgent.exe"

mkdir -p "$OUT_DIR"

if ! command -v x86_64-w64-mingw32-g++ >/dev/null 2>&1; then
  echo "mingw-w64 not found. Installing..."
  sudo apt update
  sudo apt install -y mingw-w64
fi

x86_64-w64-mingw32-g++ \
  -std=c++17 \
  -O2 \
  -static \
  -Wall \
  -Wextra \
  -Wno-cast-function-type \
  -o "$OUT" \
  "$SRC" \
  -lpsapi \
  -ladvapi32

echo "Built: $OUT"
file "$OUT"
ls -lh "$OUT"
