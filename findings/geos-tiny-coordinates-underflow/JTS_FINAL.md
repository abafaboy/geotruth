**Title:** Overlay and relate are wrong for coordinates beyond about 1e±103 (`CGAlgorithmsDD.intersection` overflow/underflow)

---

This is low priority, since coordinates this large or small are unusual in GIS data. I'm reporting it because the results are silently wrong, or an exception is thrown, for simple, valid input. I couldn't find a documented range of supported coordinate magnitudes. Every input below is valid and uses finite, normal doubles.

### Summary

`RobustLineIntersector` computes every proper crossing with `CGAlgorithmsDD.intersection`. That method builds homogeneous-coordinate terms that are cubic in the input coordinates:
- Above about ∛Double.MAX_VALUE ≈ 5.6e102, those terms overflow, and the method returns `null`.
- Below about ∛Double.MIN_NORMAL ≈ 2.8e-103, they become subnormal and lose precision. From about 1.7e-108 they are zero.

On overflow, `RobustLineIntersector` replaces the point with the nearest segment endpoint. On underflow it does the same whenever the imprecise point falls outside the segment envelopes; for axis-parallel segments, any error at all does that. So two overlapping squares get a wrong intersection from S = 1e103 up and from S = 1e-103 down. At S = 1e105 or 1e-104:
- `RelateNG` reports B as covered by A;
- `Geometry.relate` (`RelateOp`) throws `TopologyException: side location conflict`;
- `OverlayNGRobust` returns a LineString as the intersection.

At these scales the orientation predicate is still exact for these shapes. Only the intersection point is wrong.

### Reproducer

```java
import org.locationtech.jts.algorithm.*;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.*;
import org.locationtech.jts.operation.relateng.RelateNG;

public class ExtremeScale {
  public static void main(String[] args) throws Exception {
    WKTReader r = new WKTReader();
    for (String e : new String[] {"e102", "e103", "e105", "e-104"}) {
      String S = "1" + e, S2 = "2" + e, S3 = "3" + e;
      Geometry a = r.read("POLYGON ((0 0, " + S2 + " 0, " + S2 + " " + S2 + ", 0 " + S2 + ", 0 0))");
      Geometry b = r.read("POLYGON ((" + S + " " + S + ", " + S3 + " " + S + ", " + S3 + " " + S3 + ", " + S + " " + S3 + ", " + S + " " + S + "))");
      double s = Double.parseDouble(S);
      Geometry inter = OverlayNGRobust.overlay(a, b, OverlayNG.INTERSECTION).copy();
      inter.apply((CoordinateFilter) c -> { c.x /= s; c.y /= s; });   // print in units of S
      String relOp;
      try { relOp = a.relate(b).toString(); } catch (Exception ex) { relOp = ex.getClass().getSimpleName() + " " + ex.getMessage(); }
      RobustLineIntersector li = new RobustLineIntersector();
      li.computeIntersection(new Coordinate(0, 0), new Coordinate(4 * s, 2 * s), new Coordinate(0, 2 * s), new Coordinate(4 * s, 0));
      Coordinate p = li.getIntersection(0);
      System.out.println("S = " + S + ": RelateNG " + RelateNG.relate(a, b) + ", Geometry.relate " + relOp
          + ", intersection/S " + inter + ", crossing/S (" + p.x / s + " " + p.y / s + ")");
    }
    System.out.println("Orientation.index((0 0),(S 0),(0 S)), S = 1e-200: "
        + Orientation.index(new Coordinate(0, 0), new Coordinate(1e-200, 0), new Coordinate(0, 1e-200)));
  }
}
```

Output on master 3ea61f8:

```
S = 1e102: RelateNG 212101212, Geometry.relate 212101212, intersection/S POLYGON ((1 2, 2 2, 2 1, 1 1, 1 2)), crossing/S (2.0 1.0)
S = 1e103: RelateNG 212101212, Geometry.relate 212101212, intersection/S POLYGON ((2 2, 2 0, 1 1, 2 2)), crossing/S (0.0 0.0)
S = 1e105: RelateNG 212F01FF2, Geometry.relate TopologyException side location conflict [ (1.0E105, 1.0E105, NaN) ], intersection/S LINESTRING (1 1, 2 2), crossing/S (0.0 0.0)
S = 1e-104: RelateNG 212F01FF2, Geometry.relate TopologyException side location conflict [ (1.0E-104, 1.0E-104, NaN) ], intersection/S LINESTRING (1 1, 2 2), crossing/S (2.000000000000019 1.0000000000000095)
Orientation.index((0 0),(S 0),(0 S)), S = 1e-200: 0
```

