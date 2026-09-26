<!-- Filing note (delete before posting): file the GEOS issue (FINAL.md) first, then replace GEOS_ISSUE_URL below with its link. -->

# RelateNG: wrong relate/predicates when a ring vertex lies inside another ring's edge (a MultiPolygon does not contain its own element)

`RelateNG` gives wrong DE-9IM matrices for some **valid** polygonal inputs. The trigger is a vertex of one ring that lies in the interior of an edge of another ring in the same geometry. Two cases produce this: MultiPolygon elements that touch vertex-to-edge, and a hole that touches its shell at a hole vertex. In every failing case I found, the other operand has a boundary edge that runs along that ring edge, through the touch point. In the simplest case a MultiPolygon does not contain its own first element. The default `RelateOp` is correct, so this only affects code that calls `RelateNG` directly or runs with `-Djts.relate=ng`. GEOS has used RelateNG for `relate` and the non-prepared predicates since 3.13.0, and GEOS shows the same results; I reported it there as GEOS_ISSUE_URL.

## Reproducer

```java
WKTReader r = new WKTReader();
Geometry a = r.read("MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))");
Geometry b = r.read("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))");
System.out.println(RelateNG.relate(a, b));                              // 2F2F11212  (expected 2F2F11FF2)
System.out.println(RelateNG.relate(a, b, RelatePredicate.contains()));  // false      (expected true)
System.out.println(RelateNG.relate(a, b, RelatePredicate.overlaps()));  // true       (expected false)
System.out.println(a.relate(b));                                        // 2F2F11FF2  (RelateOp, correct)
```

The output in the comments is from real runs on master 3ea61f8 and on 1.20.0.

`RelateNG.relate(a, b)` on master and 1.20.0:

| # | A | B | expected | RelateNG |
|---|---|---|---|---|
| 1 | `MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))` | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` | `2F2F11FF2` (contains) | `2F2F11212` (overlaps) |
| 1r | case 1 with the arguments swapped | | `2FFF1F212` (within) | `2F2F11212` (overlaps) |
| 2 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))` | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `212F1FFF2` (contains) | `21211F2F2` (overlaps) |
| 3 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))` | `FF2F11212` (touches) | `212F11212` (overlaps) |

The expected answers can be checked by hand:
1. B is A's first element.
2. B is A with a triangular hole removed.
3. The two polygons lie on opposite sides of y = 0 and share that segment.

All inputs pass `IsValidOp`, and `Geometry.relate` (RelateOp) returns the expected matrix in every case.

With `-Djts.relate=ng`, the `Geometry` methods give the same wrong results. In case 2, `a.contains(b)` still returns true, but only because of the rectangle short-cut in `Geometry.contains` (Geometry.java:868-870). `a.covers(b)` returns false and `a.overlaps(b)` returns true.

## Analysis

Line numbers are from master 3ea61f8.

1. **Polygonal inputs skip self-noding.** `RelateGeometry.isSelfNodingRequired()` (RelateGeometry.java:262-275) returns false for Polygon/MultiPolygon, *"since they can only touch at vertices"* (javadoc, line 258). Valid polygonal geometries can also have a ring vertex in the interior of another ring's edge.
2. **Only A's flag is consulted.** `TopologyComputer.isSelfNodingRequired()` (TopologyComputer.java:142-154) checks only `geomA.isSelfNodingRequired()`, plus `geomB.hasAreaAndLine()`. For two polygonal inputs the result is false, so `computeAtEdges` uses `computeEdgesMutual` (RelateNG.java:526-531). NodeSections then come only from A×B segment intersections (EdgeSegmentIntersector.java:79-85). In 1.20.0 this method also checked `geomB.isSelfNodingRequired()`. That makes no difference for plain Polygon/MultiPolygon inputs, because the flag is false for both.
3. **The square gets no section at the touch point.** In case 1, the square's top edge and B's top edge are collinear, so their intersection yields only (0 2) and (2 2). The node at (1 2) gets sections for A's triangle and for B, but none for A's square.
4. **Side locations are then filled in wrongly.** `RelateNode.propagateSideLocations` (RelateNode.java:184-194) labels the square's edge halves as A-exterior. The output below comes from printing the node after `finish` in `TopologyComputer.evaluateNode`:
   ```
   Node[POINT ( 1 2 )]:
   LINESTRING ( 1 2, 2 2 ) - A:eee/B:ebi
   LINESTRING ( 1 2, 2 3 ) - A:ibe/B:eee
   LINESTRING ( 1 2, 0 3 ) - A:ebi/B:eee
   LINESTRING ( 1 2, 0 2 ) - A:eee/B:ibe
   ```
   `evaluateNodeEdges` then records Exterior(A)∩Interior(B) = 2 and Exterior(A)∩Boundary(B) = 1. Cases 2 and 3 fail the same way: the node gets a section for the hole but not for the shell.

Two checks support this:
- **Wrapping operand A in a GeometryCollection fixes every case.** The collection needs more than one element, which turns on self-noding. For case 1, `GEOMETRYCOLLECTION` of the two polygons; for cases 2 and 3, the polygon plus an interior `POINT (3 3)`. On master, wrapping operand B does not help (case 1 `2F2F11212`, case 2 `21211F2F2`, case 3 `212F11212`), since only A's flag is consulted. On 1.20.0, wrapping either operand works.
- **Forcing self-noding in RelateGeometry fixes all three cases.** I made `RelateGeometry.isSelfNodingRequired()` return true for Polygon/MultiPolygon. This was an experiment, not a proposed patch, because it self-nodes every polygon. Case 2 is fixed only because A (the square) is then self-noded too, which also nodes B's hole against B's shell.

So a targeted fix would also have to handle the affected geometry as operand B, as in case 2 and case 1r. I have not attempted a fix.

## Related issues checked

I searched locationtech/jts issues and PRs, open and closed: RelateNG, relate, noding, hole touching shell, and multipolygon contains. I found no duplicate. #396 ("Incorrect Relate value due to noding") is about the old RelateOp. #1175 is about line ends in `computeLineEnds`.

---

Found by differential testing against an exact rational-arithmetic oracle (geotruth: https://github.com/abafaboy/geotruth).
