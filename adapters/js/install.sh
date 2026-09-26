#!/usr/bin/env bash
# Installs the pinned npm packages (package-lock.json) outside the repo, under $BUILD_ROOT
# (default /tmp/claude-0/gb-build/js-libs), and links node_modules here to it.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD_ROOT="${BUILD_ROOT:-/tmp/claude-0/gb-build/js-libs}"
mkdir -p "$BUILD_ROOT"
cp "$HERE/package.json" "$HERE/package-lock.json" "$BUILD_ROOT/"
(cd "$BUILD_ROOT" && npm ci --no-audit --no-fund)
if [ -e "$HERE/node_modules" ] && [ ! -L "$HERE/node_modules" ]; then
    echo "install.sh: $HERE/node_modules is a real directory; leaving it alone" >&2
else
    ln -sfn "$BUILD_ROOT/node_modules" "$HERE/node_modules"
fi
node -e 'for (const p of ["@turf/turf","polygon-clipping","polyclip-ts","martinez-polygon-clipping"]) console.log(p, require(require("path").join(process.argv[1], "node_modules", p, "package.json")).version)' "$BUILD_ROOT"
