**Title:** RelateNG segfaults on a GeometryCollection that contains an EMPTY element (`AdjacentEdgeLocator` size_t underflow; null `LinearBoundary` in `initExteriorEmpty`)

### Summary

Since GEOS 3.13, `relate` and the predicates crash with SIGSEGV when a GeometryCollection
operand contains an empty element. The inputs are valid: `GEOSisValid` returns true. There
are two separate crash sites:

1. A `POLYGON EMPTY` inside a GC, plus a point located on the boundaries of two of the GC's
   polygons. This crashes `GEOSIntersects`, `GEOSWithin`, `GEOSTouches`, `GEOSContains`,
   `GEOSRelate`, `GEOSRelatePattern` and the prepared predicates, in
   `AdjacentEdgeLocator::addSections`.
2. A `LINESTRING EMPTY` in a GC whose other elements are points, related to an empty
   geometry. This crashes `GEOSRelate`, in `LinearBoundary::hasBoundary` called on a null
   pointer.

GEOS 3.11.4 (RelateOp) does not crash on either input.

### Minimal reproduction

```sh
# 1: two squares sharing the edge x = 2, plus an empty polygon; the point is on the shared edge
geosop -a 'POINT (2 1)' \
       -b 'GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), POLYGON EMPTY)' \
       intersects
Segmentation fault                 # expected: true   (relate: expected 0FFFFF212)

# 2: a point and an empty linestring, against an empty point
geosop -a 'GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)' -b 'POINT EMPTY' relate
Segmentation fault                 # expected: FF0FFFFF2
```

Without the empty element, both inputs give the expected answers (`0FFFFF212` and
`FF0FFFFF2`). An empty element adds no points, so the matrix should not change. The exact
answers were also checked with an exact rational DE-9IM engine (two independent routes). A C
program that uses only the public API is attached (`repro.c`: every call is fork-isolated, and
each case has an EMPTY-free control). The same crashes happen through Shapely 2.1.2
(`shapely.intersects(a, b)` kills the interpreter).

| | expected | GEOS main / 3.15.0 / 3.14.1 / 3.13.1 |
|---|---|---|
| case 1 `GEOSRelate(A,B)` | `0FFFFF212` | SIGSEGV |
| case 1 `GEOSIntersects`, `GEOSWithin`, `GEOSTouches`, `GEOSContains(B,A)`, `GEOSRelatePattern`, `GEOSPreparedCovers(prep B, A)` | true, true, false, true, true, true | SIGSEGV |
| case 2 `GEOSRelate(A,B)` and `(B,A)` | `FF0FFFFF2`, `FFFFFF0F2` | SIGSEGV |

The crash 1 trigger is general. It crashes with the empty polygon in any position, nested in a
sub-collection, or as an `EMPTY` part of a MultiPolygon element (`MULTIPOLYGON (((...)),
EMPTY)`). It crashes with a line or polygon operand instead of the point (e.g.
`LINESTRING (1 1, 3 1)` or `POLYGON ((1 0, 3 0, 3 2, 1 2, 1 0))`, which both cross the shared
edge). It also crashes with two polygons that share only a vertex. It needs a located point on
two or more polygon boundaries of the GC.

### Cause

**1. `AdjacentEdgeLocator` (GEOS-only porting bug).** `RelatePointLocator::locateOnPolygons`
builds an `AdjacentEdgeLocator` over the whole input when a point is on two or more polygon
boundaries (`RelatePointLocator.cpp:287-291`). `AdjacentEdgeLocator::addRings`
(`AdjacentEdgeLocator.cpp:113-129`) does not skip empty polygons, so the 0-point shell of
`POLYGON EMPTY` goes into `ringList`. Then `addSections` runs

```cpp
for (std::size_t i = 0; i < ring->getSize() - 1; i++) {   // AdjacentEdgeLocator.cpp:67
    const CoordinateXY& p0 = ring->getAt(i);                // :68, out of bounds
```

With `getSize() == 0`, the bound is `SIZE_MAX`. A debug build stops at
`CoordinateSequence.h:259` (assertion `i*stride() < m_vect.size()`, with `i = 0`,
`ring->getSize() = 0`). A release build segfaults. JTS's loop (`int i < ring.length - 1`)
runs zero times, so JTS gives the right answer here.

