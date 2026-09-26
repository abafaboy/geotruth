# Triage: geos-relateng-geometrycollection-semantics

## Verdict

The lead's five GeometryCollection classes split into **three new, independent bugs** in RelateNG's
GeometryCollection handling. Two further classes were already covered by other findings.

| class in the lead / tests | what it is | verdict |
|---|---|---|
| `mixed-gc` (test_witness_vs_geos.py), lead `relateng-gc-polygon-with-exterior-point` | **D1**: point-local exterior inferences in `TopologyComputer` assume a homogeneous geometry | **new bug** |
| `gc-adjacent-edge` / `GEOS_POINT_LOCATION` (test_relate_dual.py) | **D2**: `RelateNode::addEdges` mislabels sectors when area sections of *overlapping* GC polygons meet at a node; `AdjacentEdgeLocator` (point location) and node evaluation both use it | **new bug** |
| found during this triage | **D3**: a piece of the union's boundary that is no input ring (a hole made by overlapping polygons), or rings whose tested vertex lies inside the union, are never evaluated | **new bug** |
| `gc-overlapping-polygons` (the lead's first example, GC as operand B) | the GH-1201 self-noding regression (3.13.1) | already `geos-relateng-line-end-skip/covered-ring` |
| `empty-element-dimension` | declared dimension of an EMPTY element | already `geos-relateng-segfault` (case 3); D1's fix also corrects it |

All three new bugs are present in GEOS `main` and 3.15.0, and in every RelateNG release back to
3.13.0. JTS master and 1.20.0 have them too: RelateNG is a JTS port, and JTS master gives the same
matrix as GEOS main on all 22 cases. The inputs are valid. The documentation promises the answers
the exact engine gives: *"GeometryCollection inputs containing mixed types and overlapping polygons
are supported, using union semantics"* (GEOS `RelateNG.h:64-65`, JTS `RelateNG.java:50-51`). JTS
`relateng/package-info.java:76-86` spells this out: *"The element geometries may overlap in any
combination"*, and *"GeometryCollections are evaluated as if they were replaced by the topological
union of their elements"*. No upstream report of any of the three was found. Nothing has been
posted.

The named predicates are affected, not only the matrix:

- **D1:** `contains(GC(square, far point), smaller square)` is false.
  `within(LINESTRING(0 0, 1 0, 0 1, 0 0), GC(POINT(0 0), LINESTRING(5 5, 6 6)))` is true.
- **D2:** `contains(GC(arrowhead, rectangle), POINT(2 1))` is false and `touches` is true, for an
  interior point.
- **D3:** four overlapping strips forming a 3x3 frame with a 1x1 hole are `equals` to the full
  3x3 square. `contains` and `covers` are also true.

In each case GEOS contradicts itself:

- **D1:** without the far point `contains` is true. For the line form, GEOS's own
  `difference(A, B)` is the whole ring.
- **D2 and D3:** `GEOSRelate(GEOSUnaryUnion(A), B)` gives the exact answer.
- **D3:** GEOS's own point locator puts the frame's centre outside the frame.

Each bug has its own root cause, fix location and report:

- `FINAL.md` (D1)
- `FINAL_2_overlapping_sections.md` (D2)
- `FINAL_3_union_boundary.md` (D3)

The JTS report is `JTS_FINAL.md`, with one section per bug.

A prototype fix, one patch per bug, passes GEOS's ctest (535/535) and JTS's RelateNG JUnit
(154/154) and XML relate suites, with the same single pre-existing failure. It corrects 1001 of the
1419 wrong answers in a 33,719-case differential run and turns no correct answer wrong (section 6).
The remaining 418 wrong answers are the classes of the other findings and the known inexact-node
class. Patch 2 must not land without patch 3: on its own it unmasks an older skip bug in 10 cases.

## 0. Upstream heads (`git ls-remote`, 2026-09-26)

| repo | ref | commit | moved since the builds? |
|---|---|---|---|
| libgeos/geos | `main` | ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (2026-09-21) | no (= /tmp/claude-0/gb-build/geos-main) |
| libgeos/geos | tag 3.15.0 (latest release) | d0228513abb0c29c185443cf2bfb06c9281024b5 | no (= /tmp/claude-0/gb-build/geos-release) |
| locationtech/jts | `master` | 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd (2026-09-23) | no (= /tmp/claude-0/gb-build/jts-main) |
| locationtech/jts | tag 1.20.0 (latest release) | 6e95fe82feb986a7aa657f4ffa406d8c290af509 | the jar in /tmp/claude-0/gb-build/jts-release |

Also run: GEOS 3.13.0 (d7957246, the first RelateNG release, source build from the
line-end-skip triage), 3.14.1 (Shapely 2.2.0rc1 wheel), 3.13.1 (Shapely 2.1.2 wheel), and 3.11.4
(Shapely 2.0.7 wheel, before RelateNG).

## 1. Reproduction

Cases are in `cases.jsonl`: 22 cases, each with its exact matrix and predicates. `repro.c` (GEOS
C API), `repro.py` (Shapely) and `Repro.java` (JTS) print, for every case:

- `relate(A,B)` and `relate(B,A)` against the exact matrix and its transpose;
- the named predicates of (A,B), plus the prepared ones in C;
- `relate(unaryUnion(A), B)`.

The outputs are in `output/`. Run everything with `GEOS_CONFIG=... JTS_JAR=... ./run.sh`.

`relate(A,B)` by version ("ok" means exact):

| case | exact relate(A,B) | GEOS main / 3.15.0 | 3.14.1 | 3.13.1 | 3.13.0 | 3.11.4 | JTS master | JTS 1.20.0 |
|---|---|---|---|---|---|---|---|---|
| d1-far-point-contains | `212FF1FF2` | `212FF1212` | `212FF1212` | `212FF1212` | `212FF1212` | ok | `212FF1212` | `212FF1212` |
| d1-own-polygon | `2F0F1FFF2` | `2F0F1F212` | `2F0F1F212` | `2F0F1F212` | `2F0F1F212` | ok | `2F0F1F212` | `2F0F1F212` |
| d1-own-polygon-within | `2FFF1F0F2` | `2F2F110F2` | `2F2F110F2` | `2F2F110F2` | `2F2F110F2` | ok | `2F2F110F2` | `2F2F110F2` |
| d1-interior-point-eb | `2121F12F2` | `2121F1212` | `2121F1212` | `2121F1212` | `2121F1212` | ok | `2121F1212` | `2121F1212` |
| d1-line-covers-boundary-eb | `F10FFF2F2` | `F10FFF212` | `F10FFF212` | `F10FFF212` | `F10FFF212` | ok | `F10FFF212` | `F10FFF212` |
| d1-line-end-on-points | `FF10FF102` | `FFF0FF102` | `FFF0FF102` | `FFF0FF102` | `FFF0FF102` | `1F10FF102` | `FFF0FF102` | `FFF0FF102` |
| d1-ring-within-point | `0F1FFF102` | `0FFFFF102` | `0FFFFF102` | `0FFFFF102` | `0FFFFF102` | `1F1FFF102` | `0FFFFF102` | `0FFFFF102` |
| d1-testfile-closed-line | `0F2FF11F2` | `0F2FF1FF2` | `0F2FF1FF2` | `0F2FF1FF2` | `0F2FF1FF2` | `1F2FF11F2` | `0F2FF1FF2` | `0F2FF1FF2` |
| d1-testfile-line-ends | `FF10FF102` | `FFF0FF102` | `FFF0FF102` | `FFF0FF102` | `FFF0FF102` | `1F10FF102` | `FFF0FF102` | `FFF0FF102` |
| d2-reflex-point | `0F2FF1FF2` | `FF20F1FF2` | `FF20F1FF2` | `FF20F1FF2` | `FF20F1FF2` | exception | `FF20F1FF2` | `FF20F1FF2` |
| d2-reflex-point-swapped-elements | `0F2FF1FF2` | `FF20F1FF2` | `FF20F1FF2` | `FF20F1FF2` | `FF20F1FF2` | exception | `FF20F1FF2` | `FF20F1FF2` |
| d2-reflex-line | `102F01FF2` | `1020011F2` | `1020011F2` | `1020011F2` | `1020011F2` | exception | `1020011F2` | `1020011F2` |
| d2-adjacent-control | `0F2FF1FF2` | ok | ok | ok | ok | `FF20F1FF2` | ok | ok |
| d2-testfile-gc-reflex | `0F2FF1FF2` | `FF20F1FF2` | `FF20F1FF2` | `FF20F1FF2` | `FF20F1FF2` | exception | `FF20F1FF2` | `FF20F1FF2` |
| d2-testfile-gc-reflex-line | `102FF1FF2` | `102F01FF2` | `102F01FF2` | `102F01FF2` | `102F01FF2` | exception | `102F01FF2` | `102F01FF2` |
| d3-frame-equals | `2FF11F2F2` | `2FFF1FFF2` | `2FFF1FFF2` | `2FFF1FFF2` | `2FFF1FFF2` | exception | `2FFF1FFF2` | `2FFF1FFF2` |
| d3-frame-two-l-shapes | `2FF11F2F2` | `2FFF1FFF2` | `2FFF1FFF2` | `2FFF1FFF2` | `2FFF1FFF2` | exception | `2FFF1FFF2` | `2FFF1FFF2` |
| d3-frame-control-polygon | `2FF11F2F2` | ok | ok | ok | ok | ok | ok | ok |
| d3-frame-control-center | `FF2FF10F2` | ok | ok | ok | ok | exception | ok | ok |
| d3-no-boundary-vertex | `FF2FF1102` | `FF2FFF102` | `FF2FFF102` | `FF2FFF102` | `FF2FFF102` | ok | `FF2FFF102` | `FF2FFF102` |
| known-gc-overlap-as-b | `2FF11F212` | `212111212` | `212111212` | `212111212` | ok | exception | `212111212` | ok |
| known-empty-element | `FF1FF00F2` | `FF2FF10F2` | `FF2FF10F2` | `FF2FF10F2` | `FF2FF10F2` | `FF2FF10F2` | `FF2FF10F2` | `FF2FF10F2` |

"exception" means GEOS 3.11.4's RelateOp threw a TopologyException: side location conflict. Its
GeometryGraph does not support overlapping GC polygons. The "d3" frame cases are also wrong in
reverse order: `relate(square, frame)` gives `212F11FF2` on main and `2FFF1FFF2` on 3.13.0; the
exact matrix is `212F1FFF2`.

Named predicates that are wrong on GEOS main and 3.15.0 (identical), unprepared and prepared (see
`output/geos-main-ae9cdd9.txt`):

| case | wrong predicates (GEOS / exact) |
|---|---|
| d1-far-point-contains, d1-own-polygon | contains, covers: false / true; overlaps: true / false |
| d1-own-polygon-within | within, coveredBy: false / true; overlaps: true / false |
| d1-line-end-on-points, d1-testfile-line-ends | coveredBy: true / false |
| d1-ring-within-point | within, coveredBy: true / false |
| d1-testfile-closed-line | crosses: false / true |
| d2-reflex-point (both element orders), d2-testfile-gc-reflex | contains: false / true; touches: true / false |
| d2-reflex-line | contains, covers: false / true; crosses: true / false |
| d3-frame-equals, d3-frame-two-l-shapes | equals, contains, covers: true / false |

The remaining cases are wrong in the matrix only.

## 2. The three bugs

Line numbers are for GEOS `main` ae9cdd9, with JTS master 3ea61f8 in brackets.

### D1: exterior entries are inferred from a single element of a mixed GeometryCollection

**Minimal cases.**

- `A = GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))`,
  `B = POLYGON ((0 0, 1 0, 0 1, 0 0))`: A's own polygon. The exact matrix is `2F0F1FFF2` and
  `contains` is true. GEOS gives `2F0F1F212` and `contains` false.
- The lead's example: `GC(POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))` against the
  square `[1,2]^2`.
- The line form: `A = LINESTRING (0 0, 1 0, 0 1, 0 0)`,
  `B = GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))`. The exact matrix is `0F1FFF102`.
  GEOS gives `0FFFFF102`, so `within(A, B)` is true: a triangle outline is "within" a point.

**Hand derivation.**

- First case: A is the triangle T plus the isolated point (2, 2). B = T is inside A: II = 2,
  BB = 1, and nothing of B is outside A, so EI = EB = F. The point adds IE = 0.
- Line form: the open segment from (0, 0) to (1, 0) is in A's interior. Only (0, 0) of it is in B,
  so IE = 1.

**Root cause.** `TopologyComputer::addPointOnGeometry` (TopologyComputer.cpp:332-339
[TopologyComputer.java:286-293]) handles a Point element that lies in the target *exterior*, with
a declared target dimension of A. It records `Exterior(source) x Interior(target) = 2` and
`Exterior(source) x Boundary(target) = 1`. The comment reads "If a point intersects an area target,
then the area interior and boundary must extend beyond the point and thus interact with its
exterior". That holds for a puntal source: there `initExteriorDims` (48-88 [44-83]) has already
set the same entries. It does not hold for a mixed GC, whose polygons or lines may cover the
target.

When the point is in the target's interior, the EB entry has the same flaw (case
`d1-interior-point-eb`).

