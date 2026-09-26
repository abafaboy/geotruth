#!/usr/bin/env bash
# Build and run the reproducers.
#   GEOS_CONFIG=/path/to/geos-config ./run.sh          # C reproducer against that GEOS build
#   JTS_JAR=/path/to/jts-core.jar ./run.sh              # also run the JTS reproducer
#   PYTHON=python3 ./run.sh                             # also run the Shapely reproducer
# Only public APIs are used (GEOS C API, JTS WKTReader/OverlayNGRobust, Shapely).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${OUT:-/tmp/geos-union-drops-polygon-repro}"
mkdir -p "$OUT"
if [ -n "${GEOS_CONFIG:-}" ]; then
    LIBDIR="$("$GEOS_CONFIG" --prefix)/lib"
    ${CC:-cc} -std=c11 -Wall -o "$OUT/repro" "$HERE/repro.c" \
        $("$GEOS_CONFIG" --cflags) $("$GEOS_CONFIG" --clibs) \
        -Wl,--disable-new-dtags,-rpath,"$LIBDIR"
    "$OUT/repro"
fi
if [ -n "${JTS_JAR:-}" ]; then
    javac -d "$OUT" -cp "$JTS_JAR" "$HERE/Repro.java"
    java -cp "$JTS_JAR:$OUT" Repro
fi
if [ -n "${PYTHON:-}" ]; then
    "$PYTHON" "$HERE/repro.py"
fi
