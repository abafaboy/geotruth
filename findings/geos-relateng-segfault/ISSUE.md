# geos-relateng-segfault: triage result

## Verdict: a new, valid bug (two crash sites, one root pattern). High priority. Not reported upstream yet.

GEOS RelateNG dereferences invalid memory when a GeometryCollection operand contains an
**EMPTY element**. The input is valid under GEOS's own rules: `GEOSisValid` is true, OGC SFS
allows empty members, and GEOS's own XML suite already tests a GC with a `POLYGON EMPTY`
(`tests/xmltester/tests/general/TestRelateGC.xml`, case 1). The crash is a SIGSEGV in the
calling process. There is no exception to catch, so Shapely and other bindings die with it. There
are two independent crash sites:

1. **`AdjacentEdgeLocator` walks the 0-point shell of an empty polygon** (GEOS only). With
   `getSize() == 0`, the loop bound `ring->getSize() - 1` underflows to `SIZE_MAX`
   (`src/operation/relateng/AdjacentEdgeLocator.cpp:67`), and `getAt(0)` reads out of bounds
   (line 68). This path is reached whenever a located point lies on the boundaries of two or
   more polygonal elements of the GC, and it crashes **`intersects`, `within`, `touches`,
   `contains`, `covers`, `relate`, `relatePattern` and the prepared predicates**.
2. **Null `LinearBoundary` in `TopologyComputer::initExteriorEmpty`** (GEOS: SIGSEGV; JTS:
   `NullPointerException`). `RelateGeometry`'s dimension is `Geometry::getDimension()`, which
   counts empty elements, so `GC(POINT, LINESTRING EMPTY)` gets dimension L. Its point locator
   builds a `LinearBoundary` only for non-empty lines, so `lineBoundary` stays null. Against an
   empty operand, `initExteriorEmpty` switches on that dimension (`TopologyComputer.cpp:95`)
   and calls `hasBoundary()` (line 101), which dereferences the null pointer
   (`RelatePointLocator.cpp:70`). Only the full `relate` reaches this path.

The same declared-vs-real dimension mix-up also gives a **wrong matrix without a crash**
(case 3 below, GEOS and JTS). This is the `EMPTY_ELEMENT_DIMENSION` family pinned in
`tests/crosscheck/test_relate_dual.py`, and the same root cause as crash 2.

A 5-line prototype fix, in GEOS and JTS, removes all crashes and wrong answers of this family.
It passes GEOS's full ctest suite (535/535) and JTS's RelateNG unit tests (154/154), and it
changes no other answer in a 25,000-case differential run (see "Prototype fix").

### Facts established

