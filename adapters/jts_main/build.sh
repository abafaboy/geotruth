#!/usr/bin/env bash
# Build jts-core from locationtech/jts git master plus the adapter.
#
#   adapters/jts_main/build.sh            # clone (if needed) and build
#   adapters/jts_main/build.sh --update   # fetch the latest master first
#
# Build tree: $JTS_BUILD_DIR (default /tmp/claude-0/gb-build/jts-main), outside the repo:
#   src/           shallow clone of https://github.com/locationtech/jts (master)
#   m2/            private Maven repository
#   out/jts-core.jar, out/classes/JtsAdapter*.class, out/lib.txt
# Maven is tried first (tests and checkstyle skipped: checkstyle fetches its config from
# checkstyle.org, which the proxy blocks); if it fails, modules/core/src/main/java is
# compiled directly with javac (set FORCE_JAVAC=1 to skip Maven).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="${JTS_BUILD_DIR:-/tmp/claude-0/gb-build/jts-main}"
SRC="$BUILD/src"
OUT="$BUILD/out"
JOBS="${JOBS:-2}"
mkdir -p "$BUILD" "$OUT"

if [ ! -d "$SRC/.git" ]; then
  git clone --depth 1 https://github.com/locationtech/jts.git "$SRC"
elif [ "${1:-}" = "--update" ]; then
  git -C "$SRC" fetch --depth 1 origin master
  git -C "$SRC" reset --hard FETCH_HEAD
fi

COMMIT="$(git -C "$SRC" rev-parse --short=7 HEAD)"
VERSION="$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$SRC/modules/core/pom.xml" | head -1)"
echo "jts master $COMMIT, version $VERSION"

JAR="$OUT/jts-core.jar"
rm -f "$JAR"
if [ -z "${FORCE_JAVAC:-}" ] && command -v mvn >/dev/null 2>&1 && (cd "$SRC" && mvn -q -B -T "$JOBS" -pl modules/core -am \
      -DskipTests -Dcheckstyle.skip=true -Dmaven.javadoc.skip=true \
      -Dmaven.repo.local="$BUILD/m2" package); then
  cp "$SRC/modules/core/target/jts-core-$VERSION.jar" "$JAR"
  echo "built jts-core with Maven"
else
  echo "Maven build failed or unavailable; compiling jts-core with javac" >&2
  rm -rf "$OUT/core-classes"
  mkdir -p "$OUT/core-classes"
  find "$SRC/modules/core/src/main/java" -name '*.java' > "$OUT/core-sources.txt"
  javac -nowarn -encoding UTF-8 --release 8 -d "$OUT/core-classes" @"$OUT/core-sources.txt"
  if [ -d "$SRC/modules/core/src/main/resources" ]; then
    cp -r "$SRC/modules/core/src/main/resources/." "$OUT/core-classes/"
  fi
  jar cf "$JAR" -C "$OUT/core-classes" .
fi

rm -rf "$OUT/classes"
mkdir -p "$OUT/classes"
javac -encoding UTF-8 -cp "$JAR" -d "$OUT/classes" "$HERE/JtsAdapter.java"
echo "jts@$VERSION-$COMMIT" > "$OUT/lib.txt"
echo "lib: $(cat "$OUT/lib.txt")"
