# RelateNG (master, since #1099): a linear or GeometryCollection B is not self-noded when A is polygonal, giving wrong relate/contains/touches/covers/within

## Summary

#1099 (c3d56e6, "Fix RelateNG to cache in prepared A-L cases") changed `TopologyComputer.isSelfNodingRequired()` to consult only A's flag and `B.hasAreaAndLine()`. Its comment says *"if A is polygonal then predicates with linear B do not require self-noding"* (TopologyComputer.java:137-138). That does not hold. When B meets itself on A's boundary, or when A's rings touch each other and B runs along the touched edge, the nodes lack sections, and `RelateNG.relate` returns wrong matrices. Some named predicates are also wrong. JTS 1.20.0 (before #1099) is correct on all cases below. The change is not in a JTS release yet. GEOS ported it in 3.13.1 (GH-1201).

## Reproduction

`Repro.java` uses `RelateNG.relate(a, b)` and `RelateNG.relate(a, b, RelatePredicate.x())`. Output on master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd:

| case | A | B | expected | master |
|---|---|---|---|---|
| 1 | `POLYGON ((0 0, 2 0, 1 1, 0 0))` | `MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))` | `FF210F102` | `FF2101102` |
| 3 | `POLYGON ((0 0, 2 0, 1 1, 0 0))` | `LINESTRING (0 0, 2 0, 1 1, 0 0, 1 -1, 1 0)` | `FF210F1F2` | `FF21011F2` |
| 4 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `LINESTRING (0 0, 4 0)` | contains false, touches true | contains **true**, touches **false** |
| 5 | `MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))` | `LINESTRING (0 2, 2 2)` | covers true | covers **false** |
| 6 | `POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))` | within true | within **false** (`contains(B, A)` is true) |

The expected answers:

- **Cases 1 and 3.** B contains all of A's boundary, so BE = F. With the operands swapped, the linear A is self-noded and the matrix is right.
- **Case 4.** B is the shell's bottom edge, so it lies on A's boundary.
- **Case 5.** B is part of A's boundary.
- **Case 6.** A lies inside the union of B's polygons.

The default `Geometry.relate` (RelateOp) is right on cases 1-5.

## Analysis

With A polygonal, `computeEdgesMutual` intersects only A×B segments.

- **Case 1.** The node at (1 0) comes from A's edge and B's segment (1 0)-(1 -1). B's ring edge along A's edge overlaps it collinearly, which yields only (0 0) and (2 0). So the node has no section for B's ring, and A's edge halves at (1 0) are labelled B-exterior.
- **Cases 4 and 5.** The node at A's own ring touch gets no section for the ring whose edge passes through it. This is the same mechanism as the polygon/polygon ring-touch problem, which I am reporting separately. Before #1099 it was hidden for a linear B, because B's flag forced full noding.
- **Case 6.** The flag of B, a GC of overlapping polygons, is ignored.

Restoring `|| geomB.isSelfNodingRequired()` fixes all cases. I checked this in GEOS, with random sweeps against exact answers. It loses the caching gain of #1099, though. Self-noding only B while keeping A's cached index might keep both.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