The converse is `addLineEndOnGeometry` (346-369 [310-330]). A line end that lands on a Point
element of the target (`dimTarget == P`) returns at line 359-360 without recording
`Interior(line) x Exterior(target) = 1`. `initExteriorDims` supplies that entry only for a puntal
target (L/P). For a mixed target it is never recorded, although the line leaves the point at once.

The callers are `RelateNG::computePoint` (503-509) and `computeLineEnd` (560-574). They see only
the effective points (`RelateGeometry::getEffectivePoints`, RelateGeometry.cpp:308-327), which are
the Point elements not covered by a line or polygon. So a local inference is sound there.

**Fix** (`prototype_fix_1.diff`, 2 hunks). Use only the point's neighbourhood:

- skip the inference when the point is in the target exterior;
- record EB only when the point is on the target boundary;
- record `Interior x Exterior = L` for a line end on a Point element.

For homogeneous inputs nothing changes, because `initExteriorDims` already records these entries.

### D2: overlapping area sections at a node

**Minimal case.** `A = GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3
0, 3 1, 1 1, 1 0)))` is an "arrowhead" with a reflex vertex at (2 1), and a rectangle whose top
edge passes through (2 1). B = `POINT (2 1)`.

- Exact: `0F2FF1FF2`, and `contains` is true.
- GEOS: `FF20F1FF2`, `contains` false and `touches` true. The same with the elements swapped.
- `B = LINESTRING (2 2, 2 0)` goes through the vertex into the notch. The exact matrix is
  `102F01FF2`. GEOS gives `1020011F2`, so `contains` is false and `crosses` is true.
