**Title:** Overlay and relate are wrong for coordinates beyond about 1e±103 (`CGAlgorithmsDD::intersection` overflow/underflow), plus related orientation range limits

---

This is low priority, since coordinates this large or small are unusual in GIS data. I'm filing it because the results are silently wrong for simple, valid input, and I couldn't find a documented range of supported coordinate magnitudes. Every input below is OGC-valid and uses finite, normal doubles.

### Summary

`LineIntersector` computes every proper segment crossing with `CGAlgorithmsDD::intersection`. That function builds homogeneous-coordinate terms that are cubic in the input coordinates:
- Above about ∛DBL_MAX ≈ 5.6e102, those terms overflow and the point comes back as NaN.
- Below about ∛DBL_MIN ≈ 2.8e-103, they become subnormal and lose precision. From about 1.7e-108 (the cube root of the smallest subnormal) they are zero.

On overflow, `LineIntersector` replaces the point with the nearest segment endpoint. On underflow it does the same whenever the imprecise point falls outside the segment envelopes; for axis-parallel segments, any error at all does that. As a result, two overlapping squares get a wrong intersection and union from S = 1e103 up and from S = 1e-103 down. At some scales relate is wrong too. Only the intersection point is at fault here: for these shapes, the orientation predicate stays exact from about 1e-162 up to about 1e153. This goes back to at least 3.11.

Two related orientation issues follow (sections 2 and 3):
- a 3.14.0 regression for |coordinates| ≳ 1e154, from #1184;
- the tiny-coordinate limitation of the filter, which #1184 already mentions.

### 1. Segment intersection point (all versions tested)

```
$ A='POLYGON ((0 0, 2e105 0, 2e105 2e105, 0 2e105, 0 0))'
$ B='POLYGON ((1e105 1e105, 3e105 1e105, 3e105 3e105, 1e105 3e105, 1e105 1e105))'
$ geosop -a "$A" -b "$B" relate
212F01FF2
$ geosop -a "$A" -b "$B" overlaps
false
$ geosop -a "$A" -b "$B" intersection
LINESTRING (1e+105 1e+105, 2e+105 2e+105)
$ geosop -a "$A" -b "$B" union
MULTIPOLYGON (((1e+105 1e+105, 2e+105 0, 0 0, 0 2e+105, 1e+105 1e+105)), ((1e+105 1e+105, 1e+105 3e+105, 3e+105 3e+105, 3e+105 1e+105, 1e+105 1e+105)))
```

Expected: relate `212101212`; overlaps `true`; intersection the square `[1e105, 2e105]²`; union `POLYGON ((0 0, 0 2S, S 2S, S 3S, 3S 3S, 3S S, 2S S, 2S 0, 0 0))` with S = 1e105. The same shapes with other scales S (A = [0,2S]², B = [S,3S]²):

| S | relate(A,B) | intersection(A,B) |
|---|---|---|
| 1e102 | `212101212` (correct) | `POLYGON ((1e+102 2e+102, 2e+102 2e+102, 2e+102 1e+102, 1e+102 1e+102, 1e+102 2e+102))` (correct) |
| 1e103 | `212101212` (correct) | `POLYGON ((2e+103 2e+103, 2e+103 0, 1e+103 1e+103, 2e+103 2e+103))`: a triangle with the vertex (2S 0), which is outside B |
| 1e105 | `212F01FF2` | `LINESTRING (1e+105 1e+105, 2e+105 2e+105)` |
| 1e-104 | `212F01FF2` | `LINESTRING (1e-104 1e-104, 2e-104 2e-104)` |

A scan over S = 10^k shows the intersection and union of these squares are wrong for every k in [103, 307] and in [-307, -103], and correct for |k| ≤ 102. Relate is additionally wrong at k = -116, -104, 105 and 126.

The primitive, through the C API:

