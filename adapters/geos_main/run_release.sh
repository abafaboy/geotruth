#!/usr/bin/env bash
# Run wrapper for the GEOS latest-release adapter (contract: run_release.sh CASES.jsonl > RESULTS.jsonl).
# Build first with `build.sh release`.  Extra flags (--v2, --timing, --no-fork) are passed through.
# BUILD_ROOT moves this build's tree (default $GEOTRUTH_BUILD_DIR/geos-release).
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/geos-release}"
EXE="$BUILD_ROOT/bin/geos_adapter"
if [ ! -x "$EXE" ]; then
    echo "run_release.sh: $EXE not found; run $(dirname "$0")/build.sh release first" >&2
    exit 2
fi
exec "$EXE" "$@"
