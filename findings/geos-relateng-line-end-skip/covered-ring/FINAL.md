# RelateNG regression in 3.13.1 (GH-1201): a linear or GeometryCollection operand B is no longer self-noded when A is polygonal

## Summary

GH-1201 ported JTS #1099 to make prepared RelateNG cache A's noder in area/line cases. It changed `TopologyComputer::isSelfNodingRequired()` from `A.isSelfNodingRequired() || B.isSelfNodingRequired()` to `A.isSelfNodingRequired() || B.hasAreaAndLine()`. The change was backported to the 3.13 branch, so it is in 3.13.1 and later. When A is polygonal, a MultiLineString, a self-touching LineString, or a GeometryCollection of polygons as B is now intersected only against A's segments, never against itself. Nodes where B meets itself on A's boundary, or where A's own rings touch, then lack node sections, and the edges there get the wrong side labels. The results:

- **relate matrix.** `relate(polygon, lines)` reports Boundary(A) ∩ Exterior(B) = 1 when the lines cover the polygon's boundary. Swapping the operands gives the correct transposed matrix.
- **named predicates.** `contains`/`touches` are wrong for a polygon whose hole touches its shell, tested against the shell edge. `covers` is wrong for a MultiPolygon whose parts touch, tested against the touched edge. `within` is wrong for a polygon inside the union of a GeometryCollection of overlapping polygons.

GEOS 3.13.0 returns the correct answer for every case below. JTS master has the same change and the same results. JTS 1.20.0 predates the change and is correct.

## Minimal reproduction

All inputs are valid (`GEOSisValid` = 1). `repro.c` uses only the C API (`cc repro.c $(geos-config --cflags) $(geos-config --clibs)`). Output on `main`:

| case | A | B | expected | `main` |
|---|---|---|---|---|
| 1 | `POLYGON ((0 0, 2 0, 1 1, 0 0))` | `MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))` | `FF210F102` | `FF2101102` |
| 1, `GEOSRelatePattern(A, B, "*****F***")` | | | 1 | 0 |
| 1, operands swapped | B | A | `F11F002F2` | `F11F002F2` (correct) |
| 1 with (1 0) added as a vertex of B's ring | | | `FF210F102` | `FF210F102` (correct) |
| 2 | `POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))` | `MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 -1))` | `FF210F102` | `FF2101102` |
| 3 | `POLYGON ((0 0, 2 0, 1 1, 0 0))` | `LINESTRING (0 0, 2 0, 1 1, 0 0, 1 -1, 1 0)` | `FF210F1F2` | `FF21011F2` |
| 4 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `LINESTRING (0 0, 4 0)` | `FF2101FF2`: contains false, touches true | `1F2101FF2`: **contains true, touches false** |
| 5 | `MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))` | `LINESTRING (0 2, 2 2)` | `FF2101FF2`: covers true | `FF21011F2`: **covers false** |
| 6 | `POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))` | `2FF11F212`: within true | `212111212`: **within false** (while `contains(B, A)` is true) |

`GEOSPreparedRelate`, `GEOSPreparedContains`, `GEOSPreparedTouches` and `GEOSPreparedCovers` give the same wrong answers.

The expected answers can be checked by hand:

1. **Cases 1-3.** B contains A's whole boundary ring, so Boundary(A) \ B is empty and BE = F. In case 1, `GEOSCovers(B, GEOSBoundary(A))` returns 1.
2. **Case 4.** B is the bottom edge of A's shell. It lies on A's boundary, so it cannot meet A's interior: contains is false, and the two touch.
3. **Case 5.** B is the top edge of the square. It is part of A's boundary, so A covers B.
4. **Case 6.** A lies in the union of B's two polygons, so A is within B. GEOS also says `contains(B, A)` is true, and `difference(A, B)` has area 0.

## Versions

