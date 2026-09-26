**Title:** RelateNG: NullPointerException (and wrong IM) for a GeometryCollection with an EMPTY element, from declared vs real dimension in TopologyComputer

### Summary

`RelateNG.relate` throws `NullPointerException` for a valid GeometryCollection of points plus
an empty LineString, when it is related to an empty geometry. With an empty Polygon element,
the matrix is wrong instead. Both come from `TopologyComputer.getDimension()`, which returns
the *declared* dimension (`Geometry.getDimension()`, counting empty elements) where the
*real* dimension is needed.

This affects:
- callers of the `RelateNG` API;
- `Geometry.relate` and the predicates when JTS runs with `-Djts.relate=ng`.

JTS's default `Geometry.relate` (RelateOp) throws `IllegalArgumentException: Operation does
not support GeometryCollection arguments` on both inputs below. The default `intersects`
returns false for both, which is correct.

In GEOS the first input segfaults and the second gives the same wrong matrix. That is reported
to GEOS separately, together with a second, GEOS-only crash in `AdjacentEdgeLocator`.

### Reproduction (JTS master 3ea61f8 and 1.20.0)

```java
WKTReader r = new WKTReader();
Geometry a = r.read("GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)");
Geometry b = r.read("POINT EMPTY");
RelateNG.relate(a, b);
// java.lang.NullPointerException: Cannot invoke "LinearBoundary.hasBoundary()" because "this.lineBoundary" is null
//   at RelatePointLocator.hasBoundary(RelatePointLocator.java:99)
//   at RelateGeometry.hasBoundary(RelateGeometry.java:298)
//   at TopologyComputer.initExteriorEmpty(TopologyComputer.java:92)
//   at TopologyComputer.initExteriorDims(TopologyComputer.java:77)
// expected: FF0FFFFF2 (the same as for POINT (0 0) vs POINT EMPTY)

a = r.read("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)");
b = r.read("POINT (5 5)");
RelateNG.relate(a, b);   // FF2FF10F2, expected FF1FF00F2 (a segment's interior is 1-D, its boundary 0-D)
```

Both operands are valid (`IsValidOp`). The expected matrices are the ones JTS returns for the
same point sets without the empty element. They were also checked with an exact rational
DE-9IM engine. `Repro.java` runs these cases.

JTS's own tests already treat an empty element as contributing nothing.
`misc/TestRelateGC.xml` expects `relate` = `1FFF0FFF2` and `covers` = true for
`LINESTRING (0 0, 1 1)` vs `GEOMETRYCOLLECTION (POLYGON EMPTY, LINESTRING (0 0, 1 1))`.

### Cause

`RelateGeometry.getDimension()` is `input.getDimension()` (`RelateGeometry.java:78`). Because
of the empty element, that is 2 or 1, and `RelateGeometryTest.testDimension` pins this.
`getDimensionReal()` gives the dimension of the non-empty point set.

`RelatePointLocator` creates `lineBoundary` only for non-empty lines.
`TopologyComputer.initExteriorEmpty` (`TopologyComputer.java:85-92`) switches on
`getDimension(geomNonEmpty)`, which is the declared dimension (`TopologyComputer.java:108-110`).
For L it calls `hasBoundary()` on the null `lineBoundary`.

The same declared dimension is the exterior fallback in `RelateNG.computePoint`,
`computeLineEnd` and `computeAreaVertex`. That is where the second, wrong matrix comes from.

### Suggested fix

```diff
--- a/modules/core/src/main/java/org/locationtech/jts/operation/relateng/TopologyComputer.java
+++ b/modules/core/src/main/java/org/locationtech/jts/operation/relateng/TopologyComputer.java
@@ -106,7 +106,9 @@
   }
 
   public int getDimension(boolean isA) {
-    return getGeometry(isA).getDimension();
+    //-- the real dimension: a GeometryCollection's getDimension()
+    //-- also counts its EMPTY elements
+    return getGeometry(isA).getDimensionReal();
   }
   
   public boolean isAreaArea() {
```

With this change (tested together with the optional `AdjacentEdgeLocator` change below):
- both cases give the expected matrices;
- the relateng JUnit tests pass (154/154);
- the XML relate suites under `-Djts.relate=ng` give the same result as before (1135/1136,
  with the same single pre-existing failure).

For symmetry with the GEOS fix, `AdjacentEdgeLocator.addRings` could also skip empty polygons.
In Java that is harmless today, because the `int` loop bound is -1 for an empty ring.

### Related

- #1090 ("Fix RelateNG IM for empty-nonempty cases") changed `addPointOnGeometry` and
  `addLineEndOnGeometry` for an empty operand. It did not change `initExteriorEmpty` or the
  exterior fallbacks above.
- libgeos/geos#1011 (closed) is the same empty-element dimension question, for `covers`. The
  `TestRelateGC.xml` case above is equivalent to it, and RelateNG's predicate dispatch already
  uses `getDimensionReal()`.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
