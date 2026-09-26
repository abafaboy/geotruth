# PolyTree64: a hole whose vertices all touch its outer ring is still returned at the top level (follow-up to #973; regression since 1.5.3)

## Summary

When every vertex of a result ring lies on the boundary of the ring that contains it, `BuildTree64`
puts that ring one level too high:

- an inscribed **hole** becomes a second **top-level** node (`Level() == 1`, `IsHole() == false`),
  oriented clockwise, instead of a child of its outer ring;
- an inscribed **island** becomes a second **hole** of the outer ring (`IsHole() == true`), oriented
  counter-clockwise, instead of a child of the hole it lies in.

This is the symptom reported in #973 (a hole returned at the top level), and it comes from the same
commit, e8ebdef (the #957 fix, May 2025). #973's own input is correct on `main`, but this
configuration is not. 1.5.2, 1.4.0 and 1.2.4 are correct; 1.5.3, 1.5.4, 2.0.1 and `main` are
wrong. It affects `PolyTree64` and `PolyTreeD`, EvenOdd, NonZero and Positive,
`Clipper64::Execute` and `BooleanOp`, and even a plain union of A and B passed together as
subjects, with no clip paths (`AddSubject({A, B})`, `ClipType::Union`, EvenOdd).

The filled region is right: the `Paths64` result of the same `Execute` call is exact, and so is the
sum of signed areas over the tree. What is wrong is the ownership that PolyTree is there to provide
(`clipper.engine.h`: "it does preserve path 'ownership' - ie those paths that contain (or own) other
paths"). `IsHole()` is derived from the level, so the hole B below is reported as an outer polygon
that A does not own, and code that walks the tree as outer + child holes fills B in (area 20
instead of 12).

For inscribed rings this is the usual outcome, not a rare one: in 4788 random configurations of a
lattice polygon A with a polygon B whose vertices all lie on A's edges, the tree of
`Difference(A, B)` was wrong in 4434 (93 %) on 2.0.1 and `main`, and in 3 on 1.5.2.

## Minimal repro

```cpp
#include "clipper2/clipper.h"
#include <cstdio>
using namespace Clipper2Lib;

static void dump(const PolyPath64& n) {
  for (size_t i = 0; i < n.Count(); ++i) {
    printf("level %u %s area %+.1f\n", n[i]->Level(),
           n[i]->IsHole() ? "hole " : "outer", Area(n[i]->Polygon()));
    dump(*n[i]);
  }
}

int main() {
  // A = triangle; B = its medial triangle (each vertex of B is the midpoint of an edge of A).
  Paths64 A = {MakePath({0,0, 6,2, 2,6})};   // area 16
  Paths64 B = {MakePath({3,1, 4,4, 1,3})};   // area 4, inside A, touching it at its 3 vertices
  Clipper64 c;
  c.AddSubject(A);
  c.AddClip(B);
  PolyTree64 tree;
  c.Execute(ClipType::Difference, FillRule::EvenOdd, tree);
  dump(tree);

  // An island whose vertices all touch its hole.
  Paths64 S = {MakePath({0,0, 12,0, 12,12, 0,12}),  // square
               MakePath({2,2, 4,10, 10,4})};        // its hole H
  Paths64 I = {MakePath({6,3, 7,7, 3,6})};          // midpoints of H's edges
  Clipper64 c2;
  c2.AddSubject(S);
  c2.AddClip(I);
  PolyTree64 tree2;
  c2.Execute(ClipType::Union, FillRule::EvenOdd, tree2);
  dump(tree2);
}
```

Build: `g++ -std=c++17 -I CPP/Clipper2Lib/include repro.cpp CPP/Clipper2Lib/src/clipper.engine.cpp`

## Expected vs actual

| | expected | actual (2.0.1 and main) |
|---|---|---|
| `Difference(A, B)` | `level 1 outer area +16.0` → `level 2 hole area -4.0` | `level 1 outer area +16.0`, **`level 1 outer area -4.0`** (two top-level nodes: B is clockwise and is a direct child of the root, not of A) |
| `Union(S, I)` | `level 1 outer area +144.0` → `level 2 hole area -30.0` → `level 3 outer area +7.5` | `level 1 outer area +144.0` → `level 2 hole area -30.0`, **`level 2 hole area +7.5`** (the island is a sibling of the hole it lies in) |

`Xor(A, B)` gives the same as `Difference`. The `Paths64` results are right: areas 12 and 121.5,
equal to the exact values (A − B is the three corner triangles, 3 × 4 = 12; 144 − 30 + 7.5 = 121.5).
Clipper2's own `PointInPolygon` agrees that B lies inside A: B's vertices are `IsOn` A, and (3,3),
a point inside B, is `IsInside` A.

**Control:** if one vertex of B is moved strictly inside A (`B2 = (3,2) (4,4) (1,3)`), the tree is
correct.

## Versions

| version | commit | result |
|---|---|---|
| main (head on 2026-09-26) | f9c5eb6e14a59f6f5d65fbfb3564519a561cf4fd | wrong |
| 2.0.1 | 21ebba05db8894f0c7217ad35ea518080f324946 | wrong |
| 1.5.4 / 1.5.3 | ef88ee9 / fa165fe | wrong |
| "Fixed occasional bug in Polytree structure (#973)" | 0d0ba0f | wrong (#973's own input is correct here) |
| first bad commit (git bisect) | e8ebdef0931771443be86c092874e1bb0b51038a "Fixed incorrect Polytree ownership following clipping op. (#957)"; its parent 3dd975a is correct | wrong |
| 1.5.2 / 1.4.0 / 1.2.4 | 6901921 / 736ddb0 / ff85874 | correct |
| open PR #1101 (Ystripes) | 4115ae4 | wrong |

g++ 13, C++17, Linux x86-64. Tested with the C++ library only. By reading the source, the Delphi
`Path2ContainsPath1` has the same `Exit` (`Clipper.Core.pas:2446`), and C# keeps the old
midpoint fallback (`Clipper.Core.cs:882-883`).

## Analysis

`RecursiveCheckOwners` (`clipper.engine.cpp:2958`) receives the correct owner from the sweep: for
B, the owner is A's outrec. It then re-checks it with `Path2ContainsPath1(outrec->pts,
outrec->owner->pts)` (`:2969`). That check fails, so the loop walks up the owner chain (`:2970`) to
`nullptr`, and B is added to the root (`:2980`).

The check fails because every vertex of B is `IsOn` A. The `OutPt` overload
(`clipper.engine.cpp:576-599`) then retries on the cleaned paths with the template in `clipper.h`
(added for #973), and there:

```cpp
// clipper.h:739 (main f9c5eb6)
if (pip != PointInPolygonResult::IsInside) return false;
```

So a ring with no vertex strictly inside the other ring is never contained. Before e8ebdef, the
equivocal case fell back to `PointInPolygon(bounds-midpoint, path2) != IsOutside`, which answered
"inside" here. The C# port still does that. The #973 fix moved this check into `clipper.h` and
kept the `return false`.

For the island, the same test rejects the hole H as owner, the next owner up (the square) is
accepted, and the island becomes a hole.

A second trigger comes from the same line. When grid rounding puts one vertex just outside the
ring and all the others are on it, `pip` ends as `IsOutside` and the function again returns
`false`. We saw this on a real-coordinate input scaled by 2^52 (an island whose five vertices read
`on on on on out` against its hole).

The existing tests do not catch this: `CheckPolytreeFullyContainsChildren` only looks at nodes that
have children, and a misplaced ring leaves the signed-area total (as compared in
TestPolytreeHoles2) unchanged. A check that each node's orientation agrees with `IsHole()` would
catch it.

## Suggested fix

When the vertices cannot decide, let the midpoints of path1's edges vote. Working in doubled
coordinates (path2 is doubled, and each midpoint is taken as the sum of its edge's endpoints) keeps
the midpoints exact. This fixes both triggers:

```diff
--- a/CPP/Clipper2Lib/include/clipper2/clipper.h
+++ b/CPP/Clipper2Lib/include/clipper2/clipper.h
@@ -736,7 +736,28 @@ namespace Clipper2Lib {
         break;
       }
     }
-    if (pip != PointInPolygonResult::IsInside) return false;
+    if (pip != PointInPolygonResult::IsInside)
+    {
+      // No vertex of path1 is inside path2: every vertex is on path2, except
+      // perhaps one that rounding has put just outside. The vertices cannot
+      // decide, so let the midpoints of path1's edges vote, in doubled
+      // coordinates (path2 * 2, midpoint = sum of endpoints) so they are exact.
+      Path<T> path2x2;
+      path2x2.reserve(path2.size());
+      for (const Point<T>& pt : path2) path2x2.emplace_back(pt.x * 2, pt.y * 2);
+      int inside = 0, outside = 0;
+      for (size_t i = 0, j = path1.size() - 1; i < path1.size(); j = i++)
+      {
+        Point<T> mid(path1[i].x + path1[j].x, path1[i].y + path1[j].y);
+        switch (PointInPolygon(mid, path2x2))
+        {
+        case PointInPolygonResult::IsInside: ++inside; break;
+        case PointInPolygonResult::IsOutside: ++outside; break;
+        default: break;
+        }
+      }
+      return inside > outside;
+    }
     // result is likely true but check midpoint
     Point<T> mp1 = GetBounds(path1).MidPoint();
     return PointInPolygon(mp1, path2) == PointInPolygonResult::IsInside;
```

With this patch:

- all 48 tests in `CPP/Tests` pass (TestPolytreeHoles1-10 included, among them the tests for
  #618, #942, #957 and #973), and so does the `USINGZ` build;
- both cases above are correct;
- the random check (4788 configurations of a lattice polygon A with a polygon B through lattice
  points on A's edges) goes from 4434 wrong trees for `Difference(A, B)` and 4574 wrong trees for
  `Union({square, A, B})` to 0 and 1. The remaining one is a flat-result near-miss, not nesting;
- on our 1804-case differential set, only the 5 affected cases change.

Doubling stays in range for |coordinates| ≤ `MAX_COORD`. A smaller change, giving C++ the C#
fallback (`PointInPolygon(bounds-midpoint, path2) != IsOutside`), also passes the tests (including
TestPolytreeHoles9 and 10, for #957 and #973) and fixes the repro, but it leaves 3 and 4 of the
4788 random configurations wrong, as 1.5.2 does.

## Related issues

- #973 "PolyTree still has issues after fix of #957": the same symptom, a hole returned at the top
  level, from the same commit. I ran its input: at e8ebdef it has 4 rings whose orientation
  contradicts their level; on 1.5.2 and on `main` it is correct. Its fix (0d0ba0f / 927daf7) retries
  on cleaned paths and keeps the `return false`, so the all-vertices-on case above still fails. This
  report is best read as a follow-up to #973.
- #957: its fix, e8ebdef, is the first bad commit for this input (bisected).
- #942: an earlier nesting fix with a different mechanism (`CheckSplitOwner`, fcf5607); 3dd975a,
  which already has it, is correct here.
- #1084 (open, C#): mentions wrong `PolyTree64` results after a local change to `CheckSplitOwner`,
  with no data, so I could not tell whether it is related.
- Discussion #1022 (moved from #1008): there you preferred not to tweak results that are valid,
  i.e. that correctly describe the filled regions. Here too the filled region is right, but the tree
  contradicts itself: a clockwise ring is reported as an outer polygon (`IsHole() == false`) that
  its container does not own, the same kind of problem as #957 and #973.
- PR #1101 (open) changes the speed of the nesting point-in-polygon step, not this decision; with
  it the repro still fails.

I found no open or closed issue or PR with this input.

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
