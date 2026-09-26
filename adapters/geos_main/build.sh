#!/usr/bin/env bash
# Reproducible build of the GEOS-main adapter:
#   1. fetch GEOS at the pinned commit (shallow) into $BUILD_ROOT/src
#   2. cmake Release build with -DBUILD_TESTING=OFF, install into $BUILD_ROOT/install
#   3. compile geos_adapter.c against the installed geos_c into $BUILD_ROOT/bin/geos_adapter
#
# Env overrides: GEOS_COMMIT (full sha), BUILD_ROOT, JOBS (default 2), CC.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEOS_REPO="${GEOS_REPO:-https://github.com/libgeos/geos}"
GEOS_COMMIT="${GEOS_COMMIT:-ae9cdd98be4e0bae552b918d4d14c94a9ce99c58}"
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/geos-main}"
JOBS="${JOBS:-2}"
CC="${CC:-cc}"

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
echo "GEOS source: $(git -C "$SRC" log -1 --format='%H %cd')"

# 2. GEOS library
if [ ! -f "$PREFIX/include/geos_c.h" ]; then
    cmake -S "$SRC" -B "$BLD" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
          -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib
    cmake --build "$BLD" -j"$JOBS"
    cmake --install "$BLD"
fi

# 3. adapter (links with rpath so no LD_LIBRARY_PATH is needed)
"$CC" -O2 -g -std=c11 -Wall -Wextra -o "$BIN/geos_adapter" "$HERE/geos_adapter.c" \
      -I"$PREFIX/include" -L"$PREFIX/lib" -lgeos_c -lm -Wl,-rpath,"$PREFIX/lib"
echo "built $BIN/geos_adapter ($("$BIN/geos_adapter" --version))"