- Control: the notch filled *exactly* by the adjacent triangle `(0 0, 2 1, 4 0)`, with no
  overlap, is handled correctly.

**Hand derivation.**

- The arrowhead covers every direction from (2 1) except the downward wedge between the directions
  to (0 0) and (4 0).
- The rectangle covers the whole lower half-disc around (2 1), which contains that wedge.
- So the union covers a neighbourhood of (2 1), and (2 1) is Interior.
- `exact_check.py` confirms this: none of 124 exact probe points at distance 1e-6 lies outside both
  polygons.
- GEOS agrees once it has formed the union: `GEOSRelate(GEOSUnaryUnion(A), B)` = `0F2FF1FF2`.

**Root cause.** `RelateNode::addEdges(const NodeSection*)` (RelateNode.cpp:92-111
[RelateNode.java:52-71]) inserts both edges of an area section, e0 then e1, and only then checks
whether they fell into a sector that is already interior. It calls `updateIfAreaPrev(index0)` and
`updateIfAreaNext(index1)` at lines 110-111 [69-70]. By then the neighbour it inspects is usually
the section's own other edge.

- When the section's exterior sector lies inside an earlier section's interior (the notch inside
  the rectangle), the new edges keep EXTERIOR on that side.
- When the earlier section's edges lie inside the new section's interior, the same happens the other
  way round.

