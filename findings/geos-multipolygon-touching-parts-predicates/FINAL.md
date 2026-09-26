# RelateNG: wrong relate/predicates when a ring vertex lies inside another ring's edge (a MultiPolygon does not contain its own element)

Since GEOS 3.13.0, `relate` and the predicates built on it use RelateNG. RelateNG gives wrong results for some **valid** polygonal inputs. The trigger is a vertex of one ring that lies in the interior of an edge of another ring in the same geometry. Two cases produce this: MultiPolygon elements that touch vertex-to-edge, and a hole that touches its shell at a hole vertex. In every failing case I found, the other operand has a boundary edge that runs along that ring edge, through the touch point. In the simplest case a MultiPolygon neither `contains` nor `covers` its own first element, and `overlaps` returns true. GEOS 3.11.4 (old RelateOp) and GEOS's own overlay give the expected answers. JTS RelateNG gives the same wrong matrices.

## Reproducer

Output below is from `geosop` built from `main` (ae9cdd9):

```
$ geosop -a 'MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))' -b 'POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))' relate
2F2F11212
$ geosop -a 'MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))' -b 'POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))' contains
false
$ geosop -a 'MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))' -b 'POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))' overlaps
true
$ geosop -a 'POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))' -b 'POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))' relate
212F11212
$ geosop -a 'POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))' -b 'POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))' touches
false
```

The same check in Shapely:

```python
import shapely
a = shapely.from_wkt("MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))")
b = shapely.from_wkt("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))")
print(shapely.geos_version_string, a.relate(b), a.contains(b), a.covers(b), a.overlaps(b))
# 3.13.1 2F2F11212 False False True
# 3.14.1 2F2F11212 False False True
# 3.11.4 2F2F11FF2 True True False
```

All cases, run on `main`:

| # | A | B | expected `relate(A,B)` | actual (`main`) |
|---|---|---|---|---|
| 1 | `MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))` | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` | `2F2F11FF2` (contains, covers) | `2F2F11212` (overlaps) |
| 1r | case 1 with the arguments swapped | | `2FFF1F212` (within) | `2F2F11212` (overlaps) |
| 2 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))` | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `212F1FFF2` (contains, covers) | `21211F2F2` (overlaps) |
| 3 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))` | `FF2F11212` (touches) | `212F11212` (overlaps) |

The expected answers can be checked by hand:
1. B is A's first element.
2. B is A with a triangular hole removed.
3. A lies in y ≥ 0 and B lies in y ≤ 0, and they share the segment y = 0.

In case 1 the triangle's vertex (1 2) is the midpoint of the square's top edge. In cases 2 and 3 the hole's vertex (2 0) is the midpoint of the shell's bottom edge.

All inputs pass `GEOSisValid`. OGC SFS allows MultiPolygon elements to touch at finitely many points, and allows a hole to touch its shell at a single point. The touch point does not have to be a vertex of both rings.

Other observations on `main`:
- **Overlay agrees with the expected answers.** In cases 1 and 2, `difference(B, A)` is `POLYGON EMPTY`. In case 3, `intersection(A, B)` is `LINESTRING (0 0, 2 0, 4 0)`.
- **Adding the touch point as a vertex fixes case 1.** Inserting (1 2) into the square's top edge, in A or in B, gives `2F2F11FF2`.
- **B = the triangle `POLYGON ((1 2, 2 3, 0 3, 1 2))` is correct.**
- **Another B along the same edge also fails.** B = `POLYGON ((0 1, 2 1, 2 2, 0 2, 0 1))` gives `212F11212`; the expected matrix is `212F11FF2`.
- **Prepared predicates.** `containsPrep` and `coversPrep` (`GEOSPreparedContains_r`, `GEOSPreparedCovers_r`) also return false in case 1. In case 2 they return true, but only because A is a rectangle: `PreparedPolygon::contains` and `PreparedPolygon::covers` short-circuit (src/geom/prep/PreparedPolygon.cpp:96-101, 128-130).

## Versions

| Version | Source | Result |
|---|---|---|
| `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (3.16.0dev, 2026-09-21) | still the head of `main` on 2026-09-26 | wrong |
| 3.15.0 (tag d0228513abb0c29c185443cf2bfb06c9281024b5) | built from source; `src/operation/relateng` and `include/geos/operation/relateng` are identical to `main` | wrong |
| 3.14.1 | Shapely 2.2.0rc1 wheel | wrong |
| 3.13.1 | Shapely 2.1.2 wheel | wrong |
| 3.11.4 | Shapely 2.0.7 wheel, before RelateNG | correct |

Platform: Linux x86-64, gcc 13.3, Release build.

## Analysis

Line numbers are from `main` ae9cdd9.

