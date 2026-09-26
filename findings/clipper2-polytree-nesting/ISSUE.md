# clipper2-polytree-nesting: triage result

## Verdict: confirmed bug, a regression since Clipper2 1.5.3. New: no upstream issue or PR covers it. Not reported yet.

`PolyTree64` / `PolyTreeD` put a ring at the wrong nesting level when **every vertex of the ring
lies on the boundary of the ring that contains it**:

- a hole whose vertices all touch its outer ring comes back as a second top-level node
  (`Level() == 1`, `IsHole() == false`), although it is oriented clockwise (negative area);
- an island whose vertices all touch its hole comes back as a second hole of the outer ring
  (`Level() == 2`, `IsHole() == true`), although it is oriented counter-clockwise.

The flat `Paths64` result of the same operation is right: the rings, their orientations and the
even-odd area all match the exact answer. Only the parent links in the tree are wrong. This is
the lead's "rings themselves are right under even-odd" observation, confirmed.

The cause is `Path2ContainsPath1` (`clipper.h:718-743`). When no vertex of the inner ring is
strictly inside the outer ring, it returns `false` (`clipper.h:739`), so
`RecursiveCheckOwners` (`clipper.engine.cpp:2958-2981`) drops the correct owner that the sweep had
already assigned and moves the ring up one level. This `return false` for the "all vertices on"
case came in with the #957 fix (e8ebdef, 2025-05-04). Before that commit the equivocal case fell
back to a midpoint test that answered "inside". Releases 1.5.2 and earlier are correct.

A maintainer-ready report is in [FINAL.md](FINAL.md). The registry snippet is in
[finding.toml](finding.toml).

## Facts established

| item | result |
|---|---|
| Latest development code | `main` = `f9c5eb6e14a59f6f5d65fbfb3564519a561cf4fd` (2026-04-20). `git ls-remote` on 2026-09-26 shows this is still the head of `main` and still the only branch. **Reproduces.** |
| Latest release | `Clipper2_2.0.1` = `21ebba05db8894f0c7217ad35ea518080f324946` (2025-12-20), still the newest tag. **Reproduces**, with output identical to `main`. |
| Other versions | 1.5.4 (ef88ee9) and 1.5.3 (fa165fe): wrong. 1.5.2 (6901921), 1.4.0 (736ddb0) and 1.2.4 (ff85874): correct. Open PR #1101 "Ystripes" (head 4115ae4, the only open PR that touches PolyTree nesting): still wrong. |
| Bisect | first bad commit `e8ebdef0931771443be86c092874e1bb0b51038a` "Fixed incorrect Polytree ownership following clipping op. (#957)". Its parent `3dd975a` is correct. `git bisect run` on repro.cpp between 1.4.0 and 1.5.4 ([output/bisect_log.txt](output/bisect_log.txt)). |
| Minimal input (hole) | `A = (0,0) (6,2) (2,6)` (area 16). `B = (3,1) (4,4) (1,3)`, its medial triangle: each vertex of B is the midpoint of an edge of A. `Difference(A, B)` and `Xor(A, B)`, EvenOdd. NonZero, `PolyTreeD` and `BooleanOp` show the same. |
| Minimal input (island) | `S = square (0,0)-(12,12)` with hole `H = (2,2) (4,10) (10,4)`. `I = (6,3) (7,7) (3,6)`, the triangle on the midpoints of H's edges. `Union(S, I)`, EvenOdd. |
| Control | moving one vertex of B strictly inside A (`B2 = (3,2) (4,4) (1,3)`) gives a correct tree ([output/main_f9c5eb6.txt](output/main_f9c5eb6.txt)). |
| Input validity | A, B, S (with its hole), I: all valid simple polygons (`geotruth valid`, oracle.py `valid_a/valid_b`). Small integer coordinates, far below `MAX_COORD` (2^61 − 1). No intersection point needs rounding: every output vertex is an input vertex. Clipper2 accepts any closed paths, so nothing here is outside its documented input domain. |
| What Clipper2 returns | Case 1: `PolyTree64` has **2 top-level nodes**, `(6,2) (2,6) (0,0)` with area +16 and `(1,3) (4,4) (3,1)` with area −4, both `IsHole() == false`, the second with no parent. Case 2: the square has **two hole-level children**, `H` (area −30) and `I` (area **+7.5**, `IsHole() == true`), and `I` has no parent hole. `Paths64` of the same calls: area 12 and 121.5, both exact. |

