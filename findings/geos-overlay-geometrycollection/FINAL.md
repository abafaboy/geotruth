# Overlay with GeometryCollection operands: symDifference drops parts, difference keeps points on lines, AssertionFailedException for empty operands

## Summary

When an operand of `GEOSSymDifference`, `GEOSDifference` or `GEOSIntersection` (C++
`Geometry::symDifference` etc.) is a GeometryCollection that `HeuristicOverlay` hands to
`StructuredCollection` (a mixed-dimension GC, or any GC with a polygonal element, even an
empty one), GEOS main and 3.15.0 return wrong results or throw:

1. **symDifference drops the other operand's points and lines**, and keeps the first operand's
   points and lines even where the other operand covers them. This happens even for a GC that
   holds a single polygon, which is a simple GC by OverlayNG's own definition:
   `GC(POLYGON((0 0,4 0,0 4,0 0)))` xor `POINT(3 3)` returns the polygon without the point, and
   the same GC xor `LINESTRING(1 1,6 6)` returns the polygon without the part of the line that
   lies outside it. The result depends on operand order.
2. **difference does not remove points of A that lie on lines of B**:
   `POINT(1 0)` minus `GC(LINESTRING(0 0,2 0), POINT(3 3))` returns `POINT(1 0)`.
3. **intersection and difference throw `AssertionFailedException: Should never reach here:
   Unable to determine overlay result geometry dimension`** when one operand has no non-empty
   element and the operation goes through `StructuredCollection`:
   `GC(POLYGON EMPTY)` and `POINT(1 1)`, or `POINT EMPTY` and `GC(POLYGON((0 0,4 0,0 4,0 0)))`.

All operands are valid (`GEOSisValid` = 1). GEOS's own OverlayNG gives the right answer for
every case whose operands meet OverlayNG's input requirements (`GEOS*Prec_r(a, b, 0)` calls
`OverlayNGRobust` directly), and GEOS 3.11.4 gives the right answer for all of them. The
three causes are local to `StructuredCollection` in `src/geom/HeuristicOverlay.cpp`; a patch is
attached below.

## Minimal reproduction

```c
/* cc repro.c $(geos-config --cflags) $(geos-config --clibs) */
#include <stdio.h>
#include <geos_c.h>

static void msg(const char *fmt, void *u) { (void)u; printf("  error: %s\n", fmt); }

static void show(GEOSContextHandle_t h, const char *what, GEOSGeometry *g) {
    if (!g) { printf("%s -> (exception, see above)\n", what); return; }
    GEOSWKTWriter *w = GEOSWKTWriter_create_r(h);
    char *s = GEOSWKTWriter_write_r(h, w, g);
    printf("%s -> %s\n", what, s);
    GEOSFree_r(h, s); GEOSWKTWriter_destroy_r(h, w); GEOSGeom_destroy_r(h, g);
}

int main(void) {
    GEOSContextHandle_t h = GEOS_init_r();
    GEOSContext_setErrorMessageHandler_r(h, msg, NULL);
    GEOSWKTReader *r = GEOSWKTReader_create_r(h);
    GEOSGeometry *gcTri  = GEOSWKTReader_read_r(h, r, "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))");
    GEOSGeometry *p33    = GEOSWKTReader_read_r(h, r, "POINT (3 3)");
    GEOSGeometry *l1166  = GEOSWKTReader_read_r(h, r, "LINESTRING (1 1, 6 6)");
    GEOSGeometry *p10    = GEOSWKTReader_read_r(h, r, "POINT (1 0)");
    GEOSGeometry *gcLP   = GEOSWKTReader_read_r(h, r, "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))");
    GEOSGeometry *gcAe   = GEOSWKTReader_read_r(h, r, "GEOMETRYCOLLECTION (POLYGON EMPTY)");
    GEOSGeometry *p11    = GEOSWKTReader_read_r(h, r, "POINT (1 1)");

    show(h, "1 symDifference(GC(triangle), POINT(3 3))", GEOSSymDifference_r(h, gcTri, p33));
    show(h, "  symDifference(POINT(3 3), GC(triangle))", GEOSSymDifference_r(h, p33, gcTri));
    show(h, "  symDifferencePrec(GC(triangle), POINT(3 3), 0)", GEOSSymDifferencePrec_r(h, gcTri, p33, 0));
    show(h, "1 symDifference(GC(triangle), LINESTRING(1 1, 6 6))", GEOSSymDifference_r(h, gcTri, l1166));
    show(h, "1 symDifference(POINT(1 0), GC(line, point))", GEOSSymDifference_r(h, p10, gcLP));
    show(h, "2 difference(POINT(1 0), GC(line, point))", GEOSDifference_r(h, p10, gcLP));
    show(h, "3 intersection(GC(POLYGON EMPTY), POINT(1 1))", GEOSIntersection_r(h, gcAe, p11));
    show(h, "  intersectionPrec(GC(POLYGON EMPTY), POINT(1 1), 0)", GEOSIntersectionPrec_r(h, gcAe, p11, 0));
    return 0;
}
```

