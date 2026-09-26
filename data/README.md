# Score data (`data/`)

Compact summaries of `geotruth score` for every adapter target, on the `core` tier (3400
cases) and the `curated` tier (131 cases), small enough to keep in git. They are counted from
the full score records, which are not in git: `geotruth score` writes those next to the
library's answers under `results/` (git-ignored), and the site is built from them
(`geotruth site --scores results`, see [`../site/README.md`](../site/README.md)).

The corpus is deliberately adversarial: near-degenerate input, chosen to find the edge of
each library's arithmetic. The rates below are therefore not real-world failure rates, and
there is no single ranking: compare libraries per capability, and read a failure cluster as
unreviewed unless [`../findings/registry.toml`](../findings/registry.toml) says otherwise.

| file | what |
|---|---|
| `scores/<target>.json` | one target (for example `geos-main`): the build and its precision model, then per tier the run's provenance, per-capability verdict counts, overlay tiers, error kinds, failures per corpus family, and the largest failure clusters |
| `scores/summary.json` | all targets in one file: per target and tier the headline, timeouts, crashes and per-capability counts and rates; the corpus, expected-answer and engine versions of each tier; the controls |
| `scores/controls.json` | the checks of the three controls (below) |
| `scores/summarize.py` | writes `<target>.json` and `summary.json` from `results/` |
| `scores/controls.py` | checks the controls and writes `controls.json` |

## Reproducing

```sh
export GEOTRUTH_BUILD_DIR=~/.cache/geotruth        # where the library builds live
adapters/<dir>/build.sh                            # once per adapter (see adapters/README.md)
for t in $(geotruth run --list | awk '{print $1}'); do
  for tier in core curated; do
    geotruth run   --lib "$t" --tier "$tier" --out "results/$tier"
    geotruth score --lib "$t" --tier "$tier" --results-dir "results/$tier" \
                   --expected "corpus/expected/$tier.jsonl"
  done
done
python3 data/scores/controls.py --results results --run-cgal   # writes controls.json
python3 data/scores/summarize.py --results results             # writes the rest
```

`summarize.py` counts everything from the score records itself, and stops if its headline
disagrees with the scorer's own summary, or if the scorer reported a failure of its own.
Neither script writes a time stamp, so the same inputs give the same bytes.

## The controls

`controls.json` must say `"ok": true` before any number here is used.

- **engine-control** is the exact engine behind the adapter contract. Every record it gets
  must be graded `correct`.
- **mutant** is the same engine with faults planted on purpose (every 17th predicate
  negated, every 17th polygonal overlay output bent, see
  [`../adapters/mutant/README.md`](../adapters/mutant/README.md)). The changed fields are
  found by comparing its answers with engine-control's, case by case. Every changed (case,
  capability) must be graded `wrong`, or `convention` where the flipped value is the other
  empty-geometry convention, and no other record may be graded differently from the
  control's.
- **cgal** is CGAL with an exact kernel, an external control that shares no code with the
  engine. Its exact side-car (`adapters/cgal/run.sh --exact`: every overlay result in exact
  rationals) is rerun on the tier's cases, and its rounded answers must be the ones that were
  scored. For every overlay, the exact area must equal the expected answer's, the point set
  must be the same (symmetric-difference area 0 and Hausdorff distance 0, computed exactly),
  and the exact result must be OGC-valid.

CGAL's *scored* overlay output is its exact result rounded to doubles, and rounding can make
a valid polygon invalid (a thin ring collapses, two close edges cross). Those outputs are
graded `topological` like any other invalid output; `topological.invalid_output_within_rounding`
shows that they are within the rounding floor.

## Reading the numbers

Verdicts and tiers are defined in [`../docs/SCORING.md`](../docs/SCORING.md). For each target,
tier and capability (`relate`, `predicates`, `validity`, `overlay.intersection`,
`overlay.union`, `overlay.difference`, `overlay.symdifference`):

