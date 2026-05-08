#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$HOME/.cargo/env"

cd "$PROJECT_DIR/rust/forcehub-secscan"

cargo fmt --check
cargo check
cargo test
cargo build --release

"$PROJECT_DIR/rust/forcehub-secscan/target/release/forcehub-secscan" "$PROJECT_DIR"