| item | result |
|---|---|
| Upstream heads (`git ls-remote`, 2026-09-26) | unchanged: GEOS main `ae9cdd98b` (2026-09-21), tag 3.15.0 `d0228513a`; JTS master `3ea61f8` (2026-09-23), tag 1.20.0 `6e95fe82`. |
| GEOS main `ae9cdd98b` | crash 1 and crash 2 reproduce (C API `output_geos-main-ae9cdd9.txt`, `geosop` `output_geosop.txt`). Case 3 is wrong. |
| GEOS 3.15.0 `d0228513a` (latest release) | identical to main (`output_geos-3.15.0.txt`, `output_geosop.txt`). |
| GEOS 3.14.1 (Shapely 2.2.0rc1 wheel) | crash 1, crash 2, case 3 wrong (`output_shapely-2.2.0rc1_geos-3.14.1.txt`). |
| GEOS 3.13.1 (Shapely 2.1.2 wheel) | crash 1, crash 2, case 3 wrong (`output_shapely-2.1.2_geos-3.13.1.txt`). |
| GEOS 3.11.4 (Shapely 2.0.7 wheel, old RelateOp) | **no crash**. Case 1 is correct. Case 2 raises `IllegalArgumentException: Operation not supported by GeometryCollection`. Case 3 is already wrong (`output_shapely-2.0.7_geos-3.11.4.txt`). So both crashes are regressions that came with RelateNG (GEOS 3.13). Case 3 is older. |
| JTS master `3ea61f8` and 1.20.0 (RelateNG) | case 1 **correct** (`0FFFFF212`): Java's `int` bound `ring.length - 1 = -1` skips the empty ring. Case 2: **`NullPointerException`** at `RelatePointLocator.java:99`, called from `TopologyComputer.initExteriorEmpty` (`TopologyComputer.java:92`). Case 3 is wrong, the same as GEOS (`output_jts-*.txt`). JTS's default `Geometry.relate` (RelateOp) rejects GC arguments, so JTS users only hit this with `RelateNG` or `-Djts.relate=ng`. |
| Validity | all operands: `GEOSisValid` true, JTS `IsValidOp` true, geotruth `validity.is_valid` true (`output_exact_check.txt`). No coordinates beyond small integers. |
| Exact answers | `geotruth.relate` (arrangement route, strict) and `relate_witness` (independent witness route) agree on all 10 cases in `cases.jsonl`. A third, independent check: GEOS itself on the same point sets with the EMPTY element removed gives the exact matrix in every case (`output_exact_check.txt`). JTS gives the exact answer for case 1. |
| Debug backtraces | `output_backtrace_debug_geos-main-ae9cdd9.txt`, from a `-O0 -g3` build with assertions on. Crash 1 trips `CoordinateSequence::getAt`'s bounds assertion (`i*stride() < m_vect.size()`) with `ring->getSize() == 0` and `getSize() - 1 == 18446744073709551615`. Crash 2 has `lineBoundary == nullptr`, `lines.size() == 0`, `points.size() == 1`, `dimNonEmpty == 1`. |
| Fuzzer population | a GEOS-only rescan of the crosscheck generators (25,000 cases: adversarial seeds 1-5 and 200-203, lattice seeds 1 and 100-103, dense seeds 1 and 500) finds **13 crashes, all in the `adversarial` source**. Classified with the debug build: 9 in `AdjacentEdgeLocator::addSections` (every one has a `POLYGON EMPTY`), 4 in `LinearBoundary::hasBoundary` (a `LINESTRING EMPTY` against an empty operand). No other crash site exists in that population (`scan_crashes.jsonl`, `output_exact_check_scan_crashes.txt`). 11 of the 13 have valid operands. The other 2 (adversarial-201-649, adversarial-2-770) contain a degenerate line and are invalid, but they crash at the same site. On 12 of the 13, GEOS on the EMPTY-stripped input gives the exact matrix. The remaining one, adversarial-2-199, hits the separate `gc-overlapping-polygons` defect once the crash is removed. The lead's "8 crashes" were not saved anywhere in the repo. The two pinned `GEOS_CRASHES` in `tests/crosscheck/test_relate_dual.py` are one of each kind, and the rescan finds no third kind. |

### Minimal inputs (hand-checkable)

**Case 1: crash in `AdjacentEdgeLocator` (GEOS only)**

```
A = POINT (2 1)
B = GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), POLYGON EMPTY)
exact relate(A, B) = 0FFFFF212
```

The two squares share the edge x = 2. RelateNG uses union semantics for GCs (RelateNG.h:64-65),
and an empty polygon adds no points, so B's point set is the rectangle [0,4]x[0,2]. The point
(2,1) is in its interior: II = 0, IB = IE = F. A point has no boundary, so the B row is FFF.
EI = 2, EB = 1, EE = 2. Without the `POLYGON EMPTY`, GEOS returns exactly `0FFFFF212`
(control case 1c).

Variants that also crash (`output_variants_crash1_shapely-2.1.2_geos-3.13.1.txt`, `cases.jsonl`):
- the `POLYGON EMPTY` in any position;
- the `POLYGON EMPTY` nested in a sub-GC;
- the `POLYGON EMPTY` as an `EMPTY` part of a MultiPolygon element;
- a `LINESTRING (1 1, 3 1)` or `POLYGON ((1 0, 3 0, 3 2, 1 2, 1 0))` operand instead of the point;
- two triangles sharing only a vertex, with the point at that vertex.

A `MULTIPOLYGON EMPTY` element does not crash (it has no Polygon children). Neither does a
point on only one polygon boundary (`numBdy == 1`, so `AdjacentEdgeLocator` is not used).

**Case 2: crash on the null `LinearBoundary` (GEOS SIGSEGV, JTS NPE)**

```
A = GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)
B = POINT EMPTY
exact relate(A, B) = FF0FFFFF2
```

A's point set is {(0,0)}, and B is empty. A's interior (dimension 0) lies in B's exterior, so
IE = 0. A has no boundary (a point, and the empty line has no endpoints), so BE = F. B has
nothing, so EI = EB = F, and EE = 2. `relate(POINT (0 0), POINT EMPTY)` gives this in GEOS
(control 2c). It also crashes with `MULTILINESTRING EMPTY`, a nested `GEOMETRYCOLLECTION
(LINESTRING EMPTY)`, a MultiPoint instead of the point, B = `POLYGON EMPTY` or
`GEOMETRYCOLLECTION EMPTY`, and with the operands swapped. The named predicates do not crash
here. RelateNG decides them early for an empty operand. Only `GEOSRelate` /
`Geometry::relate` (and so `shapely.relate`) reaches the crash.

