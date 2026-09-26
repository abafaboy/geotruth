# booleanTouches gives wrong results for polygons: identical or overlapping polygons "touch", and the result depends on argument order

## Summary

For Polygon and MultiPolygon inputs, `booleanTouches(a, b)` only looks at the vertices of the outer ring of `a` (and, for a MultiPolygon, only its first polygon). It returns true when some vertex of `a` lies on the outer ring of `b` and no vertex of `a` is strictly inside `b`. It never checks the vertices of `b`, holes, the other parts of a MultiPolygon, or edges that pass through the other polygon's interior. So:

- two **identical** polygons "touch", and so do two polygons that **overlap** when none of `a`'s vertices is strictly inside `b` (false positives);
- polygons that do touch are reported as not touching when only a vertex of `b` lies on `a`'s boundary, so `booleanTouches(a, b) !== booleanTouches(b, a)`. The same happens when the contact is with a hole, or with the second part of a MultiPolygon (false negatives).

This contradicts the documented definition ("Boolean-touches true if none of the points common to both geometries intersect the interiors of both geometries"), and also the OGC/JTS `touches` predicate that the package's own tests compare against (`test.ts` checks every fixture against JSTS and Shapely when `JSTS=1` / `SHAPELY=1` is set).

## Minimal reproduction

All inputs are valid (`booleanValid` = true). Coordinates are small integers, and the rings follow the RFC 7946 right-hand rule.

```js
import { booleanTouches, polygon, multiPolygon } from "@turf/turf"; // 7.4.0

const tri = polygon([[[0, 0], [1, 0], [0, 1], [0, 0]]]);
booleanTouches(tri, tri);                                             // true   (expected false)

const sq02 = polygon([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]);
const sq13 = polygon([[[1, 0], [3, 0], [3, 2], [1, 2], [1, 0]]]);
booleanTouches(sq02, sq13);                                           // true   (expected false)

const apex = polygon([[[1, 2], [2, 3], [0, 3], [1, 2]]]);            // apex (1,2) on sq02's top edge
booleanTouches(sq02, apex);                                           // false  (expected true)
booleanTouches(apex, sq02);                                           // true
```

Two further cases from the same function (full script: [repro.mjs](repro.mjs)):

```js
// the square that touches b is the 2nd polygon of the MultiPolygon (shared edge x = 1)
const mp = multiPolygon([[[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
                         [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]);
const right = polygon([[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]);
booleanTouches(mp, right);                                            // false  (expected true)
booleanTouches(right, mp);                                            // false  (expected true)

// b lies in a's hole and shares an edge with the hole
const donut = polygon([[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]]);
const inHole = polygon([[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]);
booleanTouches(donut, inHole);                                        // false  (expected true)
booleanTouches(inHole, donut);                                        // false  (expected true)
```

| case | a / b | `touches(a,b)` | `touches(b,a)` | expected (both orders) | DE-9IM |
|---|---|---|---|---|---|
| 1 | identical triangles | **true** | **true** | false | `2FFF1FFF2` |
| 2 | squares [0,2]x[0,2] and [1,3]x[0,2] | **true** | **true** | false | `212111212` |
| 3 | square, triangle with its apex on the square's top edge | **false** | true | true | `FF2F01212` |
| 4 | MultiPolygon whose 2nd part shares an edge with b | **false** | **false** | true | `FF2F11212` |
| 5 | b inside a's hole, sharing an edge with it | **false** | **false** | true | `FF2F11212` |

The expected values can be checked by hand:

- **Case 1.** The two triangles are the same set, so every interior point of one is an interior point of the other.
- **Case 2.** Both squares contain [1,2]x[0,2] (area 2), so their interiors meet.
- **Case 3.** The triangle lies in y ≥ 2 and the square in y ≤ 2. They share only the point (1,2), which is on both boundaries.
- **Case 4.** The squares [0,1]x[0,1] and [1,2]x[0,1] share only the edge x = 1. The other part of the MultiPolygon is far away.
- **Case 5.** b = [1,2]x[1,2] lies in the hole [1,3]x[1,3]. It meets a only on the hole's boundary.

Turf's own functions agree with the expected values. `booleanIntersects` is true in all five cases. `intersect` (polyclip-ts) returns a polygon with area for cases 1 and 2, and `null` for cases 3 to 5. JSTS 2.12.1 `touches` gives false, false, true, true, true in both argument orders.

## Versions

| version | result |
|---|---|
| `@turf/turf` 7.4.0 (npm `latest`, tag v7.4.0 = 22acbd80) | cases 1-5 wrong |
| `master` bec3ac7860d5d71a31bd9dbc44dd1ac5fab0c0b7 (2026-09-07, still the head on 2026-09-26) | cases 1-5 wrong (`packages/turf-boolean-touches/index.ts` is unchanged since v7.4.0) |
| `@turf/turf` 7.0.0 | cases 1-5 wrong |
| `@turf/boolean-touches` 6.5.0 | cases 1-5 wrong |

