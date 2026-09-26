#!/bin/sh
# Build and run the repros (public APIs only).
#   GEOS_CONFIG=/path/to/geos-config   (default: geos-config on PATH)
#   JTS_JAR=/path/to/jts-core.jar      (optional: runs the Repro.java files)
# The Python repros need shapely (any 2.x; GEOS >= 3.13 inside for RelateNG).
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
OUT=${TMPDIR:-/tmp}/geos-relateng-line-end-skip
mkdir -p "$OUT"
LDFLAGS_GEOS="$($GEOS_CONFIG --clibs) -Wl,-rpath,$($GEOS_CONFIG --prefix)/lib"

echo "== line-end skip (computeLineEnds) and area-vertex skip (computeAreaVertex)"
cc -O1 -o "$OUT/repro" repro.c $($GEOS_CONFIG --cflags) $LDFLAGS_GEOS
"$OUT/repro"
python3 repro_shapely.py

echo "== covered-ring: linear / GC operand B not self-noded (GEOS >= 3.13.1)"
cc -O1 -o "$OUT/repro-covered-ring" covered-ring/repro.c $($GEOS_CONFIG --cflags) $LDFLAGS_GEOS
"$OUT/repro-covered-ring"
python3 covered-ring/repro_shapely.py

if [ -n "$JTS_JAR" ]; then
  mkdir -p "$OUT/jts1" "$OUT/jts2"
  javac -cp "$JTS_JAR" -d "$OUT/jts1" Repro.java && java -cp "$JTS_JAR:$OUT/jts1" Repro
  javac -cp "$JTS_JAR" -d "$OUT/jts2" covered-ring/Repro.java && java -cp "$JTS_JAR:$OUT/jts2" Repro
fi

# Exact answers (geotruth, from the repository root):
#   PYTHONPATH=src python3 -m geotruth relate --dual --id 'geos-relateng-line-end-skip:les-1' \
#       @findings/geos-relateng-line-end-skip/cases.jsonl
