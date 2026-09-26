# Triage: GEOS overlay with GeometryCollection operands (HeuristicOverlay / StructuredCollection)

Slug `geos-overlay-geometrycollection`. Lead: "GEOS OverlayNG with GeometryCollection operands"
(tests/crosscheck/test_overlay_crosscheck.py `GEOS_GC_OVERLAY`, `GEOS_GC_EMPTY_ASSERTION`) and
corpus/curated/leads.toml `geos-overlay-empty-vs-gc-assertion`, which this finding supersedes.

**Verdict: confirmed, three bugs within the documented contract (D1, D2, D3), plus one
secondary robustness weakness (D4) and one minor inconsistency that fails with a clear error
(D5).** None of it is OverlayNG proper: all of it is in the GeometryCollection code of
`HeuristicOverlay.cpp` (class `StructuredCollection`), which is GEOS-only ("Last port:
ORIGINAL WORK"). JTS is not affected (it rejects GC operands, as it documents). Nothing has been
posted upstream. FINAL.md is the report drafted for libgeos/geos.

| id | operation | what goes wrong | smallest case (GEOS main and 3.15.0) | exact | contract |
|---|---|---|---|---|---|
| D1 | symdifference | B's points and lines are dropped; A's points and lines are kept even where they lie in B | `GC(POLYGON((0 0,4 0,0 4,0 0)))` xor `POINT(3 3)` = `POLYGON(...)` | `GC(POLYGON(...), POINT(3 3))` | in (even OverlayNG's own) |
| D2 | difference | A's points lying on B's lines are not removed | `POINT(1 0)` minus `GC(LINESTRING(0 0,2 0), POINT(3 3))` = `POINT(1 0)` | `POINT EMPTY` | in (public API, mixed GC) |
| D3 | intersection, difference | `AssertionFailedException: Should never reach here: Unable to determine overlay result geometry dimension` when one operand has no non-empty element | `GC(POLYGON EMPTY)` and `POINT(1 1)` | `POINT EMPTY` | in (even OverlayNG's own) |
| D4 | all (secondary) | the GC's own lines are noded on their own before the overlay; a rounded node moves them off exact coincidences | `POINT(3 2)` and `GC(MULTILINESTRING((0 2,2 4),(0 4,6 0)), POINT(9 9))` = `POINT EMPTY` | `POINT(3 2)` | robustness, no exactness promise in floating point |
| D5 | all (minor) | a nested `GEOMETRYCOLLECTION EMPTY` makes a lineal/puntal GC "mixed-dimension" | `LINESTRING(0 0,1 1)` and `GC(LINESTRING(0 1,1 0), GEOMETRYCOLLECTION EMPTY)` | `POINT(0.5 0.5)` | clear IllegalArgumentException; by the letter out of OverlayNG's contract |

## 1. Versions

Upstream heads checked with `git ls-remote` on 2026-09-26 07:28 UTC: they have not moved.

| build | commit | D1 | D2 | D3 | D4 | D5 |
|---|---|---|---|---|---|---|
| GEOS main | ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (head) | wrong | wrong | assertion | wrong | exception |
| GEOS 3.15.0 (latest release) | d0228513abb0c29c185443cf2bfb06c9281024b5 | wrong | wrong | assertion | wrong | exception |
| GEOS 3.14.1 | Shapely 2.2.0rc1 wheel | wrong | wrong | assertion | wrong | exception |
| GEOS 3.13.1 | Shapely 2.1.2 wheel | wrong | wrong | assertion | wrong | exception |
| GEOS 3.13.0 | d7957246c588aa9c690efe67924fd70e741a06ab (built from the tag) | mixed-GC cases wrong (1c, 1d); simple-GC cases right (1a, 1b) | wrong | no assertion (3d gives `GEOMETRYCOLLECTION EMPTY`, same point set) | wrong | exception |
| GEOS 3.11.4 | Shapely 2.0.7 wheel | right | right | right | right | right |
| GEOS main + prototype_fix.diff | | right | right | right | wrong | exception |
| JTS master / 1.20.0 | 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd / 6e95fe82 | `Geometry.symDifference/difference` throw IllegalArgumentException ("Operation does not support GeometryCollection arguments", as documented); `OverlayNGRobust` answers the simple-GC cases correctly and rejects mixed GCs ("Overlay input is mixed-dimension") | | | | |

The 3.15 branch head (86a4af48) has no change to `HeuristicOverlay.cpp` after 3.15.0; branches
3.12 and 3.13 carry the same code (backports of #1229: 364ece73 in 3.12.3, b3844c03 in 3.13.1).

History (full clone, `git log --follow src/geom/HeuristicOverlay.cpp`):
- GEOS 3.11 and earlier: GC operands were handled by the old overlay engine; every case here is right on 3.11.4.
- c37391cf "Overlay with mixed dimension (#923)", GEOS 3.12.0 (NEWS: "Support mixed GeometryCollection in overlay ops (GH-797)"): adds `StructuredCollection`, with D1, D2 and D4 from the start.
- b6c1b594 "Fix overlay heuristic for GeometryCollections with empty elements (#1229)", 3.14.0, backported to 3.12.3 and 3.13.1: routes *every* GC with a polygonal element to `StructuredCollection` (so simple, homogeneous GCs such as `GC(POLYGON)` or `GC(POLYGON EMPTY)` now hit D1), and adds the typed empty result whose dimension is initialised to `Dimension::DONTCARE` (D3). It also fixed the TopologyExceptions for GCs with overlapping polygons (libgeos/geos#948): the scan shows 1356 TopologyExceptions on 3.13.0 and none on main.

## 2. The documented contract

What the public overlay functions promise, from the GEOS main sources:

- `capi/geos_c.h.in:4258`, `:4290`, `:4328` (GEOSIntersection, GEOSDifference,
  GEOSSymDifference): point-set definitions ("the set of points that fall in A but **not**
  within B and the set of points that fall in B but **not** in A"), no restriction on
  geometry types, `\see geos::operation::overlayng::OverlayNG`.
- `include/geos/operation/overlayng/OverlayNG.h:59-67`: OverlayNG's input requirements:
  "Input collections must be homogeneous (all elements must have the same dimension). Inputs
  may be simple GeometryCollections. A GeometryCollection is simple if it can be flattened into
  a valid Multi-geometry; i.e. it is homogeneous and does not contain any overlapping Polygons.
  In general, inputs must be valid geometries."
- `src/geom/HeuristicOverlay.cpp:24-26` (the layer between the public functions and OverlayNG):
  "It also implements overlay for GeometryCollections, which is not (yet) provided by
  OverlayNG." NEWS.md:229 (3.12.0): "Support mixed GeometryCollection in overlay ops (GH-797)";
  NEWS.md:88: "Fix overlay heuristic for GeometryCollections with empty elements (GH-1229)".
  `HeuristicOverlay.cpp:121`: "GCs with polygonals must be unioned" (so GCs with overlapping
  polygons are deliberately accepted, cf. #948).
- `include/geos/geom/Geometry.h:722,733,772,783` (C++ `Geometry::intersection`, `Union`,
  `difference`, `symDifference`): "@throws util::IllegalArgumentException if either input is a
  non-empty GeometryCollection". This is the JTS javadoc; it has been stale since 3.12 (the
  functions accept such inputs and return a result).
- `tests/unit/geom/HeuristicOverlayTest.cpp:63-71`: for mixed-dimension GCs "the result of the
  overlay might be a matter of interpretation ... The implementation just tries to generate a
  visually defensible, simplified answer." The tests that follow (tests 4-6) all expect the exact
  point set, simplified in representation only (points on lines and lines inside polygons
  dropped). Dropping parts of B, or keeping parts that lie in both operands, is not a matter of
  representation.

Classification of the cases (the `in_overlayng_input_contract` field of cases.jsonl):

1. **Inside even OverlayNG's own requirements** (every GC is simple: homogeneous, flattens to a
   valid Multi-geometry): cases 1a, 1b, 3a, 3b, 3c. GEOS's own OverlayNG gives the right
   answer (`GEOS*Prec_r(..., 0)`, which calls `OverlayNGRobust` directly, and JTS
   `OverlayNGRobust.overlay`); the public functions return a wrong geometry or assert. These
   are bugs by any reading; they are also regressions (right on 3.13.0 and 3.11.4).
2. **Mixed-dimension GCs** (1c, 1d, 2a, 3d, 4a, 4b): outside OverlayNG's class contract, but the
   public functions explicitly support them since 3.12 (NEWS, HeuristicOverlay.cpp header, the
   HeuristicOverlay unit tests) and the C API documents no restriction. The inputs are valid
   (GEOSisValid = 1, geotruth validity true). A wrong geometry is a bug here. Even under the
   stale Geometry.h reading, the documented behaviour would be an IllegalArgumentException, not
   a wrong answer, so at the very least the wrong answers must become errors.
3. **GCs with overlapping polygons** (the lead's first example, `GC(two overlapping squares)`
   xor `POINT(5 5)`): not "simple" in OverlayNG's sense, but deliberately accepted by the public
   layer (it unions the polygons first). The overlap plays no part in the defect: case 1a
   reproduces it with a single polygon.
4. **D4** is a floating-point effect (see section 3.4); GEOS promises no exact result in
   floating precision, so it is reported as a robustness weakness of the GC path, not as a
   contract violation.
5. **D5**: a `GEOMETRYCOLLECTION EMPTY` element has dimension -1, so by the letter of
   "all elements must have the same dimension" the GC is not homogeneous; GEOS answers with a
   clear IllegalArgumentException. At most a request (handle it like the `POINT EMPTY` element,
   which works).

## 3. The defects

Exact answers: geotruth `overlay` (non-strict OverlayNG semantics, certified by the
independent certificate of `overlay_certify`), the independent certificate applied to GEOS's
output (it names the misplaced witness point), and a hand check with
`tests/reference/indep.py` (Fraction arithmetic). All in `output_exact_check.txt`
(`exact_check.py`). GEOS's own predicates are printed by `repro.c` where they settle the
question (`GEOSIntersects(POINT(1 0), LINESTRING(0 0, 2 0)) = 1`,
`GEOSEquals(A, B) = 1` for 1d).

### 3.1 D1: symdifference is one-sided for points and lines

`StructuredCollection::doSymDifference` (`src/geom/HeuristicOverlay.cpp:505-528`):

```cpp
    std::unique_ptr<Geometry> poly_symdiff_poly = OverlayNGRobust::Overlay(
        poly_union.get(), a.getPolyUnion(), OverlayNG::SYMDIFFERENCE);
    std::unique_ptr<Geometry> line_symdiff_line = OverlayNGRobust::Overlay(
        line_union.get(), a.getLineUnion(), OverlayNG::DIFFERENCE);   // A.lines - B.lines only
    std::unique_ptr<Geometry> pt_symdiff_pt = OverlayNGRobust::Overlay(
        pt_union.get(), a.getPointUnion(), OverlayNG::DIFFERENCE);    // A.points - B.points only
```

Only the polygons get a symmetric difference. For the lower dimensions the code computes
`A - B` of the same dimension only, so (i) B's points and lines disappear from the result
unless the final clean-up happens to cover them, and (ii) A's points and lines are subtracted
only from B's parts of the *same* dimension, so a point of A on a line of B, or a line of A
inside both polygons, survives. `doUnaryUnion` (line 315) then only removes lower-dimensional
parts covered by the *result*, which cannot repair either. The result is not even symmetric:
`symDifference(A, B)` and `symDifference(B, A)` differ (1a vs 1a', 1c vs 1c').

| case | A | B | GEOS main / 3.15.0 | exact |
|---|---|---|---|---|
| 1a | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))` | `POINT (3 3)` | `POLYGON ((0 0, 0 4, 4 0, 0 0))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)), POINT (3 3))` |
| 1a' | B and A swapped | | `GEOMETRYCOLLECTION (POINT (3 3), POLYGON (...))` (right) | same |
| 1a" | `POLYGON ((0 0, 4 0, 0 4, 0 0))` (no GC) | `POINT (3 3)` | right | same |
| 1b | `GEOMETRYCOLLECTION (POLYGON EMPTY)` | `POINT (1 1)` | `POINT EMPTY` | `POINT (1 1)` |
| 1c | `POINT (1 0)` | `GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))` | `POINT (1 0)` | `GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))` |
| 1d | `GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 1, 2 1))` | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` | `LINESTRING (0 1, 2 1)` | `POLYGON EMPTY` |

