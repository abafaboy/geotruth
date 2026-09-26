# PolyTree64: a hole whose vertices all touch its outer ring is returned as a top-level polygon (regression since 1.5.3)

## Summary

When every vertex of a result ring lies on the boundary of the ring that contains it, `BuildTree64`
puts that ring one level too high:

- an inscribed **hole** becomes a second **top-level** node (`IsHole() == false`), oriented
  clockwise;
- an inscribed **island** becomes a second **hole** of the outer ring (`IsHole() == true`), oriented
  counter-clockwise.

The `Paths64` result of the same `Execute` call is correct. Only the parent links are wrong.
Because top-level nodes are meant to be outer contours, code that walks the tree (outer + child
holes) fills in the hole. This is a regression from e8ebdef (#957 fix, May 2025): 1.5.2 and earlier
are correct, and 1.5.3, 1.5.4, 2.0.1 and `main` are wrong. It affects `PolyTree64` and
`PolyTreeD`, EvenOdd and NonZero, `Clipper64::Execute` and `BooleanOp`. It is also common: in 4788
random configurations of a lattice polygon with a polygon inscribed in it, the tree was wrong in 93 %.

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
| `Difference(A, B)` | `level 1 outer +16.0` → `level 2 hole −4.0` | `level 1 outer +16.0`, **`level 1 outer −4.0`** (two top-level nodes; the second is clockwise and has no parent) |
| `Union(S, I)` | `level 1 outer +144.0` → `level 2 hole −30.0` → `level 3 outer +7.5` | `level 1 outer +144.0` → `level 2 hole −30.0`, **`level 2 hole +7.5`** (the island is a sibling of the hole it lies in) |

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
| 1.5.2 / 1.4.0 / 1.2.4 | 6901921 / 736ddb0 / ff85874 | correct |
| first bad commit (git bisect) | e8ebdef0931771443be86c092874e1bb0b51038a "Fixed incorrect Polytree ownership following clipping op. (#957)"; its parent 3dd975a is correct | |
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
(`clipper.engine.cpp:576-599`) then defers to the template in `clipper.h` (#973), and there:

```cpp
// clipper.h:739 (main f9c5eb6)
if (pip != PointInPolygonResult::IsInside) return false;
```

So a ring with no vertex strictly inside the other ring is never contained. Before e8ebdef, the
equivocal case fell back to `PointInPolygon(bounds-midpoint, path2) != IsOutside`, which answered
"inside" here. The C# port still does that.

For the island, the same test rejects the hole H as owner, the next owner up (the square) is
accepted, and the island becomes a hole.

A second trigger comes from the same line. When grid rounding puts one vertex just outside the
ring and all the others are on it, `pip` ends as `IsOutside` and the function again returns
`false`. We saw this on a real-coordinate input scaled by 2^52 (an island whose five vertices read
`on on on on out` against its hole).

## Suggested fix

When the vertices cannot decide, let the midpoints of path1's edges vote. Doubling path2 makes
the midpoints exact grid points. This fixes both triggers:

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
+      // decide, so let the midpoints of path1's edges vote (both paths are
+      // doubled so that the midpoints are exact grid points).
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

- all 48 tests in `CPP/Tests` pass (TestPolytreeHoles1-10 included), and so does the `USINGZ` build;
- both cases above are correct;
- the random check (4788 configurations of a lattice polygon A with a polygon B through lattice
  points on A's edges) goes from 4434 wrong trees for `Difference(A, B)` and 4574 wrong trees for
  `Union({square, A, B})` to 0 and 1. The remaining one is a flat-result near-miss, not nesting;
- on our 1804-case differential set, only the 5 affected cases change.

Doubling stays in range for |coordinates| ≤ `MAX_COORD`. A smaller change, giving C++ the C#
fallback (`PointInPolygon(bounds-midpoint, path2) != IsOutside`), also passes the tests and fixes
the repro, but it leaves 3 and 4 of the 4788 random configurations wrong, as 1.5.2 does.

## Related issues

#957 and #973 (the fixes that introduced this) and #942 (earlier nesting fix). None of them
reports this input. No open issue or PR covers it; PR #1101 changes the nesting point-in-polygon
speed but not this decision, and still reproduces.

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
