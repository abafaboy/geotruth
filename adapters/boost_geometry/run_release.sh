#!/usr/bin/env bash
# Run wrapper for the Boost.Geometry latest-release adapter (contract: run_release.sh CASES.jsonl > RESULTS.jsonl).
# Build first with build.sh.  Extra flags (--no-fork, --reasons) are passed through.
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/boost-geometry}"
EXE="$BUILD_ROOT/bin/bg_adapter_release"
if [ ! -x "$EXE" ]; then
    echo "run_release.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
exec "$EXE" "$@"