or with geosop:

```
geosop -a 'GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))' -b 'POINT (3 3)' symDifference
geosop -a 'POINT (1 0)' -b 'GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))' difference
geosop -a 'GEOMETRYCOLLECTION (POLYGON EMPTY)' -b 'POINT (1 1)' intersection
```

## Expected vs actual (GEOS main ae9cdd98b and 3.15.0, identical)

| # | operation | A | B | actual | expected |
|---|---|---|---|---|---|
| 1a | symDifference | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))` | `POINT (3 3)` | `POLYGON ((0 0, 0 4, 4 0, 0 0))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)), POINT (3 3))` |
| | (swapped) | `POINT (3 3)` | `GEOMETRYCOLLECTION (POLYGON (...))` | `GEOMETRYCOLLECTION (POINT (3 3), POLYGON (...))` | same (correct) |
| 1b | symDifference | `GEOMETRYCOLLECTION (POLYGON EMPTY)` | `POINT (1 1)` | `POINT EMPTY` | `POINT (1 1)` |
| 1c | symDifference | `POINT (1 0)` | `GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))` | `POINT (1 0)` | `GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))` |
| 1d | symDifference | `GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 1, 2 1))` | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` | `LINESTRING (0 1, 2 1)` | `POLYGON EMPTY` (`GEOSEquals(A, B)` is 1) |
| 1e | symDifference | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))` | `LINESTRING (1 1, 6 6)` | `POLYGON ((0 0, 0 4, 4 0, 0 0))` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 2 2, 0 4, 0 0)), LINESTRING (2 2, 6 6))` |
| 2 | difference | `POINT (1 0)` | `GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))` | `POINT (1 0)` | `POINT EMPTY` (`GEOSIntersects(POINT (1 0), LINESTRING (0 0, 2 0))` is 1) |
| 3a | intersection | `GEOMETRYCOLLECTION (POLYGON EMPTY)` | `POINT (1 1)` | AssertionFailedException | `POINT EMPTY` |
| 3b | intersection | `POINT EMPTY` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))` | AssertionFailedException | `POINT EMPTY` |
| 3c | difference | `POINT EMPTY` | `GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))` | AssertionFailedException | `POINT EMPTY` |
| 3d | intersection | `GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))` | `MULTIPOLYGON EMPTY` | AssertionFailedException | `LINESTRING EMPTY` |

The expected results are the point-set definitions of the C API documentation ((3 3) is outside
the triangle x + y <= 4; the line of 1e leaves the triangle at (2 2); (1 0) lies on (0 0)-(2 0);
in 1d both operands are the same point set). For 1a, 1b, 1e, 3a, 3b and 3c,
`GEOSSymDifferencePrec_r` / `GEOSIntersectionPrec_r` / `GEOSDifferencePrec_r` with
`gridSize = 0` return the expected result, and so does the public function when the polygon is
not wrapped in a GC. They were also checked against an exact rational implementation of the
overlay and, independently, by hand.

These inputs are within the documented contract. Cases 1a, 1b, 1e, 3a, 3b and 3c meet even
OverlayNG's own input requirements (OverlayNG.h: homogeneous, simple GCs). The others use
mixed-dimension GCs, which the public overlay functions support since 3.12 (NEWS for 3.12.0:
"Support mixed GeometryCollection in overlay ops (GH-797)", implemented by #923; the
HeuristicOverlay.cpp header: "It also implements overlay for GeometryCollections, which is not
(yet) provided by OverlayNG"). The C API documents no restriction on input types. (The C++
`Geometry.h` doc comments still say these methods throw IllegalArgumentException for a
non-empty GeometryCollection, which does not match their behaviour. That comment could be
updated with the fix.)

## Versions

- GEOS main ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (head on 2026-09-26): all wrong as above
- GEOS 3.15.0 d0228513abb0c29c185443cf2bfb06c9281024b5: same
- GEOS 3.14.1 (Shapely 2.2.0rc1) and 3.13.1 (Shapely 2.1.2): same
- GEOS 3.13.0 d7957246c: 1c, 1d and 2 wrong; 1a, 1b, 1e and 3a to 3c right; 3d returns
  `GEOMETRYCOLLECTION EMPTY` (the same point set). The two issues under "Also noticed" below
  occur on 3.13.0 as well.
- GEOS 3.11.4 (Shapely 2.0.7): all right (3d comes out as `LINESTRING Z EMPTY`, the same point
  set), including the two cases under "Also noticed"
- JTS master 3ea61f8 and 1.20.0 are not affected: `Geometry.symDifference`/`difference` reject
  GC arguments with IllegalArgumentException, as JTS documents, and `OverlayNGRobust` gives
  the expected result for the simple-GC cases.

The regression is specific, not general. The wrong results of 1a, 1b and 1e and the assertion
of 3a to 3d appeared with #1229 (3.14.0, backported to 3.13.1 and 3.12.3); 1c, 1d and 2 come
from the code added in #923 (3.12.0). Otherwise GC overlay has improved since 3.13.0: on the GC
pairs of the differential test described below, 3.13.0 threw TopologyException for 1356 of the
7872 results and main throws no TopologyException (the input of #948 behaves the same way).

## Analysis

All three are in `StructuredCollection` (`src/geom/HeuristicOverlay.cpp`, main ae9cdd98b):

1. **symDifference** (`doSymDifference`, lines 505-528): only the polygons get a symmetric
   difference. Lines and points are computed as `this.lines - a.lines` and
   `this.points - a.points` (lines 513-521, `OverlayNG::DIFFERENCE`). So the other operand's
   lines and points never reach the result, and this operand's lines and points are not
   removed where the other operand's polygons or lines cover them. `doUnaryUnion` only removes
   parts covered by the result. Since #1229, `isHandledByOverlayNG` (lines 118-126) sends
   every GC whose `getDimension()` is 2 here, including `GC(POLYGON)` and `GC(POLYGON EMPTY)`
   (the dimension counts empty elements). That is why 1a, 1b and 1e are right on 3.13.0 and
   wrong from 3.13.1 on.
2. **difference** (`doDifference`, lines 488-491): `pt_diff_poly_line` subtracts
   `line_diff_poly_line`, which is this operand's own remaining lines, instead of
   `a.getLineUnion()`. Points of A on lines of B survive.
3. **assertion**: `dimension` is initialised to `Dimension::DONTCARE` (-3)
   (HeuristicOverlay.h:67), and `readCollection` raises it only for non-empty atomic elements
   (line 236). For an operand with no non-empty element it stays -3. `computeResult` then gets
   -3 from `OverlayUtil::resultDimension` (min for intersection, the first operand's value for
   difference), and `doUnaryUnion` calls `OverlayUtil::createEmptyResult(-3, ...)`, which ends in
   `Assert::shouldNeverReachHere` (OverlayUtil.cpp:193-194). The typed empty result came in with
   #1229 (3.14.0, backported to 3.12.3 and 3.13.1).

## Suggested fix

The patch below (against main ae9cdd98b) changes three things in `StructuredCollection`:

1. `doSymDifference` computes `Union(Diff(A, B), Diff(B, A))`, calling `doDifference` in both
   directions (fixes 1).
2. `doDifference` subtracts `a.getLineUnion()` from A's points (fixes 2), and subtracts B's
   lines from A's lines before B's polygons.
3. An operand without non-empty elements takes its declared dimension `g->getDimension()`
   (fixes 3). This gives the same typed empty result as OverlayNG.

It also adds unit tests (HeuristicOverlayTest 13-17). With it, the cases above give the
expected results, `test_geos_unit geos::geom::HeuristicOverlay` passes 17/17, and the full
`ctest` passes 535/535. We also ran a differential test on 1968 GeometryCollection pairs × 4
operations against an exact implementation. The patch turned 458 wrong results or exceptions
into correct results and turned 1 correct result into a wrong one. That case and the results
that are still wrong come from floating-point node rounding; the remaining exceptions come
from nested empty GCs (both under "Also noticed").

The reordering in `doDifference` (lines before polygons) is not needed for correctness. It
reduces rounding effects: without it, 11 of the 1968 × 4 results that were right by accident
become wrong under the new symDifference.

<details>
<summary>Patch (git diff against ae9cdd98b, with the unit tests)</summary>

```diff
diff --git a/include/geos/geom/HeuristicOverlay.h b/include/geos/geom/HeuristicOverlay.h
index e4eb8b74a..b017d24cf 100644
--- a/include/geos/geom/HeuristicOverlay.h
+++ b/include/geos/geom/HeuristicOverlay.h
@@ -67,6 +67,9 @@ private:
         , dimension(Dimension::DONTCARE)
     {
         readCollection(g);
+        //-- no non-empty element: use the declared dimension of the (empty) input
+        if (dimension == Dimension::DONTCARE)
+            dimension = static_cast<Dimension::DimensionType>(g->getDimension());
         unionByDimension();
     };
 
