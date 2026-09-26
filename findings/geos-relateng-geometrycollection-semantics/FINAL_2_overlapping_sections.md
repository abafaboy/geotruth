# RelateNG: an interior point of a GeometryCollection of overlapping polygons is located on the boundary (contains() false, touches() true)

## Summary

Take a GeometryCollection whose polygons *overlap*, and a point where two or more polygon
boundaries meet while the union covers the whole neighbourhood. A typical example is a reflex
vertex of one polygon lying on an edge of another polygon that covers the notch.

RelateNG locates such a point as BOUNDARY instead of INTERIOR. So:

- `contains(GC, point)` is false;
- `touches` is true;
- a line through the point into the notch is reported as leaving the collection, so `contains` is
  false and `crosses` is true.

Adjacent (non-overlapping) polygons are handled correctly. The defect is in how
`RelateNode::addEdges` merges overlapping area sections. That code serves `AdjacentEdgeLocator`
(point location in a GC) and the node evaluation.

## Minimal reproduction (geosop, GEOS main)

A is an "arrowhead" with a reflex vertex at (2 1), plus a rectangle whose top edge passes through
(2 1) and which covers the arrowhead's notch:

```
$ A="GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))"
$ geosop -a "$A" -b "POINT (2 1)" relate
FF20F1FF2                    # expected 0F2FF1FF2
$ geosop -a "$A" -b "POINT (2 1)" contains
false                        # expected true
$ geosop -a "$A" -b "POINT (2 1)" touches
true                         # expected false
$ geosop -a "$A" -b "LINESTRING (2 2, 2 0)" contains
false                        # expected true (relate 1020011F2, expected 102F01FF2)
$ geosop -a "$A" unaryUnion
POLYGON ((3 0.5, 3 0, 1 0, 1 0.5, 0 0, 2 3, 4 0, 3 0.5))
$ geosop -a "POLYGON ((3 0.5, 3 0, 1 0, 1 0.5, 0 0, 2 3, 4 0, 3 0.5))" -b "POINT (2 1)" relate
0F2FF1FF2                    # GEOS on its own union: correct
```

- The result is the same with the two elements swapped.
- It is the same through the C API, prepared geometries and Shapely.
- Control: filling the notch exactly with the adjacent triangle `POLYGON ((0 0, 2 1, 4 0, 0 0))`
  (no overlap) gives the correct `0F2FF1FF2`.
- Another case, found by our fuzzer:
  `GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 1, 3 4, -1 4, 0 1, 1 2)))`
  vs `POINT (1 2)`. The expected matrix is `0F2FF1FF2`; GEOS gives `FF20F1FF2`.

## Expected vs actual

Around (2 1):

- The arrowhead covers every direction except the downward wedge between the directions to (0 0)
  and (4 0).
- The rectangle covers the whole lower half-disc, which contains that wedge.
- The union therefore covers a neighbourhood of (2 1), and under the documented union semantics
  (2 1) is an interior point. `relate(A, POINT (2 1))` must be `0F2FF1FF2`.

