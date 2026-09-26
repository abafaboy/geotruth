# Triage: JTS master union regression at extreme coordinates (and a ClassCastException found with it)

Lead `jts-master-union-extreme-regression`. Triage date 2026-09-26. Nothing has been posted
upstream.

The lead named two symptoms. They turned out to be two separate defects, and neither is the
known `geos-tiny-coordinates-underflow` mechanism, although both corpus cases need extreme
coordinates to trigger:

| # | defect | JTS builds | normal-range trigger? | verdict | report draft |
|---|---|---|---|---|---|
| 1 | `KdTree` compares squared distances, and the squared snap tolerance overflows to `Infinity`. The snapping fallback of `OverlayNGRobust` then merges every vertex into one, and union, intersection, difference and symdifference return `POLYGON EMPTY` with no exception. | master 3ea61f8 only (regression from #1114, commit 4668803) | no: needs \|ordinates\| above about 1.3e162 for OverlayNGRobust, or a `KdTree` tolerance above 1.34e154 | confirmed regression, low priority | [FINAL.md](FINAL.md) |
| 2 | `OverlayMixedPoints.extractPolygons` casts every element of the noded polygonal operand to `Polygon`. When a polygon collapses to a line, `union` and `symDifference` with a point throw `ClassCastException`. | master 3ea61f8 and 1.20.0 (1.18.0 throws `IllegalArgumentException` instead) | **yes**: any valid polygon that collapses under a fixed `PrecisionModel` | confirmed bug, normal priority | [mixed-points/FINAL.md](mixed-points/FINAL.md) |

## Versions and upstream heads

On 2026-09-26, `git ls-remote` showed that no upstream head had moved:

- locationtech/jts `master` = `3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd`, the build in
  `$GEOTRUTH_BUILD_DIR/jts-main`.
- Tag `1.20.0` peels to `6e95fe82feb986a7aa657f4ffa406d8c290af509`, the build in `jts-release`.
- libgeos/geos `main` = `ae9cdd98be4e0bae552b918d4d14c94a9ce99c58`.

Other builds used:

- JTS 1.18.0 (the Maven Central jar), used only for the history of defect 2;
- GEOS 3.15.0 (`geos-release`);
- Shapely 2.0.7 (GEOS 3.11.4), 2.1.2 (GEOS 3.13.1) and 2.2.0rc1 (GEOS 3.14.1) wheels.

## 1. The master regression: `POLYGON EMPTY` from OverlayNGRobust

### What the harness saw

Corpus case `line-polygon-1-000090-along-edge-full.ba.int.extreme` (core and full tiers;
`cases.jsonl`, first line). It is a triangle and a two-part MultiLineString, with ordinates
around 3.8e220:

- master: `OverlayNGRobust.overlay` union, difference and symdifference all return
  `POLYGON EMPTY`, with no error (`adapter_results_jts-master-3ea61f8.jsonl`).
- 1.20.0: union and symdifference give the correct `GEOMETRYCOLLECTION (POLYGON, LINESTRING)`.
  Difference is the triangle, rounded by the snap-rounding fallback.

Both builds return the correct intersection, relate (`FF2101102`) and validity.

### Magnitude matters

Multiplying by an exact power of two cannot change the answer. The case divided by 2^732 has
ordinates around 1.6 and is correct on every build. `ScanScales.java` computes union(A·2^k,
B·2^k) with OverlayNGRobust for every k and compares it with the unit-scale result times 2^k.
The output is in `output_jts-*.txt`:

| build | correct | correct up to rounding (a fallback ran) | `POLYGON EMPTY` |
|---|---|---|---|
| master 3ea61f8 | k ≤ 532 | 533..537 | **k ≥ 538** (max \|ordinate\| ≥ 1.5e162) |
| 1.20.0 | all k | none | none |
| master + prototype fix | k ≤ 532 | k ≥ 533 | none |

(k = 732 is the corpus case.) The small triangle case below behaves the same way: empty from
k = 538.

At normal magnitudes nothing fails, so by the lead's rule this is an extreme-range defect.
It belongs with the coordinate-range limits of `geos-tiny-coordinates-underflow` (JTS documents
no supported coordinate range either). It is also a plain regression in unreleased code, with a
one-line cause, so it is written up separately and not folded into that report.

### Minimal hand-checkable input

A triangle overlaid with itself (`cases.jsonl`, `min-self-overlay-1e170`; `Repro.java`, part 1):

    A = POLYGON ((0 0, 2e170 1e170, 1e170 2e170, 0 0))
    OverlayNGRobust.overlay(A, A, UNION)        = POLYGON EMPTY     (master)    expected A (1.20.0: A)
    OverlayNGRobust.overlay(A, A, INTERSECTION) = POLYGON EMPTY     (master)    expected A

The triangle with a disjoint line (`min-disjoint-line-1e170`) has no segment intersections, so
the known `CGAlgorithmsDD.intersection` overflow cannot be involved:

    B = LINESTRING (3e170 0, 4e170 0)
    union        = POLYGON EMPTY    expected GEOMETRYCOLLECTION (A, B)
    difference   = POLYGON EMPTY    expected A
    symdifference= POLYGON EMPTY    expected GEOMETRYCOLLECTION (A, B)

With `-Djts.overlay=ng`, `Geometry.union` goes through OverlayNGRobust, and `A.union(A)` is
`POLYGON EMPTY` on master as well. The default overlay (`SnapIfNeededOverlayOp`) is correct on
both builds for these inputs.

The cause is also visible directly in the `KdTree` API (`Repro.java`, part 5):

    new KdTree(1e155): insert (0 0), then (1e300 0)  -> one node (both "within 1e155")
    new KdTree(0.0):   insert (0 0), then (1e-170 0) -> one node (distinct points merged at tolerance 0)

1.20.0 keeps two nodes in both cases.

### Exact answer and validity

`exact_check.py` computes the expected answers without JTS; its output is in
`output_exact_check.txt`:

- **Validity.** Every operand is valid under exact OGC rules (`geotruth.validity`) and under
  `tests/reference/oracle.py`.
- **Exact overlays.** `geotruth.overlay` computes all four overlays, and each result passes the
  independent certificate. The relate matrix agrees between the two relate routes.
- **Independent areas for A with A.** `oracle.py` (slab areas) and `indep.py` (Green's theorem on
  boundary pieces) agree: union = intersection = A, whose area is about 1.5e340, and difference
  = symdifference = empty. The 1e170 triangle is exactly 1e170 times the unit triangle,
  because the float 2e170 equals 2 × the float 1e170.
- **The corpus case.** It is exactly 2^732 times the unit-scale copy used in the scans. Its
  exact union is the triangle plus the far segment of B. The near segment of B is an edge of the
  triangle.

### Root cause (JTS master 3ea61f8)

1. **Precondition, present in both builds.** `Geometry.getArea()` overflows once coordinate
   differences exceed about 1e154. For these rings the shoelace terms are +inf and −inf, so the
   area is `NaN`. OverlayNG's result check `OverlayUtil.isResultAreaConsistent`
   (`OverlayUtil.java:390-419`, called at `OverlayNG.java:521-523`) is false for any `NaN`
   area. So the floating overlay (`OverlayNGRobust.java:137`) and every `SnappingNoder` overlay
   throw "Result area inconsistent with overlay operation", and OverlayNGRobust falls through
   to its fallbacks.
2. **The regression.** The fallback `overlaySnapTries` (`OverlayNGRobust.java:180-201`) uses a
   snap tolerance of magnitude / 1e12 (`:283`, `:302`), multiplied by 10 on each of five tries
   (`:197`).
   - `overlaySnapBoth` first self-snaps each operand (`snapSelf`, `:259`) with a
     `SnappingNoder`, whose `SnappingPointIndex` is a `new KdTree(snapTolerance)`
     (`SnappingPointIndex.java:42`).
   - Since commit 4668803 (#1114, "Add KdTree nearestNeighbor() and nearestNeighbors()"),
     `KdTree` stores `toleranceSq = tolerance*tolerance` (`KdTree.java:97`, `:117`).
     `insertExact` snaps a point to an existing node when `p.distanceSq(node) <= toleranceSq`
     (`:424-425`).
   - For a tolerance above sqrt(Double.MAX_VALUE) ≈ 1.34e154, `toleranceSq` is `+Infinity`.
     Every distance, even an overflowed `Infinity`, then passes the test, so every vertex snaps
     to the root node.
   - Each operand collapses to `EMPTY`. The overlay of two empty operands is `POLYGON EMPTY`,
     which passes the area check trivially. `overlaySnapBoth` returns it as the result.

   The 1.20.0 code compared `p.distance(node) <= tolerance` using `Math.hypot`, which neither
   overflows nor underflows.
3. **Underflow, the same comparison at the tiny end.** With tolerance 0 (the `HotPixelIndex`
   `KdTree`), or any tolerance whose square underflows (the OverlayNGRobust snap tolerance for
   such inputs), two distinct points closer than about 1.5e-162 have `distanceSq == 0` and are
   merged. In `mixed-points/output_scan_scales.txt`
   this is why master returns `POLYGON EMPTY` for k in [-1068, -536], where 1.20.0 throws
   `TopologyException` or returns a wrong point.
4. **Why the threshold is 1.3e162 for these inputs and not 1.3e166.** Commit 52c5d988 (#1187,
   "OverlayEdge: Don't skip first point when adding coordinates") changed the start vertex of
   output rings.
   - In 1.20.0, `snapSelf(A)` came back rotated, and the rotated ring's area is `+Infinity`, not
     `NaN`. The area check passes on infinities, so the first snap try succeeded.
   - On master the ring keeps its start vertex and its area stays `NaN`. Tries 0-3 fail, and
     try 4 (tolerance magnitude × 1e-8) is the first whose square overflows.
   - The second bisect (below) therefore lands on #1187 for the 1.5e162 copy. #1187 itself is
     correct. It only removes the lucky ring rotation that hid the overflow.

   `output_fallback_trace.txt` replays the fallback chain step by step on both builds
   (`DiagFallback.java`, a diagnostic in the overlayng package).

### Bisect

In `bisect/`, `git bisect` between 1.20.0 (good) and master (bad) gave:

- the corpus case as is (3.8e220): first bad commit **4668803** (#1114);
- the case divided by 2^194 (1.5e162): first bad commit 52c5d988 (#1187), which descends from
  4668803, for the reason in point 4.

### Prototype fix

`prototype_fix.diff` (against master 3ea61f8) replaces the squared comparison in
`KdTree.insertExact`. The new test first rejects a point when |dx| or |dy| exceeds the
tolerance (cheap, and it keeps tolerance 0 exact), then compares `Math.hypot(dx, dy) <= tolerance`.
The field `toleranceSq` is removed. The diff also adds three tests:
`KdTreeTest.testLargeToleranceDoesNotSnapDistantPoints`,
`testZeroToleranceKeepsTinyDistinctPoints` and
`OverlayNGRobustTest.testLargeCoordinatesSelfUnion`.

- **The core test suite.** The core JUnit suite (2348 tests, run with JUnitCore) passes with
  the patch. The only entries JUnitCore reports are 36 non-test warnings, the same as on
  unpatched master. The three new tests fail on unpatched master (`output_prototype_tests.txt`).
- **The repro and the scans.** Nothing is wrong any more (`output_jts-master-3ea61f8+prototype_fix.txt`).
  Where master was empty, the scans give the snap-rounded union ("correct up to rounding").
- **The point cluster.** With the patch, master's scan of the corpus point case
  (`mixed-points/output_scan_scales.txt`) becomes identical to 1.20.0's.

`nearestNeighbor`/`nearestNeighbors` (#1114) also rank by `distanceSq`. When every distance
overflows, `nearestNeighbor` returns `null` on a non-empty tree. This is a minor issue in new
API and is mentioned in FINAL.md only.

### Related, not reported

- **#1112 (`MathUtil.hypot`).** Since #1112, `Coordinate.distance`, `Length` and
  `equalsExact(g, tol)` compute `sqrt(x*x + y*y)`, which overflows for distances above 1.34e154
  and underflows below about 1.5e-162. For example, master's `getLength()` of the corpus case's
  intersection line is `Infinity`, where 1.20.0 gives 5.1e214.
  - #1112 made this trade-off on purpose (speed over range; PR #1112 and issue #1110). It is
    therefore by design and not reported, but FINAL.md mentions it as context.
  - It is not the cause here: with `Math.hypot` restored only in `KdTree`, the failure is gone.
- **NetTopologySuite.** NTS `develop` (5cff3d0) `KdTree` still compares `Distance(...) <= tolerance`,
  so it is not affected unless #1114 is ported.

## 2. ClassCastException in OverlayMixedPoints

The report draft is [mixed-points/FINAL.md](mixed-points/FINAL.md); the evidence is in
`mixed-points/`.

### What the harness saw

Corpus case `point-geometry-1-000016-in-hole.ba.int.extreme` is a MultiPolygon (a quadrilateral
with a hole, plus a small triangle) and a point in the hole, with ordinates around 1e-161. On
master and 1.20.0, `OverlayNGRobust.overlay` union and symdifference throw:

    ClassCastException: class org.locationtech.jts.geom.LineString cannot be cast to class org.locationtech.jts.geom.Polygon

The stack is `OverlayMixedPoints.extractPolygons` (`OverlayMixedPoints.java:237`) ←
`computeUnion` ← `OverlayNG.getResult` ← `OverlayNGRobust.overlaySnapTol`. At the same scale,
JTS also calls A invalid, gives relate `FF20F1FF2` (exact `FF2FF10F2`) and puts the point into
the intersection. All of that is the orientation underflow of `geos-tiny-coordinates-underflow`:
the small triangle's legs are 2.2e-164, so its orientation determinant (about 4.7e-328)
underflows to 0 and the triangle collapses.

### Magnitude

The case at unit scale is correct on all builds for 2^k with k in [-527, 515]. It throws
`ClassCastException` for k in [-534, -528] (the corpus case is k = -534) and for k ≥ 517, where
the known range limits collapse the small triangle.

The *defect*, however, is not range-limited. The floating range is only one way to collapse a
polygon of the input. A fixed `PrecisionModel` does the same at ordinary coordinates, through
the documented public API.

### Minimal hand-checkable input (normal range)

    A = MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((3 0, 5 0, 5 0.4, 3 0)))   (valid)
    P = POINT (7 7)
    OverlayNG.overlay(A, P, OverlayNG.UNION, new PrecisionModel(1))   -> ClassCastException
    OverlayNG.overlay(A, P, OverlayNG.SYMDIFFERENCE, new PrecisionModel(1)) -> ClassCastException
    (both argument orders; strict mode too)

On the integer grid, (5 0.4) snaps to (5 0), so the triangle collapses to the segment (3 0)-(5 0).

- The same A with a line or a polygon operand instead of P gives, in the default non-strict mode,
  `GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0), ...)`.
  In strict mode the collapse line is dropped.
- `DIFFERENCE(A, P)` already returns `GEOMETRYCOLLECTION (POLYGON, LINESTRING (3 0, 5 0))`.

The expected union is therefore `GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)),
LINESTRING (3 0, 5 0), POINT (7 7))`. This is the answer GEOS 3.11.4, 3.13.1 and 3.14.1 return
(Shapely `grid_size=1`), and the exact non-strict union of the snapped operands
(`exact_check.py`). A is valid under exact OGC rules, P lies outside A (the engine gives relate
`FF2FF10F2`, and `indep.classify_point` gives `out`), and snapping the triangle gives twice-area 0.

### Root cause

`OverlayMixedPoints.prepareNonPoint` (`OverlayMixedPoints.java:132-141`) nodes the polygonal
operand with the non-strict `OverlayNG.union(geom, pm)` (`:139`). With a fixed precision model
this can return a GeometryCollection of polygons and collapse lines, whose dimension is still 2.
`computeUnion` (`:147-159`) then calls `extractPolygons` because the dimension is 2, and
`extractPolygons` casts every element: `(Polygon) geom.getGeometryN(i)` (`:237`). The same
unchecked cast is in `extractLines` (`:248`). The code dates from the original OverlayNG commit
(b33e2c7d, #599).

In JTS 1.18.0 the same input throws `IllegalArgumentException: Argument must be Polygonal or
LinearRing` a step earlier, from `IndexedPointInAreaLocator`.

`OverlayMixedPoints` also ignores strict mode. Strict `DIFFERENCE(A, P)` returns the collapse
line, although strict mode promises homogeneous results without collapse lines. This is a
minor, separate inconsistency, noted in the report.

### Prototype fix

`mixed-points/prototype_fix.diff` changes three things:

- `extractPolygons` and `extractLines` keep only elements of their type, instead of casting;
- `computeUnion` also collects the lines of a dimension-2 operand;
- it adds `OverlayNGMixedPointsTest.testPolygonCollapseUnion`.

The union is then the documented non-strict result.

- **Core tests.** The new test fails on master and passes with the patch; the other 2345 tests
  give the same results either way (`mixed-points/output_prototype_tests.txt`).
- **Corpus case.** At the tiny scale the case no longer throws, but its answer is still wrong,
  because of the known underflow.

### Other implementations

- **GEOS.** GEOS ports the same code with a `static_cast`.
  - 3.11.4 through 3.14.1 use the non-strict union. They reach the cast with a `LineString`,
    which is undefined behaviour, and return the non-strict answer above (the cast is
    `OverlayMixedPoints.cpp:291` in 3.13.1).
  - 3.15.0 and main node the operand in strict mode (`OverlayNG::geomunion(geom, pm, noder)`
    sets strict mode, `OverlayNG.cpp:141-147`). The collapse line never reaches the cast
    (`OverlayMixedPoints.cpp:299`), and the union is `GEOMETRYCOLLECTION (POLYGON, POINT)`.
  - GEOS 3.15+ therefore drops the collapse line for a point operand but keeps it for a line
    operand (`output_geos_and_shapely.txt`). That is a GEOS-side inconsistency, not a crash, and
    it is not reported here.
- **NetTopologySuite.** NTS `develop` has the same `(Polygon)` cast in `ExtractPolygons`. It was
  not run.

## Upstream search (2026-09-26)

Searches were run on GitHub issues and PRs, open and closed, in locationtech/jts, libgeos/geos,
shapely/shapely and NetTopologySuite/NetTopologySuite. The queries were:

- "ClassCastException LineString cannot be cast to Polygon OverlayMixedPoints";
- "OverlayNG union point polygon precision model exception collapse mixed dimension";
- "Argument must be Polygonal or LinearRing overlay point union precision";
- "snap rounding union of multipolygon and point throws exception thin polygon collapses";
- "KdTree tolerance squared overflow snapping all points merged";
- "overlay returns empty result very large coordinates";
- "Result area inconsistent with overlay operation large coordinates NaN area";
- "hypot overflow distance infinity large coordinates regression";
- PRs mentioning `KdTree` and `OverlayMixedPoints`.

No duplicate was found. The issues and PRs read, none of them the same problem:

- **jts#1114** (the PR that introduced `toleranceSq`): no discussion of range.
- **jts#1112 / #1110**: the `MathUtil.hypot` speed trade-off.
- **jts#1187**: the ring start change.
- **jts#951**: the area-check heuristic with a snapping noder, fixed by #1005, at small
  magnitudes.
- **jts#1000**: the OverlayNG failures summary; nothing on mixed points, collapse, large
  coordinates or `KdTree`.
- **jts#1133**: `SnapRoundingNoder` output is lines, a question.
- **jts#1222**: the difference moves points.
- **jts#745**: large or small coordinates in RelateOp, a different mechanism.
- **geos#931**: UB in `OverlayMixedPoints.cpp`, which is a null `PrecisionModel` reference,
  not this cast.
- **NTS#863 / #868**: ports of #1187 and #1111.

## Files

- **Cases and results.** `cases.jsonl` holds the corpus case and the minimal cases of defect 1;
  `mixed-points/cases.jsonl` holds those of defect 2. The harness output for both corpus cases
  is in `adapter_results_jts-master-3ea61f8.jsonl` and `adapter_results_jts-1.20.0.jsonl`.
- **Defect 1 programs.** `Repro.java` and `ScanScales.java` use the public API only, and
  `run.sh` builds and runs them against given jars. `DiagFallback.java` is the diagnostic
  replay of the fallback chain.
- **Defect 1 outputs.** `output_jts-master-3ea61f8.txt`, `output_jts-1.20.0.txt`,
  `output_jts-master-3ea61f8+prototype_fix.txt` and `output_fallback_trace.txt`.
- **Defect 1 fix and bisect.** `prototype_fix.diff`, `output_prototype_tests.txt`, and `bisect/`
  (the logs, the step script and the check programs).
- **Exact answers.** `exact_check.py` and `output_exact_check.txt`, for both defects.
- **Defect 2 (`mixed-points/`).** `Repro.java`, `ScanScales.java`, `repro_geos.c`,
  `repro_shapely.py`, `run.sh`, `output_*.txt`, `prototype_fix.diff`,
  `output_prototype_tests.txt` and `FINAL.md`.
- **Reports.** `FINAL.md` (defect 1, for locationtech/jts) and `finding.toml` (the registry
  snippet for both defects).
