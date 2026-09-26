# Wrong isValid / predicates / overlay for valid geometries with very small (or very large) coordinates: orientation test and segment intersection underflow

*Draft issue for libgeos/geos. Not filed.*

## Summary

When every coordinate of a simple, valid geometry is very small, GEOS returns wrong
results. This happens below about 1e-154 for nearly degenerate inputs, and below about
1.6e-162 for any input. For example:

- a right triangle is reported invalid ("Self-intersection");
- a square with a hole makes `isValid` throw;
- the centre of a square is not `contains`-ed by it;
- two overlapping squares are reported as `touches`;
- intersection and union are wrong.

The same shapes at unit scale give correct results.

The cause is numeric. The products formed inside `CGAlgorithmsDD::orientationIndex`
underflow, so the orientation test reports non-collinear points as COLLINEAR, or as the
opposite side. The DD fallback cannot recover, because DD has the same exponent range as
double.

A second, related problem is in `CGAlgorithmsDD::intersection`, which builds terms
cubic in the coordinates. It underflows or overflows for |coordinates| below about 1e-103
or above about 1e103. `GEOSSegmentIntersection` and overlay then return points that are
not the intersection point. On the large side, the orientation test fails from about
1e153 (nearly degenerate input) or about 1e155 (the squares below).

I could not find a documented range of supported coordinate magnitudes. All inputs here
are finite, normal doubles and OGC-valid. The same behaviour is in JTS.

This was found by differential testing against an exact rational oracle. I understand
these magnitudes are unusual for GIS data, so this may be low priority. If they are
out of scope, a documentation note would still help, since the current failure is
silent.

## Minimal reproduction

GEOS main (`geosop`). The same shapes at unit scale are all correct.

```
$ geosop -a 'LINESTRING (0 0, 1e-200 0)' -b 'POINT (0 1e-200)' orientationIndex
0                                              # expected 1: (0 0),(1e-200 0),(0 1e-200) is a left turn
$ geosop -a 'POLYGON ((0 0, 1e-200 0, 0 1e-200, 0 0))' isValid
false                                          # expected true (a right triangle)
$ geosop -a 'POLYGON ((0 0, 4e-200 0, 4e-200 4e-200, 0 4e-200, 0 0), (1e-200 1e-200, 1e-200 2e-200, 2e-200 2e-200, 2e-200 1e-200, 1e-200 1e-200))' isValid
Run-time exception: IllegalArgumentException: Segment vertex does not intersect ring
$ geosop -a 'POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))' -b 'POINT (1e-200 1e-200)' contains
false                                          # expected true (P is the centre of A)
$ geosop -a 'POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))' -b 'POLYGON ((1e-200 1e-200, 3e-200 1e-200, 3e-200 3e-200, 1e-200 3e-200, 1e-200 1e-200))' relate
FF2F01FF2                                      # expected 212101212
$ geosop -a '<same A>' -b '<same B>' intersection
POLYGON ((1e-200 1e-200, 1e-200 3e-200, 3e-200 3e-200, 3e-200 1e-200, 1e-200 1e-200))   # = B; expected [1e-200,2e-200]^2
$ geosop -a '<same A>' -b '<same B>' union
POLYGON ((0 0, 0 2e-200, 2e-200 2e-200, 2e-200 0, 0 0))                                 # = A; expected the 8-vertex union
```

The full C-API program (`repro.c`, public API only) runs the shapes at unit scale and at
1e-200 and prints expected against actual:

```
cc repro.c $(geos-config --cflags) $(geos-config --clibs) -o repro && ./repro
```

Shapely 2.1.2 / GEOS 3.13.1 (`repro.py`):

```python
from shapely import wkt
T = wkt.loads("POLYGON ((0 0, 1e-200 0, 0 1e-200, 0 0))")
T.is_valid                  # False, explain_validity: "Self-intersection[0 1e-200]"
A = wkt.loads("POLYGON ((0 0, 2e-200 0, 2e-200 2e-200, 0 2e-200, 0 0))")
B = wkt.loads("POLYGON ((1e-200 1e-200, 3e-200 1e-200, 3e-200 3e-200, 1e-200 3e-200, 1e-200 1e-200))")
A.relate(B), A.overlaps(B), A.touches(B)    # ('FF2F01FF2', False, True); expected ('212101212', True, False)
```

## Expected vs actual (GEOS main ae9cdd9, C API, from `output_geos-main-ae9cdd9.txt`)

