#!/usr/bin/env bash
# Reproducible build of the Clipper2 adapter:
#   1. fetch AngusJohnson/Clipper2 at the pinned commit (shallow) into $BUILD_ROOT/src
#   2. compile the C++ library sources together with clipper2_adapter.cpp (g++ -O2)
#      into $BUILD_ROOT/bin/clipper2_adapter, and repro_small_triangle.cpp alongside
#
# Env overrides: CLIPPER2_COMMIT (full sha), BUILD_ROOT, JOBS (default 2), CXX.
#   CLIPPER2_COMMIT=main build.sh   builds whatever main is now (the lib string records it)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${CLIPPER2_REPO:-https://github.com/AngusJohnson/Clipper2}"
COMMIT="${CLIPPER2_COMMIT:-f9c5eb6e14a59f6f5d65fbfb3564519a561cf4fd}"
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/clipper2}"
JOBS="${JOBS:-2}"
CXX="${CXX:-g++}"

SRC="$BUILD_ROOT/src"
OBJ="$BUILD_ROOT/obj"
BIN="$BUILD_ROOT/bin"
mkdir -p "$BUILD_ROOT" "$OBJ" "$BIN"

# 1. source at the pinned commit
if [ ! -d "$SRC/.git" ]; then
    git init -q "$SRC"
    git -C "$SRC" remote add origin "$REPO"
fi
if [ "$COMMIT" = "main" ]; then
    git -C "$SRC" fetch -q --depth 1 origin main
    git -C "$SRC" checkout -q --detach FETCH_HEAD
elif [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)" != "$COMMIT" ]; then
    git -C "$SRC" fetch -q --depth 1 origin "$COMMIT"
    git -C "$SRC" checkout -q --detach FETCH_HEAD
fi
FULL="$(git -C "$SRC" rev-parse HEAD)"
SHORT="$(git -C "$SRC" rev-parse --short=7 HEAD)"
echo "Clipper2 source: $(git -C "$SRC" log -1 --format='%H %cd')"

LIB="$SRC/CPP/Clipper2Lib"
CXXFLAGS=(-O2 -g -std=c++17 -Wall -I"$LIB/include")

# 2. library objects (rebuilt when the commit changes) and the adapter
STAMP="$OBJ/commit"
if [ "$(cat "$STAMP" 2>/dev/null || true)" != "$FULL" ]; then
    rm -f "$OBJ"/*.o
    printf '%s\n' "$LIB"/src/clipper.engine.cpp "$LIB"/src/clipper.offset.cpp \
                  "$LIB"/src/clipper.rectclip.cpp "$LIB"/src/clipper.triangulation.cpp |
        xargs -P "$JOBS" -I{} sh -c '"$0" "$@" -c "{}" -o "'"$OBJ"'/$(basename "{}" .cpp).o"' \
              "$CXX" "${CXXFLAGS[@]}"
    echo "$FULL" > "$STAMP"
fi
"$CXX" "${CXXFLAGS[@]}" -DCLIPPER2_COMMIT="\"$SHORT\"" -o "$BIN/clipper2_adapter" \
       "$HERE/clipper2_adapter.cpp" "$OBJ"/*.o
"$CXX" "${CXXFLAGS[@]}" -o "$BIN/repro_small_triangle" "$HERE/repro_small_triangle.cpp" \
       "$OBJ"/clipper.engine.o
echo "built $BIN/clipper2_adapter ($("$BIN/clipper2_adapter" --version)) and $BIN/repro_small_triangle"
