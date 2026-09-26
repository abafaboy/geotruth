# geotruth

**The exact answer to geometry questions, and a test suite that checks geometry libraries
against it.**

Do these two polygons overlap or only touch? What is their intersection? Is this polygon
valid? Geometry libraries answer such questions in floating point, and near a degeneracy
(a vertex a few ulps off an edge, two edges almost collinear) they can answer wrongly.
geotruth computes the one correct answer, in exact arithmetic on the exact input doubles,
and grades each library against it, judged only on what the library itself promises.

## An example

Two valid triangles. B's first vertex is A's vertex (-1.7, 1.9) moved by 1 ulp in x and
2 ulps in y:

```
A = POLYGON ((-0.6 3, 2 -1, -1.7 1.9, -0.6 3))
B = POLYGON ((-1.6999999999999997 1.9000000000000004, -1 2, -2.6 1, -1.6999999999999997 1.9000000000000004))
```

|  | Boost.Geometry 1.92.0 | exact (geotruth) |
|---|---|---|
| `relation(A, B)` | `2FF10F212` | `212101212` |
| `within(A, B)` | true | false |
| `overlaps(A, B)` | false | true |
| area of A ∩ B | 3.6299999999999994 (all of A) | 0.07769784172661882 |
| area of A ∪ B | 0.27000000000000024 (B alone) | 3.8223021582733816 |

A has area 3.63 and B 0.27, so A cannot lie within B. Boost.Geometry 1.83 prints the right
answer; 1.87.0 to 1.92.0 and the current `develop` print the wrong one. The case was
minimised from a corpus case and the regression bisected to one commit. It is
[`boost-geometry-develop-regression`](findings/boost-geometry-develop-regression/FINAL.md)
in the triage registry, with status *confirmed, not yet reported upstream*.

The exact relate, from the command line (`geotruth overlay` gives the areas, as exact
rationals):

```console
$ geotruth relate "POLYGON ((-0.6 3, 2 -1, -1.7 1.9, -0.6 3))" \
    "POLYGON ((-1.6999999999999997 1.9000000000000004, -1 2, -2.6 1, -1.6999999999999997 1.9000000000000004))" --dual
A: Polygon (4 coordinates; real dimension 2)
B: Polygon (4 coordinates; real dimension 2)
relate: 212101212
      I  B  E
   I  2  1  2
   B  1  0  1
   E  2  1  2
predicates:
  intersects  true
  disjoint    false
  touches     false
  crosses     false
  overlaps    true
  contains    false
  covers      false
  within      false
  covered_by  false
  equals      false
witness route: 212101212 agrees
```

## What geotruth is

- **An exact engine** ([`src/geotruth/`](src/geotruth/)). DE-9IM relate and the named
  predicates, overlay (intersection, union, difference, symmetric difference), validity
  and measures, decided in exact integer and rational arithmetic, with no tolerance in any
  decision. It follows the OGC Simple Features semantics as implemented by JTS/GEOS
  RelateNG and OverlayNG, for every geometry type including GeometryCollections and empty
  geometries.
- **A corpus** ([`corpus/`](corpus/), CC0). 17 families of near-degenerate cases: vertices
  on edges, nearly collinear edges, shared edges, slivers, holes and parts that touch,
  tilings, integer grids, extreme coordinates (below 1e-150 and above 1e150), lines and the
  Mod-2 boundary rule, points, GeometryCollections, empty geometries. Tiers: `core` (3,400
  cases, 200 per family), `full` (17,000) and `curated` (the minimal cases of every
  finding). The exact answers to the core and curated tiers are in
  [`corpus/expected/`](corpus/expected/); the full tier's are regenerated with
  `geotruth expect` and checked against the manifest there.
