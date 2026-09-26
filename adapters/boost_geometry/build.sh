#!/usr/bin/env bash
# Builds the Boost.Geometry adapter three times from the same source (bg_adapter.cpp):
#
#   $BUILD_ROOT/bin/bg_adapter_1.83     system Boost 1.83 headers (apt: libboost-dev)
#   $BUILD_ROOT/bin/bg_adapter_develop  boostorg/geometry develop headers first on the
#                                       include path, every other Boost library from the system
#   $BUILD_ROOT/bin/bg_adapter_release  boostorg/geometry at the latest release tag
#                                       (boost-1.92.0) the same way
#
#   1. check the system Boost is 1.83
#   2. fetch boostorg/geometry at the pinned develop commit into $BUILD_ROOT/geometry and at
#      the release tag into $BUILD_ROOT/geometry-release
#   3. compile the three variants (at most $JOBS compilers at once, ~90 s and ~1.5 GB each)
#   4. check from the compiler's dependency list that the develop and release binaries
#      include no Boost.Geometry header from /usr/include
#
# The develop and release builds also get -I compat/ (after their Boost.Geometry headers): a
# shim for <boost/core/invoke_swap.hpp>, which they include and Boost 1.83 does not have.
# Every build also gets -I ../geos_main for the shared contract-v2 runtime (adapter_v2.hpp).
#
# Env overrides: BG_COMMIT (full sha of develop to pin), BG_RELEASE_TAG / BG_RELEASE_COMMIT,
# BUILD_ROOT, JOBS (default 2), CXX, CXXFLAGS_EXTRA (e.g. "-UNDEBUG" to keep Boost asserts
# on; they abort the child, which the adapter reports as a crash), VARIANTS (default
# "1.83 develop release").
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BG_REPO="${BG_REPO:-https://github.com/boostorg/geometry}"
BG_COMMIT="${BG_COMMIT:-196d04c614c12a8d788212b63fa65d25c8b7ea86}"
BG_RELEASE_TAG="${BG_RELEASE_TAG:-boost-1.92.0}"
BG_RELEASE_COMMIT="${BG_RELEASE_COMMIT:-90c27ef0bf9d1700f553b85f890f43461eced529}"
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/boost-geometry}"
JOBS="${JOBS:-2}"
CXX="${CXX:-g++}"
SYS_INC="${SYS_INC:-/usr/include}"
VARIANTS="${VARIANTS:-1.83 develop release}"
SRC="$BUILD_ROOT/geometry"
SRC_REL="$BUILD_ROOT/geometry-release"
BIN="$BUILD_ROOT/bin"
mkdir -p "$BUILD_ROOT" "$BIN"

# 1. system Boost
if ! grep -q '^#define BOOST_VERSION 108300' "$SYS_INC/boost/version.hpp" 2>/dev/null; then
    echo "build.sh: need system Boost 1.83 headers in $SYS_INC (apt-get install libboost-dev)" >&2
    exit 2
fi

# 2. Boost.Geometry develop at the pinned commit, and the release tag
fetch() { # dir ref expected-commit
    local dir="$1" ref="$2" want="$3"
    if [ ! -d "$dir/.git" ]; then
        git init -q "$dir"
        git -C "$dir" remote add origin "$BG_REPO"
    fi
    if [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)" != "$want" ]; then
        git -C "$dir" fetch -q --depth 1 origin "$ref"
        git -C "$dir" checkout -q --detach FETCH_HEAD
    fi
    if [ "$(git -C "$dir" rev-parse HEAD)" != "$want" ]; then
        echo "build.sh: $ref in $dir is $(git -C "$dir" rev-parse HEAD), expected $want" >&2
        exit 1
    fi
}
fetch "$SRC" "$BG_COMMIT" "$BG_COMMIT"
fetch "$SRC_REL" "refs/tags/$BG_RELEASE_TAG" "$BG_RELEASE_COMMIT"
SHORT="$(git -C "$SRC" rev-parse --short=7 HEAD)"
REL_VERSION="${BG_RELEASE_TAG#boost-}"   # 1.92.0
REL_VERSION="${REL_VERSION%.0}"          # 1.92, like the system build's boost-geometry@1.83
echo "Boost.Geometry develop: $(git -C "$SRC" log -1 --format='%H %cd %s')"
echo "Boost.Geometry release: $BG_RELEASE_TAG $(git -C "$SRC_REL" log -1 --format='%H %cd')"

# 3. compile.  -DNDEBUG: release semantics (Boost asserts off), as a user's build would be.
CXXFLAGS=(-std=c++17 -O2 -g0 -DNDEBUG -Wall -Wno-unused-local-typedefs -Wno-maybe-uninitialized
          -I"$HERE/../geos_main" ${CXXFLAGS_EXTRA:-})
# compat/ holds a shim for <boost/core/invoke_swap.hpp> (Boost.Core >= 1.84), which newer
# Boost.Geometry needs and Boost 1.83 lacks; it comes after their headers, before the system ones.
flags() { # variant -> extra flags
    case "$1" in
        1.83) ;;
        develop) echo "-I$SRC/include -I$HERE/compat -DBG_ADAPTER_LIB=\"boost-geometry@develop-$SHORT\"" ;;
        release) echo "-I$SRC_REL/include -I$HERE/compat -DBG_ADAPTER_LIB=\"boost-geometry@$REL_VERSION\"" ;;
    esac
}
build() { # variant
    local out="$BIN/bg_adapter_$1"
    # shellcheck disable=SC2046
    "$CXX" "${CXXFLAGS[@]}" $(flags "$1") -o "$out.tmp" "$HERE/bg_adapter.cpp" && mv "$out.tmp" "$out" \
        && echo "compiled $out"
}
pids=()
for v in $VARIANTS; do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 1; done
    build "$v" & pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done

# 4. the develop and release binaries must not have picked up Boost.Geometry headers from the system
for v in develop release; do
    case " $VARIANTS " in *" $v "*) ;; *) continue ;; esac
    inc="$SRC/include"; [ "$v" = release ] && inc="$SRC_REL/include"
    # shellcheck disable=SC2046
    deps="$("$CXX" "${CXXFLAGS[@]}" $(flags "$v") -M "$HERE/bg_adapter.cpp" | tr ' \\' '\n\n' | grep -v '^$')"
    if grep -q "^$SYS_INC/boost/geometry" <<<"$deps"; then
        echo "build.sh: $v build includes system Boost.Geometry headers:" >&2
        grep "^$SYS_INC/boost/geometry" <<<"$deps" | head >&2
        exit 1
    fi
    n_bg="$(grep -c "^$inc/boost/geometry" <<<"$deps" || true)"
    n_sys="$(grep -c "^$SYS_INC/boost/" <<<"$deps" || true)"
    n_compat="$(grep -c "^$HERE/compat/" <<<"$deps" || true)"
    echo "$v build: $n_bg Boost.Geometry headers from $inc, $n_sys other Boost headers" \
         "from $SYS_INC, $n_compat compat shim(s) from $HERE/compat"
done

for v in $VARIANTS; do
    echo "built $BIN/bg_adapter_$v ($("$BIN/bg_adapter_$v" --version))"
done
