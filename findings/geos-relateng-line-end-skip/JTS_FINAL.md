# RelateNG.computeAreaVertex: the known-exterior skip loses Boundary/Exterior for GeometryCollections (same flaw as #1175)

## Summary

#1200 fixed `RelateNG.computeLineEnds` (#1175). `RelateNG.computeAreaVertex` still has the same optimisation: once one ring vertex has been found in the target's exterior, polygons whose envelope is disjoint from the target are skipped. In a GeometryCollection, the tested vertex (the ring's first vertex) can lie inside another polygon of the collection. `TopologyComputer.addAreaVertex` then records only Interior/Exterior, and does not record Boundary/Exterior. The polygons skipped after it are the ones that carry the collection's boundary, so `relate` returns BE (or EB) = `F` instead of `1`. The result depends on element order.

This is reachable through `RelateNG` (`RelateNG.relate`, prepared `RelateNG`, and pattern evaluation), and through `Geometry.relate` when `jts.relate=ng` is set. The default `Geometry.relate` (RelateOp) throws `IllegalArgumentException` for GeometryCollection arguments, so it never gets here. GEOS has used RelateNG by default since 3.13.0 and has the same code; I am reporting it there as well.

## Reproduction

`Repro.java` in the same directory; `RelateNG.relate` on JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd:

```java
Geometry b = rdr.read("LINESTRING (10 10, 11 11)");

// nested squares: no vertex of the first polygon is on the collection's boundary
Geometry a = rdr.read("GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))");
RelateNG.relate(a, b);    // FF2FFF102, expected FF2FF1102
RelateNG.relate(b, a);    // FF1FF02F2, expected FF1FF0212
// the two polygons in the other order: FF2FF1102 (correct)

// overlapping squares: the first square's first vertex (1 1) is inside the second square
Geometry a2 = rdr.read("GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))");
RelateNG.relate(a2, b);   // FF2FFF102, expected FF2FF1102
RelateNG.relate(b, a2);   // FF1FF02F2, expected FF1FF0212
// the two polygons in the other order: FF2FF1102 (correct)
```

In both cases A is the union of the two squares. Its boundary, the outline of the union, lies far from B, so Boundary(A) ∩ Exterior(B) has dimension 1. JTS 1.20.0 gives the same results. All inputs are valid. The named predicates are not affected, because I/E = 2 is always recorded. The matrix and pattern evaluation are affected.

## Analysis and fix

`computeAreaVertex(geom, isA, ring, ...)` (RelateNG.java:506-516) returns `locTarget == EXTERIOR` whatever the vertex's own location. The skip in `computeAreaVertex(geom, isA, geomTarget, ...)` (RelateNG.java:485-488) fires after the first such vertex. `addAreaVertex` records B/E, and E/E, only when `locArea == BOUNDARY`. A boundary vertex in the exterior records every entry a further known-exterior polygon can add, so the skip is safe only after one. The fix mirrors #1200: have `computeAreaVertex(ring)` return `locArea` when the vertex is in the target exterior (else `Location.NONE`), and skip only once a `BOUNDARY` vertex has been seen.

The TODO at line 507 (*"use extremal (highest) point to ensure one is on boundary of polygon cluster"*) already anticipates that the tested vertex may not be on the boundary. Choosing a better vertex per ring would fix the overlapping-squares case. It would not fix the nested case: no vertex of the small square is on the boundary, and the big square, which carries the boundary, is the one that gets skipped. So the skip itself needs to change, or at least one boundary vertex must be tested before any polygon is skipped.

I made the same change in GEOS, where the code is identical, and checked it with 3000 random GeometryCollection cases against exact answers. On JTS master, which has #1200, 45 of these cases lose BE or EB this way. In GEOS with #1200 ported and this change applied, none of them do, and no other answer changes. The GEOS patch is `patch/area-vertex-skip.diff` in this directory. It must be applied on top of the GEOS port of #1200 (`patch/port-jts-1200.diff`), because it uses the `Location` alias that the port adds.

## Related

- #1175 / #1200: the same flaw in `computeLineEnds`, fixed on master.
- I am reporting separately a related GeometryCollection problem: parts of the union boundary of overlapping polygons are never evaluated. It concerns the same TODO. Its first suggested step, using a ring vertex that is on the union boundary, fixes the overlapping-squares case above but not the nested one. The two changes are complementary, and it may be easiest to review them together.
- I searched open and closed issues for RelateNG, computeAreaVertex, GeometryCollection relate and overlapping polygons, and found no report of this variant.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