### Exact answer (three independent routes)

| route | Case 1: `A − B` (and `A xor B`, since B ⊂ A) | Case 2: `S ∪ I` |
|---|---|---|
| geotruth engine (`overlay --areal --certify`, certificate ok) | `MULTIPOLYGON (((0 0, 3 1, 1 3, 0 0)), ((1 3, 4 4, 2 6, 1 3)), ((3 1, 6 2, 4 4, 3 1)))`, area 12 | `MULTIPOLYGON (((square), (2 2, 3 6, 4 10, 7 7, 10 4, 6 3, 2 2)), ((3 6, 6 3, 7 7, 3 6)))`, area 243/2 |
| tests/reference/indep.py (Fractions, winding numbers) and oracle.py (gmpy2 slabs) | A−B = 12, B−A = 0; B's vertices `on` A; B's centroid (8/3, 8/3) is `in` A and `in` B | A−B = 114, B−A = 15/2, union 243/2; I's vertices `on` H; I's centroid is `out` of A (it lies in the hole) |
| by hand | B is the medial triangle, so A − B is the three corner triangles, each 1/4 of A: 3 × 4 = 12. B lies inside A and touches it only at its vertices | I lies inside H, touching it at its vertices: area 144 − 30 + 7.5 = 121.5 |
| Clipper2's own `PointInPolygon` | B's vertices vs A: `IsOn IsOn IsOn`. (3,3), a point inside B: `IsInside` A and `IsInside` B. So by Clipper's own point location, B's interior lies inside A's interior. A tree that makes B a sibling of A is therefore wrong: two top-level polygons would overlap | |

Files: [exact.txt](exact.txt), [indep_check.txt](indep_check.txt), [oracle.jsonl](oracle.jsonl),
[indep.jsonl](indep.jsonl) (the two routes agree on all 7 cases).

### Documented contract that the output breaks

- `clipper.engine.h:293-296` (source, checked): *"PolyTree ... does preserve path 'ownership' - ie
  those paths that contain (or own) other paths."* B is contained in A but is not owned by it.
- PolyTree64 documentation (angusj.com/clipper2/Docs/Units/Clipper.Engine/Classes/PolyTree64):
  *"Direct descendants of PolyTree64 will always be outer polygon contours"*. Issue #957 quotes the
  same page: *"Children of outers will always be holes, and children of holes will always be
  outers"*. **Caveat:** angusj.com is blocked by this sandbox's egress proxy. These sentences come
  from web-search snippets of that page and from the #957 issue text. Check them in a browser
  before citing them upstream.
