# Triage: Turf 7.4.0 boolean predicates (lead `turf-touches-overlaps-vertex-rules`)

Status: **confirmed** (booleanTouches on polygons, new, the report is drafted in [FINAL.md](FINAL.md)). The other parts of the lead are duplicates of open issues, or documented tolerances. Nothing has been posted.

## Scope

The lead (corpus/curated/leads.toml, `turf-touches-overlaps-vertex-rules`) has two minimised cases. The first is identical triangles, where `booleanTouches` returns true. The second is `shared-sloped-edge-1-000001.min`, where `booleanTouches` returns false and the exact answer is true. The lead also covers the systematic `booleanOverlap` / `booleanTouches` / `booleanContains` disagreements that adapters/js/README.md describes: the hard-coded 1e-6 tolerances, and the fact that only A's vertices are checked. This triage sorts every Polygon/Polygon predicate cluster of the core tier into one of four groups: a new bug, a known issue, a documented tolerance, or floating-point robustness.

## Upstream heads (git ls-remote, 2026-09-26)

- Turf `master` = bec3ac7860d5d71a31bd9dbc44dd1ac5fab0c0b7 (2026-09-07). npm `latest` = 7.4.0 (tag v7.4.0, commit 22acbd806adb80eece91b7fc43589d5d7788e815). Both are what was tested.
- The other libraries have not moved. GEOS main ae9cdd98be4e, JTS master 3ea61f8cf210, Clipper2 f9c5eb6e14a5 and Boost.Geometry develop 196d04c614c1 all equal the local builds. geo HEAD is c12769fdf745. None of these is used here.

Between v7.4.0 and master, `packages/turf-boolean-touches/index.ts`, `turf-boolean-point-on-line` and `turf-boolean-point-in-polygon` are unchanged except for package.json and tsconfig. `turf-boolean-overlap/index.ts` is unchanged. `turf-boolean-contains/index.ts` changed only in its doc comment. Master was run as its TypeScript sources, bundled with esbuild ([build-master.sh](build-master.sh)).

## Minimal cases ([cases.jsonl](cases.jsonl))

