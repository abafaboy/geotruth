#!/usr/bin/env bash
# Builds the Boost.Geometry adapter twice from the same source (bg_adapter.cpp):
#
#   $BUILD_ROOT/bin/bg_adapter_1.83     system Boost 1.83 headers (apt: libboost-dev)
#   $BUILD_ROOT/bin/bg_adapter_develop  boostorg/geometry develop headers first on the
#                                       include path, every other Boost library from the system
#
#   1. check the system Boost is 1.83
#   2. fetch boostorg/geometry at the pinned develop commit into $BUILD_ROOT/geometry
#   3. compile both variants (at most $JOBS compilers at once)
#   4. check from the compiler's dependency list that the develop binary includes no
#      Boost.Geometry header from /usr/include
#
# The develop build also gets -I compat/ (after the develop headers): a shim for
# <boost/core/invoke_swap.hpp>, which develop includes and Boost 1.83 does not have.
#
# Env overrides: BG_COMMIT (full sha of develop to pin), BUILD_ROOT, JOBS (default 2), CXX,
# CXXFLAGS_EXTRA (e.g. "-UNDEBUG" to keep Boost asserts on; they abort the child, which the
# adapter reports as a crash).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BG_REPO="${BG_REPO:-https://github.com/boostorg/geometry}"
BG_COMMIT="${BG_COMMIT:-196d04c614c12a8d788212b63fa65d25c8b7ea86}"
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/boost-geometry}"
JOBS="${JOBS:-2}"
CXX="${CXX:-g++}"
SYS_INC="${SYS_INC:-/usr/include}"
SRC="$BUILD_ROOT/geometry"
BIN="$BUILD_ROOT/bin"
mkdir -p "$BUILD_ROOT" "$BIN"

# 1. system Boost
if ! grep -q '^#define BOOST_VERSION 108300' "$SYS_INC/boost/version.hpp" 2>/dev/null; then
    echo "build.sh: need system Boost 1.83 headers in $SYS_INC (apt-get install libboost-dev)" >&2
    exit 2
fi

# 2. Boost.Geometry develop at the pinned commit
if [ ! -d "$SRC/.git" ]; then
    git init -q "$SRC"
    git -C "$SRC" remote add origin "$BG_REPO"
fi
if [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)" != "$BG_COMMIT" ]; then
    git -C "$SRC" fetch -q --depth 1 origin "$BG_COMMIT"
    git -C "$SRC" checkout -q --detach FETCH_HEAD
fi
SHORT="$(git -C "$SRC" rev-parse --short=7 HEAD)"
echo "Boost.Geometry develop: $(git -C "$SRC" log -1 --format='%H %cd %s')"

# 3. compile.  -DNDEBUG: release semantics (Boost asserts off), as a user's build would be.
CXXFLAGS=(-std=c++17 -O2 -g0 -DNDEBUG -Wall -Wno-unused-local-typedefs ${CXXFLAGS_EXTRA:-})
# compat/ holds a shim for <boost/core/invoke_swap.hpp> (Boost.Core >= 1.84), which develop
# needs and Boost 1.83 lacks; it comes after the develop headers, before the system ones.
DEV_FLAGS=(-I"$SRC/include" -I"$HERE/compat" -DBG_ADAPTER_LIB="\"boost-geometry@develop-$SHORT\"")

build() { # out flags...
    local out="$1"; shift
    echo "compiling $out"
    "$CXX" "${CXXFLAGS[@]}" "$@" -o "$out.tmp" "$HERE/bg_adapter.cpp" && mv "$out.tmp" "$out"
}
if [ "$JOBS" -ge 2 ]; then
    build "$BIN/bg_adapter_1.83" & p1=$!
    build "$BIN/bg_adapter_develop" "${DEV_FLAGS[@]}" & p2=$!
    wait $p1; wait $p2
else
    build "$BIN/bg_adapter_1.83"
    build "$BIN/bg_adapter_develop" "${DEV_FLAGS[@]}"
fi

# 4. the develop binary must not have picked up any Boost.Geometry header from the system
deps="$("$CXX" "${CXXFLAGS[@]}" "${DEV_FLAGS[@]}" -M "$HERE/bg_adapter.cpp" | tr ' \\' '\n\n' | grep -v '^$')"
if grep -q "^$SYS_INC/boost/geometry" <<<"$deps"; then
    echo "build.sh: develop build includes system Boost.Geometry headers:" >&2
    grep "^$SYS_INC/boost/geometry" <<<"$deps" | head >&2
    exit 1
fi
n_dev="$(grep -c "^$SRC/include/boost/geometry" <<<"$deps" || true)"
n_sys="$(grep -c "^$SYS_INC/boost/" <<<"$deps" || true)"
n_compat="$(grep -c "^$HERE/compat/" <<<"$deps" || true)"
echo "develop build: $n_dev Boost.Geometry headers from $SRC/include, $n_sys other Boost headers" \
     "from $SYS_INC, $n_compat compat shim(s) from $HERE/compat"

for v in 1.83 develop; do
    echo "built $BIN/bg_adapter_$v ($("$BIN/bg_adapter_$v" --version))"
done