diff --git a/src/geom/HeuristicOverlay.cpp b/src/geom/HeuristicOverlay.cpp
index 57f6683de..93f0caeb1 100644
--- a/src/geom/HeuristicOverlay.cpp
+++ b/src/geom/HeuristicOverlay.cpp
@@ -470,9 +470,11 @@ StructuredCollection::doDifference(const StructuredCollection& a) const
         a.getPolyUnion(),
         OverlayNG::DIFFERENCE);
 
-    std::unique_ptr<Geometry> line_diff_poly = OverlayNGRobust::Overlay(
+    //-- remove B's lines first: a line of A that coincides with a line of B
+    //-- is then removed before any noding against B's polygons can move it
+    std::unique_ptr<Geometry> line_diff_line = OverlayNGRobust::Overlay(
         line_union.get(),
-        a.getPolyUnion(),
+        a.getLineUnion(),
         OverlayNG::DIFFERENCE);
 
     std::unique_ptr<Geometry> pt_diff_poly = OverlayNGRobust::Overlay(
@@ -481,13 +483,13 @@ StructuredCollection::doDifference(const StructuredCollection& a) const
         OverlayNG::DIFFERENCE);
 
     std::unique_ptr<Geometry> line_diff_poly_line = OverlayNGRobust::Overlay(
-        line_diff_poly.get(),
-        a.getLineUnion(),
+        line_diff_line.get(),
+        a.getPolyUnion(),
         OverlayNG::DIFFERENCE);
 
     std::unique_ptr<Geometry> pt_diff_poly_line = OverlayNGRobust::Overlay(
         pt_diff_poly.get(),
-        line_diff_poly_line.get(),
+        a.getLineUnion(),
         OverlayNG::DIFFERENCE);
 
     std::unique_ptr<Geometry> pt_diff_poly_line_pt = OverlayNGRobust::Overlay(
@@ -505,25 +507,18 @@ StructuredCollection::doDifference(const StructuredCollection& a) const
 std::unique_ptr<Geometry>
 StructuredCollection::doSymDifference(const StructuredCollection& a) const
 {
-    std::unique_ptr<Geometry> poly_symdiff_poly = OverlayNGRobust::Overlay(
-        poly_union.get(),
-        a.getPolyUnion(),
-        OverlayNG::SYMDIFFERENCE);
-
-    std::unique_ptr<Geometry> line_symdiff_line = OverlayNGRobust::Overlay(
-        line_union.get(),
-        a.getLineUnion(),
-        OverlayNG::DIFFERENCE);
-
-    std::unique_ptr<Geometry> pt_symdiff_pt = OverlayNGRobust::Overlay(
-        pt_union.get(),
-        a.getPointUnion(),
-        OverlayNG::DIFFERENCE);
+    /*
+    * SymDiff(A, B) = Union(Diff(A, B), Diff(B, A)).
+    * Both differences are needed for the lower dimensions:
+    * points and lines of B must be kept where they are not in A,
+    * and points and lines of A removed where they are in B.
+    */
+    std::unique_ptr<Geometry> a_diff_b = doDifference(a);
+    std::unique_ptr<Geometry> b_diff_a = a.doDifference(*this);
 
     StructuredCollection c;
-    c.readCollection(poly_symdiff_poly.get());
-    c.readCollection(line_symdiff_line.get());
-    c.readCollection(pt_symdiff_pt.get());
+    c.readCollection(a_diff_b.get());
+    c.readCollection(b_diff_a.get());
     return computeResult(c, OverlayNG::SYMDIFFERENCE, getDimension(), a.getDimension());
 }
 
diff --git a/tests/unit/geom/HeuristicOverlayTest.cpp b/tests/unit/geom/HeuristicOverlayTest.cpp
index 0f9a19717..86bad05f1 100644
--- a/tests/unit/geom/HeuristicOverlayTest.cpp
+++ b/tests/unit/geom/HeuristicOverlayTest.cpp
@@ -216,4 +216,87 @@ void object::test<12> ()
         );
 }
 
