# RelateNG: three GeometryCollection (union semantics) defects

RelateNG documents GeometryCollection inputs "containing mixed types and overlapping polygons" as
supported using union semantics (`RelateNG.java:50-51`, `package-info.java:74-86`). Three
independent defects give wrong matrices and wrong named predicates for such valid inputs. GEOS has
the same code and the same results; each defect is reported there separately. They are listed
together here, but each section stands alone and can become its own issue.

Versions: JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd and 1.20.0 (6e95fe82) are both
wrong. Both use `RelateNG.relate(a, b)` and `RelateNG.relate(a, b, RelatePredicate.x())`. JTS's
default `Geometry.relate` (RelateOp) rejects collections.

Repro: `Repro.java` (public API only). It prints the matrix both ways, the named predicates, and
`RelateNG.relate(a.union(), b)` for comparison.

## 1. A Point element of a mixed collection invents exterior entries

```
A = GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))
B = POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))
RelateNG.relate(A, B) = 212FF1212        expected 212FF1FF2; contains = false (expected true)

A = LINESTRING (0 0, 1 0, 0 1, 0 0)
B = GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))
RelateNG.relate(A, B) = 0FFFFF102        expected 0F1FFF102; within = true (expected false)
```

`TopologyComputer.addPointOnGeometry` (TopologyComputer.java:286-293) records
`Exterior x Interior = 2` and `Exterior x Boundary = 1` for any Point element and an areal target,
even when the point is in the target's *exterior*. That is valid only for a puntal source, which
`initExteriorDims` already handles. The point may be one element of a collection whose polygons
cover the target.

Conversely, `addLineEndOnGeometry` (310-330) returns at `case Dimension.P` without recording
`Interior x Exterior = 1` when the line end lies on a Point element of a mixed target.

Fix (tested): infer only from the point's neighbourhood.

- For a point in the target exterior, add nothing.
- For a point in the target interior, add E/I = 2.
- For a point on the target boundary, add E/I = 2 and E/B = 1.
- For a line end on a Point, add I/E = 1.

## 2. Overlapping area sections at a node: an interior point is located on the boundary

```
A = GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))
RelateNG.relate(A, POINT (2 1))           = FF20F1FF2   expected 0F2FF1FF2 (contains false, touches true)
RelateNG.relate(A, LINESTRING (2 2, 2 0)) = 1020011F2   expected 102F01FF2 (contains false, crosses true)
RelateNG.relate(A.union(), POINT (2 1))   = 0F2FF1FF2
```

The arrowhead's reflex vertex (2 1) lies on the rectangle's top edge, and the rectangle covers the
notch.

`RelateNode.addEdges(NodeSection)` (RelateNode.java:52-71) inserts both area edges of a section
before calling `updateIfAreaPrev` / `updateIfAreaNext` (lines 69-70). By then the neighbour they
inspect is usually the section's own other edge. Edges that fall into a sector already made
interior by an overlapping section keep an EXTERIOR side. Adjacent sections are resolved by
`RelateEdge.merge`, so only *overlapping* ones fail.

The bug reaches the results in two ways:

- `AdjacentEdgeLocator.locate` (48-56), used when a point lies on two or more polygon boundaries
  (RelatePointLocator.java:317-321), then returns BOUNDARY.
- `TopologyComputer.evaluateNode` mislabels edges through the node.

`AdjacentEdgeLocator.createSection` (line 82) also gives every ring id 1 and ring 0, so holes are
treated as shells.

Fix (tested):

- check each edge's sector right after inserting it, and never compare an edge with itself;
- give `AdjacentEdgeLocator` sections their polygon and ring index, so that one polygon's rings go
  through `PolygonNodeConverter`.

On its own this change unmasks defect 3 and the area-vertex skip (next paragraph and below). It
should land together with the fix for 3.

## 3. Union boundary not formed by input rings is never evaluated

```
A = GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)),
                        POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))
B = POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))
RelateNG.relate(A, B) = 2FFF1FFF2   expected 2FF11F2F2; equalsTopo, contains, covers = true (expected false)
RelateNG.relate(A.union(), B) = 2FF11F2F2
```

A is a 3x3 frame with a 1x1 hole, made of four overlapping strips.

`RelateNG.computeAreaVertex(ring)` (506-516) tests only the ring's first vertex, as its TODO at
line 507 notes. `TopologyComputer.evaluateNodes` (485-493) evaluates only nodes with A/B
interaction. So two parts of the union boundary are never seen:

- a boundary component made of pieces of several rings, like the hole here, whose corners are
  crossings of the collection's own polygons;
- a ring whose first vertex lies inside the union.

For example, `GEOMETRYCOLLECTION (POLYGON ((1 1, 0 0, 2 0, 1 1)), POLYGON ((1 1, 2 0, 2 2, 0 2,
0 0, 1 1)))` against `LINESTRING (5 5, 6 6)` gives `FF2FFF102`; the expected matrix is
`FF2FF1102`.

Fix (tested):

- use a ring vertex on the union boundary when the first one is interior;
- evaluate nodes where area sections of two or more elements of one geometry meet, using the
  other geometry's location there, which is constant around the node.

With the collection as the second argument, the fix also needs B to be self-noded again, which
#1099 changed; that is reported separately.

## Tests of the combined prototype (`jts_prototype_fix.diff`)

- relateng JUnit: 154/154, the same as unpatched.
- XML relate suites with `-Djts.relate=ng`: 1135/1136, with the same pre-existing failure in
  TestRobustRelateFloat as unpatched.
- `Repro.java`: the only wrong cases left are the frame with the collection as B (needs the #1099
  revert) and the #1099 regression case itself.

In GEOS the port passes the full ctest (535/535). Over 33,719 generated cases it corrects 1001
answers and changes no correct one.

No existing JTS issue or PR covers these (searched: "RelateNG GeometryCollection",
"AdjacentEdgeLocator", "GeometryCollection overlapping polygons predicate"; related: #1069,
fixed, covered elements in mixed GCs; #784 and #833, overlay).

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
