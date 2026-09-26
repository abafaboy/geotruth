#!/usr/bin/env bash
# Run the JTS master adapter (build it first with build.sh).
#
#   adapters/jts_main/run.sh CASES.jsonl > RESULTS.jsonl
#   adapters/jts_main/run.sh --relate old CASES.jsonl > RESULTS.jsonl  # v2 via RelateOp
#   adapters/jts_main/run.sh --timeout 30 CASES.jsonl > RESULTS.jsonl  # per-operation budget, s
#   adapters/jts_main/run.sh --version
# Typed (v2) lines use RelateNG unless --relate old; legacy v1 lines use RelateOp unless
# --relate ng. Env: JTS_ADAPTER_TIMEOUT / GEOTRUTH_OP_TIMEOUT (s per operation, default 10),
# JTS_ADAPTER_MEM_MB (worker heap, default 2048), JTS_JAVA_OPTS (extra JVM options).
set -euo pipefail
BUILD="${JTS_BUILD_DIR:-${GEOTRUTH_BUILD_DIR:-$HOME/.cache/geotruth}/jts-main}"
OUT="$BUILD/out"
if [ ! -f "$OUT/lib.txt" ] || [ ! -f "$OUT/classes/JtsAdapter.class" ]; then
  echo "run.sh: adapter not built in $BUILD; run $(dirname "$0")/build.sh first" >&2
  exit 2
fi
# JAVA_TOOL_OPTIONS makes the JVM print a banner on stderr; stdout stays clean.
exec java -Xss64m -XX:+UseSerialGC ${JTS_JAVA_OPTS:-} -cp "$OUT/jts-core.jar:$OUT/classes" JtsAdapter \
  --lib "$(cat "$OUT/lib.txt")" "$@"
