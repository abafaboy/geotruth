#!/usr/bin/env bash
# Run the JTS master adapter (build it first with build.sh).
#
#   adapters/jts_main/run.sh CASES.jsonl > RESULTS.jsonl
#   adapters/jts_main/run.sh --relate ng CASES.jsonl > RESULTS.jsonl   # RelateNG predicates
#   adapters/jts_main/run.sh --timeout 30 CASES.jsonl > RESULTS.jsonl  # per-case budget, s
set -euo pipefail
BUILD="${JTS_BUILD_DIR:-/tmp/claude-0/gb-build/jts-main}"
OUT="$BUILD/out"
if [ ! -f "$OUT/lib.txt" ] || [ ! -f "$OUT/classes/JtsAdapter.class" ]; then
  echo "run.sh: adapter not built; run $(dirname "$0")/build.sh" >&2
  exit 2
fi
# JAVA_TOOL_OPTIONS makes the JVM print a banner on stderr; stdout stays clean.
exec java -Xss64m ${JTS_JAVA_OPTS:-} -cp "$OUT/jts-core.jar:$OUT/classes" JtsAdapter \
  --lib "$(cat "$OUT/lib.txt")" "$@"