| GEOS | result |
|---|---|
| `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (2026-09-21, still the head on 2026-09-26) | wrong (cases 1-6) |
| 3.15.0 (d0228513) | wrong |
| 3.14.1 (Shapely 2.2.0rc1 wheel), 3.13.1 (Shapely 2.1.2 wheel) | wrong |
| **3.13.0** (d7957246, built from source): before GH-1201 | **correct** |
| 3.11.4 (Shapely 2.0.7 wheel, RelateOp) | correct on 1-5. Case 6 throws `TopologyException` (old RelateOp and GCs) |

JTS: master 3ea61f8 is wrong on 1-6. 1.20.0 (released before #1099) is correct on 1-6.

## Analysis

Line numbers are for `main` ae9cdd9.

1. `TopologyComputer::isSelfNodingRequired()` (src/operation/relateng/TopologyComputer.cpp:133-146) has read, since b0cec404 (GH-1201; 3.13 backport 782bec07):
   ```cpp
   if (geomA.isSelfNodingRequired()) return true;
   if (geomB.hasAreaAndLine()) return true;   //-- B's own flag is no longer consulted
   return false;
   ```
   `RelateGeometry::isSelfNodingRequired()` (RelateGeometry.cpp:239-253) is false for Polygon and MultiPolygon. It is true for lines and for GCs with more than one element. So for a polygonal A and a linear or multi-polygon-GC B, `RelateNG::computeAtEdges` (RelateNG.cpp:645-649) now takes `computeEdgesMutual`, which intersects A segments with B segments only.
2. **Case 1.** At (1 0), A's edge (0 0)-(2 0) meets B's segment (1 0)-(1 -1), so a node is created there. It gets sections for A's edge and for that B segment. B's ring edge (0 0)-(2 0) is collinear with A's edge, and a collinear intersection reports only (0 0) and (2 0). So the node has no section for B's ring, and the two halves of A's edge at (1 0) are labelled B-exterior. That gives BE = 1. Inserting (1 0) as a vertex of B's ring, or swapping the operands (a linear A is self-noded), gives the correct answer.
3. **Cases 4 and 5.** The node at A's own ring touch, (2 0) or (1 2), gets no section for the ring whose edge passes through it. This is the same mechanism as a separate report on polygon/polygon inputs ("RelateNG: wrong relate/predicates when a ring vertex lies inside another ring's edge"), which fails in every RelateNG release. For a *linear* B, 3.13.0 self-noded both inputs because B's flag was consulted, which created those sections. Since GH-1201 the polygon/line cases fail as well.
4. **Case 6.** B is a GC of overlapping polygons. B's flag is true, but it is ignored, so B's polygons are never noded against each other. This gives the same wrong labelling as when such a GC is operand A and not self-noded.

**An experiment.** I restored the old condition by also returning true when `geomB.isSelfNodingRequired()` (see `experiment-self-node-linear-b.diff`). This fixes all six cases. It also fixes every disagreement of these kinds in two random sweeps checked against exact answers: 725 of 3000 polygon-vs-lines cases, and 7 of 3000 GC cases. Nothing else changes. GEOS's XML tests (171) and the RelateNG unit tests (155) still pass with it. It would undo the prepared-mode speed-up of GH-1201, though, so I am not proposing it as the fix. Two alternatives:

- Self-node only B, adding B×B intersections, when B requires it, while still querying A's cached index.
- Restrict the fast path to B inputs that cannot meet themselves. A single simple LineString is enough for the matrix: a single LineString B with a self-touch, as in case 3, already fails.

For `contains`/`covers`/`intersects`-style predicates that only need part of the matrix, a narrower rule may be enough. But `relate` itself and the patterns in cases 4-6 need the nodes.

## Related issues

- GH-1201 and locationtech/jts#1099: the change, which was made as a performance improvement for prepared A/L predicates. JTS's comment on `TopologyComputer.isSelfNodingRequired` (TopologyComputer.java:137-138 on master) states *"if A is polygonal then predicates with linear B do not require self-noding"*. Cases 1-5 are counterexamples.
- The separate RelateNG ring-touch report (polygon/polygon) shares cases 4-5's mechanism. Its polygon/polygon cases also fail on 3.13.0, since neither flag is set for two polygons. Fixing it would fix cases 4-5 but not 1-3 or 6.
- #1275 (closed, "Relate(g1, g2, pattern) returning different results depending on prepared state"): it has no reproducer, and I cannot tell whether it is related.
- I searched libgeos/geos and locationtech/jts issues and PRs, open and closed, for: RelateNG self-noding, relate polygon multilinestring, boundary exterior, contains/covers/within with a GeometryCollection, and 3.13.1 regression. I found no report of this regression.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
