#!/usr/bin/env bash
# Run wrapper for the GEOS git-main adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Build first with `build.sh main`.  Extra flags (--v2, --timing, --no-fork) are passed through.
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/geos-main}"
EXE="$BUILD_ROOT/bin/geos_adapter"
if [ ! -x "$EXE" ]; then
    echo "run.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
exec "$EXE" "$@"