```c
#include <stdio.h>
#include <geos_c.h>
int main(void) {
    initGEOS(NULL, NULL);
    const double scales[] = {1e102, 1e103, 1e-105, 1e-110};
    for (int i = 0; i < 4; i++) {
        double S = scales[i], x, y;
        /* (0 0)-(4S 2S) crosses (0 2S)-(4S 0) at (2S S) */
        int r = GEOSSegmentIntersection(0, 0, 4*S, 2*S, 0, 2*S, 4*S, 0, &x, &y);
        printf("S=%g: r=%d, point/S = (%.12g %.12g)   expected (2 1)\n", S, r, x / S, y / S);
    }
    finishGEOS();
    return 0;
}
```
```
S=1e+102: r=1, point/S = (2 1)   expected (2 1)
S=1e+103: r=1, point/S = (0 0)   expected (2 1)
S=1e-105: r=1, point/S = (1.99999999974 1.00000000003)   expected (2 1)
S=1e-110: r=1, point/S = (0 0)   expected (2 1)
```

**Analysis.** `CGAlgorithmsDD::intersection` is in `src/algorithm/CGAlgorithmsDD.cpp:116-148`. Its terms scale as follows:
- `pw` and `qw` (lines 132 and 136) are products of absolute coordinates;
- `x` and `y` (lines 138-139) are those products multiplied again by coordinate differences, so they are cubic;
- `w` (line 140) is quadratic.

`DD` has the same exponent range as `double`, so the extra precision does not help here. For the squares' crossing (2S 0)-(2S 2S) × (S S)-(3S S), the raw result divided by S is:
- (2, 1) at S = 1e102;
- (NaN, NaN) at S = 1e103 and 1e105;
- (2, 0.99999999999999933) at S = 1e-103.

`LineIntersector::intersectionSafe` (`include/geos/algorithm/LineIntersector.h:594-596`) replaces a null result with `nearestEndpoint()`. `LineIntersector::intersection` (lines 549-551) does the same for a point outside the segment envelopes. For axis-parallel segments the envelope has zero width, so even a 1-ulp error triggers the fallback. That is why the squares already fail at 1e-103. In this configuration all four endpoints are exactly S from the other segment, so which endpoint is chosen comes down to rounding.

**Possible fix.** Scale the inputs by a power of two before the computation and scale the result back. This is exact and cheap. I tried it in a diagnostic prototype (hunk below). Every example in this section then gives the expected answer: the squares at 1e103, 1e105 and 1e-104, and the C program. The prototype's other change, to `orientationIndex` (section 3), is not triggered by these inputs. I have not benchmarked it.

<details><summary>Prototype hunk (diagnostic, not proposed as-is)</summary>

```diff
@@ CGAlgorithmsDD::intersection(const CoordinateXY& p1, const CoordinateXY& p2,
                              const CoordinateXY& q1, const CoordinateXY& q2)
 {
+    // The formula below has cubic terms in the coordinates, which underflow or
+    // overflow for |coordinates| below ~1e-103 or above ~1e103.
+    // Compute on copies scaled by a power of two and scale the result back.
+    {
+        double m = std::max({std::abs(p1.x), std::abs(p1.y), std::abs(p2.x), std::abs(p2.y),
+                             std::abs(q1.x), std::abs(q1.y), std::abs(q2.x), std::abs(q2.y)});
+        if (m > 0 && std::isfinite(m) && (m < 0x1p-300 || m > 0x1p300)) {
+            int e = -std::ilogb(m);
+            auto sc = [e](const CoordinateXY& c) { return CoordinateXY(std::ldexp(c.x, e), std::ldexp(c.y, e)); };
+            CoordinateXY r = intersection(sc(p1), sc(p2), sc(q1), sc(q2));
+            if (r.isNull()) return r;
+            return CoordinateXY(std::ldexp(r.x, -e), std::ldexp(r.y, -e));
+        }
+    }
     DD q1x(q1.x);
```
</details>

### 2. Orientation for |coordinates| ≳ 1e154: regression in 3.14.0 (#1184)