Expected at every S:
- relate `212101212`;
- intersection/S `POLYGON ((1 1, 1 2, 2 2, 2 1, 1 1))`, i.e. A ∩ B = [S,2S]²;
- crossing/S `(2 1)`;
- orientation `1`.

JTS 1.20.0 gives the same results, apart from vertex order.

The segment crossing on its own, (0 0)-(4S 2S) × (0 2S)-(4S 0), gives:
- (2 1) at S = 1e102;
- (0 0) at S = 1e103 and above;
- 1e-10 relative error at S = 1e-105;
- (0 0) from S ≈ 1e-109 down.

### Analysis

`CGAlgorithmsDD.intersection` (`modules/core/src/main/java/org/locationtech/jts/algorithm/CGAlgorithmsDD.java:196-220`) computes:
- `pw` and `qw` (lines 202 and 206), which are products of absolute coordinates;
- `x` and `y` (lines 208-209), which multiply those products by coordinate differences, so they are cubic;
- `w` (line 210), which is quadratic.

`DD` has the same exponent range as `double`, so the extra precision does not help here:
- On overflow, the result is NaN and lines 215-217 return `null`. `RobustLineIntersector.intersectionSafe` (`RobustLineIntersector.java:281-283`) then uses `nearestEndpoint()`.
- On underflow, the point is slightly off. For axis-parallel segments even a 1-ulp error falls outside the zero-width segment envelope, so `RobustLineIntersector.intersection` (lines 237-242) also substitutes `nearestEndpoint()`.

In the squares case, all four endpoints are exactly S from the other segment, so which endpoint is chosen comes down to rounding. `Intersection.intersection` (`Intersection.java:47`) delegates to `CGAlgorithmsDD.intersection`.

**Possible fix.** Scale the inputs by a power of two before the computation and scale the result back. This is exact and cheap. I tried this in the GEOS port of this method (a diagnostic prototype, not benchmarked). There, every example above gives the expected answer, and GEOS's test suite still passes.

### Related: orientation for very small coordinates

`Orientation.index((0 0), (S 0), (0 S))` returns 0 for S ≤ 1.5e-162. For S = 1.6e-162 it correctly returns 1. `IsValidOp` then reports a right triangle as invalid:

```
POLYGON ((0 0, 1.6e-162 0, 0 1.6e-162, 0 0)) -> isValid true
POLYGON ((0 0, 1.5e-162 0, 0 1.5e-162, 0 0)) -> isValid false, "Self-intersection at or near point (0.0, 0.0, NaN)"
```

At S = 1e-200, with A = [0,2S]², B = [S,3S]², P = (S S) and H = [0,4S]² with the hole [S,2S]²:
- `IsValidOp(H)` throws `IllegalArgumentException: Segment vertex does not intersect ring`;
- `A.relate(P)` = `FF20F1FF2` (expected `0F2FF1FF2`);
- `RelateNG.relate(A, B)` = `FF2F01FF2` and `A.relate(B)` = `FF2212FF2` (expected `212101212`);
- the `OverlayNGRobust` intersection and union return B and A.

Here is why:
1. The products in `orientationIndexFilter` (`CGAlgorithmsDD.java:145-146`) round to 0.
2. The filter returns `signum(det) = 0` when `detleft == 0` (lines 165-167).
3. The DD path (lines 69-75) could not recover in any case, because its products underflow the same way.

For near-collinear triples the failures start earlier, from about 2^-510 (≈1e-154), and sometimes give the opposite sign. I took 20,000 random near-collinear triples that are classified correctly at unit scale and scaled them exactly by 2^-515. `Orientation.index` returns 0 for 14,293 of them and the opposite sign for 1,690.

On the large side, failures start at about 2^508 (≈1e153). There the DD products overflow to NaN, and `DD.signum()` (`DD.java:679-686`) returns 0 for NaN.

The JTS Technical Specifications say that Line Orientation and Line Intersection are implemented with robust algorithms and that "the binary predicate algorithm is completely robust". They do not mention a range of coordinate magnitudes. If these magnitudes are out of scope, a documentation note would help.

### Versions

- JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd (1.21.0-SNAPSHOT, upstream HEAD on 2026-09-26): reproduces.
- JTS 1.20.0: reproduces.
- GEOS, which ports this code, gives the same results (3.11.4 through 3.15.0 and main).

Tested with OpenJDK 21 on Linux x86-64.

### Related issues

- #745 (closed): wrong `contains` when very large and very small coordinates are mixed in one input. This is a different mechanism: here all coordinates have the same magnitude.

I found no existing issue about overflow or underflow in `CGAlgorithmsDD.intersection`.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
