# RelateNG: wrong predicates when a ring vertex touches the interior of another ring's edge (a MultiPolygon does not contain its own element)

*Draft for libgeos/geos. The same code in JTS RelateNG gives the same results; see "JTS" below.*

## Summary

Since GEOS 3.13, predicates and `relate` go through RelateNG, and RelateNG returns wrong results for some **valid** polygonal inputs. The trigger is a vertex of one ring that lies in the *interior of an edge* of another ring of the same geometry. That happens when two MultiPolygon elements touch vertex-to-edge, or when a hole touches its shell at a hole vertex. The result is wrong when the other operand's boundary runs along that edge, through the touch point.

The simplest symptom: a MultiPolygon does not `contain` or `cover` one of its own elements, and `overlaps` returns true instead. GEOS 3.11.4 (old RelateOp) returns the correct answers for all three cases below.

## Minimal reproduction

```
# case 1: the triangle's vertex (1 2) is the midpoint of the square's top edge
$ geosop -a 'MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))' \
         -b 'POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))' relate
2F2F11212          # expected 2F2F11FF2
  contains -> false (expected true), covers -> false (expected true), overlaps -> true (expected false)

# case 3: the hole's vertex (2 0) is the midpoint of the shell's bottom edge; B is the adjacent rectangle below
$ geosop -a 'POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))' \
         -b 'POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))' relate
212F11212          # expected FF2F11212
  touches -> false (expected true), overlaps -> true (expected false)
```

All inputs are valid: `GEOSisValid` returns true, and an exact rational validity check agrees. OGC SFS allows elements of a MultiPolygon to touch at finitely many points, and allows a hole to touch its shell at one point. The touch point does not have to be a vertex of both rings.

A C program that uses only the public C API is attached (`repro.c`, build with `cc repro.c $(geos-config --cflags) $(geos-config --clibs)`). It runs three cases:

