#!/usr/bin/env bash
# Build and run repro.cpp against a Clipper2 checkout.
#   CLIPPER2_SRC=/path/to/Clipper2 ./run.sh
# CLIPPER2_SRC defaults to the Clipper2 adapter's clone, $GEOTRUTH_BUILD_DIR/clipper2/src
# (adapters/clipper2/build.sh; GEOTRUTH_BUILD_DIR defaults to ~/.cache/geotruth).
# Uses only the public header clipper2/clipper.h plus the engine source file.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
C="${CLIPPER2_SRC:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/clipper2/src}"
if [ ! -f "$C/CPP/Clipper2Lib/include/clipper2/clipper.h" ]; then
    echo "run.sh: no Clipper2 checkout at $C; set CLIPPER2_SRC or run adapters/clipper2/build.sh" >&2
    exit 2
fi
OUT="${OUT:-/tmp/clipper2-thin-triangle-repro}"
echo "Clipper2 commit: $(git -C "$C" rev-parse HEAD 2>/dev/null || echo unknown)"
${CXX:-g++} -O2 -std=c++17 -I"$C/CPP/Clipper2Lib/include" "$HERE/repro.cpp" \
    "$C/CPP/Clipper2Lib/src/clipper.engine.cpp" -o "$OUT"
"$OUT"