1. **Polygonal inputs skip self-noding.** `RelateGeometry::isSelfNodingRequired()` (src/operation/relateng/RelateGeometry.cpp:239-253) returns false for `GEOS_POLYGON` and `GEOS_MULTIPOLYGON`. The header states the assumption (include/geos/operation/relateng/RelateGeometry.h:222-223): *"Self-noding is not required for polygonal geometries, since they can only touch at vertices."* For valid geometries this does not hold: a ring vertex can lie in the interior of another ring's edge, as in the inputs above.
2. **Only A's flag is consulted.** `TopologyComputer::isSelfNodingRequired()` (TopologyComputer.cpp:133-146) checks `geomA.isSelfNodingRequired()`, and otherwise only `geomB.hasAreaAndLine()`. For two polygonal inputs the result is false, so `RelateNG::computeAtEdges` uses `computeEdgesMutual` (RelateNG.cpp:645-650), which intersects A segments only with B segments. NodeSections are created only from those A×B intersections (EdgeSegmentIntersector.cpp:97-103).
3. **The square gets no section at the touch point.** In case 1, the square's top edge and B's top edge are the same segment, so their collinear intersection yields only (0 2) and (2 2). The node at (1 2) comes only from the triangle's vertex meeting the interior of B's top edge. It gets sections for A's triangle and for B, but none for A's square, although the square's edge passes through (1 2).
4. **Side locations are then filled in wrongly.** `RelateNode::finishNode` / `propagateSideLocations` (RelateNode.cpp:226-253) fill in A's side locations at that node from the triangle alone. `TopologyComputer::evaluateNodeEdges` (TopologyComputer.cpp:562-576) then records Exterior(A)∩Interior(B) = 2 and Exterior(A)∩Boundary(B) = 1. Those are exactly the wrong cells. I instrumented the equivalent JTS code (`TopologyComputer.evaluateNode`, printing the node after `finish`). At (1 2), the two halves of the square's top edge are labelled A-exterior on both sides (`A:eee`), where they should be A-boundary (`A:ebi` / `A:ibe`):
   ```
   Node[POINT ( 1 2 )]:
   LINESTRING ( 1 2, 2 2 ) - A:eee/B:ebi
   LINESTRING ( 1 2, 2 3 ) - A:ibe/B:eee
   LINESTRING ( 1 2, 0 3 ) - A:ebi/B:eee
   LINESTRING ( 1 2, 0 2 ) - A:eee/B:ibe
   ```
   Cases 2 and 3 fail the same way: the node gets a section for the hole but not for the shell.

Two checks support this:
- **Forcing full noding through the public API.** Wrapping **operand A** in a GeometryCollection with more than one element turns on self-noding, and every case then gives the expected matrix on `main`:
  - `GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 3, 0 3, 1 2)))` vs case 1 B gives `2F2F11FF2`.
  - `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (3 3))` vs case 2 B gives `212F1FFF2`.
  - The case 3 A plus `POINT (3 3)`, vs case 3 B, gives `FF2F11212`.

  In case 2 the wrapped A is the plain square, not the polygon with the touching hole. The wrapper still fixes case 2 because, once self-noding is on, `computeEdgesAll` nodes the A and B edges together, so B's hole is also noded against B's shell.

  Wrapping **operand B** instead does not help, because only A's flag is consulted. Case 1 still gives `2F2F11212`, case 2 `21211F2F2` and case 3 `212F11212`, on `main` and also on 3.13.1 and 3.14.1.
- **An experiment in JTS.** In JTS master I made `RelateGeometry.isSelfNodingRequired()` return true for Polygon/MultiPolygon. This was an experiment, not a proposed patch, since it self-nodes every polygon. It fixes all three cases. Case 2 is fixed only because A (the square) is then self-noded too.

So a fix that marks only the affected geometry as needing noding would also have to handle that geometry as operand B, as in case 2 and case 1r. I have not attempted a fix.

## JTS

JTS RelateNG has the same code (RelateGeometry.java:262-275, TopologyComputer.java:142-154) and gives the same matrices. I tested JTS 1.20.0 (6e95fe82) and master (3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd), calling `RelateNG.relate(a, b)` directly and also setting `-Djts.relate=ng`. JTS's default RelateOp is correct. I am also reporting this on locationtech/jts.

## Related issues checked

I searched libgeos/geos and locationtech/jts issues and PRs, open and closed. Search terms: RelateNG, relate, contains/covers/touches/overlaps with multipolygon, hole touching shell, self-noding. I found no duplicate. The closest are different problems:
- #1147 (closed), "RelateNG DE9IM regression": a LineString against a MultiPolygon whose elements share a segment, which is an invalid MultiPolygon. Here the inputs are valid and the parts meet at a single point.
- #1027 (open, January 2024, before RelateNG): `covers` with a MultiPolygon and a GeometryCollection argument.
- #1253 (closed): a TopologyException from `covers` in 3.11/3.12 (old RelateOp).

---

Found by differential testing against an exact rational-arithmetic oracle (geotruth: https://github.com/abafaboy/geotruth).
