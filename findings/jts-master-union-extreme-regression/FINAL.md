# KdTree: squared snap tolerance overflows, so OverlayNGRobust returns POLYGON EMPTY for large coordinates (regression in master since #1114)

*Draft issue for locationtech/jts. Not filed.*

## Summary

Since #1114 (commit 4668803, "Add KdTree nearestNeighbor() and nearestNeighbors()"),
`KdTree.insertExact` decides whether a point is within the snap tolerance of a node by
comparing squared values: `p.distanceSq(node) <= toleranceSq`, where
`toleranceSq = tolerance * tolerance`.

For a tolerance above sqrt(Double.MAX_VALUE) ≈ 1.34e154, `toleranceSq` is `+Infinity`. Every
point then counts as "within tolerance" of the root node. All inserted points are merged,
however far apart they are.

`OverlayNGRobust` reaches this through its snapping fallback. The snap tolerance there is
(coordinate magnitude) / 1e12, increased 10× per try. Once a large-coordinate overlay needs
that fallback, `snapSelf` collapses each operand to EMPTY, and the operation returns
`POLYGON EMPTY` without an exception. JTS 1.20.0 returns the correct result for the same
inputs.

Before #1114 the test was `p.distance(node) <= tolerance`. A distance that overflows is
`Infinity`, which fails that test, so the large-tolerance merging only started when the
tolerance itself was squared.

The inputs are valid, with finite ordinates of about 1e170. These magnitudes are unusual in GIS
data, so this is low priority. It is a regression in unreleased code, though, and has a small
fix, so it seems worth fixing before 1.21.

## Minimal reproduction

```java
import org.locationtech.jts.geom.*;
import org.locationtech.jts.index.kdtree.KdTree;
import org.locationtech.jts.io.WKTReader;
import org.locationtech.jts.operation.overlayng.*;

Geometry a = new WKTReader().read("POLYGON ((0 0, 2e170 1e170, 1e170 2e170, 0 0))");
OverlayNGRobust.overlay(a, a, OverlayNG.UNION);         // master: POLYGON EMPTY      1.20.0: a
OverlayNGRobust.overlay(a, a, OverlayNG.INTERSECTION);  // master: POLYGON EMPTY      1.20.0: a

Geometry b = new WKTReader().read("LINESTRING (3e170 0, 4e170 0)");   // disjoint from a
OverlayNGRobust.overlay(a, b, OverlayNG.UNION);         // master: POLYGON EMPTY      expected GEOMETRYCOLLECTION (a, b)
OverlayNGRobust.overlay(a, b, OverlayNG.DIFFERENCE);    // master: POLYGON EMPTY      expected a

KdTree t = new KdTree(1e155);
t.insert(new Coordinate(0, 0));
t.insert(new Coordinate(1e300, 0));
t.size();                                                // master: 1                  1.20.0: 2
```

With `-Djts.overlay=ng`, `a.union(a)` also returns `POLYGON EMPTY` on master.

A complete program is attached (`Repro.java`, public API only; `javac -cp jts-core.jar Repro.java
&& java -cp jts-core.jar:. Repro`). It also runs the input where we first saw this: a triangle
and a MultiLineString with ordinates around 3.8e220, where master's union, difference and
symdifference are all `POLYGON EMPTY`. It also checks the tolerance-0 case at the tiny end,
which is older than #1114 (see point 6 below).

## Expected vs actual

`OverlayNGRobust.overlay`, A = `POLYGON ((0 0, 2e170 1e170, 1e170 2e170, 0 0))`, B = `LINESTRING (3e170 0, 4e170 0)`:

| call | expected (= 1.20.0) | master 3ea61f8 |
|---|---|---|
| union(A, A), intersection(A, A) | A | `POLYGON EMPTY` |
| union(A, B), symdifference(A, B) | `GEOMETRYCOLLECTION (A, B)` | `POLYGON EMPTY` |
| difference(A, B) | A | `POLYGON EMPTY` |
| `new KdTree(1e155)`, insert (0 0), (1e300 0): size | 2 | 1 |

