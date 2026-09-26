#!/usr/bin/env bash
# Run wrapper for the Clipper2 adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Build first with build.sh. Flags are passed through:
#   --fill nonzero   NonZero fill rule with shells CCW / holes CW (default: EvenOdd)
#   --pathsd8        ClipperD with precision 8 (exact cases only, else errors.unsupported)
#   --strict-range   unsupported when a scaled coordinate exceeds Clipper2's MAX_COORD (2^61-1)
#   --timeout S      per-case budget (default 10 s); --no-fork runs without isolation
set -euo pipefail
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/clipper2}"
EXE="$BUILD_ROOT/bin/clipper2_adapter"
if [ ! -x "$EXE" ]; then
    echo "run.sh: $EXE not found; run $(dirname "$0")/build.sh first" >&2
    exit 2
fi
exec "$EXE" "$@"
