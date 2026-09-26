# RelateNG: valid polygons reported as touching or containing instead of overlapping when a proper crossing point rounds onto a vertex

## Summary

For two small valid triangles, `RelateNG` returns a wrong DE-9IM matrix, and wrong `touches`/`overlaps`/`contains`/`covers`/`within` results. The trigger is a vertex P of B that lies about 3.7e-17 off an edge of A.

- Both of B's edges at P cross A's edge properly, and `RobustLineIntersector` reports `isProper()`.
- However, the computed intersection point rounds exactly to P. `RelateSegmentString.createNodeSection` then recomputes properness by comparing that rounded point with the segment endpoints, so both crossings are treated as a touch at B's vertex.
- The result is `touches` = true instead of `overlaps` when P is inside A, and `contains`/`covers` = true instead of `overlaps` when P is outside A. With the arguments swapped, `within` = true.

The default `Geometry.relate` (RelateOp) returns the exact answer, `212101212`. The wrong results appear when `RelateNG` is used directly, and also through `Geometry` predicates when `-Djts.relate=ng` is set. GEOS has had the same behaviour since 3.13, when RelateNG became its default: libgeos/geos#____.

## About the documented round-off caveat

[package-info.java#L64-L70](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/package-info.java#L64-L70) says:

> This means that invalid input geometries or numerical round-off do not cause exceptions (although they may return incorrect answers).

I think this case is still worth fixing:

- **The inputs are valid and are used as given.** `RobustLineIntersector` decides that each crossing is proper from exact orientation tests, and RelateNG then discards that decision.
- **RelateOp gets this right.** It uses the same proper-intersection flag in `computeProperIntersectionIM`.
- **RelateNG contradicts its own point predicates.** In case 1, `RelateNG` says A contains B's vertex P but that A only touches B. In case 2, it says P does not intersect A but that A contains B.
- **The result depends on the ring's start vertex** (see below).
- **Prepared and non-prepared results disagree.** With `-Djts.relate=ng`, case 2 gives `Geometry.contains` = true but `PreparedGeometryFactory.prepare(A).contains(B)` = false.
- **The existing tests assert impossible matrices.** `RelateNGRobustnessTest.testPostGIS_5362` and `testGISSE_484691` assert `2F2101212`, which two valid polygons cannot have (see "Related").

## Reproducer

```java
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.relateng.RelateNG;
import org.locationtech.jts.operation.relateng.RelatePredicate;

public class Repro {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    Geometry a  = r.read("POLYGON ((0 0, 3 0, 3 1, 0 0))");
    Geometry b1 = r.read("POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))");
    Geometry p1 = r.read("POINT (2 0.6666666666666666)");
    Geometry b2 = r.read("POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))");
    Geometry p2 = r.read("POINT (2.5 0.8333333333333334)");
    System.out.println("JTS " + org.locationtech.jts.JTSVersion.CURRENT_VERSION);
    System.out.println("case 1: RelateOp " + a.relate(b1) + "  RelateNG " + RelateNG.relate(a, b1)
        + "  touches=" + RelateNG.relate(a, b1, RelatePredicate.touches())
        + "  overlaps=" + RelateNG.relate(a, b1, RelatePredicate.overlaps())
        + "  prepared touches=" + RelateNG.prepare(a).evaluate(b1, RelatePredicate.touches())
        + "  contains(A,P)=" + RelateNG.relate(a, p1, RelatePredicate.contains()));
    System.out.println("case 2: RelateOp " + a.relate(b2) + "  RelateNG " + RelateNG.relate(a, b2)
        + "  contains=" + RelateNG.relate(a, b2, RelatePredicate.contains())
        + "  overlaps=" + RelateNG.relate(a, b2, RelatePredicate.overlaps())
        + "  prepared contains=" + RelateNG.prepare(a).evaluate(b2, RelatePredicate.contains())
        + "  within(B,A)=" + RelateNG.relate(b2, a, RelatePredicate.within())
        + "  intersects(A,P)=" + RelateNG.relate(a, p2, RelatePredicate.intersects()));
  }
}
```

A and both B triangles are valid (`isValid()` returns true, and an exact rational check agrees).

## Expected vs actual

Expected, for both cases: `relate(A,B) = 212101212`, `overlaps` = true, and `touches` = `contains` = `covers` = `within(B,A)` = false.

Actual output on master 3ea61f8, run now. 1.20.0 prints the same lines apart from the version:

```
JTS 1.21.0 SNAPSHOT
case 1: RelateOp 212101212  RelateNG FF2F01212  touches=true  overlaps=false  prepared touches=true  contains(A,P)=true
case 2: RelateOp 212101212  RelateNG 212F01FF2  contains=true  overlaps=false  prepared contains=true  within(B,A)=true  intersects(A,P)=false
```

**Ring start vertex.** The same point sets, with B's ring rotated, give these `RelateNG.relate(A, B)` results:

```
POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))                              FF2F01212
POLYGON ((2 0.6666666666666666, 2 2, 1 2, 2 0.6666666666666666))             212F01212
POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))                  212F01FF2
POLYGON ((2.5 0.8333333333333334, 2.5 0.5, 3 0.5, 2.5 0.8333333333333334))   212F01212
```

## Why `212101212` is right (checkable by hand)

A is the region 0 ≤ y ≤ x/3, x ≤ 3.

- **Case 1.** `0.6666666666666666` is exactly 6004799503160661/2^53 = 2/3 − 1/(3·2^53).
  - So P = (2, 0.6666666666666666) is strictly inside A.
  - B's other vertices, (1 2) and (2 2), are above the line y = x/3. Both of B's edges at P therefore cross A's edge at points strictly inside both segments.
  - The two crossings and P bound a triangle in A∩B with area 1/2433889152438200504916865682767872 ≈ 4.1e-34.
- **Case 2.** `0.8333333333333334` is exactly 5/6 + 1/(3·2^53).
  - So P is strictly outside A.
  - area(B − A) = 1/1460333491462920378610593149485056 ≈ 6.8e-34.

Two independent exact rational implementations agree on these values.

## Versions tested

- JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd (1.21.0-SNAPSHOT) and JTS 1.20.0 (6e95fe8): `RelateNG` is wrong, and the default `Geometry.relate` is correct.
- OpenJDK 21 on Linux x86-64.
- GEOS 3.13.1, 3.14.1, 3.15.0 and main give the same wrong matrices. GEOS 3.11.4 is correct.

## Analysis

The line references below are for master at 3ea61f8.

1. `RobustLineIntersector.computeIntersect` classifies the crossing with `Orientation.index` ([#L65-L73](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/algorithm/RobustLineIntersector.java#L65-L73)). For both of B's edges at P, it sets `isProper = true` and then computes the point in floating point ([#L160-L161](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/algorithm/RobustLineIntersector.java#L160-L161)). For both edges, the computed point is bit-identical to P.
2. `EdgeSegmentIntersector.addIntersections` uses `li.isProper()` only to decide whether to add the node ([#L79-L84](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/EdgeSegmentIntersector.java#L79-L84)).
3. `RelateSegmentString.createNodeSection` sets `isNodeAtVertex = intPt.equals2D(getCoordinate(segIndex)) || intPt.equals2D(getCoordinate(segIndex + 1))` ([#L79-L82](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/RelateSegmentString.java#L79-L82)). `NodeSection.isProper()` returns `!isNodeAtVertex` ([#L133-L134](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/NodeSection.java#L133-L134)). Because the rounded point equals P, B's section is treated as a node at a vertex.
4. `TopologyComputer.updateAreaAreaCross` then falls back to `PolygonNodeTopology.isCrossing` at P ([#L231-L237](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/TopologyComputer.java#L231-L237)).
   - This returns false: P is not exactly on A's edge, so the rays from P to A's segment endpoints do not separate B's two neighbouring vertices.
   - The node at P is then evaluated as B's wedge touching A from outside (case 1) or from inside (case 2).
5. The ring-start dependence comes from `RelateNG.computeAreaVertex`, which locates only the first coordinate of each ring ([#L506-L508](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relateng/RelateNG.java#L506-L508)).

RelateOp's `RelateComputer.computeProperIntersectionIM` calls `setAtLeast("212101212")` for two areas whenever a proper intersection is found ([#L154-L168](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/main/java/org/locationtech/jts/operation/relate/RelateComputer.java#L154-L168)).

## Prototype (for illustration, not a proposed patch)

This change passes the intersector's exact properness through to `TopologyComputer`. For two polygonal inputs, it records the same lower bound that RelateOp uses. It may not be the approach you would choose.

<details><summary>diff against master 3ea61f8</summary>

```diff
--- a/modules/core/src/main/java/org/locationtech/jts/operation/relateng/EdgeSegmentIntersector.java
+++ b/modules/core/src/main/java/org/locationtech/jts/operation/relateng/EdgeSegmentIntersector.java
@@ -81,6 +81,9 @@
                 && ssB.isContainingSegment(segIndexB, intPt))) {
         NodeSection nsa = ssA.createNodeSection(segIndexA, intPt);
         NodeSection nsb = ssB.createNodeSection(segIndexB, intPt);
+        //-- the rounded intPt may equal a vertex even though the crossing is proper
+        if (li.isProper())
+          topoComputer.addProperIntersection(nsa, nsb);
         topoComputer.addIntersection(nsa, nsb);
       }
     }
--- a/modules/core/src/main/java/org/locationtech/jts/operation/relateng/TopologyComputer.java
+++ b/modules/core/src/main/java/org/locationtech/jts/operation/relateng/TopologyComputer.java
@@ -196,6 +196,27 @@
     return node;
   }
   
+  /**
+   * Records a proper crossing of an A segment and a B segment, as determined
+   * by the LineIntersector (exact orientation tests), independent of whether
+   * the rounded intersection point equals a segment endpoint.
+   * For two areas this implies II = 2; for two polygonal geometries it implies
+   * the lower bound 212101212 (as in RelateComputer.computeProperIntersectionIM).
+   */
+  public void addProperIntersection(NodeSection a, NodeSection b) {
+    if (a.isSameGeometry(b) || ! NodeSection.isAreaArea(a, b)) return;
+    updateDim(Location.INTERIOR, Location.INTERIOR, Dimension.A);
+    if (geomA.isPolygonal() && geomB.isPolygonal()) {
+      updateDim(Location.INTERIOR, Location.BOUNDARY, Dimension.L);
+      updateDim(Location.INTERIOR, Location.EXTERIOR, Dimension.A);
+      updateDim(Location.BOUNDARY, Location.INTERIOR, Dimension.L);
+      updateDim(Location.BOUNDARY, Location.BOUNDARY, Dimension.P);
+      updateDim(Location.BOUNDARY, Location.EXTERIOR, Dimension.L);
+      updateDim(Location.EXTERIOR, Location.INTERIOR, Dimension.A);
+      updateDim(Location.EXTERIOR, Location.BOUNDARY, Dimension.L);
+    }
+  }
+
   public void addIntersection(NodeSection a, NodeSection b) {
     if (! a.isSameGeometry(b)) {
       updateIntersectionAB(a, b);
```
</details>

Results with this change:

- **This report's cases.** Both cases above give `212101212`.
- **Generated corpus.** A differential run against an exact oracle, over 20,000 generated valid polygon pairs, found 29 pairs where `RelateNG` gives wrong predicates and RelateOp is correct.
  - Of the 29, 13 give `FF2F01212`, 12 give `212F01FF2` and 4 give `2FF10F212`.
  - With the change, all 29 give the exact `212101212`, and no new disagreement with the oracle appears on the 20,000 pairs.
- **Unit tests.** The `operation/relateng` JUnit tests run 154 tests with 2 failures: `RelateNGRobustnessTest.testPostGIS_5362` and `testGISSE_484691`, which expected `2F2101212` and now get `212101212`. That is the exact answer (see below).

## Related

- **The `2F2101212` test expectations.** `RelateNGRobustnessTest.testPostGIS_5362` ([#L164](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/test/java/org/locationtech/jts/operation/relateng/RelateNGRobustnessTest.java#L164)) and `testGISSE_484691` ([#L199](https://github.com/locationtech/jts/blob/3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd/modules/core/src/test/java/org/locationtech/jts/operation/relateng/RelateNGRobustnessTest.java#L199)) assert this matrix.
  - The exact matrix for both inputs is `212101212`: the polygons overlap by about 1.2e-21 and 4.1e-33.
  - `2F2101212` is impossible for two valid polygons: if A's connected interior meets both B's interior and B's exterior, it must meet B's boundary, so IB ≠ F.
  - The predicates are still correct on master (`overlaps` = true, `touches` = false). Only the matrix is inconsistent.
  - RelateOp returns `212101212` for PostGIS ticket 5362 and throws a TopologyException for 484691.
- **libgeos/geos#1018 (closed).** RelateNG returns `2F2F01212` for that input, which is impossible for the same reason. The exact matrix and RelateOp's answer are both `212101212`, and the predicates are correct. The change above also gives `212101212` there.
- **#1106 (point/line orientation robustness).** This is related but different: here the orientation tests are exact and correct, and RelateNG discards their result.
- **Searches.** I found no existing report of this behaviour. I searched JTS and GEOS issues and PRs (RelateNG, touches/overlaps/contains/covers, robustness), and read #1079, #1106, libgeos/geos#1060 and libgeos/geos#1275.

---

This was found by differential testing against an exact rational-arithmetic oracle ([geotruth](https://github.com/abafaboy/geotruth)).
