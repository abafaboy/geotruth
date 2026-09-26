#!/usr/bin/env bash
# Run wrapper (contract: run_polyclip_ts.sh CASES.jsonl > RESULTS.jsonl). Install first with install.sh.
# The npm packages are found under $GEOTRUTH_BUILD_DIR/js-libs; see run_lib.sh.
exec "$(dirname "${BASH_SOURCE[0]}")/run_lib.sh" polyclip_ts "$@"