```
$ geosop -a 'LINESTRING (2 0, 2 2)' -b 'POINT (1 1)' orientationIndex
1
$ geosop -a 'LINESTRING (2e155 0, 2e155 2e155)' -b 'POINT (1e155 1e155)' orientationIndex
0
$ geosop -a 'POLYGON ((0 0, 2e155 0, 2e155 2e155, 0 2e155, 0 0))' -b 'POINT (1e155 1e155)' contains
false
$ geosop -a 'POLYGON ((0 0, 2e155 0, 2e155 2e155, 0 2e155, 0 0))' -b 'POLYGON ((1e155 1e155, 3e155 1e155, 3e155 3e155, 1e155 3e155, 1e155 1e155))' relate
FF2F01FF2
$ geosop -a 'POLYGON ((0 0, 4e154 0, 4e154 4e154, 0 4e154, 0 0), (1e154 1e154, 1e154 2e154, 2e154 2e154, 2e154 1e154, 1e154 1e154))' isValid
Run-time exception: IllegalArgumentException: Segment vertex does not intersect ring
```

The first command is the unit-scale control. For the four scaled cases, the expected answers are 1, true, `212101212` and true. Those inputs are the unit-scale shapes multiplied by 1e155 or 1e154.

`GEOSOrientationIndex((2S 0), (2S 2S), (S S))` at S = 1e155 and at S = 1e300:
- returns 1 on 3.11.4, 3.13.1 and JTS;
- returns 0 on 3.14.1, 3.15.0 and main.

Via Shapely, contains, relate and isValid for the shapes above are correct up to S = 1e300 on 3.11.4 and 3.13.1. On 3.14.1 and later they are wrong from 1e155 on (isValid of the polygon with a hole from 1e154).

**Cause.**
1. The single-branch filter (`include/geos/algorithm/CGAlgorithmsDD.h:102-110`) gets `detleft = +inf` and `detright = -inf`. So `det = +inf`, which has the correct sign, but `error = |inf + -inf|·c = NaN`.
2. The test `std::abs(det) >= error` (line 108) is false, so the filter defers to the DD stage.
3. In the DD stage (`src/algorithm/CGAlgorithmsDD.cpp:70-79`), `dy1*dx2` overflows to NaN. `OrientationDD` (lines 32-44) maps NaN to `STRAIGHT`.

The pre-3.14 filter returned `sign(det)` immediately when `detleft` and `detright` had opposite signs, so this input never reached the DD stage. JTS still does this.

#1184 says "The filter will be correct for overflows". The filter itself doesn't return a wrong sign here. It defers, but the exact stage it defers to cannot handle the overflow either.

The DD stage has never handled overflow. On 3.13.1 as well, near-collinear triples, where deferring is necessary, start returning 0 at about 2^508 (≈1e153). By 2^600, all of 20,000 random such triples return 0.

**Possible fix.** Check for opposite signs only after the bound test has failed, i.e. off the fast path. For opposite signs the bound test can only fail when the bound is NaN, so this would restore the 3.13 behaviour for this input without adding a branch to the common case.

### 3. Tiny coordinates (the underflow case noted in #1184)

#1184 says the filter is "some times incorrect for underflows (intentional omission because it costs some cycles and filter failures and is not covered by the exact stage in geos anyways as far as I can see)". So I'm not reporting this as a new defect. I'm including it because of what it causes downstream, which may be worth documenting:

```
$ geosop -a 'LINESTRING (0 0, 1e-200 0)' -b 'POINT (0 1e-200)' orientationIndex
0
$ geosop -a 'POLYGON ((0 0, 1.6e-162 0, 0 1.6e-162, 0 0))' isValid
true
$ geosop -a 'POLYGON ((0 0, 1.5e-162 0, 0 1.5e-162, 0 0))' isValid
false
$ geosop -a 'POLYGON ((0 0, 4e-200 0, 4e-200 4e-200, 0 4e-200, 0 0), (1e-200 1e-200, 1e-200 2e-200, 2e-200 2e-200, 2e-200 1e-200, 1e-200 1e-200))' isValid
Run-time exception: IllegalArgumentException: Segment vertex does not intersect ring
$ geosop -a 'POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))' -b 'POINT (1e-200 1e-200)' contains
false
$ geosop -a 'POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))' -b 'POLYGON ((1e-200 1e-200, 3e-200 1e-200, 3e-200 3e-200, 1e-200 3e-200, 1e-200 1e-200))' relate
FF2F01FF2
```