Adjacent, non-overlapping sections are handled by `RelateEdge::merge`, which is why tiled GCs and
valid (Multi)Polygons work. Overlapping ones are not.

Two callers are affected:

1. `AdjacentEdgeLocator::locate` (AdjacentEdgeLocator.cpp:47-57 [48-56]). RelatePointLocator uses
   it when a point lies on the boundaries of two or more GC polygons (RelatePointLocator.cpp:287-291
   [317-321]). A wrong EXTERIOR side makes it return BOUNDARY for an interior point.
   `AdjacentEdgeLocator::createSection` (line 97 [82]) also gives every ring's section id 1 and
   ring 0. All rings count as shells of one polygon, so a hole's section claims the whole outside
   of the hole.
2. `TopologyComputer::evaluateNode` (548-557). Its `isNodeInArea` goes through the same locator,
   and the node's own sections are added with the same logic (`d2-reflex-line`).

**Fix** (`prototype_fix_2.diff`).

- Test the sector each edge was inserted into right after inserting it, and never compare an edge
  with itself.
- Give `AdjacentEdgeLocator` sections their polygon index and ring index. The rings of one polygon
  then go through `PolygonNodeConverter` as the design intends, and different polygons are added
  separately.

Both parts are needed. With only the first, a hole section seen as a shell makes the far side of
a polygon corner interior. One sweep case (`mix-1` #2740) shows this.

### D3: parts of the union boundary that belong to no input ring are never evaluated

**Minimal case.** A is four overlapping strips forming a 3x3 square frame with a 1x1 hole, and B
is the full square:

```
A = GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)),
                        POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))
B = POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))
```

- Exact: `2FF11F2F2` (A is within B, and B is not within A).
- GEOS: `2FFF1FFF2`, so `equals`, `contains` and `covers` are true.
- The same happens with two overlapping L-shapes.
- The same frame written as one POLYGON with a hole is correct.
- GEOS's own point location puts (1.5 1.5) outside the frame.
- `GEOSRelate(GEOSUnaryUnion(A), B)` is exact.

A second form: `A = GC(POLYGON ((1 1, 0 0, 2 0, 1 1)), POLYGON ((1 1, 2 0, 2 2, 0 2, 0 0, 1
1)))`, a notched square with its notch filled. Both rings start at (1 1), which is interior to the
union. Against the far line `LINESTRING (5 5, 6 6)` GEOS gives `FF2FFF102`; the exact matrix is
`FF2FF1102` (BE lost).

**Hand derivation.** The union of the strips is `[0,3]^2 \ (1,2)^2`. Its hole boundary (the unit
square) lies in B's interior, so BI = 1, and the open hole lies in B, so EI = 2. GEOS's own
`unaryUnion` builds exactly this polygon with a hole. The audited polygon references
`tests/reference/oracle.py` and `indep.py` evaluate it against B as `within`, not `equals`, with
area 8 against 9 (`output/exact_check.txt`).

**Root cause.** RelateNG learns about the parts of an areal geometry away from the other
geometry's edges from one vertex per ring. `RelateNG::computeAreaVertex(ring)` (RelateNG.cpp:619-630
[RelateNG.java:506-516]) tests only `ring->getCoordinate()`. Its TODO at line 621 [507] says *"use
extremal (highest) point to ensure one is on boundary of polygon cluster"*.