- Solutions are "Positive" oriented: outer contours counter-clockwise, holes clockwise (the Clipper2
  Overview docs, via search, and the source comment `clipper.engine.cpp:3011`, "closed paths should
  always return a Positive orientation"). A clockwise ring at the top level, or a counter-clockwise
  ring at hole level, contradicts this.

Touching rings are allowed in Clipper2 solutions, and a hole that touches its outer ring at several
points is a legitimate Clipper2 result. So a correct tree here is outer ring A with child hole B.
Read as OGC, that polygon-with-hole is not a valid Polygon (a disconnected interior), but that is a
matter of OGC form, not of Clipper2's contract, and it is not part of this report. **This is not
the documented "micro-triangle" or snapping behaviour** (the `clipper2-thin-triangle-dropped`
finding): no vertex moves, and nothing is rounded or removed.

## Root cause (file:line on main f9c5eb6)

1. The sweep gives B (outrec 1) the right owner, A (outrec 0). A diagnostic `fprintf` in the owner
   loop shows it ([output/trace_recursivecheckowners.txt](output/trace_recursivecheckowners.txt)):
   `RecursiveCheckOwners: outrec 1, initial owner 0`.
2. `ClipperBase::RecursiveCheckOwners` (`clipper.engine.cpp:2958-2981`) re-verifies that owner. The
   bounds test passes, but `Path2ContainsPath1(outrec->pts, outrec->owner->pts)` returns 0
   (`:2969`). The loop then walks up, `outrec->owner = outrec->owner->owner` (`:2970`), to `nullptr`,
   and B is added to the root (`:2980`). For the island, the hole H is rejected and the next owner up
   (the square) is accepted, so the island becomes a hole.
3. `Path2ContainsPath1(OutPt*, OutPt*)` (`clipper.engine.cpp:576-599`) finds only `IsOn` vertices. It
   then calls the template `Path2ContainsPath1(const Path<T>&, const Path<T>&)` (`clipper.h:718-743`)
   on the cleaned paths (`:598`, added for #973).
4. The template's vertex loop ends with `pip == IsOn`, and **`clipper.h:739`
   `if (pip != PointInPolygonResult::IsInside) return false;`** decides "not contained". The
   bounding-box midpoint check below it (`:740-742`) is reached only when some vertex was inside.

Public-API demonstration ([rootcause_path2containspath1.cpp](rootcause_path2containspath1.cpp),
[output/rootcause_path2containspath1.txt](output/rootcause_path2containspath1.txt)):
`Path2ContainsPath1(B, A) = 0`, `Path2ContainsPath1(I, H) = 0`, and the control
`Path2ContainsPath1(Bsmall, A) = 1`.

History: e8ebdef (#957) rewrote the helper, then called `Path1InsidePath2`. The old code counted
outside/inside votes. When the vote was equivocal (0 or ±1), it fell back to
`PointInPolygon(bbox midpoint of path1, path2) != IsOutside`. For an all-`IsOn` ring that fallback
answered "inside". The new code returns `false` whenever no vertex is inside. 0d0ba0f/927daf7
(#973) moved the logic into the public template in `clipper.h` and kept that `return false`.

Ports:
- **C#** still has the old fallback, `Clipper.Core.cs:861-884`:
  `PointInPolygon(mp, path2) != PointInPolygonResult.IsOutside`. By reading the source, C# is
  probably not affected. It was not run: there is no .NET here.
- **Delphi** has the same `return false`, `Clipper.Core.pas:2446` `if (pip <> pipInside) then Exit;`,
  so it is probably affected. Not run.

### The rounding variant (lead case `hole-contact-7-000044-cross-near.n6.unit`)

The same final `return false` also fires when every vertex is on the ring except one that grid
rounding has pushed just outside. In `hole-contact-7-000044` (scale 2^52), two exact intersection
points 1e-16 apart snap onto A's vertex, which lies just outside the hole. The island's vertices
against the hole ring then read `on on on on out`, so `pip == IsOutside`, and the function returns
`false`. The comment on the OutPt overload says the function "accommodates rounding errors that can
cause path micro intersections", but a single micro-outside vertex with no inside vertex is not
accommodated.

## All five lead cases, explained

Checked with the geotruth adapter on `main` (PolyTree64 turned into typed polygons). The checker is
[output/analyse_nesting.py](output/analyse_nesting.py), and the results are in
[output/adapter_nesting_check.txt](output/adapter_nesting_check.txt).

| lead case | op | exact area | Clipper even-odd area | read as OGC polygons | trigger |
|---|---|---|---|---|---|
| vertex-on-edge-7-000026-inscribed.n4.lonlat | difference, xor | 7.571543392259628e-11 | same | 1.9349499780219048e-10 | inscribed hole, all vertices on |
| vertex-on-edge-7-000047-inscribed.n8.projected | difference, xor | 0.06707838107831776 | same | 0.11179730179719627 | inscribed hole, all vertices on |
| vertex-on-edge-7-000056-inscribed.n4.int | difference, xor | 2010 | 2010 | 4166 | inscribed hole, all vertices on |
| hole-contact-7-000005-cross-near.n6.int | xor | 6.41597353208457e+17 | same | 6.4094503124032115e+17 | island, all vertices on its hole |
| hole-contact-7-000044-cross-near.n6.unit | xor | 0.5242703117772596 | same | 0.5038531826231366 | island, 4 vertices on + 1 rounded just outside |

On this 1804-case set the checker flags 3 more cases: `int-grid-7-000041-lattice-tri-vertex.small-shear`
(difference, xor) and `tiny-rotation-1-000108` / `-000179` (xor). These are **not** this bug. In each
of them the flat `Paths64` result already has the offending ring: an inverted snapped triangle
(area −2 where the exact area is 2/3), or a degenerate snapped sliver. That is integer-grid
snapping of the overlay itself, the class covered by the adapter's δ and by
`clipper2-thin-triangle-dropped`. The prototype fix does not change them.

## Prototype fix and validation

[patch/prototype_fix.diff](patch/prototype_fix.diff) changes only the template in `clipper.h`, in
17 lines. When no vertex of path1 is strictly inside path2, the midpoints of path1's edges vote.
Both paths are doubled so that the midpoints are exact grid points. An edge that lies along path2
votes neither way, and path1 is contained when the inside votes outnumber the outside votes. The
existing behaviour is kept whenever some vertex is inside.

| check | unpatched main | with prototype_fix.diff |
|---|---|---|
| repro.cpp (3 wrong trees + 1 control) | 3 wrong | 0 wrong |
| Clipper2's own C++ tests (`CPP/Tests`, 48 tests incl. TestPolytreeHoles1-10 for #618/#942/#957/#973), and the Z build | 48/48 | 48/48 ([patch/unit_tests.txt](patch/unit_tests.txt)) |
| geotruth 1804-case set + 5 lead cases | 5 lead cases wrong | lead cases all right. Only those 5 cases' outputs change, all other 1799 are byte-identical |
| [fuzz_inscribed.cpp](fuzz_inscribed.cpp): 4788 random lattice configurations of a convex polygon A and a polygon B through lattice points inside A's edges. Trees of `Difference(A,B)` / `Union({square, A, B})` | 4434 / 4574 wrong (93 %) | 0 / 1 (the 1 is the flat-result near-miss below, not nesting) |

The failure is the common case, not a corner case: on current releases, 93 % of random
inscribed-ring configurations produce a wrong tree ([output/fuzz_results.txt](output/fuzz_results.txt)).
1.5.2 and 1.4.0 get 3 / 4 of the 4788 wrong. That comes from the old bounding-box-midpoint
heuristic.

A simpler alternative is to give C++ the C# port's fallback,
[patch/alternative_csharp_fallback.diff](patch/alternative_csharp_fallback.diff). It also passes
48/48 and fixes repro.cpp, but it leaves the 3 / 4 fuzz failures of 1.5.2
([patch/variants.txt](patch/variants.txt)). Overflow note for the prototype: doubling is safe for
|coordinates| ≤ `MAX_COORD` = 2^61 − 1, because the doubled differences stay below 2^63.

## Upstream search (2026-09-26)

Sources: the GitHub issue search (MCP, semantic), the GitHub web issue list (open issues, and
`q=polytree`), the PR search, and web search. The API and HTML pages of github.com were blocked for
direct reading, so issue pages were read through WebFetch summaries: titles and bodies, but no
comment threads.

Queries used:
- "PolyTree hole placed at top level wrong parent touching polygon"
- "polytree hole vertices on outer boundary Path2ContainsPath1 IsOn"
- "polytree clockwise polygon at root level IsHole false negative area"
- "island inside hole becomes hole polytree nested polygon wrong level touching"
- "hole returned as outer polygon at root of polytree after difference, hole touches outer at every vertex, inscribed polygon"
- PRs matching "polytree"
- web: "Clipper2 polytree hole touches outer polygon at vertices wrong nesting"

No open issue or PR reports this. The open-issue list shown on the web (12 issues, #1084-#1112) was read and none is about
PolyTree nesting. Related closed issues follow; each is a different input or mechanism, and all of
them were fixed before or by the commits that introduced this regression:

| issue | relation |
|---|---|
| [#957](https://github.com/AngusJohnson/Clipper2/issues/957) "PolyTree issue: outer polygon on hole level" (closed 2025-05-04) | same symptom class (orientation contradicts level). Its fix e8ebdef **introduced** this regression |
| [#973](https://github.com/AngusJohnson/Clipper2/issues/973) "PolyTree still has issues after fix of #957" (closed 2025-05-06) | follow-up to #957. Its fix moved the helper into `clipper.h` and kept the `return false` |
| [#942](https://github.com/AngusJohnson/Clipper2/issues/942) "Incorrect Hierarchy in PolyTree Union Results" (closed 2025-02-08) | earlier nesting bug in `CheckSplitOwner`. Fixed before 1.5.3, and 1.5.2 is correct here |
| [#1038](https://github.com/AngusJohnson/Clipper2/issues/1038) "Union Inner/Outer Bug" (closed 2025-11) | C# `PolyTreeD`, NonZero, data in an attachment. It is C# (whose fallback differs, see above), and no data could be read |
| [#1047](https://github.com/AngusJohnson/Clipper2/issues/1047) "Polygon with hole work wrong" (closed 2025-12-17) | "the result is a polygon without hole", image only. No data to compare; closed within an hour |
| [#498](https://github.com/AngusJohnson/Clipper2/issues/498), [#520](https://github.com/AngusJohnson/Clipper2/issues/520), [#584](https://github.com/AngusJohnson/Clipper2/issues/584), [#590](https://github.com/AngusJohnson/Clipper2/issues/590), [#618](https://github.com/AngusJohnson/Clipper2/issues/618), [#638](https://github.com/AngusJohnson/Clipper2/issues/638), [#679](https://github.com/AngusJohnson/Clipper2/issues/679), [#687](https://github.com/AngusJohnson/Clipper2/issues/687), [Discussion #576](https://github.com/AngusJohnson/Clipper2/discussions/576) | 2023 PolyTree ownership bugs (horizontal joins, splits). Fixed long before, and 1.2.4 / 1.4.0 are correct here |
| [#416](https://github.com/AngusJohnson/Clipper2/issues/416), [#768](https://github.com/AngusJohnson/Clipper2/issues/768) | how touching holes are merged or kept apart in the flat result, not tree ownership |
| [PR #1101](https://github.com/AngusJohnson/Clipper2/pull/1101) "Ystripes" (open) | speeds up the point-in-polygon step of nesting. Tested at 4115ae4: still wrong |

Recommendation: report it. FINAL.md is ready and has not been posted.

## Other observations (not this finding, untriaged)

- **Flat-result near-miss, from the fuzz run.** `A = (-51,59) (-41,24) (-26,-21)`,
  `B = (-49,52) (-37,12) (-41,27)` (B inscribed in A). B's edge (−49,52)-(−37,12) passes 0.38 units
  from A's vertex (−41,24). `Difference(A, B)` returns one triangle, `(-40,24) (-37,12) (-26,-21)`,
  of area 16.5. The exact answer is 3 triangles of total area 55/2 (engine). `(-40,24)` is not an
  input vertex. Setting the `CheckJoinLeft/Right` distance thresholds (`clipper.engine.cpp:2814,
  2842`, cf. open #1111) to 0 does not fix it. This is a sub-unit near-miss on the integer grid, so
  it is probably within Clipper64's documented rounding. Its size (−11 units² on a 27.5-unit² answer)
  may deserve a lead of its own. Not investigated further here.
- The three snapping cases on the 1804-case set (above) are the same class.

## Files

| file | what |
|---|---|
| `repro.cpp`, `run.sh` | public-API repro (Case 1, control, Case 2). `CLIPPER2_SRC=/path/to/Clipper2 ./run.sh` |
| `rootcause_path2containspath1.cpp` | the root cause through the public `Path2ContainsPath1` (≥ 1.5.3) |
| `fuzz_inscribed.cpp` | random inscribed-ring check (public API) |
| `cases.jsonl` | the two minimal cases (FORMAT-v1 lines) |
| `lead_cases.jsonl` | the five original lead cases (FORMAT-v1 lines) |
| `oracle.jsonl`, `indep.jsonl`, `indep_check.txt`, `exact.txt` | exact answers: oracle.py, indep.py and the geotruth engine |
| `output/main_f9c5eb6.txt`, `output/release_2.0.1_21ebba0.txt`, `output/release_*.txt`, `output/commit_*.txt`, `output/open_pr1101_4115ae4.txt` | captured repro output per version and commit |
| `output/main_f9c5eb6_with_prototype_fix.txt` | the repro with the prototype fix |
| `output/final_md_repro.txt` | the short repro embedded in FINAL.md, on main, 2.0.1, 1.5.2 and main + fix |
| `output/bisect_log.txt`, `output/trace_recursivecheckowners.txt`, `output/rootcause_path2containspath1.txt` | bisect and root-cause evidence |
| `output/adapter_*` and `output/analyse_nesting.py` | geotruth adapter runs and the nesting checker |
| `output/fuzz_results.txt` | fuzz counts per version |
| `patch/` | prototype fix, the C#-fallback alternative, the first attempt, unit-test summaries and variant comparison |

Scratch (not needed to reproduce): `/tmp/claude-0/gb-build/triage2/clipper2-polytree-nesting/`
(full clone, worktrees per version, builds, adapter runs).
