# RelateNG: wrong polygon/polygon predicates when a crossing point rounds onto a vertex (`touches` instead of `overlaps`, `contains` instead of `overlaps`)

*Draft for libgeos/geos. JTS RelateNG gives the same results; see "JTS" below.*

## Summary

Since 3.13, GEOS evaluates predicates with RelateNG. For two valid polygons, RelateNG can return a wrong DE-9IM matrix, and wrong `touches`, `overlaps`, `contains` and `covers` results, when a vertex of one polygon is within rounding distance of an edge of the other. The trigger is that the computed intersection point of the two crossing segments rounds exactly onto that vertex.

GEOS 3.11.4 (the old RelateOp) returns the correct answer on every input below. So do JTS's default `Geometry.relate` (RelateOp) and GEOS's own point predicates on the same vertex.

## Minimal reproduction

Both cases use the same triangle A, whose hypotenuse lies on the line y = x/3. B is a triangle with one vertex P that sits 3.7e-17 (vertically) off that line.

```
A = POLYGON ((0 0, 3 0, 3 1, 0 0))

# Case 1: P = (2 0.6666666666666666) lies just inside A
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))' relate
FF2F01212                     # expected 212101212
  touches -> true (expected false), overlaps -> false (expected true)
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POINT (2 0.6666666666666666)' contains
true                          # GEOS itself agrees that B's vertex P is in A's interior

# Case 2: P = (2.5 0.8333333333333334) lies just outside A
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))' relate
212F01FF2                     # expected 212101212
  contains -> true, covers -> true (expected false), overlaps -> false (expected true)
$ geosop -a 'POLYGON ((0 0, 3 0, 3 1, 0 0))' -b 'POINT (2.5 0.8333333333333334)' intersects
false                         # GEOS itself agrees that B's vertex P is outside A
```

All four polygons are valid (`GEOSisValid` returns true, and so does an exact rational check). They are simple CCW triangles with small coordinates.

`repro.c` (public C API only; build with `cc repro.c $(geos-config --cflags) $(geos-config --clibs)`) checks `GEOSRelate`, `GEOSTouches`, `GEOSOverlaps`, `GEOSContains`, `GEOSCovers`, the prepared variants and the point tests. Its output:

| | GEOS 3.13.1 / 3.14.1 / 3.15.0 / main | GEOS 3.11.4 |
|---|---|---|
| case 1 `relate(A,B)` | `FF2F01212`, touches = true, overlaps = false, prepared touches = true | `212101212` (correct) |
| case 2 `relate(A,B)` | `212F01FF2`, contains = covers = true, overlaps = false | `212101212` (correct) |

In case 2, `GEOSPreparedContains`/`GEOSPreparedCovers` return the correct `false`, and `GEOSPreparedOverlaps` is wrong.

## Why the expected answers are right

Two lines of reasoning, each checkable by hand:

1. **Exact position of P.** A is the region 0 ≤ y ≤ x/3, x ≤ 3.
   - The double `0.6666666666666666` equals 6004799503160661/2^53 = 2/3 − 1/(3·2^53). It is below the line y = x/3 at x = 2, so P is in the interior of A. P is a vertex of B, so B's boundary passes through A's interior. That makes the interiors intersect (II = 2), so `touches` must be false and `overlaps` true.
   - The double `0.8333333333333334` equals 7505999378950827/2^53 = 5/6 + 1/(3·2^53). It is above the line at x = 2.5, so P is outside A, and A cannot contain or cover B.
2. **Consistency with GEOS's own point predicates.** In case 1, GEOS says A contains P, and P is a point of B. A polygon B that has a point in A's interior cannot merely *touch* A. In case 2, GEOS says P does not intersect A, yet P is a point of B. So A cannot *contain* B.

The exact matrix is `212101212` in both cases. The exact overlap areas are tiny but nonzero:
- case 1: area(A ∩ B) = 1/2433889152438200504916865682767872 ≈ 4.1e-34
- case 2: area(B − A) = 1/1460333491462920378610593149485056 ≈ 6.8e-34

Two independent exact-rational implementations agree on all of these values.

The GEOS FAQ ("Why doesn't a computed point lie exactly on a line?") describes these semantics: predicates are evaluated on the double coordinates as given, not with a tolerance. The RelateNG docs list a distance tolerance only as future work.

**The answer also depends on the ring's start vertex**, which an intentional tolerance would not do. Rotating B's ring so that it starts at P changes the result, although the matrix is still not the exact one:

```
B = POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))                     relate=FF2F01212  touches=true
B = POLYGON ((2 0.6666666666666666, 2 2, 1 2, 2 0.6666666666666666))    relate=212F01212  touches=false
B = POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))         relate=212F01FF2  contains=true
B = POLYGON ((2.5 0.8333333333333334, 2.5 0.5, 3 0.5, 2.5 0.8333333333333334))  relate=212F01212  contains=false
```

