# RelateNG: valid polygons reported as touching or containing instead of overlapping when a proper crossing point rounds onto a vertex

## Summary

Since GEOS 3.13, RelateNG evaluates polygon/polygon predicates. It can return a wrong DE-9IM matrix, and wrong `touches`, `overlaps`, `contains`, `covers`, `within` and `coveredBy` results, for two small valid triangles. The trigger is a vertex P of B that lies about 3.7e-17 off an edge of A. Both of B's edges at P cross A's edge properly, and `LineIntersector` reports them as proper. However, the computed intersection point rounds exactly to P. RelateNG then decides whether the crossing is proper by comparing that rounded point with the segment endpoints, so it treats both crossings as a touch at B's vertex. The results are:

- `touches` = true instead of `overlaps`, when P is inside A.
- `contains`/`covers` = true instead of `overlaps`, when P is outside A. With the arguments swapped, `within`/`coveredBy` = true.

GEOS 3.11.4 (RelateOp) returns the exact answer, `212101212`, for both inputs, and so does JTS's default `Geometry.relate`.

## About the documented round-off caveat

The RelateNG package docs in JTS, which GEOS ports, say ([package-info.java#L64-L70](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/package-info.java#L64-L70)):

> This means that invalid input geometries or numerical round-off do not cause exceptions (although they may return incorrect answers).

I think this case is still worth fixing, for these reasons:

- **The inputs are valid and are used as given.** No computed geometry is passed back in. `LineIntersector` decides that the crossing is proper using exact orientation tests, and RelateNG then discards that result.
- **This is a regression.** RelateOp uses the same proper-intersection flag to set a `212101212` lower bound, so GEOS 3.11.4 and JTS's default `Geometry.relate` return the exact answer.
- **GEOS contradicts its own point predicates.** In case 1, GEOS says A contains B's vertex P but reports that A only touches B. In case 2, GEOS says P does not intersect A but reports that A contains B.
- **The result depends on the ring's start vertex.** Rotating B's ring so that it starts at P changes the matrix (see below).
- **Prepared and non-prepared results disagree.** In case 2, `GEOSContains` returns true and `GEOSPreparedContains` returns false.
- **The existing tests assert impossible matrices.** For two inputs (PostGIS ticket 5362 and GIS.SE 484691), `RelateNGRobustnessTest` asserts `2F2101212`, a matrix that two valid polygons cannot have (details under "Related issues"). The prototype below changes both to the exact `212101212`, which suggests the same information loss.

## Reproducer

```
A  = POLYGON ((0 0, 3 0, 3 1, 0 0))                               -- 0 <= y <= x/3, x <= 3
B1 = POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))              -- case 1: vertex P just inside A
B2 = POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))  -- case 2: vertex P just outside A
```

A and both B triangles are valid (`GEOSisValid` returns true, and an exact rational check agrees). This is GEOS `main` (ae9cdd9), run now:

```
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))' relate
FF2F01212
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))' touches
true
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POINT (2 0.6666666666666666)' contains
true
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))' relate
212F01FF2
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))' contains
true
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POINT (2.5 0.8333333333333334)' intersects
false
$ geosop -a 'POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))' -b 'POLYGON ((0 0, 3 0, 3 1, 0 0))' within
true
```

The same check through Shapely:

```python
from shapely import from_wkt
A  = from_wkt("POLYGON ((0 0, 3 0, 3 1, 0 0))")
B1 = from_wkt("POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))")
B2 = from_wkt("POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))")
print(A.relate(B1), A.touches(B1), A.overlaps(B1))   # 3.13.1/3.14.1: FF2F01212 True False   3.11.4: 212101212 False True
print(A.relate(B2), A.contains(B2), A.overlaps(B2))  # 3.13.1/3.14.1: 212F01FF2 True False   3.11.4: 212101212 False True
```

## Expected vs actual

Expected, for both cases: `relate(A,B) = 212101212`, `overlaps` = true, and `touches` = `contains` = `covers` = `within(B,A)` = false.

<details><summary>Actual output of a small public C API program (source below), on GEOS main ae9cdd9. 3.15.0 and 3.14.1 print the same lines.</summary>

Build: `cc repro.c $(geos-config --cflags) $(geos-config --clibs)`

```c
#include <stdio.h>
#include <geos_c.h>

int main(void) {
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    const char *wkt[][3] = {
        {"POLYGON ((0 0, 3 0, 3 1, 0 0))", "POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))", "POINT (2 0.6666666666666666)"},
        {"POLYGON ((0 0, 3 0, 3 1, 0 0))", "POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))", "POINT (2.5 0.8333333333333334)"}};
    printf("GEOS %s\n", GEOSversion());
    for (int i = 0; i < 2; i++) {
        GEOSGeometry *a = GEOSWKTReader_read_r(h, r, wkt[i][0]);
        GEOSGeometry *b = GEOSWKTReader_read_r(h, r, wkt[i][1]);
        GEOSGeometry *p = GEOSWKTReader_read_r(h, r, wkt[i][2]);
        const GEOSPreparedGeometry *pa = GEOSPrepare_r(h, a);
        char *im = GEOSRelate_r(h, a, b);
        printf("case %d: relate=%s touches=%d overlaps=%d contains=%d covers=%d within(B,A)=%d\n",
               i + 1, im, GEOSTouches_r(h, a, b), GEOSOverlaps_r(h, a, b), GEOSContains_r(h, a, b),
               GEOSCovers_r(h, a, b), GEOSWithin_r(h, b, a));
        printf("        prepared: touches=%d overlaps=%d contains=%d covers=%d\n",
               GEOSPreparedTouches_r(h, pa, b), GEOSPreparedOverlaps_r(h, pa, b),
               GEOSPreparedContains_r(h, pa, b), GEOSPreparedCovers_r(h, pa, b));
        printf("        isValid(A)=%d isValid(B)=%d intersects(B,P)=%d contains(A,P)=%d intersects(A,P)=%d\n",
               GEOSisValid_r(h, a), GEOSisValid_r(h, b), GEOSIntersects_r(h, b, p),
               GEOSContains_r(h, a, p), GEOSIntersects_r(h, a, p));
        GEOSFree_r(h, im);
        GEOSPreparedGeom_destroy_r(h, pa);
        GEOSGeom_destroy_r(h, a); GEOSGeom_destroy_r(h, b); GEOSGeom_destroy_r(h, p);
    }
    GEOSWKTReader_destroy_r(h, r);
    GEOS_finish_r(h);
    return 0;
}
```

```
GEOS 3.16.0dev-CAPI-1.22.0
case 1: relate=FF2F01212 touches=1 overlaps=0 contains=0 covers=0 within(B,A)=0
        prepared: touches=1 overlaps=0 contains=0 covers=0
        isValid(A)=1 isValid(B)=1 intersects(B,P)=1 contains(A,P)=1 intersects(A,P)=1
case 2: relate=212F01FF2 touches=0 overlaps=0 contains=1 covers=1 within(B,A)=1
        prepared: touches=0 overlaps=0 contains=0 covers=0
        isValid(A)=1 isValid(B)=1 intersects(B,P)=1 contains(A,P)=0 intersects(A,P)=0
```
</details>

| | GEOS 3.13.1, 3.14.1, 3.15.0, main | GEOS 3.11.4 |
|---|---|---|
| case 1 | `FF2F01212`: touches = true, overlaps = false. Prepared touches and prepared overlaps are also wrong. | `212101212` (correct) |
| case 2 | `212F01FF2`: contains = covers = true, overlaps = false. `within(B,A)` = true, and `relate(B,A)` = `2FF10F212`. Prepared overlaps is wrong. Prepared contains/covers return the correct false. | `212101212` (correct) |

**Ring start vertex.** The same point sets with B's ring rotated give different matrices (geosop, main):

```
B = POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))                              FF2F01212  touches=true
B = POLYGON ((2 0.6666666666666666, 2 2, 1 2, 2 0.6666666666666666))             212F01212  touches=false
B = POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))                  212F01FF2  contains=true
B = POLYGON ((2.5 0.8333333333333334, 2.5 0.5, 3 0.5, 2.5 0.8333333333333334))   212F01212  contains=false
```

## Why `212101212` is right (checkable by hand)

- `0.6666666666666666` is exactly 6004799503160661/2^53 = 2/3 − 1/(3·2^53). This is below the line y = x/3 at x = 2, so P is in A's interior.
  - B's edges from P go to (1 2) and (2 2), which are above the line. Both edges therefore cross A's edge at points strictly inside both segments.
  - The two crossings and P bound a triangle inside A∩B with area 1/2433889152438200504916865682767872 ≈ 4.1e-34.
- `0.8333333333333334` is exactly 7505999378950827/2^53 = 5/6 + 1/(3·2^53). This is above the line at x = 2.5, so P is outside A.
  - Both of B's edges at P cross A's edge properly.
  - area(B − A) = 1/1460333491462920378610593149485056 ≈ 6.8e-34.
- In both cases, all four interior/exterior combinations of A and B are non-empty, and the boundaries cross at two points. That gives `212101212`. Two independent exact rational implementations agree on these values.

## Versions tested

| Build | Result |
|---|---|
| GEOS `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (3.16.0dev), built from source | wrong |
| GEOS 3.15.0 (d0228513), built from source | wrong |
| GEOS 3.14.1 (c389f532), built from source and via the Shapely 2.2.0rc1 wheel | wrong |
| GEOS 3.13.1, via the Shapely 2.1.2 wheel | wrong |
| GEOS 3.11.4, via the Shapely 2.0.7 wheel | correct (3.12 not tested) |
| JTS master 3ea61f8 and JTS 1.20.0 | `RelateNG` gives the same wrong matrices; default `Geometry.relate` (RelateOp) is correct |

All builds ran on Linux x86-64 with gcc 13.3 and OpenJDK 21.

## Analysis

The line references below are for GEOS main at ae9cdd9.

1. `LineIntersector::computeIntersect` classifies the crossing using `Orientation::index` signs ([LineIntersector.h#L345-L353](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/include/geos/algorithm/LineIntersector.h#L345-L353)). For both of B's edges at P, it sets `isProperVar = true` and then computes the point in floating point ([#L451-L452](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/include/geos/algorithm/LineIntersector.h#L451-L452)).
   - A small diagnostic that uses these classes directly prints `isProper() = 1` for both edges, with an intersection point that is bit-identical to P.
2. `EdgeSegmentIntersector::addIntersections` uses `li.isProper()` only to decide whether to add the node ([EdgeSegmentIntersector.cpp#L97-L103](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/src/operation/relateng/EdgeSegmentIntersector.cpp#L97-L103)).
3. `RelateSegmentString::createNodeSection` recomputes properness from the rounded point, `isNodeAtVertex = intPt.equals2D(c0) || intPt.equals2D(c1)` ([RelateSegmentString.cpp#L78](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/src/operation/relateng/RelateSegmentString.cpp#L78)), and `NodeSection::isProper()` returns `!m_isNodeAtVertex` ([NodeSection.cpp#L144](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/src/operation/relateng/NodeSection.cpp#L144)).
   - Because the rounded point equals P, B's section is treated as a node at a vertex.
4. `TopologyComputer::updateAreaAreaCross` then falls back to `PolygonNodeTopology::isCrossing` at P ([TopologyComputer.cpp#L261-L270](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/src/operation/relateng/TopologyComputer.cpp#L261-L270)). This returns false in both cases (confirmed by the diagnostic). P is not exactly on A's edge, so the rays from P to A's segment endpoints do not separate B's two neighbouring vertices.
   - The node at P is then evaluated as B's wedge touching A from outside (case 1) or from inside (case 2). The two real crossings are lost, and so is the tiny region between them.
5. The ring-start dependence comes from `RelateNG::computeAreaVertex`, which locates only the first coordinate of each ring ([RelateNG.cpp#L619-L622](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/src/operation/relateng/RelateNG.cpp#L619-L622)). When that coordinate is P, its exact location is recorded.

The old `RelateComputer::computeProperIntersectionIM` calls `setAtLeast("212101212")` for area/area inputs whenever the segment intersector reports a proper intersection ([RelateComputer.cpp#L246-L261](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/src/operation/relate/RelateComputer.cpp#L246-L261)). That is why 3.11.4 gets these inputs right.

**Prototype (for illustration, not a proposed patch).** I made a two-file change to JTS RelateNG; the GEOS code has the same structure. When `li.isProper()` holds for an A-area segment and a B-area segment, it records II = 2. For Polygon/MultiPolygon inputs, it also records the RelateOp lower bound `212101212`. The diff is in the JTS issue (link below). Results:

- It fixes both cases above.
- A differential run against an exact oracle, over 20,000 generated valid polygon pairs, found 29 pairs with wrong predicates in GEOS 3.13.1, 3.14.1 and main, all correct in 3.11.4. The prototype fixes all 29 and introduces no new disagreement with the exact oracle.
  - Of the 29, 13 give `FF2F01212` (touches), 12 give `212F01FF2` (contains) and 4 give `2FF10F212` (within).
  - Because the prototype fixes all of them, I believe they share this cause.
- In the JTS RelateNG unit tests, only `RelateNGRobustnessTest.testPostGIS_5362` and `testGISSE_484691` change: from `2F2101212` to `212101212` (see below).

A maintainer may well prefer a different fix.

## Related issues

- **PostGIS [ticket 5362](https://trac.osgeo.org/postgis/ticket/5362) and [GIS.SE 484691](https://gis.stackexchange.com/questions/484691).** `RelateNGRobustnessTest` asserts `2F2101212` for both ([#L226](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/tests/unit/operation/relateng/RelateNGRobustnessTest.cpp#L226), [#L277](https://github.com/libgeos/geos/blob/ae9cdd98be4e0bae552b918d4d14c94a9ce99c58/tests/unit/operation/relateng/RelateNGRobustnessTest.cpp#L277)).
  - The exact matrix for both inputs is `212101212`: the polygons overlap by areas of about 1.2e-21 and 4.1e-33.
  - `2F2101212` cannot occur for two valid polygons: if A's connected interior meets both B's interior and B's exterior, it must meet B's boundary, so IB ≠ F.
  - The predicates on main are still correct here (`overlaps` = true, `touches` = false). Only the matrix is internally inconsistent.
  - For comparison, GEOS 3.11.4 returns `212101212` for PostGIS 5362 and throws a TopologyException for 484691.
- **#1018 "Two polygons that only touch result in overlaps=True" (closed).** With the coordinates as posted, the exact matrix is `212101212`, with an overlap of about 6e-19. 3.11.4 returned that.
  - 3.13.1 and main return `2F2F01212`, which is impossible for valid polygons for the same IB reason.
  - The predicates on main are still correct (`overlaps` = true, `touches` = false). Only the matrix is inconsistent.
  - The JTS prototype also returns `212101212` for this input.
- **#740, #968 and locationtech/jts#1106 (point/line orientation robustness).** These are related but different: they concern inputs that are only intended to lie on a line. Here the orientation tests are exact and already give the right answer, and RelateNG discards it.
- I searched open and closed GEOS and JTS issues and PRs (RelateNG, touches/overlaps/contains/covers, robustness, DE-9IM). I also read #1060, #1147, #1275 and locationtech/jts#1079, and found no existing report of this behaviour.
- JTS counterpart: locationtech/jts#____ (same inputs, same matrices in `RelateNG`).

---

This was found by differential testing against an exact rational-arithmetic oracle ([geotruth](https://github.com/abafaboy/geotruth)).