**2. Declared vs real dimension in `TopologyComputer` (also in JTS).** `RelateGeometry::
getDimension()` is `Geometry::getDimension()` (`RelateGeometry.cpp:59`). For a GC this also
counts empty elements, so `GC(POINT, LINESTRING EMPTY)` has dimension 1. By design,
`getDimensionReal()` (`RelateGeometry.cpp:160`) does not count them: JTS's
`RelateGeometryTest.testDimension` expects 2 and 1 for `GC(POLYGON EMPTY, LINESTRING,
POINT)`. The locator only extracts non-empty elements, so `lineBoundary` is never created
(`RelatePointLocator.cpp:56-58`). `RelateNG::evaluate` and `initExteriorDims` dispatch on the
real dimension. But `TopologyComputer::initExteriorEmpty` switches on
`TopologyComputer::getDimension()`, which returns the declared one (`TopologyComputer.cpp:95`,
`:125-128`). It takes the `Dimension::L` branch and calls `hasBoundary()` (`:101`), which
calls `RelatePointLocator::hasBoundary()`, which runs `lineBoundary->hasBoundary()` on
`nullptr` (`RelatePointLocator.cpp:70`). In JTS the same input throws `NullPointerException`
(`RelatePointLocator.java:99`).

The same `TopologyComputer::getDimension()` is also the fallback dimension for a point in the
target's exterior (`RelateNG.cpp:507, 564, 571, 627`). So, without a crash, an empty polygon
in a GC gives a wrong matrix:

```sh
geosop -a 'GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)' -b 'POINT (5 5)' relate
FF2FF10F2                          # expected FF1FF00F2 (a segment's interior is not 2-D)
```

The same happens on the empty-operand path when it does not crash:

```sh
geosop -a 'POINT EMPTY' -b 'GEOMETRYCOLLECTION (POLYGON EMPTY, LINESTRING (0 0, 1 1))' relate
FFFFFF212                          # expected FFFFFF102
```

This is the matrix-level remainder of #1011: the predicates themselves already use the real
dimension. It is older than RelateNG (3.11.4 gives the same two wrong matrices), and JTS RelateNG gives them too.

### Suggested fix

```diff
--- a/src/operation/relateng/AdjacentEdgeLocator.cpp
+++ b/src/operation/relateng/AdjacentEdgeLocator.cpp
@@ -113,6 +113,9 @@ void
 AdjacentEdgeLocator::addRings(const Geometry* geom)
 {
     if (const Polygon* poly = dynamic_cast<const Polygon*>(geom)) {
+        //-- an empty polygon has no rings to add
+        if (poly->isEmpty())
+            return;
         const LinearRing* shell = poly->getExteriorRing();
         addRing(shell, true);
--- a/src/operation/relateng/TopologyComputer.cpp
+++ b/src/operation/relateng/TopologyComputer.cpp
@@ -124,7 +124,9 @@ int
 TopologyComputer::getDimension(bool isA) const
 {
-    return getGeometry(isA).getDimension();
+    //-- the real dimension: a GeometryCollection's getDimension()
+    //-- also counts its EMPTY elements
+    return getGeometry(isA).getDimensionReal();
 }
```

With this patch on main `ae9cdd98b`:
- all cases above give the expected answers;
- `ctest` passes 535/535 (including all `relateng` unit groups and the XML suites);
- a differential run of 25,000 generated relate cases (both argument orders) changes only
  cases with EMPTY elements. It removes all 13 crashes, and it fixes 150 wrong matrices of the
  kind above (they differ only in IE/BE/EI/EB entries).
- no previously correct answer changes.

`getDimensionReal()` is `False` for an empty target. That value never reaches a dimension
switch, because a point is always exterior to an empty target and the `add*` methods return
before switching. For zero-length lines the change also makes these paths use P, which is
what `RelateNG.h:66` documents. Moving `lineBoundary->hasBoundary()` behind a null check
would stop crash 2 but would give `IE = 1` instead of 0, so the dimension change is the real
fix. The same two hunks applied to JTS pass its relateng JUnit tests (154/154) and give an
unchanged XML relate result (`-Djts.relate=ng`).

### Versions

- Crash: GEOS main `ae9cdd98b` (2026-09-21), 3.15.0 (`d0228513a`), 3.14.1 (Shapely 2.2.0rc1
  wheel), 3.13.1 (Shapely 2.1.2 wheel).
- No crash: 3.11.4 (Shapely 2.0.7 wheel, RelateOp). Case 1 is correct there, and case 2
  raises `IllegalArgumentException`.
- JTS master `3ea61f8` and 1.20.0 (RelateNG): case 1 correct, case 2
  `NullPointerException`, both wrong-matrix examples wrong.
- Linux x86_64, GCC 13, Release build. Debug backtraces are from a `-O0 -g3` build of main.

### Related

- #1011 (closed): `covers` wrong for a line against a GC with `POLYGON EMPTY`. The same
  empty-element dimension problem. RelateNG's predicate dispatch now uses the real dimension,
  and `TestRelateGC.xml` has an equivalent case, but `TopologyComputer` does not.
- #1406 (closed, PR #1410) and shapely/shapely#2425: `GeometryNoder::node` segfault on a GC
  with an empty polygon. The same class of bug in a different operation.
- #1002 (closed): PointOnSurface crash on a collection with an empty LineString.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
