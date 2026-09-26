#!/bin/sh
# Re-runs every command whose output is pasted in FINAL.md / JTS_FINAL.md.
#   GEOS_PREFIX=/path/to/geos/install   JTS_JAR=/path/to/jts-core.jar
G=$GEOS_PREFIX/bin
echo "### geosop ($($G/geos-config --version))"
p() { printf '$ geosop'; for a in "$@"; do case "$a" in *' '*) printf " '%s'" "$a";; *) printf ' %s' "$a";; esac; done; echo; $G/geosop "$@" 2>&1; }
for S in e102 e103 e105 e-104; do
  A="POLYGON ((0 0, 2$S 0, 2$S 2$S, 0 2$S, 0 0))"
  B="POLYGON ((1$S 1$S, 3$S 1$S, 3$S 3$S, 1$S 3$S, 1$S 1$S))"
  for op in relate overlaps intersection union; do p -a "$A" -b "$B" $op; done
done
p -a 'LINESTRING (2 0, 2 2)' -b 'POINT (1 1)' orientationIndex
p -a 'LINESTRING (2e155 0, 2e155 2e155)' -b 'POINT (1e155 1e155)' orientationIndex
p -a 'POLYGON ((0 0, 2e155 0, 2e155 2e155, 0 2e155, 0 0))' -b 'POINT (1e155 1e155)' contains
p -a 'POLYGON ((0 0, 2e155 0, 2e155 2e155, 0 2e155, 0 0))' -b 'POLYGON ((1e155 1e155, 3e155 1e155, 3e155 3e155, 1e155 3e155, 1e155 1e155))' relate
p -a 'POLYGON ((0 0, 4e154 0, 4e154 4e154, 0 4e154, 0 0), (1e154 1e154, 1e154 2e154, 2e154 2e154, 2e154 1e154, 1e154 1e154))' isValid
p -a 'LINESTRING (0 0, 1e-200 0)' -b 'POINT (0 1e-200)' orientationIndex
p -a 'POLYGON ((0 0, 1e-200 0, 0 1e-200, 0 0))' isValid
p -a 'POLYGON ((0 0, 1.6e-162 0, 0 1.6e-162, 0 0))' isValid
p -a 'POLYGON ((0 0, 1.5e-162 0, 0 1.5e-162, 0 0))' isValid
p -a 'POLYGON ((0 0, 4e-200 0, 4e-200 4e-200, 0 4e-200, 0 0), (1e-200 1e-200, 1e-200 2e-200, 2e-200 2e-200, 2e-200 1e-200, 1e-200 1e-200))' isValid
p -a 'POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))' -b 'POINT (1e-200 1e-200)' contains
p -a 'POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))' -b 'POLYGON ((1e-200 1e-200, 3e-200 1e-200, 3e-200 3e-200, 1e-200 3e-200, 1e-200 1e-200))' relate
echo "### C API: final_segint.c"
cc final_segint.c $($G/geos-config --cflags) $($G/geos-config --clibs) -Wl,-rpath,$GEOS_PREFIX/lib -o segint && ./segint
echo "### C++: final_diag_intersection.cpp (raw CGAlgorithmsDD::intersection)"
g++ -std=c++17 final_diag_intersection.cpp $($G/geos-config --cflags) -L$GEOS_PREFIX/lib -lgeos -Wl,-rpath,$GEOS_PREFIX/lib -o diag_intersection && ./diag_intersection
echo "### C++: final_diag_filter_1e155.cpp"
g++ -std=c++17 final_diag_filter_1e155.cpp $($G/geos-config --cflags) -L$GEOS_PREFIX/lib -lgeos -Wl,-rpath,$GEOS_PREFIX/lib -o diag_filter_1e155 && ./diag_filter_1e155
if [ -n "$JTS_JAR" ]; then
  echo "### JTS: ExtremeScale.java"
  mkdir -p jcls && javac -cp "$JTS_JAR" -d jcls ExtremeScale.java && java -cp "$JTS_JAR:jcls" ExtremeScale
fi
