#!/usr/bin/env bash
# Build and run repro/ (geo public API only).
#   ./run.sh                      # geo 0.33.1 from crates.io (Cargo.lock pins i_overlay 4.5.2)
#   GEO_SRC=/path/to/geo ./run.sh # a git checkout of https://github.com/georust/geo
# With GEO_SRC the crate is copied to a scratch dir and `geo` is patched to $GEO_SRC/geo.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/geo-thin-polygon-repro-target}"
DIR="$HERE/repro"
if [[ -n "${GEO_SRC:-}" ]]; then
    DIR="$(mktemp -d)"
    cp -r "$HERE/repro/Cargo.toml" "$HERE/repro/src" "$DIR/"
    printf '\n[patch.crates-io]\ngeo = { path = "%s/geo" }\n' "$GEO_SRC" >> "$DIR/Cargo.toml"
    echo "geo: $GEO_SRC @ $(git -C "$GEO_SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
fi
cargo build --release -j2 --manifest-path "$DIR/Cargo.toml" >&2
cargo tree --manifest-path "$DIR/Cargo.toml" -e normal -i i_overlay 2>/dev/null | head -1 | sed 's/^/i_overlay: /'
cargo tree --manifest-path "$DIR/Cargo.toml" -e normal -p geo --depth 0 2>/dev/null | sed 's/^/geo: /'
"$CARGO_TARGET_DIR/release/repro"