S = 1e-200. A = [0,2S]², B = [S,3S]², P = (S S), T = triangle (0 0),(S 0),(0 S),
H = [0,4S]² with the square hole [S,2S]².

| call | expected | actual |
|---|---|---|
| `GEOSOrientationIndex((0 0),(S 0),(0 S))` | 1 | **0** |
| `GEOSSegmentIntersection((2S 0)-(2S 2S), (S S)-(3S S))` | 1, (2S S) | **-1** (no intersection) |
| `isValid(T)` | true | **false**, `Self-intersection[0 1e-200]` |
| `isValid(H)` | true | **exception** `Segment vertex does not intersect ring` |
| `contains(A, P)` | true | **false** (prepared `contains`: true) |
| `relate(A, P)` | `0F2FF1FF2` | **`FF20F1FF2`** |
| `relate(A, B)` | `212101212` | **`FF2F01FF2`** |
| `overlaps(A, B)` / `touches(A, B)` | true / false | **false / true** (prepared `overlaps`: false) |
| `intersection(A, B)` | [S,2S]² | **B** |
| `union(A, B)` | 8-vertex L-shaped union | **A** |

With S = 1 (the control), every row is correct.

## How the wrong range depends on scale

Two scans were run.

`scan_scales.c` repeats these checks for S = 10^k, k = -320..307. Results on GEOS main
and 3.15.0 are identical:

| check | wrong for S = 1e<k>, k in |
|---|---|
| orientation, `isValid(T)` | [-320, -162] |
| `isValid(H)` | [-320, -163], [154, 307] |
| `contains(A, P)` | [-320, -162], [155, 307] |
| `relate(A, B)` | [-320, -162], [155, 307], and also k = -116, -104, 105, 126 |
| `intersection` / `union` (even with a 1e-9·S vertex tolerance) | [-320, -103], [103, 307] |

For the triangle T, validity switches between s = 1.6e-162 (valid) and s = 1.5e-162
("Self-intersection"). This is where s·s rounds to zero in double arithmetic:
s < 2^-537.5 ≈ 1.57e-162.

`primitives_scaling.c` multiplies the inputs of the two primitives by exact powers of
two, which cannot change the correct answer:

- **`GEOSOrientationIndex` on near-collinear points.** The triple (-1.6 1.2),
  (-3.2 -1.8), (-6.4 -7.8), as doubles, has exact orientation -1. GEOS returns:
  - -1 at unit scale and down to 2^-510;
  - **+1 (the opposite side) at 2^-514**;
  - 0 from 2^-520 down;
  - 0 from 2^512 up.

  For the well-separated triangle, the answer is wrong from 2^-538 down.
- **`GEOSSegmentIntersection((2 0)-(2 2), (1 1)-(3 1))`, scaled by 2^k.** The exact answer
  is (2 1)·2^k. GEOS returns:
  - the segment endpoint (2 0)·2^k for k in [-537, -359] and for k in [341, 500];
  - "no intersection" from k = -538 down, and at 2^1000.

  With the decimal unit S = 1e-103 or 1e103, it already returns an endpoint: (2S 0).
  At other decimal scales it returns other endpoints, (3S S) or (S S).

In `orientation_random_scaling.py`, I generated 20,000 random near-collinear triples that
GEOS classifies correctly at unit scale and scaled each one exactly by 2^k:
- nothing goes wrong down to 2^-505 or up to 2^507;
- at 2^-515, 15,541 were reported collinear and 1,015 got the opposite sign;
- from 2^-530 down and from 2^600 up, all 20,000 were reported collinear.

## The exact answer

The shapes are a right triangle, a square with a square hole strictly inside it, the
centre point of a square, and two squares that overlap in a quarter of each. All are
OGC-valid, and at unit scale GEOS agrees.

Multiplying all coordinates by a positive factor maps a configuration to a similar one,
so validity, DE-9IM and the overlay results (scaled) do not change. For 1e-200, which is
not a power of two, `exact_check.py` confirms the answers directly with rational
arithmetic:
- 2e-200 == 2·1e-200 exactly;
- the orientation determinant of T is (1e-200)² > 0;
- area(A ∩ B) = (1e-200)² > 0;
- (2S S) is the exact crossing point.

For every case in `cases.jsonl`, two exact implementations give the same predicates: the
hunt's rational oracle (`oracle.jsonl`) and an independent one (`indep.jsonl`). For the
two-squares cases, both report `overlaps`, not `touches`. Both also report every input
valid. The one exception is the square with a hole: the independent implementation does
not decide validity for polygons with holes. For that input, `exact_check.py` uses an
exact OGC validity checker that agreed with GEOS `isValid` on 30,000 random unit-scale
geometries.