That is enough for a Polygon, whose rings are its boundary. For overlapping GC polygons the union's
boundary is made of pieces of several rings. Two things go wrong:

1. A ring's first vertex can be interior to the union (`d3-no-boundary-vertex`). Then nothing is
   learnt about its boundary.
2. A union boundary component, such as the frame's hole, can consist only of ring pieces joined at
   points where polygons of the same GC cross. It then contains no tested vertex at all.

Those crossing points are computed: self-noding intersects A's edges with each other, and
`TopologyComputer::addIntersection` (233-245) stores their sections. But `evaluateNodes` (533-543
[485-493]) evaluates only nodes with `hasInteractionAB()`, so the hole is never seen.

**Fix** (`prototype_fix_3.diff`).

- (a) In `computeAreaVertex(ring)`, when the first vertex is interior to the union, use the first
  ring vertex that is on the union boundary, if there is one. Only GCs are affected, because for
  (Multi)Polygons `locateAreaVertex` returns BOUNDARY without locating.
- (b) In `evaluateNodes`, also evaluate a node whose sections are all area sections of one
  geometry, from at least two elements. The node's location in the other geometry is constant
  around it, so every side and edge location of the finished node gives an entry
  (`TopologyComputer::evaluateCollectionNode`). This needs `RelateNode::finishNode` to be public and
  two small `NodeSections` accessors.

`relate(square, frame)`, with the GC as operand B, stays wrong with this fix alone. Since GH-1201
(3.13.1) a GC operand B is not self-noded when A is polygonal, so its self-crossings are not
computed. The GH-1201 regression is reported separately in
`findings/geos-relateng-line-end-skip/covered-ring`. With that regression reverted as well
(`experiment-self-node-linear-b.diff` there), both orders are exact.

## 3. Exact answers, independent checks, validity, limits

- **Exact engine.** For each of the 22 cases, the arrangement route (`geotruth.relate`, strict) and
  the independent witness-point route (`relate_witness`) agree with the stored matrix
  (`output/exact_check.txt`, from `exact_check.py`).
- **Independent checks** (`exact_check.py`, `repro.*`):
  - D2 and D3: GEOS's and JTS's own union of A's elements gives the exact matrix.
  - D2: exact probing around the vertex.
  - D3: the audited `oracle.py` and `indep.py` evaluate the frame's union against the square.
  - D1: hand derivations. The polygon element alone gives `212FF1FF2`, and the far point only adds
    IE = 0. A ring point (1/2 0) is in the ring's interior and in the GC's exterior.
- **Validity.** `GEOSisValid`, JTS `IsValidOp` and geotruth's exact `validity.is_valid` are true
  for every operand. GEOS and OGC validate a GC element by element, and overlapping elements are
  allowed. All coordinates are small integers, so no rounding happens in the tested cases. The only
  constructed points are crossings at (1 1), (2 1) and so on, all exact.
- **Documented limits.** RelateNG's robustness caveat covers invalid input and numerical
  round-off (JTS `package-info.java:66-70`). Neither applies here. The GC semantics are documented
  as union semantics, and the answers above follow them.

## 4. Bug or by design?

