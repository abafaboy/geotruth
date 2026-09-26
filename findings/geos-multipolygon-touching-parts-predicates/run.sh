#!/bin/sh
# Build and run the repros. Needs: a C compiler, geos-config on PATH (or GEOS_CONFIG=...),
# python3 with shapely, a JDK and a jts-core jar (JTS_JAR=...).
set -e
cd "$(dirname "$0")"
GEOS_CONFIG=${GEOS_CONFIG:-geos-config}
cc -O1 -o /tmp/geos-touch-repro repro.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) \
   -Wl,-rpath,"$($GEOS_CONFIG --prefix)/lib"
/tmp/geos-touch-repro
python3 repro_shapely.py
if [ -n "$JTS_JAR" ]; then
  mkdir -p /tmp/jts-touch-repro
  javac -cp "$JTS_JAR" -d /tmp/jts-touch-repro Repro.java
  java -cp "$JTS_JAR:/tmp/jts-touch-repro" Repro
fi
