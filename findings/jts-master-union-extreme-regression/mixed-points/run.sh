#!/bin/sh
# Build and run the mixed-points repros.
#   ./run.sh /path/to/jts-core.jar [more jars ...]
#   GEOS_CONFIG=/path/to/geos-config ./run.sh ...   (also runs repro_geos.c)
# repro_shapely.py runs when shapely is importable.
set -e
cd "$(dirname "$0")"
OUT=${TMPDIR:-/tmp}/jts-mixed-points-repro
for JAR in "$@"; do
  rm -rf "$OUT"; mkdir -p "$OUT"
  javac -cp "$JAR" -d "$OUT" Repro.java ScanScales.java
  echo "=== $JAR"
  java -cp "$JAR:$OUT" Repro
  java -cp "$JAR:$OUT" ScanScales
done
if [ -n "$GEOS_CONFIG" ]; then
  mkdir -p "$OUT"
  cc repro_geos.c $($GEOS_CONFIG --cflags) $($GEOS_CONFIG --clibs) -Wl,-rpath,"$($GEOS_CONFIG --prefix)/lib" -o "$OUT/repro_geos"
  "$OUT/repro_geos"
fi
python3 -c "import shapely" 2>/dev/null && python3 repro_shapely.py || true
