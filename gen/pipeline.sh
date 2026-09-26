#!/usr/bin/env bash
# Run the exact oracle and an adapter (default: the Shapely/GEOS reference adapter) on
# every generated family, compare, and summarise.
#
# usage: gen/pipeline.sh [family ...]          (default: every family in families.py)
# env:   ADAPTER      adapter command, run as `$ADAPTER CASES.jsonl > RESULTS.jsonl`
#                     (default: python3 <repo>/adapters/shapely_adapter.py)
#        LIB          name of the results subdirectory for the adapter (default: shapely)
#        RESULTS_DIR  where oracle/, $LIB/, compare-$LIB/ go
#                     (default /tmp/claude-0/gb-build/generators/results, outside the repo)
#        CASES_DIR    default <repo>/cases
#        JOBS         families run in parallel (default 2)
# The oracle output is reused when it is newer than the case file.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
export ROOT
export ADAPTER=${ADAPTER:-python3 $ROOT/adapters/shapely_adapter.py}
export LIB=${LIB:-shapely}
export RESULTS_DIR=${RESULTS_DIR:-/tmp/claude-0/gb-build/generators/results}
export CASES_DIR=${CASES_DIR:-$ROOT/cases}
JOBS=${JOBS:-2}
if [ $# -gt 0 ]; then
  fams=("$@")
else
  read -r -a fams <<< "$(cd "$HERE" && python3 -c 'from families import FAMILIES; print(" ".join(n for n, _ in FAMILIES))')"
fi
mkdir -p "$RESULTS_DIR/oracle" "$RESULTS_DIR/$LIB" "$RESULTS_DIR/compare-$LIB"

run_one() {
  local fam=$1 c="$CASES_DIR/$1.jsonl" o="$RESULTS_DIR/oracle/$1.jsonl"
  if [ ! -s "$o" ] || [ "$c" -nt "$o" ]; then
    python3 "$ROOT/oracle.py" "$c" > "$o.tmp" && mv "$o.tmp" "$o"
  fi
  $ADAPTER "$c" > "$RESULTS_DIR/$LIB/$fam.jsonl"
  python3 "$ROOT/compare.py" "$c" "$o" "$RESULTS_DIR/$LIB/$fam.jsonl" --json \
    > "$RESULTS_DIR/compare-$LIB/$fam.jsonl" 2> "$RESULTS_DIR/compare-$LIB/$fam.log"
  echo "$fam: $(cat "$RESULTS_DIR/compare-$LIB/$fam.log")" >&2
}
export -f run_one
printf '%s\n' "${fams[@]}" | xargs -P "$JOBS" -I{} bash -c 'run_one "$@"' _ {}
python3 "$HERE/summarize.py" "$CASES_DIR" "$RESULTS_DIR/compare-$LIB" --families "$(IFS=,; echo "${fams[*]}")"