The expected answers were checked with exact rational arithmetic. A is 1e170 times the triangle
(0 0, 2 1, 1 2) exactly, since the double 2e170 is 2 × the double 1e170. At unit scale every
build agrees.

Scaling this triangle by 2^k (exact) and computing union(A·2^k, A·2^k) gives:

- master: correct up to k = 510, correct up to snap-rounding for k = 511..537, and
  **`POLYGON EMPTY` from k = 538** (max ordinate 2^539 ≈ 1.8e162);
- 1.20.0: correct, or correct up to rounding, for every k up to 1022.

The threshold of about 1.3e162 was measured for these inputs. It depends on which snapping try
is the first to produce a result (point 5 below), so it can differ for other inputs.

## Versions

- master `3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd` (current head): wrong.
- 1.20.0 (`6e95fe82`): correct.
- Bisected (javac build of `modules/core` per commit, check: union non-empty) on the
  3.8e220 input to **4668803bdf3c460c1ab35f8c0ba00752e0b3edd4** "Add KdTree nearestNeighbor() and
  nearestNeighbors() (#1114)". The triangle A above is also correct at 4668803^ and
  `POLYGON EMPTY` at 4668803.
- For the 3.8e220 input scaled down to about 1.5e162, the bisect lands on 52c5d988 (#1187)
  instead; see point 5 below for why. This applies to that input only: the triangle A is
  already empty from k = 538 at 4668803, before #1187.

## Analysis

`OverlayNGRobust.overlay` falls back to snapping when the floating overlay throws.

1. **Why the fallback runs.** With coordinates this large, `Geometry.getArea()` overflows. For
   these rings the shoelace terms are +inf and −inf, so the area is `NaN`. Then
   `OverlayUtil.isResultAreaConsistent` (`OverlayUtil.java:390-419`, checked at
   `OverlayNG.java:521-523`) rejects every polygonal result: "Result area inconsistent with
   overlay operation". This also happens in 1.20.0, and on its own it is harmless: it only
   forces the fallback.
2. **The fallback chain.** `overlaySnapTries` (`OverlayNGRobust.java:180-201`) uses
   `snapTol = magnitude / 1e12` (`:283`, `:302`), multiplied by 10 on each of five tries (`:197`).
   `overlaySnapBoth` first self-snaps each operand with a `SnappingNoder` (`snapSelf`, `:259`),
   whose point index is a `new KdTree(snapTol)` (`SnappingPointIndex.java:42`).
3. **The overflow.** `KdTree` now stores `toleranceSq = tolerance*tolerance`
   (`KdTree.java:97`, `:117`). `insertExact` merges a point into a node when
   `p.distanceSq(curr.getCoordinate()) <= toleranceSq` (`:424-425`). Once `snapTol` exceeds
   1.34e154, `toleranceSq` is `Infinity`, the test is always true, and all vertices of an operand
   merge into the first one.
4. **The result.** Each operand self-snaps to EMPTY. The overlay of the two empties is
   `POLYGON EMPTY`, which trivially passes the area check, and `overlaySnapBoth` returns it as
   the result.
5. **The threshold.** For magnitudes above about 1.34e166 the first try already overflows. Below
   that, down to about 1.34e162, only the later tries overflow (just above 1.34e162, only the
   fifth, with tolerance magnitude × 1e-8), so the outcome depends on whether one of the earlier
   tries produces a result.
   - For the triangle A scaled into this range, none of them does, so master is empty from about
     1.3e162. That is already the case at 4668803, so for this input #1114 alone sets the
     threshold.
   - For the 3.8e220 input scaled to 1.5e162, 1.20.0's `snapSelf` returned the triangle with a
     rotated start vertex. The rotated ring's area is `+Infinity` rather than `NaN`, so the area
     check passed and the first try gave the correct result. #1187 (which is correct in itself)
     keeps the ring start, so the area stays `NaN`, tries 0-3 fail, and try 4 hits the overflow.
     This is why the bisect on that 1.5e162 copy stops at #1187.
6. **The tiny end: related, but older than #1114.** For distinct points closer than about
   1.5e-162, `distanceSq` underflows to 0, so they satisfy `0 <= toleranceSq` and are merged,
   even with tolerance 0 (`HotPixelIndex` uses `new KdTree()`). This is not new with #1114. The
   previous test, `p.distance(node) <= tolerance`, underflowed the same way once #1112 made
   `Coordinate.distance` use `MathUtil.hypot` (`sqrt(dx*dx + dy*dy)`), and 1.19.0 and earlier
   also computed the distance as `Math.sqrt(dx * dx + dy * dy)`. Only 1.20.0, with `Math.hypot`
   from #923, keeps such points apart. For `new KdTree(0.0)` with (0 0) and (1e-170 0):

   | build | nodes |
   |---|---|
   | 1.18.0 | 1 |
   | 1.20.0 | 2 |
   | aa755818^ (before #1112) | 2 |
   | aa755818 (#1112), 4668803^, master | 1 |

   The fix below happens to cover this end as well.

## Suggested fix

Avoid squaring in the tolerance test of `insertExact`. The per-axis pre-check keeps the common
case cheap (most nodes fail it), keeps tolerance 0 exact, and calls `Math.hypot` only for
candidates inside the tolerance box:

```java
  private boolean isWithinTolerance(Coordinate p, Coordinate q) {
    double dx = Math.abs(p.x - q.x);
    double dy = Math.abs(p.y - q.y);
    if (dx > tolerance || dy > tolerance)
      return false;
    return Math.hypot(dx, dy) <= tolerance;
  }
```

`prototype_fix.diff` applies this to `KdTree.insertExact`, removes `toleranceSq`, and adds
three tests:

- `KdTreeTest.testLargeToleranceDoesNotSnapDistantPoints`, for the #1114 regression;
- `KdTreeTest.testZeroToleranceKeepsTinyDistinctPoints`, for the older tiny-end behaviour of
  point 6 (it also fails before #1114, since #1112);
- `OverlayNGRobustTest.testLargeCoordinatesSelfUnion`, for the #1114 regression.

With the patch:

- **Core tests.** The core JUnit tests give the same results as on unpatched master, and the
  three new tests, which fail on unpatched master, pass.
- **Scans.** The scaling scans no longer produce empty results. The union is exact, or
  snap-rounded where the fallback runs.

The new `nearestNeighbor`/`nearestNeighbors` rank candidates by `distanceSq` as well. When all
distances overflow to `Infinity`, `nearestNeighbor` returns `null` for a non-empty tree. This is
minor, but the same scaled comparison, or `Math.hypot` for ties, would avoid it.

(Context: #1112 made `Coordinate.distance` use the naive `MathUtil.hypot`, as a deliberate speed
trade-off, so on master distances and lengths above 1.34e154 are `Infinity` and those below
about 1.5e-162 are 0. The second is where the tiny-end merging of point 6 comes from. It does
not cause the large-coordinate bug, and the fix above only touches `KdTree`.)

## Related issues

- #1114, the PR that introduced `toleranceSq`: there was no discussion of range there.
- #1112 / #1110 (`MathUtil.hypot`): the source of the tiny-end behaviour on master (point 6).
  #923 had introduced `Math.hypot` in `Coordinate.distance`, which is why 1.20.0 alone keeps
  tiny distinct points apart.
- #1187 (ring start): changes which inputs reach the overflow (point 5).
- #951 (the area-check heuristic with a snapping noder): a different trigger, at small
  magnitudes.
- #1197 (open PR, not merged) describes the DD orientation predicate as sound only for
  coordinates of roughly 2^-511 to 2^511 (about 1.5e-154 to 6.7e153). The inputs here are
  outside that band, so you may well consider them out of range. The point of this report is
  that master now returns `POLYGON EMPTY` silently where 1.20.0 returned the right answer.
- #295 is an earlier report about extreme coordinate values. It is not the same problem.
- NetTopologySuite/NetTopologySuite#814 and the open PR NetTopologySuite/NetTopologySuite#848
  port #1114's `nearestNeighbor`, but leave `insert`/`insertExact` unchanged, so NTS does not
  have this problem at present.

No existing issue reports this. The searches covered locationtech/jts issues and PRs, open and
closed: KdTree tolerance/overflow, empty overlay results, large coordinates, and the area-check
message.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
