#!/bin/sh
# Build and run the repros for geos-relateng-segfault.
# Needs: a C compiler and geos-config on PATH (or GEOS_CONFIG=/path/to/geos-config);
# python3 with shapely; optionally a JDK and a jts-core jar (JTS_JAR=...);
# optionally PYTHONPATH=<geotruth>/src for the exact answers (exact_check.py).
#
# The outputs captured in this directory were made with:
#   GEOS main ae9cdd98b   GEOS_CONFIG=${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/geos-main/install/bin/geos-config
#   GEOS 3.15.0 d0228513a GEOS_CONFIG=${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/geos-release/install/bin/geos-config
#   JTS master 3ea61f8 / 1.20.0 (JTS_JAR=${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/jts-{main,release}/out/jts-core.jar)
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
OUT=${TMPDIR:-/tmp}/geos-relateng-segfault
mkdir -p "$OUT"

cc -std=c11 -O1 -o "$OUT/repro" repro.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) \
   -Wl,-rpath,"$($GEOS_CONFIG --prefix)/lib"
"$OUT/repro"

# the same with the geosop CLI (each line ends in "Segmentation fault", exit status 139)
GEOSOP="$($GEOS_CONFIG --prefix)/bin/geosop"
if [ -x "$GEOSOP" ]; then
  B1='GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), POLYGON EMPTY)'
  "$GEOSOP" -a 'POINT (2 1)' -b "$B1" relate || echo "[exit status $?]"
  "$GEOSOP" -a 'POINT (2 1)' -b "$B1" intersects || echo "[exit status $?]"
  "$GEOSOP" -a 'GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)' -b 'POINT EMPTY' relate || echo "[exit status $?]"
fi

python3 repro.py

if [ -n "$JTS_JAR" ]; then
  javac -cp "$JTS_JAR" -d "$OUT" Repro.java
  java -cp "$JTS_JAR:$OUT" Repro
fi

if python3 -c "import geotruth" 2>/dev/null; then
  python3 exact_check.py cases.jsonl
fi
