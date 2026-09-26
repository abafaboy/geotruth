# RelateNG: boundary entries lost when later elements are skipped as "known exterior" (port JTS #1200, and the same flaw in computeAreaVertex)

## Summary

`RelateNG::computeLineEnds` has an optimisation: once one line end has been found in the exterior of the other geometry, later line elements whose envelope is disjoint from the other geometry are skipped. The first exterior line end can be a Mod-2 *interior* point, for example the start of a closed line, or an end shared by two elements. In that case no Boundary/Exterior entry has been recorded yet. The skipped elements' boundary points are then never recorded, so `relate` returns `EB` (or `BE`) = `F` instead of `0`, and the matrix depends on the order of the elements.

JTS reported this as locationtech/jts#1175 and fixed it in locationtech/jts#1200 (commit e8de44d9, June 2026). NetTopologySuite has ported the fix. GEOS `main` still has the old code.

`RelateNG::computeAreaVertex` uses the same skip for polygons, and JTS #1200 did not change it. For a GeometryCollection, the ring vertex that is tested can lie inside another polygon of the collection. It is then an *interior* point of the collection, and it records only Interior/Exterior. The polygons after it are skipped, so `BE` (or `EB`) stays `F` instead of `1`. JTS master has the same code.

Only the DE-9IM matrix is affected: `GEOSRelate`, `GEOSPreparedRelate` and `GEOSRelatePattern` with a pattern that constrains these cells. The named predicates are not affected. The same first exterior point always records an Interior/Exterior entry that already decides them.

## Minimal reproduction

All inputs are valid (`GEOSisValid` = 1). Coordinates are small integers.

```
$ geosop -a 'POINT (10 10)' -b 'MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))' relate
FF0FFF1F2        # expected FF0FFF102
$ geosop -a 'POINT (10 10)' -b 'MULTILINESTRING ((5 5, 6 6), (0 0, 1 0, 1 1, 0 0))' relate
FF0FFF102        # same geometry, elements swapped: correct
$ geosop -a 'GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))' -b 'LINESTRING (10 10, 11 11)' relate
FF2FFF102        # expected FF2FF1102
$ geosop -a 'GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))' -b 'LINESTRING (10 10, 11 11)' relate
FF2FF1102        # polygons swapped: correct
```

The expected values can be checked by hand:

- **Case 1.** B's first element is a closed line, so under the Mod-2 rule it contributes no boundary. The second element's ends (5 5) and (6 6) are B's whole boundary. GEOS agrees: `GEOSBoundary(B)` is `MULTIPOINT ((5 5), (6 6))`, and `relate(POINT (5 5), B)` is `F0FFFF102`. Both points are far from A = (10 10). So Exterior(A) ∩ Boundary(B) is non-empty and has dimension 0, which means EB = 0.
- **Case 4.** A is the union of two overlapping squares. Its boundary, the outline of that union, lies far from B, so BE = 1.

`repro.c` uses only the C API (build with `cc repro.c $(geos-config --cflags) $(geos-config --clibs)`). Its output on `main`:

