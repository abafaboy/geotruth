#!/bin/sh
# Bundle the boolean predicates of Turf master (TypeScript sources, no build step) into one ES
# module with esbuild, so repro.mjs can run against the development code:
#   ./build-master.sh [WORKDIR]   ->  $WORKDIR/turf-master-bundle.mjs
#   TURF_MODULE=$WORKDIR/turf-master-bundle.mjs node repro.mjs
# Third-party dependencies (point-in-polygon-hao, geojson-equality-ts, rbush, ...) are resolved
# from NODE_PATH (default: ./node_modules after `npm install` here).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
W=${1:-${TMPDIR:-/tmp}/turf-master-build}
mkdir -p "$W" && cd "$W"
[ -d turf ] || git clone -q --depth 1 https://github.com/Turfjs/turf.git turf
git -C turf log -1 --format='turf master %H %cd'
[ -x node_modules/.bin/esbuild ] || { npm init -y >/dev/null; npm install --no-audit --no-fund esbuild@0.25 >/dev/null; }
cat > entry.ts <<'EOT'
export { booleanTouches } from "@turf/boolean-touches";
export { booleanOverlap } from "@turf/boolean-overlap";
export { booleanContains } from "@turf/boolean-contains";
export { polygon, multiPolygon, feature } from "@turf/helpers";
EOT
ALIASES=""
for d in turf/packages/turf-*; do n=$(basename "$d"); ALIASES="$ALIASES --alias:@turf/${n#turf-}=$PWD/$d/index.ts"; done
NODE_PATH=${NODE_PATH:-$HERE/node_modules} ./node_modules/.bin/esbuild entry.ts --bundle --format=esm \
  --platform=node --outfile=turf-master-bundle.mjs $ALIASES --log-level=warning
echo "$W/turf-master-bundle.mjs"
