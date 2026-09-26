#!/usr/bin/env bash
# Run wrapper (contract: run_martinez.sh CASES.jsonl > RESULTS.jsonl). Install first with install.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$HERE/node_modules" ]; then
    echo "run_martinez.sh: $HERE/node_modules not found; run $HERE/install.sh first" >&2
    exit 2
fi
exec "${NODE:-node}" "$HERE/adapter.mjs" martinez "$@"
