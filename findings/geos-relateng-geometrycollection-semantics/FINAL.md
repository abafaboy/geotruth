# RelateNG: a Point element of a GeometryCollection invents exterior interactions (contains() false because of a far-away point)

## Summary

In a mixed-type GeometryCollection, RelateNG infers exterior entries of the DE-9IM from a single
Point element as if the whole collection were puntal. The inferences are:

- `Exterior x Interior = 2` and `Exterior x Boundary = 1`, for a Point element lying *outside* an
  areal target;
- `Exterior x Boundary = 1`, for a Point element lying inside it.

The converse also fails. A line end that lands on a Point element of a mixed collection never
records `Interior x Exterior = 1`.

The named predicates are affected:

- adding a far-away point to a collection makes `contains` / `covers` false and `overlaps` true;
- a polygon is not `within` a collection made of that polygon and a point;
- a triangle outline is `within` a collection made of one of its vertices and a far line.

The inputs are valid, and RelateNG documents mixed-type collections as supported under union
semantics.

## Minimal reproduction (geosop, GEOS main)

```
$ geosop -a "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))" \
         -b "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))" relate
212FF1212                       # expected 212FF1FF2
$ geosop -a "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))" \
         -b "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))" contains
false                           # expected true
$ geosop -a "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)))" \
         -b "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))" contains
true                            # without the far point

$ geosop -a "LINESTRING (0 0, 1 0, 0 1, 0 0)" -b "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))" relate
0FFFFF102                       # expected 0F1FFF102
$ geosop -a "LINESTRING (0 0, 1 0, 0 1, 0 0)" -b "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))" within
true                            # expected false
$ geosop -a "LINESTRING (0 0, 1 0, 0 1, 0 0)" -b "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))" difference
LINESTRING (0 0, 1 0, 0 1, 0 0) # GEOS's own overlay: A is not covered by B
```

The same results come from the C API (`GEOSRelate_r`, `GEOSContains_r`, `GEOSCovers_r`,
`GEOSWithin_r`, `GEOSCoveredBy_r` and the prepared variants) and from Shapely.

More cases, all with valid inputs and all wrong the same way:

| A | B | expected relate(A,B) | GEOS |
|---|---|---|---|
| `GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))` | `POLYGON ((0 0, 1 0, 0 1, 0 0))` | `2F0F1FFF2` (contains) | `2F0F1F212` (not contains) |
| `POLYGON ((0 0, 1 0, 0 1, 0 0))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), POINT (2 2))` | `2FFF1F0F2` (within) | `2F2F110F2` (overlaps) |
| `GEOMETRYCOLLECTION (POINT (2 2), POLYGON ((-1 -1, 5 -1, 5 5, -1 5, -1 -1), (1 1, 3 1, 3 3, 1 3, 1 1)))` | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))` | `2121F12F2` | `2121F1212` |
| `GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0, 1 1, 0 1, 0 0), POINT (5 5))` | `POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))` | `F10FFF2F2` | `F10FFF212` |
| `LINESTRING (0 0, 1 0)` | `GEOMETRYCOLLECTION (POINT (0 0), POINT (1 0), LINESTRING (5 5, 6 6))` | `FF10FF102` (not coveredBy) | `FFF0FF102` (coveredBy) |
| `GEOMETRYCOLLECTION (POLYGON ((3 2, 3 1, 1 0, 3 2)), MULTIPOINT ((3 4)))` | `LINESTRING (3 4, 4 3, 3 4)` | `0F2FF11F2` (crosses) | `0F2FF1FF2` |

## Expected vs actual

Take the first case. A is the square [0,4]^2 plus the isolated point (10 10), and B is the square
[1,2]^2.

- B lies in A's interior, so EI = EB = F.
- The point adds only IE >= 0, and IE is already 2.
- A contains B.

GEOS reports EI = 2 and EB = 1, as if B were partly outside A. The polygon element alone gives
the correct `212FF1FF2`.

In the line case, the open segment from (0 0) to (1 0) is in A's interior. Only (0 0) of it is
in B, so IE = 1 and A is not within B. GEOS reports IE = F.

The expected matrices were computed by an exact rational engine with two independent routes
(arrangement and witness points), and they agree with the hand derivations above.

## Versions

- GEOS `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 and 3.15.0 (d0228513a): wrong.
- 3.14.1, 3.13.1 and 3.13.0 (d7957246): wrong, the same matrices. The bug has been present since
  RelateNG was introduced.
- 3.11.4 (RelateOp): the polygon+point cases are correct. The line-end cases are wrong in a
  different way.
