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

At the other end, the same comparison merges distinct points closer than about 1.5e-162 even
with tolerance 0, because their squared distance underflows to 0. 1.20.0 compared
`distance <= tolerance` with `Math.hypot`, which has neither problem.

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
KdTree z = new KdTree(0.0);
z.insert(new Coordinate(0, 0));
z.insert(new Coordinate(1e-170, 0));
z.size();                                                // master: 1                  1.20.0: 2
```

With `-Djts.overlay=ng`, `a.union(a)` also returns `POLYGON EMPTY` on master.

A complete program is attached (`Repro.java`, public API only; `javac -cp jts-core.jar Repro.java
&& java -cp jts-core.jar:. Repro`). It also runs the input where we first saw this: a triangle
and a MultiLineString with ordinates around 3.8e220, where master's union, difference and
symdifference are all `POLYGON EMPTY`.

## Expected vs actual

`OverlayNGRobust.overlay`, A = `POLYGON ((0 0, 2e170 1e170, 1e170 2e170, 0 0))`, B = `LINESTRING (3e170 0, 4e170 0)`:

| call | expected (= 1.20.0) | master 3ea61f8 |
|---|---|---|
| union(A, A), intersection(A, A) | A | `POLYGON EMPTY` |
| union(A, B), symdifference(A, B) | `GEOMETRYCOLLECTION (A, B)` | `POLYGON EMPTY` |
| difference(A, B) | A | `POLYGON EMPTY` |
| `new KdTree(1e155)`, insert (0 0), (1e300 0): size | 2 | 1 |
| `new KdTree(0)`, insert (0 0), (1e-170 0): size | 2 | 1 |

The expected answers were checked with exact rational arithmetic. A is 1e170 times the triangle
(0 0, 2 1, 1 2) exactly, since the double 2e170 is 2 × the double 1e170. At unit scale every
build agrees.

Scaling the triangle by 2^k (exact) and computing union(A·2^k, A·2^k) gives:

- master: correct up to k = 510, correct up to snap-rounding for k = 511..537, and
  **`POLYGON EMPTY` from k = 538** (max ordinate 2^539 ≈ 1.8e162);
- 1.20.0: correct, or correct up to rounding, for every k up to 1022.

## Versions

- master `3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd` (current head): wrong.
- 1.20.0 (`6e95fe82`): correct.
- Bisected (javac build of `modules/core` per commit, check: union non-empty) to
  **4668803bdf3c460c1ab35f8c0ba00752e0b3edd4** "Add KdTree nearestNeighbor() and
  nearestNeighbors() (#1114)".
- For the same input scaled to about 1.5e162, the bisect lands on 52c5d988 (#1187); see the
  analysis below for why.

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
   that, down to about 1.34e162, only the fifth try (tolerance magnitude × 1e-8) overflows.
   - In 1.20.0, `snapSelf(A)` returned a rotated ring whose area is `+Infinity` rather than
     `NaN`, so the area check passed and the first try returned the correct result.
   - #1187 (which is correct in itself) keeps the ring start, so the area stays `NaN`. Tries
     0-3 fail and try 4 hits the overflow. This is why the bisect on the 1.5e162 copy stops at
     #1187.
6. **The tiny end.** For distinct points closer than about 1.5e-162, `distanceSq` underflows to
   0. They then satisfy `0 <= toleranceSq` and are merged. This holds for tolerance 0
   (`HotPixelIndex` uses `new KdTree()`) and for any tolerance whose square underflows, as the
   OverlayNGRobust snap tolerance does for such inputs. On a MultiPolygon/Point input scaled to
   ordinates of about 3e-162 and below, 1.20.0 throws `TopologyException`, while master returns
   `POLYGON EMPTY`. With the fix below, master behaves like 1.20.0 again.

Before #1114 the comparison was `p.distance(node) <= tolerance`. `Coordinate.distance` used
`Math.hypot` at the time, which does not overflow or underflow.

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

- `KdTreeTest.testLargeToleranceDoesNotSnapDistantPoints`;
- `KdTreeTest.testZeroToleranceKeepsTinyDistinctPoints`;
- `OverlayNGRobustTest.testLargeCoordinatesSelfUnion`.

With the patch:

- **Core tests.** The core JUnit tests give the same results as on unpatched master, and the
  three new tests, which fail on unpatched master, pass.
- **Scans.** The scaling scans no longer produce empty results. The union is exact, or
  snap-rounded where the fallback runs.

The new `nearestNeighbor`/`nearestNeighbors` rank candidates by `distanceSq` as well. When all
distances overflow to `Infinity`, `nearestNeighbor` returns `null` for a non-empty tree. This is
minor, but the same scaled comparison, or `Math.hypot` for ties, would avoid it.

(Context, not part of this report: #1112 made `Coordinate.distance` use the naive
`MathUtil.hypot`, as a deliberate speed trade-off, so lengths and distances above 1.34e154 are
now `Infinity` on master too. That does not cause this bug; the fix above only touches `KdTree`.)

## Related issues

- #1114, the PR that introduced `toleranceSq`: there was no discussion of range there.
- #1112 / #1110 (`MathUtil.hypot`) and #1187 (ring start): related changes, described above.
- #951 (the area-check heuristic with a snapping noder): a different trigger, at small
  magnitudes.

No existing issue reports this. The searches covered locationtech/jts issues and PRs, open and
closed: KdTree tolerance/overflow, empty overlay results, large coordinates, and the area-check
message.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
