#!/bin/sh
# Build and run the repros.
#   GEOS_CONFIG=/path/to/geos-config  (default: geos-config on PATH)
#   JTS_JAR=/path/to/jts-core.jar     (optional; runs Repro.java and ScanScales.java)
# The Python part needs shapely; exact_check.py needs ../../oracle_review.
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
OUT=${TMPDIR:-/tmp}/geos-tiny-coordinates-repro
mkdir -p "$OUT"
RPATH="-Wl,-rpath,$($GEOS_CONFIG --prefix)/lib"

# 1. C API: the minimal cases at unit scale and at 1e-200, then a scan over 1e-320..1e307,
#    then GEOSOrientationIndex / GEOSSegmentIntersection under exact 2^k scaling
cc -O1 -o "$OUT/repro" repro.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) $RPATH
"$OUT/repro"
cc -O1 -o "$OUT/scan_scales" scan_scales.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) -lm $RPATH
"$OUT/scan_scales"
# the two numeric primitives under exact power-of-two scaling
cc -O1 -o "$OUT/primitives_scaling" primitives_scaling.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) -lm $RPATH
"$OUT/primitives_scaling"
# 20,000 random near-collinear triples under exact 2^k scaling (ctypes -> GEOSOrientationIndex_r)
GEOS_C_LIB="$($GEOS_CONFIG --prefix)/lib/libgeos_c.so" python3 orientation_random_scaling.py

# 2. Shapely (whatever GEOS it bundles)
python3 repro.py

# 3. JTS
if [ -n "$JTS_JAR" ]; then
  javac -cp "$JTS_JAR" -d "$OUT" Repro.java ScanScales.java
  java -cp "$JTS_JAR:$OUT" Repro
  java -cp "$JTS_JAR:$OUT" ScanScales
fi

# 4. Exact (rational) check of the expected answers; no GEOS involved
python3 exact_check.py