The magnitudes involved are ordinary normal doubles: 1e-200 is far above the subnormal
range (DBL_MIN ≈ 2.2e-308). Only the *products* of two coordinates fall out of range.

## Analysis / root cause

References are to GEOS main ae9cdd9.

1. **Orientation filter.** `CGAlgorithmsDD::orientationIndexFilter`
   (`include/geos/algorithm/CGAlgorithmsDD.h:97-111`) computes
   `detleft = (pax-pcx)*(pby-pcy)` and `detright = (pay-pcy)*(pbx-pcx)`. When the
   coordinate differences are below ~1.5e-162, both products round to 0, so `det = 0`
   and `error = 0`. The test `std::abs(det) >= error` (line 108) is then true, and the
   filter returns 0 (collinear) *as a final answer*. The DD path is never reached.

   The error bound is relative ("coefficient as per Ozaki et al"). Relative error bounds
   of this kind are derived assuming no underflow. When the products are subnormal
   (differences below ~1.5e-154), the bound no longer holds, and a wrong non-zero sign
   can pass the filter. That is the "+1 at 2^-514" case above: the filter computes
   `det == error == 4.9e-324` (the smallest subnormal) and returns +1. At unit scale the
   same triple is deferred to DD, which returns the correct -1.
   `diag_filter_emulation.py` re-evaluates the filter's double arithmetic step by step.

2. **DD fallback.** Even when the filter defers, `CGAlgorithmsDD::orientationIndex`
   (`src/algorithm/CGAlgorithmsDD.cpp:69-79`) forms the same products in DD. DD's `hi`
   and `lo` are doubles with the same exponent range, so the products (and, earlier,
   their low-order parts) underflow in the same way.

   On the overflow side, take the near-collinear triple at 2^512. The filter gets
   `detleft = detright = inf` and `det = NaN`, so it defers. The DD products evaluate to
   NaN (`diag_dd_overflow.cpp`, a diagnostic using `geos/math/DD.h`). `OrientationDD`
   (lines 32-44) maps NaN to STRAIGHT, because NaN is neither < 0 nor > 0. Only
   `qx`/`qy` are checked for finiteness (line 58).

3. **Segment intersection point.** `CGAlgorithmsDD::intersection`
   (`src/algorithm/CGAlgorithmsDD.cpp:116-148`) evaluates homogeneous coordinates:
   - `pw` and `qw` are quadratic in the coordinates;
   - `x` and `y` are cubic;
   - `w` is quadratic.

   The cubic terms become subnormal (and inexact) at about |coord| < 2.8e-103, round to
   zero from about 2^-359 in the power-of-two test, and overflow at about
   |coord| > 5.6e102. The resulting point is off the segments.
   `LineIntersector::intersection` (`include/geos/algorithm/LineIntersector.h:549-551`)
   then replaces it with `nearestEndpoint()`. In this test, all four endpoints are at the
   same exact distance S from the other segment, so which endpoint is returned depends on
   rounding. Overlay builds on these points, which is consistent with the wrong
   intersection and union from ~1e-103. The prototype below, which only rescales these
   two functions, removes those overlay errors on the tiny side.

4. **Downstream effects.**
   - `IsValidOp` sees two edges of T as collinear and overlapping ("Self-intersection").
   - `PolygonTopologyAnalyzer::intersectingSegIndex` does not find a node on the ring and
     throws (`src/operation/valid/PolygonTopologyAnalyzer.cpp:191`).
   - Point-in-polygon puts P on the boundary.
   - RelateNG and the overlay inherit the wrong orientations.

**JTS** has the same code and the same results: master 3ea61f8 and 1.20.0, with both
`RelateOp` and `RelateNG` (`Repro.java`, `output_jts-*.txt`). In
`modules/core/src/main/java/org/locationtech/jts/algorithm/CGAlgorithmsDD.java`:
- `orientationIndexFilter` returns `signum(det)` when `detleft == 0` (lines 165-167);
- the DD path is at lines 59-76;
- `intersection()` is at lines 196-220.

One difference: `A.contains(P)` is correct in JTS, but `relate(A, P)` is not.

## A possible direction (prototype, diagnostic only)

`prototype_fix.diff` is not proposed as-is. It changes two places:

- **`orientationIndex`:** when the coordinate differences are outside [2^-400, 2^400],
  it rescales x and y separately by powers of two before running the filter. The sign
  of the determinant is unchanged, and scaling up is exact.
