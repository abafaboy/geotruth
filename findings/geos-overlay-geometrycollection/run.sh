#!/bin/sh
# Build and run the repros for geos-overlay-geometrycollection.
# Needs: a C compiler and geos-config on PATH (or GEOS_CONFIG=/path/to/geos-config);
# optionally python3 with shapely (repro.py), a JDK and a jts-core jar (JTS_JAR=..., runs
# Repro.java for contrast) and the geotruth package (PYTHONPATH=<geotruth>/src, runs
# exact_check.py: exact answers, certificates and the hand checks).
#
# The captured outputs in this directory were made with:
#   GEOS main ae9cdd98b  GEOS_CONFIG=${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/geos-main/install/bin/geos-config
#   GEOS 3.15.0 d0228513a GEOS_CONFIG=${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/geos-release/install/bin/geos-config
#   GEOS 3.13.0 d7957246 (built from the tag), main + prototype_fix.diff
#   Shapely 2.0.7 (GEOS 3.11.4), 2.1.2 (GEOS 3.13.1), 2.2.0rc1 (GEOS 3.14.1) wheels
#   JTS master 3ea61f8 / 1.20.0 6e95fe82
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
OUT=${TMPDIR:-/tmp}/geos-overlay-geometrycollection
mkdir -p "$OUT"

cc -std=c11 -O1 -o "$OUT/repro" repro.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) \
   -Wl,-rpath,"$($GEOS_CONFIG --prefix)/lib"
"$OUT/repro"

# the same through the geosop CLI
GEOSOP="$($GEOS_CONFIG --prefix)/bin/geosop"
if [ -x "$GEOSOP" ]; then
  "$GEOSOP" -a 'GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))' -b 'POINT (3 3)' symDifference
  "$GEOSOP" -a 'POINT (1 0)' -b 'GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))' difference
  "$GEOSOP" -a 'GEOMETRYCOLLECTION (POLYGON EMPTY)' -b 'POINT (1 1)' intersection || echo "[exit status $?]"
fi

if python3 -c "import shapely" 2>/dev/null; then
  python3 repro.py
fi

if [ -n "$JTS_JAR" ]; then
  javac -cp "$JTS_JAR" -d "$OUT" Repro.java
  java -cp "$JTS_JAR:$OUT" Repro "$(basename "$JTS_JAR")"
fi

if python3 -c "import geotruth" 2>/dev/null; then
  python3 exact_check.py cases.jsonl
fi
