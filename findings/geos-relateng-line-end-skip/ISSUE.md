# Triage: geos-relateng-line-end-skip

**Verdict.** This is a confirmed bug in GEOS RelateNG, and it is not by design. JTS fixed its own copy of the code (locationtech/jts#1175, fixed by #1200, commit e8de44d9, merged 2026-06-13) and NetTopologySuite ported the fix (NTS #862, fixed by NTS PR #869), but GEOS never did. For the line-end part the GEOS report is therefore a port request for a known JTS fix, not a new discovery.

Triage also found the same flaw in `computeAreaVertex`, for GeometryCollections. It is unfixed in both GEOS and JTS master, and no report of it was found. The fix to report to GEOS is: port #1200 and apply the same change to `computeAreaVertex` (`FINAL.md`). The JTS report covers the area-vertex part only (`JTS_FINAL.md`). The area-vertex part should be coordinated with the sibling finding `geos-relateng-geometrycollection-semantics` (D3, `FINAL_3_union_boundary.md`), which is about the same function and TODO (section 4).

**Covered-ring defect: a separate root cause.** The "covered-ring line end" defect in the lead has a different cause. It is a regression that GH-1201 introduced in GEOS 3.13.1 (a port of JTS #1099): a linear or GeometryCollection operand B is no longer self-noded when A is polygonal. It has its own evidence and reports in `covered-ring/` (`FINAL.md` for GEOS, `JTS_FINAL.md` for JTS, where the change is unreleased).

**Impact.** Severity of the skip defect: wrong matrix, not wrong predicate. Only the DE-9IM matrix is wrong: one cell, BE or EB. That affects `relate`, prepared relate, and `relatePattern` with patterns that test those cells; the named predicates are never affected (section 4). GEOS has used RelateNG for all of these by default since 3.13.0. In JTS the default `Geometry.relate` still uses the legacy RelateOp, which is correct on the line cases and throws `IllegalArgumentException` for GeometryCollections, so JTS users are affected only through the `RelateNG` API or `jts.relate=ng`. The covered-ring regression is worse: it also makes `contains`, `touches`, `covers` and `within` wrong for valid polygon/line and polygon/GC pairs.

## 0. Upstream heads (checked 2026-09-26 with `git ls-remote`)

| repo | ref | commit | moved since the builds? |
|---|---|---|---|
| libgeos/geos | `main` | ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 | no (same as $GEOTRUTH_BUILD_DIR/geos-main) |
| libgeos/geos | tag 3.15.0 | d0228513abb0c29c185443cf2bfb06c9281024b5 | no (the latest release; the `3.15` branch 86a4af48 has no relateng changes after 3.15.0) |
| locationtech/jts | `master` | 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd | no (same as $GEOTRUTH_BUILD_DIR/jts-main) |
| locationtech/jts | tag 1.20.0 | 6e95fe82 (tag object 9dd8436f) | the latest JTS release |

`git diff 3.15.0 main -- src/operation/relateng include/geos/operation/relateng` is empty. I also built GEOS 3.13.0 (d7957246), the first RelateNG release, from source to date the regression.

## 1. Reproduction on the latest code

Cases: `cases.jsonl`, in case v2 format with ids `geos-relateng-line-end-skip:les-*`. Programs: `repro.c` (C API), `repro_shapely.py` and `Repro.java`. Captured output is in `output/`.

| case | A | B | exact | GEOS main / 3.15.0 / 3.14.1 / 3.13.1 / 3.13.0 | GEOS 3.11.4 | JTS 1.20.0 | JTS master |
|---|---|---|---|---|---|---|---|
| les-1 | `POINT (10 10)` | `MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))` | `FF0FFF102` | `FF0FFF1F2` | ok | `FF0FFF1F2` | ok |
| les-1-parts-swapped | same | `MULTILINESTRING ((5 5, 6 6), (0 0, 1 0, 1 1, 0 0))` | `FF0FFF102` | ok | ok | ok | ok |
| les-1-operands-swapped | B of les-1 | `POINT (10 10)` | `FF1FF00F2` | `FF1FFF0F2` | ok | wrong | ok |
| les-1-degenerate-closed | `POINT (10 10)` | `MULTILINESTRING ((0 0, 1 0, 0 0), (5 5, 6 6))` | `FF0FFF102` | `FF0FFF1F2` | ok | `FF0FFF1F2` | ok |
| les-2-polygon-target | `POLYGON ((1 2, 4 0, 1 0, 1 2))` | `MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))` | `1F2001102` | `1F20011F2` | ok | wrong | ok |
| les-2-operands-swapped | B of les-2 | A of les-2 | `101F00212` | `101F0F212` | ok | `101F0F212` | ok |
| les-3-jts-1175 | `LINESTRING (10 10, 20 20)` | `MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (-1 0, 0 0))` | `FF1FF0102` | `FF1FF01F2` | ok | wrong | ok |
| les-4-both-operands | `MULTILINESTRING ((3 0, 4 3, 1 4, 3 0), (0 1, 1 3, 2 1))` | `MULTILINESTRING ((8 8, 7 6, 8 7, 8 8), (7 7, 7 6))` | `FF1FF0102` | `FF1FFF1F2` | ok | not run | not run |
| les-5-gc-area-vertex | `GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))` | `LINESTRING (10 10, 11 11)` | `FF2FF1102` | `FF2FFF102` | ok | `FF2FFF102` | `FF2FFF102` |
| les-5-gc-squares-swapped | squares swapped | same | `FF2FF1102` | ok | ok | ok | ok |
| les-5-gc-operands-swapped | the line | the GC | `FF1FF0212` | `FF1FF02F2` | ok | wrong | wrong |
| les-6-gc-nested | `GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))` | `LINESTRING (10 10, 11 11)` | `FF2FF1102` | `FF2FFF102` | ok | `FF2FFF102` | `FF2FFF102` |
| les-6-gc-polygons-swapped | squares swapped | same | `FF2FF1102` | ok | ok | ok | ok |
| les-6-gc-operands-swapped | the line | the GC | `FF1FF0212` | `FF1FF02F2` | ok | wrong | wrong |

`GEOSPreparedRelate` gives the same wrong matrices. `GEOSRelatePattern(POINT (10 10), B, "FF*FF**0*")` returns 0 (exact: 1). The patched build (main + both patches) is correct on every row. The 3.14.1, 3.13.1 and 3.11.4 results come from the Shapely wheels. `repro_shapely.py` does not include the two GC operands-swapped rows (les-5, les-6), so those were checked separately with the same wheels: `FF1FF02F2` on 3.14.1 and 3.13.1, `FF1FF0212` on 3.11.4.

Build and run: `GEOS_CONFIG=... JTS_JAR=... ./run.sh`. The line used here was `cc -O1 repro.c $(geos-config --cflags) $(geos-config --clibs) -Wl,-rpath,$(geos-config --prefix)/lib`.

## 2. Minimisation

les-1 is the smallest *non-degenerate* case for this mechanism:

1. The skip fires only after a line end in the target's exterior has been found, and it loses data only if every such end found so far is Mod-2 interior (no B/E recorded yet). With a single point as the target, every end of the first element is in the exterior, so that element must have no Mod-2 boundary: a closed line, whose start is its only tested end, or an open line whose two ends are both shared with other elements (as in les-3, whose target is a distant line). The smallest non-degenerate closed line is a triangle ring.
2. The skip also needs a *later* element that is envelope-disjoint from the target and has boundary ends.
3. A is a single point, the simplest target.
4. Every coordinate is an integer ≤ 10.

A degenerate closed element is smaller still: the there-and-back line (0 0, 1 0, 0 0) is valid and triggers the same bug with 5 coordinates in B instead of 6 (les-1-degenerate-closed: GEOS `FF0FFF1F2`, exact `FF0FFF102`). The reports use les-1 because it avoids a self-overlapping line.

The JTS #1175 case, les-3, is about the same size. Among the variants, les-2 is the one with a polygon target, reached through a shared endpoint rather than a closed element: its first element's other end (1 1) is on A's boundary, not in A's exterior, so no B/E is recorded before the skip.

For the area-vertex variant, les-5 (two overlapping axis-parallel squares and a segment) and les-6 (two nested squares and a segment) have the same size. The skip needs the first polygon's tested vertex to lie inside another polygon of the same GC. les-6 is the cleanest case: *no* vertex of its first polygon is on the union's boundary, so choosing a better vertex per ring (the TODO in `computeAreaVertex`, or step 1 of D3's prototype fix in the sibling finding) cannot fix it; only a change to the skip does. les-5 is fixed by either change.

## 3. Exact answer, independent checks, validity, documented contract

- **Exact engine.** `geotruth relate --dual` computes both routes: the arrangement route (`relate.py`) and the independent witness-point route (`relate_witness.py`). They agree on every case here (`output/exact.jsonl`, `covered-ring/exact.jsonl`). `tests/reference/indep.py` covers polygon/polygon only, so it does not apply to these line inputs.
- **Hand derivation.** In les-1, B's first element is closed, so it has no Mod-2 boundary. Bd(B) = {(5 5), (6 6)}, and both points are in Ext(A), so EB = 0. Every other entry follows from disjointness. In les-5 and les-6, Bd(A) is the outline of the union of the two squares, far from B, so BE = 1.
- **The library's own point location** confirms the exact answers:
  - `GEOSBoundary(B)` is `MULTIPOINT ((5 5), (6 6))`, and `relate(POINT (5 5), B)` is `F0FFFF102`.
  - The same geometries with their elements reordered give the exact matrix.
  - GEOS 3.11.4's RelateOp gives the exact matrix on every case. JTS's default `Geometry.relate` (RelateOp) gives it on the line cases; it throws `IllegalArgumentException` for GeometryCollections.
- **Validity.** Every input is valid: `GEOSisValid` = 1, and geotruth's exact `validity.is_valid` agrees. MultiLineStrings have no validity constraints beyond two distinct points per element. GeometryCollections may contain overlapping polygons. RelateNG documents GC support "using union semantics" (include/geos/operation/relateng/RelateNG.h, class comment).
- **Documented limits.** The default boundary rule is OGC Mod-2, and the answers above use it. RelateNG documents robustness caveats only for invalid input and round-off (JTS relateng/package-info). Neither applies: every coordinate is a small integer, and no computed intersection point is involved.
- **Not by design.** JTS labelled #1175 `type-bug` and fixed it.

## 4. Root cause

Line numbers are for GEOS `main` ae9cdd9.

- **Line ends.** In `RelateNG::computeLineEnds` (src/operation/relateng/RelateNG.cpp:514-555), one flag `hasExteriorIntersection` gates the envelope-disjoint skip at lines 531-534. `computeLineEnd` (560-574) sets that flag for any line end in the target exterior (line 573). But `TopologyComputer::addLineEndOnGeometry` (TopologyComputer.cpp:346) records only the entry for the end's own location. For a Mod-2 interior end that is I/E, never B/E. JTS #1200 tracks interior and boundary exterior ends separately. The port is `patch/port-jts-1200.diff`.
- **Area vertices.** `RelateNG::computeAreaVertex` (RelateNG.cpp:578-613) has the same skip at lines 596-598. `computeAreaVertex(ring)` (619-630) tests the ring's first vertex. The maintainers anticipated that this vertex may not be on the boundary of a polygon cluster: the TODO at line 621 says *"use extremal (highest) point to ensure one is on boundary of polygon cluster"*. What the TODO does not mention is the interaction with the skip. `TopologyComputer::addAreaVertex` (413-430) records B/E and E/E only when that vertex is on the boundary (lines 425-428). A GC vertex inside another polygon records only I/E, and the skip then drops the later polygons, which carry the boundary. The fix skips only after a *boundary* vertex was found in the exterior (`patch/area-vertex-skip.diff`).
- **Patch order.** `patch/area-vertex-skip.diff` must be applied after `patch/port-jts-1200.diff`. Its RelateNG.h hunk uses `Location`, whose `using` alias only the port adds. `git apply` accepts it on plain `main`, but the result does not compile. Applied in order, the two patches give exactly the tree that was built and tested.
- **Relation to the sibling finding D3** (`geos-relateng-geometrycollection-semantics`, `FINAL_3_union_boundary.md`). D3 is about the same function and the same TODO (RelateNG.cpp:619-630, TODO at 621), and its no-boundary-vertex example shows the same symptom (`FF2FFF102` where `FF2FF1102` is exact). Step 1 of D3's `prototype_fix_3.diff` (use a union-boundary vertex of the ring when the first vertex is interior) also fixes les-5, whose first square has union-boundary vertices such as (3 1); D3 reports that its patch 3 also fixes 19 area-vertex-skip cases in its own sweeps. It cannot fix les-6, whose first square has no union-boundary vertex. Checked on the sibling's prototype build (all its patches, without the skip fix): les-5 `FF2FF1102` (exact), les-6 still `FF2FFF102`, les-6 operands swapped still `FF1FF02F2`. So the skip fix is needed independently. The two GC reports should be filed so that they reference each other, not as unrelated issues: FINAL.md and JTS_FINAL.md here point to the union-boundary report, and D3's FINAL_3_union_boundary.md already points to "the area-vertex skip (reported separately)".
- **Why the named predicates are unaffected.** The first exterior end or vertex always records Interior ∩ Exterior of dimension 1 or 2, through `addLineEndOnLine` / `addLineEndOnArea` / `addAreaVertex`, or through `initExteriorDims` for a point target. That entry already makes `contains`, `covers`, `within`, `coveredBy` and `equals` false. The remaining predicates do not read BE/EB.

## 5. Random sweeps and the patch (`sweep/`)

Three sweeps of 3000 cases each were compared against exact answers from the arrangement route. The full table is in `sweep/summary.txt`. Counts of skip-class disagreements (lost line ends, lost area-vertex boundary):

| sweep | 3.13.0 | 3.15.0 | main | main + port-jts-1200 + area-vertex-skip |
|---|---|---|---|---|
| sweep-1 (MultiLineStrings with far elements) | 279 | 279 | 279 | 0 |
| ring-2 (polygon vs lines) | 9 | 9 | 9 | 0 |
| gc-3 (GC of polygons) | 65 | 65 | 65 | 0 |

The gc-3 count mixes the two mechanisms. 45 of the 65 cases lose BE or EB in `computeAreaVertex` (`other BE:1->F` 22 + `other EB:1->F` 22 + 1 case that also loses a line-end EB), and 20 lose only line ends in `computeLineEnds` (`lost-end EB` 11 + `lost-end BE` 9). JTS master, which has #1200, still has exactly the 45 (`sweep/summary.txt`, rows "JTS master"), and JTS 1.20.0 has all 65. So the JTS report quotes 45; the 65 is what the two GEOS patches remove together.

With the patches every line-end and area-vertex disagreement disappears, and nothing else changes. What remains on main+patches:

- the covered-ring regression: ring-2, 725 cases;
- the same regression with a GC or ring-touch operand B: gc-3, 7 cases;
- one inexact-node case (sweep-1, a crossing at (1/3, 4/3) on a collinear overlap). That class is already known in `tests/crosscheck/test_witness_vs_geos.py` and is out of scope.

The patched GEOS tree was built in $GEOTRUTH_BUILD_DIR/triage2/geos-relateng-line-end-skip/geos-patched, with the two patches applied in the order above. With the two patches, all 171 GEOS XML tests pass, and so do the 155 RelateNG unit tests, which I compiled separately against the patched libgeos. With the covered-ring experiment added, those tests pass too. The rest of the unit suite was not run. The results are in `output/geos-main-ae9cdd9+patches-tests.txt`.

The pinned case in `tests/crosscheck/test_relate_dual.py::test_line_end_skip_confirmed_on_a_single_witness` is also this class. It is A = `MULTILINESTRING ((6 3, 6 6, 1 0, 5 10, 6 6, 6 3), (9 8, 11 2))` against B = `LINESTRING (0 0, 11 1, 0 0)`. The exact matrix is `0F1FF01F2`; GEOS main and 3.13.0 give `0F1FFF1F2`, and the patched build gives `0F1FF01F2`.

## 6. The covered-ring defect: a separate root cause, a regression since 3.13.1

The lead's case: A = `POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))`, B = `MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 -1))`. The exact matrix is `FF210F102`; GEOS main gives `FF2101102`.

**Not line-end-skip.**

- No element is skipped. The ring's start (0 0) is on A's boundary, and the segment is the last element.
- Swapping B's elements does not change the wrong answer.
- The line-end patch alone leaves the output unchanged (`sweep/summary.txt`, ring-2, main+P1).
- JTS 1.20.0 gets the lead case right, and JTS master, which has the #1200 fix, gets it wrong. The line-end cases behave the other way round.

**What it is.** GH-1201 (b0cec404; 3.13 backport 782bec07, so it is in 3.13.1) changed `TopologyComputer::isSelfNodingRequired` (TopologyComputer.cpp:133-146) from `A || B.isSelfNodingRequired()` to `A || B.hasAreaAndLine()`. A linear or multi-polygon-GC B is therefore no longer self-noded when A is polygonal. At (1 0), the node has sections for A's edge and B's segment, but none for B's ring edge, which is collinear with A's edge. A's edge halves are then labelled B-exterior, so BE = 1.

**Evidence** (outputs in `covered-ring/output/`):

- GEOS 3.13.0, built from source, is correct on all six covered-ring cases, and 3.13.1, 3.14.1, 3.15.0 and main are wrong.
- JTS 1.20.0 is correct and JTS master (after #1099) is wrong.
- Swapping the operands (a linear A is self-noded) or adding (1 0) as a vertex of B's ring fixes the matrix.
- Restoring B's flag (`covered-ring/experiment-self-node-linear-b.diff`) fixes every case and all 725 + 7 regression cases in the sweeps.

**Named-predicate consequences.** I found these while sorting the sweep disagreements. All are right in 3.13.0 and wrong since 3.13.1:

- `contains(POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0)), LINESTRING (0 0, 4 0))` is true, and `touches` is false. The exact answers are false and true.
- `covers(MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2))), LINESTRING (0 2, 2 2))` is false. The exact answer is true.
- `within(POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0)), GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0))))` is false, while `contains(B, A)` is true. The exact answers are both true.

**Relation to earlier findings.**

- `geos-multipolygon-touching-parts-predicates` (ring-touch-node): the contains and covers examples above use the same missing-section mechanism as that finding. Its polygon/polygon cases also fail on 3.13.0 (checked here: `2F2F11212` and `212F11212`), so that bug predates GH-1201. For polygon/**line** pairs, though, 3.13.0 was correct: B's flag forced full noding. GH-1201 exposed the ring-touch bug there. That finding's FINAL.md only tested 3.13.1 and later, and polygon/polygon inputs. It may be worth adding a note there, but I have not edited it.
- The gc-overlapping-polygons class in `tests/crosscheck/test_witness_vs_geos.py`: its known case (the `within` example above) is also correct in 3.13.0. With the GC as operand B it is this regression.
- `geos-near-collinear-predicates`: unrelated. It concerns inexact crossing points.

**Recommendation.** File the covered-ring report (`covered-ring/FINAL.md`) separately from the line-end port. It has a different root cause, a different fix, and it trades against GH-1201's performance goal. Link it from the ring-touch report.

## 7. Upstream tracker search (2026-09-26)

**GitHub issue search**, libgeos/geos and locationtech/jts, open and closed. Queries: "RelateNG computeLineEnds", "RelateNG line end boundary skipped disjoint line components MultiLineString", "relate DE-9IM exterior boundary F instead of 0 MultiLineString element order", "RelateNG wrong relate matrix linestring polygon", "port JTS fix RelateNG", "RelateNG self-noding linear B polygonal A", "relate polygon linestring wrong boundary exterior 3.13.1 self-noding regression", "RelateNG GeometryCollection overlapping polygons relate boundary exterior computeAreaVertex", "RelateNG GeometryCollection polygons relate wrong within covers".

- **Found.** jts#1175 is the same line-end defect, and it is closed. It was fixed by jts#1200 (e8de44d9: author date 2026-06-14 01:27 +0200, merged by GitHub 2026-06-13 16:27 -0700, so merged 2026-06-13). NetTopologySuite ported the fix: NTS issue #862, closed by NTS PR #869 (merged into `develop` 2026-08-31; its commit says "Port JTS commit e8de44d9" and "Closes #862"), and NTS PR #886 (merged 2026-09-22) synced JTS's XML test for #1175. The #1175 reporter says GEOS was correct on its case. That was presumably a pre-RelateNG GEOS, because 3.13.0 to main all give `FF1FF01F2`.
- **No GEOS issue or PR ports #1200.** Besides the searches, I checked:
  - the relateng history on `main`, `3.15` and `3.14` (blobless clone);
  - every open and closed libgeos/geos PR branch numbered #1200 to #1536 (189 refs) for relateng changes, of which none touch `computeLineEnds`;
  - NEWS.md.
- **Nothing found** for the area-vertex variant, or for the GH-1201 regression.
- **Related but different.** GEOS #1147/#1148/#1149 are earlier, closed RelateNG regressions (a LineString against a MultiPolygon; GeometryCollection equals, fixed for 3.13.0 by the port of jts#1069; the boundary node rule). #1275 (prepared relate pattern, closed) has no reproducer in the issue, and the mailing-list post it cites was not reachable from the sandbox; this bug gives the same wrong answer prepared and unprepared. #983 and #1022 are old RelateOp GC issues. #1027 is a covers/MultiPolygon issue from before RelateNG. #1064 ("RelateCompute intersection report inconsistent for lines and boundary points", closed) is about the old RelateComputer. #1346 ("Relate result for self-touching line and point?", closed) is a question about a self-touching line, not about skipped elements. All of these are cited in FINAL.md's related-issues list.
- **Local cross-references.** The sibling finding `geos-relateng-geometrycollection-semantics/d3-union-boundary` overlaps with the area-vertex part (section 4); its reports and these reference each other.

## 8. Side observations (not reported)

- geosop's `boundary` operation returns the convex hull: util/geosop/GeometryOp.cpp:297-302 calls `geom.convexHull()`. This is a copy-paste in the CLI tool, not in the library. I found no GitHub issue for it.
- sweep-1 contains one inexact-node case, which is out of scope (see section 5).

## Files

- `FINAL.md`: the GEOS report (port #1200 plus the area-vertex fix). `JTS_FINAL.md`: the JTS report (area-vertex). Filing order: FINAL.md to libgeos/geos, JTS_FINAL.md to locationtech/jts, then the covered-ring reports (`covered-ring/FINAL.md`, `covered-ring/JTS_FINAL.md`). Once numbers exist, replace the "reported separately" mentions with links.
- `repro.c`, `repro_shapely.py`, `Repro.java`, `run.sh`: the repros.
- `cases.jsonl`: cases in case v2 format. `output/exact.jsonl`: exact answers from both routes.
- `output/`: GEOS main, 3.15.0 and 3.13.0; main with the patches applied, plus its test results (`geos-main-ae9cdd9+patches-tests.txt`); Shapely 2.1.2 (GEOS 3.13.1), 2.2.0rc1 (3.14.1) and 2.0.7 (3.11.4); JTS master and 1.20.0; geosop.
- `patch/port-jts-1200.diff`, `patch/area-vertex-skip.diff`: the proposed GEOS fix, tested; apply in this order.
- `sweep/`: the generators, `relate_batch.c`, the classifier, and `summary.txt` (GEOS builds, plus JTS 1.20.0 and master on gc-3).
- `covered-ring/`: `FINAL.md` (GEOS), `JTS_FINAL.md`, `repro.c`, `repro_shapely.py`, `Repro.java`, `cases.jsonl`, `exact.jsonl`, `experiment-self-node-linear-b.diff`, `output/`.
- `finding.toml`: registry snippets for both clusters.