- **A harness** ([`adapters/`](adapters/), `geotruth run`, `geotruth score`). Adapters for
  16 builds of 11 libraries (GEOS, JTS, Boost.Geometry, Clipper2, CGAL, georust `geo`,
  Turf, JSTS, polygon-clipping, polyclip-ts, martinez), each with a manifest of what the
  library promises: supported fields, precision model, overlay displacement budget,
  coordinate range. Crashes and hangs are isolated per operation.
- **A scoreboard and a triage registry.** Per-library results by capability, a static site
  with a page per failure cluster, and [`findings/registry.toml`](findings/registry.toml),
  where every cluster a person has looked at has a status.
- **Tools for maintainers.** Exact answers for any input, a delta-debugging minimiser, and
  exports of cases with exact answers to each library's own test format.

## Results

Every library target on the `core` tier (3,400 cases), graded against the committed exact
answers. Runs of 2026-09-26; builds and versions are in
[`data/scores/`](data/scores/), which also explains every field.

> **Read this first.** The corpus is adversarial by design: 2,856 of the 3,400 core cases
> contain an exact degeneracy (a vertex on an edge, collinear edges, touching parts) or one
> within a few ulps, and 268 use coordinates beyond 1e±150. These counts say how a library
> handles such input. **They are not real-world failure rates, and this is not a ranking.** Libraries promise different
> things (exact predicates, a snapping grid, polygon-only clipping), and each is graded
> against its own documentation. A failure cluster is an automated disagreement, not a
> confirmed bug, until triage says otherwise ([Findings](#findings)).

Each cell is *failures / answers graded*. A failure is a wrong answer or an error (an
exception, a crash or a timeout). Overlay output is graded in six tiers against the
library's own documented precision; only tiers 4 to 6 (gross, topological, exception) count
here, so output that is off by rounding, or within the library's documented budget, is
correct. "—" means the library does not offer the capability or the adapter does not
report it.

| library | build | relate | predicates | validity | A ∩ B | A ∪ B | A − B | A ⊕ B |
|---|---|---|---|---|---|---|---|---|
| Boost.Geometry | `boost-geometry@1.83` | 580 / 2,883 | 388 / 2,883 | 408 / 3,340 | 186 / 2,012 | 409 / 2,012 | 319 / 2,012 | 438 / 2,012 |
| Boost.Geometry | `boost-geometry@1.92` | 577 / 2,883 | 369 / 2,883 | 408 / 3,340 | 177 / 2,012 | 362 / 2,012 | 282 / 2,012 | 352 / 2,012 |
| Boost.Geometry | `boost-geometry@develop-196d04c` | 577 / 2,883 | 369 / 2,883 | 408 / 3,340 | 177 / 2,012 | 362 / 2,012 | 282 / 2,012 | 352 / 2,012 |
| CGAL (exact kernel) ¹ | `cgal@5.6` | — | 0 / 2,002 | 30 / 1,987 | 36 / 2,012 | 20 / 2,012 | 21 / 2,012 | 75 / 2,012 |
| Clipper2 | `clipper2@2.0.1-f9c5eb6` | — | 0 / 1,961 | — | 94 / 1,961 | 116 / 1,961 | 201 / 1,961 | 338 / 1,961 |
| GEOS | `geos@3.15.0` | 166 / 3,200 | 105 / 3,200 | 50 / 3,400 | 88 / 3,200 | 82 / 3,200 | 73 / 3,200 | 106 / 3,200 |
| GEOS | `geos@3.16.0dev-ae9cdd9` | 166 / 3,200 | 105 / 3,200 | 50 / 3,400 | 88 / 3,200 | 82 / 3,200 | 73 / 3,200 | 106 / 3,200 |
| GEOS through Shapely | `geos@3.13.1+shapely@2.1.2` | 162 / 3,200 | 103 / 3,200 | 45 / 3,400 | 68 / 2,990 | 66 / 2,990 | 50 / 2,990 | 64 / 2,990 |
| georust `geo` (i_overlay) | `geo@0.33.1` | 178 / 3,106 | 0 / 3,106 | 41 / 3,386 | 48 / 2,012 | 67 / 2,012 | 84 / 2,012 | 27 / 2,012 |
| JSTS | `jsts@2.12.1` | 97 / 2,934 | 82 / 2,934 | 52 / 3,400 | 178 / 3,200 | 116 / 2,990 | 104 / 2,990 | 93 / 2,990 |
| JTS | `jts@1.20.0` | 170 / 3,200 | 100 / 3,200 | 44 / 3,400 | 48 / 2,984 | 60 / 2,968 | 37 / 2,976 | 59 / 2,968 |
| JTS | `jts@1.21.0-SNAPSHOT-3ea61f8` | 160 / 3,200 | 102 / 3,200 | 44 / 3,400 | 37 / 2,984 | 54 / 2,968 | 33 / 2,976 | 53 / 2,968 |
| martinez-polygon-clipping ² | `martinez@0.8.1` | — | — | — | 294 / 2,000 | 440 / 2,000 | 390 / 2,000 | 1,182 / 2,000 |
| polyclip-ts | `polyclip-ts@0.16.8` | — | — | — | 239 / 2,000 | 232 / 2,000 | 274 / 2,000 | 404 / 2,000 |
| polygon-clipping | `polygon-clipping@0.15.7` | — | — | — | 151 / 2,000 | 196 / 2,000 | 192 / 2,000 | 214 / 2,000 |
| Turf | `turf@7.4.0` | — | 1,392 / 3,000 | 547 / 3,297 | 239 / 2,000 | 232 / 2,000 | 274 / 2,000 | 162 / 2,000 |

How to read it:

- The answers graded differ between libraries: answers outside a library's documented
  contract are `unsupported` and not graded (for example Boost.Geometry's relate on 317
  core cases), and polygon clippers are graded only on polygon pairs.
- ¹ CGAL runs as an external control: its exact results agree with geotruth on every
  overlay (below). Its counted overlay failures are the rounding of those exact results to
  doubles for output, which can make a thin polygon invalid (every one of them is within the
  rounding floor). Its validity failures are polygons with a hole that touches the shell or
  another hole at a point, which OGC allows and CGAL's validity check rejects.
- ² martinez: 21 of its failures are timeouts (3 s per operation).
- Some failures are a difference of model rather than of arithmetic, and are counted all
  the same: an overlay output that covers the exact point set but is not OGC-valid (holes
  that cut an interior in two, which polygon-clipping and polyclip-ts allow), Boost's
  "empty geometries are invalid", Turf's tolerance-based predicates.
  [`data/README.md`](data/README.md) lists the fields that separate these.
- The per-library pages of the site (`geotruth site`, below) break every cell down by corpus
  family and failure cluster, with zoomed figures of each example.

## Quickstart

geotruth needs Python 3.10 or later; [gmpy2](https://pypi.org/project/gmpy2/) is installed
with it. It is not on PyPI yet:

```sh
git clone https://github.com/abafaboy/geotruth
cd geotruth
python -m venv .venv && . .venv/bin/activate
pip install -e .                  # or '.[dev]' for the tests and the linter
```

```console
$ geotruth version
geotruth 0.1.0.dev0 (engine 0.1.0)
python 3.11.15, gmpy2 2.3.1, rational backend gmpy2
```

**Relate.** Operands are WKT or typed JSON. They are read as a library reads them: every
number becomes the nearest double, and that double is the exact input. `0.1`, `0.3` and `0.9`
are not the decimals, and these three points are not collinear:

```console
$ geotruth relate "POINT (0.1 0.3)" "LINESTRING (0 0, 0.3 0.9)"
A: Point (1 coordinate; real dimension 0)
B: LineString (2 coordinates; real dimension 1)
relate: FF0FFF102
      I  B  E
   I  F  F  0
   B  F  F  F
   E  1  0  2
predicates:
  intersects  false
  disjoint    true
  touches     false
  crosses     false
  overlaps    false
  contains    false
  covers      false
  within      false
  covered_by  false
  equals      false
```

**Overlay.** The result three ways: a WKT rounded to doubles (for display only), the exact
result with rational coordinates, and the exact area. `--certify` runs the independent
certificate on it:

```console
$ geotruth overlay "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "POLYGON ((1 -1, 3 0.1, 1 3, 1 -1))" intersection --certify
A: Polygon (5 coordinates; dimension 2)
B: Polygon (4 coordinates; dimension 2)
intersection (non-strict): Polygon, 5 vertices
  wkt:   POLYGON ((1 0, 2 0, 2 1.55, 1.6896551724137931 2, 1 2, 1 0))
  exact: {"type": "Polygon", "coordinates": [[["1", "0"], ["2", "0"], ["2", "111689270758788301/72057594037927936"], ["176541105392923443/104483511354995507", "2"], ["1", "2"], ["1", "0"]]]}
  area:  29063881665648697606023744899294167/15057660889751000093915401739567104 (~1.9301724137931036)
  certificate: ok (57 witnesses)
```

**Validity**, with every defect and its exact location. A hole whose vertex touches the
shell is valid; move that vertex 1 ulp outward and it is not:

```console
$ geotruth valid "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0), (1 1, 3 1.5, 1 2, 1 1))"
Polygon: valid
$ geotruth valid "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0), (1 1, 3.0000000000000004 1.5, 1 2, 1 1))"
Polygon: INVALID
first reason (GEOS precedence and noding order): Self-intersection at (3, 6755399441055746/4503599627370497) [/ shell; / hole 1] (proper crossing)
defects (3):
  self_intersection        Self-intersection at (3, 6755399441055745/4503599627370497) [/ shell; / hole 1] (proper crossing)
  self_intersection        Self-intersection at (3, 6755399441055746/4503599627370497) [/ shell; / hole 1] (proper crossing)
  hole_outside_shell       Hole lies outside shell at (6755399441055745/2251799813685248, 3/2) [/ hole 1]
```

**Grade a library.** Build its adapter once (the build trees live under
`$GEOTRUTH_BUILD_DIR`, default `~/.cache/geotruth`), then run, score and look:

```sh
adapters/geos_main/build.sh                        # GEOS main (build.sh release: 3.15.0)
geotruth run   --lib geos-main --tier core --out results/core
geotruth score --lib geos-main --tier core --results-dir results/core \
               --expected corpus/expected/core.jsonl
geotruth site  --scores results/core               # static site in site/_build/
```

[docs/QUICKSTART.md](docs/QUICKSTART.md) has more: `--explain` (which cell realises each
matrix entry), JSON output, the regularized overlay variant, the corpus commands.

## How it works

**Doubles are rational numbers.** Every IEEE-754 double is m·2^e exactly, so a question
about the input doubles has exactly one right answer. geotruth scales each case by a power
of two to integers and decides every orientation, segment intersection and point location
in exact integer arithmetic. Intersection points are exact rationals (gmpy2, with Python's
`fractions` as an independent second backend). Nothing is rounded until the answer is
printed.

**Two independent routes for relate.** The DE-9IM matrix is computed from a labelled
arrangement of both operands (a DCEL), and again from witness points (every vertex,
intersection, edge midpoint and a point inside each face) located directly in the original
geometries by a standalone point locator. The two routes share only the arithmetic
primitives, and an expected answer is written only when they agree.

**A certificate for every overlay.** An independent checker builds a new arrangement of A,
B and the result R from scratch and checks, for every cell, that R's label equals the
operation applied to A's and B's labels. Relate and overlay are also checked against each
other, and areas against inclusion-exclusion.

**Abstain rather than guess.** A case over the engine's size budget is `engine_skipped`, and
an internal failure or a disagreement between routes is `engine_error`. Neither is ever
counted against a library.

**Controls.** Three adapter targets test the harness itself, and every scoreboard run
includes them:

- `engine-control`, the engine behind the adapter contract, must be graded correct on
  everything;
- `mutant`, the engine with faults planted on purpose, must have every fault caught;
- CGAL, with an exact kernel and no code shared with geotruth, must give the same exact
  overlay results.

What these checks came to in the runs behind this page:

| check | result |
|---|---|
| full tier recomputed from scratch (17,000 cases) | 16,000 pairs with both operands valid: both relate routes agree on all 16,000; all 128,000 overlay results (4 operations × 2 variants) pass the certificate; 0 skipped, 0 errors; output byte-identical to the committed answers (171.5 s wall on 2 worker processes) |
| `engine-control`, core tier | 22,600 of 22,600 score records graded correct |
| `mutant`, core tier | 2,396 planted faults: 2,368 graded wrong, 28 graded as the other empty-geometry convention, 0 missed, 0 other records changed |
| CGAL exact results, core tier | 8,048 overlays: exact area equal to geotruth's 8,048, same point set 8,048, OGC-valid 8,048 |

None of this makes the engine infallible. A case where geotruth is wrong is the most
valuable bug report this project can get ([CONTRIBUTING.md](CONTRIBUTING.md)).

**Judged on what each library promises.** Relate and predicates on exact input are exact
questions, so any wrong answer counts. Overlay output is graded against the library's own
documented precision model: exact, within the correctly rounded floor, within its
documented displacement budget δ_lib (for example Clipper2's integer grid or i_overlay's
snapping grid), gross, topological, or an exception. Input outside a library's contract is
`unsupported`, never wrong. See [docs/SCORING.md](docs/SCORING.md).

## Findings

A disagreement becomes a finding only after triage: reproduced on the library's latest
development code, minimised, the exact answer checked by independent routes, the library's
documentation checked for intended behaviour, and the upstream tracker searched for
duplicates. Every finding has a directory in [`findings/`](findings/) with its cases, a
standalone reproduction that uses only the library's public API, its output on each version
tested, and a drafted report.

**None of the confirmed findings below has been reported upstream yet.** The reports are
drafted in each directory and will be filed by a person, one at a time.

| finding | library | what goes wrong | status |
|---|---|---|---|
| [boost-geometry-develop-regression](findings/boost-geometry-develop-regression/FINAL.md) | Boost.Geometry 1.87 to 1.92, develop | two overlapping triangles with a near-coincident vertex: `within` is true, the intersection is all of A (bisected to 0edb673) | confirmed |
| [clipper2-polytree-nesting](findings/clipper2-polytree-nesting/FINAL.md) | Clipper2 1.5.3 to 2.0.1, main | PolyTree puts an inscribed hole at the top level and an inscribed island as a second hole; the flat result is right | confirmed |
| [clipper2-thin-triangle-dropped](findings/clipper2-thin-triangle-dropped/ISSUE.md) | Clipper2 | result triangles with an edge under 2 grid units are removed, whatever their area | by-design (documented) |
| [geo-i-overlay-thin-polygon-collapse](findings/geo-i-overlay-thin-polygon-collapse/ISSUE.md) | georust `geo` 0.33.1 | boolean operations snap to i_overlay's grid, so a polygon thinner than one step collapses | by-design (documented by i_overlay) |
| [geos-multipolygon-touching-parts-predicates](findings/geos-multipolygon-touching-parts-predicates/FINAL.md) | GEOS 3.13.1 to main, JTS RelateNG | a MultiPolygon whose parts touch vertex-to-edge neither contains nor covers its own part | confirmed |
| [geos-near-collinear-predicates](findings/geos-near-collinear-predicates/FINAL.md) | GEOS 3.13.1 to main, JTS RelateNG | a proper crossing whose rounded point lands on a vertex is lost: `touches` instead of `overlaps` | confirmed |
| [geos-overlay-geometrycollection](findings/geos-overlay-geometrycollection/FINAL.md) | GEOS 3.13.0 to main | overlay with GeometryCollection operands drops or keeps points and lines wrongly, or throws an assertion | confirmed |
| [geos-relateng-geometrycollection-semantics](findings/geos-relateng-geometrycollection-semantics/ISSUE.md) | GEOS 3.13.0 to main, JTS RelateNG | three defects in relate for GeometryCollections (mixed dimensions, overlapping polygons) | confirmed |
| [geos-relateng-line-end-skip](findings/geos-relateng-line-end-skip/ISSUE.md) | GEOS 3.13.0 to main | a shortcut skips later line ends and polygon boundaries, so the matrix depends on element order (fixed in JTS master for lines, not ported) | confirmed |
| [geos-relateng-segfault](findings/geos-relateng-segfault/ISSUE.md) | GEOS 3.13.1 to main | a crash on valid input in RelateNG | confirmed, high priority |
| [geos-tiny-coordinates-underflow](findings/geos-tiny-coordinates-underflow/FINAL.md) | GEOS, JTS | wrong segment intersections for coordinates beyond about 1e±103, and wrong orientations beyond about 1e±154 | confirmed, low priority |
| [geos-union-drops-polygon](findings/geos-union-drops-polygon/ISSUE.md) | GEOS 3.13.1 (Shapely 2.1.2 wheels), 3.14 | union returns one operand, intersection all of the other | fixed in GEOS 3.15.0 (libgeos/geos#1405) |
| [jts-master-union-extreme-regression](findings/jts-master-union-extreme-regression/ISSUE.md) | JTS 1.20.0 and master | two overlay defects: with coordinates above about 1.3e162 the result is an empty polygon, with no exception (a regression in unreleased master); union or symmetric difference with a point throws `ClassCastException` when a polygon collapses under a fixed precision model | confirmed |
| [turf-boolean-predicates](findings/turf-boolean-predicates/FINAL.md) | Turf 7.4, master | `booleanTouches` on polygons is decided from A's vertices only: a polygon touches itself, and real touches are missed | confirmed |

The registry also lists 4 unreviewed leads. Every other failure cluster on the site is
`unreviewed` unless a registry entry matches it, and a match is shown as a candidate
explanation, not a verdict. The policy for reporting, including crashes, which go through a
library's private channel first when it has one, is in [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md).

## For library maintainers

- **Run your own branch.** Each adapter's build script takes a commit, and `--prefix`
  runs the adapter from that build tree. For GEOS:
  `GEOS_REPO=<your fork> GEOS_COMMIT=<sha> BUILD_ROOT=<dir> adapters/geos_main/build.sh`,
  then `geotruth run --lib geos-main --prefix <dir>` and `geotruth score` as above
  ([adapters/README.md](adapters/README.md)).
- **See each failure.** `geotruth site` writes a page per failure cluster (library × family
  × signature) with the exact inputs, the exact answer next to yours, figures zoomed to the
  discrepancy with the exact coordinates, an independent re-check of the exact answer, and
  the commands that reproduce both answers.
- **Shrink a case.** `geotruth minimize CASE --lib <target> --field <field>` delta-debugs a
  failing case (parts, holes, vertices, decimal digits), re-checking validity and the exact
  answer after every step.
- **Take the cases home.** `geotruth export` writes cases with their exact answers as
  JTS/GEOS XML, Boost.Geometry tests, Clipper2 `Polygons.txt`, georust `#[test]`s or pytest.
  The XML runs in your own test runner; `--run` runs it for you:

  ```console
  $ geotruth export -f jts-xml "corpus/cases/core/near-collinear.jsonl#near-collinear-1-000094-extension.moderate" \
      -o nc94.xml --run geos,jts
  wrote nc94.xml
  nc94.xml: geos xmltester: 16 tests, 13 passed, 3 failed, 0 exceptions
      nc94.xml (18): case 1, test 1: relate(A, B, 212101212) failed.
      nc94.xml (21): case 1, test 4: touches(A, B) failed.
      nc94.xml (23): case 1, test 6: overlaps(A, B) failed.
  nc94.xml: jts (ng): 16 tests, 13 passed, 3 failed, 0 exceptions
      Test Failed (A relate B 212101212 -> true)
      Test Failed (A touches B -> false)
      Test Failed (A overlaps B -> true)
  ```

  (GEOS `xmltester` built from main ae9cdd9, the JTS TestRunner from master 3ea61f8, both
  with RelateNG.) The corpus and the expected answers are CC0, so they can go into any test
  suite under any licence.
- **Tell us we are wrong.** If a manifest misstates what your library promises, an adapter
  calls it in a way you do not recommend, or a behaviour is intended, please open an issue:
  the entry becomes `by-design`, or the adapter is fixed. See the
  [FAQ](docs/FAQ.md#i-maintain-a-library-and-i-think-a-result-is-wrong-what-now).

## Status and roadmap

geotruth 0.1.0 is the first release: engine 0.1.0, corpus 2.0.0, expected answers
version 2 ([release notes](RELEASE_NOTES_v0.1.0.md), [changelog](CHANGELOG.md)). Next:

- file the drafted upstream reports, one at a time, and record each in the registry;
- show each maintainer their row before the site is published, then publish it and enable
  the nightly workflow that rebuilds every library from upstream and rescores it;
- publish the `full` tier (cases and answers) as a release asset, and the package on PyPI;
- triage the unreviewed clusters and leads, and give the sub-clusters found during triage
  their own findings directories;
- `geotruth repro CASE --lib LIB`, which writes a standalone program against the library's
  public API (today each finding directory has one written by hand);
- more adapters (NetTopologySuite, database engines through SQL).

Out of scope for now: buffer, offset and simplification; geodesic, curved and 3-D
geometry. The engine is written in Python for auditability: fast enough for the corpus
(about 20 ms per case), not a production geometry library.

## Documentation

| | |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | installing, and exact answers from the command line |
| [docs/FAQ.md](docs/FAQ.md) | why exact arithmetic, limitations, relation to prior work |
| [docs/SCORING.md](docs/SCORING.md) | verdicts, overlay tiers, displacement budgets, fairness rules |
| [docs/CORPUS.md](docs/CORPUS.md) | families, tags, tiers, expected answers, versioning |
| [docs/ADAPTERS.md](docs/ADAPTERS.md) | the adapter contract and manifest, adding a library |
| [docs/EXPORTS.md](docs/EXPORTS.md) | exports to each library's test format |
| [docs/DESIGN.md](docs/DESIGN.md) | the full design |
| [data/README.md](data/README.md) | the score data and how to reproduce it |
| [site/README.md](site/README.md) | the results site |

## Citing

If you use geotruth, its corpus or its expected answers, please cite it
([CITATION.cff](CITATION.cff)) and state the versions you used: the geotruth commit or
release, the corpus version and the engine version.

```bibtex
@software{geotruth,
  author  = {Mukhamedov, Abdulfayyod},
  title   = {geotruth: exact ground truth for computational geometry},
  url     = {https://github.com/abafaboy/geotruth},
  version = {0.1.0},
  year    = {2026}
}
```

## Licence

The code is MIT ([LICENSE](LICENSE)). The corpus and the expected answers are dedicated to
the public domain under CC0 1.0 ([corpus/LICENSE](corpus/LICENSE)), so that GEOS (LGPL), JTS
(EPL/EDL), Boost (BSL), Clipper2 (BSL) and anyone else can copy cases into their own tests.

## Credits

By Abdulfayyod Mukhamedov, built with [Claude Code](https://claude.com/claude-code).
