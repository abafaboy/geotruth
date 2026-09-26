#!/usr/bin/env bash
# Builds repro.cpp against several Boost.Geometry trees and records the output.
#   GEOM_<tag>=<path to a boostorg/geometry checkout>  (its include/ goes first on the path)
# Other Boost libraries come from the system Boost (1.83 on Ubuntu 24.04). Geometry >= 1.84
# includes <boost/core/invoke_swap.hpp>, which Boost.Core 1.83 lacks; COMPAT points at a
# one-file shim for it (not used by the code paths exercised here). With a complete Boost
# tree of the same version, drop COMPAT and use -I<boost-root>.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMPAT="${COMPAT:-$HERE/../../adapters/boost_geometry/compat}"
OUT="${OUT:-$HERE}"
build_run() { # tag include-dir-or-empty
    local tag="$1" inc="$2" exe; exe="$(mktemp)"
    if [ -n "$inc" ]; then
        g++ -std=c++17 -O2 -I"$inc/include" -I"$COMPAT" "$HERE/$SRC" -o "$exe"
        desc="$(git -C "$inc" describe --tags --always 2>/dev/null || true) $(git -C "$inc" rev-parse HEAD)"
    else
        g++ -std=c++17 -O2 "$HERE/$SRC" -o "$exe"
        desc="system Boost $(grep -m1 '#define BOOST_LIB_VERSION' /usr/include/boost/version.hpp | cut -d'"' -f2)"
    fi
    { echo "# Boost.Geometry: $desc"; echo "# g++ $(g++ -dumpfullversion), -std=c++17 -O2, $(uname -m)"; "$exe"; } > "$OUT/${OUTPREFIX}_$tag.txt"
    rm -f "$exe"; echo "wrote $OUT/${OUTPREFIX}_$tag.txt"
}
SRC="${SRC:-repro.cpp}"; OUTPREFIX="${OUTPREFIX:-output}"
for v in ${VERSIONS:-develop 1.92.0 1.87.0 1.86.0}; do
    var="GEOM_${v//./_}"; build_run "$v" "${!var}"
done
build_run "1.83-system" ""