**Case 3: wrong matrix, same cause as case 2 (GEOS and JTS; not a crash; not a regression)**

```
A = GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)
B = POINT (5 5)
exact relate(A, B) = FF1FF00F2      GEOS/JTS: FF2FF10F2
```

A's interior is the open unit segment (dimension 1), and its boundary is two points
(dimension 0). GEOS reports IE = 2 and BE = 1, which is impossible for a segment. It uses the
declared dimension A of the empty polygon when inferring the target's exterior entries for a
point in its exterior. Also `GC(POINT (0 0), POLYGON EMPTY)` vs `POINT EMPTY`: GEOS gives
`FF2FF1FF2`, exact `FF0FFFFF2`. Named predicates are unaffected (`output_variants_crash2_case3_*.txt`; checked: `crosses`,
`overlaps`, `touches` on line/line and multipoint/multipoint variants). They dispatch on
`getDimensionReal()`.

### Root cause (file:line on GEOS main `ae9cdd98b`)

`RelateGeometry` carries two dimensions:
- `getDimension()`: the *declared* dimension, initialised from `Geometry::getDimension()`
  (`RelateGeometry.cpp:59`). For a GC this is the maximum over all elements, **including empty
  ones** (`GeometryCollection::getDimension`, `GeometryCollection.cpp:175-187`).
- `getDimensionReal()` (`RelateGeometry.cpp:160`): the dimension of the non-empty point set.

JTS pins this split: `RelateGeometryTest.testDimension` expects 2 and 1 for
`GC(POLYGON EMPTY, LINESTRING, POINT)`. The element extractors (`RelatePointLocator::
extractElements`, `RelatePointLocator.cpp:78`; `RelateGeometry::analyzeDimensions`,
`RelateGeometry.cpp:103`) skip empty elements, so the locator's structures reflect the *real*
point set. The top-level dispatch uses the real dimension (`RelateNG.cpp:330-334`
`predicate.init(dimA, dimB)`; `TopologyComputer::initExteriorDims`, `TopologyComputer.cpp:50-51`).
Some code paths still use the declared one:

- **Crash 2.** `TopologyComputer::initExteriorEmpty` switches on `getDimension(geomNonEmpty)`
  (`TopologyComputer.cpp:95`, through `TopologyComputer::getDimension`, lines 125-128, which
  returns the declared `RelateGeometry::getDimension()`). The case `Dimension::L` calls
  `hasBoundary()` (line 101), which calls `RelatePointLocator::hasBoundary()` (lines 68-71),
  which returns `lineBoundary->hasBoundary()`. `lineBoundary` is created only `if
  (!lines.empty())` (lines 56-58), and `lines` holds only non-empty LineStrings. The result is
  a null dereference.
- **Case 3.** `RelateNG::computePoint` (`RelateNG.cpp:507`), and likewise `computeLineEnd`
  (564, 571) and `computeAreaVertex` (627), pass `topoComputer.getDimension(!isA)` to
  `DimensionLocation::dimension()` as the dimension to use when the point is in the target's
  exterior. With the declared dimension A, `addPointOnGeometry` adds IE = A and BE = L for a
  target that has no area.
- **Crash 1** is a separate slip in the same "empty element" class.
  `RelatePointLocator::locateOnPolygons` builds an `AdjacentEdgeLocator` over the whole input
  geometry when a point is on two or more polygon boundaries (`RelatePointLocator.cpp:287-291`).
  `AdjacentEdgeLocator::addRings` (`AdjacentEdgeLocator.cpp:113-129`) does not skip empty
  polygons. It adds their 0-point shell to `ringList`, and `addSections` then runs
  `for (std::size_t i = 0; i < ring->getSize() - 1; i++)` (line 67) with an unsigned bound of
  `SIZE_MAX`. The Java original (`AdjacentEdgeLocator.java:59`, `int i < ring.length - 1`)
  loops zero times, so this is a porting bug.

This is related to closed GEOS #1011 (from PostGIS #5640): "covers is incorrect for a LINE
against a GEOMETRYCOLLECTION containing a POLYGON EMPTY". The same declared-vs-real
dimension confusion was fixed there for the predicate dispatch (RelateNG, the
`TestRelateGC.xml` case 1 regression test), but not in `TopologyComputer`.

### Bug or by design?