Hand checks: (3 3) is outside the triangle x + y <= 4 (3 + 3 = 6); `GC(POLYGON EMPTY)` has no
points, so A xor B = B; (1 0) lies on (0 0)-(2 0), so A - B is empty and B - A is B minus one
point, whose closure is B; in 1d both operands are the same point set (the line runs from
boundary to boundary through the interior, GEOSEquals = 1), so the symmetric difference is
empty. In 1c GEOS returns exactly the part that must be removed and drops everything that
must remain.

Why the simple-GC cases 1a and 1b reach this code: `isHandledByOverlayNG`
(`HeuristicOverlay.cpp:118-126`) sends every GC whose `getDimension()` is 2 to
`StructuredCollection`, and `GeometryCollection::getDimension()` counts empty elements
(`GC(POLYGON EMPTY)` has dimension 2). `isCombinable` (line 74) does not short-circuit
because the envelopes intersect (1a) or one operand has no non-empty element (1b).

### 3.2 D2: difference ignores B's lines when removing A's points

`StructuredCollection::doDifference` (`HeuristicOverlay.cpp:465-503`), lines 488-491:

```cpp
    std::unique_ptr<Geometry> pt_diff_poly_line = OverlayNGRobust::Overlay(
        pt_diff_poly.get(),
        line_diff_poly_line.get(),   // A's own remaining lines; should be a.getLineUnion()
        OverlayNG::DIFFERENCE);
```