GEOS returns `FF20F1FF2` (the point is on A's boundary). Its own `unaryUnion` of A gives the
right answer. An exact rational engine (two independent routes) agrees with the hand derivation.
Exact probing confirms it: none of 124 points at distance 1e-6 around (2 1) lies outside both
polygons.

## Versions

- GEOS `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 and 3.15.0 (d0228513a): wrong.
- 3.14.1, 3.13.1 and 3.13.0 (d7957246): wrong, the same matrices. The bug has been present since
  RelateNG was introduced.
- 3.11.4: RelateOp throws a TopologyException, because overlapping GCs were unsupported before
  RelateNG.
- JTS master 3ea61f8 and 1.20.0 (`RelateNG`): identical.

## Analysis

A point on the boundaries of two or more polygons of a GC is located by `AdjacentEdgeLocator`
(RelatePointLocator.cpp:287-291). The locator builds a `RelateNode` from a `NodeSection` for every
ring through the point, and answers BOUNDARY if any edge has an EXTERIOR side
(AdjacentEdgeLocator.cpp:47-57).

`RelateNode::addEdges(const NodeSection*)` (RelateNode.cpp:92-111) adds an area section in this
order:

```cpp
        const RelateEdge* e0 = addAreaEdge(ns->isA(), ns->getVertex(0), false);
        const RelateEdge* e1 = addAreaEdge(ns->isA(), ns->getVertex(1), true);
        std::size_t index0 = indexOf(edges, e0);
        std::size_t index1 = indexOf(edges, e1);
        updateEdgesInArea(ns->isA(), index0, index1);
        updateIfAreaPrev(ns->isA(), index0);
        updateIfAreaNext(ns->isA(), index1);
```

`updateIfAreaPrev` and `updateIfAreaNext` are meant to mark a new edge as interior on both sides
when it falls into a sector that an earlier section already made interior. But they run after
*both* edges are inserted. By then the neighbour they inspect is usually the section's own other
edge, whose side toward the section's exterior is EXTERIOR.

Take the arrowhead added after the rectangle:

1. The rectangle's edges point W and E, and the sector below them is interior.
2. The arrowhead's edges at 206.6 and 333.4 degrees fall into that interior sector.
3. The notch between them keeps EXTERIOR on both edges.

Added in the other order, the arrowhead's interior (everything but the notch) contains the
rectangle's W and E edges, whose north sides keep EXTERIOR.

Adjacent sections, whose sectors do not overlap, are resolved by `RelateEdge::merge` on the shared
edges. That is why tiled collections and valid (Multi)Polygons are unaffected.

A second detail shows up once the ordering is fixed. `AdjacentEdgeLocator::createSection`
(line 97) gives every ring's section id 1 and ring 0. Every ring is then treated as a shell of one
polygon, and a hole's section claims the whole outside of the hole. The id is only harmless
because of the ordering defect.

`TopologyComputer::evaluateNode` (TopologyComputer.cpp:548-557) adds node sections from different
GC polygons in the same way. It decides whether the node is inside the area through
`isNodeInArea`, which calls the same locator. So edges through such a node are mislabelled too:
`LINESTRING (2 2, 2 0)` above gets EI = 1.

## Suggested fix

Tested prototype: `prototype_fix_2.diff` (RelateNode.cpp, AdjacentEdgeLocator.h/.cpp).

1. In `RelateNode::addEdges`, check the sector each edge was inserted into right after inserting
   it, before the other edge exists. In `updateIfAreaPrev` / `updateIfAreaNext`, never compare an
   edge with itself.

   ```diff
            const RelateEdge* e0 = addAreaEdge(ns->isA(), ns->getVertex(0), false);
   +        //-- check the sector e0 was inserted into, before e1 is added
   +        if (e0 != nullptr)
   +            updateIfAreaPrev(ns->isA(), indexOf(edges, e0));
            const RelateEdge* e1 = addAreaEdge(ns->isA(), ns->getVertex(1), true);
   +        if (e1 != nullptr)
   +            updateIfAreaNext(ns->isA(), indexOf(edges, e1));
            std::size_t index0 = indexOf(edges, e0);
            std::size_t index1 = indexOf(edges, e1);
            updateEdgesInArea(ns->isA(), index0, index1);
   -        updateIfAreaPrev(ns->isA(), index0);
   -        updateIfAreaNext(ns->isA(), index1);
   ```

2. Give each `AdjacentEdgeLocator` ring its polygon index and ring index (0 for the shell), and
   pass them to the `NodeSection`. The rings of one polygon then go through `PolygonNodeConverter`
   as designed, and different polygons are added separately.

Test results:

- **GEOS test suite.** `ctest` passes 535/535 with this patch, including `AdjacentEdgeLocatorTest`
  with its filled-hole cases.
- **Differential run.** Over 33,719 generated relate cases it corrects 260 answers.
- **Dependency.** On its own it turns 10 correct answers wrong. In those GCs the first ring vertex
  is exactly such a covered reflex vertex. The old, wrong BOUNDARY answer happened to record B/E
  for that ring. The correct INTERIOR answer exposes two other defects that lose B/E:
  - the area-vertex skip in `computeAreaVertex` (reported separately);
  - the "first ring vertex inside the union" problem (reported separately).

  With those fixed as well, nothing regresses, so this change should land together with them.

## Related issues

- `AdjacentEdgeLocatorTest` and `TestRelateGC.xml` ("point on common node of 3/6 adjacent
  polygons") cover adjacent polygons only.
- No report of this behaviour was found (libgeos/geos and locationtech/jts issues and PRs, open
  and closed).
- The empty-polygon crash in `AdjacentEdgeLocator::addSections` is a separate report, but it is
  in the same function. Its fix skips empty polygons in `addRings` and needs a trivial rebase
  against this one.

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