This follows from `RelateNG::computeAreaVertex` locating only the first coordinate of each ring (RelateNG.cpp:619-622).

## Versions

- GEOS `main` at ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (3.16.0dev, 2026-09-21): wrong
- GEOS 3.15.0 and 3.14.1 (built from source), and 3.13.1 (Shapely 2.1.2 wheel): wrong
- GEOS 3.11.4 (Shapely 2.0.7 wheel, pre-RelateNG): correct. 3.12 was not tested.
- Linux x86-64, gcc 13.3

**JTS** (`Repro.java`, public API): master 3ea61f8 and 1.20.0 give the same wrong matrices through `RelateNG.relate`. In JTS, `RelateNG.prepare(A).evaluate(B, contains())` is also wrong (true) in case 2. `Geometry.relate`, which still defaults to RelateOp in JTS, is correct.

## Analysis

`LineIntersector` has the exact answer, but RelateNG throws it away:

- `LineIntersector::computeIntersect` decides that the segments cross properly from `Orientation::index` signs (LineIntersector.h:345-353). It sets `isProperVar = true` and then *computes* the point (LineIntersector.h:451-452). In both cases, both of B's edges at P properly cross A's hypotenuse, and both computed intersection points round to P exactly. (`rootcause_diag.cpp` shows this with GEOS's C++ classes: `isProper() = 1`, and the intersection point equals B's vertex.)
- `EdgeSegmentIntersector::addIntersections` (EdgeSegmentIntersector.cpp:81-103) uses `li.isProper()` only to decide whether to add the node.
- `RelateSegmentString::createNodeSection` then recomputes properness from the rounded point: `isNodeAtVertex = intPt.equals2D(c0) || intPt.equals2D(c1)` (RelateSegmentString.cpp:78). `NodeSection::isProper()` is `!isNodeAtVertex` (NodeSection.cpp:144).
- Here the rounded point equals P, so B's section is treated as a vertex node. `TopologyComputer::updateAreaAreaCross` (TopologyComputer.cpp:261-270) then falls back to `PolygonNodeTopology::isCrossing` at P. P is not exactly on A's edge, and B's two neighbouring vertices lie in the same angular sector between A's two edge rays at P, so in both cases the call returns false. The node evaluation at P then sees B's wedge wholly outside A (case 1) or wholly inside A (case 2). The two real crossings, and the tiny triangle between them, are lost.

The old `RelateComputer` handled this case with `computeProperIntersectionIM`, which sets at least `212101212` for area/area inputs whenever `LineIntersector` reports a proper intersection (RelateComputer.cpp:246-261).

The same mechanism can also merge two distinct proper crossings into one computed node, for example on a sliver or spike. It explains all 29 wrong-predicate cases among 20,000 generated valid polygon pairs (see "How this was found").

**Prototype.** I tried a small change in JTS (`prototype_jts_relateng.diff`). When `li.isProper()` holds for an A-area segment and a B-area segment, it records II = 2. For Polygon/MultiPolygon inputs (not GCs, where union semantics make this unsound), it records the full `212101212` lower bound, as RelateOp did. Results:
- It fixes both cases above and all 29 corpus cases.
- It introduces no new disagreement with the exact oracle on the 20,000-case corpus.
- It changes two existing expectations in `RelateNGRobustnessTest`, `testPostGIS_5362` and `testGISSE_484691`. Both assert `2F2101212`; the prototype returns `212101212`.

For both of those test inputs, the exact matrix is `212101212`: the polygons overlap by areas of 1.2e-21 and 4.1e-33. `2F2101212` cannot occur for two valid polygons: II = 2 and IE = 2 with a connected interior of A force IB ≠ F. GEOS 3.11.4 also returns `212101212` for the PostGIS 5362 input. I'm not proposing this as the fix; it only shows where the information is lost. A maintainer may prefer a different approach.

## Related issues

- #1018 "Two polygons that only touch result in overlaps=True" (closed). With the coordinates from that issue, the exact matrix is `212101212`: the polygons overlap by an area of about 6e-19. GEOS 3.11.4 returned that, and the reporter expected `FF2F11212`. GEOS 3.13.1 and main now return `2F2F01212`, which cannot occur for valid polygons.
- #1026, PostGIS #5362, and GIS.SE 484691: the robustness tests mentioned above.
- #740 and #968, and locationtech/jts#1106 (point/line orientation robustness summary). These are related to robustness, but they are about inputs that are only *intended* to lie on a line. Here, GEOS's point predicates are already exact, and only the polygon/polygon path disagrees with them.

I did not find an existing report of this specific behaviour.

## How this was found

This was found by differential testing against an exact rational-arithmetic oracle, over generated valid polygon pairs whose vertices lie a few ulps off the other polygon's edges. A second, independently written exact implementation checked every expected value. Everything above was re-run on the builds listed in "Versions".
