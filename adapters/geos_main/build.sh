#!/usr/bin/env bash
# Reproducible build of the GEOS adapter, for GEOS git main or the latest GEOS release:
#   1. fetch GEOS at the pinned commit (shallow) into $BUILD_ROOT/src
#   2. cmake Release build with -DBUILD_TESTING=OFF, install into $BUILD_ROOT/install
#   3. compile the adapter (geos_adapter.c: driver and legacy v1 contract; geos_adapter_v2.cpp
#      with adapter_v2.hpp: contract v2) against the installed geos_c into
#      $BUILD_ROOT/bin/geos_adapter
#
# usage: build.sh [main|release]      (default main)
#   main     GEOS git main at the pinned commit            -> $GEOTRUTH_BUILD_DIR/geos-main
#   release  the latest GEOS release, tag 3.15.0 (d022851)  -> $GEOTRUTH_BUILD_DIR/geos-release
#
# Env overrides: GEOS_COMMIT (full sha), BUILD_ROOT (this variant's tree), JOBS (default 2), CC, CXX.
# The library is built once per commit; later runs only recompile the adapter (a few seconds).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARIANT="${1:-main}"
GEOS_REPO="${GEOS_REPO:-https://github.com/libgeos/geos}"
case "$VARIANT" in
    main)
        GEOS_COMMIT="${GEOS_COMMIT:-ae9cdd98be4e0bae552b918d4d14c94a9ce99c58}"  # main, 2026-09-21
        DIRNAME=geos-main
        ;;
    release)
        GEOS_COMMIT="${GEOS_COMMIT:-d0228513abb0c29c185443cf2bfb06c9281024b5}"  # tag 3.15.0
        DIRNAME=geos-release
        ;;
    *)
        echo "usage: build.sh [main|release]" >&2
        exit 2
        ;;
esac
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/$DIRNAME}"
JOBS="${JOBS:-2}"
CC="${CC:-cc}"
CXX="${CXX:-c++}"

SRC="$BUILD_ROOT/src"
BLD="$BUILD_ROOT/build"
PREFIX="$BUILD_ROOT/install"
BIN="$BUILD_ROOT/bin"
mkdir -p "$BUILD_ROOT" "$BIN"

# 1. source at the pinned commit
if [ ! -d "$SRC/.git" ]; then
    git init -q "$SRC"
    git -C "$SRC" remote add origin "$GEOS_REPO"
fi
if [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)" != "$GEOS_COMMIT" ]; then
    git -C "$SRC" fetch -q --depth 1 origin "$GEOS_COMMIT"
    git -C "$SRC" checkout -q --detach FETCH_HEAD
    rm -rf "$BLD" "$PREFIX"  # stale build of another commit
fi
echo "GEOS source ($VARIANT): $(git -C "$SRC" log -1 --format='%H %cd')"

# 2. GEOS library
if [ ! -f "$PREFIX/include/geos_c.h" ]; then
    cmake -S "$SRC" -B "$BLD" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
          -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib
    cmake --build "$BLD" -j"$JOBS"
    cmake --install "$BLD"
fi

# 3. adapter (links with rpath so no LD_LIBRARY_PATH is needed)
OBJ="$BUILD_ROOT/obj"
mkdir -p "$OBJ"
"$CC" -O2 -g -std=c11 -Wall -Wextra -I"$PREFIX/include" -c -o "$OBJ/geos_adapter.o" "$HERE/geos_adapter.c"
"$CXX" -O2 -g -std=c++17 -Wall -Wextra -I"$PREFIX/include" -I"$HERE" -c -o "$OBJ/geos_adapter_v2.o" \
       "$HERE/geos_adapter_v2.cpp"
"$CXX" -o "$BIN/geos_adapter.tmp" "$OBJ/geos_adapter.o" "$OBJ/geos_adapter_v2.o" \
       -L"$PREFIX/lib" -lgeos_c -lm -Wl,-rpath,"$PREFIX/lib"
mv "$BIN/geos_adapter.tmp" "$BIN/geos_adapter"
echo "built $BIN/geos_adapter ($("$BIN/geos_adapter" --version))"
