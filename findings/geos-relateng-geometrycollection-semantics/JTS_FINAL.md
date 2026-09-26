# RelateNG: three GeometryCollection (union semantics) defects

RelateNG documents GeometryCollection inputs "containing mixed types and overlapping polygons" as
supported using union semantics (`RelateNG.java:50-51`, `package-info.java:74-86`). Three
independent defects give wrong matrices and wrong named predicates for such valid inputs. GEOS has
the same code and the same results; each defect is reported there separately. They are listed
together here, but each section stands alone and can become its own issue.

Versions: JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd and 1.20.0 (6e95fe82) are both
wrong, through `RelateNG.relate(a, b)`, `RelateNG.relate(a, b, RelatePredicate.x())` and the
prepared `RelateNG.prepare(a)`. The two versions give the same results on every case below except
one, noted in section 3.

RelateNG is not JTS's default (`GeometryRelate.RELATE_NG_DEFAULT = false`), so these defects are
reached through the `RelateNG` API or with `-Djts.relate=ng`. With the default, `Geometry.relate`
(and `crosses`, which calls it) rejects collections (IllegalArgumentException), and the other named
predicates use RelateOp, which throws TopologyException ("side location conflict") for the
overlapping collections of sections 2 and 3.

Repro: `Repro.java` (public API only). It prints the matrix both ways, the named predicates, and
`RelateNG.relate(a.union(), b)` for comparison. The union gives the expected matrix in sections 2
and 3. It does not help in section 1: the union of a polygon and a separate point is still a mixed
collection, and in the line example the collection is B.

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

On its own this change unmasks the first-vertex form of defect 3 and the area-vertex skip in
`computeAreaVertex` (reported separately), so it should land together with the fix for 3.

## 3. Union boundary made of pieces of several rings is never evaluated

```
A = GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)),
                        POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))
B = POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))
RelateNG.relate(A, B) = 2FFF1FFF2   expected 2FF11F2F2; equalsTopo, contains, covers = true (expected false)
RelateNG.relate(A.union(), B) = 2FF11F2F2
```

A is a 3x3 frame with a 1x1 hole, made of four overlapping strips.

`RelateNG.computeAreaVertex(ring)` (506-516) tests only the ring's first vertex.
`TopologyComputer.evaluateNodes` (485-493) evaluates only nodes with A/B interaction. So two parts
of the union boundary are never seen:

- a boundary component made of pieces of several rings, like the hole here, whose corners are
  crossings of the collection's own polygons. No ring vertex lies on it, so choosing a different
  vertex per ring would not reach it;
- a ring whose first vertex lies inside the union. The TODO at line 507 ("use extremal (highest)
  point to ensure one is on boundary of polygon cluster") already anticipates this. A concrete
  case: `GEOMETRYCOLLECTION (POLYGON ((1 1, 0 0, 2 0, 1 1)), POLYGON ((1 1, 2 0, 2 2, 0 2, 0 0,
  1 1)))` against `LINESTRING (5 5, 6 6)` gives `FF2FFF102`; the expected matrix is `FF2FF1102`.

With the arguments swapped, `RelateNG.relate(B, A)` for the frame gives `212F11FF2` on master and
`2FFF1FFF2` on 1.20.0; the expected matrix is `212F1FFF2`.

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
- `Repro.java`: the only wrong cases left are the two frames (strips and L-shapes) with the
  collection as B (they need B to be self-noded again, see above) and the #1099 self-noding case itself (reported separately).

The equivalent GEOS patches pass the full GEOS ctest (535/535). Over 29,719 generated cases they
correct 1001 answers and change no correct one.

No existing JTS issue or PR covers these (searched: "RelateNG GeometryCollection",
"AdjacentEdgeLocator", "GeometryCollection overlapping polygons predicate"). Related and checked:

- #1069 ("Fix RelateNG for Line Ends in mixed-dim GCs", for libgeos/geos#1148): Point and Line
  elements *covered* by the collection's polygon. Section 1 is about uncovered elements; the
  libgeos/geos#1148 cases are correct on master.
- #1052, #1055 (the RelateNG API), #1073 (`jts.relate=ng`), #1089 and #1090 (EMPTY semantics):
  none covers these cases.
- #1099 (prepared A/L caching): the self-noding change mentioned in section 3, reported
  separately.
- #1175, fixed by #1200: the known-exterior skip in `computeLineEnds`. The same skip in
  `computeAreaVertex` is reported separately.
- #784 and #833: overlay with overlapping collections, not relate.
- libgeos/geos#1060 lists the pre-RelateNG GeometryCollection predicate issues in GEOS. Of these,
  libgeos/geos#981, libgeos/geos#982, libgeos/geos#1022, libgeos/geos#1027 and libgeos/geos#1033
  give the expected answers on GEOS main.

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
