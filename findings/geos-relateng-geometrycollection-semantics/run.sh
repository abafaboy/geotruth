#!/bin/sh
# Build and run the repros (public APIs only).
#   GEOS_CONFIG=/path/to/geos-config   (default: geos-config on PATH)
#   JTS_JAR=/path/to/jts-core.jar      (optional: runs Repro.java with JTS RelateNG)
#   PYTHON=python3                     (optional: runs repro.py; needs shapely 2.x)
# Exact answers: from the repository root,
#   PYTHONPATH=src python3 findings/geos-relateng-geometrycollection-semantics/exact_check.py
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
PYTHON=${PYTHON:-python3}
OUT=${TMPDIR:-/tmp}/geos-relateng-geometrycollection-semantics
mkdir -p "$OUT"

echo "== GEOS C API"
cc -std=c11 -O1 -o "$OUT/repro" repro.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) \
   -Wl,-rpath,"$($GEOS_CONFIG --prefix)/lib"
"$OUT/repro"

if "$PYTHON" -c "import shapely" 2>/dev/null; then
  echo "== Shapely"
  "$PYTHON" repro.py
fi

if [ -n "$JTS_JAR" ]; then
  echo "== JTS RelateNG"
  mkdir -p "$OUT/jts"
  javac -cp "$JTS_JAR" -d "$OUT/jts" Repro.java
  java -cp "$JTS_JAR:$OUT/jts" Repro
fi