| id | A | B | turf 7.4.0 / master: touches(A,B), touches(B,A) | exact |
|---|---|---|---|---|
| identical-triangles | `POLYGON ((0 0, 1 0, 0 1, 0 0))` | same | true, true | false (`2FFF1FFF2`) |
| overlapping-squares | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` | `POLYGON ((1 0, 3 0, 3 2, 1 2, 1 0))` | true, true | false (`212111212`) |
| apex-on-edge | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` | `POLYGON ((1 2, 2 3, 0 3, 1 2))` | false, true | true (`FF2F01212`) |
| multipolygon-second-part | `MULTIPOLYGON (((10 10, 11 10, 11 11, 10 11, 10 10)), ((0 0, 1 0, 1 1, 0 1, 0 0)))` | `POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0))` | false, false | true (`FF2F11212`) |
| in-hole-shared-edge | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 3, 3 3, 3 1, 1 1))` | `POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))` | false, false | true (`FF2F11212`) |

The two lead cases belong to the first and third mechanisms. The lead's identical triangles, `(0.1 0.5, -0.7 -0.1, -0.04 -0.5)`, are the identical-polygon case. In `shared-sloped-edge-1-000001.min`, B's vertex (1 0.875) lies on A's edge (0 0)-(8 7) and no vertex of A touches B. Turf returns false for touches(A,B) and true for touches(B,A). The exact matrix is `FF2F01212`.

### Exact answers and independent checks

- **geotruth engine**, `geotruth relate --dual` (arrangement route and witness-point route): the matrices above, with both routes in agreement. See [output/exact.jsonl](output/exact.jsonl). `geotruth valid` gives valid for every operand.
- **tests/reference/oracle.py** (slab areas) and **indep.py** (Green's-theorem pieces, Fractions) give the same touches in both orders. Their exact intersection areas are 1/2, 2, 0, 0 and 0. See [output/indep.jsonl](output/indep.jsonl).
- **The library's own functions** ([output/turf-7.4.0.txt](output/turf-7.4.0.txt), from [crosscheck.mjs](crosscheck.mjs)):
  - `booleanValid` is true for all operands, and `booleanIntersects` is true in all five cases.
  - `intersect` (polyclip-ts) returns the triangle and [1,2]x[0,2] for the first two cases, and `null` for the other three.
  - So Turf itself says the interiors meet in cases 1-2 and do not meet in cases 3-5.
- **JSTS 2.12.1** `relate` and `touches`, both orders, agree with the exact answers. JSTS is the reference Turf's own `test.ts` uses when `JSTS=1`. [Shapely 2.1.2 / GEOS 3.13.1](output/shapely-2.1.2-geos-3.13.1.txt) agrees too.
- **By hand**: see the case list in FINAL.md.

The inputs are valid, and within Turf's documented domain. Every coordinate is a small integer, valid as lon/lat. The rings are closed, and they follow the RFC 7946 right-hand rule (shells CCW, the hole CW). Turf's predicates are planar in coordinate space, and for these inputs there is no geodesic ambiguity: every edge is axis-parallel or a short diagonal between integer points, and the contacts are at vertices.

### Versions ([output/](output))

| build | result |
|---|---|
| `@turf/turf` 7.4.0 (npm latest) | 5/5 wrong |
| master bec3ac7 (TS sources via esbuild) | 5/5 wrong |
| `@turf/boolean-touches` 7.0.0, pinned: installed with `@turf/boolean-point-on-line`, `@turf/boolean-point-in-polygon`, `@turf/helpers` and `@turf/invariant` 7.0.0 ([shim-boolean-touches-7.0.0.mjs](shim-boolean-touches-7.0.0.mjs)) | 5/5 wrong |
| `@turf/boolean-touches` 6.5.0 (`@turf/turf` 6.5.0 does not export it; [shim-boolean-touches-6.5.0.mjs](shim-boolean-touches-6.5.0.mjs)) | 5/5 wrong |

## Bug or by design?

| behaviour | verdict | why |
|---|---|---|
| `booleanTouches` Polygon/Polygon: only A's shell vertices are tested; interior overlap is detected only through a vertex of A strictly inside B (index.ts L560-L581). B's vertices are ignored, and contact is tested against B's shell only, so a hole is never a contact location (B's holes are respected by the strictly-inside test, which gets the whole of B). | **bug, new** → FINAL.md | Contradicts the documented definition ("true if none of the points common to both geometries intersect the interiors of both geometries"). The identical-polygon case breaks it outright. The package's `test.ts` checks the fixtures against JSTS/Shapely `touches`, so OGC semantics are the intended contract. Maintainers also treat DE-9IM alignment as a bug fix (#3025, #3024). No tolerance is involved: `booleanPointOnLine` is called without `epsilon`, so it tests `cross === 0` exactly. |
| `booleanTouches` MultiPolygon branches: only the first part of each MultiPolygon is examined; L731 bounds the vertex loop by the ring count; L598 (Polygon/MultiPolygon) and L753 (MultiPolygon/MultiPolygon) pass a single ring as Polygon coordinates, so `booleanPointInPolygon` never returns true there and the strictly-inside test is inert: A "touches" B as soon as a tested vertex of A lies on a ring of B's first part, even when A lies inside B (triangle (2 0, 3 2, 1 2) and MultiPolygon [0,4]^2: true, exact `2FF10F212`). These branches do test all rings of the first part for contact (B's in P/MP, L584-L590; A's in MP/P, L705-L706), so case 5 with the donut as a one-part MultiPolygon is correct. | **bug, new** (same function; included in FINAL.md as case 4 and in the analysis) | Index and argument errors, with no documented restriction. In MP/MP the inert test only shows when A's first polygon has holes, because of the L731 bound ([extra.mjs](extra.mjs)). |
| `booleanOverlap` Polygon/Polygon is true as soon as any pair of edges intersects (overlap index.ts L79-L89), so polygons that only touch count as overlapping | **bug, known: #2454** (open) | Contradicts the doc ("intersection ... of the same dimension"). Not re-reported. See the draft comment below for a sub-case #2454 does not state. |
| `booleanOverlap` is true for A ⊃ B when the boundaries share an edge or a vertex. Example: [0,2]² and [0,1]² give `booleanOverlap` = true and `booleanContains` = true; the exact matrix is `212F11FF2`. | **bug, same root cause as #2454** | Contradicts the doc sentence added by #2133 ("provided that neither completely contains the other"). A comment on #2454 is the right channel, not a new issue. |
| `booleanOverlap` returns false when `geojsonEquality(a, b, {precision: 6})` holds (overlap index.ts L52) | **by design / tolerance** | A hard-coded 1e-6 absolute tolerance. The booleanOverlap docs do not mention it, but it matches Turf's 6-decimal design point (RFC 7946 §11.2, cited in boolean-contains index.ts L498-L506) and `booleanEqual`'s documented default precision of 6. It only matters when the whole geometry is below 1e-6 in size. Example: 2e-7 squares shifted by 1e-7 give false, and the exact answer is `212111212`. Not reported. |
| `booleanContains` / `booleanWithin`: boundary tolerance `BOUNDARY_DISTANCE_TOLERANCE = 1e-6` (contains index.ts L506) | **by design** | Documented in the source, with the RFC 7946 rationale (L498-L505). The non-hole contains/within false positives in the core tier are all sub-1e-6 slivers or 1e-10-scale inputs. |
| `booleanContains` / `booleanWithin` ignore the holes of the container (`isPolyInPoly`, "Only takes into account outer rings", contains index.ts L440). Example: a donut contains its filled shell. | **bug, known: #1882** (open) | Not re-reported. #3109 (open, v8 milestone) plans to replace `isPolyInPoly` with a difference-based test. |
| 3 `touches` true on exactly disjoint near-miss pairs, and 10 `overlaps` false on ulp-level hole fills | **floating-point robustness** | The cross product in `booleanPointOnLine` and `lineIntersect` rounds. Turf claims no exactness, so this is not reported. |

## Core-tier numbers ([output/core-clusters.txt](output/core-clusters.txt))

Core tier, turf@7.4.0 against the exact expected answers. These are the Polygon/Polygon disagreements.

- **touches true, exact false: 241.** 238 of these have meeting interiors, some vertex of A on B's shell, and no vertex of A strictly inside B. That is the mechanism behind cases 1 and 2. The other 3 are the robustness cases.
- **touches false, exact true: 59.** 31 are argument-order cases, where touches(B,A) is true (case 3). 28 involve holes (case 5).
- **overlaps true, exact false: 505.** 502 have the edge-contact mechanism of #2454: 346 are touch-only pairs, and 156 are containment or equality with a shared boundary. The other 3 are the robustness near-misses.
- **overlaps false, exact true: 165.** 155 come from the geojsonEquality 1e-6 check, and 10 are robustness cases.

Over the 2000 non-empty Polygon/MultiPolygon pairs of the core tier (all valid), `booleanTouches` disagrees on 404, across 10 families (hole-contact, int-grid, multi-touch, near-collinear, scaled, shared-edge, sliver-spike, tiling-contact, tiny-transform, vertex-on-edge). Restricted to valid areal pairs whose coordinates are all integers below 2^24, so that every float operation Turf performs is exact, 70 of 207 are wrong (60 false positives, 10 false negatives).

## Upstream search (2026-09-26)

Queries on the Turfjs/turf issues and PRs, open and closed: `booleanTouches`, `boolean-touches`, `touches`, `touch polygon`, `booleanOverlap`, the labels `@turf/boolean-touches` (no results), `@turf/boolean-overlap` and `@turf/boolean-contains`, discussions for "touches", and semantic searches ("booleanTouches returns true for identical polygons", "booleanTouches incorrect true overlapping polygons interior", "booleanTouches MultiPolygon only first polygon checked", "polygons that share only a vertex or edge reported as touching depends on argument order").

- There is **no issue about booleanTouches' Polygon/MultiPolygon results.** The only booleanTouches bug item is **#3088**, an open PR that fixes the LineString / MultiLineString loop index. It does not cover the polygon branches.
- #2454 (open) and #1991 (open, "booleanOverlap bug case", about containment returning false) concern booleanOverlap. #2271 concerns booleanIntersects of lines and polygons side by side.
- #1882 (open), #1988, #2318, #2588 and #2744 concern booleanContains. #3109 (open, v8 milestone) is the planned rewrite of `isPolyInPoly`.
- #1467 (open, 2018) reports the same vertex-only concern for booleanContains (every inner vertex inside, an edge leaving the outer polygon); cited in FINAL.md as related. #3104 (7.4.0, "Closes #2242") added the edge splitting to `isPolyInPoly` for that concern. Its own example does not show it, though: the inner edge from (0.1 1.9) to (1.9 0.1) runs through the reflex corner (1 1) in decimal, and just inside it in binary doubles (x + y = 2 - 8.3e-17), so the exact answer is contains = true (geotruth `212FF1FF2`, both routes), which Turf 7.4.0 and master return. FINAL.md therefore cites #1467 only for the concern, not as a wrong answer.
- #3025 (closed; filed by a maintainer and labelled bug) and PR #3024 aligned booleanContains with DE-9IM for MultiPoints.
- #1960, #2427 and #1781 are questions about detecting adjacent polygons. They report no wrong booleanTouches result.
- #2398 / #2431 are about booleanTouches documentation.

## Draft comment for #2454 (optional, not posted)

> The same edge-contact rule also gives `true` when one polygon contains the other and their boundaries share an edge or a vertex. This contradicts "provided that neither completely contains the other" in the docs:
> ```js
> const a = turf.polygon([[[0,0],[2,0],[2,2],[0,2],[0,0]]]);
> const b = turf.polygon([[[0,0],[1,0],[1,1],[0,1],[0,0]]]);
> turf.booleanOverlap(a, b);  // true  (expected false; booleanContains(a, b) is true, DE-9IM 212F11FF2)
> ```
> (Checked on turf 7.4.0 and on master bec3ac7. The cause is `lineIntersect(segment1, segment2)` in packages/turf-boolean-overlap/index.ts L79-L89, which counts any shared point of two edges.)

Evidence for this comment (not part of it): extra.mjs, output/extra-turf-7.4.0.txt, output/extra-turf-master-bec3ac7.txt and output/exact-extra.txt.

## Re-verification (second pass, 2026-09-26)

Everything above was re-checked from scratch rather than taken over from the first pass (scratch: $GEOTRUTH_BUILD_DIR/triage2/turf-boolean-predicates/verify2):

- **Heads** (git ls-remote): Turf master is still bec3ac7860d5 and npm `latest` is still 7.4.0. GEOS ae9cdd98be4e, JTS 3ea61f8cf210, Clipper2 f9c5eb6e14a5, Boost.Geometry 196d04c614c1 and geo c12769fdf745 have not moved either.
- **Release**: a fresh `npm install` of this directory's package.json (@turf/turf 7.4.0, jsts 2.12.1), then `./run.sh`: 5/5 cases wrong, the same output as output/turf-7.4.0.txt.
- **Master**: a fresh `build-master.sh` (new shallow clone at bec3ac7, esbuild bundle). The bundle's source markers show `turf/packages/turf-boolean-touches/index.ts`, `turf-boolean-point-on-line` and `turf-boolean-point-in-polygon` from the clone, and no `node_modules/@turf` code. Result: 5/5 wrong. `git diff v7.4.0 HEAD` confirms that the index.ts of boolean-touches, boolean-point-on-line, boolean-point-in-polygon and boolean-overlap are unchanged, and that boolean-contains changed only in its doc comment.
- **Exact answers**: `geotruth relate --dual` gives the five matrices, and the witness route agrees on each. `geotruth valid --operand a|b` is valid for all ten operands. tests/reference/indep.py (`evaluate_geoms`, both orders, selfcheck true) and oracle.py (`evaluate`, both orders) give touches = false, false, true, true, true. extra.mjs's cases are in output/exact-extra.txt.
- **Source**: the line numbers in FINAL.md were re-read at bec3ac7 (Polygon/Polygon L560-L581, Polygon/MultiPolygon L582-L605 with the ring-as-Polygon call at L598, MultiPolygon/Polygon L703-L726, MultiPolygon/MultiPolygon L727-L761 with the ring-count bound at L731 and the same ring-as-Polygon call at L753). `booleanPointOnLine` is called without `epsilon`. test.ts runs `booleanTouches(feature1, feature2)` in one order only and checks JSTS / Shapely `touches` when `JSTS` / `SHAPELY` is set.
- **Statistics**: re-run: 70 of 207 integer pairs wrong (60 false positives, 10 false negatives), and 404 of 2000 areal pairs.
- **The overlay shortcut is not a safe fix.** `booleanIntersects(a, b) && intersect(a, b) === null` fails on 71 of the 2012 valid areal core cases, which includes 12 with empty elements. 19 of the 71 are cases where `intersect` (polyclip-ts) throws, some of them on integer inputs ("Unable to complete output ring"). The rest are wrong answers. This is why FINAL.md proposes the edge-splitting approach that `isPolyInPoly` already uses (`splitLineIntoSegmentsOnPolygon` → `lineSplit`, contains index.ts L357-L367, called from `isPolyInPoly` at L478-L492), and not an overlay.
- **Tracker** (GitHub semantic search on Turfjs/turf, plus the literal web searches `booleanTouches`, `"boolean-touches"`, `touches is:issue` and the discussions search `touches`): still no report of the polygon behaviour.
  - The first result page of each literal search lists #3088, #2702, #2617, #2431, #2398, #2157, #1882, #2170, #1947, #1428, #1338, #1029, #88, #2328, #1712, #916, #623, #203 and #56. None reports a wrong polygon `touches` result.
  - #1882 appears in the `booleanTouches` search, but its rendered page (body and comments) does not mention touches. It is a booleanContains hole report, already listed above.
  - The 2026 boolean PRs (#3079, #3080, #3085, #3088, #3091, #3097, #3099, #3100, #3102, #3103, #3104) change other predicates, or the line branches of booleanTouches (#3088). Open PR #3164 touches boolean-point-in-polygon and boolean-point-on-line for performance only.
  - #2454 (open, no comments) does not mention the containment sub-case. #1991 (open) asks for `booleanOverlap` = true under containment, which is the opposite of the documented OGC meaning, so it is not the same report.

Verdict unchanged: one new bug report (FINAL.md, booleanTouches on polygons). The #2454 containment sub-case is at most a comment. Everything else is a known issue or a documented tolerance. Nothing has been posted.

## Corrections after independent review (2026-09-26)

An independent review reproduced every claim and did not refute the finding, but found four factual errors. Each was re-checked (scratch: $GEOTRUTH_BUILD_DIR/triage2/turf-boolean-predicates/fix, with a fresh `npm install` of 7.4.0, a fresh master bundle from build-master.sh and a fresh pinned 7.0.0 install) and is now fixed here, in FINAL.md, in finding.toml and in the output headers:

1. **7.0.0 was mislabelled.** The earlier "`@turf/turf` 7.0.0" run had exercised 7.4.0 code: the `^7.0.0` dependencies of `@turf/turf` 7.0.0 resolved `@turf/boolean-touches`, `boolean-point-on-line` and `boolean-point-in-polygon` to 7.4.0. Re-run with those three plus `@turf/helpers` and `@turf/invariant` installed at exactly 7.0.0 (`npm ls` lists no other `@turf` version; [shim-boolean-touches-7.0.0.mjs](shim-boolean-touches-7.0.0.mjs)): 5/5 wrong, the same output. [output/turf-7.0.0.txt](output/turf-7.0.0.txt) was regenerated from that install. v7.0.0's `index.ts` differs from master only in a JSDoc tag (`@name booleanTouches` became `@function`).
2. **The root cause was incomplete for Polygon/MultiPolygon and MultiPolygon/MultiPolygon.** L598 and L753 pass one ring as a Polygon's `coordinates`. `booleanPointInPolygon` then returns true for none of 20000 random probes, so the strictly-inside test never fires in those branches. This causes further false positives, for example the triangle (2 0, 3 2, 1 2) against the MultiPolygon [0,4]^2 (true, exact `2FF10F212`), and [0,1]^2 against the MultiPolygon [0,4]^2 (true, exact `2FF11F212`; the reverse order is also true, through the MultiPolygon/Polygon vertex-of-A rule). In MultiPolygon/MultiPolygon the L731 bound hides it unless A's first polygon has holes. These cases are now in FINAL.md's analysis, extra.mjs and [output/exact-extra.txt](output/exact-extra.txt). JSTS 2.12.1 agrees with the exact matrices.
3. **The hole wording was too broad.** "Holes are never examined" holds only for the Polygon/Polygon contact test. There, B's holes are respected by the strictly-inside test, which gets the whole of B. The Polygon/MultiPolygon branch tests contact against all rings of B's first part (L584-L590), and MultiPolygon/Polygon visits all rings of A's first part (L705-L706). Case 5 with the donut as a one-part MultiPolygon is correct (true in both orders).
4. **The fixture count.** turf-boolean-touches has four Polygon/Polygon fixtures (two in test/true, two in test/false), and the small square is `feature1` in all four. The triage summary had said "both". FINAL.md gives the count (two in test/true, two in test/false), and so does finding.toml.

The reviewer also pointed to #1467 (see the upstream search above) and suggested [0,2]^2 and [0,1]^2 as a simple Polygon/Polygon fixture (touches true one way, false the other; exact `212F11FF2`). Both are now in FINAL.md, together with #3109.

## Files

- [repro.mjs](repro.mjs): the five cases, public API only. Run it with `npm install && node repro.mjs`. `TURF_MODULE=<bundle> node repro.mjs` runs it against another build.
- [extra.mjs](extra.mjs): public-API checks for the analysis claims: the MultiPolygon/MultiPolygon ring-count bound (L731), the Polygon/MultiPolygon first-part-only branch, the two original lead cases, the #2454 containment sub-case (and the same pair for booleanTouches), the inert strictly-inside test of the Polygon/MultiPolygon and MultiPolygon/MultiPolygon branches (L598, L753), and case 5 with the donut as a Polygon and as a one-part MultiPolygon.
- [run.sh](run.sh), [package.json](package.json) (pins `@turf/turf` 7.4.0 and `jsts` 2.12.1), [crosscheck.mjs](crosscheck.mjs), [build-master.sh](build-master.sh), [shim-boolean-touches-7.0.0.mjs](shim-boolean-touches-7.0.0.mjs) and [shim-boolean-touches-6.5.0.mjs](shim-boolean-touches-6.5.0.mjs) (the older releases).
- [cases.jsonl](cases.jsonl): the cases as typed JSON, which `geotruth relate --dual --id <id> @cases.jsonl` accepts.
- output/:
  - `turf-7.4.0.txt`, `turf-master-bec3ac7.txt`, `turf-7.0.0.txt` (@turf/boolean-touches 7.0.0, pinned), `boolean-touches-6.5.0.txt`: captured library outputs.
  - `extra-turf-7.4.0.txt`, `extra-turf-master-bec3ac7.txt`: extra.mjs on the release and on master; `exact-extra.txt`: the exact matrices of its cases (both relate routes).
  - `exact.jsonl`, `indep.jsonl`, `shapely-2.1.2-geos-3.13.1.txt`: the references.
  - `core-clusters.txt`: the cluster analysis.
- [FINAL.md](FINAL.md): the maintainer-ready report. [finding.toml](finding.toml): the registry snippet.

Other defects noticed in `booleanTouches` but out of scope for this lead. The MultiLineString/MultiPoint branch indexes the lines with the MultiPoint index, `geom1.coordinates[ii]` (L336, L344). This is related to, but not fixed by, #3088, which fixes the same kind of slip at L251-L254.