| case | A | B | expected `relate(A,B)` | GEOS 3.13.1 / 3.14.1 / 3.15.0 / main | GEOS 3.11.4 |
|---|---|---|---|---|---|
| 1 | `MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))` | `POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))` (A's first element) | `2F2F11FF2`: contains, covers | `2F2F11212`: overlaps, not contains or covers | correct |
| 2 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))` | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `212F1FFF2`: contains, covers | `21211F2F2`: overlaps, not contains or covers | correct |
| 3 | `POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))` | `POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))` | `FF2F11212`: touches | `212F11212`: overlaps, not touches | correct |

The expected answers are easy to check by hand:
1. B is literally A's first element, so A contains B.
2. B is A with a triangular hole removed, so B ⊂ A.
3. The interiors are disjoint: B lies below y = 0 and A lies above it. They share the segment y = 0, so they touch.

GEOS's own overlay agrees with the expected answers. `area(B − A)` is 0 in cases 1 and 2, and `area(A ∩ B)` is 0 in case 3. So `relate` is also inconsistent with overlay.

`GEOSPreparedContains_r` is also wrong in case 1 (false). From reading the code, `PreparedPolygonContains::fullTopologicalPredicate` delegates to `Geometry::contains`, which is RelateNG, but I have not traced which branch runs here. In case 2 the prepared call returns true only because of the rectangle short-cut in `PreparedPolygon::contains`.

## Versions

- GEOS `main` at ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (3.16.0dev, 2026-09-21): wrong
- GEOS 3.15.0 (tag, d0228513), built from source: wrong. `src/operation/relateng` is identical to main.
- GEOS 3.14.1 (Shapely 2.2.0rc1 wheel) and 3.13.1 (Shapely 2.1.2 wheel): wrong
- GEOS 3.11.4 (Shapely 2.0.7 wheel, pre-RelateNG): correct
- Linux x86-64, gcc 13.3, Release build

## Analysis

As far as I can tell, the cause is that RelateNG skips self-noding for polygonal inputs:

- `RelateGeometry::isSelfNodingRequired()` (src/operation/relateng/RelateGeometry.cpp:239-253) returns false for `GEOS_POLYGON` and `GEOS_MULTIPOLYGON`, and for a GC holding one polygon. JTS documents the assumption in the same method: *"Self-noding is not required for polygonal geometries, since they can only touch at vertices."*
- So `RelateNG::computeAtEdges` (RelateNG.cpp:645-649) uses `computeEdgesMutual`, which intersects only A-segments with B-segments. A `NodeSection` is created only for a ring that has an A×B segment intersection at that point (EdgeSegmentIntersector.cpp:97-103).

In case 1 the node at T = (1 2) is created by the triangle's two edges meeting B's top edge. The square's top edge and B's top edge are collinear. The collinear intersection reports only the overlap endpoints (0 2) and (2 2), so T is never reported. The node at T therefore has a section for A's triangle but **no section for A's square**, even though the square's edge passes through T.

`RelateNode::finishNode` / `propagateSideLocations` (RelateNode.cpp:235, 242) then fills in A's side locations from the triangle alone. The edges along y = 2 and the half-plane below them are marked EXTERIOR of A. `TopologyComputer::evaluateNodeEdges` (TopologyComputer.cpp:562-575) then records Exterior(A)∩Interior(B) = 2 and Exterior(A)∩Boundary(B) = 1. These are exactly the wrong cells in `2F2F11212`. Cases 2 and 3 fail the same way: the hole has a section at T and the shell does not.

The pattern also fits the fuzz corpus this was found in. The corpus has 92 cases where A is a MultiPolygon with two elements touching vertex-to-edge and B is one of those elements:
- B = the element whose **edge** passes through T: all 50 cases wrong in GEOS 3.13.1.
- B = the element whose **vertex** is at T: all 42 cases correct in GEOS 3.13.1. B's own edges then create a node section for the other element at T.

Two checks support this diagnosis:
- **Forcing self-noding through the public API.** Wrapping the polygonal operand in a GeometryCollection makes `isSelfNodingRequired()` true: `GEOMETRYCOLLECTION(POLYGON(..), POLYGON(..))` for case 1, and `GEOMETRYCOLLECTION(<polygon>, POINT (3 3))` with an interior point for cases 2 and 3. All three cases then give the expected matrices (GEOS 3.13.1 and 3.14.1; see `check_selfnoding_gc.py`).
- **Patching JTS.** In JTS master, making `RelateGeometry.isSelfNodingRequired()` return true for Polygon/MultiPolygon also fixes all three cases. This was an experiment, not a proposed patch, since self-noding every polygon would cost performance. Details are in `output/experiment-force-self-noding.diff` and `output/jts-master-experiment-force-self-noding.txt`.

A cheaper fix might add the missing sections only where they are needed. For a polygonal geometry with more than one ring, a node could be checked against the other rings' edges that pass through the node point. I have not tried this.

## JTS

JTS RelateNG has the same code and gives the same matrices. I tested JTS master 3ea61f8 (1.21.0-SNAPSHOT) and JTS 1.20.0 with `RelateNG.relate(a, b)` and `RelateNG.relate(a, b, RelatePredicate.contains()/touches()/overlaps())`, and with `-Djts.relate=ng`. The default `RelateOp` path (`Geometry.relate`) is correct. `Repro.java` is attached.

In case 2, JTS `Geometry.contains()` returns true only because of its rectangle short-cut. `covers()` and `relate()` are wrong there.

## Related issues checked

I found no duplicates. I searched libgeos/geos and locationtech/jts issues and PRs, open and closed, for: RelateNG, contains multipolygon, touches hole, self-noding, and vertex on edge. The closest ones are different problems:

- https://github.com/libgeos/geos/issues/1147 (RelateNG DE9IM regression): its MultiPolygon elements share an edge segment, so the input is invalid. The inputs here are valid.
- https://github.com/libgeos/geos/issues/1253: a TopologyException in the old RelateOp.
- https://github.com/libgeos/geos/issues/1027: covers with a MultiPolygon in the old RelateOp, with a GC argument.
- https://github.com/locationtech/jts/issues/1064 (Error in RelateGeometry?): a typo report in the same class, closed for 1.20.0.

---

Found by differential testing against an exact rational-arithmetic oracle. A second, independent exact implementation agrees with it, and both give the expected predicates above.

<!-- local files (not part of the issue text):
  repro.c, repro_shapely.py, Repro.java, check_selfnoding_gc.py, run.sh   repros (public API only)
  cases.jsonl, original_case.jsonl                                       inputs in the hunt's JSON format
  output/*                                                               captured runs (GEOS 3.15.0, main, 3.14.1, 3.13.1, 3.11.4,
                                                                         JTS master and 1.20.0, oracle, indep, geosop, JTS experiment)
-->

