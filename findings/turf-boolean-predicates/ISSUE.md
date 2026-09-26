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
| `@turf/turf` 7.0.0 | 5/5 wrong |
| `@turf/boolean-touches` 6.5.0 (`@turf/turf` 6.5.0 does not export it; [shim-boolean-touches-6.5.0.mjs](shim-boolean-touches-6.5.0.mjs)) | 5/5 wrong |

## Bug or by design?

| behaviour | verdict | why |
|---|---|---|
| `booleanTouches` Polygon/Polygon: only A's shell vertices are tested; interior overlap is detected only through a vertex of A strictly inside B (index.ts L560-L581). Holes and B's vertices are ignored. | **bug, new** → FINAL.md | Contradicts the documented definition ("true if none of the points common to both geometries intersect the interiors of both geometries"). The identical-polygon case breaks it outright. The package's `test.ts` checks the fixtures against JSTS/Shapely `touches`, so OGC semantics are the intended contract. Maintainers also treat DE-9IM alignment as a bug fix (#3025, #3024). No tolerance is involved: `booleanPointOnLine` is called without `epsilon`, so it tests `cross === 0` exactly. |
| `booleanTouches` MultiPolygon branches: only the first part of each MultiPolygon is examined; L731 bounds the vertex loop by the ring count; L598 passes a ring as Polygon coordinates | **bug, new** (same function; included in FINAL.md as case 4 and in the analysis) | Index errors, with no documented restriction. |
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

Over all areal pairs in the core tier, `booleanTouches` disagrees on 404 cases, across 10 families. Restricted to valid areal pairs whose coordinates are all integers below 2^24, so that every float operation Turf performs is exact, 70 of 207 are wrong (60 false positives, 10 false negatives).

## Upstream search (2026-09-26)

Queries on the Turfjs/turf issues and PRs, open and closed: `booleanTouches`, `boolean-touches`, `touches`, `touch polygon`, `booleanOverlap`, the labels `@turf/boolean-touches` (no results), `@turf/boolean-overlap` and `@turf/boolean-contains`, discussions for "touches", and semantic searches ("booleanTouches returns true for identical polygons", "booleanTouches incorrect true overlapping polygons interior", "booleanTouches MultiPolygon only first polygon checked", "polygons that share only a vertex or edge reported as touching depends on argument order").

- There is **no issue about booleanTouches' Polygon/MultiPolygon results.** The only booleanTouches bug item is **#3088**, an open PR that fixes the LineString / MultiLineString loop index. It does not cover the polygon branches.
- #2454 (open) and #1991 (open, "booleanOverlap bug case", about containment returning false) concern booleanOverlap. #2271 concerns booleanIntersects of lines and polygons side by side.
- #1882 (open), #1988, #2318, #2588 and #2744 concern booleanContains. #3109 (open) is the planned rewrite of `isPolyInPoly`.
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
> (turf 7.4.0 and master bec3ac7; the root cause is `lineIntersect(segment1, segment2)` in packages/turf-boolean-overlap/index.ts L79-L89, which counts any shared point of two edges.)

## Files

- [repro.mjs](repro.mjs): the five cases, public API only. Run it with `npm install && node repro.mjs`. `TURF_MODULE=<bundle> node repro.mjs` runs it against another build.
- [run.sh](run.sh), [package.json](package.json) (pins `@turf/turf` 7.4.0 and `jsts` 2.12.1), [crosscheck.mjs](crosscheck.mjs), [build-master.sh](build-master.sh).
- [cases.jsonl](cases.jsonl): the cases as typed JSON, which `geotruth relate --dual --id <id> @cases.jsonl` accepts.
- output/:
  - `turf-7.4.0.txt`, `turf-master-bec3ac7.txt`, `turf-7.0.0.txt`, `boolean-touches-6.5.0.txt`: captured library outputs.
  - `exact.jsonl`, `indep.jsonl`, `shapely-2.1.2-geos-3.13.1.txt`: the references.
  - `core-clusters.txt`: the cluster analysis.
- [FINAL.md](FINAL.md): the maintainer-ready report. [finding.toml](finding.toml): the registry snippet.

Other defects noticed in `booleanTouches` but out of scope for this lead. The MultiLineString/MultiPoint branch indexes the lines with the MultiPoint index, `geom1.coordinates[ii]` (L336, L344). This is related to, but not fixed by, #3088, which fixes the same kind of slip at L251-L254.
