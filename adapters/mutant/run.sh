#!/usr/bin/env bash
# Run wrapper of the mutant adapter (contract: run.sh CASES.jsonl > RESULTS.jsonl).
# Nothing to build. Flags and environment as adapters/engine_control/run.sh
# (MUTANT_ADAPTER_TIMEOUT instead of CONTROL_ADAPTER_TIMEOUT).
set -euo pipefail
exec "${PYTHON:-python3}" "$(dirname "${BASH_SOURCE[0]}")/mutant_adapter.py" "$@"