+// symdifference keeps the parts of B that are not in A (GC with one polygon)
+template<>
+template<>
+void object::test<13> ()
+{
+    checkOverlay(
+        "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))",
+        "POINT (3 3)",
+        OverlayNG::SYMDIFFERENCE,
+        "GEOMETRYCOLLECTION (POINT (3 3), POLYGON ((0 0, 4 0, 0 4, 0 0)))"
+        );
+}
+
+// difference removes points of A that lie on lines of B
+template<>
+template<>
+void object::test<14> ()
+{
+    checkOverlay(
+        "POINT (1 0)",
+        "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))",
+        OverlayNG::DIFFERENCE,
+        "POINT EMPTY"
+        );
+}
+
+// symdifference removes points of A that lie on lines of B, keeps B's parts
+template<>
+template<>
+void object::test<15> ()
+{
+    checkOverlay(
+        "POINT (1 0)",
+        "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))",
+        OverlayNG::SYMDIFFERENCE,
+        "GEOMETRYCOLLECTION (POINT (3 3), LINESTRING (0 0, 2 0))"
+        );
+}
+
+// symdifference of equal point sets is empty
+template<>
+template<>
+void object::test<16> ()
+{
+    checkOverlay(
+        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 1, 2 1))",
+        "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
+        OverlayNG::SYMDIFFERENCE,
+        "POLYGON EMPTY"
+        );
+}
+
+// empty operand without non-empty elements: typed empty result, no assertion
+template<>
+template<>
+void object::test<17> ()
+{
+    checkOverlay(
+        "GEOMETRYCOLLECTION (POLYGON EMPTY)",
+        "POINT (1 1)",
+        OverlayNG::INTERSECTION,
+        "POINT EMPTY"
+        );
+    checkOverlay(
+        "GEOMETRYCOLLECTION (POLYGON EMPTY)",
+        "POINT (1 1)",
+        OverlayNG::SYMDIFFERENCE,
+        "POINT (1 1)"
+        );
+    checkOverlay(
+        "POINT EMPTY",
+        "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))",
+        OverlayNG::DIFFERENCE,
+        "POINT EMPTY"
+        );
+    checkOverlay(
+        "GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))",
+        "MULTIPOLYGON EMPTY",
+        OverlayNG::INTERSECTION,
+        "LINESTRING EMPTY"
+        );
+}
+
 } // namespace tut
