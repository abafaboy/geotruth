#!/usr/bin/env bash
# One hunt round: generate a corpus, compute the exact oracle, run every adapter,
# compare, and write a per-library summary.
#
# usage: ./hunt.sh N SEED [OUT_DIR]      (adapters must already be built)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
N=${1:?N per family}; SEED=${2:?seed}; OUT=${3:-/tmp/claude-0/gb-hunt/round-$SEED}
CASES="$OUT/cases"; SMALL="$OUT/cases-small"
mkdir -p "$CASES" "$SMALL"

# corpus: the ten generator families, the review families, Clipper's integer cases
( cd "$ROOT" && python3 gen/run_all.py "$N" "$SEED" >/dev/null )
cp "$ROOT"/cases/*.jsonl "$CASES"/
python3 "$ROOT/oracle_review/gen_review.py" all "$((N / 4))" "$SEED" > "$CASES/review.jsonl"
cp "$ROOT/adapters/clipper2/int_cases.jsonl" "$CASES/int-cases.jsonl"
# slow libraries get the first 150 cases of each family
for f in "$CASES"/*.jsonl; do head -n 150 "$f" > "$SMALL/$(basename "$f")"; done
fams=$(cd "$CASES" && ls *.jsonl | sed 's/\.jsonl$//' | tr '\n' ' ')

run() {  # run LIB ADAPTER CASES_DIR
  local lib=$1 adapter=$2 cdir=$3
  RESULTS_DIR="$OUT/results-$(basename "$cdir")" CASES_DIR="$cdir" LIB="$lib" ADAPTER="$adapter" JOBS=2 \
    "$ROOT/gen/pipeline.sh" $fams > "$OUT/summary-$lib.txt" 2>&1 || echo "pipeline failed for $lib" >&2
  echo "done $lib" >&2
}
A="$ROOT/adapters"
run shapely "python3 $A/shapely_adapter.py" "$CASES"
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
echo "all done: $OUT" >&2
