#!/usr/bin/env bash
# Shared run wrapper of the JavaScript adapters (contract: harness/FORMAT-v1.md):
#
#   run_lib.sh LIB CASES.jsonl > RESULTS.jsonl    LIB: turf, polygon_clipping, polyclip_ts, martinez
#
# The run_<lib>.sh wrappers call this. install.sh installs the pinned npm packages under
# $BUILD_ROOT (default $GEOTRUTH_BUILD_DIR/js-libs, GEOTRUTH_BUILD_DIR defaulting to
# ~/.cache/geotruth). Node resolves the adapters' ES-module imports only through a
# node_modules directory next to (or above) the importing file, so adapters/js/node_modules
# must be a link to that tree. This wrapper creates or re-points the link when it is missing
# or points elsewhere, and leaves a real node_modules directory (from `npm ci` run here) alone.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${1:?usage: run_lib.sh LIB CASES.jsonl}"
shift
BUILD_ROOT="${BUILD_ROOT:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/js-libs}"
MODULES="$BUILD_ROOT/node_modules"
LINK="$HERE/node_modules"
if [ -d "$MODULES" ] && { [ -L "$LINK" ] || [ ! -e "$LINK" ]; } &&
   [ "$(readlink "$LINK" 2>/dev/null || true)" != "$MODULES" ]; then
    # atomic replace (rename), so concurrent runs never see the link missing
    tmp="$HERE/.node_modules.$$"
    ln -sfn "$MODULES" "$tmp"
    mv -Tf "$tmp" "$LINK"
fi
if [ ! -d "$LINK" ]; then
    echo "run_$LIB.sh: no npm packages in $MODULES or $LINK; run $HERE/install.sh first" >&2
    exit 2
fi
exec "${NODE:-node}" "$HERE/adapter.mjs" "$LIB" "$@"
