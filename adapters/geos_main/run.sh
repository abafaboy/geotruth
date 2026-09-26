#!/usr/bin/env bash
# Run wrapper for the GEOS-main adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Build first with build.sh.  Extra flags (e.g. --no-fork) are passed through.
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/geos-main}"
EXE="$BUILD_ROOT/bin/geos_adapter"
if [ ! -x "$EXE" ]; then
    echo "run.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
exec "$EXE" "$@"
