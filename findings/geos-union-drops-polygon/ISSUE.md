# geos-union-drops-polygon: triage result

## Verdict: a real bug, already fixed upstream. Do not file it as a new issue.

This is libgeos/geos#1405 ("Intersection of polygons gives incorrect results, depending on
order of arguments"). It was closed by PR #1499, commit `737737dbb`, merged 2026-08-12, and
the fix shipped in **GEOS 3.15.0**. GEOS 3.15.0, GEOS main and JTS master all give the exact
answer. GEOS 3.13.1 (the version Shapely 2.1.2 bundles) and GEOS 3.14.1 are still wrong. The
fix is not on the `3.14` or `3.13` maintenance branches.

The one thing left worth sending upstream is a **request to backport #1499 to the 3.14
branch** (and 3.13, if it still gets releases). A draft is at the end of this file. Nothing
has been posted.

### Facts established

| item | result |
|---|---|
| Candidate (GEOS 3.13.1 via Shapely 2.1.2) | Reproduces: union area 3 where the exact area is 4, and B − A is empty. |
| GEOS 3.14.1, latest 3.14 release (`c389f532d`, 2025-10-27) | Reproduces on the candidate and on both minimal cases. |
| GEOS 3.15.0, latest release (`d0228513a`, 2026-09-01) | Correct on all 3 cases. |
| GEOS main (`ae9cdd98b`, 2026-09-21) | Correct on all 3 cases. |
| Commit that fixes it | `737737dbb` (PR #1499) gives 0 disagreements. Its parent `da4de475f` has all 5 disagreements. Between those two commits the only library changes are `src/edgegraph/HalfEdge.cpp` and `src/geomgraph/EdgeEnd.cpp`. |
| Maintenance branches | `origin/3.14` (`7db6f62d5`, which has an unreleased 3.14.2 NEWS section) and `origin/3.13` (`fbe9180f7`) still have the old test `if (dx == dx2 && dy == dy2)` at `src/edgegraph/HalfEdge.cpp:188`. |
| JTS master (`3ea61f8`, 1.21.0-SNAPSHOT) | Correct on all 3 cases. It has the same fix, locationtech/jts#1224 (plus #1226), merged 2026-08-12. |
| JTS 1.20.0, latest release | Same pre-fix code (`HalfEdge.java:401-410`). Case 1 and the candidate are within tolerance there: the intersection comes out 0 instead of about 5e-21 or 2e-17, and union and differences are right. Case 2 is grossly wrong: intersection 0 instead of 1/6. |
| Backport check | `737737dbb` cherry-picks without conflicts onto `origin/3.14` and `origin/3.13`. 3.14.1 plus only the `HalfEdge.cpp` hunk (`backport_halfedge_only.diff`, one file recompiled) gives 0 disagreements on all 3 cases (`output_geos-3.14.1+halfedge-backport.txt`). OverlayNG does not use `geomgraph`, so the `EdgeEnd.cpp` hunk does not affect it. |
| Input validity | All inputs are valid. For the two-triangle cases, oracle.py (with validity.py) and indep.py both say valid. For the candidate's 3-part multipolygon, oracle.py/validity.py say valid. indep.py only decides single-ring validity, so it returns null there. GEOS `isValid` and JTS `IsValidOp` also say valid. Rings are closed. GEOS and OGC do not prescribe ring orientation. No coordinate limit applies. |
| Exact answers | oracle.py and indep.py agree exactly, as rationals, on all three cases (`oracle.jsonl`, `indep.jsonl`). |

### Minimal input (case 1, 6 vertices)

```
A = POLYGON ((1 1, -1e-20 0, 1 0, 1 1))
B = POLYGON ((0 0, 1 1, 0 1, 0 0))
```

The answer can be checked by hand. Let ε = 1e-20. B is the triangle on and above the diagonal
y = x (0 ≤ x ≤ y ≤ 1). A is the triangle below the line L through (−ε, 0) and (1, 1), with
y ≥ 0 and x ≤ 1. For 0 ≤ x < 1, L lies above the diagonal by ε(1 − x)/(1 + ε). So A ∩ B is
the needle triangle (0,0), (0, ε/(1+ε)), (1,1), with area ε/(2(1+ε)) ≈ 5e-21. It follows that
area(A ∪ B) ≈ 1, area(B − A) ≈ 0.5 and area(A − B) ≈ 0.5. The oracle's exact intersection
is 6646139978924579/1329227995784915872917099340238193734 ≈ 5.0e-21.

GEOS 3.13.1, 3.14.1 and `da4de475f` (from `output_*.txt`) give:

| op | GEOS ≤ 3.14.1 | exact |
|---|---|---|
| union | `POLYGON ((1 1, 1 0, 0 0, -1e-20 0, 0 1e-20, 1 1))`, area 0.5 (this is just A) | ≈ 1.0 |
| intersection | `POLYGON ((0 0, 0 1e-20, 0 1, 1 1, 0 0))`, area 0.5 (all of B) | ≈ 5e-21 |
| B − A | `POLYGON EMPTY` | ≈ 0.5 |
| A − B | area 0.5 | ≈ 0.5 |
| symdifference | area 1.0 | ≈ 1.0 |

These results contradict each other and the predicates, which are correct:
`covers(A,B) = false`, `overlaps = true`.

**Case 2** (same structure; this one also fails in JTS 1.20.0):
`A = POLYGON ((1 1, -1e-20 0, 0 1, 1 1))`, `B = POLYGON ((0 0, 1 1, -2 -1, 0 0))`. The exact
intersection is the triangle (−ε,0), (1,1), ≈(0,1/3), with area 1/6. GEOS ≤ 3.14.1 and
JTS 1.20.0 give intersection area 0 and A − B area 0.5 (exact 1/3). The union area, 5/6, is
right.

**Original candidate** (`tiling-contact-2-001988-sq-multi.center-direct.origin`): the same
thing happens at the vertex P = (0.6849710348661722, 0.7285702995554822) that square S of A
shares with B.

### Root cause (confirmed by the one-commit bisect)

OverlayNG builds the edge star around each node with `OverlayGraph::insert`
(`src/operation/overlayng/OverlayGraph.cpp:145-158`). That calls `HalfEdge::insert` and
`HalfEdge::insertionEdge` (`src/edgegraph/HalfEdge.cpp:81, 99-128`), which order the edges with
`HalfEdge::compareAngularDirection` (`src/edgegraph/HalfEdge.cpp:180-208`, 3.13.1 and 3.14.1).
That function first computes the direction vectors in floating point
(`dx = dest.x - orig.x`, …) and returns 0, meaning "same direction", when the vectors are
equal (line 188). Only after that does it fall back to the exact `Orientation::index`.

At node (1,1) in case 1, the half-edges (1,1)→(0,0) (from B) and (1,1)→(0,1e-20) (from A,
after noding at the crossing with B's edge x = 0) both round to (−1, −1), because
`1e-20 - 1.0 == -1.0` in double. The exact orientation is nonzero (cross product −1e-20).

When the comparison returns 0, `insertionEdge` accepts either side of the tied edge, so the
counter-clockwise order at the node depends on insertion order. With the wrong order, the
faces at that node are traced wrongly. The observed effect is that B's region is labelled as
inside A: the intersection output is exactly B plus the new node. We did not trace the
labelling step by step; the one-commit bisect and the one-file backport test are the evidence.
In the candidate the same tie happens at P: both vectors round to
(−0.6849710348661722, −0.7285702995554822), while the exact orientation is −4.0e-17.

This matches the order dependence we observed: in the candidate, the result changes when the
far-away part of A is listed first or last. The fix in `737737dbb` compares the direction
*points* (`directionPt().equals2D(...)`), so non-identical directions always reach the exact
orientation test.

### Upstream tracker search (2026-09-26)

- GEOS, open and closed: "union missing polygon", "nearly coincident edge overlay",
  "intersection not commutative", "intersection order of arguments", "compareAngularDirection",
  "overlay wrong result sliver", and PRs matching "1499".
  - **Duplicate:** https://github.com/libgeos/geos/issues/1405 (closed 2026-08-12).
  - **Fix:** https://github.com/libgeos/geos/pull/1499. No backport PR was found, and git
    shows no backport on `3.14` or `3.13`.
  - Possibly related, not verified (their inputs are in attachments): #965 "Polygon disappears
    in unaryUnion" (open) and #942 "Incorrect intersection and difference results" (open).
- Shapely: https://github.com/shapely/shapely/issues/2426 (open, "upstream bug"; this is the
  Shapely twin of #1405, on Shapely 2.1.2 / GEOS 3.13.1).
- JTS: https://github.com/locationtech/jts/pull/1224 and
  https://github.com/locationtech/jts/pull/1226. Both are merged; the latest release, 1.20.0,
  does not have them.

### Files

- `repro.c`: GEOS C API reproducer (case 1). `repro.py`: the Shapely version.
  `Repro.java`: the JTS version (cases 1 and 2). `run.sh`: builds and runs them:
  `GEOS_CONFIG=/path/geos-config JTS_JAR=/path/jts-core.jar PYTHON=python3 ./run.sh`.
- `output_*.txt`: captured runs on Shapely 2.1.2 / GEOS 3.13.1, GEOS 3.14.1, 3.14.1 with
  `backport_halfedge_only.diff`, `da4de475f` (the parent of the fix), `737737dbb` (the fix),
  3.15.0, main `ae9cdd9`, JTS 1.20.0 and JTS master `3ea61f8`.
- `cases.jsonl`: case 1, case 2 and the original candidate. `oracle.jsonl` and `indep.jsonl`
  hold the exact answers. `adapter_results.jsonl` and `compare.txt` hold the repo adapters'
  results for every version above and the `compare.py` verdicts. For 3.14.1, 3.15.0 and the
  bisect builds, the adapter was linked against a stub `GEOSrevision()`, because that
  function only exists on main; that stub is where the `-release` suffix on those lib names
  comes from.

---

## Draft backport request (for libgeos/geos; not posted)

**Title:** Backport #1499 (HalfEdge direction comparison) to 3.14 branch

Hello, and thank you for GEOS.

Could #1499 (commit 737737dbb, "OverlayNG: Fix intersection computation of slightly
overlapping polygons", which closed #1405) be backported to the 3.14 branch, and to 3.13 if
that branch still gets releases? The bug gives grossly wrong overlay results, not only
tiny ones. Shapely 2.1.2 wheels bundle GEOS 3.13.1, so many users still hit it
(shapely/shapely#2426).

A two-triangle case in which a union loses almost all of one input:

```
A = POLYGON ((1 1, -1e-20 0, 1 0, 1 1))
B = POLYGON ((0 0, 1 1, 0 1, 0 0))
```

Both are valid. B lies on and above y = x. A lies below the line from (-1e-20, 0) to (1, 1).
The two overlap only in a needle of area ≈ 5e-21.

| op | expected | GEOS 3.13.1 / 3.14.1 | GEOS 3.15.0 / main |
|---|---|---|---|
| area(union) | ≈ 1.0 | 0.5 | 1.0 |
| area(intersection) | ≈ 5e-21 | 0.5 (all of B) | 5e-21 |
| area(B − A) | ≈ 0.5 | 0 (EMPTY) | 0.5 |

Reproducer (public C API): the attached `repro.c`. Build it with
`cc repro.c $(geos-config --cflags) $(geos-config --clibs)`.

We bisected this to the single commit: `da4de475f` fails and `737737dbb` passes. As in #1405,
the cause is the rounded direction-vector equality test in
`HalfEdge::compareAngularDirection` (`src/edgegraph/HalfEdge.cpp:188` on 3.14 and 3.13). At
node (1,1), the half-edges towards (0,0) and towards (0,1e-20) both round to (-1,-1), so the
test reports a tie and the edge star order depends on insertion order. On `origin/3.14`
(7db6f62d5) and `origin/3.13` (fbe9180f7) the old code is still present. The commit
cherry-picks onto both branches without conflicts. We applied only the `HalfEdge.cpp` hunk to
3.14.1, and that alone fixed all our cases.

We found this by differential testing against an exact rational-arithmetic oracle. The
expected values above were confirmed with two independent exact implementations.
