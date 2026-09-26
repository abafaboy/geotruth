#!/usr/bin/env bash
# Run wrapper for the geo adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Build first with build.sh. Flags (e.g. --in-process) are passed through.
# Env: GEO_ADAPTER_TIMEOUT (s per operation, default 10), GEO_ADAPTER_MEM_MB (worker
# address-space limit, default 4096, 0 = none), RAYON_NUM_THREADS (default 1 here).
set -euo pipefail
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/claude-0/gb-build/rust-geo/target}"
EXE="$CARGO_TARGET_DIR/release/geo_adapter"
if [ ! -x "$EXE" ]; then
    echo "run.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-1}"
exec "$EXE" "$@"
