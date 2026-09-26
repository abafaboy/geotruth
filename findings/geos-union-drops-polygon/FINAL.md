**Same root cause as #1405, fixed by #1499 in GEOS 3.15.0. A backport to 3.14 / 3.13 may be worth considering.**

I think this is the same bug as #1405. #1405 was closed by #1499 (commit 737737dbb), which is in 3.15.0rc1 and 3.15.0. The two polygons here share the vertex V = (-295.25030351249666 4.236074061427525). Their next vertices differ by one ulp in y: -2.301948231163383 in poly1 and -2.3019482311633825 in poly2. In double precision, the direction vectors from V to those two vertices both come out as (0.16319117031332553, -6.538022292590908). So `HalfEdge::compareAngularDirection` says the two edges point the same way, although the exact cross product is about 7.2e-17, not 0. The edge order around V then depends on insertion order. On 3.14.1 the result is as if one polygon lay inside the other: union returns poly2 alone, and intersection returns all of poly1. With this issue's input, 3.15.0 and current main give the correct result.

**Minimal reproducer** (two triangles, `geosop`):

```sh
A='POLYGON ((1 1, -1e-20 0, 1 0, 1 1))'
B='POLYGON ((0 0, 1 1, 0 1, 0 0))'
geosop -a "$A" -b "$B" union
geosop -a "$A" -b "$B" intersection
geosop -a "$B" -b "$A" difference
```

Both inputs are valid. B is the triangle on and above y = x. A lies below the line from (-1e-20, 0) to (1, 1), which runs above the diagonal by at most 1e-20. The triangles therefore overlap only in a needle of area about 5e-21. So the union should have area about 1, the intersection should be the needle, and B - A should be almost all of B. The tie is at node (1, 1): the edge towards (0, 0) and the edge towards the noded point (0, 1e-20) both have direction (-1, -1) in double, because `1e-20 - 1.0 == -1.0`.

| | GEOS 3.14.1 (wrong) | GEOS 3.15.0 and main (correct) |
|---|---|---|
| union | `POLYGON ((1 1, 1 0, 0 0, -1e-20 0, 0 1e-20, 1 1))`: just A, area 0.5 | `POLYGON ((0 0, -1e-20 0, 0 1e-20, 0 1, 1 1, 1 0, 0 0))`: area 1 |
| intersection | `POLYGON ((0 0, 0 1e-20, 0 1, 1 1, 0 0))`: all of B | `POLYGON ((0 1e-20, 1 1, 0 0, 0 1e-20))`: the needle |
| B - A | `POLYGON EMPTY` | `POLYGON ((0 1e-20, 0 1, 1 1, 0 1e-20))` |

**Input from this issue** (A = poly1, B = poly2). The exact answer: the two polygons touch only at V, so the union area is the sum of the two areas.

| | exact | GEOS 3.14.1 | GEOS 3.15.0 and main |
|---|---|---|---|
| area(union) | 255.86224744045356 | 127.93112372022679 (B alone) | 255.86224744045359 |
| intersection | the point V | polygon A (area 127.93112372022679) | `POINT (-295.25030351249666 4.236074061427525)` |
| A - B | A | `POLYGON EMPTY` | A |

These come from `geosop -a "$A" -b "$B" union | geosop -a stdin area`, and likewise for the other operations. Shapely 2.1.2, which bundles GEOS 3.13.1, gives the same wrong results on both inputs.

**Versions tested** (2026-09-26; all GEOS versions built from source except the Shapely wheel):

- Wrong: 3.13.1 (Shapely 2.1.2 wheel), 3.14.1 (`c389f532d`), and `da4de475f` (the parent of 737737dbb).
- Correct: `737737dbb` (#1499), 3.15.0 (`d0228513a`), and main `ae9cdd98b` (the current head).
- Not yet fixed: the `3.14` branch (`7db6f62d5`) and the `3.13` branch (`fbe9180f7`) still have the old test at `src/edgegraph/HalfEdge.cpp:188`.

**Cause.** `HalfEdge::compareAngularDirection` (`src/edgegraph/HalfEdge.cpp:180-208` in 3.14.1) computes `dx` and `dy` in floating point. At line 188 it returns 0 when both pairs are equal (`if (dx == dx2 && dy == dy2)`). That happens before the exact `Orientation::index` test at line 207. OverlayNG orders each node's edge star with this comparison: `OverlayGraph::insert` (`src/operation/overlayng/OverlayGraph.cpp:145-158`) calls `HalfEdge::insert` (`HalfEdge.cpp:81`), which calls `insertionEdge` (`HalfEdge.cpp:99-131`), which calls `compareTo`, which calls `compareAngularDirection`. On a tie, `insertionEdge` can put the new edge on either side of the tied edge. #1499 compares `directionPt()` with `equals2D()` instead, so the comparison returns 0 only when the direction points are identical.

**Backport.** 737737dbb cherry-picks without conflicts onto `3.14` and `3.13`.

- With the whole commit cherry-picked onto `3.14` (`7db6f62d5`), `ctest` passes 508 of 508 tests. That includes the cases #1499 adds to `EdgeGraphTest` and `OverlayNGRobustTest`. Both inputs above then give the correct result.
- Applying only the `HalfEdge.cpp` hunk to 3.14.1 also fixes both inputs. For union, intersection, both differences and symDifference, in both argument orders, the output matches 3.15.0 after `normalize()`; a few outputs start at a different vertex.
- I did not run the test suite on `3.13`.

Both branches have unreleased NEWS sections (3.14.2 and 3.13.2), so the fix could go into those releases if you think it is worth it. If you agree this is the same bug, this issue could be closed as fixed in 3.15.0.

**Related:**

- #1405 (closed) and its fix, #1499.
- shapely/shapely#2368: where this issue came from (open).
- shapely/shapely#2426: the Shapely report of #1405 (open).
- JTS has the same code. locationtech/jts#1224 ports the fix to JTS master, and locationtech/jts#1226 is a follow-up. JTS 1.20.0, the latest release, gives the same wrong union and intersection for this issue's input with `OverlayNGRobust`. JTS master (`3ea61f8`) gives the correct result.

<sub>Found by differential testing against an exact rational-arithmetic oracle ([geotruth](https://github.com/abafaboy/geotruth)). The exact values above were checked with two independent exact implementations.</sub>
