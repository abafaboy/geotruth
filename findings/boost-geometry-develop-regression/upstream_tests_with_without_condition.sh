#!/usr/bin/env bash
# Compiles and runs selected upstream Boost.Geometry unit tests twice: on an unmodified
# boostorg/geometry checkout ("dev") and on a copy with experiment_disable_condition.diff
# applied ("rev"). EXPERIMENT ONLY, not a proposed fix.
#   GEOM=<boostorg/geometry checkout, e.g. develop 196d04c>  WORK=<scratch dir>
#   COMPAT=<dir with the boost/core/invoke_swap.hpp shim, only needed on system Boost 1.83>
# Results on develop 196d04c (g++ 13.3, system Boost 1.83):
#   intersection, intersection_multi, union, union_multi, difference, difference_multi,
#   relate_areal_areal: "No errors detected" in both variants.
#   set_ops_areal_areal (which holds the #1288/#1345 regression cases on develop):
#   dev "No errors detected"; rev "3 failures" (issue_1288_0_2 difference and
#   sym_difference not valid, issue_1293 sym_difference not valid), see
#   output_upstream_set_ops_areal_areal.txt. So the condition is still needed for #1288.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GEOM="${GEOM:-/tmp/claude-0/gb-build/boost-geometry/geometry}"
WORK="${WORK:-/tmp/claude-0/gb-build/triage/boost-geometry-develop-regression/utest2}"
COMPAT="${COMPAT:-$HERE/../../adapters/boost_geometry/compat}"
mkdir -p "$WORK"
rm -rf "$WORK/patched" && mkdir -p "$WORK/patched" && cp -r "$GEOM/include" "$WORK/patched/"
(cd "$WORK/patched" && patch -p1 < "$HERE/experiment_disable_condition.diff") || exit 1
TESTS="algorithms/set_operations/intersection/intersection algorithms/set_operations/intersection/intersection_multi
algorithms/set_operations/union/union algorithms/set_operations/union/union_multi
algorithms/set_operations/difference/difference algorithms/set_operations/difference/difference_multi
algorithms/relate/relate_areal_areal
algorithms/set_operations/set_ops_areal_areal"
run() { # variant include-root test
    local v=$1 inc=$2 t=$3 name; name=$(basename "$t")
    g++ -std=c++17 -O1 -w -DNDEBUG -DBOOST_GEOMETRY_TEST_ONLY_ONE_TYPE -I"$inc/include" -I"$COMPAT" \
        -I"$GEOM/test" -I"$GEOM/test/$(dirname "$t")" "$GEOM/test/$t.cpp" -o "$WORK/${v}_$name" \
        > "$WORK/${v}_$name.build.log" 2>&1 || { echo "$v $name: BUILD FAILED"; return; }
    (cd "$WORK" && timeout 900 "./${v}_$name" > "${v}_$name.run.log" 2>&1)
    echo "$v $name: exit=$? $(grep -ao 'No errors detected\|[0-9]* failures\? .*detected' "$WORK/${v}_$name.run.log" | head -1)"
}
for t in $TESTS; do
    run dev "$GEOM" "$t" & run rev "$WORK/patched" "$t"; wait   # at most 2 compilers at once
done
