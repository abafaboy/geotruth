# clipper2-thin-triangle-dropped: triage result

## Verdict: not a bug. This is documented, intended behaviour, so do not file it as a bug.

The behaviour reproduces exactly as described, on the latest code and on the latest release.
Clipper2's own documentation describes it explicitly, though:

> "A triangle in a solution with an edge that's < 2 units in length will be considered within a
> rounding adjustment of having zero area (despite the length of the other edges), and these
> triangles will be removed from solutions."
> (Clipper2 docs, *Robustness*, https://angusj.com/clipper2/Docs/Robustness.htm)

Caveat on this quote: angusj.com is blocked by this sandbox's egress proxy, so the page was not
opened directly. The sentence above is the text returned, identically, by three separate
web-search queries that indexed that page. Check it in a browser before citing it upstream.
The maintainer made the same point in Discussion #538 (Oct 2023), quoting the same page: "a
triangle with one edge that's 1 unit in length could be considered within a rounding error of
having zero area".

The code matches the documented rule exactly. For integer points, `PtsReallyClose`
(`|dx| < 2 && |dy| < 2`) holds exactly when the edge length is below 2 (dx² + dy² ∈ {0, 1, 2}).

### Facts established

| item | result |
|---|---|
| Latest development code | `main` = `f9c5eb6e14a59f6f5d65fbfb3564519a561cf4fd` (2026-04-20), still the head of `main` on 2026-09-26 (`git ls-remote`). Reproduces. |
| Latest release | `Clipper2_2.0.1` = `21ebba05db8894f0c7217ad35ea518080f324946` (2025-12-20). Reproduces, with identical output. |
| Minimal input | the single triangle `(0,0) (1,0) (0,1000000)`, area 500,000: `Union` and `Intersect(t, t)` return nothing. The same triangle 2 units wide is kept. |
| Input validity | valid simple polygon: shapely 2.1.2 / GEOS 3.13.1 says "Valid Geometry", and so does oracle.py's validity check. Clipper2 imposes no orientation rule for NonZero/EvenOdd. Coordinates are far below `MAX_COORD` (2^61 − 1). |
| Exact answer | oracle.py and oracle_review/indep.py agree exactly: `Union(t) = Intersect(t, t) = 500000`. For the fat pair A, B below, `A∩B = 500000` and `A−B = 4000001500000`. |
| Root cause | `IsVerySmallTriangle`, `CPP/Clipper2Lib/src/clipper.engine.cpp:441-447` (with `PtsReallyClose` at :436). It is applied through `IsValidClosedPath` (:449-453) in `CleanCollinear` (:1529, :1548), and directly in `BuildPath64` (:2914) and `BuildPathD` (:3088). The same logic is in C# (`Clipper.Engine.cs:2812-2830, 3021`) and Delphi (`Clipper.Engine.pas:645-666, 1129`). Forcing it to `false` (`rootcause_check.diff`) restores every exact area. |
| History (it was deliberate) | `62a6e69` (2022-06-26, "Improved clipping artefact removal") dropped a triangle only when *both* neighbours of one vertex were within 1 unit. `5d866ab` (2022-07-14, "Code tidy.") changed AND to OR, and the same commit updated the expected counts and areas in `Tests/Polygons.txt`. `3202481` (2022-11-03, for #309) added the third vertex pair and the check in `BuildPath64`/`BuildPathD`. The documentation now describes the resulting rule, "despite the length of the other edges". |
| compare.py | flags `thin-tri-self` (`area_inter`, `area_union`: exact 500000, got 0). `fat-pair-thin-intersection` is under the 1e-6 relative tolerance (5e5 against operands of about 4e12), but its `Intersect` is still empty. |

### Upstream tracker search

Queries run, open and closed issues: "triangle", "thin", "small polygon removed", plus semantic
searches for "thin triangle removed / sliver disappears", "triangle inside box returns empty",
"polygon with two close points removed", "union of a single triangle returns empty", and
"IsVerySmallTriangle PtsReallyClose" (no hits).

- **#742 "Small objects intersection is not detected."** (closed, 2023-12-05):
  https://github.com/AngusJohnson/Clipper2/issues/742. It has the same mechanism at small scale:
  `Intersect(triangle (1,1),(2,2),(1,4), box 0..5)` returns empty. Verified here: it returns the
  triangle once `IsVerySmallTriangle` is disabled (`related_issue742_check.txt`). No commit
  references #742, so it appears to have been closed without a code change. Its comments could
  not be loaded from this sandbox.
- **Discussion #538**: https://github.com/AngusJohnson/Clipper2/discussions/538. The maintainer
  answers a "Union returns empty" report for sub-2-unit triangles by pointing to the Robustness
  page.
- **#309**: https://github.com/AngusJohnson/Clipper2/issues/309. This is the issue whose fix
  (`3202481`) extended the check to all three vertex pairs.
- Not the same issue:
  - #1067 (sliver triangles in union, fixed in `FixSelfIntersects`, commit `4da1564`).
  - #960 (a missing triangle in the Delphi version; on C++ `main` the missing piece is not this
    check, as tested here).
  - #1091 (PathD precision-dependent union).
  - #923.

### Recommendation for the hunt

Treat the `int-thin-triangle` family, and the snapped slivers in `int-thin-crossing-1-0003`,
`int-near-parallel-large` and `int-near-miss`, as **documented Clipper2 behaviour**, not bugs.
Either exclude result triangles with an edge shorter than 2 grid units from area comparisons,
or run the adapter with `--scale-bits 53`, which already gives 0 disagreements. For `PathsD`
the threshold is 2 units of the internal scale `2^(ilogb(10^p)+1)`. At precision 2 that is
2/128 = 0.015625, so `Union({(0,0),(0.01,0),(0,10000)}, NonZero, 2)` (area 50) returns
nothing. That is also covered by the same documentation.

---

## Optional: enhancement request draft (not a bug report)

Use this only if the team wants to raise it as a feature or design question. It
acknowledges the documented behaviour.

**Title:** Thin triangles with one sub-2-unit edge are removed regardless of area. Could the test also consider area?

Hi Angus, thank you for Clipper2.

The Robustness page documents that a solution triangle with an edge shorter than 2 units is
removed "despite the length of the other edges". I'd like to ask whether that rule could be
narrowed, because it also removes triangles whose vertices are exact input points and whose area
is large:

```cpp
#include "clipper2/clipper.h"
using namespace Clipper2Lib;
Paths64 t = {MakePath({0, 0, 1, 0, 0, 1000000})};   // valid triangle, area 500,000
Paths64 u = Union(t, FillRule::NonZero);           // u.size() == 0
Paths64 i = Intersect(t, t, FillRule::NonZero);    // i.size() == 0
// {0,0, 2,0, 0,1000000} (area 1,000,000) is returned unchanged
```

Fat operands are affected the same way. With
`A = (0,-2000000) (2000000,-2000000) (2000000,1) (0,1)` and
`B = (-2000000,-2) (2000000,2) (-2000000,2000000)`, the exact `A∩B` is the lattice triangle
`(0,0) (0,1) (1000000,1)` (area 500,000). `Intersect(A, B)` returns nothing, while
`Difference(A, B)` correctly removes exactly that triangle, so `|A∩B| + |A−B| ≠ |A|`.

- **Expected (exact):** `Union(t)` and `Intersect(t, t)` have area 500000, and `Intersect(A, B)` has area 500000.
- **Actual:** all three are empty.
- **Versions:** C++ `main` f9c5eb6 and release 2.0.1 (21ebba0), g++ -O2, Linux x86-64. The C# and
  Delphi sources contain the same check.
- **Where:** `IsVerySmallTriangle` / `PtsReallyClose` (clipper.engine.cpp:436-447), used by
  `IsValidClosedPath` in `CleanCollinear` and in `BuildPath64`/`BuildPathD`. Before `5d866ab`
  (July 2022) the test required both neighbours of a vertex to be within 1 unit, which bounds
  the area of a removed triangle to at most 1 square unit.
- **Possible direction (your call):** also require a small absolute area, for example
  `|area| < 2`, before discarding, as `DoSplitOp` already does with `absArea1 < 2`. Another
  option is a flag to keep such triangles. Without the check, all the cases above give exact
  results.

This was found by differential testing against an exact rational-arithmetic oracle, and the
expected values were confirmed by a second, independent exact implementation.