| case | A | B | expected | `main` |
|---|---|---|---|---|
| 1 | `POINT (10 10)` | `MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))` | `FF0FFF102` | `FF0FFF1F2` |
| 1, operands swapped | the MultiLineString | the point | `FF1FF00F2` | `FF1FFF0F2` |
| 1, `GEOSRelatePattern(A, B, "FF*FF**0*")` | | | 1 | 0 |
| 2 | `POLYGON ((1 2, 4 0, 1 0, 1 2))` | `MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))` | `1F2001102` | `1F20011F2` |
| 3 (the JTS #1175 test) | `LINESTRING (10 10, 20 20)` | `MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (-1 0, 0 0))` | `FF1FF0102` | `FF1FF01F2` |
| 4 | `GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))` | `LINESTRING (10 10, 11 11)` | `FF2FF1102` | `FF2FFF102` |
| 4, operands swapped | the line | the GC | `FF1FF0212` | `FF1FF02F2` |

In case 2, (2 3) ends both elements, so it is a Mod-2 interior point. It is the first line end found outside A. The element (2 3)-(4 3) is then skipped, and its boundary end (4 3) is lost.

`GEOSPreparedRelate` gives the same wrong matrices. With the elements, or the polygons, in the other order, every case is correct.

## Versions

| GEOS | result |
|---|---|
| `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (2026-09-21, still the head on 2026-09-26) | wrong (cases 1-4) |
| 3.15.0 (d0228513); `src/operation/relateng` is identical to `main` | wrong |
| 3.14.1 (Shapely 2.2.0rc1 wheel), 3.13.1 (Shapely 2.1.2 wheel) | wrong |
| 3.13.0 (d7957246, built from source): the first release with RelateNG | wrong |
| 3.11.4 (Shapely 2.0.7 wheel, RelateOp) | correct |
| `main` + the patch below | correct |

JTS: 1.20.0 is wrong on cases 1-4. JTS master 3ea61f8 is correct on cases 1-3 (#1200) and wrong on case 4.

Platform: Linux x86-64, gcc 13.3, Release builds.

## Analysis

Line numbers are for `main` ae9cdd9.

**Line ends.** In `RelateNG::computeLineEnds` (src/operation/relateng/RelateNG.cpp:514-555), one flag `hasExteriorIntersection` gates the skip at lines 531-534. `computeLineEnd` (560-574) returns true for *any* line end in the target's exterior, whatever the end's own location. `TopologyComputer::addLineEndOnGeometry` (TopologyComputer.cpp:346) records the entry for that end's location only: I/E for a Mod-2 interior end, B/E for a boundary end. Later envelope-disjoint elements are skipped, and those can have boundary ends in the exterior. JTS #1200 keeps two flags, one for an interior end found in the exterior and one for a boundary end. It skips only when both have been seen, and `computeLineEnd` returns the end's location instead of a bool.

**Area vertices.** `RelateNG::computeAreaVertex` (RelateNG.cpp:578-613) has the same pattern at lines 596-598. `computeAreaVertex(ring)` (619-630) tests the ring's first vertex, which the TODO at line 621 already notes: *"use extremal (highest) point to ensure one is on boundary of polygon cluster"*. `TopologyComputer::addAreaVertex` (TopologyComputer.cpp:413-430) records B/E only when that vertex is on the boundary (lines 425-428). For a GC whose first-tested vertex lies inside another polygon, it records only I/E. The skip then drops the polygons that carry the boundary. A vertex that is on the boundary records every entry that a known-exterior polygon could add (I/E, B/E, E/E). So it is enough to skip only after such a vertex.

**Why the named predicates are unaffected.** The first exterior line end always records Interior(line) ∩ Exterior = 1 when the target is a line or an area (`addLineEndOnLine`/`addLineEndOnArea`, TopologyComputer.cpp:374, 392). For a point target, `initExteriorDims` sets that entry. The first exterior area vertex always records Interior ∩ Exterior = 2. `contains`, `covers`, `within`, `coveredBy` and `equals` are all already false from those entries. The other predicates do not read EB/BE.

## Proposed fix

There are two patches against `main`: `patch/port-jts-1200.diff`, a direct port of JTS #1200, and `patch/area-vertex-skip.diff`, which tracks a Boundary/Exterior vertex for the area case. Together they are about 40 lines. I tested them with the cases above and with three random sweeps of 3000 cases each, compared against exact answers (details under "Testing"). With the patches every line-end and area-vertex disagreement is gone, and nothing else changes. GEOS's XML tests (`ctest -R '^xml-'`, 171 tests) and the RelateNG unit tests (`tests/unit/operation/relateng`, 155 tests) pass. I did not run the rest of the unit suite.

```cpp
// computeLineEnds (port of JTS #1200)
bool hasInteriorExteriorIntersection = false;
bool hasBoundaryExteriorIntersection = false;
...
if (hasInteriorExteriorIntersection && hasBoundaryExteriorIntersection
    && elem->getEnvelopeInternal()->disjoint(geomTarget.getEnvelope()))
    continue;
Location loc0 = computeLineEnd(geom, isA, &e0, geomTarget, topoComputer);   // now returns the end's
if (loc0 == Location::INTERIOR) hasInteriorExteriorIntersection = true;      // location if it is in the
else if (loc0 == Location::BOUNDARY) hasBoundaryExteriorIntersection = true; // target exterior, else NONE

// computeAreaVertex
if (hasBoundaryExteriorIntersection && elem->getEnvelopeInternal()->disjoint(geomTarget.getEnvelope()))
    continue;
if (computeAreaVertex(geom, isA, ring, geomTarget, topoComputer) == Location::BOUNDARY)
    hasBoundaryExteriorIntersection = true;
```

A regression test could be the JTS test `testLineDisjointMultiLineWithBoundaryInExterior_JTS1175`, which checks `FF1FF0102` in both argument orders, together with case 1 and case 4 above.

## Testing

The random sweeps compare GEOS with exact answers computed in rational arithmetic, 3000 cases each. The counts are disagreements of these two kinds (lost line ends, lost area-vertex boundary):

- MultiLineStrings with far-away elements (`sweep-1`): 279 on `main` and on 3.13.0, 0 with the patch.
- Polygons against lines (`ring-2`): 9 on `main`, 0 with the patch.
- GeometryCollections of polygons (`gc-3`): 65 on `main` and on 3.13.0, 0 with the patch.

The only disagreements left on patched `main` belong to other known classes:

- A crossing point that is not representable as a double (sweep-1).
- A separate RelateNG self-noding regression in 3.13.1 (ring-2 and gc-3), which I am reporting separately.

## Related issues

- locationtech/jts#1175 (closed): the same defect in JTS, fixed by locationtech/jts#1200 (e8de44d9). JTS 1.20.0 is still affected. Its test case is case 3 here.
- NetTopologySuite ported the fix (NTS #869, pinned by NTS #886).
- I found no GEOS issue or PR that ports JTS #1200. I searched libgeos/geos issues and PRs, open and closed, for: computeLineEnds, RelateNG boundary, line end, EB/exterior boundary, "port JTS" RelateNG. I also checked the relateng history on `main`, `3.15` and `3.14`, and every PR branch (open and closed) from #1200 onward.
- I found no report of the computeAreaVertex variant in either tracker.

---

Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
