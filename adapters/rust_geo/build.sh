#!/usr/bin/env bash
# Release build of the geo adapter. The build tree stays outside the repo:
#   $CARGO_TARGET_DIR (default /tmp/claude-0/gb-build/rust-geo/target)
# Cargo.lock pins geo and every transitive crate; `UPDATE=1 build.sh` refreshes it to the
# newest versions allowed by Cargo.toml first.
# Env overrides: CARGO_TARGET_DIR, JOBS (default 2), UPDATE.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/claude-0/gb-build/rust-geo/target}"
JOBS="${JOBS:-2}"
cd "$HERE"
if [ "${UPDATE:-0}" = 1 ]; then
    cargo update
fi
cargo build --release --locked -j"$JOBS"
EXE="$CARGO_TARGET_DIR/release/geo_adapter"
echo "built $EXE ($("$EXE" --version))"
