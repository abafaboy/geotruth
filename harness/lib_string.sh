#!/usr/bin/env bash
# Print the `lib` string an adapter reports (library name and version or commit), for
# adapters without a --version flag: run it on the first case of the seed corpus and read the
# `lib` field of the result line. Used as the version command in adapters/*/adapter.toml.
#
# usage: harness/lib_string.sh ADAPTER_COMMAND [ARG ...]
#   e.g. harness/lib_string.sh adapters/js/run_turf.sh      ->  turf@7.4.0
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ $# -gt 0 ] || { echo "usage: lib_string.sh ADAPTER_COMMAND [ARG ...]" >&2; exit 2; }
one=$(mktemp)
trap 'rm -f "$one"' EXIT
head -n 1 "$ROOT/corpus/cases/seed.jsonl" > "$one"
"$@" "$one" 2>/dev/null | head -n 1 | python3 -c 'import json, sys; print(json.loads(sys.stdin.read())["lib"])'
