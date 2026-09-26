# harness (v1)

The bug-hunt harness that geotruth grows out of: the v1 contract, the comparer and the
round driver. The v2 harness of DESIGN.md §4 (typed geometries, relate matrices, tiered
overlay scoring) will live in `src/geotruth/harness/`; until it lands, this is what runs.

| file | what |
|---|---|
| [`FORMAT-v1.md`](FORMAT-v1.md) | the v1 case and result format, and the adapter contract |
| [`compare.py`](compare.py) | lists every disagreement between an adapter's results and the exact answers |
| [`hunt.sh`](hunt.sh) | one round: generate cases, compute exact answers, run every adapter, compare, tally |
| [`tally.py`](tally.py) | disagreements per library and kind for a round's output directory |
| [`lib_string.sh`](lib_string.sh) | prints an adapter's `lib` string (version) by running it on one seed case |

## A round

The adapters must be built first (each `adapters/<lib>/build.sh`, and
`adapters/js/install.sh`). Build trees and round output go under `$GEOTRUTH_BUILD_DIR`,
which defaults to `~/.cache/geotruth`:

```sh
harness/hunt.sh --seed-only                 # only the tracked corpus/cases/seed.jsonl
harness/hunt.sh 1000 3                      # generated families + review families + seed
HUNT_LIBS="shapely clipper2" harness/hunt.sh --seed-only   # a subset of the libraries
```

A round writes `cases/`, `cases-small/` (the first 150 cases of each file, for Turf and
martinez, which are slow), `results-cases*/{oracle,<lib>,compare-<lib>}/`,
`summary-<lib>.txt` (per-family summary from `corpus/generators/summarize.py`) and
`tally.txt`.

## One adapter by hand

```sh
adapters/clipper2/run.sh corpus/cases/seed.jsonl > /tmp/clipper2.jsonl
python3 harness/compare.py corpus/cases/seed.jsonl corpus/expected-v1/seed.jsonl /tmp/clipper2.jsonl
```

`corpus/expected-v1/seed.jsonl` holds the exact answers for the seed corpus; for any other
case file, compute them with `python3 tests/reference/oracle.py CASES.jsonl > ORACLE.jsonl`.

## Seed baseline

`GEOTRUTH_BUILD_DIR=... harness/hunt.sh --seed-only` on the 1000 seed cases, 2026-09-26, about
30 s on 2 cores. Numbers are compare.py records (one case can give several). Every
adapter's output is byte-identical to its run before the move into this layout, except that
martinez's timeout messages now say 2 s (hunt.sh's budget for it) instead of 10 s.

| library | cases | records | kinds |
|---|---:|---:|---|
| shapely (GEOS 3.13.1) | 1000 | 0 | |
| geos-main | 1000 | 0 | |
| jts-main | 1000 | 0 | |
| clipper2 | 1000 | 15 | error `unsupported`: tiny-rotation cases that need a scale beyond 2^60 |
| boost-1.83 | 1000 | 229 | predicate (76 cases) |
| boost-develop | 1000 | 249 | 247 predicate, 2 area (82 cases) |
| rust-geo | 1000 | 0 | |
| polyclip-ts | 1000 | 0 | |
| polygon-clipping | 1000 | 24 | 23 error ("Unable to complete output ring"), 1 area (7 cases) |
| turf | 150 | 166 | predicate (116 cases) |
| martinez | 150 | 54 | 41 area, 13 error: timeouts at 2 s (19 cases) |

None of these is triaged; see [`findings/registry.toml`](../findings/registry.toml) for what is.
