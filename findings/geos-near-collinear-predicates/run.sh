#!/bin/sh
# Build and run the repros.
#   GEOS_CONFIG=/path/to/geos-config  (default: geos-config on PATH)
#   JTS_JAR=/path/to/jts-core.jar     (optional; runs Repro.java)
# Python part needs shapely.
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
OUT=${TMPDIR:-/tmp}/geos-near-collinear-repro
mkdir -p "$OUT"

# 1. C API (repro.c): public GEOS C API only
cc -O1 -o "$OUT/repro" repro.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) \
   -Wl,-rpath,"$($GEOS_CONFIG --prefix)/lib"
"$OUT/repro"

# 2. Shapely (repro.py), with an exact standard-library check of the critical vertex
python3 repro.py

# 3. JTS (Repro.java): RelateNG and the default RelateOp
if [ -n "$JTS_JAR" ]; then
  javac -cp "$JTS_JAR" -d "$OUT" Repro.java
  java -cp "$JTS_JAR:$OUT" Repro
fi

# Diagnostic only (uses GEOS's installed C++ headers, not the C API):
#   c++ -std=c++17 rootcause_diag.cpp $($GEOS_CONFIG --cflags) -L$($GEOS_CONFIG --prefix)/lib -lgeos \
#       -Wl,-rpath,$($GEOS_CONFIG --prefix)/lib -o "$OUT/diag" && "$OUT/diag"