These are bugs. RelateNG documents mixed-type and overlapping-polygon GCs as supported under union
semantics. The GEOS and JTS test suites exercise exactly this area:

- `TestRelateGC.xml` has cases such as "L/GC:A - line in interior of GC of overlapping polygons",
  "GC:A/GC:A - overlapping polygons equal to overlapping polygons", and "P/GC:A - point on common
  node of 3 adjacent polygons".
- `AdjacentEdgeLocatorTest` covers adjacent polygons.

None of these tests has an uncovered Point element next to a polygon, overlapping sections at a
vertex, or a union hole. The code comments show the authors knew about the gaps:

- "NOTE: this assumes the line end is NOT also in an Area of a mixed-dim GC" (TopologyComputer.cpp:402)
- "For GCs, the vertex may be either on boundary or in interior (i.e. of overlapping or adjacent
  polygons)" (TopologyComputer.cpp:419-423)
- the TODO in `computeAreaVertex`

Before RelateNG (GEOS 3.11.4), D1's point cases were correct. D2 and D3 threw TopologyException
there. Overlapping GCs were unsupported then, so D2 and D3 are not regressions; D1 is a behaviour
change that came with RelateNG (3.13.0).

## 5. Prevalence (sweeps)

Six generated families were used: `sweep.py`, written for this triage, and `xsweep.py`, which reuses
the `tools/crosscheck_relate.py` generators. The pairs are small-integer lattice pairs, GEOS-valid,
with no EMPTY elements. The exact answers come from the arrangement route. The classes are
attributed by the single-fix experiment builds (`attrib.txt`, and `experiment_toggles.diff`, which
has environment-variable switches). No case needed two of the three
fixes.