```

</details>

## Also noticed (lower priority, not fixed by the patch)

Both of these are also on 3.13.0 (they come with the code added in #923) and not on 3.11.4.

- `unionByDimension` nodes each operand's own lines in floating point before the actual
  overlay. Where two lines of a GC cross at a point that is not a double, the rounded node
  moves the split pieces off the original segments, and exact coincidences with the other
  operand are lost:
  `GEOSIntersection(POINT (3 2), GEOMETRYCOLLECTION (MULTILINESTRING ((0 2, 2 4), (0 4, 6 0)), POINT (9 9)))`
  returns `POINT EMPTY` (`GEOMETRYCOLLECTION EMPTY` on 3.13.0), and with `LINESTRING (3 2, 6 0)`
  as A it returns `POINT (6 0)`. The expected results are `POINT (3 2)` and
  `LINESTRING (3 2, 6 0)`: (3 2) lies exactly on (0 4)-(6 0). With
  `MULTILINESTRING ((0 2, 2 4), (0 4, 6 0))` as B (no GC), both are correct.
- A lineal GC with a nested `GEOMETRYCOLLECTION EMPTY`, e.g.
  `GEOSIntersection(LINESTRING (0 0, 1 1), GEOMETRYCOLLECTION (LINESTRING (0 1, 1 0), GEOMETRYCOLLECTION EMPTY))`,
  throws "IllegalArgumentException: Overlay input is mixed-dimension".
  `Geometry::isMixedDimension` ignores the empty nested GC, but
  `EdgeNodingBuilder::addGeometryCollection` compares its dimension (-1). With `POINT EMPTY`
  in place of `GEOMETRYCOLLECTION EMPTY` the result is correct.

## Related issues

- #797, fixed by #923 ("Overlay with mixed dimension", 3.12.0), which introduced
  `StructuredCollection`.
- #1224 (union results containing empty elements), fixed by #1229 (3.14.0, backported to
  3.12.3 and 3.13.1). #1229 introduced the typed empty result and the routing of polygonal GCs
  to `StructuredCollection`.
- #948 (still open): difference with a GC of overlapping polygons threw a TopologyException.
  The input from that issue still throws on 3.13.0, but 3.13.1 and later (including main) return
  the correct polygon, so it may be possible to close it.
- #696 / #716: OverlayNG support for simple GeometryCollection inputs, which the `*Prec_r`
  route uses.
- Checked and different: #1023 / #1050 (3.9 branch: a mixed-GC difference threw
  IllegalArgumentException), #1059 (how an intersection with a GC of adjacent polygons is
  represented), #1316 (difference of a line and a point, no GC).
- JTS: locationtech/jts#667 and locationtech/jts#833, open proposals for GC support in
  OverlayNG and in `Geometry.difference`. JTS itself rejects GC operands, so it is not affected.
- Downstream: duckdb/duckdb-spatial#803 (the assertion, via `ST_Intersection` with an empty
  geometry; closed there, with no GEOS issue linked).

We found no existing GEOS report of the wrong symDifference/difference results or of the
assertion. We searched libgeos/geos issues and PRs (open and closed) and the Shapely and JTS
trackers. We could not search PostGIS trac.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
