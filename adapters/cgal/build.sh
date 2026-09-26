#!/usr/bin/env bash
# Build of the CGAL adapter (the exact control) against the system CGAL:
#   1. check the CGAL headers (apt-get install libcgal-dev: CGAL 5.6 on Ubuntu 24.04, header-only,
#      with GMP and MPFR)
#   2. compile cgal_adapter.cpp (with the shared v2 runtime ../geos_main/adapter_v2.hpp) into
#      $BUILD_ROOT/bin/cgal_adapter
#
# CGAL's own checks stay on (no NDEBUG / CGAL_NDEBUG): a failed precondition throws and is
# reported as that operation's error, which is what a control should do.
#
# Env overrides: BUILD_ROOT (default $GEOTRUTH_BUILD_DIR/cgal), CXX, CGAL_INC (default /usr/include).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/cgal}"
CXX="${CXX:-g++}"
CGAL_INC="${CGAL_INC:-/usr/include}"
BIN="$BUILD_ROOT/bin"
mkdir -p "$BIN"

# 1. system CGAL
if [ ! -f "$CGAL_INC/CGAL/version.h" ]; then
    echo "build.sh: need the CGAL headers in $CGAL_INC (apt-get install libcgal-dev)" >&2
    exit 2
fi
echo "CGAL: $(grep -m1 '#define CGAL_VERSION ' "$CGAL_INC/CGAL/version.h")," \
     "package $(dpkg-query -W -f='${Version}' libcgal-dev 2>/dev/null || echo unknown)"

# 2. adapter
"$CXX" -std=c++17 -O2 -g0 -Wall -Wno-unused-local-typedefs -frounding-math \
       -I"$CGAL_INC" -I"$HERE/../geos_main" -o "$BIN/cgal_adapter.tmp" "$HERE/cgal_adapter.cpp" \
       -lmpfr -lgmp
mv "$BIN/cgal_adapter.tmp" "$BIN/cgal_adapter"
echo "built $BIN/cgal_adapter ($("$BIN/cgal_adapter" --version))"
