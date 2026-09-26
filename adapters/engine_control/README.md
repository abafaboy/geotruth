# engine_control: geotruth's own exact engine as an adapter

The control of DESIGN.md §7. It answers every contract-v2 field from geotruth's exact
engine, so it **must score 100%** (no headline failure). If it does not, the bug is in the
harness (the runner, the adapter runtime or the scorer), not in a library. `lib` is
`geotruth-control@<engine version>`, currently `geotruth-control@0.1.0`.

```sh
python3 -m geotruth run --lib engine-control --tier core     # results/engine-control/core.jsonl
python3 -m geotruth score --lib engine-control --tier core   # must print "0 headline failures"
adapters/engine_control/run.sh corpus/cases/curated.jsonl    # the bare adapter, v2 lines only
```

Nothing is built: `run.sh` puts `src/` of this checkout on `sys.path`.

| file | what |
|---|---|
| `engine_control_adapter.py` | entry point: `pyadapter.main(ControlLibrary())` |
| `run.sh` | run wrapper (flags `--timing`, `--no-fork`, `--version` pass through) |
| `adapter.toml` | manifest (DESIGN.md §4.2): fields, δ, isolation |

The code lives in the harness package, so the mutant can share it:
[`src/geotruth/harness/control.py`](../../src/geotruth/harness/control.py) (the answers),
[`engine.py`](../../src/geotruth/harness/engine.py) (the shim to the engine),
[`regularize.py`](../../src/geotruth/harness/regularize.py) (valid rounding) and
[`pyadapter.py`](../../src/geotruth/harness/pyadapter.py) (the contract-v2 runtime shared
with the Shapely adapter).

## What each field is

| field | answer |
|---|---|
| `echo` | the operands as parsed (Python `float()`), written back with `json.dumps` (shortest round trip) |
| `valid_a`, `valid_b` | `geotruth.validity.validate` (GEOS IsValidOp rules, exact) |
| `relate` | the exact DE-9IM matrix: `geotruth.relate.relate` when it exists, else the witness relate |
| `predicates.*` | `geotruth.predicates` from the relate matrix and the real dimensions (declared derived from relate) |
| `overlay.<op>` | the exact **non-strict** result (lower-dimensional parts of boundary contact kept), every coordinate correctly rounded to a double (ties to even) |

`GEOTRUTH_EXACT_BACKEND=auto|engine|reference` picks the route through the shim. `auto`
uses the engine's documented API (`geotruth.relate`, `geotruth.overlay`) where it is
importable and the audited references of `tests/reference/` otherwise; the harness fallback
overlay (`src/geotruth/harness/fallback_overlay.py`) assembles polygons from the reference
arrangement until `geotruth.overlay` lands.

Relate, predicates and overlay are `"unsupported"` for invalid input (the engine defines
them for valid input only) and `null` where the engine abstains (`engine_skipped`).

**Valid rounding.** Rounding an exact result to doubles can make it invalid: a hole within
an ulp of its shell crosses it, or a sliver collapses to a zero-area ring. When that
happens the polygonal part is replaced by the exact regularization (positive winding
number of the oriented rings) of its own rounded rings, and rounded again, at most 4
rounds. Each round moves a vertex by at most √2/2 ulp(M), so the manifest's δ is
`{kind = "ulp", value = 3}`. Such output grades `budget` (tier 3), which is not a headline
failure.

## Isolation

Each operation runs in a forked worker process that streams its result back. An
operation over `GEOTRUTH_OP_TIMEOUT` / `CONTROL_ADAPTER_TIMEOUT` seconds (default 10) is
killed (`{"kind": "timeout"}`), a dead worker fails that operation (`{"kind": "crash"}`)
and a fresh worker carries on; the worker's address space is capped at
`GEOTRUTH_ADAPTER_MEM_MB` (default 4096; `MemoryError` is `{"kind": "memory"}`).

## Results

Core tier (3400 cases), 2026-09-26: **0 headline failures and 0 scorer failures**. Every
relate, predicate, validity and echo answer is correct; the overlays grade `exact` or
`rounding`, apart from a handful in `budget` after regularization. The expected answers
came from the engine route (`geotruth.relate`, `geotruth.overlay`); on the 7952
(case, op, variant) overlays that the harness fallback overlay also answers, the two
routes give identical point sets (`tests/harness/test_score_crosscheck.py` checks a
sample).