Expected: 1; true; true (a right triangle); true; true (the centre of the square); `212101212`.

For well-separated points, the threshold is where the products of coordinate differences round to 0: (1.5e-162)² rounds to 0, while (1.6e-162)² rounds to 4.9e-324, the smallest subnormal. Then `detleft = detright = 0`, so `det = error = 0`, and the filter returns 0 as a final answer. The DD stage has the same exponent range, so it could not recover even if the filter deferred.

Near-degenerate input fails earlier, from about 2^-510 (≈1e-154), and sometimes with the opposite sign. I took 20,000 random near-collinear triples that are classified correctly at unit scale and scaled them exactly by 2^-515:
- main returns 0 for 15,541 of them and the opposite sign for 1,015;
- 3.13.1 returns 0 for 14,293 and the opposite sign for 1,690.

So wrong-side answers predate #1184.

If this range is out of scope, a sentence in the docs (for example the FAQ robustness section or the `PrecisionModel` / C API docs) would help users. Alternatively, rescaling by a power of two could fix it, for example only on the DD path, with the filter deferring when its bound underflows. That has a cost, which #1184 chose to avoid.

For reference, I also tried a diagnostic prototype that rescales in both `intersection` and `orientationIndex`. The `orientationIndex` part applies when coordinate differences are outside [2^-400, 2^400], and it is placed ahead of the fast filter. With it:
- every example in this report gives the expected answer;
- `ctest` passes 535/535.

It has not been benchmarked. Also, in a full scan the union of the squares at some S ≥ 1e155 still has vertices 1-2 ulps off, which I did not investigate.

### Expected answers

All shapes are axis-parallel squares, a right triangle, or a square with a hole strictly inside it. The expected results follow from inspection, for example A ∩ B = [S,2S]². They do not depend on how the decimal literals round. I also checked them with an exact rational implementation.

### Versions tested

| version | (1) intersection | (2) large-side orientation | (3) tiny-side orientation |
|---|---|---|---|
| GEOS main ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (3.16.0dev, upstream HEAD on 2026-09-26) | yes | yes | yes |
| GEOS 3.15.0 (output identical to main) | yes | yes | yes |
| GEOS 3.14.1 (Shapely 2.2.0rc1 wheel) | yes | yes | yes |
| GEOS 3.13.1 (Shapely 2.1.2 wheel) | yes | no | yes |
| GEOS 3.11.4 (Shapely 2.0.7 wheel) | yes (relate at 1e105 throws `TopologyException: side location conflict`) | no | yes |
| JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd and 1.20.0 | yes | no | yes |

main and 3.15.0 were built from source (Linux x86-64, gcc, Release).

JTS has the same `CGAlgorithmsDD.intersection` and gives the same results for (1). Its `RelateOp` throws `side location conflict` at 1e105 and 1e-104. JTS also gives the same results for (3). It does not have (2), because it still uses the pre-#1184 filter.

### Related

- #1184, "Use Ozaki et al.'s error bound and single-branch evaluation in orientation index filter" (merged 2025-02-03, first released in 3.14.0). It introduced (2) and describes (3).
- #144 enabled the orientation filter in 2018.
- #970 / #973: a crash with large finite coordinates (e.g. 1e279), fixed in the WKT writer's number formatting.
- locationtech/jts#745 (closed): wrong `contains` when very large and very small coordinates are mixed in one input. This is a different mechanism.

I found no existing issue about overflow or underflow in segment intersection.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).

*Side note, unrelated (I can file it separately):* the doc comment of `GEOSOrientationIndex` (`capi/geos_c.h.in:6928`) says it returns -1 for a counter-clockwise (left) turn. The function returns 1 for a left turn, e.g. (0 0), (1 0), (0 1) → 1. The expected values above follow the implementation.
