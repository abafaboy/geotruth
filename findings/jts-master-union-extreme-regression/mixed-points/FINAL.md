# OverlayNG: union/symDifference of a polygon and a point throws ClassCastException when a polygon collapses under the precision model

*Draft issue for locationtech/jts. Not filed.*

## Summary

`OverlayNG.overlay(A, P, UNION, pm)` and `SYMDIFFERENCE` throw

    java.lang.ClassCastException: class org.locationtech.jts.geom.LineString cannot be cast to class org.locationtech.jts.geom.Polygon
        at org.locationtech.jts.operation.overlayng.OverlayMixedPoints.extractPolygons(OverlayMixedPoints.java:237)
        at org.locationtech.jts.operation.overlayng.OverlayMixedPoints.computeUnion(OverlayMixedPoints.java:155)
        at org.locationtech.jts.operation.overlayng.OverlayMixedPoints.getResult(OverlayMixedPoints.java:115)
        at org.locationtech.jts.operation.overlayng.OverlayMixedPoints.overlay(OverlayMixedPoints.java:67)
        at org.locationtech.jts.operation.overlayng.OverlayNG.getResult(OverlayNG.java:482)

when A is polygonal, P is a point (or points), and a polygon of A collapses to a line under the
precision model. This happens in either argument order, and in strict mode as well. The input is
valid, with small, ordinary coordinates (0 to 7).

It is also reachable without calling `OverlayNG` directly. With a `GeometryFactory` that has a
fixed `PrecisionModel`, `OverlayNGRobust.overlay(A, P, OverlayNG.UNION)` throws, and with
`-Djts.overlay=ng` so do `A.union(P)` and `A.symDifference(P)`. The point operand can even be
empty: `OverlayNG.overlay(A, POINT EMPTY, UNION, pm)` throws too.

## Minimal reproduction

```java
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.OverlayNG;

WKTReader r = new WKTReader();
Geometry a = r.read("MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((3 0, 5 0, 5 0.4, 3 0)))");
Geometry p = r.read("POINT (7 7)");
PrecisionModel pm = new PrecisionModel(1);

OverlayNG.overlay(a, p, OverlayNG.UNION, pm);          // ClassCastException
OverlayNG.overlay(a, p, OverlayNG.SYMDIFFERENCE, pm);  // ClassCastException
OverlayNG.overlay(a, p, OverlayNG.DIFFERENCE, pm);     // GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0))
```

On the integer grid, (5 0.4) rounds to (5 0), so the thin triangle collapses to the segment
(3 0)-(5 0).

A complete program is attached (`Repro.java`, public API only;
`javac -cp jts-core.jar Repro.java && java -cp jts-core.jar:. Repro`). Its section 5 covers
the other entry points above; run it with `-Djts.overlay=ng` to include `Geometry.union`.

## Expected vs actual

For the same A with other kinds of operands, OverlayNG handles the collapse as documented. In
the default non-strict mode, "results can include lines caused by Area topology collapse";
in strict mode the collapse line is dropped.

| call (pm = `new PrecisionModel(1)`) | JTS master 3ea61f8 and 1.20.0 |
|---|---|
| `UNION(A, LINESTRING (7 7, 8 8))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0), LINESTRING (7 7, 8 8))` |
| `UNION(A, POLYGON ((7 7, 8 7, 8 8, 7 7)))` | `GEOMETRYCOLLECTION (POLYGON (...), POLYGON (...), LINESTRING (3 0, 5 0))` |
| `DIFFERENCE(A, POINT (7 7))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0))` |
| **`UNION(A, POINT (7 7))`, `SYMDIFFERENCE(A, POINT (7 7))`** | **`ClassCastException`** |

Expected, for union and symdifference:

    GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0), POINT (7 7))

With strict mode the collapse line should be left out:
`GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), POINT (7 7))`.

The non-strict answer is what GEOS 3.11.4, 3.13.1 and 3.14.1 return for the same input
(`shapely.union(a, p, grid_size=1)`). It is also the exact non-strict union of the snapped
operands, checked with rational arithmetic. A is valid, and P lies outside A.

## Versions

- master `3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd`: `ClassCastException`.
- 1.20.0: `ClassCastException`.
- 1.18.0: `IllegalArgumentException: Argument must be Polygonal or LinearRing`, one step earlier,
  from `IndexedPointInAreaLocator`. There it is thrown for `DIFFERENCE(A, P)` as well as for
  `UNION` and `SYMDIFFERENCE` (in both orders); only `DIFFERENCE(P, A)` succeeds.

