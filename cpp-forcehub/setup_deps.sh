#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p external

if [ ! -d external/Crow ]; then
  git clone --depth 1 https://github.com/CrowCpp/Crow.git external/Crow
fi

echo "C++ deps ready"
