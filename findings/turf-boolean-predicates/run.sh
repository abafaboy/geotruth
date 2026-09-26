#!/bin/sh
# Run the booleanTouches repro (public API only) and the cross-checks.
#   npm install            (installs @turf/turf 7.4.0 and jsts 2.12.1 from package.json)
#   ./run.sh               (latest release)
#   TURF_MODULE=/abs/path/turf-master-bundle.mjs ./run.sh   (master, see build-master.sh)
set -e
cd "$(dirname "$0")"
node repro.mjs
node extra.mjs                         # MultiPolygon branches (incl. L598/L753), holes, the two lead cases, the #2454 sub-case
node crosscheck.mjs cases.jsonl        # Turf's own booleanValid / booleanIntersects / intersect, and JSTS
# Exact answers (geotruth, from the repository root), both relate routes:
#   PYTHONPATH=src python3 -m geotruth relate --dual --id turf-touches-identical-triangles \
#       @findings/turf-boolean-predicates/cases.jsonl
