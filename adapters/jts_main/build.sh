#!/usr/bin/env bash
# Build jts-core and the adapter, for JTS git master or the latest JTS release.
#
#   adapters/jts_main/build.sh [main]          # master at the pinned commit (the default)
#   adapters/jts_main/build.sh release         # the latest release tag (1.20.0)
#   adapters/jts_main/build.sh main --update   # move master to the newest upstream commit
#
# Build trees (outside the repo; GEOTRUTH_BUILD_DIR defaults to ~/.cache/geotruth):
#   main:    $JTS_BUILD_DIR (default $GEOTRUTH_BUILD_DIR/jts-main)
#   release: $JTS_RELEASE_BUILD_DIR (default $GEOTRUTH_BUILD_DIR/jts-release)
# each holding
#   src/           shallow clone of https://github.com/locationtech/jts at the pinned commit
#   m2/            private Maven repository (main only)
#   out/jts-core.jar, out/jts-core.commit, out/classes/JtsAdapter*.class, out/lib.txt
#
# jts-core is built once per commit (out/jts-core.commit records which); later runs only
# recompile the adapter. Maven is tried first for master (tests and checkstyle skipped:
# checkstyle fetches its config from checkstyle.org, which the proxy blocks); if it fails,
# and always for the release, modules/core/src/main/java is compiled directly with javac
# (FORCE_JAVAC=1 always uses javac). Both paths give byte-identical adapter results.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-main}"
[ $# -gt 0 ] && shift
UPDATE=0
for a in "$@"; do
  case "$a" in
    --update) UPDATE=1 ;;
    *) echo "build.sh: unknown argument $a" >&2; exit 2 ;;
  esac
done

ROOT="${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}"
case "$TARGET" in
  main|master)
    TARGET=main
    BUILD="${JTS_BUILD_DIR:-$ROOT/jts-main}"
    REF="3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd"   # master ("Update JTS_Version_History.md")
    FETCH="master" ;;
  release)
    BUILD="${JTS_RELEASE_BUILD_DIR:-$ROOT/jts-release}"
    REF="6e95fe82feb986a7aa657f4ffa406d8c290af509"   # tag 1.20.0, the latest release
    FETCH="refs/tags/1.20.0" ;;
  *) echo "build.sh: target must be main or release, not $TARGET" >&2; exit 2 ;;
esac
SRC="$BUILD/src"
OUT="$BUILD/out"
JOBS="${JOBS:-2}"
mkdir -p "$BUILD" "$OUT"

if [ ! -d "$SRC/.git" ]; then
  git init -q "$SRC"
  git -C "$SRC" remote add origin https://github.com/locationtech/jts.git
fi
HEAD_NOW="$(git -C "$SRC" rev-parse -q --verify HEAD 2>/dev/null || true)"
if [ "$UPDATE" = 1 ]; then
  git -C "$SRC" fetch -q --depth 1 origin "$FETCH"
  git -C "$SRC" checkout -q --detach FETCH_HEAD
elif [ "$HEAD_NOW" != "$REF" ]; then
  git -C "$SRC" fetch -q --depth 1 origin "$REF" || git -C "$SRC" fetch -q --depth 1 origin "$FETCH"
  git -C "$SRC" checkout -q --detach "$REF"
fi

COMMIT_FULL="$(git -C "$SRC" rev-parse HEAD)"
COMMIT="$(git -C "$SRC" rev-parse --short=7 HEAD)"
VERSION="$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$SRC/modules/core/pom.xml" | head -1)"
echo "jts $TARGET: $COMMIT_FULL, version $VERSION"

JAR="$OUT/jts-core.jar"
if [ -f "$JAR" ] && [ "$(cat "$OUT/jts-core.commit" 2>/dev/null)" = "$COMMIT_FULL" ]; then
  echo "jts-core for $COMMIT is already built"
elif [ -f "$JAR" ] && [ ! -f "$OUT/jts-core.commit" ] && [ -f "$OUT/lib.txt" ] &&
     [ "$(cat "$OUT/lib.txt")" = "jts@$VERSION-$COMMIT" ]; then
  # a tree built before jts-core.commit existed: its lib.txt names this commit
  echo "$COMMIT_FULL" > "$OUT/jts-core.commit"
  echo "jts-core for $COMMIT is already built"
else
  rm -f "$JAR" "$OUT/jts-core.commit"
  if [ -z "${FORCE_JAVAC:-}" ] && [ "$TARGET" = main ] && command -v mvn >/dev/null 2>&1 &&
     (cd "$SRC" && mvn -q -B -T "$JOBS" -pl modules/core -am \
        -DskipTests -Dcheckstyle.skip=true -Dmaven.javadoc.skip=true \
        -Dmaven.repo.local="$BUILD/m2" package); then
    cp "$SRC/modules/core/target/jts-core-$VERSION.jar" "$JAR"
    echo "built jts-core with Maven"
  else
    echo "compiling jts-core with javac" >&2
    rm -rf "$OUT/core-classes"
    mkdir -p "$OUT/core-classes"
    find "$SRC/modules/core/src/main/java" -name '*.java' > "$OUT/core-sources.txt"
    javac -nowarn -encoding UTF-8 --release 8 -J-Xmx1g -d "$OUT/core-classes" @"$OUT/core-sources.txt"
    if [ -d "$SRC/modules/core/src/main/resources" ]; then
      cp -r "$SRC/modules/core/src/main/resources/." "$OUT/core-classes/"
    fi
    jar cf "$JAR" -C "$OUT/core-classes" .
  fi
  echo "$COMMIT_FULL" > "$OUT/jts-core.commit"
fi

if [ -n "${JTS_LIBRARY_ONLY:-}" ]; then
  exit 0
fi
rm -rf "$OUT/classes"
mkdir -p "$OUT/classes"
javac -encoding UTF-8 -cp "$JAR" -d "$OUT/classes" "$HERE/JtsAdapter.java"
if [ "$TARGET" = release ]; then
  echo "jts@$VERSION" > "$OUT/lib.txt"
else
  echo "jts@$VERSION-$COMMIT" > "$OUT/lib.txt"
fi
echo "lib: $(cat "$OUT/lib.txt")"
