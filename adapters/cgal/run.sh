#!/usr/bin/env bash
# Run wrapper for the CGAL adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Build first with build.sh. Flags are passed through: --v2, --exact SIDECAR.jsonl, --timing,
# --no-fork, --version.
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/cgal}"
EXE="$BUILD_ROOT/bin/cgal_adapter"
if [ ! -x "$EXE" ]; then
    echo "run.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
exec "$EXE" "$@"