| family | cases | wrong on main | D1 | D2 | D3 | other findings (GH-1201, skips, EMPTY) | inexact node |
|---|---|---|---|---|---|---|---|
| mix-1 (mixed GCs vs all types) | 4000 | 59 | 44 | 2 | 0 | 11 | 2 |
| ovl-2 (GCs of 2-3 overlapping polygons) | 4000 | 75 | 3 | 0 | 1 | 70 | 1 |
| mix2-3 (GC lines/points on a polygon's boundary) | 4000 | 626 | 625 | 0 | 0 | 1 | 0 |
| adj-4 (reflex vertex on another polygon's edge) | 4000 | 302 | 3 | 256 | 31 | 9 | 3 |
| frame-5 (3-5 overlapping rectangles) | 3000 | 277 | 0 | 0 | 3 | 274 | 0 |
| xc (crosscheck lattice, dense, adversarial, exhaustive) | 10719 | 80 | 19 | 2 | 0 | 41 | 18 |

The inexact-node residue has a non-dyadic intersection point in every case (`inexact.py`). It is
the known `inexact-node` class of `tests/crosscheck/test_witness_vs_geos.py`, and its cause is
GEOS's floating-point rounding, which is outside the scope of this finding. Some of these cases
involve GCs, for example:

- a line crossing an internal, shared GC edge at (9/5, 16/5), where the rounded node falls off
  the other polygon's edge;
- a GC line crossing its own polygon's boundary at an inexact point.

## 6. Prototype fix and tests

`prototype_fix.diff` is the three patches together (GEOS, 9 files, +140/-16). Each of
`prototype_fix_1.diff`, `prototype_fix_2.diff` and `prototype_fix_3.diff` applies on its own. The
JTS port is `jts_prototype_fix.diff`.

- **GEOS main + all three:**
  - `ctest` 535/535;
  - relateng unit groups all ok: AdjacentEdgeLocator 6, RelateNG 64, RelateNGGC 25,
    RelateNGRobustness 19, RelatePointLocator 8, and the rest;
  - `repro.c`: 19 wrong cases become 3. What remains is the GH-1201 case and the two frames in
    reverse order.
- **Each patch alone**, then all three (`output/prototype_split_tests.txt`,
  `output/prototype_split_differential.txt`): each builds and passes ctest 535/535 on its own.
  - Patch 1 fixes 689 D1 cases (+1, `geos-relateng-segfault` case 3).
  - Patch 2 fixes 260 D2 cases.
  - Patch 3 fixes 32 D3 cases, plus 19 area-vertex-skip cases of `geos-relateng-line-end-skip`.
  - **Patch 2 alone turns 10 exact answers wrong.** They are all GCs of a notched polygon whose
    first ring vertex is the reflex vertex covered by the other polygon. Main's wrong BOUNDARY for
    that vertex happened to record BE. With the vertex correctly INTERIOR, the area-vertex skip
    (9 cases) or D3's no-boundary-vertex form (1 case) loses BE.
  - So **patch 2 must land with patch 3** (or at least with 3 (a) and the line-end-skip finding's
    area-vertex fix). The three together turn no exact answer wrong.
- **Differential run over the 33,719 cases** (`output/prototype_differential.txt`):
  - 1001 answers become exact;
  - **no answer that was exact becomes wrong**;
  - 20 of the 1001 are also fixed by the other findings' fixes. D3's boundary-vertex scan removes
    the area-vertex-skip symptom when the ring has a union-boundary vertex, and D1 fixes
    `geos-relateng-segfault` case 3.
- **JTS master + `jts_prototype_fix.diff`** (patched classes first on the classpath):
  - relateng JUnit 154/154, the same as unpatched;
  - XML suites with `-Djts.relate=ng` (TestRelateEmpty, TestRelateGC, TestRelate{AA,PP,LL,PL,PA,LA},
    TestRobustRelate{,Float}): 1135/1136 in both runs, with the same single pre-existing failure
    in TestRobustRelateFloat (`output/jts-prototype-tests.txt`);
  - `Repro.java`: 3 cases remain wrong, the same three as in GEOS.
- **Cost.** On a GC of 400 overlapping 33-vertex circles against a polygon, 10 calls (2 relate + 8
  predicates each) take 0.44 s instead of 0.18 s. The extra time goes to evaluating the GC's
  self-crossing nodes (D3 b). A production fix could skip `evaluateCollectionNode` once the entries
  it can set are known, or evaluate only nodes on the union boundary. The prototype does neither.

## 7. Upstream search (2026-09-26, open and closed)

**GitHub issue search.**

- libgeos/geos:
  - "RelateNG GeometryCollection wrong relate result";
  - "contains returns false GeometryCollection with polygon and point";
  - "overlapping polygons GeometryCollection covers equals interior hole union semantics";
  - "equals true for collection of polygons with a hole and a polygon without hole";
  - "point on shared boundary of two polygons in collection reported as boundary instead of interior";
  - PR searches "RelateNG" and "GeometryCollection relate".
- locationtech/jts:
  - "RelateNG GeometryCollection";
  - "AdjacentEdgeLocator point location collection boundary interior";
  - "RelateNG wrong matrix predicate contains within covers";
  - "GeometryCollection relate intersection matrix point outside polygon exterior interior dimension";
  - "GeometryCollection overlapping polygons predicate contains intersects relate union";
  - PR search "RelateNG".
- NetTopologySuite: "RelateNG GeometryCollection wrong result".
- shapely: "relate geometry collection wrong contains within GEOS 3.13".
- The web: "RelateNG GeometryCollection union semantics wrong result overlapping polygons";
  "ST_Contains GEOMETRYCOLLECTION point polygon false GEOS 3.13 RelateNG".

**No duplicate found.** Related items were checked and differ:

- **GEOS #1060** (Relate issue summary, closed) lists the pre-RelateNG GC issues. Checked on
  current GEOS:
  - **#1022** (open): ST_Crosses with GC(POINT, LINESTRING) depends on ring order. main gives
    `F01FF0212` for both ring orders, which is exact, so this looks fixed by RelateNG.
  - **#981** (open): ContainsProperly with a Point element on a line end. main gives `FF10F0FF2`,
    exact; the point is on the GC boundary.
  - **#982** (open): within(POINT, GC(POINT, LINESTRING)) depends on element order. Both orders now
    give `F0FFFF102`, which is correct under union semantics: the point is the line's boundary.
  - **#983** (open): RelateOp throws for GCs. RelateNG replaced it.
  - **#1033** (closed): contains(polygon, GC of points and a line) is now exact.
  - **#1011** (closed): the empty-element dimension, see `geos-relateng-segfault`.
  - **#1027** (open): covers after mutating POLYGON to MULTIPOLYGON, pre-RelateNG; see
    `geos-multipolygon-touching-parts-predicates`.

  #1022, #981 and #982 might be closable. That observation is not part of this report.
- **GEOS #1148 / JTS #1069** (closed, 3.13.0): "Fix RelateNG for Line Ends in mixed-dim GCs". The
  line-end fix for *covered* elements added the "skip line ends in a GC area" logic. The #1148 cases
  (a GC whose Point or Line elements are covered by its polygon) are exact on main. D1 is the
  *uncovered* element case, which that fix did not touch.
- **GEOS #948 and JTS #784, #833**: overlay (difference, union) with overlapping GC polygons. That
  is OverlayNG, not RelateNG.
- **GEOS PR #1201 / JTS PR #1099**: the self-noding change, see the covered-ring finding.

## 8. Relation to other findings and leads

- **`geos-relateng-line-end-skip/covered-ring`** (GH-1201): the lead's first example
  (`POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))` vs `GC(square, rect)`) is that regression. It is exact on
  3.13.0 and on JTS 1.20.0, exact with the GC as operand A, and fixed by restoring B's
  self-noding. D3's fix needs the same for a GC operand B.
- **`geos-relateng-line-end-skip`** (area-vertex skip): related to D3 (a). The skip there is safe
  only after a *boundary* vertex. D3 (a) is about rings with no boundary vertex tested at all. The
  two fixes are complementary and overlap on some inputs.
- **`geos-relateng-segfault`**:
  - case 3 is `EMPTY_ELEMENT_DIMENSION`. D1's fix corrects it too: the EXTERIOR point no longer
    invents IE/BE. The `getDimensionReal` fix there is still needed for the crash.
  - The `AdjacentEdgeLocator` empty-polygon crash sits in the function D2 changes. The two patches
    touch adjacent lines, so whichever lands second needs a rebase.
- **`geos-multipolygon-touching-parts-predicates`** (ring-touch-node) and
  **`geos-near-collinear-predicates`**: different mechanisms, valid (Multi)Polygons. They do not
  appear in the D1-D3 attributions.
- **Lead `relateng-gc-polygon-with-exterior-point`** (`corpus/curated/leads.toml`): this is D1, and
  this finding supersedes it (`finding.toml`).
- **`tests/crosscheck`**:
  - the `mixed-gc` class and `test_mixed_gc_point_changes_containment` are D1;
  - `GEOS_POINT_LOCATION` / `gc-adjacent-edge` is D2;
  - `gc-overlapping-polygons` is GH-1201;
  - `EMPTY_ELEMENT_DIMENSION` is `geos-relateng-segfault`.
  The docstring's description of `gc-overlapping-polygons` ("the node topology ... ignores the
  other elements covering that node") describes D2's mechanism. Its pinned case is GH-1201.

## 9. Caveats

- D1's line-end hunk sets `Interior x Exterior = L` for any line end on a Point. A zero-length
  line (GEOS-invalid; RelateNG treats it as a point) reaching that branch would get L instead of P.
  The existing `addLineEndOnLine` has the same caveat ("This works for zero-length lines as well").
- D3 (b) evaluates only nodes inside the A/B envelope intersection, where `computeAtEdges` works.
  Outside it, the other geometry is exterior, and the vertex scan (a) supplies BE.
- A union-boundary component made only of self-crossing pieces and lying entirely outside the
  envelope intersection would still be missed. No such case occurred in the sweeps.
- The prototype shows where the bugs are. It is not a tuned implementation (see the cost in
  section 6).
- PostGIS was not run. Every GEOS client that passes such GCs to predicates is exposed, and so are
  JTS users of `RelateNG`, or of `-Djts.relate=ng` (JTS's default `Geometry.relate` rejects GCs).

## Files

| file | what |
|---|---|
| `FINAL.md`, `FINAL_2_overlapping_sections.md`, `FINAL_3_union_boundary.md` | GEOS reports, one per bug |
| `JTS_FINAL.md` | JTS report (the three bugs, as separate sections) |
| `cases.jsonl` | the 22 cases (typed v2 records with `a_wkt`/`b_wkt`, the exact matrix, the exact predicates, the bug class) |
| `repro.c`, `repro.py`, `Repro.java`, `run.sh` | public-API repros (GEOS C, Shapely, JTS RelateNG) and the runner |
| `exact_check.py` | exact answers and independent checks (`output/exact_check.txt`) |
| `output/` | captured outputs: GEOS main, 3.15.0, 3.13.0; Shapely 2.1.2/3.13.1, 2.2.0rc1/3.14.1, 2.0.7/3.11.4; JTS master, 1.20.0; `geosop` one-liners (`geosop-main-ae9cdd9.txt`); the prototype runs; `testfile-dense-case-attribution.txt` (the third `GEOS_POINT_LOCATION` case, from the dense source, is D2) |
| `prototype_fix.diff`, `prototype_fix_{1,2,3}.diff`, `jts_prototype_fix.diff` | prototype fixes |
| `sweep/` | the generators, batch runner, comparison scripts, attribution and differential summaries |
| `finding.toml` | registry snippet |

Scratch (not needed to reproduce) is in `/tmp/claude-0/gb-build/triage2/geos-relateng-geometrycollection-semantics/`:
the experiment build with switches, the sweep TSVs and per-build outputs.
