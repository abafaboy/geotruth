# RelateNG.computeAreaVertex: the known-exterior skip loses Boundary/Exterior for GeometryCollections (same flaw as #1175)

## Summary

#1200 fixed `RelateNG.computeLineEnds` (#1175). `RelateNG.computeAreaVertex` still has the same optimisation: once one ring vertex has been found in the target's exterior, polygons whose envelope is disjoint from the target are skipped. In a GeometryCollection, the tested vertex (the ring's first vertex) can lie inside another polygon of the collection. `TopologyComputer.addAreaVertex` then records only Interior/Exterior, and does not record Boundary/Exterior. The polygons skipped after it are the ones that carry the collection's boundary, so `relate` returns BE (or EB) = `F` instead of `1`. The result depends on element order.

## Reproduction

`Repro.java` in the same directory; `RelateNG.relate` on JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd:

```java
Geometry a = rdr.read("GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))");
Geometry b = rdr.read("LINESTRING (10 10, 11 11)");
RelateNG.relate(a, b);   // FF2FFF102, expected FF2FF1102
RelateNG.relate(b, a);   // FF1FF02F2, expected FF1FF0212
// the two polygons in the other order: FF2FF1102 (correct)
```

A is the union of two overlapping squares. Its boundary, the outline of the union, lies far from B, so Boundary(A) ∩ Exterior(B) has dimension 1. JTS 1.20.0 gives the same results. The named predicates are not affected, because I/E = 2 is always recorded. `relate` and `relate(pattern)` are affected.

## Analysis and fix

`computeAreaVertex(geom, isA, ring, ...)` (RelateNG.java:506-516) returns `locTarget == EXTERIOR` whatever the vertex's own location. The skip in `computeAreaVertex(geom, isA, geomTarget, ...)` (RelateNG.java:485-488) fires after the first such vertex. `addAreaVertex` records B/E, and E/E, only when `locArea == BOUNDARY`. A boundary vertex in the exterior records every entry a further known-exterior polygon can add, so the skip is safe only after one. The fix mirrors #1200: have `computeAreaVertex(ring)` return `locArea` when the vertex is in the target exterior (else `Location.NONE`), and skip only once a `BOUNDARY` vertex has been seen. The TODO at line 507 (*"use extremal (highest) point to ensure one is on boundary of polygon cluster"*) points at the same issue.

I made the same change in GEOS, where the code is identical, and checked it with 3000 random GeometryCollection cases against exact answers. It removes all 65 disagreements of this kind and changes nothing else. The GEOS patch is `patch/area-vertex-skip.diff` in this directory. It applies on top of the GEOS port of #1200 (`patch/port-jts-1200.diff`).

## Related

- #1175 / #1200: the same flaw in `computeLineEnds`, fixed on master.
- I searched open and closed issues for RelateNG, computeAreaVertex, GeometryCollection relate and overlapping polygons, and found no report of this variant.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
