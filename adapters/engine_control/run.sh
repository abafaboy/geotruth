#!/usr/bin/env bash
# Run wrapper of the engine control adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Nothing to build: it runs geotruth's own engine from this source tree (src/). Flags
# (--timing, --no-fork, --version) are passed through.
# Env: GEOTRUTH_OP_TIMEOUT or CONTROL_ADAPTER_TIMEOUT (s per operation, default 10),
# GEOTRUTH_ADAPTER_MEM_MB (worker address-space cap, default 4096), GEOTRUTH_EXACT_BACKEND
# (auto | engine | reference), PYTHON (default python3).
set -euo pipefail
exec "${PYTHON:-python3}" "$(dirname "${BASH_SOURCE[0]}")/engine_control_adapter.py" "$@"