A's points are subtracted from B's polygons and B's points, and from *A's own* lines (which
`doUnaryUnion` would do anyway), never from B's lines. By the variable names
(`pt_diff_poly_line`, parallel to `line_diff_poly_line = line_diff_poly - a.getLineUnion()`)
this is a slip.

| case | A | B | GEOS | exact |
|---|---|---|---|---|
| 2a | `POINT (1 0)` | `GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))` | `POINT (1 0)` | `POINT EMPTY` |
| 2a' | `POINT (1 0)` | `LINESTRING (0 0, 2 0)` (no GC) | `POINT EMPTY` (right) | same |
| lead | `POINT (2 3)` | `GEOMETRYCOLLECTION (LINESTRING (2 0, 2 4), POINT (9 9))` | `POINT (2 3)` | `POINT EMPTY` |
| lead | `MULTIPOINT ((4 1), (0 2))` | `GEOMETRYCOLLECTION (POINT (3 0), LINESTRING (4 2, 4 1))` | `MULTIPOINT ((0 2), (4 1))` | `POINT (0 2)` |

D1's case 1c contains D2 as well (its A - B part).

### 3.3 D3: AssertionFailedException for an operand without non-empty elements

`StructuredCollection`'s `dimension` starts at `Dimension::DONTCARE` (-3)
(`include/geos/geom/HeuristicOverlay.h:67`) and only `readCollection` raises it, for non-empty
atomic elements (`HeuristicOverlay.cpp:236` returns early for empty ones). For an operand with no
non-empty element (`POINT EMPTY`, `MULTIPOLYGON EMPTY`, `GC(POLYGON EMPTY)`) it stays -3.
`computeResult` (line 358-364) passes it to `OverlayUtil::resultDimension`
(`src/operation/overlayng/OverlayUtil.cpp:201-226`): intersection takes the minimum, difference
the first operand's dimension, so the result dimension is -3, and `doUnaryUnion` (lines 343-351)
calls `OverlayUtil::createEmptyResult(-3, ...)`, whose `default:` branch is
`util::Assert::shouldNeverReachHere("Unable to determine overlay result geometry dimension")`
(`OverlayUtil.cpp:193-194`). Union and symdifference take the maximum and do not assert (but
1b shows symdifference losing the point through D1).