Node v22.22.2.

## Analysis

All line numbers refer to `packages/turf-boolean-touches/index.ts` at bec3ac7. They are the same in v7.4.0.

- **Polygon / Polygon ([L560-L581](https://github.com/Turfjs/turf/blob/bec3ac7860d5d71a31bd9dbc44dd1ac5fab0c0b7/packages/turf-boolean-touches/index.ts#L560-L581)).** The loop runs over `geom1.coordinates[0]` only, the outer ring of `a`. A touching point is found when a vertex of `a` lies on `geom2.coordinates[0]` (L567). The only interior test asks whether a vertex of `a` is strictly inside `b` (L572-L579).
  - **Cases 1 and 2.** The interiors of two polygons can meet without any vertex of `a` lying strictly inside `b`. With identical polygons, every vertex is on the boundary. With overlapping polygons, the overlap can come only from edges crossing.
  - **Case 3.** Contact made by a vertex of `b` is never examined.
  - **Case 5.** A hole of `b` (L567) or of `a` (L562) is never examined.
- **MultiPolygon / Polygon ([L703-L726](https://github.com/Turfjs/turf/blob/bec3ac7860d5d71a31bd9dbc44dd1ac5fab0c0b7/packages/turf-boolean-touches/index.ts#L703-L726)).** Only `geom1.coordinates[0]`, the first polygon, is examined (case 4).
- **Polygon / MultiPolygon ([L582-L605](https://github.com/Turfjs/turf/blob/bec3ac7860d5d71a31bd9dbc44dd1ac5fab0c0b7/packages/turf-boolean-touches/index.ts#L582-L605)).** Only `b`'s first polygon is examined. L598 also passes a single ring (`geom2.coordinates[0][i]`) as the `coordinates` of a Polygon.
- **MultiPolygon / MultiPolygon ([L727-L761](https://github.com/Turfjs/turf/blob/bec3ac7860d5d71a31bd9dbc44dd1ac5fab0c0b7/packages/turf-boolean-touches/index.ts#L727-L761)).** Only the first polygon of each operand is examined. The vertex loop at L731 is bounded by `geom1.coordinates[0].length`, which is the number of *rings*. For a polygon without holes, only its first vertex is tested. For example, with the adjacent unit squares [0,1]x[0,1] and [1,2]x[0,1] each wrapped in a one-part MultiPolygon, `booleanTouches(a, b)` is false and `booleanTouches(b, a)` is true (both should be true, DE-9IM `FF2F11212`).

The existing Polygon/Polygon fixtures always pass the small square as `feature1`, and none has a shared interior without a vertex of `feature1` strictly inside `feature2`. That is why the tests pass. Cases 1-5 above, in both argument orders, would make good fixtures.

For two areal geometries, `touches(a, b)` is `intersects(a, b)` and "the interiors do not meet". A symmetric implementation needs two things:

1. Test the vertices of both geometries, on all rings of all polygons.
2. Detect interior overlap that involves no vertex. One way is to split each edge at the other geometry's boundary and classify the midpoint of each piece, as `isPolyInPoly` in `@turf/boolean-contains` already does with `lineSplit`. A piece that lies on both boundaries also needs a same-side test for the two interiors, which is what decides case 1.

To see how often this happens beyond hand-made cases: in an exact-arithmetic test corpus, 70 of 207 valid Polygon/MultiPolygon pairs with small integer coordinates (all float arithmetic exact) get the wrong `booleanTouches` result. 60 of them are false positives.

## Related issues

- #3088 (open PR) fixes an index bug in the LineString / MultiLineString branch of the same function. It does not touch the polygon branches.
- #2454 (open): `booleanOverlap` returns true for adjoining polygons. That is a different function, and it has the mirror-image problem: an edge contact counts as an overlap.
- #1882 (open): `booleanContains` ignores holes. Different function, related to case 5.
- #3025 / #3024: `booleanContains` was aligned with DE-9IM for MultiPoints. It is the same kind of correction, for a different function.
- #2398 / #2431: `booleanTouches` documentation.

I searched the open and closed issues, PRs and discussions (last on 2026-09-26) for "booleanTouches", "boolean-touches", "touches" and "touch polygon", plus several paraphrased searches (identical or overlapping polygons, argument order, MultiPolygon parts, holes). I found no report of the polygon behaviour above. #1960, #2427 and #1781 ask how to detect adjacent polygons and report no wrong `booleanTouches` result. The 2026 PRs for the other boolean predicates (#3079, #3085, #3091, #3097, #3104) do not modify `@turf/boolean-touches`. Neither does the open perf PR #3164, which only avoids copies in `booleanPointInPolygon` / `booleanPointOnLine`.

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