- JTS master 3ea61f8 and 1.20.0 (`RelateNG`): identical wrong matrices (a separate JTS
  report).

## Analysis

`TopologyComputer::addPointOnGeometry` (src/operation/relateng/TopologyComputer.cpp:310-342)
handles an areal target at lines 332-339:

```cpp
    case Dimension::A:
        /**
         * If a point intersects an area target, then the area interior and boundary
         * must extend beyond the point and thus interact with its exterior.
         */
        updateDim(isPointA, Location::EXTERIOR, Location::INTERIOR, Dimension::A);
        updateDim(isPointA, Location::EXTERIOR, Location::BOUNDARY, Dimension::L);
```

This runs whatever `locTarget` is, including EXTERIOR. Here `dimTarget` is the target's declared
dimension, via `DimensionLocation::dimension` in `RelateNG::computePoint`, RelateNG.cpp:503-509.
The inference is only true globally when the source geometry is puntal, and in that case
`initExteriorDims` (lines 48-88, the P/A branch) has already set both entries.

For a mixed collection the points passed in are the *effective* points
(`RelateGeometry::getEffectivePoints`, RelateGeometry.cpp:308-327): Point elements not covered by
the collection's lines or polygons. Nothing is known about the target beyond such a point's
neighbourhood, because the collection's polygons may cover it. What the neighbourhood does give:

- a point in the target interior gives `E x I = 2`;
- a point on the target boundary gives `E x I = 2` and `E x B = 1`;
- a point in the target exterior gives nothing.

`addLineEndOnGeometry` (lines 346-369) has the opposite gap. For `dimTarget == Dimension::P`
(line 359), which means the line end lies on a Point element, it returns without recording
`Interior(line) x Exterior(target) = 1`. That entry comes from `initExteriorDims` only for a puntal
target (the L/P branch). With a mixed target it is lost. `computeLineEnd` has already dropped
line ends covered by the source's own polygons (RelateNG.cpp:565-567), so the inference is local
and sound.

## Suggested fix

This hunk is taken from the tested prototype `prototype_fix_1.diff`:

```diff
     case Dimension::A:
         /**
          * If a point intersects an area target, then the area interior and boundary
          * must extend beyond the point and thus interact with its exterior.
+         * Only the neighbourhood of the point can be used:
+         * the point may be an element of a mixed GeometryCollection
+         * whose other elements cover the rest of the target.
+         * (For a puntal geometry these entries are set by initExteriorDims.)
          */
+        if (locTarget == Location::EXTERIOR)
+            return;
         updateDim(isPointA, Location::EXTERIOR, Location::INTERIOR, Dimension::A);
-        updateDim(isPointA, Location::EXTERIOR, Location::BOUNDARY, Dimension::L);
+        if (locTarget == Location::BOUNDARY)
+            updateDim(isPointA, Location::EXTERIOR, Location::BOUNDARY, Dimension::L);
         return;
@@ addLineEndOnGeometry
     case Dimension::P:
+        /**
+         * The line end is on a Point (for instance a Point element of a mixed GC),
+         * so some length of the line interior is in the target exterior.
+         * (For a puntal target this entry is set by initExteriorDims.)
+         */
+        updateDim(isLineA, Location::INTERIOR, Location::EXTERIOR, Dimension::L);
         return;
```

Test results:

- **GEOS test suite.** With this patch on main, `ctest` passes 535/535.
- **Differential run.** Over 33,719 generated small-integer relate cases (both argument orders,
  exact answers from the rational engine), it corrects 689 wrong answers and changes no correct
  one.
- **Side effect.** It also corrects the wrong matrix for `GC(LINESTRING (0 0, 1 0), POLYGON EMPTY)`
  vs `POINT (5 5)`: the exterior point no longer invents IE = 2 and BE = 1.

One caveat: a zero-length line element that reaches the new `Dimension::P` branch would get
IE = 1. The existing `addLineEndOnLine` makes the same assumption.

Suggested tests for `TestRelateGC.xml` are the rows of the table above.

## Related issues

- #1148 / JTS #1069 (closed, 3.13.0), "RelateNG Equals regression". That fix handles Point and Line
  elements *covered* by the collection's polygon. This report is about *uncovered* elements; the
  #1148 cases are correct on main.
- #1022, #981, #982 (open) are pre-RelateNG GeometryCollection predicate reports. They give the
  union-semantics answer on main and are not this bug.
- #1011 (closed): the declared dimension of an EMPTY element, a different cause.

No existing report of this behaviour was found (searches of libgeos/geos and locationtech/jts
issues and PRs, open and closed).

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