The cast has been in `OverlayMixedPoints` since OverlayNG was added (#599).

The same failure also occurs without a fixed precision model. `OverlayNGRobust.overlay(A, P,
UNION)` throws it whenever the floating union of A collapses a polygon, for example for inputs
with ordinates around 1e-161, where orientation tests underflow (a separate issue). The fixed
precision model is simply the easy way to trigger it.

## Analysis

- **How the collapse gets into the operand.** `OverlayMixedPoints.prepareNonPoint`
  (`OverlayMixedPoints.java:132-141`) nodes and rounds the non-point operand with
  `OverlayNG.union(geomNonPointInput, pm)` (`:139`), in the default non-strict mode. With a fixed
  precision model, the result can be a GeometryCollection of polygons plus collapse lines. Its
  dimension is still 2.
- **The cast.** `computeUnion` (`:147-159`) sees dimension 2 and calls `extractPolygons`, which
  casts every element: `Polygon poly = (Polygon) geom.getGeometryN(i);` (`:237`).
  `extractLines` has the same unchecked cast (`:248`).
- **Strict mode.** It does not help, because `OverlayNG.getResult` calls
  `OverlayMixedPoints.overlay(opCode, geom0, geom1, pm)` (`OverlayNG.java:482`) without the
  strict flag. For the same reason, strict `DIFFERENCE(A, P)` returns the collapse line too.
  That is a smaller, related inconsistency.

## Suggested fix

Take only the elements of the wanted type, and keep the collapse lines of an areal operand,
as the non-point overlay does:

```java
  private Geometry computeUnion(Coordinate[] coords) {
    ...
    if (geomNonPointDim == 2) {
      resultPolyList = extractPolygons(geomNonPoint);
      // non-strict union of the areal input can contain lines from collapsed polygons
      resultLineList = extractLines(geomNonPoint);
    }
    ...
  }

  private static List<Polygon> extractPolygons(Geometry geom) {
    List<Polygon> list = new ArrayList<Polygon>();
    for (int i = 0; i < geom.getNumGeometries(); i++) {
      Geometry elem = geom.getGeometryN(i);
      if (elem instanceof Polygon && ! elem.isEmpty()) list.add((Polygon) elem);
    }
    return list;
  }
  // extractLines likewise with LineString
```

`prototype_fix.diff` makes these changes and adds
`OverlayNGMixedPointsTest.testPolygonCollapseUnion`, which fails on master and passes with the
patch. The rest of the core JUnit tests give the same results with and without the patch.

The prototype only gives the correct result in the default non-strict mode. In strict mode it
still keeps the collapse line: strict `UNION(A, P)` returns
`GEOMETRYCOLLECTION (POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0)), LINESTRING (3 0, 5 0), POINT (7 7))`,
because `OverlayMixedPoints` never sees the strict flag. To honour strict mode as well,
`OverlayMixedPoints` would need that flag. It could then call the strict union in
`prepareNonPoint`, as GEOS 3.15 does. The prototype does not attempt that.

## Related

- GEOS ports this code (`OverlayMixedPoints.cpp`) with a `static_cast` in `extractPolygons`.
  - Up to 3.14.x the cast is reached with a `LineString`, which is undefined behaviour (the
    cast is `static_cast<const Polygon*>` in the 3.13.1 and 3.14.1 sources). It happens to
    return the non-strict answer above (run on 3.11.4, 3.13.1 and 3.14.1).
  - 3.15.0 and main node the operand in strict mode (`OverlayNG::geomunion(geom, pm, noder)`
    sets strict mode). The line never reaches the cast, and union gives
    `GEOMETRYCOLLECTION (POLYGON, POINT)`. Union with a line operand still keeps the collapse
    line. This came in with libgeos/geos@095c7270 "OverlayNG: Support curved types" (in 3.15.0),
    which passes a noder to `geomunion`; as far as we can tell it was not aimed at this case.
- NetTopologySuite has the same `(Polygon)` cast in `ExtractPolygons`; it was not run.
- No existing issue was found. The searches covered locationtech/jts, libgeos/geos,
  shapely/shapely and NetTopologySuite, issues and PRs, open and closed:
  ClassCastException / OverlayMixedPoints / point-polygon overlay with a precision model /
  "Argument must be Polygonal or LinearRing".
  - libgeos/geos#931 (UB in `OverlayMixedPoints.cpp`) is a different defect: a null
    `PrecisionModel` reference.
  - #1133 (`SnapRoundingNoder` output is lines) is a usage question.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
