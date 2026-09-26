#!/usr/bin/env bash
# One hunt round: generate a corpus, compute the exact oracle, run every adapter,
# compare, and write a per-library summary.
#
# usage: harness/hunt.sh N SEED [OUT_DIR]      full round: generated families + seed corpus
#        harness/hunt.sh --seed-only [OUT_DIR] only the tracked corpus/cases/seed.jsonl
#
# The adapters must already be built (adapters/*/build.sh, adapters/js/install.sh).
#
# env:   GEOTRUTH_BUILD_DIR  root of every adapter build tree, and parent of the default
#                            OUT_DIR (default ~/.cache/geotruth)
#        HUNT_LIBS           space-separated subset of the libraries below (default: all)
#        JOBS                case files run in parallel per library (default 2)
#
# OUT_DIR defaults to $GEOTRUTH_BUILD_DIR/hunt/round-SEED (or hunt/seed-only). It receives
# cases/ and cases-small/ (the first 150 cases of each file, for the slow libraries),
# results-cases*/{oracle,<lib>,compare-<lib>}/, summary-<lib>.txt and tally.txt.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export GEOTRUTH_BUILD_DIR=${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}
# BUILD_ROOT is a per-adapter override (see adapters/*/README.md); one exported value would
# point every adapter at the same tree, so a round always uses $GEOTRUTH_BUILD_DIR/<name>.
unset BUILD_ROOT

usage="usage: hunt.sh N SEED [OUT_DIR] | hunt.sh --seed-only [OUT_DIR]"
if [ "${1:-}" = "--seed-only" ]; then
  SEED_ONLY=1
  OUT=${2:-$GEOTRUTH_BUILD_DIR/hunt/seed-only}
else
  SEED_ONLY=0
  N=${1:?$usage}; SEED=${2:?$usage}
  OUT=${3:-$GEOTRUTH_BUILD_DIR/hunt/round-$SEED}
fi
CASES="$OUT/cases"; SMALL="$OUT/cases-small"
mkdir -p "$CASES" "$SMALL"

# corpus: the tracked seed corpus; for a full round also the ten generator families, the
# oracle-review families and Clipper2's integer cases
cp "$ROOT/corpus/cases/seed.jsonl" "$CASES/seed.jsonl"
if [ "$SEED_ONLY" = 0 ]; then
  python3 "$ROOT/corpus/generators/run_all.py" "$N" "$SEED" --outdir "$CASES" >/dev/null
  python3 "$ROOT/tools/oracle_review/gen_review.py" all "$((N / 4))" "$SEED" > "$CASES/review.jsonl"
  cp "$ROOT/adapters/clipper2/int_cases.jsonl" "$CASES/int-cases.jsonl"
fi
# slow libraries get the first 150 cases of each file
for f in "$CASES"/*.jsonl; do head -n 150 "$f" > "$SMALL/$(basename "$f")"; done
fams=$(cd "$CASES" && ls *.jsonl | sed 's/\.jsonl$//' | tr '\n' ' ')

want() {  # want LIB: is LIB selected by HUNT_LIBS?
  [ -z "${HUNT_LIBS:-}" ] || [[ " $HUNT_LIBS " == *" $1 "* ]]
}
run() {  # run LIB ADAPTER CASES_DIR
  local lib=$1 adapter=$2 cdir=$3
  want "$lib" || return 0
  RESULTS_DIR="$OUT/results-$(basename "$cdir")" CASES_DIR="$cdir" LIB="$lib" ADAPTER="$adapter" \
    JOBS=${JOBS:-2} "$ROOT/corpus/generators/pipeline.sh" $fams > "$OUT/summary-$lib.txt" 2>&1 \
    || echo "pipeline failed for $lib (see $OUT/summary-$lib.txt)" >&2
  echo "done $lib" >&2
}
A="$ROOT/adapters"
run shapely "python3 $A/shapely/shapely_adapter.py" "$CASES"
run geos-main "$A/geos_main/run.sh" "$CASES"
run jts-main "$A/jts_main/run.sh" "$CASES"
run clipper2 "$A/clipper2/run.sh" "$CASES"
run boost-1.83 "$A/boost_geometry/run_1.83.sh" "$CASES"
run boost-develop "$A/boost_geometry/run_develop.sh" "$CASES"
run rust-geo "$A/rust_geo/run.sh" "$CASES"
run polyclip-ts "$A/js/run_polyclip_ts.sh" "$CASES"
run polygon-clipping "$A/js/run_polygon_clipping.sh" "$CASES"
run turf "$A/js/run_turf.sh" "$SMALL"
JS_ADAPTER_TIMEOUT=2 run martinez "$A/js/run_martinez.sh" "$SMALL"
python3 "$ROOT/harness/tally.py" "$OUT" | tee "$OUT/tally.txt"
echo "all done: $OUT" >&2
