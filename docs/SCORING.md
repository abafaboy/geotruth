# Scoring

`geotruth score` grades a library's answers against the exact answers. This page says what
is graded, how, and the rules that keep the grading fair. The implementation is
[`src/geotruth/harness/score.py`](../src/geotruth/harness/score.py) and
[`metrics.py`](../src/geotruth/harness/metrics.py); the design is
[DESIGN.md §4.3](DESIGN.md#43-scoring-scorepy).

## What is graded

One record ([`score.v2`](../schemas/score.v2.schema.json)) per (case, library,
capability):

| capability | graded on |
|---|---|
| `echo` | the parse-echo canary: the operands the adapter read, written back, must be the case's doubles bit for bit (`-0.0` keeps its sign) |
| `relate` | the DE-9IM matrix string, exactly |
| `predicates` | all ten named predicates of the case together, exactly: one record per case, however many predicates are wrong |
| `validity` | `valid_a` and `valid_b`, on the boolean (the reason is informational) |
| `overlay.intersection`, `.union`, `.difference`, `.symdifference` | the output geometry, in tiers (below) |

Relate, predicates and overlay are defined only for valid operands, so a case with an
invalid operand gets validity (and echo) records only.

## Verdicts

| verdict | meaning | counted against the library |
|---|---|---|
| `correct` | agrees with the exact answer (overlay: tiers 1-3) | no |
| `wrong` | disagrees (overlay: tiers 4-5) | **yes** |
| `error` | an exception, crash, hang or memory failure (overlay: tier 6) | **yes** |
| `convention` | disagrees only on a field that the empty-geometry convention table decides | no |
| `unsupported` | the input is outside the library's documented contract (the adapter says so) | no |
| `not_reported` | the library does not provide the field (`null`) | no |
| `engine_skipped` | the exact engine abstained: the case is over its budget | no |
| `engine_error` | the exact engine failed or its independent checks disagreed | no |

The **headline** of a library is the number of `wrong` and `error` records, with a fault
counted once where the manifest declares a field derived from another (below). For overlay
it is tiers 4-6.

## Exact capabilities

Relate and predicates on exact input are exact questions, so any disagreement is wrong,
with two exceptions:

- **Conventions.** With an empty operand the matrix does not settle every predicate, and
  libraries follow different conventions. geotruth reports the GEOS 3.13 / JTS RelateNG
  answer and records the alternative in a convention table
  ([`src/geotruth/predicates.py`](../src/geotruth/predicates.py)):
  `equals(EMPTY, EMPTY)` is true in RelateNG although the pattern gives false;
  `contains`/`covers(X, EMPTY)` and `within`/`covered_by(EMPTY, X)` are false in GEOS,
  while set inclusion says true. A disagreement only on such a field is `convention`.
- **Derived fields.** A manifest may declare a field derived from another call, for
  example Boost's `contains(A, B)` computed as `within(B, A)`, or a predicate read off the
  library's relate matrix. When a derived predicate is wrong because the relate it comes
  from is wrong in the same case, the record is marked `derived`: the fault is counted
  once, under relate. The same holds for overlays (Turf's symmetric difference is built
  from two differences).

The named predicates are read off the matrix by dimension, exactly as JTS
`IntersectionMatrix` / RelateNG do (the table is in
[DESIGN.md §1](DESIGN.md#de-9im) and in `predicates.py`).

## Overlay tiers

A library's overlay output is compared with the exact result in exact arithmetic: the
library's doubles are converted to rationals exactly, the squared Hausdorff distance is
computed exactly (as a quadratic surd), and the symmetric-difference area exactly. M is
the largest absolute input ordinate of the case, and P_E, P_L are the perimeters of the
exact result and the library's output.

| tier | name | condition | verdict |
|---|---|---|---|
| 1 | `exact` | the same point set: Hausdorff distance 0 and symmetric-difference area 0 | correct |
| 2 | `rounding` | within the correctly rounded floor, δ = ulp(M)/√2 (see the two conditions below) | correct |
| 3 | `budget` | within the library's own budget δ_lib (the same two conditions) | correct |
| 4 | `gross` | beyond | wrong |
| 5 | `topological` | invalid output, or a missing or extra component or hole | wrong |
| 6 | `exception` | an exception, crash, hang or memory failure | error |

Tiers 2 and 3 both need

- Hausdorff distance ≤ δ, and
- |E ⊕ L| ≤ 2δ(P_E + P_L) + πδ²·n, the area of a δ-tube around both boundaries (n is
  the number of vertices). Irrational quantities in this bound (perimeters, π, δ) are
  replaced by rational upper bounds, so the bound's own rounding never makes a library
  gross.

In tiers 2 and 3, exact components and holes thin enough to fit inside the δ-tube of their
own boundary may vanish or collapse, and so may any part of the exact boundary within 2δ
of another part of it (a thin spike, a thin gap between two rings). They are left out of
the exact-to-library direction of the Hausdorff distance; the library-to-exact direction
and the area bound still apply in full.

**Which exact result.** The exact overlay comes in two variants: non-strict (OverlayNG's
default, keeping the lines and points of boundary touches) and regularized areal (the
polygonal part only). A library's output is compared with the non-strict result when the
output has lower-dimensional parts, and with the areal result otherwise, so polygon-only
clippers are judged on what they promise. An invalid output is measured by even-odd
parity.

### The displacement budget δ_lib

δ_lib comes from the library's manifest (`[target.precision].delta`), never from its
results:

| kind | δ |
|---|---|
| `relative` | value × M |
| `ulp` | value × ulp(M) |
| `absolute` | value |
| `grid` | value × the grid step described by the manifest's `grid` |
| `undocumented` | none: the library documents no bound, so its output is graded in tiers 1, 2, 4-6 only |

The values in the manifests today:

| target | δ_lib | source |
|---|---|---|
| GEOS (`geos-main`, `geos-release`, `shapely`), JTS (`jts-main`, `jts-release`) | 1e-8 × M | the loosest documented fallback of OverlayNGRobust (the 5th snapping try); marked uncertain in the manifests |
| JSTS | 2e-9 × M | its snapping tolerance; marked uncertain |
| CGAL | 1.58e-16 × M | output rounding only (CGAL computes exactly) |
| Clipper2 | 2 grid units | its integer grid and its documented small-triangle removal |
| georust `geo` | 2 grid steps (step ≤ 2^-28.5 H) | i_overlay's integer grid; marked uncertain |
| Boost.Geometry, Turf, polygon-clipping, polyclip-ts, martinez | undocumented | no documented bound |
| controls (`engine-control`, `mutant`) | 3 × ulp(M) | the control's own valid rounding |

A budget marked uncertain is a reading of the library's source or documentation that has
not been confirmed by its maintainers. Corrections are welcome: see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Fairness rules

1. **A library is judged only on what it promises.** Input outside its documented contract
   (coordinates beyond Clipper2's range, GeometryCollections where a library has no GC
   semantics, line output from a polygon-only clipper) is `unsupported`, never `wrong`.
   The adapter decides this from the library's documentation, and the manifest records it.
2. **Overlay is graded against the library's own precision model**, in tiers, not against
   bit-exactness. Only tiers 4-6 count.
3. **The engine may abstain**, and an abstention (`engine_skipped`, `engine_error`) is
   never counted against a library.
4. **A fault is counted once.** Predicates are one record per case, and fields derived
   from another call are marked `derived` when that call is wrong in the same case.
5. **Conventions are not errors.** Disagreements that depend on an empty-geometry
   convention are reported separately.
6. **Tolerance-based predicates are labelled.** A library whose manifest says it uses
   tolerances in predicates (Turf, Boost's equals) has `|tolerance` appended to its
   predicate failure clusters, so readers can tell design from defect.
7. **No automated disagreement is presented as a confirmed bug.** Failures are grouped
   into clusters (library × family × signature), and each cluster has a triage status in
   [`findings/registry.toml`](../findings/registry.toml): unreviewed, confirmed,
   by-design, reported or fixed.
8. **There is no single ranking.** The corpus is deliberately adversarial: rates measure
   behaviour on near-degenerate input, not how often a library fails on real-world data.
   Results are reported per capability, never as one total per library.
9. **Maintainers get notice** before their library's results are first published
   ([DESIGN.md §6](DESIGN.md#6-site-site)); `geotruth site --preview` builds the pages they
   are shown.
10. **Everything is recorded.** Every result carries the library version or commit, the
    adapter hash, the compiler and flags, non-default options, the engine version and the
    corpus version (`run.json`, and `versions` in every score record).
11. **The harness is itself tested.** The engine control (the exact engine behind the
    adapter contract) must score no headline failure, and the mutant (the control with
    faults planted on purpose) must have every fault caught.

Not implemented yet: DESIGN.md also mentions an optional mode that grades GEOS's
floating-noder output alone, to separate failures of the precise path from documented
snapping.

## Failure clusters

Each wrong or error record carries a cluster key `library|family|signature`, for example
`mutant|vertex-on-edge|predicates:within` or `mutant|multi-touch|overlay.difference:gross`
(from the worked example below). For predicates the signature lists the predicates that
disagree; for relate, the matrix entries that differ; for overlay, the tier. The summary
lists clusters by size, and the site gives each cluster a page with examples.

## A worked example: the two controls

The two harness controls show what the scorer does with a perfect answer sheet and with a
sabotaged one. These are real runs on the core tier (3400 cases) from 2026-09-26, engine
0.1.0, corpus 2.0.0, against the committed expected answers:

```sh
geotruth run   --lib engine-control --tier core --out results
geotruth score --lib engine-control --tier core --results-dir results \
               --expected corpus/expected/core.jsonl
```

```
library geotruth-control@0.1.0: 3400 cases, 0 headline failures (wrong or error, derived counted once; overlay tiers gross, topological, exception)

capability                      correct          wrong          error     convention    unsupported   not_reported engine_skipped   engine_error
------------------------------------------------------------------------------------------------------------------------------------------------
relate                             3200              0              0              0              0              0              0              0
predicates                         3200              0              0              0              0              0              0              0
validity                           3400              0              0              0              0              0              0              0
overlay.intersection               3200              0              0              0              0              0              0              0
overlay.union                      3200              0              0              0              0              0              0              0
overlay.difference                 3200              0              0              0              0              0              0              0
overlay.symdifference              3200              0              0              0              0              0              0              0

overlay tiers                   exact     rounding       budget        gross  topological    exception
overlay.difference               2052         1147            1            0            0            0
overlay.intersection             2059         1141            0            0            0            0
overlay.symdifference            2010         1185            5            0            0            0
overlay.union                    1997         1203            0            0            0            0
```

The control computes every answer exactly, so it has no headline failure. Its overlay
output is in tier 2 wherever an exact vertex is not a double and had to be rounded, and
in tier 3 in the few cases where rounding made a ring invalid and the control had to
repair it (its δ_lib of 3 ulps covers that). Relate, predicates and overlay have 3200
records, not 3400, because the 200 cases of the `invalid-zero-length-line` family have an
invalid operand: they are graded on validity only.

The mutant is the same engine with faults planted on purpose (every 17th predicate
negated, every 17th polygonal overlay output bent; see
[`adapters/mutant/README.md`](../adapters/mutant/README.md)):

```
library geotruth-mutant@0.1.0: 3400 cases, 2368 headline failures (wrong or error, derived counted once; overlay tiers gross, topological, exception)

capability                      correct          wrong          error     convention    unsupported   not_reported engine_skipped   engine_error
------------------------------------------------------------------------------------------------------------------------------------------------
relate                             3200              0              0              0              0              0              0              0
predicates                         1317           1855              0             28              0              0              0              0
validity                           3400              0              0              0              0              0              0              0
overlay.intersection               3107             93              0              0              0              0              0              0
overlay.union                      3051            149              0              0              0              0              0              0
overlay.difference                 3073            127              0              0              0              0              0              0
overlay.symdifference              3056            144              0              0              0              0              0              0

overlay tiers                   exact     rounding       budget        gross  topological    exception
overlay.difference               1990         1082            1           91           36            0
overlay.intersection             2024         1083            0           61           32            0
overlay.symdifference            1925         1126            5           99           45            0
overlay.union                    1903         1148            0          116           33            0
```

All 1883 negated predicates and all 513 bent overlays are detected: 1855 + 28 predicate
records and 93 + 149 + 127 + 144 overlay records. The 28 predicate records graded
`convention` rather than `wrong` are empty-geometry cases where the flipped value is the
other legitimate convention, which is what the convention rule is for; they are not
counted in the headline. Here is one of those records, and one of the bent overlays:

```json
{"id": "empty-1-000027-empty-empty.unit", "family": "empty", "capability": "predicates",
 "verdict": "convention", "fields": ["predicates.covered_by"],
 "expected": {"covered_by": false}, "got": {"covered_by": true}, ...}
```

```json
{"id": "vertex-on-edge-1-000093-inscribed.n128.unit", "lib": "geotruth-mutant@0.1.0",
 "family": "vertex-on-edge", "capability": "overlay.union", "verdict": "wrong", "tier": "gross",
 "metrics": {"variant": "areal", "output_valid": true,
             "symdiff_area": "73730329739151921669/151115727451828646838272",
             "hausdorff2": "5436161523444070277620761508975511745561/841742464469957448627495260107775598433140736",
             "delta_rounding": 3.925231146709438e-17, "delta": 1.6653345369377348e-16,
             "delta_kind": "ulp", "area_budget": 1.057401552521834e-15},
 "cluster": "mutant|vertex-on-edge|overlay.union:gross", ...}
```

`symdiff_area` and `hausdorff2` (the squared Hausdorff distance) are exact rationals; the
output is valid, but its Hausdorff distance from the exact union is about 2.5e-3 and the
symmetric-difference area about 4.9e-4, far beyond δ ≈ 1.7e-16 and the area budget
≈ 1.1e-15.

## Output files

`geotruth score --lib TARGET --tier TIER` reads `<results>/<target>/<tier>.jsonl` (written
by `geotruth run`) and writes next to it:

| file | what |
|---|---|
| `<tier>.score.jsonl` | one score.v2 record per (case, capability) |
| `<tier>.summary.json` | the counts, tiers and clusters, for machines |
| `<tier>.summary.txt` | the table above, also printed |

The exact answers come from `--expected` (the committed `corpus/expected/<tier>.jsonl`) or,
without it, are computed by the engine and cached under `<results>/_expected/`. Exit status
3 means the scorer itself failed on a record (a harness bug, never the library's).