Bug. The input is valid: `GEOSisValid` is true, and OGC SFS permits empty members of a
collection. RelateNG documents GC support with union semantics (`RelateNG.h:64-65`) and
"robust computation ... invalid geometry topology does not cause failures" (line 62-63).
GEOS's own tests already include a GC with a `POLYGON EMPTY` (TestRelateGC.xml case 1).
Earlier fixes for crashes on empty members of collections in other operations (#1002
PointOnSurface, #1406 GeometryNoder, fixed by PR #1410) show that GEOS treats such crashes as
bugs. No documented limit applies (small integers).

### Upstream search (2026-09-26; nothing matching, open or closed)

- **libgeos/geos issues:**
  - "RelateNG segfault crash empty polygon GeometryCollection";
  - "AdjacentEdgeLocator crash";
  - "relate segmentation fault GEOMETRYCOLLECTION LINESTRING EMPTY LinearBoundary hasBoundary null";
  - "RelateNG" (all 4: #1060, #1147, #1148, #1149, all closed regressions in DE-9IM values);
  - "crash intersects contains GeometryCollection with empty polygon";
  - "GeometryCollection getDimension empty element dimension relate wrong matrix";
  - "GEOSRelate crash GeometryCollection containing empty LineString".
  
  Related but not duplicates:
  - **#1011** (closed): the same empty-element dimension confusion, for `covers`, before RelateNG;
  - **#1406** (closed, PR #1410: `GeometryNoder` crashes on a GC with an empty polygon; the fix touched only `src/noding`);
  - **#1002** (closed: PointOnSurface crash on a collection with an empty linestring);
  - **#1060** (the Relate issue summary: lists #1011, and no crash);
  - #983 (old RelateOp with GCs).
- **libgeos/geos PRs/commits:** "RelateNG empty" matches no PRs. The only matching commit is
  `face0894` ("Fix RelateNG IM for empty-nonempty cases", a port of JTS #1090), which touched
  `addPointOnGeometry` and `addLineEndOnGeometry` but not these paths.
- **locationtech/jts:**
  - issues "RelateNG NullPointerException empty geometry collection", "RelateNG crash exception GeometryCollection empty element", "AdjacentEdgeLocator empty ring";
  - PRs "RelateNG" (#1052, #1055, #1069, #1073, #1089, #1090, #1099, #1200).
  
  None is about empty elements in a non-empty GC. #1064 ("Error in RelateGeometry?") is a
  typo report fixed in 1.20.0.
- **shapely/shapely:** "segfault relate GeometryCollection empty geometry GEOS 3.13" and
  "intersects segfault geometry collection empty polygon point on boundary shared edge".
  The only related report is #2425 (`node` segfault on a GC with an empty polygon; that is
  GEOS #1406, a different operation).
- **Web search:** nothing on RelateNG crashes with empty GC elements. PostGIS #5580 is
  ST_3DIntersects in PostGIS's own code.

### Prototype fix (`prototype_fix.diff`, `jts_prototype_fix.diff`)

```diff
--- a/src/operation/relateng/AdjacentEdgeLocator.cpp
+++ b/src/operation/relateng/AdjacentEdgeLocator.cpp
@@ AdjacentEdgeLocator::addRings(const Geometry* geom)
     if (const Polygon* poly = dynamic_cast<const Polygon*>(geom)) {
+        //-- an empty polygon has no rings to add
+        if (poly->isEmpty())
+            return;
         const LinearRing* shell = poly->getExteriorRing();
--- a/src/operation/relateng/TopologyComputer.cpp
+++ b/src/operation/relateng/TopologyComputer.cpp
@@ TopologyComputer::getDimension(bool isA) const
-    return getGeometry(isA).getDimension();
+    //-- the real dimension: a GeometryCollection's getDimension()
+    //-- also counts its EMPTY elements
+    return getGeometry(isA).getDimensionReal();
```

The second hunk fixes crash 2 and case 3 together. `TopologyComputer::getDimension` is used
only by `initExteriorEmpty`, `isAreaArea` and the four exterior-dimension fallbacks in
`RelateNG.cpp`. For all of them the real dimension is the intended one. The
`getDimensionReal()` value `False` for an empty target never reaches a dimension switch,
because a point is always EXTERIOR to an empty target and each `add*` method returns first.
The same change also treats a zero-length line as a point there, which is what RelateNG.h:66
documents. A first attempt that changed `RelateGeometry::getDimension()` instead broke JTS's
`RelateGeometryTest.testDimension`, which pins the declared dimension, so it was dropped.

Results (`output_prototype_tests.txt`):
- GEOS patched: `ctest` 535/535 (171 XML suites plus 364 unit tests, including all 10
  `relateng` groups).
- The repro gives the exact answers for all six cases
  (`output_prototype_fix_geos-main-ae9cdd9+prototype_fix.txt`).
- Differential run over the 25,000 generated cases (both argument orders), unpatched main vs
  patched:
  - crashes go from 13 to 0;
  - GEOS exceptions: 612, the same cases in both builds;
  - 163 cases change their answer, all of them with an EMPTY element. 162 become exact. The
    last (adversarial-2-199) changes from a crash to the answer GEOS gives on the same input
    without its EMPTY element, which is the separate `gc-overlapping-polygons` defect.
  - **No answer that was exact becomes wrong.**
- JTS patched (the same two hunks in `TopologyComputer.java` and `AdjacentEdgeLocator.java`):
  - relateng JUnit 154/154;
  - XML relate suites with `-Djts.relate=ng`: 1135/1136, the same single pre-existing failure
    as unpatched;
  - Repro exact on all 3 cases.

### Relation to other findings

- `geos-multipolygon-touching-parts-predicates` (ring-touch-node) and
  `geos-near-collinear-predicates` are wrong-answer defects in RelateNG's node topology and
  predicates. This finding is different: a memory-safety crash plus a dimension
  inconsistency, all triggered only by EMPTY elements.
- The `GC_REFLEX` / `gc-adjacent-edge` point-location defect pinned in
  `tests/crosscheck/test_relate_dual.py` is also in `AdjacentEdgeLocator`, but it is a wrong
  location at a reflex vertex, not this crash.
- `EMPTY_ELEMENT_DIMENSION` in the same test file is case 3 of this finding.
- The `corpus/curated/leads.toml` lead **`relateng-empty-operand-type-dimension`**
  (`POINT EMPTY` vs `GEOMETRYCOLLECTION (POLYGON EMPTY, LINESTRING (0 0, 1 1))`: GEOS main
  `FFFFFF212`, exact `FFFFFF102`) is the empty-operand side of the same cause.
  `initExteriorEmpty` switches on the declared dimension A instead of L. The prototype fix
  gives `FFFFFF102` / `FF1FF0FF2` (case `lead-relateng-empty-operand-type-dimension` in
  `cases.jsonl`). This finding subsumes the lead (`supersedes_lead` in `finding.toml`).
- The lead `relateng-gc-polygon-with-exterior-point` has no EMPTY element and is a different
  defect. The prototype fix does not change its answer (`2F2F110F2` before and after).

### Caveats

- GEOS 3.13.0 itself was not run. 3.13.1 is the oldest RelateNG build tested. 3.11.4
  (pre-RelateNG) does not crash.
- PostGIS was not tested. Any GEOS client that passes such a GC to a predicate is exposed. In
  Shapely, `shapely.intersects(point, gc)` kills the interpreter.
- The lead's original "8 crashes" list is not in the repo. This triage regenerated the crash
  population from the tool's generators and found 13, all of the two kinds.

### Files

| file | what |
|---|---|
| `FINAL.md` | maintainer-ready GEOS report |
| `JTS_FINAL.md` | short JTS report (the NPE and case 3) |
| `repro.c` | public C API only. Each call is fork-isolated, with a control per case. Build: `cc -std=c11 repro.c $(geos-config --cflags) $(geos-config --clibs)` |
| `repro.py` | Shapely, subprocess-isolated |
| `Repro.java` | JTS RelateNG (public API) |
| `run.sh` | builds and runs all of the above (`GEOS_CONFIG=`, `JTS_JAR=`) |
| `cases.jsonl` | the minimal cases and variants (plus the `relateng-empty-operand-type-dimension` lead case), as v2 typed-JSON case records with the WKT in `a_wkt`/`b_wkt` and a note |
| `probe_variants.py`, `output_variants_*.txt` | variants and entry points, each call in a fresh interpreter (Shapely 2.1.2) |
| `exact_check.py`, `output_exact_check*.txt` | exact answers: arrangement, witness route, GEOS on the EMPTY-stripped input, validity |
| `scan_crashes.jsonl` | the 13 regenerated crash cases, with their crash site |
| `output_*` | captured outputs per version (see the table above) |
| `output_backtrace_debug_geos-main-ae9cdd9.txt` | debug backtraces and locals |
| `prototype_fix.diff`, `jts_prototype_fix.diff`, `output_prototype_tests.txt` | the prototype fix and its test results |
| `finding.toml` | registry snippet |

Scratch (not needed to reproduce) is under `$GEOTRUTH_BUILD_DIR/triage2/geos-relateng-segfault/`:
the debug build, the patched build, the batch runner `relate_batch.c`, and the 25,000-case dump.