| field | meaning |
|---|---|
| `correct` … `engine_error` | score records per verdict |
| `graded` | `correct` + `wrong` + `error` + `convention`: the records that compare the library with an exact answer |
| `derived` | `wrong` or `error` records of a field the manifest declares derived from another call that is wrong in the same case (counted once, under that call) |
| `failures` | `wrong` + `error` − `derived`: this capability's part of the headline |
| `failure_rate` | `failures / graded`, rounded to 6 digits; `null` when nothing was graded |
| `by_range` | `graded` and `failures` per coordinate range tag (`normal`, `extreme`) |
| `error_kinds` | `error` records by kind: `exception`, `crash`, `timeout` (3 s per operation), `memory` |
| `overlay_tiers` | overlay records per tier: `exact`, `rounding`, `budget` (correct), `gross`, `topological` (wrong), `exception` (error) |
| `topological` | the counted `topological` records split by cause: `invalid_output` (not OGC-valid), and among those `invalid_output_exact_point_set` (the exact point set, in an invalid representation) and `invalid_output_within_rounding` (Hausdorff distance within the rounding floor, exact point sets included); `missing_or_extra_parts` (valid, but a component or hole missing or extra) |
| `invalid_output_reasons` | the first OGC validity reason of the invalid outputs |

Each tier of `<target>.json` also has `headline_failures` (the sum of `failures`), `cases`
(`total`, `run`, `scored`), the runner's health counters (`runner`), `families` (per corpus
family, the capabilities with failures), `clusters` (the 40 largest failure clusters,
`library|family|signature`, with `clusters_total` and the records of the omitted ones), and
for the curated tier `case_verdicts` (every case's verdicts). `run` is the provenance from
`run.json`: dates, runner image, per-operation timeout, the library version and commit the
build reported, and the adapter's manifest hash and git commit (`+dirty` when the adapter had
uncommitted changes).

`unsupported` (outside the library's documented contract) and `not_reported` (a field the
library does not provide) are never graded. Relate, predicates and overlay are defined only
for valid operands, so the 200 cases of the `invalid-zero-length-line` family have validity
records only.

Some counts reflect a difference of model rather than a wrong number, and are graded as
failures all the same; the fields above let a reader separate them:

- **Output representation.** An overlay output that is not OGC-valid is `topological` even
  when its point set is exact. Not every library promises OGC's rules: polygon-clipping and
  polyclip-ts document that the rings of a polygon may touch each other, which lets holes cut
  an interior in two (OGC: disconnected interior). `topological.invalid_output_exact_point_set`
  and `topological.invalid_output_within_rounding` count the topological verdicts that are
  invalid representations of the exact point set, or of one within the rounding floor.
- **Validity rules.** Boost.Geometry reports empty geometries invalid (OGC and GEOS: valid);
  CGAL reports a hole touching the shell at a point inside an edge invalid (OGC: valid);
  Turf's `booleanValid` rejects MultiPolygons whose parts touch at a point. The
  empty-geometry convention table covers predicates only, so these are `wrong`.
- **Adapter options.** Options that depart from a library's defaults (for example Turf's
  `booleanEqual` precision) are listed in each target's `options`.

## This snapshot

- Runs: 2026-09-26, every target on one host (Ubuntu 24.04.4 LTS VM, 4 cores, Python
  3.11.15), per-operation timeout 3 s, from 11:49 to 11:59 UTC (the `core` tier, then the
  `curated` tier, which is built from the registry's 14 findings and the leads). Library
  builds and versions are in each `<target>.json`.
- geotruth: every run at the v0.1.0 release commit `3a72e05`, from a clean checkout.
  `summary.json` → `geotruth` records the commit the summary was made at and whether the
  checkout was clean (changes under `data/scores/` itself do not count). The adapter commit
  recorded for each target is the last commit that changed that adapter's directory.
- Engine 0.1.0, corpus 2.0.0, expected answers v2: `core.jsonl` sha256 `70c78e04…`,
  `curated.jsonl` sha256 `daf738bb…` (full hashes in `summary.json` → `tiers`), with no
  `engine_skipped` or `engine_error` record.
- On the curated tier, GEOS main, 3.15.0 and 3.13.1 (through Shapely) crash on 12
  operations each: the cases of the `geos-relateng-segfault` finding. The adapters isolate
  every operation, so each crash is recorded as an `error` of that operation only.
- The parse-echo canary (DESIGN.md §4.1, `schemas/examples/case.v2.valid.json`) comes back
  bit for bit from 17 of the 18 targets. CGAL returns `-0.0` as `0.0`, as its README
  documents (an exact rational has no signed zero).
- Every target was run and scored three times on the core tier, from scratch (runs from
  08:21 to 08:40, 09:06 to 09:23 and 11:49 to 11:58 UTC). Apart from CGAL, whose adapter
  changed after the first run, the libraries' answers came out byte-identical, and so did the
  score records, except for the adapter commit they record. The release run gave the same
  verdict on every score record of both tiers as the run before it. `controls.py --run-cgal`
  recomputed CGAL's exact side-car for both tiers after the release run, and every control
  held again.