- **`intersection`:** it rescales by a power of two and scales the result back.

With it:
- `repro.c`, `scan_scales.c` (the tiny side and the predicates) and
  `primitives_scaling.c` report 0 wrong results;
- the hunt's 12,000 ordinary cases are unchanged (one area got closer to the exact
  value);
- the exact-oracle "extreme" family changes. It holds valid grid polygon pairs scaled
  by 2^k, about 220-240 cases per exponent. For each k in {-1074, -1070, -1060, -1000,
  -600}, the cases with a wrong predicate or validity result go from 90-113 to 0;
- GEOS's own `ctest` passes 535/535 and `test_geos_unit` passes 3932 (4 skipped, needing
  `--data`).

Some large-scale failures remain (≥ 2^505). These come from other overflows that I did
not investigate.

The prototype puts its range test ahead of the fast filter on every call and was not
benchmarked. One possible production version would keep the fast path unchanged:

- make the filter return FAILURE when its error bound is below the normal range (for
  example, `error < DBL_MIN`-scaled);
- rescale only on the DD path.

That is a suggestion; I have not implemented or measured it.

## Versions

| version | result |
|---|---|
| GEOS main ae9cdd98be4e0bae552b918d4d14c94a9ce99c58 (3.16.0dev, current HEAD at time of testing) | reproduces |
| GEOS 3.15.0 (latest release) | reproduces, identical output |
| GEOS 3.14.1 (Shapely 2.2.0rc1), 3.13.1 (Shapely 2.1.2) | reproduce |
| GEOS 3.11.4 (Shapely 2.0.7) | reproduces; `intersection` and `union` of the two squares return `POLYGON EMPTY` there |
| JTS master 3ea61f8cf2103f454c9cf3962df75fb6ef3ebecd (1.21.0-SNAPSHOT) and 1.20.0 | reproduce |

Platform: Linux x86-64, gcc, Release build.

## Related issues (no duplicate found)

- locationtech/jts#745, "Contains predicate incorrect for Polygon/MultiLineString with
  very large/small coordinates" (closed, WONT FIX). It is about mixing magnitudes (1e7
  with 1e-10) in one predicate, not about uniformly small coordinates.
- libgeos/geos#970 and PR #973: crash on large finite coordinates in the WKT writer,
  fixed so that extreme doubles (5e-324 .. 1.7e308) are handled in I/O.
- locationtech/jts#163 and locationtech/jts#750: DD conversion and orientation precision
  at ordinary scale; not about range.

Searches run (open and closed, GEOS / JTS / Shapely trackers): underflow, subnormal /
denormal, tiny, small coordinates, very small polygon is_valid, overflow coordinates,
extreme coordinates, orientationIndex, CGAlgorithmsDD, robust orientation, "e-200".

## Unrelated observation

The Doxygen comment of `GEOSOrientationIndex` in `capi/geos_c.h.in` (around line 6928)
says it returns -1 for a counter-clockwise (left) turn and 1 for a clockwise turn. The
implementation returns `Orientation::index`, which is 1 for a left turn: A=(0 0),
B=(1 0), P=(0 1) gives 1 (first line of `output_geos-main-ae9cdd9.txt`). I did not find
an existing report of this and can file it separately if that is preferred.

## Files

- `repro.c`: public C API; unit scale and 1e-200; triangle threshold.
- `scan_scales.c`: 1e-320 .. 1e307.
- `primitives_scaling.c`: exact 2^k scaling of `GEOSOrientationIndex` / `GEOSSegmentIntersection`.
- `orientation_random_scaling.py`: 20,000 random near-collinear triples under 2^k scaling
  (ctypes to `GEOSOrientationIndex_r`).
- `repro.py`: Shapely.
- `leads_check.py`: the original box/box and hole-touching-shell leads.
- `Repro.java`, `ScanScales.java`: JTS.
- `exact_check.py`: rational check of every expected answer.
- `diag_filter_emulation.py`, `diag_dd_overflow.cpp`: diagnostics for the root cause.
- `cases.jsonl`, `oracle.jsonl`, `indep.jsonl`, `adapter_results.jsonl`, `compare.txt`:
  differential-testing records.
- `output_*.txt`: captured outputs.
- `prototype_fix.diff`, `output_prototype_regression.txt`.
- `run.sh`: builds and runs everything. Example:
  `GEOS_CONFIG=/path/to/geos-config JTS_JAR=/path/to/jts-core.jar sh run.sh`.
