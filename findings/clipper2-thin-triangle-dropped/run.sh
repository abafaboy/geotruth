#!/usr/bin/env bash
# Build and run repro.cpp against a Clipper2 checkout.
#   CLIPPER2_SRC=/path/to/Clipper2 ./run.sh
# Uses only the public header clipper2/clipper.h plus the engine source file.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
C="${CLIPPER2_SRC:?set CLIPPER2_SRC to a Clipper2 checkout}"
OUT="${OUT:-/tmp/clipper2-thin-triangle-repro}"
echo "Clipper2 commit: $(git -C "$C" rev-parse HEAD 2>/dev/null || echo unknown)"
${CXX:-g++} -O2 -std=c++17 -I"$C/CPP/Clipper2Lib/include" "$HERE/repro.cpp" \
    "$C/CPP/Clipper2Lib/src/clipper.engine.cpp" -o "$OUT"
"$OUT"
