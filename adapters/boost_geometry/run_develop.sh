#!/usr/bin/env bash
# Run wrapper for the Boost.Geometry develop adapter (contract: run_develop.sh CASES.jsonl > RESULTS.jsonl).
# Build first with build.sh.  Extra flags (--no-fork, --reasons) are passed through.
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/boost-geometry}"
EXE="$BUILD_ROOT/bin/bg_adapter_develop"
if [ ! -x "$EXE" ]; then
    echo "run_develop.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
exec "$EXE" "$@"
