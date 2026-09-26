#!/bin/sh
# Build and run the repros against one or more jts-core jars.
#   ./run.sh /path/to/jts-core-master.jar [/path/to/jts-core-1.20.0.jar ...]
# Build jts-core with adapters/jts_main/build.sh (master 3ea61f8, release 1.20.0) or Maven.
# exact_check.py (the expected answers, no JTS involved) needs PYTHONPATH=<geotruth>/src.
set -e
cd "$(dirname "$0")"
OUT=${TMPDIR:-/tmp}/jts-master-union-extreme-regression
for JAR in "$@"; do
  rm -rf "$OUT"; mkdir -p "$OUT"
  javac -cp "$JAR" -d "$OUT" Repro.java ScanScales.java
  echo "=== $JAR"
  java -cp "$JAR:$OUT" Repro
  java -Djts.overlay=ng -cp "$JAR:$OUT" Repro | sed -n '/^4\./,/^$/p'
  java -cp "$JAR:$OUT" ScanScales
done