| case | A | B | op | exact |
|---|---|---|---|---|
| 3a | `GEOMETRYCOLLECTION (POLYGON EMPTY)` | `POINT (1 1)` | intersection | `POINT EMPTY` |
| 3b | `POINT EMPTY` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))` | intersection | `POINT EMPTY` |
| 3c | `POINT EMPTY` | same GC | difference | `POINT EMPTY` |
| 3d | `GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))` | `MULTIPOLYGON EMPTY` | intersection | `LINESTRING EMPTY` |

All four assert on main and 3.15.0 (also 3.13.1, 3.14.1); `POLYGON EMPTY` instead of
`GC(POLYGON EMPTY)` in 3a gives `POINT EMPTY`, and `GEOSIntersectionPrec_r(A, B, 0)` gives the
expected typed empty in all four. This is the leads.toml lead
`geos-overlay-empty-vs-gc-assertion` (its six cases all assert for intersection, and for
difference with the empty operand first; with the empty operand first, symdifference also
drops the GC's `POINT (5 5)` through D1; output_lead_cases.txt). A downstream report exists:
duckdb/duckdb-spatial#803 (April 2026, `ST_Intersection(mixed GC, POLYGON EMPTY)`, closed, no
GEOS issue linked).

### 3.4 D4 (secondary): the GC's lines are noded on their own before the overlay

`unionByDimension` (`HeuristicOverlay.cpp:282-311`) unions each dimension of each operand
separately (`OverlayNGRobust::Union` of the MultiLineString), which nodes the operand's own
lines in floating point *before* the actual overlay. Where two lines of the same GC cross at a
point that is not a double, the node is rounded, and the split pieces no longer lie exactly on
the original segments. The pairwise overlays that follow then miss exact coincidences with the
other operand: a point on a line, a collinear overlap.

| case | A | B | GEOS | exact |
|---|---|---|---|---|
| 4a | `POINT (3 2)` | `GEOMETRYCOLLECTION (MULTILINESTRING ((0 2, 2 4), (0 4, 6 0)), POINT (9 9))` | `POINT EMPTY` | `POINT (3 2)` |
| 4b | `LINESTRING (3 2, 6 0)` | same | `POINT (6 0)` | `LINESTRING (3 2, 6 0)` |
| 4a'/4b' | same A | `MULTILINESTRING ((0 2, 2 4), (0 4, 6 0))` (no GC) | right | |

(3 2) and (6 0) lie exactly on (0 4)-(6 0) (4 - 2*3/3 = 2); the lines of B cross at
(6/5, 16/5). OverlayNG proper nodes all edges of both operands in one pass, so the collinear
overlap is found on the original segments; the GC path loses a whole segment of length about
3.6. GEOS's floating-point overlay makes no exactness promise, so this is filed as a robustness
weakness of the GC path, lower priority; it is also what remains of the scan after the
prototype fix (section 4). The remedy is structural (overlay the operands' elements without
pre-noding them, as OverlayNG itself does for non-simple MultiLineStrings), not a one-line fix.
Right on 3.11.4, wrong on 3.13.0 and later (3.12.x was not run; the code dates from #923, 3.12.0).

### 3.5 D5 (minor): nested `GEOMETRYCOLLECTION EMPTY`

`Geometry::isMixedDimension` (`src/geom/Geometry.cpp:177-193`) recurses into collections, so an
empty nested GC contributes nothing and `GC(LINESTRING, GEOMETRYCOLLECTION EMPTY)` counts as
homogeneous and goes to OverlayNG. OverlayNG's `EdgeNodingBuilder::addGeometryCollection`
(`src/operation/overlayng/EdgeNodingBuilder.cpp:238-247`) compares every direct element's
`getDimension()` with the collection's, and the empty GC's is -1: IllegalArgumentException
"Overlay input is mixed-dimension". With `POINT EMPTY` instead of `GEOMETRYCOLLECTION EMPTY`
(case 5a') `isMixedDimension` is true, the GC goes to `StructuredCollection`, and the answer is
right. A clear error, not a wrong answer: at most a request for consistency.

### 3.6 Not claimed

- Typed empties: `StructuredCollection` types an empty result by the operands' *non-empty*
  elements (a #1229 design decision), OverlayNG proper and the geotruth convention by
  `getDimension()`, which counts empty elements (`POLYGON EMPTY` intersected with
  `GC(LINESTRING, POLYGON EMPTY)`: GEOS with the prototype fix `LINESTRING EMPTY`, geotruth
  `POLYGON EMPTY`). Same point set; a convention (the crosscheck tool's `empty-type (gc)`
  class), not reported.
- Rounding: results whose exact coordinates are not doubles differ from GEOS by rounding
  (`rounding (...)` verdicts of the scan); expected in floating point.

## 4. Scan and prototype fix

`scan.py` + `scan_overlay_batch.c`: 1968 GC-involving, GEOS-valid pairs from the geotruth
adversarial and lattice generators (418 with only simple GCs), all four operations through the
public C API, verdicts by the independent certificate (`tools/crosscheck_overlay.py
geos_verdict`). Full table in `output_scan.txt`. Results that are wrong although the exact
result has only double coordinates, main (3.15.0 identical):

- symdifference: 323 drop parts (31 of them with only simple GCs), 17 add parts, 3 wrong parts;
- difference: 60 add parts (D2 and D4), 18 AssertionFailed;
- intersection: 36 AssertionFailed, 6 drop parts (D4);
- union: 2 wrong parts (D4);
- 8 IllegalArgumentException (D5; every one has a nested `GEOMETRYCOLLECTION EMPTY`).

`prototype_fix.diff` (against ae9cdd98; also adds HeuristicOverlay unit tests 13-17):

1. `doDifference`: subtract `a.getLineUnion()` from A's points (D2), and subtract B's lines
   from A's lines before B's polygons (so coincident lines cancel before any noding against
   polygon boundaries; this only reduces D4 effects).
2. `doSymDifference`: `Union(Diff(A, B), Diff(B, A))`, reusing `doDifference` both ways (D1).
3. `StructuredCollection(const Geometry*)`: an operand without non-empty elements takes its
   declared dimension `g->getDimension()` (D3), which gives the same typed empty as OverlayNG.

With it: every case of repro.c except 4a, 4b and 5a is right; `test_geos_unit
geos::geom::HeuristicOverlay` 17/17; full `ctest` 535/535; in the scan 458 results go from wrong
or error to right, 1 goes the other way (a difference whose A-lines are B's polygon
boundaries, noded at rounded crossings: D4), no AssertionFailed remains, symdifference "drops
parts" goes from 323 to 0. `prototype_fix_minimal.diff` is items 1 (first half), 2 and 3 only
(no reordering): 446 better, 11 worse, all 11 D4-type symdifferences that were right by
accident before. The remaining failures are D4 and D5.

## 5. Upstream search (2026-09-26)

GitHub issue/PR search (open and closed) in libgeos/geos: "symdifference GeometryCollection
drops points", "Unable to determine overlay result geometry dimension", "mixed
GeometryCollection overlay difference wrong result", "HeuristicOverlay StructuredCollection",
"intersection empty geometry with GeometryCollection throws exception assertion",
"SymDifference collection point lost asymmetric result", "intersecting GeometryCollection with
empty geometry error", "difference GeometryCollection point on line not removed"; PRs
"HeuristicOverlay GeometryCollection", "symdifference collection overlay fix", "overlay mixed
dimension collection". shapely/shapely: "symmetric difference GeometryCollection wrong result
missing geometry", "AssertionFailedException Should never reach here overlay empty geometry
collection". locationtech/jts: "OverlayNG GeometryCollection support non-homogeneous". Web:
the assertion message; PostGIS trac for ST_SymDifference with GCs.

No report of D1, D2, D4 or D5 was found. Related:

- libgeos/geos#797 (closed): mixed-GC difference threw after the old overlay engine was removed;
  fixed by #923 (introduced `StructuredCollection`).
- libgeos/geos#923 (PR, merged 2023-06-14): "Overlay with mixed dimension", the origin of D1, D2, D4.
- libgeos/geos#1224 (closed) / #1229 (PR, merged 2025-01-17): empty elements in GC overlay; the
  origin of D3 and of routing simple polygonal GCs (1a, 1b) into `StructuredCollection`.
- libgeos/geos#948 (open): difference with a GC of overlapping polygons threw a
  TopologyException on 3.12.0; no longer reproduces on main (#1229 unions the polygons first).
- libgeos/geos#1023 / PR #1050 (closed): the 3.9-branch counterpart of #797.
- libgeos/geos#1316 (closed): difference of a line and a point; different (not GC).
- duckdb/duckdb-spatial#803 (closed): downstream report of D3; not forwarded to GEOS as far as
  the page shows.
- locationtech/jts#667 (open): proposal that OverlayNG accept heterogeneous GCs; context only.

## 6. Relation to other findings

Independent of `geos-relateng-segfault` (RelateNG, empty GC elements) and of the RelateNG
predicate findings: this is the overlay code path, and no relate call is involved.
`tests/crosscheck/test_overlay_crosscheck.py` pins the lead's cases (`GEOS_GC_OVERLAY`,
`GEOS_GC_EMPTY_ASSERTION`) against Shapely's GEOS 3.13.1; they are D1, D2 and D3.

## 7. Files

- `repro.c`: the minimal cases through the public C API, with controls (`*Prec_r` = OverlayNG
  proper, the same operands without the GC wrapper, swapped operands) and GEOS's own predicates.
  Outputs: `output_geos-main-ae9cdd9.txt`, `output_geos-3.15.0.txt`, `output_geos-3.13.0.txt`,
  `output_geos-main-ae9cdd9+prototype_fix.txt`; `output_geosop.txt` (the geosop CLI).
- `repro.py`: the same through Shapely; `output_shapely-2.0.7_geos-3.11.4.txt`,
  `output_shapely-2.1.2_geos-3.13.1.txt`, `output_shapely-2.2.0rc1_geos-3.14.1.txt`.
- `Repro.java`: JTS contrast; `output_jts-1.20.0.txt`, `output_jts-master-3ea61f8.txt`.
- `cases.jsonl`: the cases with exact answers and the recorded GEOS results;
  `exact_check.py` / `output_exact_check.txt`: exact answers, certificates, hand checks.
- `output_lead_cases.txt`: the lead's cases (task text, leads.toml) on main, 3.15.0 and the fix.
- `scan.py`, `scan_overlay_batch.c`, `output_scan.txt`: the differential scan.
- `prototype_fix.diff`, `prototype_fix_minimal.diff`: prototype fixes (not upstream).
- `FINAL.md`: the report drafted for libgeos/geos. `finding.toml`: registry entry.
- `run.sh`: builds and runs everything.
