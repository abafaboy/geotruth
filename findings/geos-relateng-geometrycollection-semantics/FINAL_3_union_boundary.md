# RelateNG: a GeometryCollection of overlapping polygons forming a frame "equals" the full square (union boundary not evaluated)

## Summary

In a GeometryCollection of overlapping polygons, parts of the union's boundary are never evaluated
unless the other geometry's edges cross them. Two forms occur:

- a union boundary that belongs to no input ring, such as a hole enclosed by several overlapping
  polygons;
- rings whose first vertex lies inside the union.

Four overlapping strips forming a 3x3 frame with a 1x1 hole are reported `equals`, `contains` and
`covers` the full 3x3 square. GEOS's own point locator says the square's centre is outside the
frame, and GEOS's own `unaryUnion` gives the correct relation.

## Minimal reproduction (geosop, GEOS main)

```
$ A="GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 0 1, 0 0)), POLYGON ((0 2, 3 2, 3 3, 0 3, 0 2)), POLYGON ((0 0, 1 0, 1 3, 0 3, 0 0)), POLYGON ((2 0, 3 0, 3 3, 2 3, 2 0)))"
$ B="POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))"
$ geosop -a "$A" -b "$B" relate
2FFF1FFF2                    # expected 2FF11F2F2
$ geosop -a "$A" -b "$B" equals
true                         # expected false
$ geosop -a "$A" -b "$B" contains
true                         # expected false
$ geosop -a "$A" -b "POINT (1.5 1.5)" intersects
false                        # GEOS's own point location: the centre is not in A
$ geosop -a "$A" unaryUnion
POLYGON ((1 0, 0 0, 0 1, 0 2, 0 3, 1 3, 2 3, 3 3, 3 2, 3 1, 3 0, 2 0, 1 0), (1 2, 1 1, 2 1, 2 2, 1 2))
$ geosop -a "<that polygon>" -b "$B" relate
2FF11F2F2                    # correct
```

- `relate(B, A)` gives `212F11FF2` on 3.13.1 and later, and `2FFF1FFF2` on 3.13.0. The expected
  matrix is `212F1FFF2`.
- Two overlapping L-shapes give the same wrong answers:
  `GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 1, 1 1, 1 3, 0 3, 0 0)), POLYGON ((3 3, 0 3, 0 2, 2 2, 2 0, 3 0, 3 3)))`.
- The same frame as a single `POLYGON` with a hole is handled correctly.

The second form involves no hole. A notched square has its notch filled by a triangle, and both
rings start at the notch vertex (1 1), which is interior to the union. Against a disjoint line,
the boundary/exterior entry is lost:

```
A = GEOMETRYCOLLECTION (POLYGON ((1 1, 0 0, 2 0, 1 1)), POLYGON ((1 1, 2 0, 2 2, 0 2, 0 0, 1 1)))
B = LINESTRING (5 5, 6 6)
GEOS relate(A,B) = FF2FFF102    expected FF2FF1102
```

## Expected vs actual

The union of the four strips is `[0,3]^2` minus the open square `(1,2)^2`.

- The hole's boundary lies in B's interior, so BI = 1.
- The hole lies in B's interior and outside A, so EI = 2.
- A is `within` B, but it is neither `equals` nor `contains`.

Two audited exact polygon references compute the same relation for (the union, B), with areas 8
and 9. So does an exact rational engine run on the GeometryCollection itself (two independent
routes).

## Versions

- GEOS `main` ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 and 3.15.0 (d0228513a): wrong.
- 3.14.1, 3.13.1 and 3.13.0 (d7957246): wrong.
- 3.11.4: RelateOp throws a TopologyException.
- JTS master 3ea61f8 and 1.20.0 (`RelateNG`): identical.

## Analysis

Away from the other geometry's edges, RelateNG learns about an areal geometry from one vertex per
ring. `RelateNG::computeAreaVertex(ring)` (src/operation/relateng/RelateNG.cpp:619-630) tests
`ring->getCoordinate()` only, and its TODO says so:

```cpp
    //TODO: use extremal (highest) point to ensure one is on boundary of polygon cluster
    const CoordinateXY* pt = ring->getCoordinate();
```

For a Polygon or MultiPolygon this is enough, because every ring is boundary. For overlapping
polygons of a GeometryCollection the union's boundary is made of *pieces* of several rings, joined
where rings of the same collection cross. This causes two failures:

1. **The ring's first vertex is interior to the union.** `addAreaVertex` then records only I/E
   (TopologyComputer.cpp:413-430) and nothing about the ring's boundary pieces.
2. **A union boundary component contains no ring vertex at all**, like the frame's hole, whose
   corners are T-crossings of the strips. Its only special points are the crossings between the
   collection's own polygons. Those crossings are computed: the collection is self-noded, and
   `TopologyComputer::addIntersection` (233-245) stores their node sections. But `evaluateNodes`
   (533-543) evaluates only nodes with `hasInteractionAB()`, so they are discarded.

## Suggested fix

Tested prototype: `prototype_fix_3.diff`. It touches RelateNG.cpp, TopologyComputer.h/.cpp,
NodeSections.h/.cpp, and RelateNode.h (`finishNode` made public).

1. In `computeAreaVertex(ring)`, if the first vertex is INTERIOR (possible only in a GC), use the
   first ring vertex that is on the union boundary, if any:

   ```cpp
       if (locArea == Location::INTERIOR) {
           const CoordinateSequence* seq = ring->getCoordinatesRO();
           for (std::size_t i = 1; i + 1 < seq->size(); i++) {
               const CoordinateXY* pi = &seq->getAt<CoordinateXY>(i);
               if (geom.locateAreaVertex(pi) == Location::BOUNDARY) {
                   pt = pi; locArea = Location::BOUNDARY; break;
               }
           }
       }
   ```
2. In `evaluateNodes`, also evaluate a node whose sections are all area sections of one geometry,
   from at least two of its elements. At such a node the other geometry has no edge, so its
   location there, whether INTERIOR of an area or EXTERIOR, is constant around the node. Finish
   the node for the collection (`isNodeInArea` + `finishNode`) and record, for each edge,
   `(LEFT/RIGHT location, other location)` as dimension 2 and `(ON location, other location)` as
   dimension 1 (`TopologyComputer::evaluateCollectionNode` in the prototype).

Test results:

- **GEOS test suite.** `ctest` passes 535/535 with this patch.
- **Differential run.** Over 33,719 generated relate cases it corrects 32 answers of this class
  (plus 19 cases of the area-vertex skip reported separately), and changes no correct answer.
- **Operand order.** `relate(B, A)`, with the collection as the *second* argument, stays wrong.
  Since #1201 (3.13.1) a collection B is not self-noded when A is polygonal, so the crossings are
  never computed. That self-noding change is reported separately. With it reverted, both orders
  are exact.
- **Cost.** On a GC of 400 overlapping circles the prototype's extra node evaluations make relate
  about 2.5 times slower. A production fix could skip `evaluateCollectionNode` once the entries it
  can set are known.

## Related issues

- The TODO at RelateNG.cpp:621 (JTS RelateNG.java:507).
- The area-vertex skip (reported separately) makes the first form worse: after an INTERIOR first
  vertex in the target exterior, later polygons are skipped.
- #948 and JTS #784 / #833 are about *overlay* with overlapping GC polygons, not relate.
- No report of this behaviour was found (libgeos/geos and locationtech/jts issues and PRs, open
  and closed).

---
Found by differential testing against an exact rational oracle (geotruth: https://github.com/abafaboy/geotruth).
